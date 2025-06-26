from aiogram import Router, F, types, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.core.start import START_TEXT, get_main_menu_kb
from handlers.core.subscription import is_subscribed
from utils.chatgpt.gpt import generate_response, generate_response_with_edits
from utils.payments.payment_functional import create_payment, check_payment_status
from utils.utils import safe_edit_text, safe_call_answer
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
    """Отображает меню выбора темы поздравления."""
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Дружба",    callback_data="congrats_type_friendship")],
        [InlineKeyboardButton(text="Любовь",    callback_data="congrats_type_love")],
        [InlineKeyboardButton(text="Нейтральная", callback_data="congrats_type_neutral")],
        [InlineKeyboardButton(text="Родственники", callback_data="congrats_type_relatives")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
    ])
    await call.message.edit_text(
        text=(
            "✨ Добро пожаловать в генератор поздравлений!\n\n"
            "♡ Выберите тему поздравления — от дружбы до семьи, "
            "и мы придумаем идеальные слова.\n\n"
            "👇 Кому вы хотите адресовать эти тёплые пожелания?"
        ),
        reply_markup=kb
    )
    await safe_call_answer(call)


# ——————————————————————
# Выбор темы поздравления
# ——————————————————————
@router.callback_query(F.data.startswith("congrats_type_"))
async def congrats_type(call: CallbackQuery, state: FSMContext):
    """Сохраняет выбранную тему поздравления и запрашивает у пользователя детали."""
    await state.update_data(
        current_file_index=0
    )
    ru_names = {
        "friendship": "Дружба",
        "love":       "Любовь",
        "neutral":    "Нейтральная",
        "relatives":  "Родственники"
    }
    key = call.data.split("congrats_type_")[1]
    category_ru = ru_names.get(key)
    await state.update_data(category_ru=category_ru)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")]
    ])
    msg = await call.message.edit_text(
        text=(
            "📝 Расскажите, кому адресовано поздравление, "
            "какие детали учесть и какие тёплые слова вы хотите услышать. "
            "Поделитесь идеями, а мы их воплотим!"
        ),
        reply_markup=kb
    )
    await state.update_data(details_message_id=msg.message_id)
    await state.set_state(CongratsStates.input_congrats_prompt)
    await safe_call_answer(call)


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
    await message.delete()


    if await is_subscribed(message.from_user.id):
        data = await state.get_data()
        await message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=data["details_message_id"],
        )
        loading = await message.answer("⚙️ Создаем поздравление...")
        generated = await generate_response((await state.get_data())["category_ru"], text)
        await state.update_data(current_congratulation=generated)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Новый текст (0/10)", callback_data="regenerate_congrats"),
                InlineKeyboardButton(text="✏️ Скорректировать (0/10)", callback_data="edit_congrats"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
        ])

        sent = await message.bot.send_message(
            chat_id=message.chat.id,
            text=generated,
            reply_markup=kb
        )
        await state.update_data(details_message_id=sent.message_id)
        await message.bot.delete_message(chat_id=loading.chat.id, message_id=loading.message_id)
    else:
        url, pid = await create_payment(message.from_user.id, 50, "Оплата за поздравление")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Оплатить поздравление", url=url)],
            [InlineKeyboardButton(text="📬 Получить поздравление", callback_data=f"check_congrats:{pid}")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")],
        ])

        data = await state.get_data()
        await message.bot.edit_message_text(
            text=(
                "💌 Оформите заказ — оплатите поздравление, "
                "и мы мгновенно отправим его вам в чат!"
            ),
            chat_id=message.chat.id,
            message_id=data["details_message_id"],
            reply_markup=kb
        )

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
    pid = call.data.split(":", 1)[1]
    status = await check_payment_status(pid)
    if status != "succeeded":
        await call.answer(text="❌ Платёж не подтверждён", show_alert=True)
        return

    await call.answer()
    chat_id = call.message.chat.id
    await call.message.delete()

    loading = await call.bot.send_message(chat_id=chat_id, text="⚙️ Создаем поздравление...")

    data = await state.get_data()
    await state.update_data(paid_pid=pid)

    try:
        text = await generate_response(data["category_ru"], data["user_prompt"])
    except Exception as e:
        logger.error(f"Error in generate_response: {e}")
        kb_err = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать снова", callback_data="regenerate_congrats")],
            [InlineKeyboardButton(text="Написать в поддержку",   url=SUPPORT_URL)],
            [InlineKeyboardButton(text="⏎ Назад",                callback_data="go_back_congrats")],
        ])
        await call.message.edit_text("❌ Произошла ошибка при генерации поздравления.", reply_markup=kb_err)
        await call.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        await safe_call_answer(call)
        return

    await state.update_data(current_congratulation=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Новый текст (0/5)", callback_data="regenerate_congrats"),
            InlineKeyboardButton(text="✏️ Скорректировать (0/5)", callback_data="edit_congrats"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
    ])
    await call.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
    await call.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
    await safe_call_answer(call)


