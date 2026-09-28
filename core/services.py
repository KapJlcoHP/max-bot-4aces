"""Общая бизнес-логика: один код для REST API (мини-ап) и бота (кнопки в чате).

Ошибки брошены как ServiceError: API превращает её в HTTP 4xx, бот — в текст пользователю.
"""

from datetime import date, datetime, time as dtime

from sqlalchemy.orm import Session

from core.db.models import (
    HealthRecord,
    MedCourse,
    MedIntake,
    Reminder,
    Route,
    RouteStep,
    utcnow,
)

HEALTH_TYPES = {"bp", "weight", "sugar", "mood"}
MOODS = ("Хорошо", "Нормально", "Плохо")


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def active_route(db: Session, user_id: int) -> Route | None:
    return db.query(Route).filter(Route.user_id == user_id, Route.active.is_(True)).first()


# ---------- маршрут ----------


def complete_route_step(
    db: Session, user_id: int, step_id: int, note: str | None = None, done_date: date | None = None
) -> RouteStep:
    """Шаг → done, следующий незавершённый → current. Возвращает выполненный шаг."""
    route = active_route(db, user_id)
    if route is None:
        raise ServiceError("Активный маршрут не найден", 404)
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise ServiceError("Шаг не найден", 404)
    if step.status == "done":
        raise ServiceError("Шаг уже выполнен", 409)

    step.status = "done"
    step.completed_at = utcnow()
    step.note = note or None
    if done_date:
        step.completed_at = datetime.combine(done_date, dtime(12, 0))

    next_step = (
        db.query(RouteStep)
        .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
        .order_by(RouteStep.position)
        .first()
    )
    if next_step is not None:
        next_step.status = "current"
    db.commit()
    db.refresh(step)
    return step


def uncomplete_route_step(db: Session, user_id: int, step_id: int) -> RouteStep:
    """Отменить выполнение: шаг снова pending. Если текущего нет (маршрут был завершён),
    текущим становится самый ранний невыполненный."""
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
    has_current = (
        db.query(RouteStep)
        .filter(RouteStep.route_id == route.id, RouteStep.status == "current")
        .first()
    )
    if has_current is None:
        earliest = (
            db.query(RouteStep)
            .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
            .order_by(RouteStep.position)
            .first()
        )
        if earliest is not None:
            earliest.status = "current"
    db.commit()
    db.refresh(step)
    return step


# ---------- лекарства ----------


def take_med(db: Session, user_id: int, course_id: int, at_time: str, day: date | None = None) -> MedIntake:
    """Отметить приём (односторонне: снимает только API через intake-toggle с undo)."""
    course = db.query(MedCourse).filter(MedCourse.id == course_id, MedCourse.user_id == user_id).first()
    if course is None:
        raise ServiceError("Курс лекарства не найден", 404)
    day = day or date.today()
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
        intake = MedIntake(course_id=course.id, user_id=user_id, day=day, at_time=at_time, taken_at=utcnow())
        db.add(intake)
    elif intake.taken_at is None:
        intake.taken_at = utcnow()
    db.commit()
    db.refresh(intake)
    return intake


# ---------- напоминания ----------


def complete_reminder(db: Session, user_id: int, reminder_id: int) -> Reminder:
    row = db.query(Reminder).filter(Reminder.id == reminder_id, Reminder.user_id == user_id).first()
    if row is None:
        raise ServiceError("Напоминание не найдено", 404)
    if row.done_at is None:
        row.done_at = utcnow()
        db.commit()
        db.refresh(row)
    return row


# ---------- дневники здоровья ----------


def add_health_record(db: Session, user_id: int, type: str, **fields) -> HealthRecord:
    """Только факты: сервер хранит значения и контекст, никакой интерпретации «норма/не норма»."""
    if type not in HEALTH_TYPES:
        raise ServiceError("Неизвестный дневник", 404)

    row = HealthRecord(user_id=user_id, type=type, at=utcnow(), tag=fields.get("tag"), note=fields.get("note"))
    if type == "bp":
        systolic, diastolic, pulse = fields.get("systolic"), fields.get("diastolic"), fields.get("pulse")
        if systolic is None or diastolic is None:
            raise ServiceError("Укажите верхнее и нижнее давление")
        if not (70 <= systolic <= 250 and 40 <= diastolic <= 150):
            raise ServiceError("Показатели вне допустимого диапазона")
        if pulse is not None and not (30 <= pulse <= 220):
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
        if sugar is None or not (1.1 <= sugar <= 35.0):
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
