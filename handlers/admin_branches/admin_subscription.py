from datetime import datetime, timezone

from aiogram import Router, F, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.utils import safe_answer_callback
from handlers.core.admin import START_TEXT, get_admin_menu_kb
from handlers.core.subscription import (
    activate_subscription
)
from utils.database.db import fetch_subscription, delete_subscription


router = Router()


class AdminSubStates(StatesGroup):
    sub_menu = State()
    sub_wait_id = State()
    sub_confirm_action = State()


# ——————————————————————
# Меню управления подписками
# ——————————————————————
@router.callback_query(F.data == "admin_subscriptions")
async def admin_subscriptions_menu(call: CallbackQuery, state: FSMContext):
    """Меню выбора типа подписки для управления."""
    await safe_answer_callback(call, state)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Добрые открыточки+", callback_data="admin_sub_choice:main")],
        [InlineKeyboardButton(text="🧠 Добрый психолог+", callback_data="admin_sub_choice:psychologist")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_back")]
    ])
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text="⚙️ Выберите тип подписки для управления:",
            reply_markup=kb
        )
    await state.set_state(AdminSubStates.sub_menu)


# ——————————————————————
# Выбор типа подписки
# ——————————————————————
@router.callback_query(AdminSubStates.sub_menu, F.data.startswith("admin_sub_choice:"))
async def admin_sub_choice(call: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор типа подписки и сразу запрашивает ID пользователя."""
    await safe_answer_callback(call, state)
    
    subscription_type = call.data.split(':')[1]
    await state.update_data(subscription_type=subscription_type)
    
    if call.message:
        await state.update_data(
            prompt_chat_id=call.message.chat.id,
            prompt_message_id=call.message.message_id,
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_sub")]
        ])
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text="Введите Telegram ID пользователя для управления подпиской:",
                reply_markup=kb
            )
    await state.set_state(AdminSubStates.sub_wait_id)


# ——————————————————————
# Управление подпиской
# ——————————————————————


@router.message(AdminSubStates.sub_wait_id)
async def handle_user_id_input(message: Message, state: FSMContext):
    """Обрабатывает ввод ID, проверяет подписку и предлагает действие."""
    await message.delete()
    data = await state.get_data()
    chat_id = data["prompt_chat_id"]
    msg_id = data["prompt_message_id"]
    
    if not message.text:
        if message.bot:
            await message.bot.send_message(chat_id, "❌ Пожалуйста, введите корректный числовой ID.")
        return
    
    text = message.text.strip()
    if not text.isdigit():
        if message.bot:
            await message.bot.send_message(chat_id, "❌ Пожалуйста, введите корректный числовой ID.")
        return
    user_id = int(text)
    user_name = None
    if message.bot:
        try:
            chat = await message.bot.get_chat(user_id)
            user_name = chat.full_name
        except TelegramBadRequest:
            user_name = None

    data = await state.get_data()
    subscription_type = data.get("subscription_type", "main")
    record = await fetch_subscription(user_id, type=subscription_type)
    now_utc = datetime.now(timezone.utc)

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if record and record["expires_at"] > now_utc:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="🗑️ Отменить подписку", callback_data="confirm_subscription")
        ])
        action = "remove"
    else:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text="✅ Выдать подписку", callback_data="confirm_subscription")
        ])
        action = "add"
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_sub")
    ])
    display_name = (
        f"{user_name} (ID: {user_id})"
        if user_name else
        f"ID: {user_id}"
    )
    text_to_show = (
        f"Пользователь: {display_name}\n"
        f"Текущее состояние подписки: "
        + (f"активна до {record['expires_at'].strftime('%Y-%m-%d')}"
           if record and record["expires_at"] > now_utc
           else "нет активной подписки")
        + "\n\nВыберите действие:"
    )

    if message.bot:
        await message.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text_to_show,
            reply_markup=kb
        )
    await state.update_data(user_id=user_id, action=action)
    await state.set_state(AdminSubStates.sub_confirm_action)


@router.callback_query(AdminSubStates.sub_confirm_action, F.data == "confirm_subscription")
async def admin_sub_confirm(call: CallbackQuery, state: FSMContext):
    """Выполняет добавление или удаление подписки."""
    await safe_answer_callback(call, state)
    data = await state.get_data()
    user_id = data["user_id"]
    action = data["action"]
    chat_id = data["prompt_chat_id"]
    msg_id = data["prompt_message_id"]

    data = await state.get_data()
    subscription_type = data.get("subscription_type", "main")
    sub_name = "Добрые открыточки+" if subscription_type == "main" else "Добрый психолог+"
    
    if action == "add":
        expires = await activate_subscription(user_id, days=30, subscription_type=subscription_type)
        # Обнуляем бесплатные сообщения, если это психолог
        if subscription_type == "psychologist":
            from utils.database.db import set_free_count
            await set_free_count(user_id, 0)
        result_text = f"🎉 Подписка «{sub_name}» выдана пользователю ID {user_id} до {expires.strftime('%Y-%m-%d')}."
    else:
        await delete_subscription(user_id, type=subscription_type)
        result_text = f"🗑️ Подписка «{sub_name}» пользователя ID {user_id} удалена."

    await state.clear()

    if call.bot:
        await call.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=result_text
        )
        await call.bot.send_message(
            chat_id=chat_id,
            text=START_TEXT,
            reply_markup=get_admin_menu_kb()
        )


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_admin_sub")
async def go_back_admin_sub(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя на предыдущий шаг или в главное меню админа."""
    await safe_answer_callback(call, state)
    current = await state.get_state()

    if current == AdminSubStates.sub_confirm_action.state:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_sub")]
        ])
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text="Введите Telegram ID пользователя для управления подпиской:",
                reply_markup=kb
            )
        await state.set_state(AdminSubStates.sub_wait_id)
        return

    if current == AdminSubStates.sub_menu.state:
        # Возвращаемся к выбору типа подписки
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Добрые открыточки+", callback_data="admin_sub_choice:main")],
            [InlineKeyboardButton(text="🧠 Добрый психолог+", callback_data="admin_sub_choice:psychologist")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text="⚙️ Выберите тип подписки для управления:",
                reply_markup=kb
            )
        await state.set_state(AdminSubStates.sub_menu)
        return

    if current == AdminSubStates.sub_wait_id.state:
        # Возвращаемся к выбору типа подписки
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Добрые открыточки+", callback_data="admin_sub_choice:main")],
            [InlineKeyboardButton(text="🧠 Добрый психолог+", callback_data="admin_sub_choice:psychologist")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text="⚙️ Выберите тип подписки для управления:",
                reply_markup=kb
            )
        await state.set_state(AdminSubStates.sub_menu)
        return

    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.bot.delete_message(msg.chat.id, msg.message_id)
        await msg.bot.send_message(
            chat_id=msg.chat.id,
            text=START_TEXT,
            reply_markup=get_admin_menu_kb()
        )
    await state.clear()


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_subscriptions(dp: Dispatcher):
    dp.include_router(router)