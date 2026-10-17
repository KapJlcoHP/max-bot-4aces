"""Маршруты пользователя и конструктор шагов."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.db.models import NotificationLog, RouteStep, User
from core.db.seed import build_route_for, load_catalog
from core.schemas import (
    CompleteStepIn,
    CompleteStepOut,
    RouteDto,
    RouteStartIn,
    StepAddIn,
    StepDto,
    StepUpdateIn,
)
from core.services import ServiceError, complete_route_step, uncomplete_route_step
from .common import consented_user, db_session, get_active_route, route_dto, route_template_title, step_dto

router = APIRouter()


@router.get("/route", response_model=RouteDto | None)
def get_route(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    route = get_active_route(db, user.id)
    return route_dto(route) if route else None


@router.delete("/route")
def delete_route(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    route = get_active_route(db, user.id)
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
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название шага не может быть пустым")
    if body.source not in ("user", "doctor"):
        raise HTTPException(status_code=422, detail="Недопустимый источник шага")
    route = get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")

    anchor = None
    if after_step_id:
        anchor = db.query(RouteStep).filter(RouteStep.id == after_step_id, RouteStep.route_id == route.id).first()
        if anchor is None:
            raise HTTPException(status_code=404, detail="Шаг для вставки не найден")
    if anchor is None:
        anchor = db.query(RouteStep).filter(
            RouteStep.route_id == route.id, RouteStep.status == "current"
        ).first()
    if anchor is None:
        anchor = db.query(RouteStep).filter(
            RouteStep.route_id == route.id
        ).order_by(RouteStep.position.desc()).first()

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


@router.delete("/route/steps/{step_id}", response_model=RouteDto | None)
def delete_step(step_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    route = get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise HTTPException(status_code=404, detail="Шаг не найден")
    if step.status == "done":
        raise HTTPException(status_code=409, detail="Пройденный шаг удалить нельзя")

    if db.query(RouteStep).filter(RouteStep.route_id == route.id).count() == 1:
        db.delete(route)
        db.commit()
        return None

    was_current = step.status == "current"
    position = step.position
    db.delete(step)
    db.flush()
    db.query(RouteStep).filter(
        RouteStep.route_id == route.id, RouteStep.position > position
    ).update({"position": RouteStep.position - 1}, synchronize_session=False)
    if was_current:
        next_step = db.query(RouteStep).filter(
            RouteStep.route_id == route.id, RouteStep.status != "done"
        ).order_by(RouteStep.position).first()
        if next_step is not None:
            next_step.status = "current"
    db.commit()
    db.refresh(route)
    return route_dto(route)


@router.post("/route/steps/{step_id}/complete", response_model=CompleteStepOut)
def complete_step(
    step_id: int,
    body: CompleteStepIn | None = None,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    try:
        step = complete_route_step(
            db,
            user.id,
            step_id,
            note=(body.note if body else None),
            done_date=(body.date if body else None),
        )
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    route = get_active_route(db, user.id)
    next_step = db.query(RouteStep).filter(
        RouteStep.route_id == route.id, RouteStep.status != "done"
    ).order_by(RouteStep.position).first()
    return CompleteStepOut(
        step=step_dto(step, route_template_title(route)),
        route=route_dto(route),
        next_step=step_dto(next_step, route_template_title(route)) if next_step else None,
    )


@router.post("/route/steps/{step_id}/uncomplete", response_model=RouteDto)
def uncomplete_step(step_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    try:
        uncomplete_route_step(db, user.id, step_id)
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    route = get_active_route(db, user.id)
    return route_dto(route)


@router.patch("/route/steps/{step_id}", response_model=StepDto)
def update_step(
    step_id: int,
    body: StepUpdateIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    route = get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise HTTPException(status_code=404, detail="Шаг не найден")
    if step.status == "done":
        raise HTTPException(status_code=409, detail="Пройденный шаг изменить нельзя")
    deadline_changed = step.deadline != body.deadline
    step.deadline = body.deadline
    if deadline_changed:
        db.query(NotificationLog).filter(
            NotificationLog.user_id == user.id,
            NotificationLog.kind == "step",
            NotificationLog.ref_id == step.id,
        ).delete(synchronize_session=False)
    db.commit()
    db.refresh(step)
    return step_dto(step, route_template_title(route))
