from aiogram import Router, F, types, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.core.start import START_TEXT, get_main_menu_kb
from handlers.core.subscription import is_subscribed
from utils.chatgpt.gpt import generate_response, generate_response_with_edits
from utils.payments.payment_functional import create_payment, check_payment_status
from utils.utils import safe_edit_text, safe_answer_callback
from config import logger, SUPPORT_URL


router = Router()


class CongratsStates(StatesGroup):
    input_congrats_prompt = State()
    input_edit_prompt = State()


# ——————————————————————
# Меню генератора поздравлений
# ——————————————————————
@router.callback_query(F.data == "congrats")
async def congrats_start(call: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя детали поздравления сразу."""
    await state.clear()
    user_id = call.from_user.id if call.from_user else None
    logger.info(f"Пользователь {user_id} переключился на вкладку «Теплое поздравление»")
    
    # Проверяем доступность сервиса
    from utils.service_checker import check_service_availability
    is_available, maintenance_message, keyboard = await check_service_availability("congrats")
    
    if not is_available:
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text=maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard
            )
        await safe_answer_callback(call, state)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
    ])
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text=(
                "✨ Добро пожаловать в генератор поздравлений!\n\n"
                "♡ Расскажите, кому адресовано поздравление, какие детали учесть и какие тёплые слова вы хотите услышать.\n\n"
                "Поделитесь идеями, а мы их воплотим!\n\n"
            ),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
        # Сохраняем message_id приветственного сообщения
        await state.update_data(details_message_id=call.message.message_id)
    await state.set_state(CongratsStates.input_congrats_prompt)
    await safe_answer_callback(call, state)


# ——————————————————————
# Ввод пользовательского запроса
# ——————————————————————
@router.message(CongratsStates.input_congrats_prompt)
async def input_congrats_prompt(message: types.Message, state: FSMContext):
    """
    Получает от пользователя текст запроса и
    либо генерирует поздравление (если подписка есть),
    либо предлагает оплатить.
    """
    text = message.text or ""
    if len(text) > 255:
        await message.answer("❌ Слишком длинный запрос! Пожалуйста, введите более короткий запрос.")
        return

    await state.update_data(user_prompt=text, regeneration_count=0)

    # Удаляем приветственное сообщение, если оно есть
    data = await state.get_data()
    details_message_id = data.get("details_message_id")
    deleted = False
    if details_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=details_message_id)
            deleted = True
        except TelegramBadRequest:
            pass

    try:
        await message.delete()  # Удаляем сообщение пользователя
    except TelegramBadRequest:
        pass

    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("❌ Не удалось определить пользователя. Попробуйте еще раз.")
        return
    if await is_subscribed(user_id):
        data = await state.get_data()
        details_message_id = data.get("details_message_id")
        if details_message_id and message.bot is not None and not deleted:
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=details_message_id,
                )
            except TelegramBadRequest:
                pass
        loading = await message.answer("⚙️ Создаем поздравление...")  # Показываем загрузку
        generated = await generate_response(text)  # Генерируем поздравление
        await state.update_data(current_congratulation=generated)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Новый текст (0/10)", callback_data="regenerate_congrats"),
                InlineKeyboardButton(text="✏️ Скорректировать (0/10)", callback_data="edit_congrats"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
        ])

        # Удаляем сообщение о загрузке
        if message.bot is not None and loading is not None and hasattr(loading, 'chat') and hasattr(loading, 'message_id'):
            try:
                await message.bot.delete_message(chat_id=loading.chat.id, message_id=loading.message_id)
            except TelegramBadRequest:
                pass

        # Только после удаления загрузки отправляем результат
        sent = await message.answer(
            text=generated,
            reply_markup=kb
        )
        await state.update_data(details_message_id=sent.message_id)
    else:
        url, pid = await create_payment(user_id, 100, "Оплата за поздравление")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Оплатить поздравление", url=url)],
            [InlineKeyboardButton(text="📬 Получить поздравление", callback_data=f"check_congrats:{pid}")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")],
        ])

        data = await state.get_data()
        details_message_id = data.get("details_message_id")
        if details_message_id and message.bot is not None:
            try:
                await message.bot.edit_message_text(
                    text=(
                        "💌 Оформите заказ — оплатите поздравление, "
                        "и мы мгновенно отправим его вам в чат!"
                    ),
                    chat_id=message.chat.id,
                    message_id=details_message_id,
                    reply_markup=kb
                )
            except TelegramBadRequest:
                pass

    await state.set_state(None)


# ——————————————————————
# Проверка оплаты поздравления
# ——————————————————————
@router.callback_query(F.data.startswith("check_congrats:"))
async def check_congrats_payment(call: CallbackQuery, state: FSMContext):
    """
    Проверяет статус платежа. При успешной оплате
    генерирует и отправляет поздравление.
    """
    pid = call.data.split(":", 1)[1] if call.data and ":" in call.data else None
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return
    status = await check_payment_status(pid)

    if status != "succeeded":
        await call.answer(text="❌ Платёж не подтверждён", show_alert=True)
        logger.warning(
            f"Платёж {pid} пользователя {user_id} для поздравления не подтверждён "
            f"(статус={status})"
        )
        return
    logger.info(f"Пользователь {user_id} получил поздравление (payment_id={pid})")

    await safe_answer_callback(call, state)
    chat_id = call.message.chat.id if call.message else None
    if call.message and hasattr(call.message, "message_id") and chat_id is not None and call.bot is not None:
        await call.bot.delete_message(chat_id=chat_id, message_id=call.message.message_id)

    loading = None
    if chat_id is not None and call.bot is not None:
        loading = await call.bot.send_message(chat_id=chat_id, text="⚙️ Создаем поздравление...")

    data = await state.get_data()
    await state.update_data(paid_pid=pid)

    try:
        text = await generate_response(data["user_prompt"])
    except TelegramBadRequest:
        logger.error(
            f"Ошибка генерации поздравления после оплаты для {user_id} "
            f"(payment_id={pid})"
        )
        kb_err = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать снова", callback_data="regenerate_congrats")],
            [InlineKeyboardButton(text="Написать в поддержку",   url=SUPPORT_URL)],
            [InlineKeyboardButton(text="⏎ Назад",                callback_data="go_back_congrats")],
        ])
        if call.message and hasattr(call.message, "message_id") and chat_id is not None and call.bot is not None:
            await call.bot.edit_message_text(
                "❌ Произошла ошибка при генерации поздравления.",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=kb_err
            )
        if loading and call.bot is not None and chat_id is not None:
            await call.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        await safe_answer_callback(call, state)
        return

    await state.update_data(current_congratulation=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Новый текст (0/5)", callback_data="regenerate_congrats"),
            InlineKeyboardButton(text="✏️ Скорректировать (0/5)", callback_data="edit_congrats"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
    ])
    if chat_id is not None and call.bot is not None:
        await call.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
    if loading and call.bot is not None and chat_id is not None:
        await call.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
    await safe_answer_callback(call, state)


# ——————————————————————
# Новая генерация поздравления
# ——————————————————————
@router.callback_query(F.data == "regenerate_congrats")
async def regenerate_congratulation(call: CallbackQuery, state: FSMContext):
    """Создаст новое поздравление с учётом лимита попыток и предыдущих правок, если они были."""
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return
    max_attempts = 10 if await is_subscribed(user_id) else 5

    data = await state.get_data()
    cnt = data.get("regeneration_count", 0)
    if cnt >= max_attempts:
        await call.answer(text="❌ Достигнут лимит попыток", show_alert=True)
        return

    cnt += 1
    await state.update_data(regeneration_count=cnt)

    base_prompt = data["user_prompt"]
    edits = data.get("edits", [])

    # 1. Удаляем текущее сообщение с поздравлением
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        try:
            await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except TelegramBadRequest:
            pass

    # 2. Отправляем сообщение ожидания
    loading = None
    if call.message and call.bot is not None:
        loading = await call.bot.send_message(chat_id=call.message.chat.id, text="⚙️ Создаем новый текст...")

    try:
        if edits:
            new_text = await generate_response_with_edits(base_prompt, edits)
        else:
            new_text = await generate_response(base_prompt)
    except TelegramBadRequest:
        kb_err = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="regenerate_congrats")],
            [InlineKeyboardButton(text="✉️ Написать в поддержку", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")],
        ])
        if loading and call.bot is not None and call.message is not None:
            try:
                await call.bot.edit_message_text(
                    text="❌ Произошла ошибка при генерации поздравления.",
                    chat_id=call.message.chat.id,
                    message_id=loading.message_id,
                    reply_markup=kb_err
                )
            except TelegramBadRequest:
                pass
        await safe_answer_callback(call, state)
        return

    await state.update_data(current_congratulation=new_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🔄 Новый текст ({cnt}/{max_attempts})", callback_data="regenerate_congrats"),
            InlineKeyboardButton(text=f"✏️ Скорректировать ({cnt}/{max_attempts})", callback_data="edit_congrats"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
    ])
    # 3. Удаляем сообщение ожидания и отправляем новое поздравление
    if loading and call.bot is not None and call.message is not None:
        try:
            await call.bot.delete_message(chat_id=call.message.chat.id, message_id=loading.message_id)
        except TelegramBadRequest:
            pass
        sent = await call.bot.send_message(
            chat_id=call.message.chat.id,
            text=new_text,
            reply_markup=kb
        )
        await state.update_data(details_message_id=sent.message_id)
    # Удаляю вызов safe_answer_callback, чтобы не появлялось главное меню
    # await safe_answer_callback(call, state)


# ——————————————————————
# Редактирование поздравления
# ——————————————————————
@router.callback_query(F.data == "edit_congrats")
async def edit_congrats_start(call: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя ввод правок к ранее сгенерированному поздравлению."""
    data = await state.get_data()
    cnt = data.get("regeneration_count", 0)
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return
    max_attempts = 10 if await is_subscribed(user_id) else 5
    if cnt >= max_attempts:
        await call.answer(text="❌ Достигнут лимит попыток", show_alert=True)
        return

    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        msg = await call.bot.edit_message_text(
            text="🖋 Что бы вы хотели скорректировать в поздравлении?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")]
            ])
        )
        await state.update_data(edit_prompt_message_id=call.message.message_id)
    await state.set_state(CongratsStates.input_edit_prompt)
    await safe_answer_callback(call, state)


