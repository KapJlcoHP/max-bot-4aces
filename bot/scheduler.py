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
from datetime import date, datetime, time as dtime, timedelta
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
from core.diary_settings import diary_settings
from core.services import active_route
from core.time import db_utc, local_day_bounds, normalize_clock_time, strict_local_utc, user_local, user_zone
from bot.step_text import booking_information, completion_label, deadline_label

log = logging.getLogger("bot.scheduler")

TICK_SECONDS = 60
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
    step_schedule: tuple | None = None
    step_revision: int = 0


def delivery_lead(push: Push) -> str:
    return f"{push.lead}:{push.step_revision}" if push.kind == "step" and push.step_revision else push.lead


def _local_naive(dt: datetime, tz: ZoneInfo | None) -> datetime:
    """UTC DateTime из БД -> настенное время пользователя."""
    return user_local(dt, str(tz) if tz else None).replace(tzinfo=None)


def _user_now(user: User) -> datetime:
    """«Сейчас» в поясе пользователя; сохраняем offset/fold при переводе часов."""
    return datetime.now(user_zone(user.tz))


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
    normalized = normalize_clock_time(value)
    if normalized is None:
        return None
    return dtime.fromisoformat(normalized)


def collect_due(db: Session, now: datetime | None = None, *, user_id: int | None = None) -> list[Push]:
    """Что пора отправить прямо сейчас. Чистая по отношению к отправке — тестируемая.

    now — опционально для тестов; в проде считается per-user в поясе пользователя.
    """
    pushes: list[Push] = []

    def logged(kind: str, ref_id: int, lead: str) -> bool:
        return (
            db.query(NotificationLog)
            .filter(
                NotificationLog.user_id == user.id,
                NotificationLog.kind == kind,
                NotificationLog.ref_id == ref_id,
                NotificationLog.lead == lead,
            )
            .first()
            is not None
        )

    users = db.query(User)
    if user_id is not None:
        users = users.filter(User.id == user_id)
    for user in users.all():
        if not user.notifications_on:
            continue
        zone: ZoneInfo | None = None
        try:
            zone = ZoneInfo(user.tz or "Europe/Moscow")
        except Exception:
            zone = None
        clock_now = now if now is not None else _user_now(user)
        user_now = user_local(clock_now, user.tz).replace(tzinfo=None) if clock_now.tzinfo is not None else clock_now
        today = user_now.date()

        # --- шаг маршрута: дедлайн текущего шага ---
        route = active_route(db, user.id)
        if route is not None:
            step = (
                db.query(RouteStep)
                .filter(RouteStep.route_id == route.id, RouteStep.status == "current")
                .order_by(RouteStep.position)
                .first()
            )
            if step is not None and step.deadline is not None:
                slot = _parse_time(step.deadline_time) if step.deadline_time else None
                has_time = slot is not None
                day_time = _parse_time(user.step_day_before_time) or dtime(9, 0)
                due_at = datetime.combine(step.deadline, slot or day_time)
                day_start = datetime.combine(step.deadline, dtime.min)
                day_end = day_start + timedelta(days=1)
                leads = []
                mode = step.reminder_mode or "profile"
                # Compare instants, not naive walls: an hour across DST is still
                # exactly an hour. Legacy ambiguous event clocks are skipped.
                try:
                    instant_now = db_utc(clock_now) if clock_now.tzinfo is not None else strict_local_utc(user_now, user.tz)
                    if mode == "custom":
                        at = step.reminder_at
                        if at is not None and (step.activated_at is None or at >= step.activated_at):
                            leads.append(("custom", at, at + timedelta(days=1)))
                    else:
                        event_utc = strict_local_utc(due_at, user.tz)
                        end_utc = strict_local_utc(day_end, user.tz)
                        if mode == "day" or (mode == "profile" and user.notify_day_before):
                            start = strict_local_utc(datetime.combine(step.deadline - timedelta(days=1), day_time), user.tz)
                            end = strict_local_utc(day_start, user.tz)
                            if has_time:
                                end = min(end, event_utc - timedelta(hours=1))
                            leads.append(("day", start, end))
                        if has_time and (mode == "hour" or (mode == "profile" and user.notify_hour_before)):
                            leads.append(("hour", event_utc - timedelta(hours=1), event_utc))
                        if mode == "profile" and user.notify_at_deadline:
                            leads.append(("now", event_utc, end_utc))
                except ValueError:
                    leads = []
                fingerprint = (
                    route.id, step.status, step.title, step.deadline, step.deadline_time,
                    mode, step.reminder_at, step.reminder_revision, step.activated_at,
                    user.tz, user.notifications_on, user.notify_day_before,
                    user.notify_hour_before, user.notify_at_deadline, user.step_day_before_time,
                    step.kind, step.appointment_date, step.booking_target_step_id,
                )
                for lead, start, end in leads:
                    # A newly current step starts only future windows. A
                    # retry for a step that was already current remains valid.
                    if step.activated_at is not None and start < step.activated_at:
                        continue
                    # Revision isolates receipts from an edit made while a
                    # previous delivery was in flight (or awaiting log retry).
                    dedup_lead = f"{lead}:{step.reminder_revision}" if step.reminder_revision else lead
                    if not (start <= instant_now < end) or logged("step", step.id, dedup_lead):
                        continue
                    text = (
                        (f"⏰ **Пора**: «{step.title}» — срок наступил." if has_time else
                         f"⏰ **Сегодня срок шага**: «{step.title}». Время события не указано.")
                        if lead == "now" else
                        f"⏰ **Напоминание о шаге**\n«{step.title}» — срок {_when_desc(due_at, user_now, has_time)}.\n"
                        "Отметить выполнение можно прямо здесь."
                    )
                    if step.kind == "booking":
                        text += f"\n{deadline_label(step)}. {booking_information(step)}"
                        text += "\nДату внесите в карточке записи до завершения. Кнопка в чате не меняет дату/выполнение будущего события."
                    elif step.kind == "visit":
                        text += "\nВ чате визит завершается без ввода назначений; их можно добавить в карточке выполненного визита."
                    pushes.append(
                        Push(
                            user_id=user.id,
                            max_user_id=user.max_user_id,
                            text=text,
                            actions=[(completion_label(step), f"sdone_{step.id}")],
                            app_payload=f"step_{step.id}",
                            kind="step",
                            ref_id=step.id,
                            lead=lead,
                            step_schedule=fingerprint,
                            step_revision=step.reminder_revision,
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
                normalize_clock_time(i.at_time) or i.at_time
                for i in db.query(MedIntake)
                .filter(MedIntake.course_id == c.id, MedIntake.day == today, MedIntake.taken_at.is_not(None))
                .all()
            }
            for raw_time in c.times or []:
                t = normalize_clock_time(raw_time)
                slot = _parse_time(raw_time)
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
        for s in diary_settings(db, user.id).values():
            if not s.enabled or not s.push_time or s.diary not in DIARY_TITLES:
                continue
            setting_row = (
                db.query(HealthSetting)
                .filter(HealthSetting.user_id == user.id, HealthSetting.diary == s.diary)
                .first()
            )
            # Current defaults have no push time. If a default ever gains one,
            # use a stable per-user/diary ref without inventing an ORM id.
            setting_ref = setting_row.id if setting_row is not None else user.id * 10 + ("bp", "weight", "sugar", "mood").index(s.diary)
            slot = _parse_time(s.push_time)
            if slot is None or user_now.time() < slot:
                continue
            lead = f"{today:%Y%m%d}"
            if logged("diary", setting_ref, lead):
                continue
            # HealthRecord.at хранится как UTC; сравниваем с границами местного дня в UTC.
            day_start, day_end = local_day_bounds(today, user.tz)
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
                    ref_id=setting_ref,
                    lead=lead,
                )
            )

    return pushes


