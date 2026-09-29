"""Интерактив бота: колбэк-кнопки на пушах, /status, /diary и ввод дневников прямо в чате.

Лёгкий FSM ввода — in-memory dict по max_user_id: после перезапуска бота незавершённый
диалог просто сбрасывается (пользователь начинает заново через /diary).
"""

import logging
import re

from maxapi import F, Router
from maxapi.filters.command import Command
from maxapi.types import MessageCallback, MessageCreated
from sqlalchemy.orm import Session

from bot.keyboards import (
    diary_choice_keyboard,
    mood_keyboard,
    open_app_keyboard,
    push_keyboard,
    sugar_meal_keyboard,
)
from core.db.models import HealthSetting, MedCourse, RouteStep, User
from core.db.demo import fill_demo, has_any_data, wipe_data
from core.db.session import SessionLocal
from core.services import (
    ServiceError,
    active_route,
    add_health_record,
    complete_reminder,
    complete_route_step,
    take_med,
)
from bot.exporter import send_health_pdf
from bot.throttle import throttled

log = logging.getLogger("bot.actions")

router = Router(router_id="actions")

DIARY_TITLES = {"bp": "Давление", "weight": "Вес", "sugar": "Сахар", "mood": "Самочувствие"}
MOOD_PAYLOADS = {"mood_ok": "Хорошо", "mood_norm": "Нормально", "mood_bad": "Плохо"}

# шаг диалога: max_user_id → {"diary": "bp" | "weight" | "sugar" | "mood", ...}
_DIALOGS: dict[int, dict] = {}

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _user(db: Session, max_user_id: int) -> User | None:
    return db.query(User).filter(User.max_user_id == max_user_id).first()


def _sender_id(event) -> int | None:
    sender = getattr(event.message, "sender", None)
    if sender is not None and getattr(sender, "user_id", None) is not None:
        return sender.user_id
    recipient = getattr(event.message, "recipient", None)
    return getattr(recipient, "user_id", None) if recipient else None


def _username(event) -> str | None:
    me = event.bot.me
    return me.username if me else None


def _nums(text: str) -> list[float]:
    return [float(x.replace(",", ".")) for x in _NUM_RE.findall(text)]


def parse_bp(text: str) -> tuple[int, int, int | None]:
    nums = _nums(text)
    if len(nums) < 2:
        raise ServiceError("Не понял показания. Напишите, например: 120/80, пульс 72")
    return int(nums[0]), int(nums[1]), (int(nums[2]) if len(nums) >= 3 else None)


# ---------- команды ----------


@router.message_created(Command("status"))
@throttled
async def status_command(event: MessageCreated):
    """Текущий шаг маршрута + кнопки: выполнить в чате или открыть приложение."""
    username = _username(event)
    with SessionLocal() as db:
        user = _user(db, _sender_id(event) or 0)
        if user is None or user.consent_at is None:
            await event.message.answer("Сначала откройте «МедМаршрут» — работа начинается в приложении.")
            return
        route = active_route(db, user.id)
        step = None
        if route is not None:
            step = (
                db.query(RouteStep)
                .filter(RouteStep.route_id == route.id, RouteStep.status != "done")
                .order_by(RouteStep.position)
                .first()
            )
        if step is None:
            await event.message.answer(
                "Активного шага нет — выберите ситуацию в приложении.",
                attachments=[open_app_keyboard(username).as_markup()] if username else None,
            )
            return
        parts = [f"📍 Текущий шаг: **{step.title}**"]
        if step.place:
            parts.append(f"Где: {step.place}")
        when = " · ".join(
            filter(None, [step.deadline.strftime("%d.%m") if step.deadline else "", step.deadline_time or ""])
        )
        if when:
            parts.append(f"Срок: {when}")
        kb = push_keyboard(username, [("✅ Выполнить шаг", f"sdone_{step.id}")], app_payload=f"step_{step.id}")
        await event.message.answer("\n".join(parts), attachments=[kb.as_markup()])


