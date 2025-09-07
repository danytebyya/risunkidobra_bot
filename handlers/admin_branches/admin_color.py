import os
from pathlib import Path
from PIL import Image
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, FSInputFile
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.utils import safe_answer_callback
from utils.database.db import add_color, list_colors, delete_color
from handlers.core.admin import START_TEXT, get_admin_menu_kb
from utils.database.dropbox_storage import upload_file, delete_file


router = Router()


class AdminColorsStates(StatesGroup):
    menu = State()
    wait_hex = State()
    wait_name = State()
    confirm_add = State()
    browsing = State()


# ——————————————————————
# Меню управления цветами
# ——————————————————————
@router.callback_query(F.data == "admin_colors")
async def admin_colors_menu(call: CallbackQuery, state: FSMContext):
    """Отображает главное меню управления цветами (добавление или удаление)."""
    await safe_answer_callback(call, state)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="colors_add"),
         InlineKeyboardButton(text="- Удалить", callback_data="colors_delete")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_data_management")]
    ])
    if call.message:
        await call.message.edit_text("🎨 Управление цветами:", reply_markup=kb)  # type: ignore
    await state.set_state(AdminColorsStates.menu)


# ——————————————————————
# Добавление цвета
# ——————————————————————
@router.callback_query(AdminColorsStates.menu, F.data == "colors_add")
async def colors_add_start(call: CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя ввод hex-кода цвета."""
    await safe_answer_callback(call, state)
    if call.message:
        prompt = await call.message.edit_text(  # type: ignore
            "🔢 Введите hex-код цвета (формат: #RRGGBB).\n\n"
            "Цвета можно просмотреть на <a href=\"https://colorscheme.ru/html-colors.html\">сайте</a>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_colors")]
            ])
        )
        await state.update_data(prompt_message_id=prompt.message_id)  # type: ignore
    await state.set_state(AdminColorsStates.wait_hex)


@router.message(AdminColorsStates.wait_hex)
async def colors_receive_hex(message: Message, state: FSMContext):
    """Обрабатывает введенный hex-код, проверяет формат и запрашивает название цвета."""
    if not message.text:
        return await message.answer("❌ Неверный формат. Укажите цвет в виде #RRGGBB.")
    
    hex_code = message.text.strip()
    if not (hex_code.startswith('#') and len(hex_code) == 7):
        return await message.answer("❌ Неверный формат. Укажите цвет в виде #RRGGBB.")

    existing = await list_colors()
    if any(item['hex_code'].lower() == hex_code.lower() for item in existing):
        data = await state.get_data()
        if message.bot:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=data['prompt_message_id'],
                text=f"❌ Hex-код `{hex_code}` уже существует. Введите другой hex:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_colors")]
                ])
            )
        await message.delete()
        return

    await state.update_data(hex_code=hex_code)
    await message.delete()
    data = await state.get_data()
    chat_id = message.chat.id
    prompt_id = data['prompt_message_id']
    if message.bot:
        await message.bot.edit_message_text(
            "📤 Теперь введите название цвета:",
            chat_id=chat_id, message_id=prompt_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_colors")]
            ])
        )
    await state.set_state(AdminColorsStates.wait_name)


@router.message(AdminColorsStates.wait_name)
async def colors_receive_name(message: Message, state: FSMContext):
    """Обрабатывает введённое название цвета, показывает превью или ошибку дубликата."""
    if not message.text:
        return await message.answer("❌ Пожалуйста, введите название цвета.")
    
    name = message.text.strip()
    existing = await list_colors()
    if any(item['name'].lower() == name.lower() for item in existing):
        try:
            await message.delete()
        except TelegramBadRequest:
            pass

        data = await state.get_data()
        prompt_id = data.get('prompt_message_id')
        if prompt_id and message.bot:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_id,
                text=f'❌ Цвет "{name}" уже есть. Введите другое название:',
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back_admin_colors')]
                ])
            )
        return await state.set_state(AdminColorsStates.wait_name)
    await state.update_data(name=name)
    await message.delete()
    data = await state.get_data()
    tmp_dir = Path('/tmp/color_samples')
    tmp_dir.mkdir(exist_ok=True, parents=True)
    preview = tmp_dir / f"{name}.jpg"
    Image.new('RGB', (442,442), data['hex_code']).save(preview)
    media = InputMediaPhoto(media=FSInputFile(str(preview)),caption=f'Название: {name}')
    if message.bot:
        await message.bot.edit_message_media(
            media=media,
            chat_id=message.chat.id,
            message_id=data['prompt_message_id'],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text='🎨 Добавить', callback_data='colors_confirm_add'),
                    InlineKeyboardButton(text='⏎ Назад', callback_data='go_back_admin_colors')
                ]
            ])
        )
    await state.update_data(preview_tmp=str(preview))
    await state.set_state(AdminColorsStates.confirm_add)


@router.callback_query(AdminColorsStates.confirm_add, F.data == 'colors_confirm_add')
async def colors_confirm_add(call: CallbackQuery, state: FSMContext):
    """Сохраняет цвет в базе данных и сохраняет файл превью."""
    await safe_answer_callback(call, state)
    data = await state.get_data()
    dest = Path('resources/color_samples')
    dest.mkdir(exist_ok=True, parents=True)
    dest_path = dest / f"{data['name']}.jpg"
    os.replace(data['preview_tmp'], dest_path)
    # Синхронизация с Dropbox
    upload_file(str(dest_path), f"/resources/color_samples/{data['name']}.jpg")
    try:
        await add_color(data['name'], data['hex_code'], str(dest_path))
    except Exception as e:
        error_msg = str(e)
        if 'UNIQUE constraint' in error_msg:
            if call.message:
                await call.message.edit_text(  # type: ignore
                    '❌ Цвет с таким именем уже существует. Введите другое название:',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text='⏎ Назад',callback_data='go_back_admin_colors')]])
                )
                await state.update_data(prompt_message_id=call.message.message_id)  # type: ignore
            return await state.set_state(AdminColorsStates.wait_name)
        if call.message:
            await call.message.answer('❌ Ошибка при добавлении цвета.')
        return
    await state.clear()
    try:
        if call.message:
            await call.message.delete()  # type: ignore
    except TelegramBadRequest:
        pass
    if call.message:
        await call.message.answer(f"🎉 Цвет '{data['name']}' ({data['hex_code']}) успешно добавлен.")
        await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Удаление цвета
# ——————————————————————
@router.callback_query(AdminColorsStates.menu, F.data == "colors_delete")
async def colors_delete_start(call: CallbackQuery, state: FSMContext):
    """Начинает просмотр цветов для удаления, загружает список и показывает первый образец."""
    await safe_answer_callback(call, state)
    try: 
        if call.message:
            await call.message.delete()  # type: ignore
    except TelegramBadRequest: pass
    if call.message:
        loading = await call.message.answer("🎨 Подгружаем цвета...")
    colors = await list_colors()
    if not colors:
        if call.message and 'loading' in locals():
            await loading.delete()
        return await call.answer("❌ Нет цветов для удаления", show_alert=True)
    await state.update_data(index=0)
    await _show_color_for_delete(call, state)
    if call.message and 'loading' in locals():
        await loading.delete()
    await state.set_state(AdminColorsStates.browsing)


async def _show_color_for_delete(call: CallbackQuery, state: FSMContext, edit=False):
    """Внутренняя функция для отображения образца цвета при просмотре удаления."""
    data = await state.get_data()
    colors = await list_colors()
    idx = data['index'] % len(colors)
    item = colors[idx]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='←', callback_data='colors_prev'),
         InlineKeyboardButton(text=f"{idx+1}/{len(colors)}", callback_data='noop'),
         InlineKeyboardButton(text='→', callback_data='colors_next')],
        [InlineKeyboardButton(text='🗑️ Удалить', callback_data=f"colors_do_delete_{item['id']}" )],
        [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back_admin_colors')]
    ])
    media = InputMediaPhoto(media=FSInputFile(item['sample_path']), caption=f"Цвет: {item['name']} {item['hex_code']}")
    try:
        if edit and call.message:
            await call.message.edit_media(media=media, reply_markup=kb)  # type: ignore
        elif call.message:
            await call.message.answer_photo(photo=FSInputFile(item['sample_path']), caption=f"Цвет: {item['name']} {item['hex_code']}", reply_markup=kb)
    except TelegramBadRequest:
        if call.message:
            await call.message.answer_photo(photo=FSInputFile(item['sample_path']), caption=f"Цвет: {item['name']} {item['hex_code']}", reply_markup=kb)
    await safe_answer_callback(call, state)


@router.callback_query(F.data == 'colors_prev')
async def colors_prev(call: CallbackQuery, state: FSMContext):
    """Переходит к предыдущему цвету в режиме удаления."""
    data = await state.get_data()
    idx = (data['index'] - 1) % len(await list_colors())
    await state.update_data(index=idx)
    await _show_color_for_delete(call, state, edit=True)


@router.callback_query(F.data == 'colors_next')
async def colors_next(call: CallbackQuery, state: FSMContext):
    """Переходит к следующему цвету в режиме удаления."""
    data = await state.get_data()
    idx = (data['index'] + 1) % len(await list_colors())
    await state.update_data(index=idx)
    await _show_color_for_delete(call, state, edit=True)


@router.callback_query(F.data.startswith('colors_do_delete_'))
async def colors_do_delete(call: CallbackQuery, state: FSMContext):
    """Удаляет выбранный цвет из базы и файловой системы."""
    await safe_answer_callback(call, state)
    if not call.data:
        return
    
    color_id = int(call.data.split('_')[-1])
    all_colors = await list_colors()
    pos = next((i + 1 for i, c in enumerate(all_colors) if c['id'] == color_id), None)
    pos_display = f"{pos}" if pos is not None else f"{color_id}"

    paths = await delete_color(color_id)
    if not paths:
        paths_list = []
    elif isinstance(paths, str):
        paths_list = [paths]
    else:
        paths_list = list(paths)

    project_root = Path(__file__).resolve().parent.parent.parent
    deleted, failed = [], []
    for rel in paths_list:
        p = Path(rel)
        if not p.is_absolute():
            p = project_root / rel
        try:
            if p.is_file():
                p.unlink()
                # Синхронизация с Dropbox
                dropbox_path = f"/resources/color_samples/{p.name}"
                if not dropbox_path.startswith("/"):
                    dropbox_path = "/" + dropbox_path
                delete_file(dropbox_path)
                deleted.append(str(p))
            else:
                failed.append(str(p))
        except (OSError, PermissionError):
            failed.append(str(p))

    await state.clear()
    try:
        if call.message:
            await call.message.delete()  # type: ignore
    except TelegramBadRequest:
        pass
    if call.message:
        if deleted:
            await call.message.answer(f"🗑️ Цвет #{pos_display} успешно удалён.")
        else:
            await call.message.answer(f"❌ Не удалось удалить изображения цвета #{color_id}.")
        await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_admin_colors")
async def go_back_admin_colors(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает навигацию "назад" в различных состояниях FSM.
    Восстанавливает предыдущие шаги или возвращает в меню.
    """
    await safe_answer_callback(call, state)
    current = await state.get_state()

    if current == AdminColorsStates.confirm_add.state:
        try:
            if call.message:
                await call.message.delete()  # type: ignore
        except TelegramBadRequest:
            pass
        if call.message:
            prompt = await call.message.answer(
                "📤 Теперь введите название цвета:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_colors")]
                ])
            )
            await state.update_data(prompt_message_id=prompt.message_id)
        await state.set_state(AdminColorsStates.wait_name)
        return

    if current == AdminColorsStates.wait_name.state:
        if call.message:
            await call.message.edit_text(  # type: ignore
                "🔢 Введите hex-код цвета (формат: #RRGGBB).\n\n"
                "Цвета можно просмотреть на <a href=\"https://colorscheme.ru/html-colors.html\">сайте</a>.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_colors")]
                ])
            )
        await state.set_state(AdminColorsStates.wait_hex)
        return

    if current in (
        AdminColorsStates.wait_hex.state,
        AdminColorsStates.menu.state,
        AdminColorsStates.browsing.state
    ):
        try: 
            if call.message:
                await call.message.delete()  # type: ignore
        except TelegramBadRequest: pass
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Добавить", callback_data="colors_add"),
             InlineKeyboardButton(text="- Удалить", callback_data="colors_delete")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        if call.message:
            await call.message.answer("🎨 Управление цветами:", reply_markup=kb)
        await state.set_state(AdminColorsStates.menu)
        return

    await state.clear()
    try: 
        if call.message:
            await call.message.delete()  # type: ignore
    except TelegramBadRequest: pass
    if call.message:
        await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_colors(dp):
    dp.include_router(router)
    