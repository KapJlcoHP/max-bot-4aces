"""Клавиатуры бота. Кнопка open_app запускает мини-ап, привязанный к боту в business.max.ru."""

from maxapi.types import OpenAppButton
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
