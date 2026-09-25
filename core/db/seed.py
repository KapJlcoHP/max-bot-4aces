"""Загрузка контента и демо-данных. Персональные данные — синтетические (см. content/SOURCES.md)."""

import json
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

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


def _build_route(db: Session, user: User, situation_key: str) -> Route:
    scenarios = load_scenarios()
    spec = scenarios[situation_key]
    today = date.today()
    route = Route(user_id=user.id, situation_key=situation_key, title=spec["route_title"])
    db.add(route)
    db.flush()

    done_count = min(spec.get("done_steps", 0), len(spec["steps"]) - 1)
    for i, step in enumerate(spec["steps"]):
        deadline = today + timedelta(days=step["in_days"]) if "in_days" in step else None
        if i < done_count:
            status = "done"
        elif i == done_count:
            status = "current"
        else:
            status = "pending"
        db.add(
            RouteStep(
                route_id=route.id,
                position=i + 1,
                title=step["title"],
                description=step.get("description", ""),
                place=step.get("place", ""),
                deadline=deadline,
                deadline_time=step.get("time"),
                status=status,
                has_checklist=step.get("has_checklist", False),
                completed_at=utcnow_if_done(status),
            )
        )
    return route


def utcnow_if_done(status: str):
    from core.db.models import utcnow

    return utcnow() if status == "done" else None


def _seed_checklist(db: Session, user: User, situation_key: str) -> None:
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


def _seed_bp(db: Session, user: User) -> None:
    today = date.today()
    # Синтетическая история за две недели — значения в пределах нормы.
    rows = [
        (0, 8, 30, 120, 80, 72),
        (1, 20, 15, 122, 81, 68),
        (3, 9, 5, 125, 83, 75),
        (6, 8, 40, 119, 79, 70),
        (10, 21, 0, 118, 79, 67),
        (11, 8, 20, 124, 82, 73),
        (14, 9, 10, 121, 80, 71),
    ]
    for days_ago, h, m, sys_, dia, pulse in rows:
        db.add(
            BpRecord(
                user_id=user.id,
                at=datetime.combine(today - timedelta(days=days_ago), dtime(h, m)),
                systolic=sys_,
                diastolic=dia,
                pulse=pulse,
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
    _seed_bp(db, user)
    _seed_family(db, user)
    db.commit()


def build_route_for(db: Session, user: User, situation_key: str) -> Route:
    """Новая активная ситуация: прежний активный маршрут гасим, чек-лист обновляем."""
    db.query(Route).filter(Route.user_id == user.id, Route.active.is_(True)).update({"active": False})
    route = _build_route(db, user, situation_key)
    db.query(ChecklistItem).filter(ChecklistItem.user_id == user.id).delete()
    _seed_checklist(db, user, situation_key)
    db.commit()
    return route
