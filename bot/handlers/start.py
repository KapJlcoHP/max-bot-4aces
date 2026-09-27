"""Хендлеры бота: /start, /app, /help. Кнопка open_app открывает мини-ап «МедМаршрут»."""

import os

from dotenv import load_dotenv
from maxapi import Router
from maxapi.filters.command import Command, CommandStart
from maxapi.types import MessageCreated

from bot.keyboards import open_app_keyboard

load_dotenv()

router = Router(router_id="start")

WELCOME = (
    "Здравствуйте! 👋\n\n"
    "Я бот **МедМаршрут** — помощник в медицинских маршрутах.\n\n"
    "Помогу подготовиться к приёму, собрать документы, "
    "не забыть про анализы и визиты к врачу.\n\n"
    "Нажмите кнопку ниже, чтобы открыть приложение."
)

HELP = (
    "Команды бота:\n"
    "/start — приветствие и кнопка приложения\n"
    "/app — открыть мини-ап «МедМаршрут»\n"
    "/status — где вы в маршруте и какой шаг текущий\n"
    "/diary — внести показатели в дневник здоровья прямо в чате\n"
    "/help — эта справка\n\n"
    "Я также напомню о шагах маршрута, визитах и приёме лекарств — "
    "действовать можно прямо в чате, кнопками под сообщением.\n\n"
    "Демо-данные маршрутов и организаций — синтетические, "
    "персональные данные не собираются."
)


def _miniapp_url_hint() -> str:
    url = os.getenv("MINIAPP_PUBLIC_URL", "").strip()
    return f"\n\nСсылка на приложение: {url}" if url else ""


async def _answer_with_app_button(event: MessageCreated, text: str) -> None:
    """Кнопка open_app ссылается на username бота; если он ещё не получен — шлём текст с URL."""
    me = event.bot.me
    username = me.username if me else None
    if username:
        await event.message.answer(text, attachments=[open_app_keyboard(username).as_markup()])
    else:
        await event.message.answer(text + _miniapp_url_hint())


@router.message_created(CommandStart())
async def start(event: MessageCreated):
    await _answer_with_app_button(event, WELCOME)


@router.message_created(Command("app"))
async def app(event: MessageCreated):
    await _answer_with_app_button(event, "Открываю «МедМаршрут»…" + _miniapp_url_hint())


@router.message_created(Command("help"))
async def help_command(event: MessageCreated):
    await event.message.answer(HELP + _miniapp_url_hint())
