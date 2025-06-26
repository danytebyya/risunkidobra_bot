import os
import random

from aiogram import Router, Dispatcher, F
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, FSInputFile, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from PIL import Image

import config

from config import logger
from utils.database.db import list_fonts, list_colors
from utils.image_processing import add_watermark, add_text_to_image, add_number_overlay
from utils.payments.payment_functional import create_payment, check_payment_status
from utils.utils import safe_edit_text, safe_edit_media, push_state, validate_text, safe_call_answer
from handlers.core.start import START_TEXT, get_main_menu_kb
from handlers.core.subscription import is_subscribed


router = Router()


class ImageMaker(StatesGroup):
    choosing_category = State()
    choosing_image = State()
    choosing_font = State()
    choosing_color = State()
    choosing_position = State()
    entering_text = State()


# ——————————————————————
# Меню создания открытки
# ——————————————————————
@router.callback_query(F.data == 'create_card')
async def create_card(call: CallbackQuery, state: FSMContext, force_new_message: bool = False):
    """Инициализирует создание новой открытки и предлагает выбрать категорию"""
    await state.clear()
    await state.update_data(state_stack=[])

    text = (
        '✨ Добро пожаловать в мастерскую открыток!\n\n'
        '♡ Выберите изображение по душе, которое задаст настроение вашей открытке\n'
        '✎ Напишите тёплое личное послание в изысканном шрифте, отражающем ваши чувства\n'
        '✓ Завершите оформление: оплатите заказ и мгновенно получите своё уникальное творение\n\n'
        'Готовы вдохновлять близких?\n\n'
        '👇 Начнём с выбора категории изображения:'
    )

    await push_state(state, ImageMaker.choosing_category)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f'category_{name}')] for name in config.Image_Categories
    ] + [[InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="go_back")]])

    if force_new_message:
        await call.message.answer(text, reply_markup=keyboard)
    else:
        await safe_edit_text(call.message, text=text, reply_markup=keyboard)

    logger.info(f"User {call.from_user.id}: started image creation")
    await call.answer()


# ——————————————————————
# Выбор категории изображения
# ——————————————————————
@router.callback_query(F.data.startswith('category_'))
async def process_category(call: CallbackQuery, state: FSMContext):
    """Сохраняет выбранную категорию и переходит к выбору изображения"""
    category = call.data.split(sep='_', maxsplit=1)[1]
    if category not in config.Image_Categories:
        await call.answer(text='❌ Категория не найдена', show_alert=True)
        return
    await safe_call_answer(call)
    await state.update_data(selected_category=category)

    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass

    logger.info(f"User {call.from_user.id}: selected category {category}")
    await choose_image(call, state)


async def choose_image(call: CallbackQuery, state: FSMContext):
    """Загружает список файлов изображений и инициирует показ первого изображения"""
    await push_state(state, ImageMaker.choosing_image)
    data = await state.get_data()
    folder = config.Image_Categories[data['selected_category']]
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.png')))
    await state.update_data(image_files=files, image_folder=folder)
    await show_images_album(call, state, page=0)


