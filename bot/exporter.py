"""Отправка PDF-сводки в чат бота.

На телефонах вебвью MAX блокирует скачивание файлов, поэтому файл доставляет бот:
мини-ап кладёт заявку (export_requests через API), вотчер каждые 3 с забирает,
собирает PDF тем же кодом, что и веб-экспорт, и шлёт файлом в чат.
Та же функция используется командой /svodka в самом боте.
"""

import asyncio
import logging
from datetime import timedelta

from maxapi import Bot
from maxapi.enums.upload_type import UploadType
from maxapi.types import InputMediaBuffer
from sqlalchemy.orm import Session

from core.db.models import ExportRequest, User, utcnow
from core.db.session import SessionLocal
from core.export_queue import MAX_ATTEMPTS, RETRY_DELAYS_SECONDS
from core.time import user_local
from core.time import db_utc
from server.api.v1.api import _get_diary_settings, health_report
from server.health_pdf import build_health_pdf

log = logging.getLogger("bot.exporter")

WATCH_SECONDS = 3
BACKOFF_CAP_SECONDS = 15 * 60
LEASE_SECONDS = 5 * 60

PDF_CAPTION = "📄 Сводка для врача за 30 дней — можно показать на приёме или сохранить."


def _build_pdf(db: Session, user: User) -> tuple[bytes, str]:
    """Тот же PDF, что и в веб-экспорте (GET /health/export)."""
    report = health_report(user=user, db=db)
    enabled = _get_diary_settings(db, user.id)
    data = build_health_pdf(db, user, report, enabled)
    stamp = user_local(utcnow(), user.tz).strftime("%d.%m.%Y")
    return data, f"medroute-svodka-{stamp}.pdf"


def _build_pdf_in_thread(user_id: int) -> tuple[bytes, str]:
    """Открыть SQLAlchemy-сессию в том же потоке, где строится PDF."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise ValueError(f"Пользователь не найден: {user_id}")
        return _build_pdf(db, user)


async def send_health_pdf(bot: Bot, db: Session, user: User) -> None:
    # reportlab синхронный и тяжёлый — в отдельный поток, чтобы не замораживать event loop
    # Сессию нельзя переносить из event loop в worker thread: SQLite/SQLAlchemy
    # привязывает соединение к потоку. Поэтому worker открывает свою сессию.
    data, filename = await asyncio.to_thread(_build_pdf_in_thread, user.id)
    attachment = await bot.upload_media(
        InputMediaBuffer(data, filename=filename, type=UploadType.FILE)
    )
    await bot.send_message(user_id=user.max_user_id, text=PDF_CAPTION, attachments=[attachment])


async def export_watcher_loop(bot: Bot) -> None:
    """Забирает заявки из export_requests и шлёт файл в чат."""
    while True:
        try:
            with SessionLocal() as db:
                rows = (
                    db.query(ExportRequest)
                    .filter(
                        ExportRequest.sent_at.is_(None),
                        # Processing восстанавливается после истечения lease.
                        ExportRequest.status.in_(("queued", "retry", "processing")),
                        ExportRequest.attempts < MAX_ATTEMPTS,
                        (ExportRequest.next_attempt_at.is_(None) | (ExportRequest.next_attempt_at <= db_utc(utcnow()))),
                    )
                    .order_by(ExportRequest.id)
                    .limit(5)
                    .all()
                )
                for row in rows:
                    user = db.get(User, row.user_id)
                    if user is None:
                        row.sent_at = utcnow()
                        row.status = "failed"
                        row.last_error = "Пользователь не найден"
                        db.commit()
                        continue
                    # Фиксируем claim до сетевой/CPU-работы. attempts меняется
                    # только после фактического вызова send_health_pdf.
                    now = db_utc(utcnow())
                    claimed = db.query(ExportRequest).filter(
                        ExportRequest.id == row.id,
                        ExportRequest.sent_at.is_(None),
                        ExportRequest.status.in_(("queued", "retry", "processing")),
                        (ExportRequest.next_attempt_at.is_(None) | (ExportRequest.next_attempt_at <= now)),
                    ).update({
                        "status": "processing",
                        "next_attempt_at": now + timedelta(seconds=LEASE_SECONDS),
                    }, synchronize_session=False)
                    db.commit()
                    if not claimed:
                        continue
                    db.refresh(row)
                    try:
                        await send_health_pdf(bot, db, user)
                    except Exception as exc:
                        row.attempts += 1
                        # Не сохраняем payload/URL/токены из текста SDK-ошибки.
                        row.last_error = f"{type(exc).__name__}: Не удалось сформировать или доставить PDF"
                        if row.attempts >= MAX_ATTEMPTS:
                            row.status = "failed"
                            row.next_attempt_at = None
                        else:
                            row.status = "retry"
                            # 30 с → 2 мин → 5 мин → 15 мин. Это переживает
                            # краткий сетевой сбой, не удерживая заявку бесконечно.
                            delay = min(BACKOFF_CAP_SECONDS, RETRY_DELAYS_SECONDS[row.attempts - 1])
                            row.next_attempt_at = db_utc(utcnow()) + timedelta(seconds=delay)
                        db.commit()
                        log.exception("PDF не отправлен: заявка #%s (попытка %s)", row.id, row.attempts)
                        continue
                    row.attempts += 1
                    row.sent_at = db_utc(utcnow())
                    row.status = "sent"
                    row.next_attempt_at = None
                    row.last_error = None
                    db.commit()
        except Exception:
            log.exception("Тик export-watcher упал")
        await asyncio.sleep(WATCH_SECONDS)
