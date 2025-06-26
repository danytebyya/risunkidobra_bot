import os

from pathlib import Path
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, FSInputFile
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.utils import safe_call_answer
from utils.database.db import add_font, list_fonts, delete_font
from handlers.core.admin import START_TEXT, get_admin_menu_kb
from utils.image_processing import generate_font_sample

router = Router()


class AdminFontsStates(StatesGroup):
    menu = State()
    wait_upload = State()
    confirm_upload = State()
    browsing = State()
    adjust_size = State()
    edit_text = State()


# ——————————————————————
# Меню управления шрифтами
# ——————————————————————
@router.callback_query(F.data == "admin_fonts")
async def admin_fonts_menu(call: CallbackQuery, state: FSMContext):
    """Отображает главное меню управления шрифтами (добавить или удалить)."""
    await safe_call_answer(call)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_add"),
         InlineKeyboardButton(text="- Удалить", callback_data="fonts_delete")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
    ])
    await call.message.edit_text("⚙️ Управление шрифтами:", reply_markup=kb)
    await state.set_state(AdminFontsStates.menu)


# ——————————————————————
# Добавление шрифта
# ——————————————————————
@router.callback_query(AdminFontsStates.menu, F.data == "fonts_add")
async def fonts_add_start(call: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя файл шрифта в формате .ttf."""
    await safe_call_answer(call)
    await call.message.edit_text(
        "📤 Пришлите файл шрифта .ttf",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")]
        ])
    )
    await state.set_state(AdminFontsStates.wait_upload)


@router.message(AdminFontsStates.wait_upload, F.document)
async def fonts_receive_file(message: Message, state: FSMContext):
    """Принимает .ttf файл, генерирует и отображает пример шрифта."""
    try:
        await message.bot.delete_message(message.chat.id, message.message_id - 1)
    except TelegramBadRequest:
        pass
    doc = message.document
    if not doc.file_name.lower().endswith('.ttf'):
        return await message.answer("❌ Пожалуйста, пришлите .ttf файл.")

    fonts = await list_fonts()
    next_id = fonts[-1]['id'] + 1 if fonts else 1
    await state.update_data(file_id=doc.file_id, next_id=next_id)

    tmp_dir = Path('/tmp/font_samples'); tmp_dir.mkdir(exist_ok=True, parents=True)
    sample_tmp = tmp_dir / f"{next_id}.jpg"
    tmp_font = Path(f"/tmp/font_{next_id}.ttf")
    file = await message.bot.get_file(doc.file_id)
    await message.bot.download_file(file.file_path, destination=tmp_font)

    size = 280
    text = f"пример {next_id}-го рукописного шрифта для ваших пожеланий"
    await generate_font_sample(tmp_font, sample_tmp, size, text)
    await state.update_data(
        font_tmp=str(tmp_font),
        sample_tmp=str(sample_tmp),
        font_size=size,
        font_text=text,
        next_id=next_id,
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_confirm_add")],
        [InlineKeyboardButton(text="Увеличить текст", callback_data="font_increase"),
        InlineKeyboardButton(text="Уменьшить текст", callback_data="font_decrease")],
        [InlineKeyboardButton(text="Изменить текст", callback_data="font_change_text")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")],
    ])
    await message.answer_photo(
        FSInputFile(str(sample_tmp)),
        caption="Проверьте пример шрифта",
        reply_markup=kb
    )
    await state.set_state(AdminFontsStates.confirm_upload)


@router.callback_query(F.data == "font_increase", AdminFontsStates.confirm_upload)
async def font_increase(call: CallbackQuery, state: FSMContext):
    """Увеличивает размер текста в примере шрифта."""
    await safe_call_answer(call)
    data = await state.get_data()

    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass

    notify = await call.message.answer("⏳ Изменяем размер шрифта...")

    size = data["font_size"] + 20
    text = data["font_text"]
    tmp_font = Path(data["font_tmp"])
    sample_tmp = Path(data["sample_tmp"])
    await generate_font_sample(tmp_font, sample_tmp, size, text)
    await state.update_data(font_size=size)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_confirm_add")],
        [InlineKeyboardButton(text="Увеличить текст", callback_data="font_increase"),
         InlineKeyboardButton(text="Уменьшить текст", callback_data="font_decrease")],
        [InlineKeyboardButton(text="Изменить текст", callback_data="font_change_text")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")],
    ])
    await call.message.answer_photo(
        FSInputFile(str(sample_tmp)),
        caption="Проверьте пример шрифта",
        reply_markup=kb
    )

    await notify.delete()


@router.callback_query(F.data == "font_decrease", AdminFontsStates.confirm_upload)
async def font_decrease(call: CallbackQuery, state: FSMContext):
    """Уменьшает размер текста в примере шрифта."""
    await safe_call_answer(call)
    data = await state.get_data()

    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass

    notify = await call.message.answer("⏳ Изменяем размер шрифта...")

    size = max(20, data["font_size"] - 20)
    text = data["font_text"]
    tmp_font = Path(data["font_tmp"])
    sample_tmp = Path(data["sample_tmp"])
    await generate_font_sample(tmp_font, sample_tmp, size, text)
    await state.update_data(font_size=size)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_confirm_add")],
        [InlineKeyboardButton(text="Увеличить текст", callback_data="font_increase"),
         InlineKeyboardButton(text="Уменьшить текст", callback_data="font_decrease")],
        [InlineKeyboardButton(text="Изменить текст", callback_data="font_change_text")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")],
    ])

    await call.message.answer_photo(
        FSInputFile(str(sample_tmp)),
        caption="Проверьте пример шрифта",
        reply_markup=kb
    )

    await notify.delete()


@router.callback_query(F.data == "font_change_text", AdminFontsStates.confirm_upload)
async def font_change_text(call: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя новый текст для примера шрифта."""
    await safe_call_answer(call)
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass

    prompt = await call.message.answer(
        text="🖋 Введите новый текст для образца шрифта:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")]]
        )
    )
    await state.update_data(prompt_msg_id=prompt.message_id)
    await state.set_state(AdminFontsStates.edit_text)


