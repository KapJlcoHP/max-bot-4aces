"""Входная точка чат-бота (long polling — только dev; в проде вебхук на /webhook/max).

Запуск: run.bat или `.venv\\Scripts\\python.exe run_bot.py`.
Важно: экземпляр бота должен быть ровно один (иначе двойные ответы).
"""

import asyncio
import logging
import os
import sys

import dotenv
from maxapi import Bot, Dispatcher

from bot.handlers import start as start_handler


async def main() -> None:
    dotenv.load_dotenv()
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        print("Ошибка: MAX_BOT_TOKEN не задан. Впишите токен в файл .env (без кавычек).")
        sys.exit(1)

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_routers(start_handler.router)

    me = await bot.get_me()
    print(f"Бот: @{me.username} ({me.first_name})")
    print("Long polling запущен. Ctrl+C — остановить.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
