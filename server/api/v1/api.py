"""REST API v1 для мини-апа. Аутентификация — подписанный initData в заголовке X-Max-Init-Data.

Персональные данные отдаём только после согласия на обработку (152-ФЗ): без consent_at
дата-эндпоинты отвечают 403 consent_required, фронт показывает онбординг.
"""

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from core.db.models import (
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
from core.db.seed import build_route_for, load_catalog, load_regions, load_scenarios
from core.schemas import (
    ChecklistAddIn,
    ChecklistItemDto,
    ChecklistOut,
    CompleteStepIn,
    CompleteStepOut,
    ConsentIn,
    FamilyAddIn,
    FamilyMemberDto,
    HealthAddIn,
    HealthRecordDto,
    HealthReportOut,
    HealthSettingDto,
    HealthSettingsIn,
    HealthSettingsOut,
    MedAddIn,
    MedCourseDto,
    MedSlotDto,
    MedsOut,
    OrganizationDto,
    ReportMedsRow,
    ReportNote,
    ReminderDto,
    RouteDto,
    RegionDto,
    RouteStartIn,
    SettingsIn,
    SituationDto,
    StepAddIn,
    StepDto,
    StepUpdateIn,
    UserDto,
)
from server.deps import AuthError, get_or_create_user
from server.health_pdf import build_health_pdf
from core.db.session import SessionLocal
from core.services import (
    ServiceError,
    add_health_record as create_health_record,
    complete_route_step,
    take_med,
    uncomplete_route_step,
    user_today,
)

router = APIRouter(prefix="/api/v1")

HEALTH_TYPES = {"bp", "weight", "sugar", "mood"}
DEFAULT_DIARIES = [("bp", True), ("weight", True), ("sugar", False), ("mood", True)]


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


def consented_user(user: User = Depends(current_user)) -> User:
    """Данные пользователя отдаём только после согласия на обработку (152-ФЗ)."""
    if user.consent_at is None:
        raise HTTPException(status_code=403, detail="consent_required")
    return user


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


@router.post("/me/consent", response_model=UserDto)
def give_consent(body: ConsentIn | None = None, user: User = Depends(current_user), db: Session = Depends(db_session)):
    """Фиксируем согласие на обработку персональных данных (+ часовой пояс с телефона)."""
    if user.consent_at is None:
        user.consent_at = utcnow()
    if body and body.tz:
        try:
            ZoneInfo(body.tz)
            user.tz = body.tz
        except Exception:
            pass  # незнакомую зону не сохраняем — остаётся дефолт
    db.commit()
    db.refresh(user)
    return user


@router.delete("/me/data")
def delete_my_data(user: User = Depends(current_user), db: Session = Depends(db_session)):
    """Право на удаление (152-ФЗ, ст. 21): стираем аккаунт целиком — при следующем входе
    пользователь зарегистрируется заново (согласие + демо-данные)."""
    route_ids = db.query(Route.id).filter(Route.user_id == user.id)
    # bulk-удаление маршрутов обходит ORM-каскад — шаги стираем явно (user_id у них нет)
    db.query(RouteStep).filter(RouteStep.route_id.in_(route_ids)).delete(synchronize_session=False)
    for model, field in (
        (Route, "user_id"),
        (ChecklistItem, "user_id"),
        (Reminder, "user_id"),
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


# ---------- регионы ----------


@router.get("/regions", response_model=list[RegionDto])
def regions(user: User = Depends(consented_user)):
    """Справочник регионов из content/regions.json — источник и организаций (сид-синк на старте)."""
    return [RegionDto(key=r["key"], title=r["title"], pilot=r.get("pilot", False)) for r in load_regions()]


# ---------- каталог ситуаций ----------


@router.get("/catalog", response_model=list[SituationDto])
def catalog(user: User = Depends(consented_user)):
    return [SituationDto(**s) for s in load_catalog()]


@router.get("/catalog/{key}/steps")
def catalog_steps(key: str, user: User = Depends(consented_user)):
    """Шаги шаблона — конструктору нужны тумблеры «включить/выключить шаг» до создания маршрута."""
    spec = load_scenarios().get(key)
    if spec is None:
        raise HTTPException(status_code=404, detail="Неизвестная ситуация")
    return [
        {"position": i, "title": s["title"], "has_checklist": s.get("has_checklist", False)}
        for i, s in enumerate(spec["steps"], start=1)
    ]


# ---------- маршрут ----------


def _get_active_route(db: Session, user_id: int) -> Route | None:
    return db.query(Route).filter(Route.user_id == user_id, Route.active.is_(True)).first()


@router.get("/route", response_model=RouteDto | None)
def get_route(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    route = _get_active_route(db, user.id)
    return route_dto(route) if route else None


@router.delete("/route")
def delete_route(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Удалить активный маршрут целиком (шаги уходят каскадом)."""
    route = _get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    db.delete(route)
    db.commit()
    return {"status": "deleted"}


@router.post("/route/start", response_model=RouteDto)
def start_route(body: RouteStartIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    known = {s["key"] for s in load_catalog()} | {"custom"}
    if body.situation_key not in known:
        raise HTTPException(status_code=404, detail="Неизвестная ситуация")
    route = build_route_for(
        db,
        user,
        body.situation_key,
        exclude_positions=body.exclude_positions,
        custom_steps=[s.model_dump() for s in body.custom_steps],
    )
    return route_dto(route)


@router.post("/route/steps", response_model=RouteDto)
def add_step(
    body: StepAddIn,
    after_step_id: int | None = Query(default=None),
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    """Новый шаг маршрута. По умолчанию вставаем сразу после текущего шага;
    after_step_id нужен, чтобы несколько назначений подряд шли в порядке добавления."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название шага не может быть пустым")
    if body.source not in ("user", "doctor"):
        raise HTTPException(status_code=422, detail="Недопустимый источник шага")
    route = _get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")

    anchor = None
    if after_step_id:
        anchor = db.query(RouteStep).filter(RouteStep.id == after_step_id, RouteStep.route_id == route.id).first()
        if anchor is None:
            raise HTTPException(status_code=404, detail="Шаг для вставки не найден")
    if anchor is None:
        anchor = (
            db.query(RouteStep)
            .filter(RouteStep.route_id == route.id, RouteStep.status == "current")
            .first()
        )
    if anchor is None:  # всё выполнено — добавляем в конец
        anchor = (
            db.query(RouteStep)
            .filter(RouteStep.route_id == route.id)
            .order_by(RouteStep.position.desc())
            .first()
        )

    # В пустом маршруте якоря нет; первый добавленный шаг становится текущим.
    position = anchor.position + 1 if anchor is not None else 1
    has_unfinished = db.query(RouteStep).filter(
        RouteStep.route_id == route.id, RouteStep.status != "done"
    ).first() is not None
    if anchor is not None:
        db.query(RouteStep).filter(
            RouteStep.route_id == route.id, RouteStep.position >= position
        ).update({"position": RouteStep.position + 1}, synchronize_session=False)
    step = RouteStep(
        route_id=route.id,
        position=position,
        title=title,
        description="",
        place=body.place or "",
        deadline=body.deadline,
        deadline_time=body.deadline_time,
        status="pending" if has_unfinished else "current",
        source=body.source,
    )
    db.add(step)
    db.commit()
    db.refresh(route)
    return route_dto(route)


@router.delete("/route/steps/{step_id}", response_model=RouteDto)
def delete_step(step_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Удалить непройденный шаг; если удалили текущий — текущим становится следующий pending."""
    route = _get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise HTTPException(status_code=404, detail="Шаг не найден")
    if step.status == "done":
        raise HTTPException(status_code=409, detail="Пройденный шаг удалить нельзя")

    was_current = step.status == "current"
    position = step.position
    db.delete(step)
    db.flush()
    db.query(RouteStep).filter(
        RouteStep.route_id == route.id, RouteStep.position > position
    ).update({"position": RouteStep.position - 1}, synchronize_session=False)
    if was_current:
        next_step = (
            db.query(RouteStep)
            .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
            .order_by(RouteStep.position)
            .first()
        )
        if next_step is not None:
            next_step.status = "current"
    db.commit()
    db.refresh(route)
    return route_dto(route)


@router.post("/route/steps/{step_id}/complete", response_model=CompleteStepOut)
def complete_step(step_id: int, body: CompleteStepIn | None = None, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    try:
        step = complete_route_step(db, user.id, step_id, note=(body.note if body else None), done_date=(body.date if body else None))
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    route = _get_active_route(db, user.id)
    next_step = (
        db.query(RouteStep)
        .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
        .order_by(RouteStep.position)
        .first()
    )
    return CompleteStepOut(
        step=StepDto.model_validate(step),
        route=route_dto(route),
        next_step=StepDto.model_validate(next_step) if next_step else None,
    )


@router.post("/route/steps/{step_id}/uncomplete", response_model=RouteDto)
def uncomplete_step(step_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Отменить выполнение шага (отметили случайно — можно снять)."""
    try:
        uncomplete_route_step(db, user.id, step_id)
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    route = _get_active_route(db, user.id)
    return route_dto(route)


@router.patch("/route/steps/{step_id}", response_model=StepDto)
def update_step(step_id: int, body: StepUpdateIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Изменить срок шага (в том числе шаблонного) — выполняенный не меняем."""
    route = _get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise HTTPException(status_code=404, detail="Шаг не найден")
    if step.status == "done":
        raise HTTPException(status_code=409, detail="Пройденный шаг изменить нельзя")
    step.deadline = body.deadline
    db.commit()
    db.refresh(step)
    return StepDto.model_validate(step)


# ---------- чек-лист ----------


@router.get("/checklist", response_model=ChecklistOut)
def checklist(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    items = db.query(ChecklistItem).filter(ChecklistItem.user_id == user.id).order_by(ChecklistItem.position, ChecklistItem.id).all()
    return ChecklistOut(
        items=[ChecklistItemDto.model_validate(i) for i in items],
        collected=sum(1 for i in items if i.collected),
        total=len(items),
    )


@router.post("/checklist/{item_id}/toggle", response_model=ChecklistItemDto)
def toggle_checklist_item(item_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id, ChecklistItem.user_id == user.id).first()
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


# ---------- организации (демо-данные) ----------


@router.get("/orgs", response_model=list[OrganizationDto])
def orgs(
    q: str = Query(default=""),
    org_type: str = Query(default=""),
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    query = db.query(Organization)
    if user.region:
        # организации выбранного региона; регион не выбран — показываем все
        query = query.filter(Organization.region == user.region)
    if org_type and org_type != "Все":
        query = query.filter(Organization.org_type == org_type)
    if q:
        query = query.filter(Organization.title.ilike(f"%{q}%"))
    return [OrganizationDto.model_validate(o) for o in query.all()]


@router.get("/orgs/{org_id}", response_model=OrganizationDto)
def org_detail(org_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    return OrganizationDto.model_validate(org)


# ---------- напоминания ----------


@router.get("/reminders", response_model=list[ReminderDto])
def reminders(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    rows = (
        db.query(Reminder)
        .filter(Reminder.user_id == user.id, Reminder.done_at.is_(None))
        .order_by(Reminder.at)
        .all()
    )
    return [ReminderDto.model_validate(r) for r in rows]


@router.post("/reminders/{reminder_id}/toggle", response_model=ReminderDto)
def toggle_reminder(reminder_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    row = db.query(Reminder).filter(Reminder.id == reminder_id, Reminder.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    row.enabled = not row.enabled
    db.commit()
    return row


@router.post("/reminders", response_model=ReminderDto)
def add_reminder(body: dict, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    title = str((body or {}).get("title", "")).strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    raw_at = (body or {}).get("at")
    try:
        at = datetime.fromisoformat(raw_at) if raw_at else utcnow() + timedelta(days=1)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Некорректная дата напоминания")
    row = Reminder(user_id=user.id, title=title, place=str((body or {}).get("place", "") or ""), at=at)
    db.add(row)
    db.commit()
    return row


# ---------- дневники здоровья ----------


def _get_diary_settings(db: Session, user_id: int) -> dict[str, bool]:
    rows = db.query(HealthSetting).filter(HealthSetting.user_id == user_id).all()
    if not rows:
        return dict(DEFAULT_DIARIES)
    return {r.diary: r.enabled for r in rows}


@router.get("/health/settings", response_model=HealthSettingsOut)
def health_settings(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    rows = {r.diary: r for r in db.query(HealthSetting).filter(HealthSetting.user_id == user.id).all()}
    out = []
    for d in ("bp", "weight", "sugar", "mood"):
        row = rows.get(d)
        out.append(
            HealthSettingDto(
                diary=d,
                enabled=row.enabled if row else False,
                push_time=row.push_time if row else None,
            )
        )
    return HealthSettingsOut(diaries=out)


@router.put("/health/settings", response_model=HealthSettingsOut)
def update_health_settings(body: HealthSettingsIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    for item in body.diaries:
        if item.diary not in HEALTH_TYPES:
            raise HTTPException(status_code=422, detail=f"Неизвестный дневник: {item.diary}")
        push_time = (item.push_time or "").strip()
        if push_time:
            try:
                dtime.fromisoformat(push_time)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Некорректное время: {push_time}")
        else:
            push_time = None
        row = (
            db.query(HealthSetting)
            .filter(HealthSetting.user_id == user.id, HealthSetting.diary == item.diary)
            .first()
        )
        if row is None:
            db.add(HealthSetting(user_id=user.id, diary=item.diary, enabled=item.enabled, push_time=push_time))
        else:
            row.enabled = item.enabled
            row.push_time = push_time
    db.commit()
    return health_settings(user=user, db=db)


@router.get("/health/{type}/records", response_model=list[HealthRecordDto])
def health_records(type: str, limit: int = Query(default=100, le=500), user: User = Depends(consented_user), db: Session = Depends(db_session)):
    if type not in HEALTH_TYPES:
        raise HTTPException(status_code=404, detail="Неизвестный дневник")
    rows = (
        db.query(HealthRecord)
        .filter(HealthRecord.user_id == user.id, HealthRecord.type == type)
        .order_by(HealthRecord.at.desc())
        .limit(limit)
        .all()
    )
    return [HealthRecordDto.model_validate(r) for r in rows]


# Кратковременные токены экспорта PDF: единственный надёжный путь скачать файл из
# вебвью MAX, где a.download/blob и шаринг могут быть заблокированы — ссылку с токеном
# открывают в обычном браузере. В памяти процесса, TTL 5 минут, даёт доступ только к PDF.
_EXPORT_TOKENS: dict[str, tuple[int, datetime]] = {}  # token -> (user_id, expires_at)
_EXPORT_TTL = timedelta(minutes=5)


@router.post("/health/export-token")
def create_export_token(user: User = Depends(consented_user)):
    import uuid

    token = uuid.uuid4().hex
    _EXPORT_TOKENS[token] = (user.id, utcnow() + _EXPORT_TTL)
    for t, (_, exp) in list(_EXPORT_TOKENS.items()):
        if exp < utcnow():
            _EXPORT_TOKENS.pop(t, None)
    return {"token": token, "ttl_seconds": int(_EXPORT_TTL.total_seconds())}


@router.post("/health/send-to-bot")
def request_pdf_in_chat(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Попросить бота прислать PDF-сводку в чат (на телефонах вебвью MAX не умеет скачивать)."""
    row = ExportRequest(user_id=user.id)
    db.add(row)
    db.commit()
    return {"status": "queued", "hint": "PDF придёт в чат бота через несколько секунд"}


@router.get("/health/export")
def export_health_pdf(request: Request, t: str | None = Query(default=None), db: Session = Depends(db_session)):
    """PDF-сводка дневников для врача. Авторизация: initData-заголовок ИЛИ ?t=<токен из /health/export-token>."""
    user: User | None = None
    if t is not None:
        entry = _EXPORT_TOKENS.pop(t, None)
        if entry is None or entry[1] < utcnow():
            raise HTTPException(status_code=401, detail="Ссылка недействительна или устарела")
        user = db.get(User, entry[0])
    else:
        try:
            user = get_or_create_user(db, request.headers.get("X-Max-Init-Data"))
        except AuthError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    if user.consent_at is None:
        raise HTTPException(status_code=403, detail="consent_required")

    report = health_report(user=user, db=db)
    enabled = _get_diary_settings(db, user.id)
    data = build_health_pdf(db, user, report, enabled)
    stamp = utcnow().strftime("%d.%m.%Y")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="medroute-svodka-{stamp}.pdf"'},
    )


@router.post("/health/{type}", response_model=HealthRecordDto)
def add_health_record(type: str, body: HealthAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    try:
        return create_health_record(db, user.id, type, **body.model_dump())
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


@router.delete("/health/{type}/{record_id}")
def delete_health_record(type: str, record_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Удалить одну запись дневника (ошибочно внесённую)."""
    if type not in HEALTH_TYPES:
        raise HTTPException(status_code=404, detail="Неизвестный дневник")
    row = (
        db.query(HealthRecord)
        .filter(HealthRecord.id == record_id, HealthRecord.user_id == user.id, HealthRecord.type == type)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@router.get("/health/report", response_model=HealthReportOut)
def health_report(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    """Сводка для врача: агрегаты за 30 дней по включённым дневникам, только факты."""
    period_start = utcnow() - timedelta(days=30)
    enabled = _get_diary_settings(db, user.id)
    out = HealthReportOut()

    def rows(t: str) -> list[HealthRecord]:
        return (
            db.query(HealthRecord)
            .filter(HealthRecord.user_id == user.id, HealthRecord.type == t, HealthRecord.at >= period_start)
            .order_by(HealthRecord.at)
            .all()
        )

    if enabled.get("bp"):
        bp = rows("bp")
        if bp:
            out.bp_count = len(bp)
            out.bp_avg = f"{round(sum(r.systolic for r in bp) / len(bp))}/{round(sum(r.diastolic for r in bp) / len(bp))}"
            pulses = [r.pulse for r in bp if r.pulse is not None]
            out.pulse_avg = round(sum(pulses) / len(pulses)) if pulses else None
    if enabled.get("weight"):
        weight = rows("weight")
        if weight:
            out.weight_count = len(weight)
            out.weight_latest = weight[-1].weight_kg
            out.weight_delta = round(weight[-1].weight_kg - weight[0].weight_kg, 1)
    if enabled.get("sugar"):
        sugar = rows("sugar")
        if sugar:
            out.sugar_count = len(sugar)
            out.sugar_avg = round(sum(r.sugar_mmol for r in sugar) / len(sugar), 1)

    if enabled.get("mood"):
        notes = (
            db.query(HealthRecord)
            .filter(HealthRecord.user_id == user.id, HealthRecord.note.is_not(None), HealthRecord.at >= period_start)
            .order_by(HealthRecord.at.desc())
            .limit(5)
            .all()
        )
        out.notes = [ReportNote(at=n.at, note=n.note) for n in notes]

    today = user_today(user)
    period_start_day = user_today(user, period_start)
    for course in db.query(MedCourse).filter(MedCourse.user_id == user.id, MedCourse.enabled.is_(True)).all():
        start = max(course.created_at.date(), period_start_day) if course.created_at else period_start_day
        end = min(course.until, today) if course.until else today
        if start > end:
            continue
        days = (end - start).days + 1
        planned = days * len(course.times)
        taken = (
            db.query(MedIntake)
            .filter(
                MedIntake.course_id == course.id,
                MedIntake.taken_at.is_not(None),
                MedIntake.day >= start,
                MedIntake.day <= end,
            )
            .count()
        )
        taken = min(taken, planned)
        out.meds.append(
            ReportMedsRow(
                name=course.name,
                taken=taken,
                planned=planned,
                pct=round(100 * taken / planned) if planned else 0,
            )
        )
    return out





# ---------- лекарства ----------


def _meds_out(db: Session, user: User) -> MedsOut:
    today = user_today(user)
    courses = (
        db.query(MedCourse)
        .filter(MedCourse.user_id == user.id, MedCourse.enabled.is_(True))
        .order_by(MedCourse.created_at)
        .all()
    )
    intakes = (
        db.query(MedIntake)
        .filter(MedIntake.user_id == user.id, MedIntake.day == today)
        .all()
    )
    taken_map = {(i.course_id, i.at_time): i for i in intakes}
    slots: list[MedSlotDto] = []
    for c in courses:
        if c.until is not None and c.until < today:
            continue
        for t in c.times:
            intake = taken_map.get((c.id, t))
            slots.append(
                MedSlotDto(course_id=c.id, name=c.name, at_time=t, taken=intake is not None and intake.taken_at is not None, taken_at=intake.taken_at if intake else None)
            )
    slots.sort(key=lambda s: s.at_time)
    return MedsOut(courses=[MedCourseDto.model_validate(c) for c in courses], today=slots)


@router.get("/meds", response_model=MedsOut)
def meds(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    return _meds_out(db, user)


@router.post("/meds", response_model=MedsOut)
def add_med(body: MedAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    for t in body.times:
        try:
            dtime.fromisoformat(t)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Некорректное время: {t}")
    db.add(MedCourse(user_id=user.id, name=name, times=sorted(set(body.times)), until=body.until))
    db.commit()
    return _meds_out(db, user)


@router.post("/meds/{course_id}/intake-toggle", response_model=MedSlotDto)
def toggle_intake(course_id: int, body: dict, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    at_time = str((body or {}).get("at_time", "")).strip()
    course = db.query(MedCourse).filter(MedCourse.id == course_id, MedCourse.user_id == user.id).first()
    if course is None or at_time not in course.times:
        raise HTTPException(status_code=404, detail="Курс или время приёма не найдены")
    intake = (
        db.query(MedIntake)
        .filter(MedIntake.course_id == course.id, MedIntake.day == user_today(user), MedIntake.at_time == at_time)
        .first()
    )
    undo = intake is not None and intake.taken_at is not None
    if undo:
        intake.taken_at = None
        db.commit()
    else:
        try:
            intake = take_med(db, user.id, course_id, at_time)
        except ServiceError as e:
            raise HTTPException(status_code=e.status, detail=str(e)) from e
    return MedSlotDto(course_id=course.id, name=course.name, at_time=at_time, taken=intake.taken_at is not None, taken_at=intake.taken_at)


@router.post("/meds/{course_id}/disable", response_model=MedsOut)
def disable_med(course_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    course = db.query(MedCourse).filter(MedCourse.id == course_id, MedCourse.user_id == user.id).first()
    if course is None:
        raise HTTPException(status_code=404, detail="Курс не найден")
    course.enabled = False
    db.commit()
    return _meds_out(db, user)


# ---------- семейный доступ (демо) ----------


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