def revalidate_step_push(db: Session, push: Push, now: datetime | None = None) -> bool:
    """Fresh ownership/status/global switch/schedule/dedup check before I/O.

    Never trust ORM objects retained from collection or a prior transaction.
    """
    if push.kind != "step":
        return True
    db.expire_all()
    return any(
        fresh.kind == "step" and fresh.user_id == push.user_id
        and fresh.max_user_id == push.max_user_id and fresh.ref_id == push.ref_id
        and fresh.lead == push.lead and fresh.step_schedule == push.step_schedule
        for fresh in collect_due(db, now, user_id=push.user_id)
    )


def mark_sent(db: Session, push: Push) -> None:
    """Дедуп пишем ТОЛЬКО после успешной отправки."""
    db.add(NotificationLog(user_id=push.user_id, kind=push.kind, ref_id=push.ref_id, lead=delivery_lead(push)))
    if push.reminder_id is not None:
        reminder = db.get(Reminder, push.reminder_id)
        if reminder is not None and reminder.sent_at is None:
            reminder.sent_at = db_utc(utcnow())
    try:
        db.commit()
    except IntegrityError:
        # Игнорируем только повторную запись уже существующего уведомления.
        db.rollback()
        existing = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.kind == push.kind,
                NotificationLog.user_id == push.user_id,
                NotificationLog.ref_id == push.ref_id,
                NotificationLog.lead == delivery_lead(push),
            )
            .first()
        )
        if existing is None:
            raise


async def scheduler_loop(bot, bot_username: str | None) -> None:
    from bot.keyboards import push_keyboard

    sent_unlogged: dict[tuple[int, str, int, str], Push] = {}

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
                # user_id обязателен: id курса/напоминания/настройки могут
                # совпадать у разных пользователей.
                key = (push.user_id, push.kind, push.ref_id, delivery_lead(push))
                if key in sent_unlogged:
                    continue
                kb = push_keyboard(bot_username, push.actions, push.app_payload)
                try:
                    with SessionLocal() as db:
                        if not revalidate_step_push(db, push):
                            continue
                    await bot.send_message(
                        user_id=push.max_user_id,
                        text=push.text,
                        attachments=[kb.as_markup()],
                        notify=True,
                    )
                except Exception:
                    # Нельзя превращать сетевой сбой в «доставлено»: пока MAX
                    # недоступен, due-запись остаётся видимой на следующем тике.
                    log.exception("Пуш не отправлен: user=%s kind=%s ref=%s", push.user_id, push.kind, push.ref_id)
                    continue
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
