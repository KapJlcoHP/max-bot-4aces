"""Дневники здоровья, отчёт и экспорт PDF."""

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.models import ExportRequest, HealthRecord, HealthSetting, MedCourse, MedIntake, User, utcnow
from core.diary_settings import diary_settings, enabled_diaries
from core.schemas import (
    HealthAddIn,
    HealthRecordDto,
    HealthReportOut,
    HealthSettingsIn,
    HealthSettingsOut,
    ReportMedsRow,
    ReportNote,
)
from core.services import ServiceError, add_health_record as create_health_record, user_today
from core.time import report_window, user_local
from server.deps import AuthError, get_authenticated_user
from server.health_pdf import build_health_pdf
from .common import (
    HEALTH_TYPES,
    consented_user,
    current_user,
    db_session,
    apply_diary_settings,
    validate_diary_settings,
)

router = APIRouter()

# Кратковременные токены экспорта PDF, TTL 5 минут.
_EXPORT_TOKENS: dict[str, tuple[int, datetime]] = {}
_EXPORT_TTL = timedelta(minutes=5)


def _diary_settings(db: Session, user_id: int):
    return diary_settings(db, user_id)


def _get_diary_settings(db: Session, user_id: int) -> dict[str, bool]:
    return enabled_diaries(db, user_id)


