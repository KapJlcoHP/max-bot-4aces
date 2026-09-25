"""REST API v1 для мини-апа. Аутентификация — подписанный initData в заголовке X-Max-Init-Data."""

from datetime import datetime, time as dtime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from core.db.models import (
    BpRecord,
    ChecklistItem,
    FamilyMember,
    Organization,
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)
from core.db.seed import build_route_for, load_catalog
from core.schemas import (
    BpAddIn,
    BpRecordDto,
    ChecklistAddIn,
    ChecklistItemDto,
    ChecklistOut,
    CompleteStepIn,
    CompleteStepOut,
    FamilyAddIn,
    FamilyMemberDto,
    OrganizationDto,
    ReminderDto,
    RouteDto,
    SettingsIn,
    SituationDto,
    StepDto,
    UserDto,
)
from server.deps import AuthError, get_or_create_user
from core.db.session import SessionLocal

router = APIRouter(prefix="/api/v1")


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    try:
        return get_or_create_user(db, request.headers.get("X-Max-Init-Data"))
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


def route_dto(route: Route) -> RouteDto:
    steps = [StepDto.model_validate(s) for s in route.steps]
    return RouteDto(
        id=route.id,
        situation_key=route.situation_key,
        title=route.title,
        subtitle=route.subtitle,
        active=route.active,
        total_steps=len(steps),
        done_steps=sum(1 for s in steps if s.status == "done"),
        steps=steps,
    )


# ---------- профиль ----------

@router.get("/me", response_model=UserDto)
def me(user: User = Depends(current_user)):
    return user


