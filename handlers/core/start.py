from aiogram import Router, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart

from config import logger


router = Router()


START_TEXT = (
    "👋 Приветствуем в «Добрые открыточки»!\n\n👇 Выбирайте кнопку ниже — и вместе мы создадим настоящее волшебство!"
)


def get_main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼️ Персональная открытка", callback_data="create_card")],
        [InlineKeyboardButton(text="💌 Теплое поздравление", callback_data="congrats")],
        [InlineKeyboardButton(text="✍️ Письмо в будущее", callback_data="future_letter")],
        [InlineKeyboardButton(text="💬 Цитата дня", callback_data="quote_of_day")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
    ])


def get_shop_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼️ Купить фон", callback_data="purchase_backgrounds")],
        [InlineKeyboardButton(text="🖋️ Купить шрифт", callback_data="purchase_fonts")],
        [InlineKeyboardButton(text="✨ Купить подписку", callback_data="subscription")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_main_start")],
    ])


@router.callback_query(F.data == "start")
async def start_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())
    await call.answer()
    logger.info(f"Пользователь {call.from_user.id} нажал кнопку старт и перешел в главное меню")


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(START_TEXT, reply_markup=get_main_menu_kb())
    logger.info(f"Пользователь {message.from_user.id} использовал команду /start и перешел в главное меню")


@router.callback_query(F.data == "shop")
async def shop_menu(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "🛒 Добро пожаловать в магазин! Выберите, что хотите приобрести:",
        reply_markup=get_shop_menu_kb()
    )
    await call.answer()
    logger.info(f"Пользователь {call.from_user.id} открыл магазин")


@router.callback_query(F.data == "back_to_main_start")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())
    await call.answer()
    logger.info(f"Пользователь {call.from_user.id} вернулся в главное меню из магазина")


def register_start_handlers(dp: Dispatcher):
    dp.include_router(router)
