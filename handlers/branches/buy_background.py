import tempfile

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, InputMediaPhoto, InputMediaDocument
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import os
from pathlib import Path

import config

from utils.utils import safe_call_answer, push_state
from utils.payments.payment_functional import create_payment, check_payment_status
from handlers.core.start import START_TEXT, get_main_menu_kb
from utils.image_processing import add_watermark, add_number_overlay


router = Router()


class UserBackgroundStates(StatesGroup):
    menu = State()
    browsing = State()
    waiting_payment = State()
    post_payment = State()


# ——————————————————————
# Меню покупки фонов
# ——————————————————————
@router.callback_query(F.data == "purchase_backgrounds")
async def purchase_backgrounds_menu(call: CallbackQuery, state: FSMContext):
    """Открывает меню покупки фонов."""
    await safe_call_answer(call)
    await state.clear()
    await choose_background(call, state)


# ——————————————————————
# Выбор фона
# ——————————————————————
@router.callback_query(UserBackgroundStates.menu, F.data == "backgrounds_browse")
async def choose_background(call: CallbackQuery, state: FSMContext):
    """Показывает список доступных фонов постранично. Сохраняет список файлов и папку в state."""
    await safe_call_answer(call)
    await push_state(state, UserBackgroundStates.menu)

    files = sorted(
        f for f in os.listdir(Path("resources/backgrounds"))
        if f.lower().endswith((".jpg", ".png"))
    )
    if not files:
        return await call.answer("❌ Нет доступных фонов", show_alert=True)

    await state.update_data(
        image_files=files,
        image_folder=str(Path("resources/backgrounds"))
    )
    loading = await call.message.answer("⚙️ Загружаем фоны…")
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    await show_backgrounds_album(call, state, loading, page=0)
    await state.set_state(UserBackgroundStates.browsing)


async def show_backgrounds_album(call: CallbackQuery, state: FSMContext, loading, page: int = 0):
    """
    Отображает альбом фоновых изображений на указанной странице.
    Добавляет водяной знак и нумерацию к каждому изображению.
    """
    await safe_call_answer(call)
    data = await state.get_data()

    files = data['image_files']
    total = len(files)
    max_page = (total - 1) // 10
    page = page % (max_page + 1)

    start = page * 10
    page_files = files[start:start + 10]

    with tempfile.TemporaryDirectory(dir=config.Output_Folder) as tmpdirname:
        tmp_path = Path(tmpdirname)
        media = []
        for idx, filename in enumerate(page_files, start=1):
            src = os.path.join(data['image_folder'], filename)
            wm_path = tmp_path / f"wm_{page}_{idx}_{filename}"
            num_path = tmp_path / f"num_{page}_{idx}_{filename}"

            add_watermark(str(src), str(wm_path))
            add_number_overlay(str(wm_path), str(num_path), number=idx)

            media.append(InputMediaPhoto(media=FSInputFile(str(num_path))))

        album_msgs = await loading.answer_media_group(media=media)
        album_ids = [msg.message_id for msg in album_msgs]

    select_buttons = [
        [InlineKeyboardButton(text=str(i), callback_data=f'select_bg_{start + i - 1}')
         for i in range(1, min(5, len(page_files)) + 1)],
        [InlineKeyboardButton(text=str(i), callback_data=f'select_bg_{start + i - 1}')
         for i in range(5, len(page_files) + 1)]
    ]
    nav_buttons = [
        InlineKeyboardButton(text='←', callback_data=f'prev_bg_{page - 1}'),
        InlineKeyboardButton(text=f'{page + 1}/{max_page + 1}', callback_data='noop'),
        InlineKeyboardButton(text='→', callback_data=f'next_bg_{page + 1}')
    ]
    back_button = [InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='bg_go_back')]
    keyboard = InlineKeyboardMarkup(inline_keyboard=select_buttons + [nav_buttons] + [back_button])

    keyboard_msg = await loading.answer(
        text="♡ Погрузитесь в коллекцию и выберите фон:",
        reply_markup=keyboard
    )
    try:
        await loading.delete()
    except TelegramBadRequest:
        pass

    await state.update_data(
        last_album_msgs=album_ids,
        last_keyboard_msg_id=keyboard_msg.message_id,
        image_page=page
    )


async def clear_album(call: CallbackQuery, state: FSMContext):
    """
    Удаляет предыдущие сообщения альбома и клавиатуру.
    Очищает экран перед показом новой страницы или возвратом.
    """
    data = await state.get_data()
    for msg_id in data.get('last_album_msgs', []):
        try:
            await call.bot.delete_message(call.message.chat.id, msg_id)
        except TelegramBadRequest:
            pass
    if data.get('last_keyboard_msg_id'):
        try:
            await call.bot.delete_message(call.message.chat.id, data['last_keyboard_msg_id'])
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith('next_bg_'))
async def next_bg_page(call: CallbackQuery, state: FSMContext):
    """Переходит на следующую страницу альбома фоновых изображений."""
    await safe_call_answer(call)
    await clear_album(call, state)
    loading = await call.message.answer("⚙️ Загружаем фоны…")
    await show_backgrounds_album(call, state, loading, page=int(call.data.split('_')[-1]))
    await state.set_state(UserBackgroundStates.browsing)