@router.patch("/me/settings", response_model=UserDto)
def update_settings(body: SettingsIn, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if body.notifications_on is not None:
        user.notifications_on = body.notifications_on
    if body.email is not None:
        user.email = body.email
    db.commit()
    db.refresh(user)
    return user


# ---------- каталог ситуаций ----------

@router.get("/catalog", response_model=list[SituationDto])
def catalog(user: User = Depends(current_user)):
    return [SituationDto(**s) for s in load_catalog()]


# ---------- маршрут ----------

def _get_active_route(db: Session, user_id: int) -> Route | None:
    return db.query(Route).filter(Route.user_id == user_id, Route.active.is_(True)).first()


@router.get("/route", response_model=RouteDto | None)
def get_route(user: User = Depends(current_user), db: Session = Depends(db_session)):
    route = _get_active_route(db, user.id)
    return route_dto(route) if route else None


@router.post("/route/start", response_model=RouteDto)
def start_route(body: dict, user: User = Depends(current_user), db: Session = Depends(db_session)):
    key = (body or {}).get("situation_key", "")
    if key not in {s["key"] for s in load_catalog()}:
        raise HTTPException(status_code=404, detail="Неизвестная ситуация")
    return route_dto(build_route_for(db, user, key))


@router.post("/route/steps/{step_id}/complete", response_model=CompleteStepOut)
def complete_step(step_id: int, body: CompleteStepIn | None = None, user: User = Depends(current_user), db: Session = Depends(db_session)):
    route = _get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise HTTPException(status_code=404, detail="Шаг не найден")
    if step.status == "done":
        raise HTTPException(status_code=409, detail="Шаг уже выполнен")

    step.status = "done"
    step.completed_at = utcnow()
    step.note = (body.note if body else None) or None
    if body and body.date:
        step.completed_at = datetime.combine(body.date, dtime(12, 0))

    next_step = (
        db.query(RouteStep)
        .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
        .order_by(RouteStep.position)
        .first()
    )
    if next_step is not None:
        next_step.status = "current"
    db.commit()

    return CompleteStepOut(
        step=StepDto.model_validate(step),
        route=route_dto(route),
        next_step=StepDto.model_validate(next_step) if next_step else None,
    )


# ---------- чек-лист ----------

@router.get("/checklist", response_model=ChecklistOut)
def checklist(user: User = Depends(current_user), db: Session = Depends(db_session)):
    items = db.query(ChecklistItem).filter(ChecklistItem.user_id == user.id).order_by(ChecklistItem.position, ChecklistItem.id).all()
    return ChecklistOut(
        items=[ChecklistItemDto.model_validate(i) for i in items],
        collected=sum(1 for i in items if i.collected),
        total=len(items),
    )


@router.post("/checklist/{item_id}/toggle", response_model=ChecklistItemDto)
def toggle_checklist_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id, ChecklistItem.user_id == user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Пункт не найден")
    item.collected = not item.collected
    db.commit()
    return item


@router.post("/checklist", response_model=ChecklistItemDto)
def add_checklist_item(body: ChecklistAddIn, user: User = Depends(current_user), db: Session = Depends(db_session)):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    item = ChecklistItem(user_id=user.id, title=title, position=0)
    db.add(item)
    db.commit()
    return item


# ---------- организации (демо-данные) ----------

@router.get("/orgs", response_model=list[OrganizationDto])
def orgs(
    q: str = Query(default=""),
    org_type: str = Query(default=""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    query = db.query(Organization)
    if org_type and org_type != "Все":
        query = query.filter(Organization.org_type == org_type)
    if q:
        query = query.filter(Organization.title.ilike(f"%{q}%"))
    return [OrganizationDto.model_validate(o) for o in query.all()]


@router.get("/orgs/{org_id}", response_model=OrganizationDto)
def org_detail(org_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    return OrganizationDto.model_validate(org)


# ---------- напоминания ----------

@router.get("/reminders", response_model=list[ReminderDto])
def reminders(user: User = Depends(current_user), db: Session = Depends(db_session)):
    rows = db.query(Reminder).filter(Reminder.user_id == user.id).order_by(Reminder.at).all()
    return [ReminderDto.model_validate(r) for r in rows]


@router.post("/reminders/{reminder_id}/toggle", response_model=ReminderDto)
def toggle_reminder(reminder_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    row = db.query(Reminder).filter(Reminder.id == reminder_id, Reminder.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    row.enabled = not row.enabled
    db.commit()
    return row


@router.post("/reminders", response_model=ReminderDto)
def add_reminder(body: dict, user: User = Depends(current_user), db: Session = Depends(db_session)):
    title = str((body or {}).get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    at = utcnow() + timedelta(days=1)
    row = Reminder(user_id=user.id, title=title, place=str((body or {}).get("place", "") or ""), at=at)
    db.add(row)
    db.commit()
    return row


# ---------- дневник здоровья ----------

@router.get("/health/records", response_model=list[BpRecordDto])
def bp_records(user: User = Depends(current_user), db: Session = Depends(db_session)):
    rows = db.query(BpRecord).filter(BpRecord.user_id == user.id).order_by(BpRecord.at.desc()).all()
    return [BpRecordDto.model_validate(r) for r in rows]


@router.post("/health/records", response_model=BpRecordDto)
def add_bp_record(body: BpAddIn, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if not (70 <= body.systolic <= 250 and 40 <= body.diastolic <= 150 and 30 <= body.pulse <= 220):
        raise HTTPException(status_code=422, detail="Показатели вне допустимого диапазона")
    if body.diastolic >= body.systolic:
        raise HTTPException(status_code=422, detail="Диастолическое давление не может быть выше систолического")
    row = BpRecord(user_id=user.id, at=utcnow(), systolic=body.systolic, diastolic=body.diastolic, pulse=body.pulse)
    db.add(row)
    db.commit()
    return row


# ---------- семейный доступ (демо) ----------

@router.get("/family", response_model=list[FamilyMemberDto])
def family(user: User = Depends(current_user), db: Session = Depends(db_session)):
    rows = db.query(FamilyMember).filter(FamilyMember.owner_id == user.id).all()
    return [FamilyMemberDto.model_validate(r) for r in rows]


@router.post("/family", response_model=FamilyMemberDto)
def add_family_member(body: FamilyAddIn, user: User = Depends(current_user), db: Session = Depends(db_session)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Имя не может быть пустым")
    row = FamilyMember(owner_id=user.id, name=name, role=body.role.strip() or "Родственник", color="blue")
    db.add(row)
    db.commit()
    return row
