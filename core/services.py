"""Общая бизнес-логика: один код для REST API (мини-ап) и бота (кнопки в чате).

Ошибки брошены как ServiceError: API превращает её в HTTP 4xx, бот — в текст пользователю.
"""

from datetime import date, datetime, time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.orm import Session

from core.db.models import (
    HealthRecord,
    MedCourse,
    MedIntake,
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)
from core.time import as_utc, db_utc, user_zone

HEALTH_TYPES = {"bp", "weight", "sugar", "mood"}
MOODS = ("Хорошо", "Нормально", "Плохо")


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def active_route(db: Session, user_id: int) -> Route | None:
    return db.query(Route).filter(Route.user_id == user_id, Route.active.is_(True)).first()


# ---------- маршрут ----------


def lock_route_writes(db: Session, user_id: int) -> None:
    """Hold until commit/rollback: SQLite writer lock, PostgreSQL user row lock.

    Take this before reading route state, including when auth has already read
    the user. A real UPDATE also works with SQLite's deferred transactions.
    Refresh loaded route objects after waiting; expire_on_commit may be False.
    """
    with db.no_autoflush:
        db.execute(
            update(User).where(User.id == user_id).values(id=User.id)
            .execution_options(synchronize_session=False)
        )
        # Composed callers (e.g. demo setup, commit=False) may have staged
        # changes. Persist them under the lock before refreshing stale reads.
        db.flush()
        for obj in list(db.identity_map.values()):
            if isinstance(obj, (Route, RouteStep)) and obj not in db.new and obj not in db.deleted:
                db.expire(obj)


def ordered_route_steps(db: Session, route: Route) -> list[RouteStep]:
    return db.query(RouteStep).filter(RouteStep.route_id == route.id).order_by(
        RouteStep.position, RouteStep.id,
    ).populate_existing().all()


def normalize_route_steps(db: Session, route: Route, steps: list[RouteStep] | None = None) -> None:
    """Historical done rows stay done; exactly the first unfinished is current."""
    steps = ordered_route_steps(db, route) if steps is None else steps
    found_current = False
    for position, step in enumerate(steps, 1):
        step.position = position
        if step.status == "done":
            continue
        status = "pending" if found_current else "current"
        if status == "current" and step.status != "current":
            step.activated_at = utcnow()
        step.status = status
        found_current = True
    db.flush()
    # A preloaded relationship and bulk-shifted positions must not leak stale DTOs.
    db.expire(route, ["steps"])


def insert_route_steps(
    db: Session, route: Route, anchor: RouteStep | None, additions: list[RouteStep],
    *, before: bool = False,
) -> None:
    steps = ordered_route_steps(db, route)
    index = steps.index(anchor) + int(not before) if anchor is not None else len(steps)
    for step in additions:
        step.route_id = route.id
        step.status = "pending"
        db.add(step)
    steps[index:index] = additions
    normalize_route_steps(db, route, steps)


def validate_booking_target(
    db: Session, route: Route, step: RouteStep, kind: str, target_id: int | None,
) -> RouteStep | None:
    """Resolve only explicit IDs in this route; never infer a role from text."""
    if target_id is None:
        return None
    if kind != "booking":
        raise ServiceError("Связь допустима только для шага booking")
    target = db.query(RouteStep).filter_by(id=target_id, route_id=route.id).first()
    if target is None:
        raise ServiceError("Цель записи не найдена", 404)
    if target.id == step.id or target.position <= step.position:
        raise ServiceError("Цель записи должна находиться после записи")
    if target.status == "done" or target.kind not in {"visit", "investigation", "task", "process"}:
        raise ServiceError("Выберите незавершённое событие известного вида")
    return target


def complete_route_step(
    db: Session,
    user_id: int,
    step_id: int,
    note: str | None = None,
    done_date: date | None = None,
    commit: bool = True,
) -> RouteStep:
    """Шаг → done, следующий незавершённый → current. Возвращает выполненный шаг."""
    lock_route_writes(db, user_id)
    route = active_route(db, user_id)
    if route is None:
        raise ServiceError("Активный маршрут не найден", 404)
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise ServiceError("Шаг не найден", 404)
    if step.status == "done":
        raise ServiceError("Шаг уже выполнен", 409)
    if step.status != "current":
        raise ServiceError("Сначала завершите текущий шаг", 409)

    step.status = "done"
    step.completed_at = utcnow()
    step.note = note or None
    if done_date:
        owner = db.get(User, user_id)
        step.completed_at = db_utc(
            datetime.combine(done_date, dtime(12, 0)),
            user_zone(owner.tz if owner else None),
        )

    normalize_route_steps(db, route)
    if commit:
        db.commit()
        db.refresh(step)
    return step


