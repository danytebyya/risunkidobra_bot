from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands, BotCommandScopeChat

from config import ADMIN_IDS, logger
from handlers.branches.future_letter import setup_future_letter_scheduler


async def on_startup(bot: Bot):
    setup_future_letter_scheduler(bot)
    logger.info("Письма в будущее перезаписаны!")

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
