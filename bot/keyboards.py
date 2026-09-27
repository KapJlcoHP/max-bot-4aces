"""Клавиатуры бота. OpenAppButton запускает мини-ап, CallbackButton — действие прямо в чате."""

from maxapi.types import CallbackButton, OpenAppButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def open_app_keyboard(bot_username: str, payload: str | None = None) -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        OpenAppButton(
            text="🏥 Открыть МедМаршрут",
            web_app=bot_username,
            payload=payload,
        )
    )
    return keyboard


def push_keyboard(
    bot_username: str | None,
    actions: list[tuple[str, str]],
    app_payload: str | None = None,
) -> InlineKeyboardBuilder:
    """Клавиатура пуша: ряд callback-кнопок + кнопка приложения, если известен username."""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(*(CallbackButton(text=text, payload=payload) for text, payload in actions))
    if bot_username:
        keyboard.row(
            OpenAppButton(text="🏥 Открыть МедМаршрут", web_app=bot_username, payload=app_payload)
        )
    return keyboard


def diary_choice_keyboard(diaries: list[tuple[str, str]]) -> InlineKeyboardBuilder:
    """Выбор дневника, который заполняем в чате: [(type, «Давление»), …]"""
    keyboard = InlineKeyboardBuilder()
    keyboard.row(*(CallbackButton(text=title, payload=f"diary_{t}") for t, title in diaries))
    return keyboard


def sugar_meal_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(text="🍽 До еды", payload="meal_before"),
        CallbackButton(text="🍽 После еды", payload="meal_after"),
    )
    return keyboard


def mood_keyboard() -> InlineKeyboardBuilder:
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        CallbackButton(text="🙂 Хорошо", payload="mood_ok"),
        CallbackButton(text="😐 Нормально", payload="mood_norm"),
        CallbackButton(text="☹️ Плохо", payload="mood_bad"),
    )
    return keyboard
