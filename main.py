import os
from config import HTTP_PROXY

os.environ["HTTP_PROXY"]  = HTTP_PROXY
os.environ["HTTPS_PROXY"] = HTTP_PROXY

import asyncio

from aiogram import Bot, Dispatcher

from config import TOKEN, logger
from utils.startup import on_startup
from utils.database.db import init_db
from handlers import register_all


bot = Bot(token=TOKEN)
dp = Dispatcher()


async def main():
    register_all(dp)

    await init_db()
    logger.info("🚀 Инициализация базы данных...")

    await on_startup(bot)
    logger.info("Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