@router.message_created(Command("diary"))
@throttled
async def diary_command(event: MessageCreated):
    """Заполнить дневник здоровья прямо в чате."""
    with SessionLocal() as db:
        user = _user(db, _sender_id(event) or 0)
        if user is None or user.consent_at is None:
            await event.message.answer("Сначала откройте «МедМаршрут» — настройка дневников там.")
            return
        enabled = (
            db.query(HealthSetting)
            .filter(HealthSetting.user_id == user.id, HealthSetting.enabled.is_(True))
            .all()
        )
    diaries = [(s.diary, DIARY_TITLES[s.diary]) for s in enabled if s.diary in DIARY_TITLES]
    if not diaries:
        await event.message.answer("Дневники пока не выбраны — настройте их в приложении, раздел «Здоровье».")
        return
    if len(diaries) == 1:
        await event.message.answer(_diary_prompt(diaries[0][0]), attachments=_diary_attachments(diaries[0][0]))
        _DIALOGS[_sender_id(event) or 0] = {"diary": diaries[0][0]}
        return
    await event.message.answer(
        "Какой дневник заполняем?",
        attachments=[diary_choice_keyboard(diaries).as_markup()],
    )


@router.message_created(Command("demo"))
@throttled
async def demo_command(event: MessageCreated):
    """Заполнить аккаунт модельными данными — для быстрой проверки сценария."""
    with SessionLocal() as db:
        user = _user(db, _sender_id(event) or 0)
        if user is None or user.consent_at is None:
            await event.message.answer("Сначала откройте «МедМаршрут» и пройдите вход — потом возвращайтесь за демо-данными.")
            return
        if has_any_data(db, user.id):
            await event.message.answer("В аккаунте уже есть данные — чтобы заменить их на демо, сначала отправьте /wipe.")
            return
        fill_demo(db, user)
    await event.message.answer(
        "🎲 Аккаунт заполнен **модельными данными** для демонстрации:\n\n"
        "• маршрут «Наблюдаться по хроническому» — первые шаги выполнены\n"
        "• дневники за 30 дней: давление и пульс, вес, сахар, самочувствие\n"
        "• курсы лекарств с отметками приёма\n"
        "• два будущих визита — придут напоминания\n\n"
        "Откройте приложение и смотрите: маршрут, графики, «Сводка для врача» — /svodka.\n"
        "Убрать демо-данные: /wipe."
    )


@router.message_created(Command("wipe"))
@throttled
async def wipe_command(event: MessageCreated):
    """Очистить контент аккаунта (маршрут, дневники, лекарства); согласие остаётся."""
    max_user_id = _sender_id(event) or 0
    _DIALOGS.pop(max_user_id, None)
    with SessionLocal() as db:
        user = _user(db, max_user_id)
        if user is None:
            await event.message.answer("Аккаунта ещё нет — очищать нечего. Начните с /start.")
            return
        had = has_any_data(db, user.id)
        wipe_data(db, user)
    if had:
        await event.message.answer(
            "🧹 Готово: маршрут, дневники, лекарства и напоминания удалены.\n"
            "Аккаунт и согласие сохранены. Заполнить заново демо-данными: /demo."
        )
    else:
        await event.message.answer("Данных не было — аккаунт и так чист. Заполнить демо-данными: /demo.")


@router.message_created(Command("svodka"))
@throttled
async def svodka_command(event: MessageCreated):
    """PDF-сводка для врача прямо в чат — без открытия мини-апа."""
    await event.message.answer("Собираю сводку за 30 дней…")
    with SessionLocal() as db:
        user = _user(db, _sender_id(event) or 0)
        if user is None or user.consent_at is None:
            await event.message.answer("Сначала откройте «МедМаршрут» — сводка строится из ваших дневников.")
            return
        try:
            await send_health_pdf(event.bot, db, user)
        except Exception:
            log.exception("/svodka не удалась")
            await event.message.answer("Не удалось собрать сводку — попробуйте позже.")


# ---------- диалог ввода дневника ----------


