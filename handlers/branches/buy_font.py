from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, InputMediaDocument
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InputMediaPhoto

from utils.utils import safe_answer_callback
from utils.database.db import list_fonts
from handlers.core.start import START_TEXT, get_main_menu_kb
from utils.payments.payment_functional import create_payment, check_payment_status
from config import logger


router = Router()


class UserFontsStates(StatesGroup):
    menu = State()
    browsing = State()
    waiting_payment = State()
    post_payment = State()


# ——————————————————————
# Инициация оплаты
# ——————————————————————
@router.callback_query(F.data == "purchase_fonts")
async def purchase_fonts_menu(call: CallbackQuery, state: FSMContext):
    """Открывает меню покупки шрифтов."""
    await safe_answer_callback(call, state)
    user_id = call.from_user.id
    logger.info(f"Пользователь {user_id} переключился на вкладку «Купить шрифт»")
    await state.clear()
    await fonts_browse(call, state)


# ——————————————————————
# Просмотр шрифта
# ——————————————————————
@router.callback_query(UserFontsStates.menu, F.data == "fonts_browse")
async def fonts_browse(call: CallbackQuery, state: FSMContext):
    """
    Загружает список доступных шрифтов и показывает первый превью.
    Сохраняет список в state.
    """
    await safe_answer_callback(call, state)
    loading = await call.message.answer("⚙️ Загружаем шрифты…")
    fonts = await list_fonts()
    if not fonts:
        return await call.answer("❌ Пока нет доступных шрифтов", show_alert=True)

    await state.update_data(font_index=0, fonts=fonts)
    await _show_font_for_purchase(call, state, edit=True)
    await loading.delete()
    await state.set_state(UserFontsStates.browsing)


async def _show_font_for_purchase(call: CallbackQuery, state: FSMContext, edit: bool):
    """Отображает превью шрифта для покупки, редактируя сообщение при edit=True или отправляя новое при edit=False."""
    data = await state.get_data()
    font = data['fonts'][data['font_index']]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="←", callback_data="_fonts_prev"),
         InlineKeyboardButton(text=f"{data['font_index']+1}/{len(data['fonts'])}", callback_data="noop"),
         InlineKeyboardButton(text="→", callback_data="_fonts_next")],
        [InlineKeyboardButton(text="💳 Приобрести", callback_data=f"fonts_pay_{font['id']}")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="go_back_user_font")]
    ])
    media_path = font['sample_path']

    if edit:
        try:
            await call.message.edit_media(
                InputMediaPhoto(media=FSInputFile(media_path), caption=f"Шрифт: {font['name']}"),
                reply_markup=kb
            )
            return
        except TelegramBadRequest:
            pass
    try:
        await call.message.answer_photo(
            photo=FSInputFile(media_path),
            caption=f"Шрифт: {font['name']}",
            reply_markup=kb
        )
    except TelegramBadRequest:
        await call.message.answer_document(
            document=FSInputFile(media_path),
            caption=f"Шрифт: {font['name']}",
            reply_markup=kb
        )


@router.callback_query(F.data == '_fonts_prev')
async def fonts_prev(call: CallbackQuery, state: FSMContext):
    """Показывает предыдущий шрифт в режиме просмотра."""
    data = await state.get_data()
    idx = (data['font_index'] - 1) % len(data['fonts'])
    await state.update_data(font_index=idx)
    await _show_font_for_purchase(call, state, edit=True)


@router.callback_query(F.data == '_fonts_next')
async def fonts_next(call: CallbackQuery, state: FSMContext):
    """Показывает следующий шрифт в режиме просмотра."""
    data = await state.get_data()
    idx = (data['font_index'] + 1) % len(data['fonts'])
    await state.update_data(font_index=idx)
    await _show_font_for_purchase(call, state, edit=True)


