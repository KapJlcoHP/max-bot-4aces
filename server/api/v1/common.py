"""Общие зависимости и преобразования для API v1."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.db.models import HealthSetting, Route, RouteStep, User
from core.db.session import SessionLocal
from core.db.seed import load_catalog, load_sources
from core.schemas import ContentSourceDto, HealthSettingDto, RouteDto, StepDto
from core.diary_settings import DIARIES
from server.deps import AuthError, PendingUser, get_authenticated_user

HEALTH_TYPES = set(DIARIES)


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(db_session)) -> User | PendingUser:
    try:
        return get_authenticated_user(
            db,
            request.headers.get("X-Max-Init-Data"),
            test_token=request.headers.get("X-Test-Token"),
        )
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


def consented_user(user: User | PendingUser = Depends(current_user)) -> User:
    """Маршруты и записи доступны после сохранения согласия."""
    if isinstance(user, PendingUser) or user.consent_at is None:
        raise HTTPException(status_code=403, detail="consent_required")
    return user


def route_template_title(route: Route) -> str:
    return next((item["title"] for item in load_catalog() if item["key"] == route.situation_key), route.title)


def step_dto(step: RouteStep, template_title: str, sources: dict[str, dict] | None = None) -> StepDto:
    dto = StepDto.model_validate(step)
    if step.source == "template":
        dto.reason = f"Входит в маршрут «{template_title}», который вы выбрали при создании маршрута."
        if step.source_id:
            source = (load_sources() if sources is None else sources).get(step.source_id)
            if source is not None:
                dto.source_info = ContentSourceDto.model_validate(source)
    elif step.source == "doctor":
        dto.reason = "Назначение врача — внесено вами."
    elif step.source == "user":
        dto.reason = "Ваш шаг — добавлен вами в маршрут."
    else:
        dto.reason = "Происхождение этого шага не указано."
    if step.source != "template":
        dto.source_id = None
    return dto


def route_dto(route: Route) -> RouteDto:
    template_title = route_template_title(route)
    sources = load_sources()
    steps = [step_dto(s, template_title, sources) for s in route.steps]
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


def validate_diary_settings(diaries: list[HealthSettingDto]) -> list[tuple[str, bool, str | None]]:
    """Проверить весь набор до первой записи в БД."""
    from datetime import time as dtime

    normalized: list[tuple[str, bool, str | None]] = []
    seen: set[str] = set()
    for item in diaries:
        if item.diary not in HEALTH_TYPES or item.diary in seen:
            raise HTTPException(status_code=422, detail=f"Неизвестный или повторный дневник: {item.diary}")
        seen.add(item.diary)
        push_time = (item.push_time or "").strip() or None
        if push_time:
            try:
                dtime.fromisoformat(push_time)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"Некорректное время: {push_time}") from e
        normalized.append((item.diary, item.enabled, push_time))
    return normalized


def apply_diary_settings(
    db: Session, user_id: int, normalized: list[tuple[str, bool, str | None]]
) -> None:
    """Сохранить проверенные настройки в текущей транзакции."""
    for diary, enabled, push_time in normalized:
        row = db.query(HealthSetting).filter(
            HealthSetting.user_id == user_id,
            HealthSetting.diary == diary,
        ).first()
        if row is None:
            db.add(HealthSetting(user_id=user_id, diary=diary, enabled=enabled, push_time=push_time))
        else:
            row.enabled = enabled
            row.push_time = push_time


def get_active_route(db: Session, user_id: int) -> Route | None:
    return db.query(Route).filter(Route.user_id == user_id, Route.active.is_(True)).first()