async def show_images_album(call: CallbackQuery, state: FSMContext, page: int = 0):
    """Отображает изображения постранично с водяными знаками и нумерацией."""
    await safe_call_answer(call)

    user_id = call.from_user.id

    data = await state.get_data()
    old_album_msgs = data.get('last_album_msgs', [])
    keyboard_msg_id = data.get('last_keyboard_msg_id')
    for msg_id in old_album_msgs:
        try:
            await call.bot.delete_message(call.message.chat.id, msg_id)
        except TelegramBadRequest:
            pass
    if keyboard_msg_id:
        try:
            await call.bot.delete_message(call.message.chat.id, keyboard_msg_id)
        except TelegramBadRequest:
            pass

    loading_msg = await call.message.answer("⚙️ Загружаем картинки...")
    files = data['image_files']
    total = len(files)
    image_folder = data['image_folder']
    max_page = (total - 1) // 10
    if page < 0:
        page = max_page
    elif page > max_page:
        page = 0
    start = page * 10
    end = min(start + 10, total)
    page_files = files[start:end]

    media = []
    for i, filename in enumerate(page_files):
        src = os.path.join(image_folder, filename)
        numbered_path = os.path.join(
            config.Output_Folder,
            f'scroll_numbered_{start + i + 1}_{os.path.basename(src)}'
        )
        if await is_subscribed(user_id):
            add_number_overlay(str(src), numbered_path, number=i + 1)
        else:
            wm_path = os.path.join(
                config.Output_Folder,
                f'scroll_watermarked_{os.path.basename(src)}'
            )
            add_watermark(src, wm_path, watermark_text='Создано в Добрые Открыточки<3')
            add_number_overlay(wm_path, numbered_path, number=i + 1)
        media.append(InputMediaPhoto(media=FSInputFile(numbered_path)))

    album_msgs = await loading_msg.answer_media_group(media=media)
    album_msg_ids = [msg.message_id for msg in album_msgs]

    select_buttons = [
        [InlineKeyboardButton(text=str(i+1), callback_data=f'select_image_{start+i}')
         for i in range(0, min(5, len(page_files)))],
        [InlineKeyboardButton(text=str(i+1), callback_data=f'select_image_{start+i}')
         for i in range(5, min(10, len(page_files)))]
    ]
    max_page_display = max_page + 1
    nav_buttons = [
        InlineKeyboardButton(text='←', callback_data=f'prev_page_{page-1}'),
        InlineKeyboardButton(text=f'{page+1}/{max_page_display}', callback_data='noop'),
        InlineKeyboardButton(text='→', callback_data=f'next_page_{page+1}')
    ]
    back_button = [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back')]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=select_buttons + [nav_buttons] + [back_button]
    )
    keyboard_msg = await loading_msg.answer(
        text="♡ Погрузитесь в коллекцию и выберите изображение:",
        reply_markup=keyboard
    )
    try:
        await loading_msg.delete()
    except TelegramBadRequest:
        pass
    await state.update_data(
        last_album_msgs=album_msg_ids,
        last_keyboard_msg_id=keyboard_msg.message_id,
        image_page=page
    )


@router.callback_query(F.data.startswith('next_page_'))
async def next_page_cb(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split('_')[-1])
    await show_images_album(call, state, page)


@router.callback_query(F.data.startswith('prev_page_'))
async def prev_page_cb(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split('_')[-1])
    await show_images_album(call, state, page)


@router.callback_query(F.data.startswith('select_image_'))
async def select_image_cb(call: CallbackQuery, state: FSMContext):
    """Сохраняет выбранное изображение и переходит к выбору шрифта."""
    await safe_call_answer(call)
    idx = int(call.data.split('_')[-1])
    data = await state.get_data()
    filename = data['image_files'][idx]
    await state.update_data(selected_image=filename, image_index=idx)

    old_album_msgs = data.get('last_album_msgs', [])
    keyboard_msg_id = data.get('last_keyboard_msg_id')

    for msg_id in old_album_msgs:
        try:
            await call.bot.delete_message(call.message.chat.id, msg_id)
        except TelegramBadRequest:
            pass
    if keyboard_msg_id:
        try:
            await call.bot.delete_message(call.message.chat.id, keyboard_msg_id)
        except TelegramBadRequest:
            pass

    logger.info(f"User {call.from_user.id}: selected image {filename}")
    await choose_font(call, state)


