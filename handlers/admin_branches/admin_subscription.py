from datetime import datetime, timezone

from aiogram import Router, F, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.utils import safe_call_answer
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
    """Меню управления подписками."""
    await safe_call_answer(call)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Проверить / Управлять", callback_data="admin_sub_check")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
    ])
    await call.message.edit_text("⚙️ Меню управления подписками:", reply_markup=kb)
    await state.set_state(AdminSubStates.sub_menu)


# ——————————————————————
# Управление подпиской
# ——————————————————————
@router.callback_query(AdminSubStates.sub_menu, F.data == "admin_sub_check")
async def admin_sub_check(call: CallbackQuery, state: FSMContext):
    """Запрашивает у администратора ID пользователя."""
    await safe_call_answer(call)
    await state.update_data(
        prompt_chat_id=call.message.chat.id,
        prompt_message_id=call.message.message_id,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_sub")]
    ])
    await call.message.edit_text(
        "Введите Telegram ID пользователя для управления подпиской:",
        reply_markup=kb
    )
    await state.set_state(AdminSubStates.sub_wait_id)


@router.message(AdminSubStates.sub_wait_id)
async def handle_user_id_input(message: Message, state: FSMContext):
    """Обрабатывает ввод ID, проверяет подписку и предлагает действие."""
    await message.delete()
    data = await state.get_data()
    chat_id = data["prompt_chat_id"]
    msg_id = data["prompt_message_id"]
    text = message.text.strip()
    if not text.isdigit():
        return await message.answer("❌ Пожалуйста, введите корректный числовой ID.")
    user_id = int(text)
    try:
        chat = await message.bot.get_chat(user_id)
        user_name = chat.full_name
    except TelegramBadRequest:
        user_name = None

    record = await fetch_subscription(user_id)
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
    await safe_call_answer(call)
    data = await state.get_data()
    user_id = data["user_id"]
    action = data["action"]
    chat_id = data["prompt_chat_id"]
    msg_id = data["prompt_message_id"]

    if action == "add":
        expires = await activate_subscription(user_id, days=30)
        result_text = f"🎉 Подписка выдана пользователю ID {user_id} до {expires.strftime('%Y-%m-%d')}."
    else:
        await delete_subscription(user_id)
        result_text = f"🗑️ Подписка пользователя ID {user_id} удалена."

    await state.clear()

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
    await safe_call_answer(call)
    current = await state.get_state()

    if current == AdminSubStates.sub_confirm_action.state:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_sub")]
        ])
        await call.message.edit_text(
            "Введите Telegram ID пользователя для управления подпиской:",
            reply_markup=kb
        )
        await state.set_state(AdminSubStates.sub_wait_id)
        return

    if current == AdminSubStates.sub_wait_id.state:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Проверить / Управлять", callback_data="admin_sub_check")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        await call.message.edit_text(
            "⚙️ Меню управления подписками:",
            reply_markup=kb
        )
        await state.set_state(AdminSubStates.sub_menu)
        return

    await call.message.delete()
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())
    await state.clear()


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_subscriptions(dp: Dispatcher):
    dp.include_router(router)
