import os
import re
import tempfile

from pathlib import Path
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.utils import safe_call_answer
from utils.image_processing import add_number_overlay
from handlers.core.admin import START_TEXT, get_admin_menu_kb


BACKGROUNDS_FOLDER = os.path.join("resources", "backgrounds")
OUTPUT_FOLDER = os.path.join("resources", "output")


router = Router()


class AdminBgStates(StatesGroup):
    browsing = State()
    wait_numbers = State()
    confirm_delete = State()
    wait_upload = State()


# ——————————————————————
# Меню управления фонами
# ——————————————————————
@router.callback_query(F.data == "admin_backgrounds")
async def admin_backgrounds_menu(call: CallbackQuery, state: FSMContext):
    """Меню управления фонами: удалить или добавить фон."""
    await safe_call_answer(call)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+ Добавить фон", callback_data="bg_add"),
            InlineKeyboardButton(text="- Удалить фон", callback_data="bg_delete")
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
    ])
    await call.message.edit_text(text="⚙️ Управление фонами:", reply_markup=kb)
    await state.set_state(AdminBgStates.browsing)


# ——————————————————————
# Добавление фоновых изображений
# ——————————————————————
@router.callback_query(AdminBgStates.browsing, F.data == "bg_add")
async def admin_bg_add(call: CallbackQuery, state: FSMContext):
    """Запуск процесса добавления фоновых изображений."""
    await safe_call_answer(call)
    await call.message.delete()

    folder = BACKGROUNDS_FOLDER
    nums = [int(m.group(1)) for f in os.listdir(folder) if (m := re.match(r"^(\d+)", f))]
    next_idx = max(nums) + 1 if nums else 1
    await state.update_data(folder=folder, next_index=next_idx, pending_files=[])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Добавить", callback_data="bg_done_upload")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_bg")]
    ])
    await call.message.answer(
        text="Пришлите фоны (одно или несколько изображений). Затем нажмите «Добавить».",
        reply_markup=kb
    )
    await state.set_state(AdminBgStates.wait_upload)


@router.message(AdminBgStates.wait_upload)
async def admin_bg_collect(message: Message, state: FSMContext):
    """Сбор загруженных пользователем изображений перед добавлением."""
    data = await state.get_data()
    pending = data.get('pending_files', [])

    if message.photo:
        pending.append({'type': 'photo', 'file_id': message.photo[-1].file_id})
    elif message.document and message.document.mime_type.startswith('image/'):
        pending.append({'type': 'document', 'file_id': message.document.file_id, 'file_name': message.document.file_name})
    else:
        return await message.answer("❌ Пришлите изображение или документ с изображением.")

    await state.update_data(pending_files=pending)


@router.callback_query(AdminBgStates.wait_upload, F.data == "bg_done_upload")
async def admin_bg_finish_upload(call: CallbackQuery, state: FSMContext):
    """Сохраняет загруженные изображения в папку и завершает процесс."""
    await safe_call_answer(call)
    data = await state.get_data()
    folder = data['folder']
    idx = data['next_index']
    pending = data.get('pending_files', [])

    for item in pending:
        tg_file = await call.bot.get_file(item['file_id'])
        ext = '.jpg' if item['type'] == 'photo' else os.path.splitext(item['file_name'])[1] or '.png'
        dest = os.path.join(folder, f"{idx}{ext}")
        await call.bot.download_file(tg_file.file_path, destination=dest)
        idx += 1

    count = len(pending)
    await state.clear()
    await call.message.delete()
    if count:
        await call.message.answer(f"🎉 Успешно добавлено {count} фонов.")
    else:
        await call.message.answer("❌ Файлы не были загружены.")
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Удаление фоновых изображений
# ——————————————————————
@router.callback_query(AdminBgStates.browsing, F.data == "bg_delete")
async def admin_bg_delete(call: CallbackQuery, state: FSMContext):
    """Загружает все фоны и показывает их постранично для удаления."""
    await safe_call_answer(call)
    await call.message.delete()

    folder = BACKGROUNDS_FOLDER
    files = []
    for fname in os.listdir(folder):
        if fname.lower().endswith((".jpg", ".png")):
            m = re.match(r"^(\d+)", os.path.splitext(fname)[0])
            if m:
                files.append((int(m.group(1)), fname))
    files.sort(key=lambda x: x[0])
    filenames = [f for _, f in files]
    next_idx = files[-1][0] + 1 if files else 1

    await state.update_data(folder=folder, files=filenames, next_index=next_idx)
    await _show_bg_images(call, state, page=0)