@router.message(AdminFontsStates.edit_text)
async def font_edit_text(message: Message, state: FSMContext):
    """Обновляет пример шрифта с новым введённым текстом."""
    new_text = message.text
    data = await state.get_data()
    size = data["font_size"]
    tmp_font = Path(data["font_tmp"])
    sample_tmp = Path(data["sample_tmp"])

    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    prompt_id = data.get("prompt_msg_id")
    if prompt_id:
        try:
            await message.bot.delete_message(message.chat.id, prompt_id)
        except TelegramBadRequest:
            pass

    notify = await message.answer("⏳ Изменяем образец шрифта…")

    await generate_font_sample(tmp_font, sample_tmp, size, new_text)
    await state.update_data(font_text=new_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_confirm_add")],
        [InlineKeyboardButton(text="Увеличить текст", callback_data="font_increase"),
         InlineKeyboardButton(text="Уменьшить текст", callback_data="font_decrease")],
        [InlineKeyboardButton(text="Изменить текст", callback_data="font_change_text")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")],
    ])
    await message.answer_photo(FSInputFile(str(sample_tmp)),
                               caption="Новый пример текста", reply_markup=kb)
    await notify.delete()
    await state.set_state(AdminFontsStates.confirm_upload)


@router.callback_query(AdminFontsStates.confirm_upload, F.data == "fonts_confirm_add")
async def fonts_confirm_add(call: CallbackQuery, state: FSMContext):
    """Сохраняет шрифт и пример в папках ресурсов и добавляет запись в БД."""
    await safe_call_answer(call)
    data = await state.get_data()
    next_id = data['next_id']
    font_tmp = Path(data['font_tmp'])
    sample_tmp = Path(data['sample_tmp'])

    dest_fonts = Path('resources/fonts'); dest_fonts.mkdir(exist_ok=True, parents=True)
    dest_samples = Path('resources/font_samples'); dest_samples.mkdir(exist_ok=True, parents=True)

    font_dest = dest_fonts / f"{next_id}.ttf"
    sample_dest = dest_samples / f"{next_id}.jpg"
    os.replace(font_tmp, font_dest)
    os.replace(sample_tmp, sample_dest)

    await add_font(str(next_id), str(font_dest), str(sample_dest))

    await state.clear()
    await call.message.delete()
    await call.message.answer(f"🎉 Шрифт #{next_id} успешно добавлен.")
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Удаление шрифта
# ——————————————————————
@router.callback_query(AdminFontsStates.menu, F.data == "fonts_delete")
async def fonts_delete_start(call: CallbackQuery, state: FSMContext):
    """Инициализирует просмотр шрифтов и показывает первый образец для удаления."""
    await safe_call_answer(call)
    try: await call.message.delete()
    except TelegramBadRequest: pass
    loading = await call.message.answer("⚙️ Подгружаем шрифты...")

    fonts = await list_fonts()
    if not fonts:
        await loading.delete()
        return await call.answer("❌ Нет шрифтов для удаления", show_alert=True)

    await state.update_data(font_index=0)
    await _show_font_for_delete(call, state)

    try: await loading.delete()
    except TelegramBadRequest: pass
    await state.set_state(AdminFontsStates.browsing)


