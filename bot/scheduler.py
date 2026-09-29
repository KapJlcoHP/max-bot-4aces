"""Планировщик пушей бота: шаги маршрута, напоминания, лекарства, дневники здоровья.

Каждые 60 с собирает список «пора отправить», отправляет и только после успешной
отправки пишет дедуп в notification_log — упавший пуш повторится на следующем тике.

Время: «настенные» значения (deadline/time, Reminder.at, MedCourse.times,
HealthSetting.push_time) трактуются в поясе ПОЛЬЗОВАТЕЛЯ (users.tz, IANA-имя с
его телефона): для каждого пользователя свой «сейчас» через zoneinfo.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.models import (
    HealthRecord,
    HealthSetting,
    MedCourse,
    MedIntake,
    NotificationLog,
    Reminder,
    RouteStep,
    User,
    utcnow,
)
from core.db.session import SessionLocal
from core.services import active_route

log = logging.getLogger("bot.scheduler")

TICK_SECONDS = 60
FAIL_MARK_ATTEMPTS = 5  # после стольких неудачных тиков пуш глушим дедупом (dialog.not.found сам не вылечится)
DIARY_TITLES = {"bp": "Давление", "weight": "Вес", "sugar": "Сахар", "mood": "Самочувствие"}


@dataclass
class Push:
    user_id: int          # внутренний id (NotificationLog.user_id)
    max_user_id: int      # адресат в MAX
    text: str
    actions: list         # [(текст кнопки, payload)]
    app_payload: str | None
    kind: str             # step | reminder | med | diary
    ref_id: int
    lead: str
    reminder_id: int | None = None  # reminder: пометить sent_at при lead='now'


def _local_naive(dt: datetime, tz: ZoneInfo | None) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(tz).replace(tzinfo=None) if tz else dt.astimezone().replace(tzinfo=None)


def _user_now(user: User) -> datetime:
    """«Сейчас» в поясе пользователя (наивное настенное время)."""
    try:
        return datetime.now(ZoneInfo(user.tz or "Europe/Moscow")).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _when_desc(due: datetime, now: datetime, has_time: bool) -> str:
    days = (due.date() - now.date()).days
    if days == 1:
        day = "завтра"
    elif days == 0:
        day = "сегодня"
    else:
        day = due.strftime("%d.%m")
    return f"{day} в {due:%H:%M}" if has_time else day


def _parse_time(value: str) -> dtime | None:
    try:
        return dtime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def collect_due(db: Session, now: datetime | None = None) -> list[Push]:
    """Что пора отправить прямо сейчас. Чистая по отношению к отправке — тестируемая.

    now — опционально для тестов; в проде считается per-user в поясе пользователя.
    """
    pushes: list[Push] = []

    def logged(kind: str, ref_id: int, lead: str) -> bool:
        return (
            db.query(NotificationLog)
            .filter(
                NotificationLog.kind == kind,
                NotificationLog.ref_id == ref_id,
                NotificationLog.lead == lead,
            )
            .first()
            is not None
        )

    for user in db.query(User).all():
        if not user.notifications_on:
            continue
        zone: ZoneInfo | None = None
        try:
            zone = ZoneInfo(user.tz or "Europe/Moscow")
        except Exception:
            zone = None
        user_now = now if now is not None else _user_now(user)
        today = user_now.date()

        # --- шаг маршрута: дедлайн текущего шага ---
        route = active_route(db, user.id)
        if route is not None:
            step = (
                db.query(RouteStep)
                .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
                .order_by(RouteStep.position)
                .first()
            )
            if step is not None and step.deadline is not None:
                slot = _parse_time(step.deadline_time) or dtime(12, 0)
                due_at = datetime.combine(step.deadline, slot)
                has_time = step.deadline_time is not None
                for lead, start, end in (
                    ("day", due_at - timedelta(days=1), due_at - timedelta(hours=1)),
                    ("hour", due_at - timedelta(hours=1), due_at),
                ):
                    if start <= user_now < end and not logged("step", step.id, lead):
                        pushes.append(
                            Push(
                                user_id=user.id,
                                max_user_id=user.max_user_id,
                                text=(
                                    f"⏰ **Напоминание о шаге**\n«{step.title}» — срок {_when_desc(due_at, user_now, has_time)}.\n"
                                    "Отметить выполнение можно прямо здесь."
                                ),
                                actions=[("✅ Выполнить шаг", f"sdone_{step.id}")],
                                app_payload=f"step_{step.id}",
                                kind="step",
                                ref_id=step.id,
                                lead=lead,
                            )
                        )
                if due_at.date() == today and user_now >= due_at and not logged("step", step.id, "now"):
                    pushes.append(
                        Push(
                            user_id=user.id,
                            max_user_id=user.max_user_id,
                            text=f"⏰ **Пора**: «{step.title}» — срок наступил.",
                            actions=[("✅ Выполнить шаг", f"sdone_{step.id}")],
                            app_payload=f"step_{step.id}",
                            kind="step",
                            ref_id=step.id,
                            lead="now",
                        )
                    )

        # --- напоминания пользователя ---
        for r in (
            db.query(Reminder)
            .filter(Reminder.user_id == user.id, Reminder.enabled.is_(True), Reminder.done_at.is_(None))
            .all()
        ):
            at = _local_naive(r.at, zone)
            where = f" · {r.place}" if r.place else ""
            for lead, start, end in (
                ("day", at - timedelta(days=1), at - timedelta(hours=1)),
                ("hour", at - timedelta(hours=1), at),
                ("now", at, None),
            ):
                if lead == "now" and at.date() != today:
                    continue  # прошлые дни не догоняем — шумно
                if user_now >= start and (end is None or user_now < end) and not logged("reminder", r.id, lead):
                    if lead == "day":
                        text = f"⏰ **Напоминание**: «{r.title}»{where} — {_when_desc(at, user_now, True)}."
                    elif lead == "hour":
                        text = f"⏰ **Через час**: «{r.title}»{where} — {_when_desc(at, user_now, True)}."
                    else:
                        text = f"⏰ **Пора**: «{r.title}»{where}."
                    pushes.append(
                        Push(
                            user_id=user.id,
                            max_user_id=user.max_user_id,
                            text=text,
                            actions=[("✅ Выполнено", f"rdone_{r.id}")],
                            app_payload=None,
                            kind="reminder",
                            ref_id=r.id,
                            lead=lead,
                            reminder_id=r.id if lead == "now" else None,
                        )
                    )

        # --- лекарства: слот настал, приём не отмечен ---
        for c in (
            db.query(MedCourse).filter(MedCourse.user_id == user.id, MedCourse.enabled.is_(True)).all()
        ):
            if c.until is not None and c.until < today:
                continue
            taken_slots = {
                i.at_time
                for i in db.query(MedIntake)
                .filter(MedIntake.course_id == c.id, MedIntake.day == today, MedIntake.taken_at.is_not(None))
                .all()
            }
            for t in c.times or []:
                slot = _parse_time(t)
                if slot is None:
                    continue
                slot_at = datetime.combine(today, slot)
                if not (slot_at <= user_now < slot_at + timedelta(hours=6)):
                    continue  # не догоняем пропущенные слоты
                lead = f"{today:%Y%m%d}-{slot:%H%M}"
                if t in taken_slots or logged("med", c.id, lead):
                    continue
                pushes.append(
                    Push(
                        user_id=user.id,
                        max_user_id=user.max_user_id,
                        text=f"💊 **Пора принять**: {c.name} — {slot:%H:%M}.",
                        actions=[("✅ Принято", f"mtake_{c.id}_{slot:%H%M}")],
                        app_payload="meds",
                        kind="med",
                        ref_id=c.id,
                        lead=lead,
                    )
                )

        # --- дневники здоровья: время пуша настало, записи сегодня ещё нет ---
        for s in (
            db.query(HealthSetting)
            .filter(HealthSetting.user_id == user.id, HealthSetting.enabled.is_(True))
            .all()
        ):
            if not s.push_time or s.diary not in DIARY_TITLES:
                continue
            slot = _parse_time(s.push_time)
            if slot is None or user_now.time() < slot:
                continue
            lead = f"{today:%Y%m%d}"
            if logged("diary", s.id, lead):
                continue
            # HealthRecord.at хранится как UTC; сравниваем с границами местного дня в UTC.
            local_zone = zone or datetime.now().astimezone().tzinfo
            day_start = datetime.combine(today, dtime.min, tzinfo=local_zone).astimezone(timezone.utc).replace(tzinfo=None)
            day_end = datetime.combine(today + timedelta(days=1), dtime.min, tzinfo=local_zone).astimezone(timezone.utc).replace(tzinfo=None)
            already = (
                db.query(HealthRecord)
                .filter(
                    HealthRecord.user_id == user.id,
                    HealthRecord.type == s.diary,
                    HealthRecord.at >= day_start,
                    HealthRecord.at < day_end,
                )
                .first()
            )
            if already is not None:
                continue
            pushes.append(
                Push(
                    user_id=user.id,
                    max_user_id=user.max_user_id,
                    text=f"📝 **{DIARY_TITLES[s.diary]}**: пора внести показатели.\nМожно прямо здесь — кнопкой ниже.",
                    actions=[("✍️ Внести данные", f"diary_{s.diary}")],
                    app_payload="health",
                    kind="diary",
                    ref_id=s.id,
                    lead=lead,
                )
            )

    return pushes


def mark_sent(db: Session, push: Push) -> None:
    """Дедуп пишем ТОЛЬКО после успешной отправки."""
    db.add(NotificationLog(user_id=push.user_id, kind=push.kind, ref_id=push.ref_id, lead=push.lead))
    if push.reminder_id is not None:
        reminder = db.get(Reminder, push.reminder_id)
        if reminder is not None and reminder.sent_at is None:
            reminder.sent_at = utcnow()
    try:
        db.commit()
    except IntegrityError:
        # Игнорируем только повторную запись уже существующего уведомления.
        db.rollback()
        existing = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.kind == push.kind,
                NotificationLog.ref_id == push.ref_id,
                NotificationLog.lead == push.lead,
            )
            .first()
        )
        if existing is None:
            raise


async def scheduler_loop(bot, bot_username: str | None) -> None:
    from bot.keyboards import push_keyboard

    fail_counts: dict[tuple[str, int, str], int] = {}
    sent_unlogged: dict[tuple[str, int, str], Push] = {}

    while True:
        try:
            # Сообщение уже доставлено, но запись в БД могла не сохраниться.
            # Повторяем только запись журнала, не отправку в MAX.
            for key, push in list(sent_unlogged.items()):
                try:
                    with SessionLocal() as db:
                        mark_sent(db, push)
                except Exception:
                    log.exception("Не удалось записать доставленное уведомление: kind=%s ref=%s", push.kind, push.ref_id)
                else:
                    sent_unlogged.pop(key, None)
            with SessionLocal() as db:
                due = collect_due(db)
            for push in due:
                key = (push.kind, push.ref_id, push.lead)
                if key in sent_unlogged:
                    continue
                kb = push_keyboard(bot_username, push.actions, push.app_payload)
                try:
                    await bot.send_message(
                        user_id=push.max_user_id,
                        text=push.text,
                        attachments=[kb.as_markup()],
                        notify=True,
                    )
                except Exception:
                    fail_counts[key] = fail_counts.get(key, 0) + 1
                    if fail_counts[key] >= FAIL_MARK_ATTEMPTS:
                        log.warning(
                            "Пуш не отправлен после %d попыток, глушу дедупом: kind=%s ref=%s lead=%s",
                            fail_counts.pop(key), push.kind, push.ref_id, push.lead,
                        )
                        with SessionLocal() as db:
                            mark_sent(db, push)
                    else:
                        log.exception("Пуш не отправлен: kind=%s ref=%s", push.kind, push.ref_id)
                    continue
                fail_counts.pop(key, None)
                sent_unlogged[key] = push
                try:
                    with SessionLocal() as db:
                        mark_sent(db, push)
                except Exception:
                    log.exception("Не удалось записать доставленное уведомление: kind=%s ref=%s", push.kind, push.ref_id)
                else:
                    sent_unlogged.pop(key, None)
        except Exception:
            log.exception("Тик планировщика упал")
        await asyncio.sleep(TICK_SECONDS)
