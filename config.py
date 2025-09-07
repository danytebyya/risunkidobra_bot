import os

from sys import stdout
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN = os.getenv("TELEGRAM_TOKEN")
# PAYMENT_SECRET_KEY = os.getenv("PAYMENT_SECRET_KEY")
PAYMENT_SECRET_KEY_LIVE = os.getenv("PAYMENT_SECRET_KEY_LIVE", None)
# HTTP_PROXY = os.getenv("HTTP_PROXY", None)
DATABASE_URL = os.getenv("DATABASE_URL")
APP_KEY = os.getenv('DROPBOX_APP_KEY')
APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
REFRESH_TOKEN = os.getenv('DROPBOX_REFRESH_TOKEN')

required = {
    "TELEGRAM_TOKEN": TOKEN,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "PAYMENT_SECRET_KEY_LIVE": PAYMENT_SECRET_KEY_LIVE,
}
missing = [name for name, val in required.items() if not val]
if missing:
    raise RuntimeError(f"Не заданы переменные окружения: {', '.join(missing)}")

logger.remove()
logger.add(stdout, level="DEBUG", enqueue=True)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ADMIN_IDS = [782942700, 735800754]

SUPPORT_URL = "tg://resolve?domain=ourlifeiswhatourthoughtsmakeit"

Font_Folder = "resources/fonts/"
Output_Folder = "resources/output/"
