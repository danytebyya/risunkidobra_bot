import os
import re
import shutil

import config

from aiogram import Router, F, Dispatcher
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


router = Router()


class AdminImgStates(StatesGroup):
    images_menu = State()
    images_category = State()
    images_browsing = State()
    images_wait_numbers = State()
    images_confirm_delete = State()
    images_wait_upload = State()


# ——————————————————————
# Меню управления открытками
# ——————————————————————
@router.callback_query(F.data == "admin_images")
async def admin_images_menu(call: CallbackQuery, state: FSMContext):
    """Отображает меню управления изображениями: удаление и добавление."""
    await safe_call_answer(call)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="admin_images_add"),
        InlineKeyboardButton(text="- Удалить", callback_data="admin_images_delete")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
    ])
    await call.message.edit_text(text="⚙️ Меню управления изображениями:", reply_markup=kb)
    await state.set_state(AdminImgStates.images_menu)


# ——————————————————————
# Добавление цвета
# ——————————————————————
@router.callback_query(AdminImgStates.images_menu, F.data == "admin_images_add")
async def admin_images_add(call: CallbackQuery, state: FSMContext):
    """Инициирует процесс добавления фотографий: выбор категории."""
    await safe_call_answer(call)
    keyboard = [[InlineKeyboardButton(text=cat, callback_data=f"img_add_{cat}")] for cat in config.Image_Categories.keys()]
    keyboard.append([InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")])
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await call.message.edit_text(text="👇 Выберите категорию для добавления:", reply_markup=kb)
    await state.set_state(AdminImgStates.images_category)
    await state.set_state(AdminImgStates.images_category)


@router.callback_query(AdminImgStates.images_category, F.data.startswith("img_add_"))
async def admin_images_ready_upload(call: CallbackQuery, state: FSMContext):
    """Готовит хранилище для загрузки новых фотографий и ждёт отправки файлов."""
    await safe_call_answer(call)
    await call.message.delete()

    cat = call.data.split("img_add_")[1]
    folder = config.Image_Categories[cat]

    nums = [
        int(re.match(r"(\d+)", f).group(1))
        for f in os.listdir(folder)
        if re.match(r"^\d+", f)
    ]
    next_idx = max(nums) + 1 if nums else 1

    await state.update_data(
        img_folder=folder,
        start_index=next_idx,
        next_index=next_idx,
        pending_files=[]
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Добавить", callback_data="done_upload")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")]
    ])
    await call.message.answer(
        text="Пришлите любые изображения (альбом, несколько фото или документы)."
        '\n\n👇 После добавления всех фотографий нажмите кнопку "Добавить"!',
        reply_markup=kb
    )
    await state.set_state(AdminImgStates.images_wait_upload)


@router.message(AdminImgStates.images_wait_upload)
async def admin_images_collect(message: Message, state: FSMContext):
    """Собирает фото и документы в ожидании завершения загрузки."""
    data = await state.get_data()
    pending = data.get("pending_files", [])

    if message.photo:
        file = message.photo[-1]
        pending.append({
            "type": "photo",
            "file_id": file.file_id
        })

    elif message.document and message.document.mime_type.startswith("image/"):
        pending.append({
            "type": "document",
            "file_id": message.document.file_id,
            "file_name": message.document.file_name
        })

    else:
        return await message.answer("❌ Пожалуйста, пришлите изображение или фото-файл.")

    await state.update_data(pending_files=pending)


@router.callback_query(AdminImgStates.images_wait_upload, F.data == "done_upload")
async def finish_upload(call: CallbackQuery, state: FSMContext):
    """Сохраняет загруженные файлы в нужную папку и сообщает об успешном добавлении."""
    await safe_call_answer(call)
    data = await state.get_data()

    folder = data["img_folder"]
    idx = data["next_index"]
    pending = data.get("pending_files", [])

    general_folder = config.Image_Categories["Общее"]
    nums = [
        int(re.match(r"(\d+)", f).group(1))
        for f in os.listdir(general_folder)
        if re.match(r"^\d+", f)
    ]
    general_idx = max(nums) + 1 if nums else 1

    for item in pending:
        tg_file = await call.bot.get_file(item["file_id"])
        if item["type"] == "photo":
            ext = ".jpg"
        else:
            ext = os.path.splitext(item["file_name"])[1] or ".png"

        fn = f"{idx}{ext}"
        dest = os.path.join(folder, fn)
        await call.bot.download_file(tg_file.file_path, destination=dest)

        if os.path.abspath(folder) != os.path.abspath(general_folder):
            fn_all = f"{general_idx}{ext}"
            dest_all = os.path.join(general_folder, fn_all)
            shutil.copy(dest, dest_all)
            general_idx += 1

        idx += 1

    count = len(pending)
    await state.clear()
    await call.message.delete()
    if count == 0:
        await call.message.answer("❌ Файлы не были загружены.")
    else:
        await call.message.answer(f"🎉 Успешно добавлено {count} файлов.")

    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Удаление цвета
