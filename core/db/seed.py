"""Загрузка контента и демо-данных. Персональные данные — синтетические (см. content/SOURCES.md)."""

import json
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from core.db.models import (
    ChecklistItem,
    FamilyMember,
    HealthRecord,
    HealthSetting,
    MedCourse,
    MedIntake,
    Organization,
    Reminder,
    Route,
    RouteStep,
    User,
    utcnow,
)

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


def load_catalog() -> list[dict]:
    return json.loads((CONTENT_DIR / "catalog.json").read_text(encoding="utf-8"))["situations"]


def load_scenarios() -> dict:
    return json.loads((CONTENT_DIR / "scenarios.json").read_text(encoding="utf-8"))


def load_orgs() -> list[dict]:
    return json.loads((CONTENT_DIR / "organizations.json").read_text(encoding="utf-8"))["organizations"]


def seed_organizations(db: Session) -> None:
    """Справочник организаций — модельные данные, засеиваем один раз."""
    if db.query(Organization).count() > 0:
        return
    for item in load_orgs():
        db.add(Organization(**item))
    db.commit()


def _build_route(
    db: Session,
    user: User,
    situation_key: str,
    exclude_positions: list[int] | None = None,
    custom_steps: list[dict] | None = None,
) -> Route:
    """Маршрут из шаблона (с возможным выключением шагов) или с нуля + свои шаги в конце.

    exclude_positions — 1-based позиции шагов шаблона, которые пользователь выключил в конструкторе.
    """
    today = date.today()
    exclude = set(exclude_positions or [])

    if situation_key == "custom":
        route = Route(user_id=user.id, situation_key="custom", title="Мой маршрут", subtitle="Свой маршрут")
        template_steps: list[dict] = []
    else:
        spec = load_scenarios()[situation_key]
        route = Route(user_id=user.id, situation_key=situation_key, title=spec["route_title"])
        template_steps = [s for i, s in enumerate(spec["steps"], start=1) if i not in exclude]

    db.add(route)
    db.flush()

    done_count = min(max(load_scenarios().get(situation_key, {}).get("done_steps", 0), 0), max(len(template_steps) - 1, 0))
    position = 0
    for step in template_steps:
        deadline = today + timedelta(days=step["in_days"]) if "in_days" in step else None
        status = "done" if position < done_count else ("current" if position == done_count else "pending")
        position += 1
        db.add(
            RouteStep(
                route_id=route.id,
                position=position,
                title=step["title"],
                description=step.get("description", ""),
                place=step.get("place", ""),
                deadline=deadline,
                deadline_time=step.get("time"),
                status=status,
                has_checklist=step.get("has_checklist", False),
                source="template",
                completed_at=utcnow() if status == "done" else None,
            )
        )
    for step in custom_steps or []:
        deadline = step.get("deadline")
        position += 1
        db.add(
            RouteStep(
                route_id=route.id,
                position=position,
                title=step["title"],
                description="",
                place=step.get("place", ""),
                deadline=deadline,
                deadline_time=step.get("time"),
                status="pending",
                source="user",
            )
        )
    steps = db.query(RouteStep).filter(RouteStep.route_id == route.id).order_by(RouteStep.position).all()
    if steps and not any(s.status == "current" for s in steps):
        steps[0].status = "current"
    return route


def _seed_checklist(db: Session, user: User, situation_key: str) -> None:
    if situation_key == "custom":
        return
    spec = load_scenarios()[situation_key]
    for pos, item in enumerate(spec.get("checklist", [])):
        db.add(
            ChecklistItem(
                user_id=user.id,
                title=item["title"],
                collected=item.get("collected", False),
                position=pos,
            )
        )


def _seed_reminders(db: Session, user: User) -> None:
    today = date.today()
    at = datetime.combine
    db.add_all(
        [
            Reminder(
                user_id=user.id,
                title="Сдать анализы крови",
                place="Клинико-диагностическая лаборатория",
                at=at(today + timedelta(days=1), dtime(10, 0)),
            ),
            Reminder(
                user_id=user.id,
                title="Приём у терапевта",
                place="Городская поликлиника №12, каб. 304",
                at=at(today + timedelta(days=6), dtime(11, 30)),
            ),
            Reminder(
                user_id=user.id,
                title="Запись к врачу",
                place="Регистратура поликлиники",
                at=at(today - timedelta(days=14), dtime(15, 0)),
                enabled=False,
            ),
        ]
    )


