import os
import re

import config

from aiogram import Router, F, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, FSInputFile, MediaUnion
)
from typing import Sequence
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.utils import safe_answer_callback
from utils.image_processing import add_number_overlay
from handlers.core.admin import START_TEXT, get_admin_menu_kb
from utils.database.dropbox_storage import upload_file, delete_file


router = Router()


class AdminImgStates(StatesGroup):
    images_menu = State()
    images_category = State()
    images_browsing = State()
    images_wait_numbers = State()
    images_confirm_delete = State()
    images_wait_upload = State()


IMAGES_FOLDER = "resources/images/"

# ——————————————————————
# Меню управления открытками
# ——————————————————————
@router.callback_query(F.data == "admin_images")
async def admin_images_menu(call: CallbackQuery, state: FSMContext):
    """Отображает меню управления изображениями: удаление и добавление."""
    await safe_answer_callback(call, state)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="+ Добавить", callback_data="admin_images_add"),
        InlineKeyboardButton(text="- Удалить", callback_data="admin_images_delete")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_data_management")]
    ])
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text="⚙️ Меню управления изображениями:",
            reply_markup=kb
        )
    await state.set_state(AdminImgStates.images_menu)


# ——————————————————————
# Добавление изображений (без категорий)
# ——————————————————————
@router.callback_query(AdminImgStates.images_menu, F.data == "admin_images_add")
async def admin_images_add(call: CallbackQuery, state: FSMContext):
    """Инициирует процесс добавления фотографий: выбор категории."""
    await safe_answer_callback(call, state)
    # Сразу переходим к загрузке в одну папку
    nums = []
    if os.path.exists(IMAGES_FOLDER):
        for f in os.listdir(IMAGES_FOLDER):
            m = re.match(r"(\d+)", f)
            if m:
                nums.append(int(m.group(1)))
    next_idx = max(nums) + 1 if nums else 1
    await state.update_data(
        img_folder=IMAGES_FOLDER,
        start_index=next_idx,
        next_index=next_idx,
        pending_files=[]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Добавить", callback_data="done_upload")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_admin_img")]
    ])
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text="Пришлите любые изображения (альбом, несколько фото или документы).\n\n👇 После добавления всех фотографий нажмите кнопку 'Добавить'!",
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

    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
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
    await safe_answer_callback(call, state)
    data = await state.get_data()

    folder = data["img_folder"]
    idx = data["next_index"]
    pending = data.get("pending_files", [])

    for item in pending:
        bot = getattr(call, 'bot', None)
        if not bot:
            continue
        tg_file = await bot.get_file(item["file_id"])
        if item["type"] == "photo":
            ext = ".jpg"
        else:
            ext = os.path.splitext(item["file_name"])[1] or ".png"

        fn = f"{idx}{ext}"
        dest = os.path.join(folder, fn)
        if not tg_file.file_path:
            continue
        await bot.download_file(tg_file.file_path, destination=dest)

        # Синхронизация с Dropbox
        upload_file(dest, f"/resources/images/{fn}")

        idx += 1

    count = len(pending)
    await state.clear()
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.bot.delete_message(msg.chat.id, msg.message_id)
    if count == 0:
        if msg:
            await msg.answer(
                text="❌ Файлы не были загружены."
            )
    else:
        if msg:
            await msg.answer(
                text=f"🎉 Успешно добавлено {count} файлов."
            )

    if msg:
        await msg.answer(
            text=START_TEXT,
            reply_markup=get_admin_menu_kb()
        )


