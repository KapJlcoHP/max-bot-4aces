"""Маршруты пользователя и конструктор шагов."""

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from core.db.models import NotificationLog, Route, RouteAssignmentReceipt, RouteStep, User, utcnow
from core.db.seed import build_route_for, load_catalog
from core.schemas import (
    CompleteStepIn,
    CompleteStepOut,
    RouteDto,
    RouteStartIn,
    StepAddIn,
    StepAssignmentsIn,
    StepAssignmentsOut,
    StepBookingIn,
    StepDto,
    StepUpdateIn,
)
from core.services import (
    ServiceError, complete_route_step, insert_route_steps, lock_route_writes,
    normalize_route_steps, uncomplete_route_step, validate_booking_target,
)
from core.time import normalize_clock_time, strict_local_utc
from .common import consented_user, db_session, get_active_route, route_dto, route_template_title, step_dto

router = APIRouter()


def reminder_setting(body, user, deadline, clock, step=None, schedule_changed=False):
    fields = body.model_fields_set
    mode = body.reminder_mode if "reminder_mode" in fields else (step.reminder_mode if step else "profile")
    moment = step.reminder_at if step else None
    if "reminder_at" in fields:
        try:
            moment = strict_local_utc(body.reminder_at, user.tz) if body.reminder_at is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "deadline" in fields and deadline is None:
        if ("reminder_mode" in fields and mode != "profile") or body.reminder_at is not None:
            raise HTTPException(status_code=422, detail="Напоминание требует даты события")
        return "profile", None
    if mode == "day" and deadline is None:
        raise HTTPException(status_code=422, detail="Напоминание за день требует даты события")
    if mode == "hour" and (deadline is None or clock is None):
        raise HTTPException(status_code=422, detail="Напоминание за час требует даты и точного времени события")
    if mode == "custom":
        if deadline is None or moment is None:
            raise HTTPException(status_code=422, detail="Укажите дату события и время напоминания")
        if step and step.reminder_mode == "custom" and schedule_changed and not {"reminder_mode", "reminder_at"} <= fields:
            raise HTTPException(status_code=422, detail="Срок изменён. Подтвердите время напоминания заново или выберите другой режим")
        unchanged = step and not schedule_changed and (mode, moment) == (step.reminder_mode, step.reminder_at)
        if not unchanged and moment <= utcnow():
            raise HTTPException(status_code=422, detail="Время напоминания должно быть в будущем")
    else:
        if "reminder_at" in fields and body.reminder_at is not None:
            raise HTTPException(status_code=422, detail="Отдельное время допустимо только в режиме «В другое время»")
        moment = None
    return mode, moment


