"""Профиль, согласие и справочники, доступные до согласия."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
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
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)
from core.db.seed import load_catalog, load_regions, load_scenarios
from core.schemas import ConsentIn, RegionDto, SettingsIn, SituationDto, UserDto
from server.deps import PendingUser
from .common import (
    apply_diary_settings,
    consented_user,
    current_user,
    db_session,
    validate_diary_settings,
)

router = APIRouter()


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
    if body and body.region is not None:
        if body.region not in {r["title"] for r in load_regions()}:
            raise HTTPException(status_code=422, detail="Неизвестный регион")
    diaries = validate_diary_settings(body.diaries) if body and body.diaries is not None else None

    if isinstance(user, PendingUser):
        pending = user
        user = User(
            max_user_id=pending.max_user_id,
            first_name=pending.first_name,
            last_name=pending.last_name,
            email=pending.email,
            avatar_url=pending.avatar_url,
            region=pending.region,
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
    if body and body.tz:
        user.tz = body.tz
    if body and body.region is not None:
        user.region = body.region
    if user.consent_at is None:
        user.consent_at = utcnow()
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
    if body.notifications_on is not None:
        user.notifications_on = body.notifications_on
    if body.email is not None:
        user.email = body.email
    if body.region is not None:
        known = {r["title"] for r in load_regions()}
        if body.region not in known:
            raise HTTPException(status_code=422, detail="Неизвестный регион")
        user.region = body.region
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
