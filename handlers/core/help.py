from aiogram import Router, types, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import logger, SUPPORT_URL

router = Router()

HELP_TEXT = (
    "📝 Если у вас есть какие-либо предложения или возникли ошибки — пишите в поддержку, "
    "и мы обязательно разберёмся!"
)

def get_help_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💬 Написать в поддержку",
                url=SUPPORT_URL
            )
        ],
        [
            InlineKeyboardButton(
                text="🏠 Вернуться в главное меню",
                callback_data="start"
            )
        ],
    ])

@router.message(Command(commands=["help"]))
async def cmd_help(message: types.Message, state: FSMContext):
    # Сбрасываем сессию психолога, если пользователь был в ней
    data = await state.get_data()
    if data.get("session_active") and data.get("psychologist_stage"):
        logger.info(f"Сбрасываем сессию психолога для пользователя {message.from_user.id}")
    
    await state.clear()
    await message.answer(HELP_TEXT, reply_markup=get_help_menu_kb())
    if message.from_user:
        logger.info(f"Пользователь {message.from_user.id} вызвал /help и увидел меню поддержки")


def register_help_handlers(dp: Dispatcher):
    dp.include_router(router)