def _seed_health(db: Session, user: User) -> None:
    """Синтетическая история дневников: АД за две недели, вес по субботам, самочувствие."""
    today = date.today()
    at = datetime.combine
    bp_rows = [
        (0, 8, 30, 120, 80, 72, "утром"),
        (1, 20, 15, 122, 81, 68, "вечером"),
        (3, 9, 5, 125, 83, 75, "утром"),
        (6, 8, 40, 119, 79, 70, "утром"),
        (10, 21, 0, 118, 79, 67, "вечером"),
        (11, 8, 20, 124, 82, 73, "утром"),
        (14, 9, 10, 121, 80, 71, "утром"),
    ]
    for days_ago, h, m, sys_, dia, pulse, tag in bp_rows:
        db.add(
            HealthRecord(
                user_id=user.id,
                type="bp",
                at=at(today - timedelta(days=days_ago), dtime(h, m)),
                systolic=sys_,
                diastolic=dia,
                pulse=pulse,
                tag=tag,
            )
        )
    # ближайшие 4 субботы назад, утром натощак
    saturday = today - timedelta(days=(today.weekday() + 1) % 7)
    for i, kg in enumerate([84.2, 85.0, 85.8, 86.6], start=1):
        db.add(
            HealthRecord(
                user_id=user.id,
                type="weight",
                at=at(saturday - timedelta(weeks=i - 1), dtime(8, 0)),
                weight_kg=kg,
                tag="утром",
            )
        )
    db.add_all(
        [
            HealthRecord(
                user_id=user.id, type="mood", at=at(today - timedelta(days=1), dtime(21, 0)),
                mood="Хорошо", pain=2, tag="вечером",
            ),
            HealthRecord(
                user_id=user.id, type="mood", at=at(today - timedelta(days=2), dtime(21, 10)),
                mood="Нормально", pain=3, tag="вечером", note="Головная боль к вечеру",
            ),
            HealthRecord(
                user_id=user.id, type="mood", at=at(today - timedelta(days=3), dtime(20, 45)),
                mood="Хорошо", pain=None, tag="вечером",
            ),
        ]
    )


def _seed_health_settings(db: Session, user: User) -> None:
    for diary, enabled in [("bp", True), ("weight", True), ("sugar", False), ("mood", True)]:
        db.add(HealthSetting(user_id=user.id, diary=diary, enabled=enabled))


def _seed_meds(db: Session, user: User) -> None:
    """Два демо-курса; первый приём Магния сегодня уже отмечен."""
    today = date.today()
    magnesium = MedCourse(user_id=user.id, name="Магний B6", times=["08:00", "13:00"], until=today + timedelta(days=19))
    vitamin_d = MedCourse(user_id=user.id, name="Витамин D", times=["21:00"], until=today + timedelta(days=34))
    db.add_all([magnesium, vitamin_d])
    db.flush()
    db.add(
        MedIntake(
            course_id=magnesium.id,
            user_id=user.id,
            day=today,
            at_time="08:00",
            taken_at=datetime.combine(today, dtime(8, 4)),
        )
    )


def _seed_family(db: Session, user: User) -> None:
    db.add_all(
        [
            FamilyMember(owner_id=user.id, name="Иван Иванов", role="Отец", color="pink"),
            FamilyMember(owner_id=user.id, name="Ольга Иванова", role="Супруга", color="yellow"),
            FamilyMember(owner_id=user.id, name="Максим Иванов", role="Сын", color="blue"),
        ]
    )


def seed_demo_user(db: Session, user: User) -> None:
    """При первом входе пользователя выдаём демо-состояние (синтетика)."""
    _build_route(db, user, "doctor")
    _seed_checklist(db, user, "doctor")
    _seed_reminders(db, user)
    _seed_health(db, user)
    _seed_health_settings(db, user)
    _seed_meds(db, user)
    _seed_family(db, user)
    db.commit()


def build_route_for(
    db: Session,
    user: User,
    situation_key: str,
    exclude_positions: list[int] | None = None,
    custom_steps: list[dict] | None = None,
) -> Route:
    """Новая активная ситуация: прежний активный маршрут гасим, чек-лист обновляем."""
    db.query(Route).filter(Route.user_id == user.id, Route.active.is_(True)).update({"active": False})
    route = _build_route(db, user, situation_key, exclude_positions, custom_steps)
    db.query(ChecklistItem).filter(ChecklistItem.user_id == user.id).delete()
    _seed_checklist(db, user, situation_key)
    db.commit()
    return route
