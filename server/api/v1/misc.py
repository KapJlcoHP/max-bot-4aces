"""Чек-лист, организации, напоминания и семейный доступ."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.db.models import ChecklistItem, FamilyMember, Organization, Reminder, User
from core.schemas import (
    ChecklistAddIn,
    ChecklistItemDto,
    ChecklistOut,
    FamilyAddIn,
    FamilyMemberDto,
    MapConfigDto,
    OrganizationDto,
    ReminderAddIn,
    ReminderDto,
)
from core.time import strict_local_utc, user_local
from core.config import get_settings
from server.deps import PendingUser
from .common import consented_user, current_user, db_session

router = APIRouter()


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