# ——————————————————————
@router.callback_query(AdminImgStates.images_menu, F.data == "admin_images_delete")
async def admin_images_delete(call: CallbackQuery, state: FSMContext):
    """Инициирует процесс выбора категории для удаления фотографий."""
    await safe_call_answer(call)
    await call.message.delete()
    keyboard = [[InlineKeyboardButton(text=cat, callback_data=f"img_cat_{cat}")]
                for cat in config.Image_Categories.keys()]
    keyboard.append([InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")])
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await call.message.answer(text="👇 Выберите категорию:", reply_markup=kb)
    await state.set_state(AdminImgStates.images_category)


@router.callback_query(AdminImgStates.images_category, F.data.startswith("img_cat_"))
async def admin_images_select_category(call: CallbackQuery, state: FSMContext):
    """Загружает список файлов выбранной категории и сохраняет их в state для дальнейшей обработки."""
    await safe_call_answer(call)
    await call.message.delete()
    cat = call.data.split("img_cat_")[1]
    folder = config.Image_Categories.get(cat)
    files = []
    for f in os.listdir(folder):
        if f.lower().endswith((".jpg",".png")):
            m = re.match(r"(\d+)", os.path.splitext(f)[0])
            if m:
                files.append((int(m.group(1)), f))
    files.sort(key=lambda x: x[0])
    filenames = [f for _, f in files]
    next_idx = files[-1][0] + 1 if files else 1
    await state.update_data(img_folder=folder, img_files=filenames, next_index=next_idx)
    await show_admin_images(call, state, page=0)


async def show_admin_images(call: CallbackQuery, state: FSMContext, page: int, loading_msg=None):
    """Показывает фотографии постранично с возможностью навигации и вводом номеров для удаления."""
    data = await state.get_data()
    files = data['img_files']; folder = data['img_folder']
    total = len(files); max_page = (total - 1) // 10 if total else 0
    page = page % (max_page + 1 if total else 1)
    start, end = page * 10, min((page + 1) * 10, total)

    for mid in data.get('prev_msgs', []):
        try:
            await call.bot.delete_message(call.message.chat.id, mid)
        except:
            pass

    if loading_msg:
        await call.bot.delete_message(call.message.chat.id, loading_msg.message_id)

    loading = await call.message.answer("⚙️ Загружаем картинки...")

    media = []
    for idx, fname in enumerate(files[start:end], start):
        src = os.path.join(folder, fname)
        tmp = os.path.join(config.Output_Folder, f"adm_img_{idx}_{fname}")
        add_number_overlay(str(src), str(tmp), number=idx + 1)
        media.append(InputMediaPhoto(media=FSInputFile(tmp)))
    msgs = await call.message.answer_media_group(media)
    await call.bot.delete_message(call.message.chat.id, loading.message_id)

    mids = [m.message_id for m in msgs]
    nav = [
        InlineKeyboardButton(text="←", callback_data=f"img_prev_{page - 1}"),
        InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}" if total else "0/0", callback_data="noop"),
        InlineKeyboardButton(text="→", callback_data=f"img_next_{page + 1}")
    ]
    keyboard = [
        nav,
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
    prompt = await call.message.answer(
        text="🔢 Введите номера фото для удаления (через запятую):", reply_markup=kb
    )
    await state.update_data(prev_msgs=mids + [prompt.message_id])
    await state.set_state(AdminImgStates.images_wait_numbers)


@router.callback_query(F.data.startswith("img_prev_") | F.data.startswith("img_next_"))
async def admin_images_page(call: CallbackQuery, state: FSMContext):
    """Обрабатывает навигацию по страницам изображений."""
    await safe_call_answer(call)
    page = int(call.data.split("_")[-1])
    await show_admin_images(call, state, page)


@router.message(AdminImgStates.images_wait_numbers)
async def handle_delete_numbers(message: Message, state: FSMContext):
    """Парсит введённые номера фотографий и отображает их для подтверждения удаления."""
    data = await state.get_data()
    await message.delete()
    for mid in data.get('prev_msgs', []):
        try:
            await message.bot.delete_message(message.chat.id, mid)
        except:
            pass

    text = message.text or ''
    nums = [n.strip() for n in text.split(',') if n.strip()]
    if not nums or not all(n.isdigit() for n in nums):
        return await message.answer(
            f"❌ Пожалуйста, введите цифры от 1 до {len(data['img_files'])} через запятую."
        )
    indices = sorted({int(n) - 1 for n in nums})
    if not all(0 <= i < len(data['img_files']) for i in indices):
        return await message.answer(
            f"❌ Номера должны быть от 1 до {len(data['img_files'])}."
        )
    await state.update_data(delete_indices=indices)

    media = [
        InputMediaPhoto(media=FSInputFile(
            os.path.join(str(data['img_folder']), str(data['img_files'][i]))
        ))
        for i in indices
    ]
    msgs = await message.answer_media_group(media)
    prev_ids = [m.message_id for m in msgs]

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑️ Удалить", callback_data="confirm_delete_photos"),
        InlineKeyboardButton(text="⏎ Назад", callback_data="admin_images_delete"),
    ]])
    prompt_msg = await message.answer(
        text="Вы действительно хотите удалить выбранные фотографии?",
        reply_markup=kb
    )
    prev_ids.append(prompt_msg.message_id)
    await state.update_data(prev_ids=prev_ids)
    await state.set_state(AdminImgStates.images_confirm_delete)