# ——————————————————————
# Новая генерация поздравления
# ——————————————————————
@router.callback_query(F.data == "regenerate_congrats")
async def regenerate_congratulation(call: CallbackQuery, state: FSMContext):
    """Создаст новое поздравление с учётом лимита попыток и предыдущих правок, если они были."""
    user_id = call.from_user.id
    max_attempts = 10 if await is_subscribed(user_id) else 5

    data = await state.get_data()
    cnt = data.get("regeneration_count", 0)
    if cnt >= max_attempts:
        await call.answer(text="❌ Достигнут лимит попыток", show_alert=True)
        return

    cnt += 1
    await state.update_data(regeneration_count=cnt)

    category = data["category_ru"]
    base_prompt = data["user_prompt"]
    edits = data.get("edits", [])

    try:
        if edits:
            new_text = await generate_response_with_edits(
                category,
                base_prompt,
                edits
            )
        else:
            new_text = await generate_response(
                category,
                base_prompt
            )
    except Exception as e:
        logger.error(f"Error in regenerate_response: {e}")
        kb_err = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="regenerate_congrats")],
            [InlineKeyboardButton(text="✉️ Написать в поддержку", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")],
        ])
        await call.message.answer("❌ Произошла ошибка при генерации поздравления.", reply_markup=kb_err)
        await safe_call_answer(call)
        return

    await state.update_data(current_congratulation=new_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🔄 Новый текст ({cnt}/{max_attempts})", callback_data="regenerate_congrats"),
            InlineKeyboardButton(text=f"✏️ Скорректировать ({cnt}/{max_attempts})", callback_data="edit_congrats"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
    ])
    await call.message.edit_text(new_text, reply_markup=kb)
    await safe_call_answer(call)


# ——————————————————————
# Редактирование поздравления
# ——————————————————————
@router.callback_query(F.data == "edit_congrats")
async def edit_congrats_start(call: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя ввод правок к ранее сгенерированному поздравлению."""
    data = await state.get_data()
    cnt = data.get("regeneration_count", 0)
    max_attempts = 10 if await is_subscribed(call.from_user.id) else 5
    if cnt >= max_attempts:
        await call.answer(text="❌ Достигнут лимит попыток", show_alert=True)
        return

    msg = await call.message.edit_text(
        text="🖋 Что бы вы хотели скорректировать в поздравлении?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")]
        ])
    )
    await state.update_data(edit_prompt_message_id=msg.message_id)
    await state.set_state(CongratsStates.input_edit_prompt)
    await safe_call_answer(call)


@router.message(CongratsStates.input_edit_prompt)
async def input_edit_prompt(message: types.Message, state: FSMContext):
    edit_text = message.text.strip()
    await message.delete()

    data = await state.get_data()
    chat_id = message.chat.id

    prompt_id = data.get("edit_prompt_message_id")
    if prompt_id:
        await message.bot.delete_message(chat_id=chat_id, message_id=prompt_id)

    loading = await message.answer("⚙️ Вносим правки...")

    base_prompt = data["user_prompt"]
    edits = data.get("edits", [])
    edits.append(edit_text)
    cnt = data.get("regeneration_count", 0) + 1
    await state.update_data(edits=edits, regeneration_count=cnt)

    new_generated = await generate_response_with_edits(
        data["category_ru"],
        base_prompt,
        edits
    )
    await state.update_data(current_congratulation=new_generated)

    max_attempts = 10 if await is_subscribed(message.from_user.id) else 5
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🔄 Новый текст ({cnt}/{max_attempts})", callback_data="regenerate_congrats"),
            InlineKeyboardButton(text=f"✏️ Скорректировать ({cnt}/{max_attempts})", callback_data="edit_congrats"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
    ])
    await message.answer(new_generated, reply_markup=kb)
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
        max_attempts = 10 if await is_subscribed(call.from_user.id) else 5
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔄 Новый текст ({cnt}/{max_attempts})", callback_data="regenerate_congrats"),
                InlineKeyboardButton(text=f"✏️ Скорректировать ({cnt}/{max_attempts})", callback_data="edit_congrats"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="return_to_main")],
        ])
        await safe_edit_text(call.message, text=text, reply_markup=kb)
        await state.set_state(None)
        await safe_call_answer(call)
        return

    if current == CongratsStates.input_congrats_prompt.state:
        await congrats_start(call, state)
        return

    if not current and details_msg_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_congrats")],
        ])
        await safe_edit_text(
            {"bot": call.bot, "chat_id": call.message.chat.id, "message_id": details_msg_id},
            text=(
                "📝 Расскажите, кому адресовано поздравление, "
                "какие детали учесть и какие тёплые слова вы хотите услышать. "
                "Поделитесь идеями, а мы их воплотим!"
            ),
            reply_markup=kb
        )
        await state.set_state(CongratsStates.input_congrats_prompt)
        await safe_call_answer(call)
        return

    await state.clear()
    await safe_edit_text(call.message, text=START_TEXT, reply_markup=get_main_menu_kb())
    await safe_call_answer(call)


@router.callback_query(F.data == "return_to_main")
async def return_to_main(call: CallbackQuery):
    """Очищает клавиатуру и возвращает пользователя в главное меню."""
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
    await safe_call_answer(call)


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_congrats_handlers(dp: Dispatcher):
    """Регистрирует маршрутизатор для генератора поздравлений."""
    dp.include_router(router)