@router.get("/route", response_model=RouteDto | None)
def get_route(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    route = get_active_route(db, user.id)
    return route_dto(route) if route else None


@router.delete("/route")
def delete_route(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    lock_route_writes(db, user.id)
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
    lock_route_writes(db, user.id)
    try:
        route = build_route_for(
            db,
            user,
            body.situation_key,
            exclude_positions=body.exclude_positions,
            custom_steps=[s.model_dump() for s in body.custom_steps],
            commit=False,
        )
    except (ValueError, ServiceError) as exc:
        db.rollback()
        raise HTTPException(status_code=getattr(exc, "status", 422), detail=str(exc)) from exc
    for step in route.steps:
        if step.status == "current":
            step.activated_at = utcnow()
    result = route_dto(route)
    db.commit()
    return result


@router.post("/route/steps", response_model=RouteDto)
def add_step(
    body: StepAddIn,
    after_step_id: int | None = None,
    before_step_id: int | None = None,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название шага не может быть пустым")
    if body.source not in ("user", "doctor"):
        raise HTTPException(status_code=422, detail="Недопустимый источник шага")
    if after_step_id is not None and before_step_id is not None:
        raise HTTPException(status_code=422, detail="Выберите before_step_id или after_step_id")
    lock_route_writes(db, user.id)
    route = get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")

    mode, moment = reminder_setting(body, user, body.deadline, body.deadline_time)
    anchor = None
    anchor_id = before_step_id if before_step_id is not None else after_step_id
    if anchor_id is not None:
        anchor = db.query(RouteStep).filter(RouteStep.id == anchor_id, RouteStep.route_id == route.id).first()
        if anchor is None:
            raise HTTPException(status_code=404, detail="Шаг для вставки не найден")
        if before_step_id is not None and anchor.status == "done":
            raise HTTPException(status_code=409, detail="Нельзя вставить шаг перед историческим шагом")
    if anchor is None:
        anchor = db.query(RouteStep).filter(
            RouteStep.route_id == route.id, RouteStep.status == "current"
        ).first()
    if anchor is None:
        anchor = db.query(RouteStep).filter(
            RouteStep.route_id == route.id
        ).order_by(RouteStep.position.desc()).first()

    step = RouteStep(
        route_id=route.id,
        title=title,
        kind=body.kind,
        appointment_date=body.appointment_date,
        booking_target_step_id=body.booking_target_step_id,
        description="",
        place=body.place or "",
        deadline=body.deadline,
        deadline_time=body.deadline_time,
        reminder_mode=mode,
        reminder_at=moment,
        source=body.source,
    )
    try:
        insert_route_steps(db, route, anchor, [step], before=before_step_id is not None)
        validate_booking_target(db, route, step, body.kind, body.booking_target_step_id)
        result = route_dto(route)
        db.commit()
        return result
    except ServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.delete("/route/steps/{step_id}", response_model=RouteDto | None)
def delete_step(step_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    lock_route_writes(db, user.id)
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

    # Explicitly clear references, including when SQLite FK enforcement is off.
    for linked in db.query(RouteStep).filter_by(route_id=route.id, booking_target_step_id=step.id):
        linked.booking_target_step_id = None
        linked.reminder_revision += 1
    db.flush()
    db.delete(step)
    db.flush()
    normalize_route_steps(db, route)
    result = route_dto(route)
    db.commit()
    return result


@router.post("/route/steps/{step_id}/assignments", response_model=StepAssignmentsOut)
def assign_steps(
    step_id: int,
    body: StepAssignmentsIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    # Canonical validated input: omitted/null optional fields and equivalent
    # clock spellings represent the same operation; anchor is part of identity.
    payload = {"step_id": step_id, **body.model_dump(mode="json", exclude={"request_id"})}
    # S4 receipts predate kind. Default unknown is omitted even if explicitly
    # supplied, preserving their canonical fingerprints byte-for-byte.
    for item in payload["assignments"]:
        if item["kind"] == "unknown":
            item.pop("kind")
        if item["appointment_date"] is None:
            item.pop("appointment_date")
    fingerprint = hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    try:
        lock_route_writes(db, user.id)
        receipt = db.query(RouteAssignmentReceipt).filter_by(
            user_id=user.id, request_id=str(body.request_id),
        ).first()
        if receipt is not None:
            if receipt.fingerprint != fingerprint:
                raise HTTPException(status_code=409, detail="request_id уже использован для другого запроса")
            result = StepAssignmentsOut.model_validate(receipt.response)
            db.commit()
            return result

        route = get_active_route(db, user.id)
        if route is None:
            raise HTTPException(status_code=404, detail="Активный маршрут не найден")
        step = db.query(RouteStep).filter_by(id=step_id, route_id=route.id).first()
        if step is None:
            raise HTTPException(status_code=404, detail="Шаг не найден")
        expected = "current" if body.complete else "done"
        if step.status != expected:
            raise HTTPException(status_code=409, detail="Состояние шага изменилось. Обновите маршрут")
        if step.kind != "visit":
            raise HTTPException(status_code=409, detail="Назначения можно добавить только к врачебному визиту")

        if body.complete:
            step.status = "done"
            step.completed_at = utcnow()
        additions = [RouteStep(**item.model_dump(), description="", source="doctor")
                     for item in body.assignments]
        insert_route_steps(db, route, step, additions)
        snapshot = route_dto(route)
        result = StepAssignmentsOut(
            step=next(s for s in snapshot.steps if s.id == step_id),
            route=snapshot,
            next_step=next((s for s in snapshot.steps if s.status == "current"), None),
            added_step_ids=[s.id for s in additions],
        )
        db.add(RouteAssignmentReceipt(
            user_id=user.id, request_id=str(body.request_id), fingerprint=fingerprint,
            response=result.model_dump(mode="json"),
        ))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post("/route/steps/{step_id}/booking", response_model=CompleteStepOut)
def save_booking(
    step_id: int,
    body: StepBookingIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    payload = {"operation": "booking", "step_id": step_id,
               **body.model_dump(mode="json", exclude={"request_id"})}
    fingerprint = hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    try:
        lock_route_writes(db, user.id)
        receipt = db.query(RouteAssignmentReceipt).filter_by(
            user_id=user.id, request_id=str(body.request_id),
        ).first()
        if receipt is not None:
            if receipt.fingerprint != fingerprint:
                raise HTTPException(status_code=409, detail="request_id уже использован для другого запроса")
            result = CompleteStepOut.model_validate(receipt.response)
            db.commit()
            return result
        route = get_active_route(db, user.id)
        if route is None:
            raise HTTPException(status_code=404, detail="Активный маршрут не найден")
        step = db.query(RouteStep).filter_by(id=step_id, route_id=route.id).first()
        if step is None:
            raise HTTPException(status_code=404, detail="Шаг не найден")
        if step.kind != "booking" or step.status == "done" or (body.complete and step.status != "current"):
            raise HTTPException(status_code=409, detail="Состояние или вид записи изменились. Обновите маршрут")
        target = validate_booking_target(db, route, step, step.kind, body.target_step_id)
        if target is not None and body.appointment_date is not None:
            if body.expected_target_revision is None:
                raise HTTPException(status_code=422, detail="Укажите expected_target_revision")
            if target.reminder_revision != body.expected_target_revision:
                raise HTTPException(status_code=409, detail="Цель изменилась. Обновите маршрут")
            needs_confirmation = (
                (target.deadline is not None and target.deadline != body.appointment_date)
                or target.deadline_time is not None or target.reminder_mode != "profile"
            )
            if needs_confirmation and not body.confirm_target_change:
                raise HTTPException(status_code=409, detail="Подтвердите изменение срока и напоминания цели")
            mode = target.reminder_mode if body.target_reminder_action == "keep" else "profile"
            moment = target.reminder_at if mode == "custom" else None
            if mode == "hour" and not normalize_clock_time(target.deadline_time):
                raise HTTPException(status_code=422, detail="Напоминание за час требует точного времени цели")
            if mode == "custom" and (moment is None or moment <= utcnow()):
                raise HTTPException(status_code=422, detail="Время напоминания должно быть в будущем")
            changed = (target.deadline, target.reminder_mode, target.reminder_at) != (
                body.appointment_date, mode, moment,
            )
            if changed:
                target.deadline = body.appointment_date
                target.reminder_mode, target.reminder_at = mode, moment
                target.reminder_revision += 1
                db.query(NotificationLog).filter_by(
                    user_id=user.id, kind="step", ref_id=target.id,
                ).delete(synchronize_session=False)
        if step.booking_target_step_id != body.target_step_id:
            step.reminder_revision += 1
        step.booking_target_step_id = body.target_step_id
        step.appointment_date = body.appointment_date
        if body.complete:
            step.status, step.completed_at = "done", utcnow()
            normalize_route_steps(db, route)
        db.flush()
        snapshot = route_dto(route)
        result = CompleteStepOut(
            step=next(s for s in snapshot.steps if s.id == step_id), route=snapshot,
            next_step=next((s for s in snapshot.steps if s.status == "current"), None),
        )
        db.add(RouteAssignmentReceipt(
            user_id=user.id, request_id=str(body.request_id), fingerprint=fingerprint,
            response=result.model_dump(mode="json"),
        ))
        db.commit()
        return result
    except ServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


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
            commit=False,
        )
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    route = get_active_route(db, user.id)
    next_step = db.query(RouteStep).filter(
        RouteStep.route_id == route.id, RouteStep.status != "done"
    ).order_by(RouteStep.position).first()
    result = CompleteStepOut(
        step=step_dto(step, route_template_title(route)),
        route=route_dto(route),
        next_step=step_dto(next_step, route_template_title(route)) if next_step else None,
    )
    db.commit()
    return result


@router.post("/route/steps/{step_id}/uncomplete", response_model=RouteDto)
def uncomplete_step(step_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    try:
        uncomplete_route_step(db, user.id, step_id, commit=False)
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e
    route = get_active_route(db, user.id)
    result = route_dto(route)
    db.commit()
    return result


@router.patch("/route/steps/{step_id}", response_model=StepDto, responses={409: {"description": "Шаг выполнен или изменился одновременно; обновите маршрут"}})
def update_step(
    step_id: int,
    body: StepUpdateIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    lock_route_writes(db, user.id)
    route = get_active_route(db, user.id)
    if route is None:
        raise HTTPException(status_code=404, detail="Активный маршрут не найден")
    step = db.query(RouteStep).filter(RouteStep.id == step_id, RouteStep.route_id == route.id).first()
    if step is None:
        raise HTTPException(status_code=404, detail="Шаг не найден")
    fields = body.model_fields_set
    clarify_history = (step.status == "done" and step.kind == "unknown"
                       and fields == {"kind"} and body.kind != "unknown")
    if step.status == "done" and not clarify_history:
        raise HTTPException(status_code=409, detail="Пройденный шаг изменить нельзя")
    if not fields:
        return step_dto(step, route_template_title(route))
    kind = body.kind if "kind" in fields else step.kind
    target_id = body.booking_target_step_id if "booking_target_step_id" in fields else step.booking_target_step_id
    semantic_changed = (kind, target_id) != (step.kind, step.booking_target_step_id)
    try:
        if semantic_changed:
            validate_booking_target(db, route, step, kind, target_id)
            if kind in {"unknown", "booking"} and db.query(RouteStep).filter_by(
                route_id=route.id, booking_target_step_id=step.id,
            ).first() is not None:
                raise ServiceError("Сначала уберите ссылки записей на этот шаг")
        if kind != "booking" and step.appointment_date is not None:
            raise ServiceError("Сначала очистите дату записи через операцию booking")
    except ServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    if kind == "booking" and "deadline_time" in fields and body.deadline_time is not None:
        old_time = normalize_clock_time(step.deadline_time) if step.deadline_time else None
        if old_time != body.deadline_time:
            raise HTTPException(status_code=422, detail="Запись не принимает новое точное время оформления")
    deadline = body.deadline if "deadline" in fields else step.deadline
    deadline_time = body.deadline_time if "deadline_time" in fields else step.deadline_time
    if "deadline" in fields and deadline is None:
        # A date clear also clears its dependent time; contradictory input is
        # rejected by StepUpdateIn before the endpoint is called.
        deadline_time = None
    schedule_fields = {"deadline", "deadline_time", "reminder_mode", "reminder_at"}
    if fields & schedule_fields and deadline is None and deadline_time is not None:
        raise HTTPException(status_code=422, detail="Время шага требует даты")
    # Older rows may contain equivalent noncanonical values such as 8:00.
    old_clock = normalize_clock_time(step.deadline_time) if step.deadline_time else None
    new_clock = normalize_clock_time(deadline_time) if deadline_time else None
    schedule_changed = (step.deadline, old_clock or step.deadline_time) != (deadline, new_clock or deadline_time)
    mode, moment = (reminder_setting(body, user, deadline, new_clock, step, schedule_changed)
                    if fields & schedule_fields else (step.reminder_mode, step.reminder_at))
    reminder_changed = (step.reminder_mode, step.reminder_at) != (mode, moment)
    result = db.execute(update(RouteStep).where(
        RouteStep.id == step.id,
        RouteStep.route_id == route.id,
        (RouteStep.status == "done" if clarify_history else RouteStep.status != "done"),
        RouteStep.reminder_revision == step.reminder_revision,
        RouteStep.route_id.in_(db.query(Route.id).filter(
            Route.user_id == user.id, Route.active.is_(True),
        )),
    ).values(
        deadline=deadline,
        deadline_time=new_clock if "deadline_time" in fields else deadline_time,
        reminder_mode=mode,
        reminder_at=moment,
        kind=kind,
        booking_target_step_id=target_id,
        reminder_revision=step.reminder_revision + int(schedule_changed or reminder_changed or semantic_changed),
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Шаг изменился. Обновите маршрут перед повторным сохранением")
    if schedule_changed or reminder_changed:
        db.query(NotificationLog).filter(
            NotificationLog.user_id == user.id,
            NotificationLog.kind == "step",
            NotificationLog.ref_id == step.id,
        ).delete(synchronize_session=False)
    db.commit()
    db.refresh(step)
    return step_dto(step, route_template_title(route))