def _diary_prompt(diary: str) -> str:
    if diary == "bp":
        return "📝 **Давление и пульс**\n\nВведите показания одним сообщением, например:\n120/80, пульс 72\n(пульс можно не указывать)"
    if diary == "weight":
        return "📝 **Вес**\n\nВведите вес в килограммах, например: 82,5"
    if diary == "sugar":
        return "📝 **Сахар крови**\n\nКогда измеряли?"
    return "📝 **Самочувствие**\n\nКак вы себя чувствуете сегодня?"


def _diary_attachments(diary: str):
    if diary == "sugar":
        return [sugar_meal_keyboard().as_markup()]
    if diary == "mood":
        return [mood_keyboard().as_markup()]
    return None


async def _edit_to_prompt(event: MessageCallback, diary: str) -> None:
    """Из пуша с кнопкой — в вопрос диалога: редактируем то же сообщение."""
    _DIALOGS[event.callback.user.user_id] = {"diary": diary}
    await event.answer(new_text=_diary_prompt(diary), attachments=_diary_attachments(diary) or [])


# ---------- колбэки кнопок ----------


@router.message_callback(F.callback.payload.startswith("sdone_"))
@throttled
async def cb_step_done(event: MessageCallback):
    step_id = int(event.callback.payload.split("_")[1])
    with SessionLocal() as db:
        user = _user(db, event.callback.user.user_id)
        if user is None or user.consent_at is None:
            await event.answer(notification="Сначала откройте приложение")
            return
        try:
            step = complete_route_step(db, user.id, step_id)
        except ServiceError as e:
            await event.answer(notification=str(e))
            return
    await event.answer(new_text=f"✅ Шаг выполнен: {step.title}", attachments=[])


@router.message_callback(F.callback.payload.startswith("rdone_"))
@throttled
async def cb_reminder_done(event: MessageCallback):
    reminder_id = int(event.callback.payload.split("_")[1])
    with SessionLocal() as db:
        user = _user(db, event.callback.user.user_id)
        if user is None or user.consent_at is None:
            await event.answer(notification="Сначала откройте приложение")
            return
        try:
            reminder = complete_reminder(db, user.id, reminder_id)
        except ServiceError as e:
            await event.answer(notification=str(e))
            return
    await event.answer(new_text=f"✅ Готово: {reminder.title}", attachments=[])


@router.message_callback(F.callback.payload.startswith("mtake_"))
@throttled
async def cb_med_taken(event: MessageCallback):
    _, course_id_raw, hhmm = event.callback.payload.split("_")
    at_time = f"{hhmm[:2]}:{hhmm[2:]}"
    with SessionLocal() as db:
        user = _user(db, event.callback.user.user_id)
        if user is None or user.consent_at is None:
            await event.answer(notification="Сначала откройте приложение")
            return
        try:
            take_med(db, user.id, int(course_id_raw), at_time)
        except ServiceError as e:
            await event.answer(notification=str(e))
            return
        course = db.query(MedCourse).filter(MedCourse.id == int(course_id_raw)).first()
    await event.answer(new_text=f"✅ Принято: {course.name if course else 'лекарство'}, {at_time}", attachments=[])


@router.message_callback(F.callback.payload.startswith("diary_"))
@throttled
async def cb_diary_pick(event: MessageCallback):
    diary = event.callback.payload.removeprefix("diary_")
    if diary not in DIARY_TITLES:
        await event.answer(notification="Неизвестный дневник")
        return
    await _edit_to_prompt(event, diary)


@router.message_callback(F.callback.payload.startswith("meal_"))
@throttled
async def cb_meal_tag(event: MessageCallback):
    dialog = _DIALOGS.get(event.callback.user.user_id)
    if not dialog or dialog.get("diary") != "sugar":
        await event.answer(notification="Начните заново: /diary")
        return
    dialog["meal"] = "до еды" if event.callback.payload == "meal_before" else "после еды"
    await event.answer(new_text="Введите уровень сахара в ммоль/л, например: 5,5", attachments=[])


