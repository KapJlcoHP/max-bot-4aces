"""Лекарственные курсы и отметки приёма."""

from datetime import time as dtime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.db.models import MedCourse, MedIntake, User
from core.schemas import MedAddIn, MedCourseDto, MedSlotDto, MedsOut
from core.services import ServiceError, take_med, user_today
from core.time import user_local
from .common import consented_user, db_session

router = APIRouter()


def _meds_out(db: Session, user: User) -> MedsOut:
    today = user_today(user)
    courses = db.query(MedCourse).filter(
        MedCourse.user_id == user.id, MedCourse.enabled.is_(True)
    ).order_by(MedCourse.created_at).all()
    intakes = db.query(MedIntake).filter(
        MedIntake.user_id == user.id, MedIntake.day == today
    ).all()
    taken_map = {(i.course_id, i.at_time): i for i in intakes}
    slots: list[MedSlotDto] = []
    for c in courses:
        if c.until is not None and c.until < today:
            continue
        for t in c.times:
            intake = taken_map.get((c.id, t))
            slots.append(MedSlotDto(
                course_id=c.id,
                name=c.name,
                at_time=t,
                taken=intake is not None and intake.taken_at is not None,
                taken_at=user_local(intake.taken_at, user.tz) if intake and intake.taken_at else None,
            ))
    slots.sort(key=lambda s: s.at_time)
    return MedsOut(courses=[MedCourseDto.model_validate(c) for c in courses], today=slots)


@router.get("/meds", response_model=MedsOut)
def meds(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    return _meds_out(db, user)


@router.post("/meds", response_model=MedsOut)
def add_med(body: MedAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    for t in body.times:
        try:
            dtime.fromisoformat(t)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Некорректное время: {t}")
    db.add(MedCourse(user_id=user.id, name=name, times=sorted(set(body.times)), until=body.until))
    db.commit()
    return _meds_out(db, user)


@router.post("/meds/{course_id}/intake-toggle", response_model=MedSlotDto)
def toggle_intake(
    course_id: int,
    body: dict,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    at_time = str((body or {}).get("at_time", "")).strip()
    course = db.query(MedCourse).filter(
        MedCourse.id == course_id, MedCourse.user_id == user.id
    ).first()
    if course is None or at_time not in course.times:
        raise HTTPException(status_code=404, detail="Курс или время приёма не найдены")
    intake = db.query(MedIntake).filter(
        MedIntake.course_id == course.id,
        MedIntake.day == user_today(user),
        MedIntake.at_time == at_time,
    ).first()
    undo = intake is not None and intake.taken_at is not None
    if undo:
        intake.taken_at = None
        db.commit()
    else:
        try:
            intake = take_med(db, user.id, course_id, at_time)
        except ServiceError as e:
            raise HTTPException(status_code=e.status, detail=str(e)) from e
    return MedSlotDto(
        course_id=course.id,
        name=course.name,
        at_time=at_time,
        taken=intake.taken_at is not None,
        taken_at=user_local(intake.taken_at, user.tz) if intake.taken_at else None,
    )


@router.post("/meds/{course_id}/disable", response_model=MedsOut)
def disable_med(course_id: int, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    course = db.query(MedCourse).filter(
        MedCourse.id == course_id, MedCourse.user_id == user.id
    ).first()
    if course is None:
        raise HTTPException(status_code=404, detail="Курс не найден")
    course.enabled = False
    db.commit()
    return _meds_out(db, user)
