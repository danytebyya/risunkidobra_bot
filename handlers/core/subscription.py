from datetime import datetime, timedelta, timezone
from aiogram import F, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from utils.database.db import upsert_subscription, fetch_subscription
from utils.payments.payment_functional import create_payment, check_payment_status
from handlers.core.start import START_TEXT, get_main_menu_kb
from config import logger
from utils.utils import safe_answer_callback


router = Router()


# --- Функции активации подписок ---
async def activate_subscription(user_id: int, days: int, subscription_type: str = 'main') -> datetime:
    """Активирует или продлевает подписку на days дней."""
    now = datetime.now(timezone.utc)
    record = await fetch_subscription(user_id, type=subscription_type)
    if record and record['expires_at'] > now:
        base = record['expires_at']
    else:
        base = now
    expires = base + timedelta(days=days)
    await upsert_subscription(user_id, expires, type=subscription_type)
    logger.info(f"Подписка {subscription_type} пользователя {user_id} активирована на {days} дн. до {expires.isoformat()}")
    return expires


async def is_subscribed(user_id: int, subscription_type: str = 'main') -> bool:
    """Проверяет наличие активной подписки."""
    record = await fetch_subscription(user_id, type=subscription_type)
    now_utc = datetime.now(timezone.utc)
    active = bool(record and record['expires_at'] > now_utc)
    return active


# --- Данные подписок ---
SUBSCRIPTION_DATA = {
    'main': {
        'name': 'Добрые открыточки+',
        'price': 490,
        'days': 30,
        'description': (
            "- Бесплатная генерация открыток\n"
            "- Бесплатная генерация поздравлений\n"
            "- Ежемесячно — одно бесплатное письмо в будущее \n"
            "- Доступ к «Цитате дня»"
        )
    },
    'psychologist': {
        'name': 'Добрый психолог+',
        'price': 990,
        'days': 30,
        'description': (
            "- Неограниченное общение с ботом-психологом\n"
            "- Сохранение истории и персональное резюме"
        )
    }
}


# --- Клавиатуры ---
def get_subscription_menu_kb():
    """Клавиатура выбора подписки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Добрые открыточки+", callback_data="subscription_choice:main")],
        [InlineKeyboardButton(text="🧠 Добрый психолог+", callback_data="subscription_choice:psychologist")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_edit_sub")]
    ])


def get_back_to_menu_kb():
    """Клавиатура возврата в главное меню."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_sub")]
    ])


def get_payment_kb(url: str, payment_id: str, days: int, subscription_type: str):
    """Клавиатура оплаты."""
    check_callback = f"check_psychologist:{payment_id}:{days}" if subscription_type == 'psychologist' else f"check:{payment_id}:{days}"
    back_callback = "psychologist_back_to_menu" if subscription_type == 'psychologist' else "subscription_back_to_menu"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти к оплате", url=url)],
        [InlineKeyboardButton(text="Проверить оплату", callback_data=check_callback)],
        [InlineKeyboardButton(text="⏎ Назад", callback_data=back_callback)]
    ])


# --- Обработчики команд ---
@router.message(Command(commands=["subscribe", "subscription"]))
async def show_subscription_menu(message: Message, state: FSMContext):
    """Показывает пользователю меню выбора подписки."""
    user_id = message.from_user.id if message.from_user else 0
    logger.info(f"Пользователь {user_id} открыл меню подписки")
    
    # Сбрасываем сессию психолога, если пользователь был в ней
    data = await state.get_data()
    if data.get("session_active") and data.get("psychologist_stage"):
        logger.info(f"Сбрасываем сессию психолога для пользователя {user_id}")
        await state.clear()
    
    text = "✨ Выберите подписку:"
    await message.answer(text, reply_markup=get_subscription_menu_kb())


@router.message(Command(commands=["psychologist_subscription"]))
async def show_psychologist_subscription_menu(message: Message, state: FSMContext):
    """Показывает меню подписки на психолога (для обратной совместимости)."""
    user_id = message.from_user.id if message.from_user else 0
    logger.info(f"Пользователь {user_id} открыл меню подписки на психолога")
    
    # Сбрасываем сессию психолога, если пользователь был в ней
    data = await state.get_data()
    if data.get("session_active") and data.get("psychologist_stage"):
        logger.info(f"Сбрасываем сессию психолога для пользователя {user_id}")
        await state.clear()
    
    await show_subscription_info(message, 'psychologist')


# --- Обработчики callback ---
@router.callback_query(F.data == "main_subscription")
async def subscription_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик для обратной совместимости."""
    await safe_answer_callback(call, state)
    await show_subscription_info(call, 'main')


@router.callback_query(F.data.startswith("subscription_choice:"))
async def subscription_choice_callback(call: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор типа подписки."""
    await safe_answer_callback(call, state)
    
    if not call.data:
        return
    
    subscription_type = call.data.split(':')[1]
    await show_subscription_info(call, subscription_type)


