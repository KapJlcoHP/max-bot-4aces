"""Модельные демо-данные для проверки сценария: команды /demo и /wipe бота.

Заполняет аккаунт вымышленной историей пациента (гипертония): маршрут с
частично выполненными шагами, 30 дней измерений, курсы лекарств, напоминания.
Все данные синтетические; в PDF и текстах это помечается. Времена — «настенные»
Europe/Moscow: интерфейс показывает их как есть.
"""

import random
from datetime import date, datetime, time as dtime, timedelta

from sqlalchemy.orm import Session

from core.db.models import (
    BpRecord, ChecklistItem, ExportRequest, FamilyMember, HealthRecord, HealthSetting,
    MedCourse, MedIntake, NotificationLog, Reminder, Route, RouteStep, User,
)
from core.db.seed import build_route_for
from core.services import complete_route_step

TODAY = date.today()


def has_any_data(db: Session, user_id: int) -> bool:
    """Есть ли у аккаунта хоть какой-то контент (для защиты /demo от перезаписи)."""
    route_ids = db.query(Route.id).filter(Route.user_id == user_id)
    return (
        db.query(Route).filter(Route.user_id == user_id).first() is not None
        or db.query(RouteStep).filter(RouteStep.route_id.in_(route_ids)).first() is not None
        or db.query(HealthRecord).filter(HealthRecord.user_id == user_id).first() is not None
        or db.query(MedCourse).filter(MedCourse.user_id == user_id).first() is not None
        or db.query(Reminder).filter(Reminder.user_id == user_id).first() is not None
    )


def wipe_data(db: Session, user: User) -> None:
    """Стираем контент, аккаунт и согласие остаются (в отличие от DELETE /me/data)."""
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
    db.commit()


def _at(days_ago: int, hh: int, mm: int) -> datetime:
    """«Настенное» время days_ago дней назад — наивное, как хранит прод."""
    return datetime.combine(TODAY - timedelta(days=days_ago), dtime(hh, mm))


def fill_demo(db: Session, user: User) -> None:
    rng = random.Random(42)
    if not user.region:
        user.region = "ivanovo"  # организации справочника фильтруются по региону
    db.commit()

    # --- маршрут «Наблюдаться по хроническому», первые шаги выполнены ---
    route = build_route_for(db, user, "chronic")
    steps = (
        db.query(RouteStep)
        .filter(RouteStep.route_id == route.id)
        .order_by(RouteStep.position)
        .all()
    )
    for i, step in enumerate(steps[:3]):
        complete_route_step(db, user.id, step.id, done_date=TODAY - timedelta(days=6 - i * 2))

    # --- дневники: 30 дней ---
    bp_rows = []
    for day in range(29, -1, -1):
        drift = day * 0.15  # к сегодняшнему дню показатели чуть спокойнее
        sys = int(rng.gauss(146 - drift, 5))
        dia = int(rng.gauss(90 - drift * 0.6, 4))
        pulse = int(rng.gauss(74, 5))
        bp_rows.append(HealthRecord(user_id=user.id, type="bp", at=_at(day, 8, 10),
                                    systolic=sys, diastolic=dia, pulse=pulse, tag="утром"))
        if rng.random() < 0.4:
            bp_rows.append(HealthRecord(user_id=user.id, type="bp", at=_at(day, 19, 30),
                                        systolic=sys - rng.randint(0, 8), diastolic=dia - rng.randint(0, 5),
                                        pulse=pulse + rng.randint(-4, 4), tag="вечером"))
    for day in range(28, -1, -3):
        w = 84.8 - (28 - day) * 0.06 + rng.uniform(-0.25, 0.25)
        bp_rows.append(HealthRecord(user_id=user.id, type="weight", at=_at(day, 8, 5),
                                    weight_kg=round(w, 1), tag="утром"))
    for day in range(28, -1, -2):
        if rng.random() < 0.75:
            pre = rng.random() < 0.5
            v = round(rng.gauss(5.4 if pre else 6.6, 0.45), 1)
            bp_rows.append(HealthRecord(user_id=user.id, type="sugar", at=_at(day, 9 if pre else 11, 40),
                                        sugar_mmol=v, meal_tag="до еды" if pre else "после еды"))
    for day, mood, pain, note in (
        (12, "Нормально", 3, "К вечеру подташнивало после новой таблетки"),
        (8, "Хорошо", 2, "Гуляла 40 минут, давление мерила дважды"),
        (5, "Плохо", 6, "Болела голова, приняла парацетамол"),
        (2, "Нормально", 3, None),
    ):
        bp_rows.append(HealthRecord(user_id=user.id, type="mood", at=_at(day, 21, 15),
                                    mood=mood, pain=pain, note=note))
    db.add_all(bp_rows)

    # --- какие дневники ведём: сахар выключен, как в онбординге по умолчанию ---
    for diary, push, enabled in (("bp", "08:30", True), ("weight", "08:30", True),
                                 ("mood", "21:00", True), ("sugar", None, False)):
        db.add(HealthSetting(user_id=user.id, diary=diary, enabled=enabled, push_time=push))

    # --- курсы лекарств + отметки приёма за 30 дней ---
    courses = [
        MedCourse(user_id=user.id, name="Эналаприл 10 мг", times=["08:00", "20:00"],
                  created_at=_at(29, 8, 0),
                  until=TODAY + timedelta(days=27)),
        MedCourse(user_id=user.id, name="Аторвастатин 20 мг", times=["21:00"],
                  created_at=_at(29, 8, 0),
                  until=TODAY + timedelta(days=27)),
    ]
    db.add_all(courses)
    db.flush()
    for day in range(30):
        for course in courses:
            for at_time in course.times:
                if rng.random() < 0.93:
                    db.add(MedIntake(course_id=course.id, user_id=user.id,
                                     day=TODAY - timedelta(days=day), at_time=at_time,
                                     taken_at=_at(day, int(at_time[:2]), int(at_time[3:]))))

    # --- будущие визиты, чтобы боту было что напоминать ---
    db.add(Reminder(user_id=user.id, title="Кардиолог — плановый приём",
                    place="Консультативно-диагностический центр, каб. 12",
                    at=datetime.combine(TODAY + timedelta(days=6), dtime(10, 0))))
    db.add(Reminder(user_id=user.id, title="УЗИ почек натощак",
                    place="Поликлиника по месту прикрепления",
                    at=datetime.combine(TODAY + timedelta(days=12), dtime(9, 0))))
    db.commit()