@router.callback_query(F.data.startswith('prev_bg_'))
async def prev_bg_page(call: CallbackQuery, state: FSMContext):
    """Переходит на предыдущую страницу альбома фоновых изображений."""
    await safe_call_answer(call)
    await clear_album(call, state)
    loading = await call.message.answer("⚙️ Загружаем фоны…")
    await show_backgrounds_album(call, state, loading, page=int(call.data.split('_')[-1]))
    await state.set_state(UserBackgroundStates.browsing)


# ——————————————————————
# Инициация оплаты
# ——————————————————————
@router.callback_query(UserBackgroundStates.browsing, F.data.startswith('select_bg_'))
async def select_background(call: CallbackQuery, state: FSMContext):
    """Инициирует платёж за выбранный фон. Генерирует ссылку на оплату и предлагает подтвердить."""
    await safe_call_answer(call)
    await clear_album(call, state)

    bg_index = int(call.data.split('_')[-1])
    user_id = call.from_user.id
    display_index = bg_index + 1
    payment_url, payment_id = await create_payment(
        user_id,
        50,
        f"Покупка фона #{display_index}"
    )
    await state.update_data(paying_bg=bg_index, payment_id=payment_id)
    await push_state(state, UserBackgroundStates.browsing)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить фон", url=payment_url)],
        [InlineKeyboardButton(text="📬 Получить фон", callback_data=f'backgrounds_check_{payment_id}_{bg_index}')],
        [InlineKeyboardButton(text="⏎ Назад", callback_data='bg_go_back')]
    ])
    await call.message.answer(
        text=(
            f"💰 Фон #{display_index}\n\n"
            "Оплатите фон — после подтверждения оплаты он сразу станет вам доступен."
        ),
        reply_markup=kb
    )
    await state.set_state(UserBackgroundStates.waiting_payment)


# ——————————————————————
# Проверка оплаты и отправка фона
# ——————————————————————
@router.callback_query(UserBackgroundStates.waiting_payment, F.data.startswith('backgrounds_check_'))
async def backgrounds_check(call: CallbackQuery, state: FSMContext):
    """
    Проверяет статус платежа.
    При успешном платеже отправляет выбранный фон пользователю.
    """
    payload = call.data[len("backgrounds_check_"):]
    payment_id, bg_index = payload.split("_")

    status = await check_payment_status(payment_id)
    if status != "succeeded":
        return await call.answer(text="❌ Платёж не подтверждён!", show_alert=True)

    await call.answer()

    data = await state.get_data()
    bg_file = os.path.join(
        data['image_folder'],
        data['image_files'][int(bg_index)]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏠 Главное меню", callback_data='bg_go_back_main')
    ]])
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    try:
        await call.message.edit_media(
            media=InputMediaDocument(media=FSInputFile(str(bg_file)), caption="✅ Оплата подтверждена!\n\n👆 Ваш фон."),
            reply_markup=kb
        )
    except TelegramBadRequest:
        await call.message.answer_document(
            document=FSInputFile(str(bg_file)),
            caption="✅ Оплата подтверждена!\n\n👆 Ваш фон.",
            reply_markup=kb
        )
    await push_state(state, UserBackgroundStates.post_payment)
    await state.clear()


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == 'bg_go_back')
async def bg_go_back(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает «Назад» в любом состоянии FSM:
    возвращает к списку фонов или в главное меню.
    """
    await safe_call_answer(call)
    current = await state.get_state()
    data = await state.get_data()

    if current == UserBackgroundStates.browsing.state:
        await clear_album(call, state)
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
        await state.clear()


    elif current == UserBackgroundStates.waiting_payment.state:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        loading = await call.message.answer("⚙️ Загружаем фоны…")
        await show_backgrounds_album(call, state, loading, page=data.get('image_page', 0))
        await state.set_state(UserBackgroundStates.browsing)

    else:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
        await state.clear()


@router.callback_query(F.data == 'bg_go_back_main')
async def bg_go_back_main(call: CallbackQuery, state: FSMContext):
    """
    Возвращает пользователя в главное меню из пост-оплаты.
    Очищает клавиатуру текущего сообщения.
    """
    await safe_call_answer(call)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await state.clear()
    await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_backgrounds(dp):
    """Регистрирует маршруты для работы с фонами."""
    dp.include_router(router)
