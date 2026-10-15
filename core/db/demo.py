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
from core.db.seed import build_route_for, pilot_region
from core.services import complete_route_step
from core.time import db_utc, user_zone

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
        or db.query(ChecklistItem).filter(ChecklistItem.user_id == user_id).first() is not None
        or db.query(MedIntake).filter(MedIntake.user_id == user_id).first() is not None
        or db.query(FamilyMember).filter(FamilyMember.owner_id == user_id).first() is not None
        or db.query(NotificationLog).filter(NotificationLog.user_id == user_id).first() is not None
        or db.query(ExportRequest).filter(ExportRequest.user_id == user_id).first() is not None
        or db.query(BpRecord).filter(BpRecord.user_id == user_id).first() is not None
    )


def _has_demo_route(db: Session, user_id: int) -> bool:
    """Есть ли у пользователя маршрут, созданный предыдущим запуском /demo."""
    return (
        db.query(Route.id)
        .filter(Route.user_id == user_id, Route.situation_key == "chronic")
        .first()
        is not None
    )


def is_demo_data(db: Session, user_id: int) -> bool:
    """Распознать ровно полный синтетический набор, созданный ``fill_demo``.

    Это не источник права на удаление данных: повторный запуск ``fill_demo`` для
    уже готового набора ниже является no-op. Точные размеры нужны только для
    отличия демо от аккаунта, в котором пользователь уже что-то добавил.
    """
    counts = {
        Route: 1,
        RouteStep: 6,
        ChecklistItem: 4,
        HealthRecord: 68,
        HealthSetting: 4,
        MedCourse: 2,
        MedIntake: 86,
        Reminder: 2,
        FamilyMember: 0,
        NotificationLog: 0,
        ExportRequest: 0,
        BpRecord: 0,
    }
    for model, expected in counts.items():
        if model is RouteStep:
            query = db.query(model).filter(
                RouteStep.route_id.in_(db.query(Route.id).filter(Route.user_id == user_id))
            )
        else:
            field = "owner_id" if model is FamilyMember else "user_id"
            query = db.query(model).filter(getattr(model, field) == user_id)
        if query.count() != expected:
            return False
    return _has_demo_route(db, user_id)


def wipe_data(db: Session, user: User, commit: bool = True) -> None:
    """Стираем контент, аккаунт и согласие остаются (в отличие от DELETE /me/data)."""
    route_ids = db.query(Route.id).filter(Route.user_id == user.id)
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
    if commit:
        db.commit()


def _at(days_ago: int, hh: int, mm: int, tz: str | None = None) -> datetime:
    """Временная точка демо: пользовательское настенное время -> UTC-naive."""
    return db_utc(datetime.combine(TODAY - timedelta(days=days_ago), dtime(hh, mm)), user_zone(tz))


