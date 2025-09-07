import os
from dotenv import load_dotenv

# Загружаем переменные окружения в самом начале
load_dotenv()

# from config import HTTP_PROXY

# if HTTP_PROXY is not None and HTTP_PROXY != "":
#     os.environ["HTTP_PROXY"] = HTTP_PROXY
#     os.environ["HTTPS_PROXY"] = HTTP_PROXY
#     os.environ["NO_PROXY"] = "api.dropboxapi.com,content.dropboxapi.com"

import asyncio

from aiogram import Dispatcher

from config import logger
from utils.startup import on_startup
from handlers import register_all
from utils.bot_instance import bot
from utils.activity_middleware import ActivityMiddleware


if bot.token is None:
    raise RuntimeError("TELEGRAM_TOKEN не задан!")

dp = Dispatcher()

# Создаем экземпляр middleware для отслеживания активности
activity_middleware = ActivityMiddleware()

# Регистрируем middleware для отслеживания активности
dp.message.middleware(activity_middleware)
dp.callback_query.middleware(activity_middleware)


async def main():
    register_all(dp)

    await on_startup(bot, activity_middleware)
    logger.info("🤖 Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
