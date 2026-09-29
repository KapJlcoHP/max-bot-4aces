"""Отправка PDF-сводки в чат бота.

На телефонах вебвью MAX блокирует скачивание файлов, поэтому файл доставляет бот:
мини-ап кладёт заявку (export_requests через API), вотчер каждые 3 с забирает,
собирает PDF тем же кодом, что и веб-экспорт, и шлёт файлом в чат.
Та же функция используется командой /svodka в самом боте.
"""

import asyncio
import logging
from datetime import datetime

from maxapi import Bot
from maxapi.enums.upload_type import UploadType
from maxapi.types import InputMediaBuffer
from sqlalchemy.orm import Session

from core.db.models import ExportRequest, User, utcnow
from core.db.session import SessionLocal
from server.api.v1.api import _get_diary_settings, health_report
from server.health_pdf import build_health_pdf

log = logging.getLogger("bot.exporter")

WATCH_SECONDS = 3
MAX_ATTEMPTS = 3

PDF_CAPTION = "📄 Сводка для врача за 30 дней — можно показать на приёме или сохранить."


def _build_pdf(db: Session, user: User) -> tuple[bytes, str]:
    """Тот же PDF, что и в веб-экспорте (GET /health/export)."""
    report = health_report(user=user, db=db)
    enabled = _get_diary_settings(db, user.id)
    data = build_health_pdf(db, user, report, enabled)
    stamp = datetime.now().strftime("%d.%m.%Y")
    return data, f"medroute-svodka-{stamp}.pdf"


async def send_health_pdf(bot: Bot, db: Session, user: User) -> None:
    # reportlab синхронный и тяжёлый — в отдельный поток, чтобы не замораживать event loop
    data, filename = await asyncio.to_thread(_build_pdf, db, user)
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
                    .filter(ExportRequest.sent_at.is_(None), ExportRequest.attempts < MAX_ATTEMPTS)
                    .order_by(ExportRequest.id)
                    .limit(5)
                    .all()
                )
                for row in rows:
                    user = db.get(User, row.user_id)
                    if user is None:
                        row.sent_at = utcnow()
                        db.commit()
                        continue
                    row.attempts += 1
                    db.commit()
                    try:
                        await send_health_pdf(bot, db, user)
                    except Exception:
                        log.exception("PDF не отправлен: заявка #%s (попытка %s)", row.id, row.attempts)
                        continue
                    row.sent_at = utcnow()
                    db.commit()
        except Exception:
            log.exception("Тик export-watcher упал")
        await asyncio.sleep(WATCH_SECONDS)
