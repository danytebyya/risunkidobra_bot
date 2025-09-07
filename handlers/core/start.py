from aiogram import Router, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart

from config import logger, ADMIN_IDS
from utils.utils import safe_answer_callback


router = Router()


START_TEXT = (
    "👋 Приветствуем в «Добрые открыточки»!\n\n👇 Выбирайте кнопку ниже — и вместе мы создадим настоящее волшебство!"
)


def get_main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼️ Персональная открытка 🖼️", callback_data="create_card")],
        [InlineKeyboardButton(text="💌 Теплое поздравление 💌", callback_data="congrats")],
        [InlineKeyboardButton(text="💬 Совет от психолога 💬", callback_data="psychologist_advice")],
        [InlineKeyboardButton(text="💡 Идеи для чего угодно 💡", callback_data="ideas")],
        [InlineKeyboardButton(text="📋 Чек-лист достижения цели 📋", callback_data="start_goal_checklist")],
        [InlineKeyboardButton(text="⏳ Письмо в будущее ⌛️", callback_data="future_letter")],
        [InlineKeyboardButton(text="📜 Цитата дня 📜", callback_data="quote_of_day")],
        [InlineKeyboardButton(text="🛒 Магазин 🛒", callback_data="shop")],
    ])


def get_shop_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Купить подписку", callback_data="subscription")],
        [InlineKeyboardButton(text="🖼️ Купить фон", callback_data="purchase_backgrounds")],
        [InlineKeyboardButton(text="🖋️ Купить шрифт", callback_data="purchase_fonts")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_main_start")],
    ])


@router.callback_query(F.data == "start")
async def start_callback(call: CallbackQuery, state: FSMContext):
    # Сбрасываем сессию психолога, если пользователь был в ней
    data = await state.get_data()
    if data.get("session_active") and data.get("psychologist_stage"):
        logger.info(f"Сбрасываем сессию психолога для пользователя {call.from_user.id}")
    
    # Всегда показываем обычное главное меню, даже для админов
    # Админы могут использовать команду /admin для доступа к админ-панели
    
    # Проверяем, есть ли сохраненные идеи для отображения без кнопок
    current_ideas = data.get("current_ideas")
    if current_ideas:
        # Показываем идеи без кнопок и затем главное меню
        if isinstance(call.message, Message):
            # Сначала удаляем текущее сообщение
            try:
                await call.message.delete()
            except Exception:
                pass
            # Отправляем идеи без кнопок
            await call.message.answer(f"✨ Ваши идеи:\n\n{current_ideas}")
            # Затем отправляем главное меню снизу
            await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
    else:
        if isinstance(call.message, Message):
            await call.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())
    
    await state.clear()
    await safe_answer_callback(call, state)
    logger.info(f"Пользователь {call.from_user.id} вернулся в главное меню")


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    # Сбрасываем сессию психолога, если пользователь был в ней
    data = await state.get_data()
    if data.get("session_active") and data.get("psychologist_stage"):
        logger.info(f"Сбрасываем сессию психолога для пользователя {message.from_user.id}")
    
    # Всегда показываем обычное главное меню, даже для админов
    # Админы могут использовать команду /admin для доступа к админ-панели
    
    await state.clear()
    await message.answer(START_TEXT, reply_markup=get_main_menu_kb())
    if message.from_user:
        logger.info(f"Пользователь {message.from_user.id} использовал команду /start и перешел в главное меню")


@router.callback_query(F.data == "shop")
async def shop_menu(call: CallbackQuery, state: FSMContext):
    # Проверяем доступность сервиса
    from utils.service_checker import check_service_availability
    is_available, maintenance_message, keyboard = await check_service_availability("shop")
    
    if not is_available:
        if isinstance(call.message, Message):
            await call.message.edit_text(maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.", reply_markup=keyboard)
        await safe_answer_callback(call, state)
        return
    
    if isinstance(call.message, Message):
        await call.message.edit_text(
            "🛒 Добро пожаловать в магазин! Выберите, что хотите приобрести:",
            reply_markup=get_shop_menu_kb()
        )
    await safe_answer_callback(call, state)
    logger.info(f"Пользователь {call.from_user.id} открыл магазин")


@router.callback_query(F.data == "subscription")
async def subscription_menu(call: CallbackQuery, state: FSMContext):
    """Показывает меню выбора подписки."""
    await safe_answer_callback(call, state)
    
    text = "✨ Выберите подписку:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Добрые открыточки+", callback_data="subscription_choice:main")],
        [InlineKeyboardButton(text="💭 Добрый психолог+", callback_data="subscription_choice:psychologist")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="back_to_main_start")]
    ])
    
    if isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=keyboard)
    logger.info(f"Пользователь {call.from_user.id} открыл меню выбора подписки")


@router.callback_query(F.data == "back_to_main_start")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    if isinstance(call.message, Message):
        await call.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())
    await safe_answer_callback(call, state)
    logger.info(f"Пользователь {call.from_user.id} вернулся в главное меню из магазина")


def register_start_handlers(dp: Dispatcher):
    dp.include_router(router)
