"""Загрузка контента и построение маршрутов. Персональные данные пользователь заводит сам."""

import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from core.db.models import ChecklistItem, Organization, Route, RouteStep, User

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


def load_catalog() -> list[dict]:
    return json.loads((CONTENT_DIR / "catalog.json").read_text(encoding="utf-8"))["situations"]


def load_scenarios() -> dict:
    return json.loads((CONTENT_DIR / "scenarios.json").read_text(encoding="utf-8"))


def load_regions() -> list[dict]:
    """Регионы и их организации — единственный источник content/regions.json:
    добавить регион или организацию = правка файла, код не трогаем."""
    return json.loads((CONTENT_DIR / "regions.json").read_text(encoding="utf-8"))["regions"]


def pilot_region() -> str:
    """Регион пилотного запуска (pilot: true) — дефолт для новых пользователей."""
    for region in load_regions():
        if region.get("pilot", False):
            return region["title"]
    return ""


def seed_organizations(db: Session) -> None:
    """Организации синхронизируем из regions.json при каждом старте:
    обновляем существующие по названию, добавляем новые, удаляем исчезнувшие."""
    by_title = {
        item["title"]: {**item, "region": region["title"]}
        for region in load_regions()
        for item in region.get("organizations", [])
    }
    existing = {org.title: org for org in db.query(Organization).all()}
    for title, item in by_title.items():
        if title in existing:
            org = existing.pop(title)
            for key, value in item.items():
                setattr(org, key, value)
        else:
            db.add(Organization(**item))
    for org in existing.values():
        db.delete(org)
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

    position = 0
    for step in template_steps:
        deadline = today + timedelta(days=step["in_days"]) if "in_days" in step else None
        status = "current" if position == 0 else "pending"
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
                collected=False,  # новый маршрут — чек-лист всегда с нуля
                position=pos,
            )
        )


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