def uncomplete_route_step(db: Session, user_id: int, step_id: int, commit: bool = True) -> RouteStep:
    """Отменить выполнение: возвращаемся к этому шагу маршрута."""
    lock_route_writes(db, user_id)
    route = active_route(db, user_id)
    if route is None:
        raise ServiceError("Активный маршрут не найден", 404)
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise ServiceError("Шаг не найден", 404)
    if step.status != "done":
        raise ServiceError("Шаг ещё не выполнен", 409)

    step.status = "pending"
    step.completed_at = None
    normalize_route_steps(db, route)
    if commit:
        db.commit()
        db.refresh(step)
    return step


# ---------- лекарства ----------


def user_today(user: User, now: datetime | None = None) -> date:
    """Текущая дата в часовом поясе пользователя."""
    # ZoneInfo остаётся локальной точкой подмены для legacy callers/tests;
    # при плохом значении используется та же безопасная конвенция.
    try:
        zone = ZoneInfo(user.tz or "Europe/Moscow")
    except Exception:
        zone = user_zone(user.tz)
    return as_utc(now or utcnow()).astimezone(zone).date()


def take_med(db: Session, user_id: int, course_id: int, at_time: str, day: date | None = None) -> MedIntake:
    """Отметить приём (односторонне: снимает только API через intake-toggle с undo)."""
    course = db.query(MedCourse).filter(MedCourse.id == course_id, MedCourse.user_id == user_id).first()
    if course is None:
        raise ServiceError("Курс лекарства не найден", 404)
    if day is None:
        user = db.get(User, user_id)
        if user is None:
            raise ServiceError("Пользователь не найден", 404)
        day = user_today(user)
    intake = (
        db.query(MedIntake)
        .filter(
            MedIntake.course_id == course.id,
            MedIntake.user_id == user_id,
            MedIntake.day == day,
            MedIntake.at_time == at_time,
        )
        .first()
    )
    if intake is None:
        intake = MedIntake(course_id=course.id, user_id=user_id, day=day, at_time=at_time, taken_at=db_utc(utcnow()))
        db.add(intake)
    elif intake.taken_at is None:
        intake.taken_at = db_utc(utcnow())
    db.commit()
    db.refresh(intake)
    return intake


# ---------- напоминания ----------


def complete_reminder(db: Session, user_id: int, reminder_id: int) -> Reminder:
    row = db.query(Reminder).filter(Reminder.id == reminder_id, Reminder.user_id == user_id).first()
    if row is None:
        raise ServiceError("Напоминание не найдено", 404)
    if row.done_at is None:
        row.done_at = db_utc(utcnow())
        db.commit()
        db.refresh(row)
    return row


# ---------- дневники здоровья ----------


def add_health_record(db: Session, user_id: int, type: str, **fields) -> HealthRecord:
    """Только факты: сервер хранит значения и контекст, никакой интерпретации «норма/не норма»."""
    if type not in HEALTH_TYPES:
        raise ServiceError("Неизвестный дневник", 404)

    row = HealthRecord(user_id=user_id, type=type, at=db_utc(utcnow()), tag=fields.get("tag"), note=fields.get("note"))
    if type == "bp":
        systolic, diastolic, pulse = fields.get("systolic"), fields.get("diastolic"), fields.get("pulse")
        if systolic is None or diastolic is None:
            raise ServiceError("Укажите верхнее и нижнее давление")
        if not (50 <= systolic <= 260 and 30 <= diastolic <= 150):
            raise ServiceError("Показатели вне допустимого диапазона")
        if pulse is not None and not (25 <= pulse <= 220):
            raise ServiceError("Пульс вне допустимого диапазона")
        if diastolic >= systolic:
            raise ServiceError("Нижнее давление не может быть выше верхнего")
        row.systolic, row.diastolic, row.pulse = systolic, diastolic, pulse
    elif type == "weight":
        weight = fields.get("weight_kg")
        if weight is None or not (20 <= weight <= 300):
            raise ServiceError("Вес вне допустимого диапазона")
        row.weight_kg = weight
    elif type == "sugar":
        sugar = fields.get("sugar_mmol")
        if sugar is None or not (1 <= sugar <= 35):
            raise ServiceError("Показатель вне допустимого диапазона")
        row.sugar_mmol = sugar
        row.meal_tag = fields.get("meal_tag")
    elif type == "mood":
        mood = fields.get("mood")
        if mood not in MOODS:
            raise ServiceError("Отметьте самочувствие")
        pain = fields.get("pain")
        if pain is not None and not (1 <= pain <= 10):
            raise ServiceError("Боль оценивается от 1 до 10")
        row.mood, row.pain = mood, pain
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