@router.message(CongratsStates.input_edit_prompt)
async def input_edit_prompt(message: types.Message, state: FSMContext):
    edit_text = (message.text or "").strip()
    await message.delete()

    data = await state.get_data()
    chat_id = message.chat.id

    prompt_id = data.get("edit_prompt_message_id")
    if prompt_id and message.bot is not None and chat_id is not None:
        await message.bot.delete_message(chat_id=chat_id, message_id=prompt_id)

    loading = await message.answer("⚙️ Вносим правки...")

    base_prompt = data["user_prompt"]
    edits = data.get("edits", [])
    edits.append(edit_text)
    cnt = data.get("regeneration_count", 0) + 1
    await state.update_data(edits=edits, regeneration_count=cnt)

    new_generated = await generate_response_with_edits(base_prompt, edits)
    await state.update_data(current_congratulation=new_generated)

    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("❌ Не удалось определить пользователя. Попробуйте еще раз.")
        return
    max_attempts = 10 if await is_subscribed(user_id) else 5
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🔄 Новый текст ({cnt}/{max_attempts})", callback_data="regenerate_congrats"),
            InlineKeyboardButton(text=f"✏️ Скорректировать ({cnt}/{max_attempts})", callback_data="edit_congrats"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
    ])
    await message.answer(new_generated, reply_markup=kb)
    if loading and hasattr(loading, 'chat') and hasattr(loading, 'message_id') and message.bot is not None:
        await message.bot.delete_message(chat_id=loading.chat.id, message_id=loading.message_id)
    await state.set_state(None)


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_congrats")
async def go_back(call: CallbackQuery, state: FSMContext):
    """Универсальный «Назад» для flow поздравлений."""
    current = await state.get_state()
    data = await state.get_data()
    details_msg_id = data.get("details_message_id")

    if current == CongratsStates.input_edit_prompt.state:
        text = data.get("current_congratulation", "")
        cnt = data.get("regeneration_count", 0)
        user_id = call.from_user.id if call.from_user else None
        if user_id is None:
            await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
            return
        max_attempts = 10 if await is_subscribed(user_id) else 5
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔄 Новый текст ({cnt}/{max_attempts})", callback_data="regenerate_congrats"),
                InlineKeyboardButton(text=f"✏️ Скорректировать ({cnt}/{max_attempts})", callback_data="edit_congrats"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
        ])
        await safe_edit_text(call.message, text=text, reply_markup=kb)
        await state.set_state(None)
        await safe_answer_callback(call, state)
        return

    if current == CongratsStates.input_congrats_prompt.state:
        await congrats_start(call, state)
        return

    if not current and details_msg_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")],
        ])
        if call.message and hasattr(call.message, "chat") and hasattr(call.message, "message_id") and call.bot is not None:
            await safe_edit_text(
                {"bot": call.bot, "chat_id": call.message.chat.id, "message_id": details_msg_id},
                text=(
                    "✨ Добро пожаловать в генератор поздравлений!\n\n"
                    "♡ Расскажите, кому адресовано поздравление, какие детали учесть и какие тёплые слова вы хотите услышать.\n\n "
                    "Поделитесь идеями, а мы их воплотим!"
                ),
                reply_markup=kb
            )
        await state.set_state(CongratsStates.input_congrats_prompt)
        await safe_answer_callback(call, state)
        return

    await state.clear()
    if call.message and hasattr(call.message, "chat") and hasattr(call.message, "message_id") and call.bot is not None:
        await safe_edit_text(call.message, text=START_TEXT, reply_markup=get_main_menu_kb())
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "return_to_main")
async def return_to_main(call: CallbackQuery, state: FSMContext):
    """Очищает клавиатуру и возвращает пользователя в главное меню."""
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None
        )
        await call.bot.send_message(
            chat_id=call.message.chat.id,
            text=START_TEXT,
            reply_markup=get_main_menu_kb()
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_congrats_handlers(dp: Dispatcher):
    """Регистрирует маршрутизатор для генератора поздравлений."""
    dp.include_router(router)