# ——————————————————————
# Выбор шрифта
# ——————————————————————
async def choose_font(call: CallbackQuery, state: FSMContext, edit=False):
    """Отображает образцы шрифтов и навигацию по ним"""
    await push_state(state, ImageMaker.choosing_font)
    data = await state.get_data()
    fonts = await list_fonts()
    if not fonts:
        await call.answer("❌ База шрифтов пуста", show_alert=True)
        return
    idx = data.get('font_index', 0) % len(fonts)
    font = fonts[idx]
    await state.update_data(font_index=idx)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='←', callback_data='prev_font'),
         InlineKeyboardButton(text=f'{idx+1}/{len(fonts)}', callback_data='noop'),
         InlineKeyboardButton(text='→', callback_data='next_font')],
        [InlineKeyboardButton(text='✓ Выбрать', callback_data=f'select_font_{font['id']}')],
        [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back')]
    ])
    media = InputMediaPhoto(media=FSInputFile(font['sample_path']),
                            caption=f'✎ Подберите стиль шрифта — '
                                    f'пусть ваше послание зазвучит по-особенному')
    if edit:
        try:
            await call.message.edit_media(media=media, reply_markup=keyboard)
        except TelegramBadRequest:
            await call.message.answer_photo(photo=FSInputFile(font['sample_path']),
                                           caption=f'✎ Подберите стиль шрифта — '
                                                    f'пусть ваше послание зазвучит по-особенному',
                                           reply_markup=keyboard)
    else:
        await call.message.answer_photo(photo=FSInputFile(font['sample_path']),
                                        caption=f'✎ Подберите стиль шрифта — '
                                                f'пусть ваше послание зазвучит по-особенному',
                                        reply_markup=keyboard)
    await call.answer()


@router.callback_query(F.data == 'prev_font')
async def prev_font(call: CallbackQuery, state: FSMContext):
    """Переходит к предыдущему образцу шрифта"""
    data = await state.get_data()
    fonts = await list_fonts()
    idx = (data.get('font_index', 0) - 1) % len(fonts)
    await state.update_data(font_index=idx)
    await choose_font(call, state, edit=True)


@router.callback_query(F.data == 'next_font')
async def next_font(call: CallbackQuery, state: FSMContext):
    """Переходит к следующему образцу шрифта"""
    data = await state.get_data()
    fonts = await list_fonts()
    idx = (data.get('font_index', 0) + 1) % len(fonts)
    await state.update_data(font_index=idx)
    await choose_font(call, state, edit=True)


@router.callback_query(F.data.startswith('select_font_'))
async def select_font(call: CallbackQuery, state: FSMContext):
    """Сохраняет выбранный шрифт и переходит к выбору цвета"""
    font_id = int(call.data.split('_')[-1])
    fonts = await list_fonts()
    selected = next((f for f in fonts if f['id'] == font_id), None)
    if not selected:
        await call.answer("❌ Шрифт не найден", show_alert=True)
        return
    await state.update_data(selected_font=selected['font_path'])
    await call.answer()
    await choose_color(call, state)


# ——————————————————————
# Выбор цвета
# ——————————————————————
async def choose_color(call: CallbackQuery, state: FSMContext):
    """Отображает образцы цветов и навигацию по ним"""
    await push_state(state, ImageMaker.choosing_color)
    data = await state.get_data()
    colors = await list_colors()
    if not colors:
        await call.answer("❌ База цветов пуста", show_alert=True)
        return
    idx = data.get('color_index', 0) % len(colors)
    color = colors[idx]
    await state.update_data(color_index=idx)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='←', callback_data='prev_color'),
         InlineKeyboardButton(text=f'{idx+1}/{len(colors)}', callback_data='noop'),
         InlineKeyboardButton(text='→', callback_data='next_color')],
        [InlineKeyboardButton(text=f'✓ {color['name']}', callback_data=f'select_color_{color['id']}')],
        [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back')]
    ])
    media = InputMediaPhoto(media=FSInputFile(color['sample_path']),
                            caption= f"🎨 Выберите цвет — "
                            "чтобы каждая деталь передавала нужное настроение")
    await safe_edit_media(call.message, media=media, reply_markup=keyboard)


