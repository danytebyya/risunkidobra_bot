import os

from sys import stdout
from loguru import logger
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TOKEN = os.getenv("TELEGRAM_TOKEN")
PAYMENT_SECRET_KEY = os.getenv("PAYMENT_SECRET_KEY")
PAYMENT_SECRET_KEY_LIVE = os.getenv("PAYMENT_SECRET_KEY_LIVE", None)
HTTP_PROXY = os.getenv("HTTP_PROXY")

required = {
    "TELEGRAM_TOKEN": TOKEN,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "PAYMENT_SECRET_KEY": PAYMENT_SECRET_KEY,
}
missing = [name for name, val in required.items() if not val]
if missing:
    raise RuntimeError(f"Не заданы переменные окружения: {', '.join(missing)}")

logger.remove()
logger.add(stdout, level="DEBUG", enqueue=True)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

ADMIN_IDS = [782942700, 735800754]

SUPPORT_URL = "tg://resolve?domain=ourlifeiswhatourthoughtsmakeit"

Font_Folder = "resources/fonts/"
Output_Folder = "resources/output/"

Image_Categories = {
    "Для него": "resources/images/for_him",
    "Для неё": "resources/images/for_her",
    "День рождения": "resources/images/birthday",
    "Пожелания": "resources/images/wishes",
    "Общее": "resources/images/all"
}