@router.callback_query(AdminImgStates.images_confirm_delete, F.data == "admin_images_delete")
async def cancel_delete(call: CallbackQuery, state: FSMContext):
    """Отменяет удаление и возвращает к выбору фотографий."""
    await safe_call_answer(call)
    data = await state.get_data()
    for mid in data.get('prev_ids', []):
        try:
            await call.bot.delete_message(call.message.chat.id, mid)
        except:
            pass
    await show_admin_images(call, state, page=0)


@router.callback_query(AdminImgStates.images_confirm_delete, F.data == "confirm_delete_photos")
async def admin_images_do_delete(call: CallbackQuery, state: FSMContext):
    """Удаляет подтвержденные фотографии из файловой системы и обновляет список."""
    await safe_call_answer(call)
    data = await state.get_data()
    for mid in data.get('prev_ids', []):
        try:
            await call.bot.delete_message(call.message.chat.id, mid)
        except:
            pass

    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass

    folder = data['img_folder']
    files = data['img_files']
    indices = data['delete_indices']
    for idx in sorted(indices, reverse=True):
        path = os.path.join(folder, files[idx])
        try:
            os.remove(path)
        except OSError:
            pass
        del files[idx]

    deleted_count = len(indices)
    await state.clear()
    await call.message.answer(f"🗑️ Удалено {deleted_count} фото.")
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_admin_img")
async def go_back_admin_img(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя к предыдущему шагу в стэке состояний"""
    await safe_call_answer(call)
    current = await state.get_state()

    if current == AdminImgStates.images_wait_numbers.state:
        data = await state.get_data()
        chat_id = call.message.chat.id
        for mid in data.get("prev_msgs", []):
            try:
                await call.bot.delete_message(chat_id, mid)
            except TelegramBadRequest:
                pass
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        keyboard = [
            [InlineKeyboardButton(text=cat, callback_data=f"img_cat_{cat}")]
            for cat in config.Image_Categories.keys()
        ]
        keyboard.append([
            InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")
        ])
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await call.message.answer(text="👇 Выберите категорию:", reply_markup=kb)
        await state.set_state(AdminImgStates.images_category)
        return

    if current == AdminImgStates.images_wait_upload.state:
        await state.clear()
        keyboard = [
            [InlineKeyboardButton(text=cat, callback_data=f"img_add_{cat}")]
            for cat in config.Image_Categories.keys()
        ]
        keyboard.append([
            InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")
        ])
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(text="👇 Выберите категорию для добавления:", reply_markup=kb)
        await state.set_state(AdminImgStates.images_category)
        return

    if current == AdminImgStates.images_category.state:
        await call.message.delete()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="admin_images_add"),
            InlineKeyboardButton(text="- Удалить", callback_data="admin_images_delete")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="admin_back")]
        ])
        await call.message.answer(text="⚙️ Меню управления изображениями:", reply_markup=kb)
        await state.set_state(AdminImgStates.images_menu)
        return

    await call.message.delete()
    await call.message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_img(dp: Dispatcher):
    """Регистрирует роутер."""
    dp.include_router(router)