# ——————————————————————
# Удаление изображений (без категорий)
# ——————————————————————
@router.callback_query(AdminImgStates.images_menu, F.data == "admin_images_delete")
async def admin_images_delete(call: CallbackQuery, state: FSMContext):
    """Инициирует процесс удаления фотографий: сразу показывает альбом с номерами."""
    await safe_answer_callback(call, state)
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.bot.delete_message(msg.chat.id, msg.message_id)
    # Получаем список файлов из папки и сортируем по номеру в имени
    def extract_num(fname):
        m = re.match(r"(\d+)", fname)
        return int(m.group(1)) if m else float('inf')
    files = [f for f in os.listdir(IMAGES_FOLDER) if os.path.isfile(os.path.join(IMAGES_FOLDER, f)) and f.lower().endswith((".jpg", ".png"))]
    files.sort(key=extract_num)
    if not files:
        if call.message:
            await call.message.answer("В папке нет изображений для удаления.")
        return
    await state.update_data(img_files=files, img_folder=IMAGES_FOLDER)
    await show_admin_images(call, state, page=0)


async def show_admin_images(call: CallbackQuery, state: FSMContext, page: int, loading_msg=None):
    """Показывает фотографии постранично с возможностью навигации и вводом номеров для удаления."""
    data = await state.get_data()
    files = data['img_files']; folder = data['img_folder']
    total = len(files); max_page = (total - 1) // 10 if total else 0
    page = page % (max_page + 1 if total else 1)
    start, end = page * 10, min((page + 1) * 10, total)

    msg = getattr(call, 'message', None)
    for mid in data.get('prev_msgs', []):
        try:
            if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
                await msg.bot.delete_message(msg.chat.id, mid)
        except:
            pass

    if loading_msg:
        msg = getattr(call, 'message', None)
        bot = getattr(msg, 'bot', None)
        chat = getattr(msg, 'chat', None)
        if bot and chat:
            await bot.delete_message(chat.id, loading_msg.message_id)

    msg = getattr(call, 'message', None)
    if msg:
        loading = await msg.answer("⚙️ Загружаем картинки...")

    media = []
    for idx, fname in enumerate(files[start:end], start):
        src = os.path.join(folder, fname)
        tmp = os.path.join(config.Output_Folder, f"adm_img_{idx}_{fname}")
        add_number_overlay(str(src), str(tmp), number=idx + 1)
        media.append(InputMediaPhoto(media=FSInputFile(tmp)))
    if msg:
        msgs = await msg.answer_media_group(media)
        bot = getattr(msg, 'bot', None)
        chat = getattr(msg, 'chat', None)
        if bot and chat:
            await bot.delete_message(chat.id, loading.message_id)

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
        prompt = await msg.answer(
            text="🔢 Введите номера фото для удаления (через запятую):",
            reply_markup=kb
        )
        await state.update_data(prev_msgs=mids + [prompt.message_id])
    await state.set_state(AdminImgStates.images_wait_numbers)


@router.callback_query(F.data.startswith("img_prev_") | F.data.startswith("img_next_"))
async def admin_images_page(call: CallbackQuery, state: FSMContext):
    """Обрабатывает навигацию по страницам изображений."""
    await safe_answer_callback(call, state)
    if not call.data:
        return
    
    page = int(call.data.split("_")[-1])
    await show_admin_images(call, state, page)


@router.message(AdminImgStates.images_wait_numbers)
async def handle_delete_numbers(message: Message, state: FSMContext):
    """Парсит введённые номера фотографий и отображает их для подтверждения удаления."""
    data = await state.get_data()
    await message.delete()
    msg = message
    if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
        bot = getattr(msg, 'bot', None)
        chat = getattr(msg, 'chat', None)
        for mid in data.get('prev_msgs', []):
            try:
                if bot and chat:
                    await bot.delete_message(chat.id, mid)
            except:
                pass

    if not message.text:
        return await message.answer("❌ Пожалуйста, введите номера фотографий.")
    
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

    media: Sequence[MediaUnion] = [
        InputMediaPhoto(media=FSInputFile(
            os.path.join(str(data['img_folder']), str(data['img_files'][i]))
        ))
        for i in indices
    ]
    msgs = await message.answer_media_group(list(media))
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
    await safe_answer_callback(call, state)
    data = await state.get_data()
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
        for mid in data.get('prev_ids', []):
            try:
                await msg.bot.delete_message(msg.chat.id, mid)
            except:
                pass
    await show_admin_images(call, state, page=0)