def fill_demo(db: Session, user: User) -> None:
    # Повторный вызов уже готового демо безопасен и ничего не перезаписывает.
    if is_demo_data(db, user.id):
        return
    if has_any_data(db, user.id):
        raise ValueError("В аккаунте уже есть пользовательские данные")

    rng = random.Random(42)
    if not user.region:
        user.region = pilot_region()  # в БД хранится заголовок региона, не его ключ
    try:
        # --- маршрут «Наблюдаться по хроническому», первые шаги выполнены ---
        route = build_route_for(db, user, "chronic", commit=False)
        steps = (
            db.query(RouteStep)
            .filter(RouteStep.route_id == route.id)
            .order_by(RouteStep.position)
            .all()
        )
        for i, step in enumerate(steps[:3]):
            complete_route_step(
                db, user.id, step.id,
                done_date=TODAY - timedelta(days=6 - i * 2),
                commit=False,
            )

        # --- дневники: 30 дней ---
        bp_rows = []
        for day in range(29, -1, -1):
            drift = day * 0.15
            sys = int(rng.gauss(146 - drift, 5))
            dia = int(rng.gauss(90 - drift * 0.6, 4))
            pulse = int(rng.gauss(74, 5))
            bp_rows.append(HealthRecord(
                user_id=user.id, type="bp", at=_at(day, 8, 10, user.tz),
                systolic=sys, diastolic=dia, pulse=pulse, tag="утром",
            ))
            if rng.random() < 0.4:
                bp_rows.append(HealthRecord(
                    user_id=user.id, type="bp", at=_at(day, 19, 30, user.tz),
                    systolic=sys - rng.randint(0, 8),
                    diastolic=dia - rng.randint(0, 5),
                    pulse=pulse + rng.randint(-4, 4), tag="вечером",
                ))
        for day in range(28, -1, -3):
            weight = 84.8 - (28 - day) * 0.06 + rng.uniform(-0.25, 0.25)
            bp_rows.append(HealthRecord(
                user_id=user.id, type="weight", at=_at(day, 8, 5, user.tz),
                weight_kg=round(weight, 1), tag="утром",
            ))
        for day in range(28, -1, -2):
            if rng.random() < 0.75:
                pre = rng.random() < 0.5
                value = round(rng.gauss(5.4 if pre else 6.6, 0.45), 1)
                bp_rows.append(HealthRecord(
                    user_id=user.id, type="sugar", at=_at(day, 9 if pre else 11, 40, user.tz),
                    sugar_mmol=value, meal_tag="до еды" if pre else "после еды",
                ))
        for day, mood, pain, note in (
            (12, "Нормально", 3, "К вечеру подташнивало после новой таблетки"),
            (8, "Хорошо", 2, "Гуляла 40 минут, давление мерила дважды"),
            (5, "Плохо", 6, "Болела голова, приняла парацетамол"),
            (2, "Нормально", 3, None),
        ):
            bp_rows.append(HealthRecord(
                user_id=user.id, type="mood", at=_at(day, 21, 15, user.tz),
                mood=mood, pain=pain, note=note,
            ))
        db.add_all(bp_rows)

        # Настройки, созданные онбордингом, не перезаписываем.
        for diary, push, enabled in (
            ("bp", "08:30", True), ("weight", "08:30", True),
            ("mood", "21:00", True), ("sugar", None, False),
        ):
            setting = (
                db.query(HealthSetting)
                .filter(HealthSetting.user_id == user.id, HealthSetting.diary == diary)
                .first()
            )
            if setting is None:
                db.add(HealthSetting(
                    user_id=user.id, diary=diary, enabled=enabled, push_time=push,
                ))

        # --- курсы лекарств + отметки приёма за 30 дней ---
        courses = [
            MedCourse(
                user_id=user.id, name="Эналаприл 10 мг", times=["08:00", "20:00"],
                created_at=_at(29, 8, 0, user.tz), until=TODAY + timedelta(days=27),
            ),
            MedCourse(
                user_id=user.id, name="Аторвастатин 20 мг", times=["21:00"],
                created_at=_at(29, 8, 0, user.tz), until=TODAY + timedelta(days=27),
            ),
        ]
        db.add_all(courses)
        db.flush()
        for day in range(30):
            for course in courses:
                for at_time in course.times:
                    if rng.random() < 0.93:
                        db.add(MedIntake(
                            course_id=course.id, user_id=user.id,
                            day=TODAY - timedelta(days=day), at_time=at_time,
                            taken_at=_at(day, int(at_time[:2]), int(at_time[3:]), user.tz),
                        ))

        # --- будущие визиты, чтобы боту было что напоминать ---
        db.add(Reminder(
            user_id=user.id, title="Кардиолог — плановый приём",
            place="Консультативно-диагностический центр, каб. 12",
            at=db_utc(datetime.combine(TODAY + timedelta(days=6), dtime(10, 0)), user_zone(user.tz)),
        ))
        db.add(Reminder(
            user_id=user.id, title="УЗИ почек натощак",
            place="Поликлиника по месту прикрепления",
            at=db_utc(datetime.combine(TODAY + timedelta(days=12), dtime(9, 0)), user_zone(user.tz)),
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
