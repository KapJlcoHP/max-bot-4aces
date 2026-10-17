"""Профиль, согласие и справочники, доступные до согласия."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.models import (
    BpRecord,
    ChecklistItem,
    ExportRequest,
    FamilyMember,
    HealthRecord,
    HealthSetting,
    MedCourse,
    MedIntake,
    NotificationLog,
    Organization,
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)
from core.db.seed import load_catalog, load_regions, load_scenarios, refresh_route_clinic
from core.schemas import ClinicChangeIn, ConsentIn, RegionDto, SettingsIn, SituationDto, UserDto
from server.deps import PendingUser
from .common import (
    apply_diary_settings,
    consented_user,
    current_user,
    db_session,
    validate_diary_settings,
)

router = APIRouter()


def _clinic_conflict():
    raise HTTPException(status_code=409, detail="Профиль изменился. Обновите данные и подтвердите выбор заново")


def _profile_state(db: Session, user: User):
    # Read columns, not a possibly stale ORM identity loaded by authentication.
    return db.query(User.region, User.attached_clinic_id).filter(User.id == user.id).one()


def _validate_clinic(db: Session, clinic_id: int, region: str):
    if clinic_id <= 0 or not region:
        raise HTTPException(status_code=422, detail="Выберите регион и поликлинику")
    clinic = db.get(Organization, clinic_id)
    if clinic is None or clinic.org_type != "Поликлиники":
        raise HTTPException(status_code=422, detail="Поликлиника не найдена")
    if clinic.region != region:
        raise HTTPException(status_code=422, detail="Поликлиника не найдена в выбранном регионе")
    return clinic


def _save_profile(db: Session, user: User, state, values: dict):
    result = db.execute(update(User).where(
        User.id == user.id, User.region == state.region,
        User.attached_clinic_id.is_(None) if state.attached_clinic_id is None
        else User.attached_clinic_id == state.attached_clinic_id,
    ).values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        _clinic_conflict()
    db.refresh(user)
    if "region" in values or "attached_clinic_id" in values:
        refresh_route_clinic(db, user)


@router.post("/me/clinic", response_model=UserDto, responses={409: {"description": "Профиль изменился; обновите данные и подтвердите выбор заново"}})
def change_clinic(body: ClinicChangeIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    if not body.expected_region.strip():
        raise HTTPException(status_code=422, detail="Выберите регион")
    state = _profile_state(db, user)
    if state.region != body.expected_region:
        _clinic_conflict()
    _validate_clinic(db, body.attached_clinic_id, state.region)
    # A repeated successful request is safe, but never replays over a different choice.
    if state.attached_clinic_id != body.attached_clinic_id and state.attached_clinic_id != body.expected_clinic_id:
        _clinic_conflict()
    try:
        _save_profile(db, user, state, {"attached_clinic_id": body.attached_clinic_id})
    except HTTPException as error:
        if error.status_code != 409:
            raise
        current = _profile_state(db, user)
        if current.region != body.expected_region or current.attached_clinic_id != body.attached_clinic_id:
            raise
        # Another window completed this exact operation between SELECT and UPDATE.
        db.refresh(user)
    db.commit()
    db.refresh(user)
    return user


def give_consent_impl(
    body: ConsentIn | None = None,
    user: User | PendingUser = None,
    db: Session | None = None,
    *,
    zone_info_cls=ZoneInfo,
):
    """Создать профиль только при согласии; настройки и профиль фиксируются вместе."""
    if body and body.tz:
        try:
            zone_info_cls(body.tz)
        except Exception as e:
            raise HTTPException(status_code=422, detail="Неизвестный часовой пояс") from e
    known_regions = {r["title"] for r in load_regions()}
    if body and body.region is not None:
        if body.region not in known_regions:
            raise HTTPException(status_code=422, detail="Неизвестный регион")
    diaries = validate_diary_settings(body.diaries) if body and body.diaries is not None else None

    target_region = body.region if body and body.region is not None else user.region
    attached_clinic_id = body.attached_clinic_id if body else None
    if attached_clinic_id is not None:
        clinic = db.query(Organization).filter(
            Organization.id == attached_clinic_id,
            Organization.org_type == "Поликлиники",
            Organization.region == target_region,
        ).first()
        if clinic is None:
            raise HTTPException(status_code=422, detail="Поликлиника не найдена в выбранном регионе")

    if isinstance(user, PendingUser):
        pending = user
        user = User(
            max_user_id=pending.max_user_id,
            first_name=pending.first_name,
            last_name=pending.last_name,
            email=pending.email,
            avatar_url=pending.avatar_url,
            region=pending.region,
            attached_clinic_id=None,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Два окна могли подтвердить согласие одновременно: используем уже созданный профиль.
            db.rollback()
            user = db.query(User).filter(User.max_user_id == pending.max_user_id).first()
            if user is None:
                raise
    state = _profile_state(db, user)
    values = {}
    if body and body.tz:
        values["tz"] = body.tz
    if body and body.region is not None:
        if state.attached_clinic_id is not None and state.region != body.region:
            _clinic_conflict()
        values["region"] = body.region
    if body and "attached_clinic_id" in body.model_fields_set:
        if state.attached_clinic_id is not None and attached_clinic_id != state.attached_clinic_id:
            _clinic_conflict()
        if attached_clinic_id is not None:
            _validate_clinic(db, attached_clinic_id, values.get("region", state.region))
            values["attached_clinic_id"] = attached_clinic_id
    if user.consent_at is None:
        values["consent_at"] = utcnow()
    if values:
        _save_profile(db, user, state, values)
    if diaries is not None:
        apply_diary_settings(db, user.id, diaries)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserDto)
def me(user: User | PendingUser = Depends(current_user)):
    return UserDto.model_validate(user)


@router.post("/me/consent", response_model=UserDto)
def give_consent(
    body: ConsentIn | None = None,
    user: User | PendingUser = Depends(current_user),
    db: Session = Depends(db_session),
):
    return give_consent_impl(body, user, db)


@router.delete("/me/data")
def delete_my_data(user: User | PendingUser = Depends(current_user), db: Session = Depends(db_session)):
    """Стереть аккаунт целиком; при следующем входе профиль создаётся заново."""
    if isinstance(user, PendingUser):
        return {"status": "deleted"}
    route_ids = db.query(Route.id).filter(Route.user_id == user.id)
    db.query(RouteStep).filter(RouteStep.route_id.in_(route_ids)).delete(synchronize_session=False)
    for model, field in (
        (Route, "user_id"),
        (ChecklistItem, "user_id"),
        (Reminder, "user_id"),
        (BpRecord, "user_id"),
        (HealthRecord, "user_id"),
        (HealthSetting, "user_id"),
        (MedIntake, "user_id"),
        (MedCourse, "user_id"),
        (FamilyMember, "owner_id"),
        (NotificationLog, "user_id"),
        (ExportRequest, "user_id"),
    ):
        db.query(model).filter(getattr(model, field) == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


@router.patch("/me/settings", response_model=UserDto)
def update_settings(body: SettingsIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    state = _profile_state(db, user)
    target_region = body.region if body.region is not None else state.region
    values = {}
    if body.region is not None:
        known = {r["title"] for r in load_regions()}
        if body.region not in known:
            raise HTTPException(status_code=422, detail="Неизвестный регион")
    if "attached_clinic_id" in body.model_fields_set:
        if state.attached_clinic_id is not None and body.attached_clinic_id != state.attached_clinic_id:
            _clinic_conflict()
        if body.attached_clinic_id is not None:
            _validate_clinic(db, body.attached_clinic_id, target_region)
            values["attached_clinic_id"] = body.attached_clinic_id
    for field in ("notifications_on", "notify_day_before", "notify_hour_before", "notify_at_deadline", "step_day_before_time", "email"):
        if getattr(body, field) is not None:
            values[field] = getattr(body, field)
    if body.region is not None:
        values["region"] = body.region
        if body.expected_region is not None and (
            body.expected_region != state.region or body.expected_clinic_id != state.attached_clinic_id
        ):
            _clinic_conflict()
        if state.attached_clinic_id is not None:
            current_clinic = db.get(Organization, state.attached_clinic_id)
            if current_clinic is None or current_clinic.org_type != "Поликлиники" or current_clinic.region != body.region:
                if (not body.confirm_clinic_reset or "expected_clinic_id" not in body.model_fields_set
                        or body.expected_clinic_id != state.attached_clinic_id or body.expected_region != state.region):
                    _clinic_conflict()
                values["attached_clinic_id"] = None
    if values:
        _save_profile(db, user, state, values)
    db.commit()
    db.refresh(user)
    return user


@router.get("/regions", response_model=list[RegionDto])
def regions(user: User | PendingUser = Depends(current_user)):
    return [RegionDto(key=r["key"], title=r["title"], pilot=r.get("pilot", False)) for r in load_regions()]


@router.get("/catalog", response_model=list[SituationDto])
def catalog(user: User = Depends(consented_user)):
    return [SituationDto(**s) for s in load_catalog()]


@router.get("/catalog/{key}/steps")
def catalog_steps(key: str, user: User = Depends(consented_user)):
    spec = load_scenarios().get(key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Неизвестная ситуация")
    return [
        {"position": i, "title": s["title"], "has_checklist": s.get("has_checklist", False)}
        for i, s in enumerate(spec["steps"], start=1)
    ]
