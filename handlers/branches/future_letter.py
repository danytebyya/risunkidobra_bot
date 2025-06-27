import asyncio
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Router, F, Bot, Dispatcher
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

from handlers.core.start import START_TEXT, get_main_menu_kb
from handlers.core.subscription import is_subscribed
from utils.utils import safe_call_answer
from utils.payments.payment_functional import create_payment, check_payment_status
from utils.database.db import (
    upsert_future_letter,
    fetch_due_letters,
    fetch_all_unsent_letters,
    mark_letter_sent,
    count_free_letters_in_month
)
from utils.utils import safe_edit_text
from config import logger, ADMIN_IDS


router = Router()
scheduler = AsyncIOScheduler()


class FutureLetterStates(StatesGroup):
    input_letter = State()
    confirm_interval = State()
    waiting_for_payment = State()


# ——————————————————————
# Ввод текста письма
# ——————————————————————
async def show_input_step(call: CallbackQuery, state: FSMContext):
    """
    Отображает пользователю приглашение написать письмо в будущее.
    Устанавливает состояние input_letter.
    """
    await state.clear()
    await state.update_data(bot_msg_id=call.message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='go_back_letter')
    ]])
    await call.message.edit_text(
        text="✨ Добро пожаловать в «Письмо в будущее»!\n\n"
             "✎ Напишите письмо своему будущему «я» — расскажите о мечтах, надеждах и планах.",
        reply_markup=kb
    )
    await state.set_state(FutureLetterStates.input_letter)


