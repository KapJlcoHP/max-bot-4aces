"""Профиль, согласие и справочники, доступные до согласия."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.db.models import (
    BpRecord,
    ChecklistItem,
    ExportRequest,
    FamilyAccess,
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
from core.location import city_for_location, cities_for_region
from core.schemas import CityDto, ClinicChangeIn, ConsentIn, RegionDto, SettingsIn, SituationDto, TemplateStepDto, UserDto
from core.time import move_wall_time
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
    return db.query(User.region, User.city, User.tz, User.attached_clinic_id).filter(User.id == user.id).one()


def _reschedule_future_notification_moments(
    db: Session, user_id: int, old_tz: str | None, new_tz: str | None,
) -> None:
    """Keep future notification walls stable when a city changes.

    Reminder/step custom moments are persisted as UTC instants.  Existing
    future notifications are user-facing wall-clock choices, so move those
    moments to the new server-derived zone.  Past, completed and historical
    rows are deliberately left untouched.
    """
    if old_tz == new_tz:
        return
    now = utcnow()
    reminders = db.query(Reminder).filter(
        Reminder.user_id == user_id,
        Reminder.done_at.is_(None),
        Reminder.at >= now,
    ).all()
    for reminder in reminders:
        try:
            reminder.at = move_wall_time(reminder.at, old_tz, new_tz)
        except ValueError:
            # A future wall time that becomes a DST gap/fold is not silently
            # invented. Keep the stored instant and let the user edit it.
            continue

    future_steps = (
        db.query(RouteStep)
        .join(Route, Route.id == RouteStep.route_id)
        .filter(
            Route.user_id == user_id,
            Route.active.is_(True),
            RouteStep.status != "done",
            RouteStep.reminder_at.is_not(None),
            RouteStep.reminder_at >= now,
        )
        .all()
    )
    for step in future_steps:
        try:
            step.reminder_at = move_wall_time(step.reminder_at, old_tz, new_tz)
        except ValueError:
            continue


def _validate_location(city: str | None, region: str | None):
    """Validate the user-facing city/region pair and return its internal zone."""
    if region is not None and region not in {item["title"] for item in load_regions()}:
        raise HTTPException(status_code=422, detail="Неизвестный регион")
    if city is None:
        return None
    city = city.strip()
    if not city or not region:
        raise HTTPException(status_code=422, detail="Выберите город и регион")
    region_item = next((item for item in load_regions() if item["title"] == region), None)
    if not region_item or not region_item.get("pilot", False):
        raise HTTPException(status_code=422, detail="Город доступен только в пилотном регионе")
    item = city_for_location(city, region)
    if item is None:
        raise HTTPException(status_code=422, detail="Выберите город из справочника выбранного региона")
    return item


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
    conditions = [
        User.id == user.id,
        User.region == state.region,
        User.attached_clinic_id.is_(None) if state.attached_clinic_id is None
        else User.attached_clinic_id == state.attached_clinic_id,
    ]
    location_change = "city" in values or "tz" in values
    state_tz = getattr(state, "tz", getattr(user, "tz", None))
    if location_change:
        conditions.extend([
            User.city.is_(None) if state.city is None else User.city == state.city,
            User.tz == state_tz,
        ])
    result = db.execute(update(User).where(*conditions).values(**values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        _clinic_conflict()
    if location_change:
        _reschedule_future_notification_moments(db, user.id, state_tz, values.get("tz", state_tz))
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
    target_region = body.region if body and body.region is not None else user.region
    target_city = body.city if body and body.city is not None else getattr(user, "city", None)
    if body and body.region is not None and body.region not in {item["title"] for item in load_regions()}:
        raise HTTPException(status_code=422, detail="Неизвестный регион")
    location = _validate_location(target_city, target_region) if body and body.city is not None else None
    diaries = validate_diary_settings(body.diaries) if body and body.diaries is not None else None

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
            city=pending.city,
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
    if body and body.city is not None:
        values["city"] = location["title"]
        values["tz"] = location["tz"]
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
    db.query(FamilyAccess).filter(
        or_(FamilyAccess.owner_id == user.id, FamilyAccess.viewer_id == user.id)
    ).delete(synchronize_session=False)
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
    location = _validate_location(body.city, target_region) if body.city is not None else None
    if body.region is not None and body.region not in {r["title"] for r in load_regions()}:
        raise HTTPException(status_code=422, detail="Неизвестный регион")
    if body.city is not None:
        values["city"] = location["title"]
        values["tz"] = location["tz"]
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
        if body.city is None:
            # A region change cannot silently retain a city from another
            # region. The UI may supply a new city in the same request; when
            # it does not, clear the old value and let the user choose one.
            if state.city:
                values["city"] = None
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
    return [RegionDto(
        key=r["key"], title=r["title"], pilot=r.get("pilot", False),
        cities=[CityDto(key=c["key"], title=c["title"], region=c["region"]) for c in cities_for_region(r["title"])],
    ) for r in load_regions()]


@router.get("/catalog", response_model=list[SituationDto])
def catalog(user: User = Depends(consented_user)):
    return [SituationDto(**s) for s in load_catalog()]


@router.get("/catalog/{key}/steps", response_model=list[TemplateStepDto])
def catalog_steps(key: str, user: User = Depends(consented_user)):
    spec = load_scenarios().get(key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Неизвестная ситуация")
    return [
        {"position": i, "title": s["title"], "has_checklist": s.get("has_checklist", False),
         "key": s.get("key"), "kind": s.get("kind", "unknown"),
         "booking_target_key": s.get("booking_target_key"), "description": s.get("description", "")}
        for i, s in enumerate(spec["steps"], start=1)
    ]
