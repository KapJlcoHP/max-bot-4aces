"""Входная точка чат-бота (long polling — только dev; в проде вебхук на /webhook/max).

Запуск: run.bat или `.venv\\Scripts\\python.exe run_bot.py`.
Важно: экземпляр бота должен быть ровно один (иначе двойные ответы).
Рядом с поллингом живёт планировщик пушей (bot/scheduler.py) — общая БД с API.
"""

import asyncio
import logging
import os
import sys

import dotenv
from maxapi import Bot, Dispatcher
from maxapi.enums.parse_mode import ParseMode

from bot.handlers import actions as actions_handler
from bot.handlers import start as start_handler
from bot.scheduler import scheduler_loop


async def main() -> None:
    dotenv.load_dotenv()
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        print("Ошибка: MAX_BOT_TOKEN не задан. Впишите токен в файл .env (без кавычек).")
        sys.exit(1)

    # format=MARKDOWN: **жирный** в текстах рендерится, а не печатается звёздочками
    bot = Bot(token=token, format=ParseMode.MARKDOWN)
    dp = Dispatcher()
    dp.include_routers(start_handler.router, actions_handler.router)

    me = await bot.get_me()
    username = me.username if me else None
    print(f"Бот: @{username} ({me.first_name if me else '?'})")
    print("Long polling запущен. Ctrl+C — остановить.")

    scheduler = asyncio.create_task(scheduler_loop(bot, username))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
