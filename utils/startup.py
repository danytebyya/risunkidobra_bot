import asyncio

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands, BotCommandScopeChat

from config import ADMIN_IDS, logger
from handlers.branches.future_letter import setup_future_letter_scheduler
from utils.database.dropbox_storage import sync_resources_hash
from utils.notification_sender import start_notification_scheduler
from utils.database.db import init_db, init_connection_pool


def sync_resources():
    logger.info('🔄 Синхронизируем папку resources с Dropbox...')
    sync_resources_hash()

async def on_startup(bot: Bot, activity_middleware=None):
    # Инициализируем пул соединений для оптимизации производительности
    await init_connection_pool()
    logger.info("🚀 Пул соединений БД инициализирован...")
    
    # Инициализируем базу данных
    await init_db()
    logger.info("🚀 Инициализация базы данных...")
    
    # Запускаем синхронизацию в отдельном потоке, чтобы не блокировать event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sync_resources)
    setup_future_letter_scheduler(bot)
    start_notification_scheduler()
    
    # Запускаем фоновый процессор активности, если передан
    if activity_middleware:
        await activity_middleware.start_background_processor()
        logger.info("Фоновый процессор активности запущен!")
    
    logger.info("Письма в будущее перезаписаны!")
    logger.info("Планировщик уведомлений запущен!") 

    default_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="subscription", description="Оформить подписку"),
        BotCommand(command="help", description="Поддержка"),
    ]
    await bot.set_my_commands(commands=default_commands, scope=BotCommandScopeAllPrivateChats())

    admin_commands = default_commands + [
        BotCommand(command="admin", description="Меню админа"),
    ]

    for admin_id in ADMIN_IDS:
        await bot.set_my_commands(commands=admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