@router.get("/health/settings", response_model=HealthSettingsOut)
def health_settings(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    return HealthSettingsOut(diaries=list(_diary_settings(db, user.id).values()))


@router.put("/health/settings", response_model=HealthSettingsOut)
def update_health_settings(
    body: HealthSettingsIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    apply_diary_settings(db, user.id, validate_diary_settings(body.diaries))
    db.commit()
    return health_settings(user=user, db=db)


def _health_record_dto(row: HealthRecord, user: User) -> HealthRecordDto:
    dto = HealthRecordDto.model_validate(row)
    dto.at = user_local(row.at, user.tz)
    return dto


@router.get("/health/{type}/records", response_model=list[HealthRecordDto])
def health_records(
    type: str,
    limit: int = Query(default=100, le=500),
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    if type not in HEALTH_TYPES:
        raise HTTPException(status_code=404, detail="Неизвестный дневник")
    rows = db.query(HealthRecord).filter(
        HealthRecord.user_id == user.id, HealthRecord.type == type
    ).order_by(HealthRecord.at.desc()).limit(limit).all()
    return [_health_record_dto(r, user) for r in rows]


@router.post("/health/export-token")
def create_export_token(user: User = Depends(consented_user)):
    token = uuid.uuid4().hex
    _EXPORT_TOKENS[token] = (user.id, utcnow() + _EXPORT_TTL)
    for t, (_, exp) in list(_EXPORT_TOKENS.items()):
        if exp < utcnow():
            _EXPORT_TOKENS.pop(t, None)
    return {"token": token, "ttl_seconds": int(_EXPORT_TTL.total_seconds())}


@router.post("/health/send-to-bot")
def request_pdf_in_chat(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    active = db.query(ExportRequest).filter(
        ExportRequest.user_id == user.id,
        ExportRequest.sent_at.is_(None),
        ExportRequest.status.notin_(("failed", "sent")),
    ).order_by(ExportRequest.id.desc()).first()
    if active is not None:
        return {
            "status": active.status,
            "request_id": active.id,
            "hint": "Заявка уже в очереди — PDF придёт в чат бота после обработки",
        }
    row = ExportRequest(user_id=user.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = db.query(ExportRequest).filter(
            ExportRequest.user_id == user.id,
            ExportRequest.sent_at.is_(None),
            ExportRequest.status.notin_(("failed", "sent")),
        ).order_by(ExportRequest.id.desc()).first()
        if active is None:
            raise
        return {"status": active.status, "request_id": active.id, "hint": "Заявка уже в очереди"}
    return {"status": row.status, "request_id": row.id, "hint": "PDF придёт в чат бота через несколько секунд"}


@router.get("/health/send-to-bot")
def pdf_in_chat_status(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    row = db.query(ExportRequest).filter_by(user_id=user.id).order_by(ExportRequest.id.desc()).first()
    if row is None:
        return {"status": "idle", "request_id": None, "attempts": 0, "can_retry": False}
    return {
        "status": row.status,
        "request_id": row.id,
        "attempts": row.attempts,
        "can_retry": row.status == "failed",
        "next_attempt_at": user_local(row.next_attempt_at, user.tz) if row.next_attempt_at else None,
        "sent_at": user_local(row.sent_at, user.tz) if row.sent_at else None,
        "error": row.last_error,
        "hint": "Не удалось доставить PDF. Повторите запрос отправки." if row.status == "failed" else None,
    }


def health_report_impl(
    user: User,
    db: Session,
    *,
    now_fn=utcnow,
    get_diary_settings_fn=_get_diary_settings,
):
    """Сводка для врача: агрегаты за 30 дней по включённым дневникам."""
    now = now_fn()
    period_start, period_end, local_start, local_now = report_window(now, user.tz)
    enabled = get_diary_settings_fn(db, user.id)
    out = HealthReportOut()
    out._window_now = now

    def rows(t: str) -> list[HealthRecord]:
        return db.query(HealthRecord).filter(
            HealthRecord.user_id == user.id,
            HealthRecord.type == t,
            HealthRecord.at >= period_start,
            HealthRecord.at <= period_end,
        ).order_by(HealthRecord.at).all()

    if enabled.get("bp"):
        bp = rows("bp")
        if bp:
            out.bp_count = len(bp)
            out.bp_avg = f"{round(sum(r.systolic for r in bp) / len(bp))}/{round(sum(r.diastolic for r in bp) / len(bp))}"
            pulses = [r.pulse for r in bp if r.pulse is not None]
            out.pulse_avg = round(sum(pulses) / len(pulses)) if pulses else None
    if enabled.get("weight"):
        weight = rows("weight")
        if weight:
            out.weight_count = len(weight)
            out.weight_latest = weight[-1].weight_kg
            out.weight_delta = round(weight[-1].weight_kg - weight[0].weight_kg, 1)
    if enabled.get("sugar"):
        sugar = rows("sugar")
        if sugar:
            out.sugar_count = len(sugar)
            out.sugar_avg = round(sum(r.sugar_mmol for r in sugar) / len(sugar), 1)
    if enabled.get("mood"):
        notes = db.query(HealthRecord).filter(
            HealthRecord.user_id == user.id,
            HealthRecord.type.in_([diary for diary, on in enabled.items() if on]),
            HealthRecord.note.is_not(None),
            HealthRecord.at >= period_start,
            HealthRecord.at <= period_end,
        ).order_by(HealthRecord.at.desc()).limit(5).all()
        out.notes = [ReportNote(at=user_local(n.at, user.tz), note=n.note) for n in notes]

    today = local_now.date()
    period_start_day = local_start.date()
    for course in db.query(MedCourse).filter(
        MedCourse.user_id == user.id, MedCourse.enabled.is_(True)
    ).all():
        first_intake = db.query(MedIntake.day).filter(
            MedIntake.course_id == course.id,
            MedIntake.taken_at.is_not(None),
            MedIntake.day >= period_start_day,
        ).order_by(MedIntake.day).first()
        created_at = course.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        course_start = user_today(user, created_at) if created_at else period_start_day
        if first_intake:
            course_start = min(course_start, first_intake[0])
        start = max(course_start, period_start_day)
        end = min(course.until, today) if course.until else today
        if start > end:
            continue
        days = (end - start).days + 1
        planned = days * len(course.times)
        taken = db.query(MedIntake).filter(
            MedIntake.course_id == course.id,
            MedIntake.taken_at.is_not(None),
            MedIntake.day >= start,
            MedIntake.day <= end,
        ).count()
        taken = min(taken, planned)
        out.meds.append(ReportMedsRow(
            name=course.name,
            taken=taken,
            planned=planned,
            pct=round(100 * taken / planned) if planned else 0,
        ))
    return out


@router.get("/health/export")
def export_health_pdf(
    request: Request,
    t: str | None = Query(default=None),
    db: Session = Depends(db_session),
):
    return export_health_pdf_impl(request, t, db)


def export_health_pdf_impl(
    request: Request,
    t: str | None,
    db: Session,
    *,
    auth_fn=get_authenticated_user,
    report_fn=health_report_impl,
    diary_settings_fn=_get_diary_settings,
    pdf_builder=build_health_pdf,
):
    user: User | None = None
    if t is not None:
        entry = _EXPORT_TOKENS.pop(t, None)
        if entry is None or entry[1] < utcnow():
            raise HTTPException(status_code=401, detail="Ссылка недействительна или устарела")
        user = db.get(User, entry[0])
    else:
        try:
            user = auth_fn(
                db,
                request.headers.get("X-Max-Init-Data"),
                test_token=request.headers.get("X-Test-Token"),
            )
        except AuthError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    if user.consent_at is None:
        raise HTTPException(status_code=403, detail="consent_required")

    report = report_fn(user=user, db=db)
    enabled = diary_settings_fn(db, user.id)
    data = pdf_builder(db, user, report, enabled)
    stamp = user_local(utcnow(), user.tz).strftime("%d.%m.%Y")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="medroute-svodka-{stamp}.pdf"'},
    )


@router.post("/health/{type}", response_model=HealthRecordDto)
def add_health_record(
    type: str,
    body: HealthAddIn,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    try:
        return _health_record_dto(create_health_record(db, user.id, type, **body.model_dump()), user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


@router.delete("/health/{type}/{record_id}")
def delete_health_record(
    type: str,
    record_id: int,
    user: User = Depends(consented_user),
    db: Session = Depends(db_session),
):
    if type not in HEALTH_TYPES:
        raise HTTPException(status_code=404, detail="Неизвестный дневник")
    row = db.query(HealthRecord).filter(
        HealthRecord.id == record_id,
        HealthRecord.user_id == user.id,
        HealthRecord.type == type,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@router.get("/health/report", response_model=HealthReportOut)
def health_report(user: User = Depends(consented_user), db: Session = Depends(db_session)):
    return health_report_impl(user, db)
