"""Чек-лист, организации, напоминания и read-only доступ помощника."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.db.models import (
    ChecklistItem,
    FamilyAccess,
    FamilyMember,
    HealthRecord,
    HealthSetting,
    MedCourse,
    MedIntake,
    Organization,
    Reminder,
    Route,
    User,
    utcnow,
)
from core.diary_settings import DIARIES, diary_settings
from core.schemas import (
    ChecklistAddIn,
    ChecklistItemDto,
    ChecklistOut,
    FamilyAcceptIn,
    FamilyAccessDto,
    FamilyAddIn,
    FamilyDiaryStatusDto,
    FamilyInviteIn,
    FamilyInviteOut,
    FamilyMemberDto,
    FamilyMedicationStatusDto,
    FamilyRouteSnapshotDto,
    FamilySnapshotDto,
    FamilyStepSnapshotDto,
    MapConfigDto,
    OrganizationDto,
    ReminderAddIn,
    ReminderDto,
)
from core.services import user_today
from core.time import strict_local_utc, user_local
from core.config import get_settings
from server.deps import PendingUser
from .common import consented_user, current_user, db_session

router = APIRouter()

FAMILY_SCOPES = ["route", "appointments", "diary_status", "medication_status"]
DIARY_LABELS = {"bp": "Давление", "weight": "Вес", "sugar": "Сахар", "mood": "Самочувствие"}


def _family_name(user: User | None) -> str | None:
    if user is None:
        return None
    return " ".join(part for part in (user.first_name, user.last_name) if part).strip() or "Пользователь"


def _family_access_dto(db: Session, access: FamilyAccess) -> FamilyAccessDto:
    owner = db.get(User, access.owner_id)
    viewer = db.get(User, access.viewer_id) if access.viewer_id is not None else None
    return FamilyAccessDto(
        id=access.id,
        status=access.status,
        label=access.label,
        owner_name=_family_name(owner) or "Пользователь",
        viewer_name=_family_name(viewer),
        scopes=list(access.scopes or []),
        created_at=access.created_at,
        accepted_at=access.accepted_at,
        expires_at=access.expires_at,
        revoked_at=access.revoked_at,
    )


def _normalise_family_code(code: str) -> str:
    return "".join(code.upper().split()).replace("-", "")


def _family_code_hash(code: str) -> str:
    return hashlib.sha256(_normalise_family_code(code).encode("ascii")).hexdigest()


def _active_family_access(db: Session, access_id: int, viewer: User) -> FamilyAccess:
    access = db.query(FamilyAccess).filter(
        FamilyAccess.id == access_id,
        FamilyAccess.viewer_id == viewer.id,
    ).first()
    if access is None:
        raise HTTPException(status_code=404, detail="Доступ не найден")
    if access.status != "active" or access.revoked_at is not None:
        raise HTTPException(status_code=403, detail="Доступ отозван")
    if access.expires_at <= utcnow():
        access.status = "expired"
        db.commit()
        raise HTTPException(status_code=403, detail="Срок доступа истёк")
    return access


@router.get("/checklist", response_model=ChecklistOut)
def checklist(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    items = db.query(ChecklistItem).filter(
        ChecklistItem.user_id == user.id
    ).order_by(ChecklistItem.position, ChecklistItem.id).all()
    return ChecklistOut(
        items=[ChecklistItemDto.model_validate(i) for i in items],
        collected=sum(1 for i in items if i.collected),
        total=len(items),
    )


@router.post("/checklist/{item_id}/toggle", response_model=ChecklistItemDto)
def toggle_checklist_item(item_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    item = db.query(ChecklistItem).filter(
        ChecklistItem.id == item_id, ChecklistItem.user_id == user.id
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Пункт не найден")
    item.collected = not item.collected
    db.commit()
    return item


@router.post("/checklist", response_model=ChecklistItemDto)
def add_checklist_item(body: ChecklistAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    item = ChecklistItem(user_id=user.id, title=title, position=0)
    db.add(item)
    db.commit()
    return item


@router.get("/orgs", response_model=list[OrganizationDto])
def orgs(
    q: str = Query(default=""),
    org_type: str = Query(default=""),
    region: str | None = Query(default=None, description="Не передан — регион профиля; пустая строка или «Все» — все регионы"),
    user: User | PendingUser = Depends(current_user),
    db: Session = Depends(db_session),
):
    # При прямом вызове старых unit-тестов FastAPI не успевает развернуть Query.
    q = q if isinstance(q, str) else ""
    org_type = org_type if isinstance(org_type, str) else ""
    region = region.strip() if isinstance(region, str) else None
    query = db.query(Organization)
    selected_region = user.region if region is None else ("" if region == "Все" else region)
    if selected_region:
        query = query.filter(Organization.region == selected_region)
    if org_type and org_type != "Все":
        query = query.filter(Organization.org_type == org_type)
    # The small reference catalog is searched literally in Python: SQLite's
    # lower/ilike only folds ASCII, so Cyrillic searches otherwise miss matches.
    # This also keeps '%' and '_' from becoming unexpected wildcard filters.
    needle = q.strip().casefold()
    rows = query.order_by(Organization.id).all()
    return [OrganizationDto.model_validate(o) for o in rows
            if not needle or needle in o.title.casefold() or needle in o.address.casefold()]


@router.get("/maps/config", response_model=MapConfigDto)
def maps_config():
    """Публичная конфигурация клиентской части Яндекс.Карт."""
    api_key = getattr(get_settings(), "yandex_maps_api_key", "")
    return MapConfigDto(enabled=bool(api_key), api_key=api_key)


@router.get("/orgs/{org_id}", response_model=OrganizationDto)
def org_detail(org_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    return OrganizationDto.model_validate(org)


def _reminder_dto(row: Reminder, user: User) -> ReminderDto:
    dto = ReminderDto.model_validate(row)
    dto.at = user_local(row.at, user.tz)
    if row.done_at is not None:
        dto.done_at = user_local(row.done_at, user.tz)
    return dto


@router.get("/reminders", response_model=list[ReminderDto])
def reminders(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    rows = db.query(Reminder).filter(
        Reminder.user_id == user.id, Reminder.done_at.is_(None)
    ).order_by(Reminder.at).all()
    return [_reminder_dto(r, user) for r in rows]


@router.post("/reminders/{reminder_id}/toggle", response_model=ReminderDto)
def toggle_reminder(reminder_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    row = db.query(Reminder).filter(
        Reminder.id == reminder_id, Reminder.user_id == user.id
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    row.enabled = not row.enabled
    db.commit()
    return _reminder_dto(row, user)


@router.post("/reminders", response_model=ReminderDto)
def add_reminder(body: ReminderAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    try:
        # A naive datetime is a wall-clock value in the profile zone; an
        # explicit offset remains the instant supplied by the client.  Reject
        # DST gaps/folds rather than silently choosing a different reminder.
        at = strict_local_utc(body.at, user.tz)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = Reminder(
        user_id=user.id,
        title=title,
        place=body.place or "",
        at=at,
    )
    db.add(row)
    db.commit()
    return _reminder_dto(row, user)


@router.get("/family/access", response_model=list[FamilyAccessDto])
def family_access_list(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Доступы, которыми владеет текущий пользователь."""
    rows = db.query(FamilyAccess).filter(FamilyAccess.owner_id == user.id).order_by(FamilyAccess.id.desc()).all()
    now = utcnow()
    changed = False
    for row in rows:
        if row.status == "pending" and row.expires_at <= now:
            row.status = "expired"
            changed = True
    if changed:
        db.commit()
    return [_family_access_dto(db, row) for row in rows]