# ——————————————————————
# Подтверждение интервала отправки
# ——————————————————————
async def show_confirm_step(call_obj, draft: str, state: FSMContext, is_callback: bool=True):
    """Отображает пользователю выбор интервала отправки письма."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✓ Через месяц', callback_data='in_month'),
         InlineKeyboardButton(text='✓ Через год', callback_data='in_year')],
        [InlineKeyboardButton(text='↩ Назад', callback_data='go_back_letter')]
    ])
    text =  ("✉️ Ваше письмо готово к отправке:\n\n"
             f"{draft}\n\n"
             f"Когда вы хотите получить этот привет из прошлого?")

    data = await state.get_data()
    bot_msg_id = data.get('bot_msg_id')
    chat_id = call_obj.message.chat.id if is_callback else call_obj.chat.id

    if is_callback:
        await call_obj.message.edit_text(text, reply_markup=kb)
    else:
        await call_obj.bot.edit_message_text(
            chat_id=chat_id,
            message_id=bot_msg_id,
            text=text,
            reply_markup=kb
        )


# ——————————————————————
# Оплата письма
# ——————————————————————
async def show_payment_step(call: CallbackQuery, interval: str, state: FSMContext):
    """Предлагает пользователю оплатить письмо."""
    url, pid = await create_payment(call.from_user.id, 100, 'Письмо в будущее')
    await state.update_data(pid=pid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🛒 Оплатить Письмо в будущее', url=url)],
        [InlineKeyboardButton(text='📥 Отправить письмо', callback_data='check_future_letter')],
        [InlineKeyboardButton(text='↩ Назад', callback_data='go_back_letter')]
    ])
    await safe_call_answer(call)
    await call.message.edit_text(
        text=f"💳 Вложитесь в воспоминания: оплатите, "
             f"и ваше письмо отправится через {interval}.",
        reply_markup=kb
    )
    await state.set_state(FutureLetterStates.waiting_for_payment)


# ——————————————————————
# Запуск flow «Письмо в будущее»
# ——————————————————————
@router.callback_query(F.data == 'future_letter')
async def future_letter_start(call: CallbackQuery, state: FSMContext):
    """Обрабатывает нажатие кнопки «Письмо в будущее» и запускает ввод письма."""
    user_id = call.from_user.id
    logger.info(f"Пользователь {user_id} переключился на вкладку «Письмо в будущее»")
    await show_input_step(call, state)
    await safe_call_answer(call)


# ——————————————————————
# Обработка ввода текста письма
# ——————————————————————
@router.message(FutureLetterStates.input_letter)
async def input_future_letter(message: Message, state: FSMContext):
    """Получает текст письма от пользователя. Переходит к выбору интервала отправки."""
    if message.content_type != 'text':
        data = await state.get_data()
        bot_msg_id = data.get('bot_msg_id')
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text='❌ Пожалуйста, отправьте текстовое сообщение.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='go_back_to_menu')
            ]])
        )
        return
    draft = message.text
    created_at = datetime.now(timezone.utc)
    await state.update_data(user_text=draft, created_at=created_at.isoformat())
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    await show_confirm_step(message, draft, state, is_callback=False)
    await state.set_state(FutureLetterStates.confirm_interval)


# ——————————————————————
# Выбор интервала отправки
# ——————————————————————
@router.callback_query(F.data.in_({'in_month', 'in_year'}))
async def choose_interval(call: CallbackQuery, state: FSMContext):
    """Сохраняет интервал отправки и запускает оплату. Также планирует задачу отправки письма через APScheduler."""
    user_id = call.from_user.id
    data = await state.get_data()
    draft = data['user_text']
    now = datetime.now(timezone.utc)
    delay_days = 30 if call.data == 'in_month' else 365
    send_at = now + timedelta(days=delay_days)

    if await is_subscribed(user_id):
        used = await count_free_letters_in_month(user_id, send_at)
        if used < 1:
            await upsert_future_letter(user_id, draft, send_at, is_free=True)
            scheduler.add_job(
                call.bot.send_message,
                trigger='date',
                run_date=send_at,
                args=[
                    user_id,
                    f"📨 Ваше письмо из прошлого:\n\n{draft}"
                ]
            )
            formatted_date = send_at.strftime("%d.%m.%Y")
            await safe_call_answer(call)
            await call.message.edit_text(
                text=(
                    f"✅ Отлично! Как подписчик, вы получили бесплатную отправку.\n"
                    f"Ваше письмо запланировано на {formatted_date} в 12:00 UTC."
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='go_back_to_menu')]
                ])
            )
            await state.clear()
            return

    await state.update_data(send_at=send_at.isoformat())
    interval = 'месяц' if call.data == 'in_month' else 'год'
    await show_payment_step(call, interval, state)


# ——————————————————————
# Проверка оплаты и фиксация письма
# ——————————————————————
@router.callback_query(F.data == 'check_future_letter')
async def check_future_letter(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = data.get('pid')
    status = await check_payment_status(pid)
    user_id = call.from_user.id

    if not pid or await check_payment_status(pid) != 'succeeded':
        await call.answer(text='❌ Платёж не подтверждён', show_alert=True)
        logger.warning(
            f"Платёж {pid} пользователя {user_id} для письма в будущее не подтверждён "
            f"(статус={status})"
        )
        return
    logger.info(f"Пользователь {user_id} успешно оплатил и отправил письмо в будущее (payment_id={pid})")

    draft = data['user_text']
    send_at = datetime.fromisoformat(data['send_at'])
    await upsert_future_letter(call.from_user.id, draft, send_at)

    scheduler.add_job(
        call.bot.send_message,
        trigger='date',
        run_date=send_at,
        args=[
            call.from_user.id,
            f"📨 Ваше письмо из прошлого:\n\n{draft}"
        ]
    )

    formatted_date = send_at.strftime("%d.%m.%Y")
    await safe_call_answer(call)
    await call.message.edit_text(
        text= f"✅ Отлично! Ваше письмо запланировано на "
            f"{formatted_date} в 12:00 UTC — "
            f"приготовьтесь встретиться с собой будущим.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='go_back_to_menu')]
        ])
    )
    await state.clear()


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == 'go_back_letter')
async def go_back_letter(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает возвращение назад в flow письма:
    возвращает к вводу письма, выбору интервала или в главное меню.
    """
    current = await state.get_state()
    data = await state.get_data()
    await safe_call_answer(call)
    if current == FutureLetterStates.confirm_interval.state:
        await show_input_step(call, state)
    elif current == FutureLetterStates.waiting_for_payment.state:
        draft = data.get('user_text', '')
        await show_confirm_step(call, draft, state)
        await state.set_state(FutureLetterStates.confirm_interval)
    else:
        await state.clear()
        await safe_edit_text(call.message, text=START_TEXT, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == 'go_back_to_menu')