async def show_subscription_info(message_or_call, subscription_type: str):
    """Показывает информацию о подписке или меню покупки."""
    user_id = message_or_call.from_user.id if hasattr(message_or_call, 'from_user') else message_or_call.from_user.id
    
    # Проверяем активную подписку
    if await is_subscribed(user_id, subscription_type):
        record = await fetch_subscription(user_id, type=subscription_type)
        if record:
            expires: datetime = record['expires_at']
            formatted = expires.strftime("%d.%m.%Y")
            sub_data = SUBSCRIPTION_DATA[subscription_type]
            
            text = f"🎉 Ваша подписка «{sub_data['name']}» активна до {formatted}."
            
            if isinstance(message_or_call, Message):
                await message_or_call.answer(text, reply_markup=get_back_to_menu_kb())
            else:
                await message_or_call.message.edit_text(text, reply_markup=get_back_to_menu_kb())
            return
    
    # Если подписки нет, показываем меню покупки
    sub_data = SUBSCRIPTION_DATA[subscription_type]
    text = (
        f"✨ Подписка «{sub_data['name']}»\n\n"
        f"{sub_data['description']}\n\n"
        f"Стоимость: {sub_data['price']}₽/мес"
    )
    
    buy_callback = f"buy_psychologist:{sub_data['days']}:{sub_data['price']}" if subscription_type == 'psychologist' else f"buy:{sub_data['days']}:{sub_data['price']}"
    back_callback = "subscription_back_to_menu"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оформить подписку", callback_data=buy_callback)],
        [InlineKeyboardButton(text="⏎ Назад", callback_data=back_callback)]
    ])
    
    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=keyboard)
    else:
        await message_or_call.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("buy:"))
async def purchase_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик покупки основной подписки."""
    await process_purchase(call, state, 'main')


@router.callback_query(F.data.startswith("buy_psychologist:"))
async def purchase_psychologist_callback(call: CallbackQuery, state: FSMContext):
    """Обработчик покупки подписки на психолога."""
    await process_purchase(call, state, 'psychologist')


async def process_purchase(call: CallbackQuery, state: FSMContext, subscription_type: str):
    """Обрабатывает процесс покупки подписки."""
    if not call.data:
        return
    
    parts = call.data.split(':')
    if len(parts) < 3:
        return
    
    _, days_str, amount = parts
    days = int(days_str)
    sub_data = SUBSCRIPTION_DATA[subscription_type]
    description = f"Подписка {sub_data['name']} на {days} дней"

    url, payment_id = await create_payment(call.from_user.id, amount, description)
    keyboard = get_payment_kb(url, payment_id, days, subscription_type)

    if isinstance(call.message, Message):
        await call.message.edit_text(
            f"👇 Нажмите на кнопку ниже, чтобы перейти к оплате подписки {sub_data['name']}:",
            reply_markup=keyboard
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data.startswith("check:"))
async def check_callback(call: CallbackQuery, state: FSMContext):
    """Проверка оплаты основной подписки."""
    await process_payment_check(call, state, 'main')


@router.callback_query(F.data.startswith("check_psychologist:"))
async def check_psychologist_callback(call: CallbackQuery, state: FSMContext):
    """Проверка оплаты подписки на психолога."""
    await process_payment_check(call, state, 'psychologist')


async def process_payment_check(call: CallbackQuery, state: FSMContext, subscription_type: str):
    """Обрабатывает проверку оплаты."""
    if not call.data:
        return
    
    parts = call.data.split(':')
    if len(parts) < 3:
        return
    
    user_id = call.from_user.id
    _, payment_id, days_str = parts
    days = int(days_str)
    status = await check_payment_status(payment_id)

    if status == 'succeeded':
        expires = await activate_subscription(call.from_user.id, days, subscription_type)
        formatted = expires.strftime("%d.%m.%Y")
        sub_data = SUBSCRIPTION_DATA[subscription_type]
        
        # Сбрасываем счетчик бесплатных сообщений при оформлении подписки
        if subscription_type == 'psychologist':
            from utils.database.db import reset_free_count
            await reset_free_count(user_id)
            logger.info(f"Сброшен счетчик бесплатных сообщений для пользователя {user_id}")
        
        logger.info(f"Платёж {payment_id} пользователя {user_id} успешно завершён, подписка {subscription_type} до {formatted}")
        
        text = f"🎉 Оплата подтверждена!\n\nВаша подписка «{sub_data['name']}» активна до {formatted}."
        
        if isinstance(call.message, Message):
            await call.message.edit_text(text, reply_markup=get_back_to_menu_kb())
    else:
        logger.warning(f"Платёж {payment_id} пользователя {user_id} не подтверждён (статус={status})")
        await call.answer(
            f"❌ Оплата не подтверждена. Текущий статус: {status}.",
            show_alert=True
        )
    await safe_answer_callback(call, state)


# --- Обработчики навигации ---
@router.callback_query(F.data == "subscription_back_to_menu")
async def subscription_back_to_menu(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя в меню выбора подписки."""
    await safe_answer_callback(call, state)
    
    text = "✨ Выберите подписку:"
    if isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=get_subscription_menu_kb())


@router.callback_query(F.data == "psychologist_back_to_menu")
async def psychologist_back_to_menu(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя в меню подписки на психолога."""
    await safe_answer_callback(call, state)
    await show_subscription_info(call, 'psychologist')


@router.callback_query(F.data == "main_menu_sub")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    """Возвращает в главное меню."""
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "main_menu_edit_sub")
async def back_to_main_edit(call: CallbackQuery, state: FSMContext):
    """Возвращает в главное меню (редактирование)."""
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())
    await safe_answer_callback(call, state)


def register_subscription(dp: Dispatcher):
    """Регистрирует роутер подписки в диспетчере."""
    dp.include_router(router)