@router.post("/family/access/invite", response_model=FamilyInviteOut)
def create_family_invitation(
    body: FamilyInviteIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    """Создать одноразовый код для read-only помощника."""
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Укажите имя помощника")
    active_count = db.query(FamilyAccess).filter(
        FamilyAccess.owner_id == user.id,
        FamilyAccess.status.in_(["pending", "active"]),
    ).count()
    if active_count >= 5:
        raise HTTPException(status_code=409, detail="Можно создать не более пяти активных доступов")
    code = secrets.token_hex(6).upper()
    # Читаемый код показывается владельцу один раз, в БД сохраняется только hash.
    display_code = f"{code[:4]}-{code[4:8]}-{code[8:]}"
    access = FamilyAccess(
        owner_id=user.id,
        label=label,
        invite_hash=_family_code_hash(display_code),
        status="pending",
        scopes=FAMILY_SCOPES,
        expires_at=utcnow() + timedelta(days=body.expires_days),
    )
    db.add(access)
    db.commit()
    db.refresh(access)
    return FamilyInviteOut(access=_family_access_dto(db, access), code=display_code)


@router.post("/family/access/accept", response_model=FamilyAccessDto)
def accept_family_invitation(
    body: FamilyAcceptIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    code = _normalise_family_code(body.code)
    if len(code) != 12 or not all(ch in "0123456789ABCDEF" for ch in code):
        raise HTTPException(status_code=422, detail="Код приглашения должен иметь формат XXXX-XXXX-XXXX")
    access = db.query(FamilyAccess).filter(FamilyAccess.invite_hash == _family_code_hash(code)).first()
    if access is None or access.status != "pending":
        raise HTTPException(status_code=404, detail="Приглашение не найдено или уже использовано")
    if access.expires_at <= utcnow():
        access.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Срок приглашения истёк")
    if access.owner_id == user.id:
        raise HTTPException(status_code=422, detail="Нельзя принять собственное приглашение")
    existing = db.query(FamilyAccess).filter(
        FamilyAccess.owner_id == access.owner_id,
        FamilyAccess.viewer_id == user.id,
        FamilyAccess.status == "active",
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="У вас уже есть доступ к этому маршруту")
    access.viewer_id = user.id
    access.status = "active"
    access.accepted_at = utcnow()
    access.invite_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    db.commit()
    db.refresh(access)
    return _family_access_dto(db, access)


@router.delete("/family/access/{access_id}", response_model=FamilyAccessDto)
def revoke_family_access(
    access_id: int,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    access = db.query(FamilyAccess).filter(
        FamilyAccess.id == access_id,
        FamilyAccess.owner_id == user.id,
    ).first()
    if access is None:
        raise HTTPException(status_code=404, detail="Доступ не найден")
    access.status = "revoked"
    access.revoked_at = utcnow()
    db.commit()
    return _family_access_dto(db, access)


@router.get("/family/observed", response_model=list[FamilyAccessDto])
def family_observed(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Активные read-only доступы текущего пользователя."""
    rows = db.query(FamilyAccess).filter(
        FamilyAccess.viewer_id == user.id,
        FamilyAccess.status == "active",
    ).order_by(FamilyAccess.id.desc()).all()
    return [_family_access_dto(db, row) for row in rows if row.expires_at > utcnow()]


@router.get("/family/observed/{access_id}", response_model=FamilySnapshotDto)
def family_snapshot(
    access_id: int,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    """Безопасная агрегированная витрина маршрута: без заметок и сырых измерений."""
    access = _active_family_access(db, access_id, user)
    owner = db.get(User, access.owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Владелец маршрута не найден")
    route = db.query(Route).filter(Route.user_id == owner.id, Route.active.is_(True)).first()
    route_snapshot = None
    if route is not None:
        steps = [FamilyStepSnapshotDto(
            id=step.id,
            position=step.position,
            title=step.title,
            kind=step.kind,
            status=step.status,
            appointment_date=step.appointment_date,
            deadline=step.deadline,
            deadline_time=step.deadline_time,
            place=step.place,
            # Route timestamps are stored as UTC-naive values.  The family
            # screen formats an API timestamp as a local wall-clock value,
            # so convert it to the owner's city timezone just like the
            # regular reminders/diary endpoints do.
            completed_at=user_local(step.completed_at, owner.tz) if step.completed_at is not None else None,
        ) for step in route.steps]
        route_snapshot = FamilyRouteSnapshotDto(
            title=route.title,
            subtitle=route.subtitle,
            active=route.active,
            total_steps=len(steps),
            done_steps=sum(1 for step in steps if step.status == "done"),
            steps=steps,
        )

    today = user_today(owner)
    settings = diary_settings(db, owner.id)
    diary_rows: list[FamilyDiaryStatusDto] = []
    for diary in DIARIES:
        setting = settings[diary]
        record = db.query(HealthRecord).filter(
            HealthRecord.user_id == owner.id,
            HealthRecord.type == diary,
        ).order_by(HealthRecord.at.desc()).first()
        last_record_at = user_local(record.at, owner.tz) if record is not None else None
        diary_rows.append(FamilyDiaryStatusDto(
            diary=diary,
            label=DIARY_LABELS.get(diary, diary),
            enabled=setting.enabled,
            filled_today=bool(last_record_at and last_record_at.date() == today),
            last_record_at=last_record_at,
        ))

    courses = db.query(MedCourse).filter(MedCourse.user_id == owner.id, MedCourse.enabled.is_(True)).all()
    active_courses = [course for course in courses if course.until is None or course.until >= today]
    planned_today = sum(len(course.times or []) for course in active_courses)
    course_ids = {course.id for course in active_courses}
    intakes = db.query(MedIntake).filter(
        MedIntake.user_id == owner.id,
        MedIntake.day == today,
        MedIntake.course_id.in_(course_ids) if course_ids else False,
    ).all() if course_ids else []
    taken_today = sum(1 for intake in intakes if intake.taken_at is not None)
    return FamilySnapshotDto(
        access_id=access.id,
        owner_name=_family_name(owner) or "Пользователь",
        generated_at=user_local(utcnow(), owner.tz),
        route=route_snapshot,
        diaries=diary_rows,
        medication=FamilyMedicationStatusDto(
            active_courses=len(active_courses),
            planned_today=planned_today,
            taken_today=taken_today,
        ),
    )


@router.get("/family", response_model=list[FamilyMemberDto])
def family(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    rows = db.query(FamilyMember).filter(FamilyMember.owner_id == user.id).all()
    return [FamilyMemberDto.model_validate(r) for r in rows]


@router.post("/family", response_model=FamilyMemberDto)
def add_family_member(body: FamilyAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Имя не может быть пустым")
    row = FamilyMember(owner_id=user.id, name=name, role=body.role.strip() or "Родственник", color="blue")
    db.add(row)
    db.commit()
    return row