async def _show_bg_images(call: CallbackQuery, state: FSMContext, page: int, loading_msg=None):
    """Постраничный вывод фоновых изображений для удаления."""
    data = await state.get_data()
    files = data['files']
    folder = data['folder']
    total = len(files)
    max_page = (total - 1) // 10 if total else 0
    page = page % (max_page + 1 if total else 1)
    start, end = page * 10, min((page + 1) * 10, total)
    await state.update_data(current_page=page)

    for mid in data.get('prev_msgs', []):
        try:
            await call.bot.delete_message(call.message.chat.id, mid)
        except TelegramBadRequest:
            pass
    if loading_msg:
        await call.bot.delete_message(call.message.chat.id, loading_msg.message_id)

    loading = await call.message.answer("⚙️ Загружаем фоны...")

    with tempfile.TemporaryDirectory(dir=OUTPUT_FOLDER) as tmpdirname:
        media = []
        tmp_path = Path(tmpdirname)
        for idx, fname in enumerate(files[start:end], start):
            src = os.path.join(folder, fname)
            tmp_file = tmp_path / f"bg_{idx}_{fname}"
            add_number_overlay(str(src), str(tmp_file), number=idx + 1)
            media.append(InputMediaPhoto(media=FSInputFile(str(tmp_file))))

        msgs = await call.message.answer_media_group(media)

    await call.bot.delete_message(call.message.chat.id, loading.message_id)

    mids = [m.message_id for m in msgs]
    nav = [
        InlineKeyboardButton(text="←", callback_data=f"bg_prev_{page - 1}"),
        InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data="noop"),
        InlineKeyboardButton(text="→", callback_data=f"bg_next_{page + 1}")
    ]
    keyboard = [
        nav,
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_bg")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    prompt = await call.message.answer(
        text="🔢 Введите номера фонов для удаления через запятую:", reply_markup=kb
    )
    mids.append(prompt.message_id)
    await state.update_data(prev_msgs=mids)
    await state.set_state(AdminBgStates.wait_numbers)


@router.callback_query(F.data.startswith("bg_prev_") | F.data.startswith("bg_next_"))
async def admin_bg_page(call: CallbackQuery, state: FSMContext):
    """Обработка перехода между страницами фоновых изображений."""
    await safe_call_answer(call)
    await safe_call_answer(call)
    page = int(call.data.rsplit("_", 1)[-1])
    await _show_bg_images(call, state, page)


@router.message(AdminBgStates.wait_numbers)
async def handle_bg_delete_numbers(message: Message, state: FSMContext):
    """Обработка введенных пользователем номеров фонов для удаления."""
    data = await state.get_data()
    await message.delete()
    for mid in data.get('prev_msgs', []):
        try:
            await message.bot.delete_message(message.chat.id, mid)
        except TelegramBadRequest:
            pass

    nums = [n.strip() for n in (message.text or '').split(',') if n.strip().isdigit()]
    if not nums:
        return await message.answer(f"❌ Введите числа от 1 до {len(data['files'])}")

    indices = sorted({int(n) - 1 for n in nums})
    if not all(0 <= i < len(data['files']) for i in indices):
        return await message.answer(f"❌ Номера от 1 до {len(data['files'])}")

    await state.update_data(delete_indices=indices)
    media = [
        InputMediaPhoto(media=FSInputFile(str(os.path.join(data['folder'], data['files'][i]))))
        for i in indices
    ]
    msgs = await message.answer_media_group(media)
    prev_ids = [m.message_id for m in msgs]

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="bg_confirm_delete"),
        InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_bg")
    ]])
    prompt = await message.answer(text="Подтвердите удаление выбранных фонов:", reply_markup=kb)
    prev_ids.append(prompt.message_id)
    await state.update_data(prev_msgs=prev_ids)
    await state.set_state(AdminBgStates.confirm_delete)


@router.callback_query(AdminBgStates.confirm_delete, F.data == "bg_confirm_delete")
async def admin_bg_do_delete(call: CallbackQuery, state: FSMContext):
    """Удаление выбранных фоновых изображений и сброс состояния FSM."""
    await safe_call_answer(call)
    data = await state.get_data()
    for mid in data.get('prev_msgs', []):
        try:
            await call.bot.delete_message(call.message.chat.id, mid)
        except TelegramBadRequest:
            pass

    folder = data['folder']
    files = data['files']
    for idx in sorted(data['delete_indices'], reverse=True):
        try:
            os.remove(os.path.join(folder, files[idx]))
        except OSError:
            pass
        del files[idx]

    count = len(data['delete_indices'])
    await state.clear()
    await call.message.answer(f"🗑️ Удалено {count} фонов.")
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_admin_bg")
async def go_back_admin_bg(call: CallbackQuery, state: FSMContext):
    """Обрабатывает возврат в меню управления фонами из любого состояния."""
    await safe_call_answer(call)
    current = await state.get_state()
    data = await state.get_data()
    chat_id = call.message.chat.id

    if current == AdminBgStates.confirm_delete.state:
        for mid in data.get("prev_msgs", []):
            try:
                await call.bot.delete_message(chat_id, mid)
            except TelegramBadRequest:
                pass
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

        page = data.get("current_page", 0)
        await _show_bg_images(call, state, page)
        return

    if current == AdminBgStates.wait_numbers.state:
        for mid in data.get("prev_msgs", []):
            try:
                await call.bot.delete_message(chat_id, mid)
            except TelegramBadRequest:
                pass
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="+ Добавить фон", callback_data="bg_add"),
                InlineKeyboardButton(text="- Удалить фон", callback_data="bg_delete")
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_back")]
        ])
        await call.bot.send_message(chat_id, text="⚙️ Управление фонами:", reply_markup=kb)
        await state.set_state(AdminBgStates.browsing)
        return

    if current == AdminBgStates.wait_upload.state or True:
        await state.clear()
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="+ Добавить фон", callback_data="bg_add"),
                InlineKeyboardButton(text="- Удалить фон", callback_data="bg_delete")
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="admin_back")]
        ])
        await call.bot.send_message(chat_id, text="⚙️ Управление фонами:", reply_markup=kb)
        await state.set_state(AdminBgStates.browsing)


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_backgrounds(dp):
    """Регистрирует роутер управления фонами."""
    dp.include_router(router)
