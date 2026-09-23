import asyncio
import logging
import os

from dotenv import load_dotenv
from maxapi import Bot, Dispatcher

from handlers.start import router as start_router


async def main():
    load_dotenv()
    token = os.getenv("MAX_BOT_TOKEN")

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_routers(start_router)
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