@router.callback_query(F.data == 'prev_color')
async def prev_color(call: CallbackQuery, state: FSMContext):
    """Переключается на предыдущий образец цвета"""
    data = await state.get_data()
    colors = await list_colors()
    idx = (data.get('color_index', 0) - 1) % len(colors)
    await state.update_data(color_index=idx)
    await choose_color(call, state)


@router.callback_query(F.data == 'next_color')
async def next_color(call: CallbackQuery, state: FSMContext):
    """Переключается на следующий образец цвета"""
    data = await state.get_data()
    colors = await list_colors()
    idx = (data.get('color_index', 0) + 1) % len(colors)
    await state.update_data(color_index=idx)
    await choose_color(call, state)


@router.callback_query(F.data.startswith('select_color_'))
async def select_color(call: CallbackQuery, state: FSMContext):
    """Сохраняет выбранный цвет и переходит к выбору позиции текста"""
    color_id = int(call.data.split('_')[-1])
    colors = await list_colors()
    selected = next((c for c in colors if c['id'] == color_id), None)
    if not selected:
        await call.answer("❌ Цвет не найден", show_alert=True)
        return
    await state.update_data(selected_color=selected['hex'])
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    await call.answer()
    await choose_position(call, state)


# ——————————————————————
# Выбор позиции текста
# ——————————————————————
async def choose_position(call: CallbackQuery, state: FSMContext):
    """Отображает клавиатуру для выбора позиции текста"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Сверху', callback_data='position_top'),
            InlineKeyboardButton(text='По центру', callback_data='position_center'),
            InlineKeyboardButton(text='Снизу', callback_data='position_bottom'),
        ],
        [ InlineKeyboardButton(text='⏎ Назад', callback_data='go_back') ]
    ])

    await call.message.answer(text='👇 Укажите, где разместить текст', reply_markup=kb)
    await state.set_state(ImageMaker.choosing_position)
    await call.answer()


@router.callback_query(F.data.startswith('position_'))
async def select_position(call: CallbackQuery, state: FSMContext):
    """Сохраняет выбранную позицию текста и переводит пользователя к вводу текста"""
    pos = call.data.split('_')[-1]
    await state.update_data(selected_text_position=pos)
    logger.info(f"User {call.from_user.id}: selected position {pos}")
    try:
        await call.message.delete()
    except TelegramBadRequest:
        logger.debug("❌ Не удалось удалить старое сообщение перед вводом текста")

    prompt = await call.message.answer('📝 Напишите текст, используя кириллицу:')
    await state.update_data(text_prompt_msg_id=prompt.message_id)
    await state.set_state(ImageMaker.entering_text)
    await call.answer()


# ——————————————————————
# Обработка ввода текста открытки
# ——————————————————————
@router.message(ImageMaker.entering_text, F.text)
async def handle_text(message: Message, state: FSMContext):
    """Обрабатывает введенный текст и отправляет превью открытки."""
    if await validate_text(message, state):
        await send_image_preview(message, state, size_correction=0)


# ——————————————————————
# Создание и отправка превью открытки
# ——————————————————————
async def send_image_preview(message: Message, state: FSMContext, size_correction=0, is_resizing=False, user_id: int | None = None):
    """Создает и отправляет превью открытки с текстом."""
    indicator_text = '⚙️ Редактируем размер шрифта…' if is_resizing else '⚙️ Создаём открытку…'
    indicator = await message.answer(indicator_text)

    if user_id is None:
        user_id = message.from_user.id
    data = await state.get_data()
    src = os.path.join(data['image_folder'], data['selected_image'])
    filename = f"final_{message.from_user.id}_{random.randint(1000000,99999999)}.png"
    final_path = os.path.join(config.Output_Folder, filename)

    if await is_subscribed(user_id):
        add_text_to_image(src, data['user_text'], data['selected_font'], data['selected_color'],
                          final_path, position=data['selected_text_position'], size_correction=size_correction)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Текст меньше', callback_data='resize_minus'),
            InlineKeyboardButton(text='Текст больше', callback_data='resize_plus')],
            [InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='main_menu')],
            [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back')],
        ])
        await message.answer_photo(
            photo=FSInputFile(final_path),
            caption='👆 Ваша открытка без водяного знака.\n\n♡ Спасибо за подписку!',
            reply_markup=keyboard
        )
        try:
            await indicator.delete()
        except TelegramBadRequest:
            logger.debug("❌ Не удалось удалить индикатор создания/редактирования открытки")
        return

    add_text_to_image(src, data['user_text'], data['selected_font'], data['selected_color'],
                      final_path, position=data['selected_text_position'], size_correction=size_correction)
    preview_path = os.path.join(config.Output_Folder, f"preview_{filename}")
    add_watermark(final_path, preview_path, watermark_text='Создано в Добрые Открыточки<3')

    if not is_resizing:
        url, pid = await create_payment(message.from_user.id, 100, 'Оплата за открытку')
        await state.update_data(payment_url=url, payment_id=pid)

    await state.update_data(preview_path=preview_path, final_path=final_path, size_correction=size_correction)

    data = await state.get_data()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🛒 Оплатить открытку', url=data['payment_url'])],
        [InlineKeyboardButton(text='💌 Получить открытку', callback_data=f'check_payment:{data['payment_id']}')],
        [InlineKeyboardButton(text='Текст меньше', callback_data='resize_minus'),
         InlineKeyboardButton(text='Текст больше', callback_data='resize_plus')],
        [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back')]
    ])

    await message.answer_photo(photo=FSInputFile(preview_path), caption='📦 Предварительный просмотр',
                               reply_markup=keyboard)
    try:
        await indicator.delete()
    except TelegramBadRequest:
        logger.debug("❌ Не удалось удалить индикатор создания/редактирования открытки")


# ——————————————————————
# Редактирование картинки
# ——————————————————————
@router.callback_query(F.data == 'resize_minus')
async def resize_minus(call: CallbackQuery, state: FSMContext):
    """Уменьшает размер шрифта и обновляет превью (шрифт не меньше минимального)."""
    await call.answer()
    data = await state.get_data()

    src = os.path.join(data['image_folder'], data['selected_image'])
    image = Image.open(src)
    if image.width < 2000:
        base_font_size = 72
    else:
        base_font_size = 120

    current_correction = data.get('size_correction', 0)
    min_font_size = 52
    new_correction = current_correction - 1
    new_font_size = base_font_size + (new_correction * 20)

    if new_font_size <= min_font_size:
        await call.answer(text='❌ Минимальный размер шрифта — {min_font_size}', show_alert=True)
        return

    await state.update_data(size_correction=new_correction)
    try:
        await call.message.delete()
    except TelegramBadRequest:
        logger.debug("❌ Не удалось удалить старое превью")
    await send_image_preview(call.message, state, size_correction=new_correction, is_resizing=True, user_id=call.from_user.id)


@router.callback_query(F.data == 'resize_plus')
async def resize_plus(call: CallbackQuery, state: FSMContext):
    """Увеличивает размер шрифта и обновляет превью."""
    await call.answer()
    data = await state.get_data()
    new_correction = data.get('size_correction', 0) + 1
    await state.update_data(size_correction=new_correction)
    try:
        await call.message.delete()
    except TelegramBadRequest:
        logger.debug("❌ Не удалось удалить старое превью")
    await send_image_preview(call.message, state, size_correction=new_correction, is_resizing=True, user_id=call.from_user.id)


# ——————————————————————
# Проверка оплаты и финальная отправка открытки
# ——————————————————————
@router.callback_query(F.data.startswith('check_payment:'))
async def check_payment_callback(call: CallbackQuery, state: FSMContext):
    """Проверяет статус оплаты и в том же сообщении вставляет финал без водяного знака"""
    pid = call.data.split(':', 1)[1]
    if await check_payment_status(pid) == 'succeeded':
        data = await state.get_data()
        final_path = data.get('final_path') or data.get('preview_path')
        if not final_path:
            await call.message.answer("❌ Не удалось найти файл открытки — попробуйте заново.")
            return
        media = InputMediaPhoto(
            media=FSInputFile(final_path),
            caption='Вот ваше изображение без водяного знака.\n\n♡ Спасибо за покупку!'
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🏠 Вернуться в главное меню', callback_data='main_menu')]
        ])
        try:
            await call.message.edit_media(media=media, reply_markup=kb)
        except TelegramBadRequest as e:
            logger.error(f"Failed to edit media in check_payment: {e}")
    else:
        await call.answer(text='❌ Платёж не подтверждён', show_alert=True)


# ——————————————————————
# Универсальный возврат «Назад»
# ——————————————————————
@router.callback_query(F.data == 'go_back')
async def go_back(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя к предыдущему шагу в stack'е состояний"""
    current = await state.get_state()
    if current == ImageMaker.choosing_image.state:
        data = await state.get_data()
        old_album_msgs = data.get('last_album_msgs', [])
        keyboard_msg_id = data.get('last_keyboard_msg_id')

        for msg_id in old_album_msgs:
            try:
                await call.bot.delete_message(call.message.chat.id, msg_id)
            except TelegramBadRequest:
                pass
        if keyboard_msg_id:
            try:
                await call.bot.delete_message(call.message.chat.id, keyboard_msg_id)
            except TelegramBadRequest:
                pass
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass

        await create_card(call, state, force_new_message=True)
        await state.set_state(ImageMaker.choosing_category)
    elif current == ImageMaker.choosing_font.state:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            logger.debug("❌ Не удалось удалить сообщение с выбором шрифта")
        await show_images_album(call, state)
        await state.set_state(ImageMaker.choosing_image)
    elif current == ImageMaker.choosing_color.state:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            logger.debug("❌ Не удалось удалить сообщение с выбором цвета")
        await choose_font(call, state)
        await state.set_state(ImageMaker.choosing_font)
    elif current == ImageMaker.choosing_position.state:
        await choose_color(call, state)
        await state.set_state(ImageMaker.choosing_color)
    elif current == ImageMaker.entering_text.state:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            logger.debug("❌ Не удалось удалить сообщение при возврате от ввода текста")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text='Сверху',   callback_data='position_top'),
                InlineKeyboardButton(text='По центру', callback_data='position_center'),
                InlineKeyboardButton(text='Снизу',     callback_data='position_bottom')
            ],
            [InlineKeyboardButton(text='⏎ Назад', callback_data='go_back')]
        ])
        await call.message.answer(text='👇 Укажите, где разместить текст', reply_markup=kb)
        await state.set_state(ImageMaker.choosing_position)
    elif current == ImageMaker.choosing_category.state:
        await state.clear()
        await safe_edit_text(call.message, text=START_TEXT, reply_markup=get_main_menu_kb())
    else:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            logger.debug("❌ Не удалось удалить неизвестное сообщение")
        await create_card(call, state, force_new_message=True)

    await call.answer()


@router.callback_query(F.data == 'main_menu')
async def main_menu(call: CallbackQuery, state: FSMContext):
    """Очищает состояние FSM и возвращает пользователя в главное меню, сохраняя данные оплаты."""
    await state.set_state(None)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        logger.debug("❌ Не удалось удалить клавиатуру у подписчика при возврате в меню")
    await call.message.answer(
        START_TEXT,
        reply_markup=get_main_menu_kb()
    )
    await call.answer()


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_generic_picture(dp: Dispatcher):
    """Регистрирует роутер с обработчиками для создания открыток"""
    dp.include_router(router)
