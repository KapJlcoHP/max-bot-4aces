"""Чат-бот команды 4Aces (хакатон MAX) — базовая версия.

Умеет: /start с приветствием и меню из кнопок, ответы на нажатия, эхо текста.
Токен берётся только из .env (MAX_BOT_TOKEN) — в коде его быть не должно.
Запуск: run.bat или .venv\\Scripts\\python.exe bot.py
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from maxapi import Bot, Dispatcher, F
from maxapi.filters.command import CommandStart
from maxapi.types import CallbackButton, MessageCallback, MessageCreated
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

TOKEN = os.getenv("MAX_BOT_TOKEN")
if not TOKEN or TOKEN == "paste_your_token_here":
    raise SystemExit("Не ��аполнен MAX_BOT_TOKEN в файле .env")

bot = Bot(token=TOKEN)
dp = Dispatcher()

BUTTON_ANSWERS = {
    "hello": "И вам привет! 👋",
    "next": (
        "Дальше по плану — сценарий кейса «Забота о людях»: "
        "навигатор по услугам и статусам. Пока это заглушка 🙂"
    ),
}


def main_menu() -> list:
    kb = InlineKeyboardBuilder()
    kb.row(
        CallbackButton(text="👋 Привет", payload="hello"),
        CallbackButton(text="ℹ️ Что дальше", payload="next"),
    )
    return [kb.as_markup()]


@dp.message_created(CommandStart())
async def start(event: MessageCreated) -> None:
    await event.message.answer(
        "Привет! Я бот команды 4Aces.\n"
        "Попробуйте кнопки ниже или просто пришлите сообщение — "
        "я пока повторяю текст.",
        attachments=main_menu(),
    )


@dp.message_callback()
async def on_button(event: MessageCallback) -> None:
    text = BUTTON_ANSWERS.get(
        event.callback.payload, "Неизвестная кнопка 🤷"
    )
    await event.answer(new_text=text)


@dp.message_created(F.message.body.text)
async def echo(event: MessageCreated) -> None:
    await event.message.answer(f"Вы написали: {event.message.body.text}")


async def main() -> None:
    logger.info("Запуск long polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
