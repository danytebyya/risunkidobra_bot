import re

from aiogram import types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.exceptions import TelegramBadRequest

from config import logger


def is_russian(text: str) -> bool:
    return bool(re.fullmatch(r"[а-яА-ЯёЁ\d\s.,!?\-:;()]+", text))


async def safe_edit_text(target, text: str, reply_markup=None, **kwargs):
    """
    Безопасно редактирует сообщение или его подпись, игнорируя ошибки о том, что
    сообщение не изменилось или не найдено.
    """
    try:
        # если передали сам объект Message
        if isinstance(target, types.Message):
            msg = target
            if getattr(msg, "photo", None) or getattr(msg, "document", None) or getattr(msg, "video", None):
                await msg.edit_caption(caption=text, reply_markup=reply_markup, **kwargs)
            else:
                await msg.edit_text(text=text, reply_markup=reply_markup, **kwargs)
        # или передали словарь с ботом и id
        else:
            bot = target["bot"]
            chat_id = target["chat_id"]
            message_id = target["message_id"]
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                **kwargs
            )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if (
            "message is not modified" in msg
            or "no text in the message to edit" in msg
            or "message to edit not found" in msg
        ):
            logger.debug(f"safe_edit_text skipped: {e}")
        else:
            raise


async def safe_edit_media(message: types.Message, media, reply_markup=None):
    """Безопасно изменяет медиа сообщения, игнорируя ошибки, если медиа не изменилось"""
    try:
        await message.edit_media(media=media, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        msg = str(e)
        if 'message is not modified' in msg or 'message to edit not found' in msg:
            logger.debug(f'safe_edit_media skipped: {e}')
        else:
            raise


async def push_state(state: FSMContext, new_state: State):
    """Сохраняет текущий stack состояний и переводит машину состояний в новое состояние"""
    data = await state.get_data()
    stack = data.get('state_stack', [])
    current = await state.get_state()
    if current:
        stack.append(current)
    await state.update_data(state_stack=stack)
    await state.set_state(new_state)


async def validate_text(message: Message, state: FSMContext) -> bool:
    """Обрабатывает и проверяет введенный текст пользователя."""
    text = (message.text or "").strip()
    data = await state.get_data()

    if not is_russian(text):
        prompt_id = data.get('text_prompt_msg_id')
        if prompt_id:
            try:
                if message.bot is not None:
                    await message.bot.delete_message(chat_id=message.chat.id, message_id=prompt_id)
            except TelegramBadRequest:
                logger.debug("Не удалось удалить сообщение-подсказку при ошибке ввода")
        try:
            await message.delete()
        except TelegramBadRequest:
            logger.debug("Не удалось удалить некорректный ввод пользователя")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Назад', callback_data='go_back')]
        ])
        err = await message.answer(
            '❌ Только русский текст и спецсимволы, повторите ввод',
            reply_markup=keyboard
        )
        await state.update_data(text_prompt_msg_id=err.message_id)
        return False

    prompt_id = data.get('text_prompt_msg_id')
    if prompt_id:
        try:
            if message.bot is not None:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=prompt_id)
        except TelegramBadRequest:
            logger.debug("Не удалось удалить подсказку перед финальной генерацией")
    try:
        await message.delete()
    except TelegramBadRequest:
        logger.debug("Не удалось удалить сообщение пользователя с валидным текстом")

    await state.update_data(user_text=text)
    return True


async def safe_call_answer(call, *args, **kwargs):
    """
        Безопасно отвечает на callback query, подавляя TelegramBadRequest,
        если ответ не может быть отправлен (например, уже был отправлен).
        """
    try:
        await call.answer(*args, **kwargs)
    except TelegramBadRequest:
        pass


async def safe_answer_callback(call: types.CallbackQuery, state: FSMContext | None = None):
    """Безопасно отвечает на callback query, обрабатывая устаревшие запросы"""
    try:
        await call.answer()
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            # Обрабатываем устаревшие callback query
            if state:
                await handle_stale_callback(call, state)
            # Иначе просто игнорируем
        else:
            # Перебрасываем другие ошибки
            raise


async def handle_stale_callback(call: types.CallbackQuery, state: FSMContext):
    """Обрабатывает устаревшие callback query, возвращая пользователя в актуальное состояние"""
    try:
        await safe_call_answer(call, "⚠️ Что-то пошло не так, возвращаем вас в актуальное состояние...")
    except TelegramBadRequest:
        # Если даже ответить не можем, просто игнорируем
        pass
    
    # Определяем текущее состояние и возвращаем пользователя в актуальное место
    current = await state.get_state()
    data = await state.get_data()
    
    # Если есть данные о выбранных параметрах, возвращаем в меню создания открытки
    if data.get('selected_image') or data.get('selected_font') or data.get('selected_color'):
        # Импортируем здесь, чтобы избежать циклических импортов
        from handlers.branches.generic_picture import create_card
        await create_card(call, state, force_new_message=True)
    elif data.get('is_surprise'):
        # Для сюрприз-идей НЕ отправляем главное меню автоматически
        pass
    else:
        # Иначе возвращаем в главное меню
        from handlers.core.start import START_TEXT, get_main_menu_kb
        if call.message and isinstance(call.message, types.Message):
            await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
