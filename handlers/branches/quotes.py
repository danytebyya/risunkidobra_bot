import re, json

from datetime import date
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils.database.db import fetch_daily_quote, upsert_daily_quote
from utils.chatgpt.gpt import generate_daily_quote_model
from handlers.core.subscription import is_subscribed
from handlers.core.start import START_TEXT, get_main_menu_kb
from config import SUPPORT_URL, logger
from utils.utils import safe_answer_callback


router = Router()


# ——————————————————————
# Утилиты для безопасного редактирования сообщений
# ——————————————————————
async def safe_edit_message(message: Message, text: str, **kwargs) -> bool:
    """
    Безопасно редактирует сообщение, обрабатывая ошибку 'message is not modified'.
    Возвращает True, если редактирование прошло успешно, False - если сообщение не изменилось.
    """
    try:
        await message.edit_text(text, **kwargs)
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug(f"Сообщение не изменилось, пропускаем редактирование: {e}")
            return False
        else:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            raise


# ——————————————————————
# Утилиты форматирования цитаты
# ——————————————————————
async def format_quote_message(quote: str, source: str | None) -> tuple[str, dict]:
    """
    Формирует Markdown-текст и дополнительные параметры для отправки цитаты.
    Возвращает кортеж (text, kwargs), где kwargs содержит reply_markup и parse_mode.
    """
    text = f"💬 *Цитата дня*:\n\n_{quote}_"
    if source:
        text += f"\n\n_{source}_"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_quote")]
    ])
    return text, {"reply_markup": kb, "parse_mode": "Markdown"}


# ——————————————————————
# Основной обработчик «Цитата дня»
# ——————————————————————
@router.callback_query(F.data == "quote_of_day")
async def quote_of_day_handler(call: CallbackQuery, state: FSMContext):
    """
    Получает «Цитату дня» для пользователя:
    — если уже сохранена, выводит её;
    — иначе проверяет подписку, запрашивает, сохраняет и показывает новую;
    — при отсутствии подписки предлагает оформить.
    """
    user_id = call.from_user.id
    today = date.today()  # today — объект date

    logger.info(f"Пользователь {user_id} запросил цитату дня за {today}")

    # Проверяем доступность сервиса
    from utils.service_checker import check_service_availability
    is_available, maintenance_message, keyboard = await check_service_availability("quote_of_day")
    
    if not is_available:
        if isinstance(call.message, Message):
            await safe_edit_message(call.message, maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.", reply_markup=keyboard)
        await safe_answer_callback(call, state)
        return

    existing = await fetch_daily_quote(user_id, today)
    if existing:
        quote, source = existing
        text, extra = await format_quote_message(quote, source)
        if isinstance(call.message, Message):
            await safe_edit_message(call.message, text, **extra)
        await safe_answer_callback(call, state)
        return

    if not await is_subscribed(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Что за подписка?", callback_data="subscription")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_edit_quote")]
        ])
        if isinstance(call.message, Message):
            await safe_edit_message(
                call.message,
                text="Чтобы получить «Цитату дня» и другие привилегии, оформите подписку Добрые открыточки+ 🫶",
                reply_markup=kb
            )
        await safe_answer_callback(call, state)
        return

    # Показываем индикатор загрузки
    if isinstance(call.message, Message):
        await safe_edit_message(call.message, "⏳ Генерируем цитату дня...")
    
    try:
        raw = await generate_daily_quote_model()
        if isinstance(raw, str):
            m = re.search(r"```json\s*(\{[\s\S]*?})\s*```", raw, re.DOTALL)
            json_str = m.group(1) if m else raw.strip("` \n")
            data = json.loads(json_str)
        else:
            data = raw
        quote = data.get("quote", "").strip("` \n")
        source = data.get("source") or None
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.error(f"Ошибка при генерации цитаты дня для {user_id}: {str(e)}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="quote_of_day")],
            [InlineKeyboardButton(text="✉️ Написать в поддержку", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_quote")]
        ])
        if isinstance(call.message, Message):
            await safe_edit_message(
                call.message,
                text="❌ Не удалось получить цитату. Попробуйте снова или свяжитесь с поддержкой.",
                reply_markup=kb
            )
        await safe_answer_callback(call, state)
        return

    await upsert_daily_quote(user_id, today, quote, source)
    text, extra = await format_quote_message(quote, source)
    if isinstance(call.message, Message):
        await safe_edit_message(call.message, text, **extra)
    await safe_answer_callback(call, state)


# ——————————————————————
# Возврат в главное меню из цитаты
# ——————————————————————
@router.callback_query(F.data == "main_menu_quote")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    """
    Убирает кнопку из цитаты и отправляет главное меню новым сообщением.
    """
    await safe_answer_callback(call, state)
    if isinstance(call.message, Message):
        # Убираем кнопку из сообщения с цитатой
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        # Отправляем главное меню новым сообщением
        await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "main_menu_edit_quote")
async def back_to_main_from_quote(call: CallbackQuery, state: FSMContext):
    """
    Пользователь без подписки нажал «Главное меню» из цитаты —
    редактируем текущее сообщение под основное меню.
    """
    await safe_answer_callback(call, state)
    if isinstance(call.message, Message):
        await safe_edit_message(
            call.message,
            START_TEXT,
            reply_markup=get_main_menu_kb()
        )


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_quote_handlers(dp):
    dp.include_router(router)