@router.message_callback(F.callback.payload.startswith("mood_"))
@throttled
async def cb_mood_pick(event: MessageCallback):
    dialog = _DIALOGS.get(event.callback.user.user_id)
    if not dialog or dialog.get("diary") != "mood":
        await event.answer(notification="Начните заново: /diary")
        return
    dialog["mood"] = MOOD_PAYLOADS[event.callback.payload]
    await event.answer(
        new_text="Оцените боль по шкале от 1 до 10 — или напишите «нет», если боли нет.",
        attachments=[],
    )


# ---------- текстовый ввод дневников (регистрируется последним — ловит остаток) ----------

COMMANDS_HINT = (
    "Команды:\n"
    "/app — открыть «МедМаршрут»\n"
    "/status — текущий шаг маршрута\n"
    "/diary — внести показатели в дневник здоровья\n"
    "/svodka — сводка для врача PDF\n"
    "/demo — заполнить аккаунт модельными данными\n"
    "/wipe — очистить маршрут, дневники, лекарства\n"
    "/help — справка"
)
FALLBACK_TAIL = "\n\nПоказатели дневника (давление, вес, сахар, самочувствие) вводите после команды /diary."


@router.message_created()
@throttled
async def diary_text_input(event: MessageCreated):
    """Ответ диалога дневника; вне диалога — подсказка на любое «лишнее» сообщение."""
    body_text = (event.message.body.text if event.message.body else "") or ""
    max_user_id = _sender_id(event) or 0
    dialog = _DIALOGS.get(max_user_id)
    if not dialog:
        if body_text.strip().startswith("/"):
            head = "Такой команды я не знаю."
        else:
            head = "Не понял сообщение — я работаю командами и дневниками."
        await event.message.answer(f"{head}\n\n{COMMANDS_HINT}{FALLBACK_TAIL}")
        return
    if body_text.strip().startswith("/"):
        _DIALOGS.pop(max_user_id, None)
        return

    diary = dialog["diary"]
    saved = ""
    with SessionLocal() as db:
        user = _user(db, max_user_id)
        if user is None or user.consent_at is None:
            _DIALOGS.pop(max_user_id, None)
            await event.message.answer("Сначала откройте приложение и пройдите вход.")
            return
        try:
            if diary == "bp":
                systolic, diastolic, pulse = parse_bp(body_text)
                row = add_health_record(db, user.id, "bp", systolic=systolic, diastolic=diastolic, pulse=pulse)
                saved = f"{row.systolic}/{row.diastolic}" + (f", пульс {row.pulse}" if row.pulse else "")
            elif diary == "weight":
                nums = _nums(body_text)
                if not nums:
                    raise ServiceError("Не понял вес. Напишите, например: 82,5")
                row = add_health_record(db, user.id, "weight", weight_kg=nums[0])
                saved = f"{str(row.weight_kg).replace('.', ',')} кг"
            elif diary == "sugar":
                nums = _nums(body_text)
                if not nums:
                    raise ServiceError("Не понял значение. Напишите, например: 5,5")
                row = add_health_record(db, user.id, "sugar", sugar_mmol=nums[0], meal_tag=dialog.get("meal"))
                saved = f"{str(row.sugar_mmol).replace('.', ',')} ммоль/л" + (f" ({row.meal_tag})" if row.meal_tag else "")
            elif diary == "mood":
                mood = dialog.get("mood")
                if not mood:
                    await event.message.answer("Сначала выберите самочувствие кнопкой выше.")
                    return
                pain = None
                if not re.search(r"нет|без боли", body_text, re.IGNORECASE):
                    ints = [int(n) for n in _nums(body_text)]
                    pain = ints[0] if ints else None
                row = add_health_record(db, user.id, "mood", mood=mood, pain=pain)
                saved = f"самочувствие — {row.mood}" + (f", боль {row.pain}/10" if row.pain else "")
            else:
                _DIALOGS.pop(max_user_id, None)
                return
        except ServiceError as e:
            await event.message.answer(f"{e}\nПопробуйте ещё раз.")
            return
    _DIALOGS.pop(max_user_id, None)
    username = _username(event)
    kb = open_app_keyboard(username, app_payload="health") if username else None
    await event.message.answer(f"✅ Записал: {saved}. 💙", attachments=[kb.as_markup()] if kb else None)