# ——————————————————————
# Инициация оплаты
# ——————————————————————
@router.callback_query(UserFontsStates.browsing, F.data.startswith('fonts_pay_'))
async def fonts_pay(call: CallbackQuery, state: FSMContext):
    """
    Инициирует платёж за выбранный шрифт.
    Отправляет ссылку на оплату и кнопку для проверки.
    """
    await safe_answer_callback(call, state)
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass

    font_id = int(call.data.split('_')[-1])
    user_id = call.from_user.id

    fonts = await list_fonts()
    font = next((f for f in fonts if f['id'] == font_id), None)
    if not font:
        await call.message.answer("❗️ Шрифт не найден.")
        logger.warning(f"Пользователь {user_id} попытался купить несуществующий шрифт {font_id}")
        return

    font_name = font['name']

    payment_url, payment_id = await create_payment(
        user_id,
        1000,
        f"Покупка шрифта #{font_id}"
    )
    await state.update_data(paying_font=font_id, payment_id=payment_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить шрифт", url=payment_url)],
        [InlineKeyboardButton(text="📬 Получить шрифт", callback_data=f"fonts_check_{payment_id}_{font_id}")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_user_font")],
    ])

    # Показываем фото выбранного шрифта перед кнопками оплаты
    try:
        await call.message.answer_photo(
            photo=FSInputFile(font['sample_path']),
            caption=f"Вы выбрали шрифт: {font_name}",
            reply_markup=kb
        )
    except TelegramBadRequest:
        await call.message.answer(
            text=f"Вы выбрали шрифт: {font_name}",
            reply_markup=kb
        )
    await state.set_state(UserFontsStates.waiting_payment)


# ——————————————————————
# Проверка оплаты и выдача шрифта
# ——————————————————————
@router.callback_query(UserFontsStates.waiting_payment, F.data.startswith('fonts_check_'))
async def fonts_check(call: CallbackQuery, state: FSMContext):
    """
    Проверяет статус платежа.
    При успехе отправляет файл шрифта, иначе уведомляет об ошибке.
    """
    payload = call.data[len("fonts_check_"):]
    payment_id, font_id = payload.split("_", 1)
    font_id = int(font_id)
    user_id = call.from_user.id

    status = await check_payment_status(payment_id)
    if status != "succeeded":
        await call.answer(text="❌ Платёж не подтверждён!", show_alert=True)
        logger.warning(
            f"Платёж {payment_id} пользователя {user_id} для шрифта {font_id} не подтверждён "
            f"(статус={status})"
        )
        return

    fonts = await list_fonts()
    font = next((f for f in fonts if f['id'] == int(font_id)), None)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="user_back_to_main")
    ]])

    if font:
        media = InputMediaDocument(
            media=FSInputFile(font['font_path']),
            caption="✅ Оплата подтверждена!\n\n👆 Ваш шрифт."
        )
        try:
            await call.message.edit_media(media=media, reply_markup=kb)
        except TelegramBadRequest:
            await call.message.answer_document(
                FSInputFile(font['font_path']),
                caption="✅ Оплата подтверждена!\n\n👆 Ваш шрифт.",
                reply_markup=kb
            )

            logger.info(
                f"Пользователь {user_id} получил шрифт «{font['name']}» "
                f"(font_id={font_id}, payment_id={payment_id})"
            )
    else:
        await call.message.edit_caption(
            caption="❌ Шрифт не найден, обратитесь в поддержку - /help.",
            reply_markup=kb
        )
        logger.error(
            f"После оплаты {payment_id} шрифт {font_id} не найден в базе для пользователя {user_id}"
        )

    await state.clear()


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == 'go_back_user_font')
async def go_back_fonts(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя на предыдущий шаг при работе со шрифтами или в главное меню."""
    await safe_answer_callback(call, state)
    current = await state.get_state()

    if current in {UserFontsStates.browsing.state, UserFontsStates.menu.state}:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
        await state.clear()
    elif current == UserFontsStates.waiting_payment.state:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        loading = await call.message.answer("⚙️ Загружаем шрифты…")
        fonts = await list_fonts()
        if not fonts:
            await loading.edit_text("❌ Пока нет доступных шрифтов")
            return
        await state.update_data(font_index=0, fonts=fonts)
        await _show_font_for_purchase(call, state, edit=False)
        await loading.delete()
        await state.set_state(UserFontsStates.browsing)
        await state.set_state(UserFontsStates.browsing)
    else:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
        await state.clear()


@router.callback_query(F.data == "user_back_to_main")
async def user_back_to_main(call: CallbackQuery, state: FSMContext):
    """
    Возвращает пользователя в главное меню после покупки.
    Очищает текущее состояние и клавиатуру.
    """
    await safe_answer_callback(call, state)
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_user_fonts(dp):
    """Регистрирует маршруты для пользовательской покупки шрифтов."""
    dp.include_router(router)