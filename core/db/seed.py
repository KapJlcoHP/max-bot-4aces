"""Загрузка контента и построение маршрутов. Персональные данные пользователь заводит сам."""

import json
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import Session, object_session

from core.db.models import ChecklistItem, Organization, Route, RouteStep, User

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


def load_catalog() -> list[dict]:
    return json.loads((CONTENT_DIR / "catalog.json").read_text(encoding="utf-8"))["situations"]


def load_scenarios() -> dict:
    return json.loads((CONTENT_DIR / "scenarios.json").read_text(encoding="utf-8"))


def load_sources() -> dict[str, dict]:
    items = json.loads((CONTENT_DIR / "sources.json").read_text(encoding="utf-8"))["sources"]
    return {item["id"]: item for item in items}


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


def _clinic_place(place: str, clinic: Organization | None) -> str:
    """Only explicitly bound scenario fields receive the profile clinic."""
    label = f"{clinic.title}, {clinic.address}" if clinic else "Поликлиника не выбрана — выберите в профиле"
    return place.replace("{clinic}", label)


def _clinic_text(text: str, clinic: Organization | None) -> str:
    return _clinic_place(text, clinic)


def clinic_for_user(db: Session, user: User) -> Organization | None:
    """Return the selected clinic only when it belongs to the user's region."""
    if user.attached_clinic_id is None:
        return None
    return db.query(Organization).filter(
        Organization.id == user.attached_clinic_id,
        Organization.org_type == "Поликлиники",
        Organization.region == user.region,
    ).first()


def clinic_step_display(db: Session, user: User, route: Route, stored: RouteStep) -> dict[str, str]:
    """Read-only projection, including pre-binding saved routes; preserve personal edits/history."""
    result = {"place": stored.place, "description": stored.description}
    if not route.active or stored.status == "done" or stored.source != "template":
        return result
    specs = load_scenarios().get(route.situation_key, {}).get("steps", [])
    matches = [s for s in specs if s["title"] == stored.title and s.get("source_id") == stored.source_id]
    # Ambiguous identity cannot establish a binding. Nor can duplicate saved steps.
    if len(matches) != 1 or sum(s.title == stored.title and s.source_id == stored.source_id and s.source == "template" for s in route.steps) != 1:
        return result
    spec = matches[0]
    clinic = clinic_for_user(db, user)
    old_clinics = None
    for field in result:
        template = spec.get(field, "")
        if "{clinic}" not in template:
            continue
        value = result[field] or ""
        allowed = {template, _clinic_place(template, None)}
        if old_clinics is None:
            old_clinics = db.query(Organization).filter(Organization.org_type == "Поликлиники").all()
        allowed.update(_clinic_place(template, org) for org in old_clinics)
        if field == "place":
            allowed.update({"", "Поликлиника по месту прикрепления", "Поликлиника №12, каб. 304"})
            # The previous formatter incorrectly retained a fictional cabinet.
            allowed.update(f"{org.title}, {org.address}, каб. 304" for org in old_clinics)
        elif route.situation_key == "doctor":
            legacy = {
                "Выбрать поликлинику": "Определена поликлиника по месту прикрепления — №12.",
                "Записаться на приём": "Выбрано удобное время через личный кабинет поликлиники №12.",
            }.get(stored.title)
            if legacy:
                allowed.add(legacy)
                allowed.update(legacy.replace("поликлиники №12", org.title) for org in old_clinics)
        if value in allowed:
            result[field] = _clinic_place(template, clinic)
    return result


def project_step_clinic(stored: RouteStep) -> dict[str, str]:
    db = object_session(stored)
    if db is None:
        return {}
    route = db.get(Route, stored.route_id)
    user = db.get(User, route.user_id) if route else None
    return clinic_step_display(db, user, route, stored) if user else {}


def refresh_route_clinic(db: Session, user: User, route: Route | None = None) -> Route | None:
    route = route or db.query(Route).filter(Route.user_id == user.id, Route.active.is_(True)).first()
    if route is not None:
        for stored in route.steps:
            changes = {field: value for field, value in clinic_step_display(db, user, route, stored).items()
                       if getattr(stored, field) != value}
            if not changes:
                continue
            # A concurrently completed/edited step is a fact, not template content.
            db.execute(update(RouteStep).where(
                RouteStep.id == stored.id, RouteStep.status != "done", RouteStep.source == "template",
                RouteStep.place == stored.place, RouteStep.description == stored.description,
                RouteStep.route_id.in_(db.query(Route.id).filter(Route.active.is_(True), Route.user_id == user.id)),
            ).values(**changes).execution_options(synchronize_session=False))
            db.refresh(stored)
    return route


def seed_organizations(db: Session) -> None:
    """Организации синхронизируем из regions.json при каждом старте:
    идентичность — (регион, название); ID существующих организаций сохраняем."""
    by_identity = {
        (region["title"], item["title"]): {**item, "region": region["title"]}
        for region in load_regions()
        for item in region.get("organizations", [])
    }
    existing: dict[tuple[str, str], list[Organization]] = {}
    for org in db.query(Organization).order_by(Organization.id).all():
        existing.setdefault((org.region, org.title), []).append(org)
    for identity, item in by_identity.items():
        matches = existing.pop(identity, [])
        if matches:
            # Самый ранний ID — стабильная каноническая строка. Остальные
            # дубликаты ниже объединяем, не теряя допустимые прикрепления.
            org = matches.pop(0)
            for key, value in item.items():
                setattr(org, key, value)
        else:
            org = Organization(**item)
            db.add(org)
        for duplicate in matches:
            for user in db.query(User).filter(User.attached_clinic_id == duplicate.id).all():
                user.attached_clinic_id = (
                    org.id if org.org_type == "Поликлиники" and user.region == org.region
                    else None
                )
            db.delete(duplicate)
    for obsolete in existing.values():
        for org in obsolete:
            # Исчезнувшее название не угадываем по другим полям/регионам.
            for user in db.query(User).filter(User.attached_clinic_id == org.id).all():
                user.attached_clinic_id = None
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
    exclude = set(exclude_positions or [])

    if situation_key == "custom":
        route = Route(user_id=user.id, situation_key="custom", title="Мой маршрут", subtitle="Свой маршрут")
        template_steps: list[dict] = []
    else:
        spec = load_scenarios()[situation_key]
        route = Route(user_id=user.id, situation_key=situation_key, title=spec["route_title"])
        template_steps = [s for i, s in enumerate(spec["steps"], start=1) if i not in exclude]

    clinic = clinic_for_user(db, user)

    db.add(route)
    db.flush()

    position = 0
    for step in template_steps:
        status = "current" if position == 0 else "pending"
        position += 1
        db.add(
            RouteStep(
                route_id=route.id,
                position=position,
                title=step["title"],
                description=_clinic_text(step.get("description", ""), clinic),
                place=_clinic_place(step.get("place", ""), clinic),
                deadline=None,
                deadline_time=None,
                status=status,
                has_checklist=step.get("has_checklist", False),
                source="template",
                source_id=step.get("source_id"),
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
                deadline_time=step.get("deadline_time") or step.get("time"),
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
    commit: bool = True,
) -> Route:
    """Новая активная ситуация: прежний активный маршрут гасим, чек-лист обновляем."""
    db.query(Route).filter(Route.user_id == user.id, Route.active.is_(True)).update({"active": False})
    route = _build_route(db, user, situation_key, exclude_positions, custom_steps)
    db.query(ChecklistItem).filter(ChecklistItem.user_id == user.id).delete()
    _seed_checklist(db, user, situation_key)
    if commit:
        db.commit()
    return route