@router.callback_query(AdminImgStates.images_confirm_delete, F.data == "confirm_delete_photos")
async def admin_images_do_delete(call: CallbackQuery, state: FSMContext):
    """Удаляет подтвержденные фотографии из файловой системы и обновляет список."""
    await safe_answer_callback(call, state)
    data = await state.get_data()
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
        for mid in data.get('prev_ids', []):
            try:
                await msg.bot.delete_message(msg.chat.id, mid)
            except:
                pass

    try:
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
            await msg.bot.delete_message(msg.chat.id, msg.message_id)
    except TelegramBadRequest:
        pass

    folder = data['img_folder']
    files = data['img_files']
    indices = data['delete_indices']
    for idx in sorted(indices, reverse=True):
        path = os.path.join(folder, files[idx])
        dropbox_path = f"/resources/images/{files[idx]}"
        try:
            os.remove(path)
            delete_file(dropbox_path)
        except OSError:
            pass
        del files[idx]

    deleted_count = len(indices)
    await state.clear()
    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.answer(
            text=f"🗑️ Удалено {deleted_count} фото."
        )
        await msg.answer(
            text=START_TEXT,
            reply_markup=get_admin_menu_kb()
        )


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_admin_img")
async def go_back_admin_img(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя к предыдущему шагу в стэке состояний"""
    await safe_answer_callback(call, state)
    current = await state.get_state()

    if current == AdminImgStates.images_wait_numbers.state:
        data = await state.get_data()
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
            bot = getattr(msg, 'bot', None)
            chat = getattr(msg, 'chat', None)
            for mid in data.get("prev_msgs", []):
                try:
                    if bot and chat:
                        await bot.delete_message(chat.id, mid)
                except TelegramBadRequest:
                    pass
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None) and getattr(msg, 'chat', None):
            try:
                await msg.bot.delete_message(msg.chat.id, msg.message_id)
            except TelegramBadRequest:
                pass
        keyboard = [
            [InlineKeyboardButton(text="+ Добавить", callback_data="admin_images_add"),
            InlineKeyboardButton(text="- Удалить", callback_data="admin_images_delete")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_data_management")]
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.answer(text="⚙️ Меню управления открытками:", reply_markup=kb)
        await state.set_state(AdminImgStates.images_menu)
        return

    if current == AdminImgStates.images_wait_upload.state:
        await state.clear()
        keyboard = [
            [InlineKeyboardButton(text="+ Добавить", callback_data="admin_images_add"),
            InlineKeyboardButton(text="- Удалить", callback_data="admin_images_delete")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_data_management")]
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            try:
                await msg.bot.delete_message(msg.chat.id, msg.message_id)
            except TelegramBadRequest:
                pass
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.answer(text="⚙️ Меню управления изображениями:", reply_markup=kb)
        await state.set_state(AdminImgStates.images_menu)
        return

    if current == AdminImgStates.images_category.state:
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.bot.delete_message(msg.chat.id, msg.message_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+ Добавить", callback_data="admin_images_add"),
            InlineKeyboardButton(text="- Удалить", callback_data="admin_images_delete")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_data_management")]
        ])
        msg = getattr(call, 'message', None)
        if msg and getattr(msg, 'bot', None):
            await msg.answer(text="⚙️ Меню управления изображениями:", reply_markup=kb)
        await state.set_state(AdminImgStates.images_menu)
        return

    msg = getattr(call, 'message', None)
    if msg and getattr(msg, 'bot', None):
        await msg.delete_message(msg.chat.id, msg.message_id)
        await msg.answer(
            text=START_TEXT,
            reply_markup=get_admin_menu_kb()
        )


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_admin_img(dp: Dispatcher):
    """Регистрирует роутер."""
    dp.include_router(router)
    