async def go_back_to_menu(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя в главное меню и сбрасывает состояние."""
    await state.clear()
    await safe_call_answer(call)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(text=START_TEXT, reply_markup=get_main_menu_kb())


# ——————————————————————
# Доставка писем
# ——————————————————————
async def deliver_future_letters(bot: Bot):
    """
    Периодически проверяет БД на неотправленные письма
    и отправляет их пользователям.
    """
    letters = await fetch_due_letters()
    for l in letters:
        for attempt in (1, 2):
            try:
                created_at = l.get('created_at')
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)
                ts = created_at.strftime("%d.%m.%Y %H:%M")
                text = (
                    f"📨 Ваше письмо, составленное {ts}:\n\n"
                    f"{l['content']}"
                )
                await bot.send_message(l['user_id'], text)
                await mark_letter_sent(l['id'])
                break
            except TelegramBadRequest as e:
                if attempt == 1:
                    await asyncio.sleep(5)
                else:
                    logger.exception(f"Не удалось отправить письмо id={l['id']} после 2 попыток", exc_info=e)
                    try:
                        chat = await bot.get_chat(l['user_id'])
                        username = chat.username or f"{chat.first_name or ''} {chat.last_name or ''}".strip()
                    except TelegramBadRequest:
                        username = None
                    admin_text = (
                        f"❗ Не удалось доставить письмо пользователю {l['user_id']}"
                        f"{f' (@{username})' if username else ''}:\n\n{l['content']}"
                    )
                    try:
                        await bot.send_message(ADMIN_IDS, admin_text)
                    except TelegramBadRequest:
                        logger.exception("Не удалось уведомить админа о неотправленном письме")


async def reschedule_pending(bot: Bot):
    """
    При старте приложения вновь планирует все письма,
    которые ещё не были отправлены.
    """
    pending = await fetch_all_unsent_letters()
    now = datetime.now(timezone.utc)
    for l in pending:
        raw_send = l.get('send_at')
        if not raw_send:
            logger.warning(f"reschedule_pending: письмо id={l.get('id')} без send_at, пропускаем"
                           f"текст письма: \"{l.get('content', '').replace(chr(10), ' ')}\""
                           )
            continue
        run_dt = (datetime.fromisoformat(raw_send)
                  if isinstance(raw_send, str) else raw_send)
        if run_dt.tzinfo is None:
            run_dt = run_dt.replace(tzinfo=timezone.utc)

        if run_dt <= now:
            created_raw = l.get('created_at')
            created_at = (datetime.fromisoformat(created_raw)
                            if isinstance(created_raw, str) else created_raw)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            ts = created_at.strftime("%d.%m.%Y %H:%M")
            text = f"📨 Ваше письмо, составленное {ts}:\n\n{l['content']}"
            try:
                await bot.send_message(l['user_id'], text)
                await mark_letter_sent(l['id'])
            except TelegramBadRequest as e:
                logger.exception(f"Ошибка при немедленной отправке письма id={l['id']}", exc_info=e)
            continue

        content = l['content']
        scheduler.add_job(
            bot.send_message,
            trigger='date',
            run_date=run_dt,
            args=[
                l['user_id'],
                f"📨 Ваше письмо, из прошлого:\n\n{content}"
            ]
        )


def setup_future_letter_scheduler(bot: Bot):
    """
    Настраивает APScheduler:
    - ежедневная проверка unsent писем в 12:00 UTC
    - планирование уже имеющихся писем.
    """
    scheduler.add_job(
        deliver_future_letters,
        'cron',
        hour=12,
        minute=0,
        args=[bot]
    )
    scheduler.start()
    asyncio.get_event_loop().create_task(reschedule_pending(bot))


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_future_letter(dp: Dispatcher):
    dp.include_router(router)
