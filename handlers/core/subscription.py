from datetime import datetime, timedelta
from aiogram import F, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram import Router
from aiogram.filters import Command

from utils.database.db import upsert_subscription, fetch_subscription
from utils.payments.payment_functional import create_payment, check_payment_status
from handlers.core.start import START_TEXT, get_main_menu_kb
from config import logger


router = Router()


async def activate_subscription(user_id: int, days: int) -> datetime:
    """
    Активирует или продлевает подписку на days дней.
    """
    now = datetime.utcnow()
    record = await fetch_subscription(user_id)
    if record and record['expires_at'] > now:
        base = record['expires_at']
    else:
        base = now
    expires = base + timedelta(days=days)
    await upsert_subscription(user_id, expires.isoformat())
    logger.info(f"Подписка пользователя {user_id} активирована на {days} дн. до {expires.isoformat()}")
    return expires


async def is_subscribed(user_id: int) -> bool:
    """
    Проверяет наличие активной подписки.
    """
    record = await fetch_subscription(user_id)
    active = bool(record and record['expires_at'] > datetime.utcnow())
    return active


@router.message(Command(commands=["subscribe", "subscription"]))
async def show_subscription_menu(message: Message):
    """
    Показывает пользователю информацию о подписке или дату её окончания.
    """
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} открыл меню подписки")

    if await is_subscribed(user_id):
        record = await fetch_subscription(user_id)
        expires: datetime = record['expires_at']
        formatted = expires.strftime("%d.%m.%Y")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_sub")]
        ])
        await message.answer(
            f"🎉 Ваша подписка активна до {formatted}.",
            reply_markup=kb
        )
        return

    text = (
        "✨ Подписка «Добрые открыточки+»\n\n"
        "- Бесплатная генерация открыток\n"
        "- Бесплатная генерация поздравлений\n"
        "- Ежемесячно — одно бесплатное письмо в будущее \n"
        "- Доступ к «Цитате дня»\n\n"
        "Стоимость: 500₽/мес"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оформить подписку", callback_data="buy:30:500")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_edit_sub")]
    ])
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "subscription")
async def subscription_callback(call: CallbackQuery):
    """
    Пользователь нажал на «Оформить подписку» из inline-кнопки —
    редактируем текущее сообщение, показывая меню подписки.
    """
    await call.answer()  # убираем «часики»

    user_id = call.from_user.id

    if await is_subscribed(user_id):
        record = await fetch_subscription(user_id)
        expires = record['expires_at']
        formatted = expires.strftime("%d.%m.%Y")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_sub")]
        ])
        await call.message.edit_text(
            f"🎉 Ваша подписка активна до {formatted}.",
            reply_markup=kb
        )
    else:
        text = (
            "✨ Подписка Добрые открыточки+\n\n"
            "- Бесплатная генерация открыток\n"
            "- Бесплатная генерация поздравлений\n"
            "- Одно бесплатное письмо в будущее (раз в месяц)\n"
            "- Доступ к «Цитате дня»\n\n"
            "Стоимость: 500₽/мес"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оформить подписку", callback_data="buy:30:500")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_edit_sub")]
        ])
        await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("buy:"))
async def purchase_callback(call: CallbackQuery):
    """
    При нажатии «Оформить подписку» редактирует сообщение: показывает кнопки для оплаты.
    """
    _, days_str, amount = call.data.split(':')
    days = int(days_str)
    description = f"Подписка на {days} дней"

    url, payment_id = await create_payment(call.from_user.id, amount, description)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти к оплате", url=url)],
        [InlineKeyboardButton(text="Проверить оплату", callback_data=f"check:{payment_id}:{days}")]
    ])

    await call.message.edit_text(
        "👇 Нажмите на кнопку ниже, чтобы перейти к оплате подписки:",
        reply_markup=keyboard
    )
    await call.answer()


@router.callback_query(F.data.startswith("check:"))
async def check_callback(call: CallbackQuery):
    """
    Проверяет статус платежа и, при успехе, редактирует сообщение:
    убирает кнопки и выводит подтверждение оплаты.
    """
    user_id = call.from_user.id
    _, payment_id, days_str = call.data.split(':')
    days = int(days_str)
    status = await check_payment_status(payment_id)

    if status == 'succeeded':
        expires = await activate_subscription(call.from_user.id, days)
        formatted = expires.strftime("%d.%m.%Y")
        logger.info(f"Платёж {payment_id} пользователя {user_id} успешно завершён, подписка до {formatted}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_sub")]
        ])
        await call.message.edit_text(
            f"🎉 Оплата подтверждена!\n\nВаша подписка активна до {formatted}.",
            reply_markup=kb
        )
    else:
        logger.warning(f"Платёж {payment_id} пользователя {user_id} не подтверждён (статус={status})")
        await call.answer(
            f"❌ Оплата не подтверждена. Текущий статус: {status}.",
            show_alert=True
        )
    await call.answer()


@router.callback_query(F.data == "main_menu_sub")
async def back_to_main(call: CallbackQuery):
    """
    Отправляет главное меню и убирает кнопки.
    """
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "main_menu_edit_sub")
async def back_to_main_edit(call: CallbackQuery):
    """
    Отправляет главное меню и убирает кнопки.
    """
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await call.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())


def register_subscription(dp: Dispatcher):
    """Регистрирует роутер подписки в диспетчере."""
    dp.include_router(router)