async def _show_font_for_delete(call: CallbackQuery, state: FSMContext, edit=False):
    """Внутренняя функция: показывает образец шрифта при удалении."""
    data = await state.get_data()
    fonts = await list_fonts()
    idx = data['font_index'] % len(fonts)
    font = fonts[idx]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='←', callback_data='fonts_prev'),
         InlineKeyboardButton(text=f"{idx+1}/{len(fonts)}", callback_data='noop'),
         InlineKeyboardButton(text='→', callback_data='fonts_next')],
        [InlineKeyboardButton(text='🗑️ Удалить', callback_data=f"fonts_do_delete_{font['id']}")],
        [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back_admin_fonts')]
    ])
    media = InputMediaPhoto(media=FSInputFile(font['sample_path']), caption=f"Шрифт: {font['name']}")
    try:
        if edit:
            await call.message.edit_media(media=media, reply_markup=kb)
        else:
            await call.message.answer_photo(photo=FSInputFile(font['sample_path']),
                                            caption=f"Шрифт: {font['name']}", reply_markup=kb)
    except TelegramBadRequest:
        await call.message.answer_photo(photo=FSInputFile(font['sample_path']),
                                        caption=f"Шрифт: {font['name']}", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == 'fonts_prev')
async def fonts_prev(call: CallbackQuery, state: FSMContext):
    """Показывает предыдущий шрифт в списке удаления."""
    data = await state.get_data()
    fonts = await list_fonts()
    idx = (data.get('font_index', 0) - 1) % len(fonts)
    await state.update_data(font_index=idx)
    await _show_font_for_delete(call, state, edit=True)


@router.callback_query(F.data == 'fonts_next')
async def fonts_next(call: CallbackQuery, state: FSMContext):
    """Показывает следующий шрифт в списке удаления."""
    data = await state.get_data()
    fonts = await list_fonts()
    idx = (data.get('font_index', 0) + 1) % len(fonts)
    await state.update_data(font_index=idx)
    await _show_font_for_delete(call, state, edit=True)


@router.callback_query(F.data.startswith('fonts_do_delete_'))
async def fonts_do_delete(call: CallbackQuery, state: FSMContext):
    """Подтверждает удаление шрифта из БД и файловой системы."""
    await safe_call_answer(call)
    font_id = int(call.data.split('_')[-1])

    fonts = await list_fonts()
    pos = next((i + 1 for i, f in enumerate(fonts) if f['id'] == font_id), None)
    pos_display = pos if pos is not None else font_id

    paths = await delete_font(font_id)
    if paths:
        for p in paths:
            try:
                os.remove(p)
            except (OSError, PermissionError):
                pass
        msg = f"🗑️ Шрифт #{pos_display} удалён"
    else:
        msg = "❌ Ошибка при удалении шрифта"
    await state.clear()
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    await call.message.answer(msg)
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_admin_fonts")
async def go_back_admin_fonts(call: CallbackQuery, state: FSMContext):
    """Обрабатывает навигацию «Назад» в разных состояниях FSM."""
    await safe_call_answer(call)
    current = await state.get_state()

    if current == AdminFontsStates.confirm_upload.state:
        try: await call.message.delete()
        except TelegramBadRequest: pass
        await call.message.answer(
            "📤 Пришлите файл шрифта .ttf",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")]]
            )
        )
        await state.set_state(AdminFontsStates.wait_upload)
        return

    if current in (AdminFontsStates.wait_upload.state, AdminFontsStates.menu.state):
        try: await call.message.delete()
        except TelegramBadRequest: pass
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_add"),
             InlineKeyboardButton(text="- Удалить", callback_data="fonts_delete")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        await call.message.answer("⚙️ Управление шрифтами:", reply_markup=kb)
        await state.set_state(AdminFontsStates.menu)
        return

    if current == AdminFontsStates.browsing.state:
        try: await call.message.delete()
        except TelegramBadRequest: pass
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_add"),
             InlineKeyboardButton(text="- Удалить", callback_data="fonts_delete")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        await call.message.answer("⚙️ Управление шрифтами:", reply_markup=kb)
        await state.set_state(AdminFontsStates.menu)
        return

    if current == AdminFontsStates.edit_text.state:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

        data = await state.get_data()
        sample_tmp = Path(data["sample_tmp"])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="fonts_confirm_add")],
            [InlineKeyboardButton(text="Увеличить текст", callback_data="font_increase"),
            InlineKeyboardButton(text="Уменьшить текст", callback_data="font_decrease")],
            [InlineKeyboardButton(text="Изменить текст", callback_data="font_change_text")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_fonts")],
        ])
        await call.message.answer_photo(
            FSInputFile(str(sample_tmp)),
            caption = "Проверьте пример шрифта",
            reply_markup = kb
        )
        await state.set_state(AdminFontsStates.confirm_upload)

        return

    await state.clear()
    try: await call.message.delete()
    except TelegramBadRequest: pass
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_fonts(dp):
    dp.include_router(router)
