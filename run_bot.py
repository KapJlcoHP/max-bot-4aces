"""Входная точка чат-бота (long polling — только dev; в проде вебхук на /webhook/max).

Запуск: run.bat или `.venv\\Scripts\\python.exe run_bot.py`.
Важно: экземпляр бота должен быть ровно один (иначе двойные ответы).
Рядом с поллингом живёт планировщик пушей (bot/scheduler.py) — общая БД с API.

Сбой сети/API не роняет процесс: бот перезапускается сам с нарастающей паузой.
"""

import asyncio
import logging
import os
import sys
import time

import dotenv
from maxapi import Bot, Dispatcher
from maxapi.enums.parse_mode import ParseMode

from bot.handlers import actions as actions_handler
from bot.handlers import start as start_handler
from bot.exporter import export_watcher_loop
from bot.scheduler import scheduler_loop

log = logging.getLogger("bot")

RESTART_DELAYS = (5, 10, 20, 40, 60)  # секунды между перезапусками (максимум — последний)
STABLE_RUN = 300  # прожил дольше — считаем сбой разовым, паузу сбрасываем


async def run_once(token: str) -> None:
    """Одна жизнь бота: коннект, поллинг, фоновые задачи. Любое исключение — наверх."""
    bot = Bot(token=token, format=ParseMode.MARKDOWN)
    dp = Dispatcher()
    dp.include_routers(start_handler.router, actions_handler.router)

    me = await bot.get_me()
    username = me.username if me else None
    print(f"Бот: @{username} ({me.first_name if me else '?'})")
    print("Long polling запущен. Ctrl+C — остановить.")

    scheduler = asyncio.create_task(scheduler_loop(bot, username))
    exporter = asyncio.create_task(export_watcher_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.cancel()
        exporter.cancel()


async def main() -> None:
    dotenv.load_dotenv()
    token = os.getenv("MAX_BOT_TOKEN")
    if not token:
        print("Ошибка: MAX_BOT_TOKEN не задан. Впишите токен в файл .env (без кавычек).")
        sys.exit(1)

    attempt = 0
    while True:
        started = time.monotonic()
        try:
            await run_once(token)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            delay = RESTART_DELAYS[min(attempt, len(RESTART_DELAYS) - 1)]
            log.exception("Бот упал — перезапуск через %s c", delay)
            await asyncio.sleep(delay)
        if time.monotonic() - started > STABLE_RUN:
            attempt = 0  # работали долго — сбой был разовым, пауза снова маленькая
        else:
            attempt += 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
