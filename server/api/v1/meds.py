"""Лекарственные курсы и отметки приёма."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.db.models import MedCourse, MedIntake, User
from core.schemas import MedAddIn, MedCourseDto, MedIntakeToggleIn, MedSlotDto, MedsOut
from core.services import ServiceError, take_med, user_today
from core.time import normalize_clock_time, user_local
from .common import consented_user, db_session

router = APIRouter()


def _meds_out(db: Session, user: User) -> MedsOut:
    today = user_today(user)
    # Keep completed courses in the response: they are part of the user's
    # medication history. Only active courses contribute slots below, so a
    # completed course cannot accidentally re-enable its daily schedule.
    courses = db.query(MedCourse).filter(
        MedCourse.user_id == user.id
    ).order_by(MedCourse.created_at).all()
    intakes = db.query(MedIntake).filter(
        MedIntake.user_id == user.id, MedIntake.day == today
    ).all()
    taken_map = {(i.course_id, i.at_time): i for i in intakes}
    slots: list[MedSlotDto] = []
    course_dtos: list[MedCourseDto] = []
    for c in courses:
        canonical_times = sorted({normalize_clock_time(t) for t in c.times if normalize_clock_time(t) is not None})
        course_dtos.append(MedCourseDto(
            id=c.id,
            name=c.name,
            times=canonical_times,
            until=c.until,
            enabled=c.enabled,
        ))
        if not c.enabled or (c.until is not None and c.until < today):
            continue
        for t in canonical_times:
            intake = next(
                (row for (course_id, raw_time), row in taken_map.items()
                 if course_id == c.id and normalize_clock_time(raw_time) == t),
                None,
            )
            slots.append(MedSlotDto(
                course_id=c.id,
                name=c.name,
                at_time=t,
                taken=intake is not None and intake.taken_at is not None,
                taken_at=user_local(intake.taken_at, user.tz) if intake and intake.taken_at else None,
            ))
    slots.sort(key=lambda s: s.at_time)
    return MedsOut(courses=course_dtos, today=slots)


@router.get("/meds", response_model=MedsOut)
def meds(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    return _meds_out(db, user)


@router.post("/meds", response_model=MedsOut)
def add_med(body: MedAddIn, user: User = Depends(consented_user), db: Session = Depends(db_session)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    times: list[str] = []
    for raw_time in body.times:
        canonical = normalize_clock_time(raw_time)
        if canonical is None:
            raise HTTPException(status_code=422, detail=f"Некорректное время: {raw_time}")
        times.append(canonical)
    db.add(MedCourse(user_id=user.id, name=name, times=sorted(set(times)), until=body.until))
    db.commit()
    return _meds_out(db, user)


@router.post("/meds/{course_id}/intake-toggle", response_model=MedSlotDto)
def toggle_intake(
    course_id: int,
    body: MedIntakeToggleIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    raw_at_time = body.at_time.strip()
    at_time = normalize_clock_time(raw_at_time)
    if at_time is None:
        raise HTTPException(status_code=422, detail="Некорректное время приёма")
    course = db.query(MedCourse).filter(
        MedCourse.id == course_id, MedCourse.user_id == user.id
    ).first()
    if course is None:
        raise HTTPException(status_code=404, detail="Курс или время приёма не найдены")
    matching_time = next((raw for raw in course.times if normalize_clock_time(raw) == at_time), None)
    if matching_time is None:
        raise HTTPException(status_code=404, detail="Курс или время приёма не найдены")
    if course.times != [normalize_clock_time(raw) or raw for raw in course.times]:
        course.times = sorted({normalize_clock_time(raw) or raw for raw in course.times})
        db.flush()
    intake = db.query(MedIntake).filter(
        MedIntake.course_id == course.id,
        MedIntake.day == user_today(user),
    ).all()
    intake = next((row for row in intake if normalize_clock_time(row.at_time) == at_time), None)
    if intake is not None:
        # Legacy rows may contain ``8:00``/``08:00:00``.  Canonicalize the
        # existing row before delegating to the shared idempotent service.
        intake.at_time = at_time
        db.flush()
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
