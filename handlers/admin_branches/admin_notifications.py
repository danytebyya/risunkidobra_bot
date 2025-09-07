from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from datetime import datetime, timezone, timedelta
import re
import json
import asyncio

from config import ADMIN_IDS, logger
from utils.utils import safe_answer_callback
from utils.database.db import (
    create_notification, 
    get_all_users, 
    get_active_users_count,
    get_notifications_history,
    mark_notification_sent,
    get_users_count
)

router = Router()

# Константы для текстов сообщений
MEDIA_INSTRUCTION_TEXT = (
    "📎 Теперь отправьте медиафайлы (фото, видео, документы):\n\n"
    "💡 Вы можете отправить несколько файлов\n"
    "📝 Первый файл будет с подписью (текстом уведомления)\n"
    "⏭️ Или нажмите 'Пропустить' если медиафайлы не нужны"
)

TEXT_INSTRUCTION_TEXT = (
    "📝 Введите текст уведомления:\n\n"
    "💡 Вы можете использовать HTML-разметку:\n"
    "• <b>жирный текст</b>\n"
    "• <i>курсив</i>\n"
    "• <code>моноширинный</code>\n"
    "• <a href='ссылка'>ссылка</a>"
)


class NotificationStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_media = State()
    waiting_for_schedule = State()
    confirm_send = State()


def get_notifications_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Отправить уведомление", callback_data="admin_send_notification")],
        [InlineKeyboardButton(text="📋 История уведомлений", callback_data="admin_notifications_history")],
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="admin_users_stats")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_back")],
    ])


def get_schedule_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить сейчас", callback_data="schedule_now")],
        [InlineKeyboardButton(text="⏰ Запланировать время", callback_data="schedule_later")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_media")],
    ])


def get_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_send")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_schedule")],
    ])


@router.callback_query(F.data == "admin_notifications")
async def admin_notifications_menu(call: CallbackQuery, state: FSMContext):
    """Показывает меню управления уведомлениями."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    if isinstance(call.message, Message):
        await call.message.edit_text(
            "📢 Управление уведомлениями. Выберите действие:",
            reply_markup=get_notifications_menu_kb()
        )


@router.callback_query(F.data == "admin_send_notification")
async def start_notification_creation(call: CallbackQuery, state: FSMContext):
    """Начинает процесс создания уведомления."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    await state.set_state(NotificationStates.waiting_for_text)
    
    if isinstance(call.message, Message):
        sent_message = await call.message.edit_text(
            TEXT_INSTRUCTION_TEXT,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_notifications")]
            ])
        )
        # Сохраняем ID сообщения с инструкциями
        await state.update_data(instruction_message_id=sent_message.message_id)


@router.message(NotificationStates.waiting_for_text)
async def handle_notification_text(message: Message, state: FSMContext):
    """Обрабатывает введенный текст уведомления."""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Сохраняем текст
    await state.update_data(notification_text=message.text)
    
    # Удаляем сообщение с текстом
    try:
        await message.delete()
    except:
        pass
    
    # Удаляем сообщение с инструкциями (если есть)
    data = await state.get_data()
    instruction_message_id = data.get("instruction_message_id")
    if instruction_message_id:
        try:
            await message.bot.delete_message(message.chat.id, instruction_message_id)
        except:
            pass
    
    # Переходим к вводу медиа
    await state.set_state(NotificationStates.waiting_for_media)
    
    # Отправляем новое сообщение и сохраняем его ID
    sent_message = await message.answer(
        MEDIA_INSTRUCTION_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_media")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")]
        ])
    )
    # Сохраняем ID сообщения с инструкциями о медиа
    await state.update_data(media_instruction_message_id=sent_message.message_id)


@router.message(NotificationStates.waiting_for_media)
async def handle_notification_media(message: Message, state: FSMContext):
    """Обрабатывает медиафайлы для уведомления."""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    media_files = data.get("media_files", [])
    
    # Получаем информацию о файле
    file_info = None
    if message.photo:
        file_info = {
            "type": "photo",
            "file_id": message.photo[-1].file_id,
            "caption": message.caption
        }
    elif message.video:
        file_info = {
            "type": "video",
            "file_id": message.video.file_id,
            "caption": message.caption
        }
    elif message.document:
        file_info = {
            "type": "document",
            "file_id": message.document.file_id,
            "caption": message.caption
        }
    
    if file_info:
        media_files.append(file_info)
        await state.update_data(media_files=media_files)
        

        
        # НЕ удаляем сообщение с медиа от пользователя
        
        # Удаляем сообщение с выбором времени (если есть)
        schedule_message_id = data.get("schedule_message_id")
        if schedule_message_id:
            try:
                await message.bot.delete_message(message.chat.id, schedule_message_id)
            except:
                pass
        
        # Проверяем, является ли это частью медиагруппы (альбома)
        is_media_group = hasattr(message, 'media_group_id') and message.media_group_id is not None
        
        if is_media_group:
            # Если это часть альбома, используем отложенную обработку
            media_group_id = message.media_group_id
            
            # Проверяем, есть ли уже задача для этой медиагруппы
            pending_tasks = data.get("pending_media_group_tasks", {})
            
            if media_group_id not in pending_tasks:
                # Создаем новую задачу для обработки этой медиагруппы
                task = asyncio.create_task(process_media_group_delayed(message, state, media_group_id))
                pending_tasks[media_group_id] = task
                await state.update_data(pending_media_group_tasks=pending_tasks)
        else:
            # Если это одиночный файл, обрабатываем сразу
            await update_media_info_message(message, state, media_files)


async def process_media_group_delayed(message: Message, state: FSMContext, media_group_id: str):
    """Обрабатывает медиагруппу с задержкой для сбора всех файлов."""
    try:
        # Ждем 2 секунды для сбора всех файлов из альбома
        await asyncio.sleep(2.0)
        
        # Получаем актуальные данные
        data = await state.get_data()
        media_files = data.get("media_files", [])
        
        # Проверяем, было ли уже создано сообщение для этой медиагруппы
        processed_groups = data.get("processed_media_groups", set())
        
        if media_group_id not in processed_groups:
            # Помечаем эту медиагруппу как обработанную
            processed_groups.add(media_group_id)
            await state.update_data(processed_media_groups=processed_groups)
            
            # Обновляем сообщение с информацией о медиа
            await update_media_info_message(message, state, media_files)
        
        # Удаляем задачу из списка ожидающих
        pending_tasks = data.get("pending_media_group_tasks", {})
        if media_group_id in pending_tasks:
            del pending_tasks[media_group_id]
            await state.update_data(pending_media_group_tasks=pending_tasks)
    
    except asyncio.CancelledError:
        # Задача была отменена, ничего не делаем
        pass
    except Exception as e:
        logger.error(f"Ошибка при обработке медиагруппы {media_group_id}: {e}")
        # Удаляем задачу из списка ожидающих даже при ошибке
        try:
            data = await state.get_data()
            pending_tasks = data.get("pending_media_group_tasks", {})
            if media_group_id in pending_tasks:
                del pending_tasks[media_group_id]
                await state.update_data(pending_media_group_tasks=pending_tasks)
        except:
            pass


async def update_media_info_message(message: Message, state: FSMContext, media_files: list):
    """Обновляет сообщение с информацией о медиафайлах."""
    try:
        # Удаляем предыдущее сообщение с информацией о медиа (если есть)
        data = await state.get_data()
        media_info_message_id = data.get("media_info_message_id")
        if media_info_message_id:
            try:
                await message.bot.delete_message(message.chat.id, media_info_message_id)
            except:
                pass
        
        # Создаем новое сообщение с информацией о медиа
        if len(media_files) > 1:
            message_text = f"📎 Альбом добавлен! Всего файлов: {len(media_files)}"
        else:
            message_text = f"📎 Медиафайл добавлен! Всего файлов: {len(media_files)}"
        
        message_text += "\n\nОтправьте еще файлы или нажмите 'Продолжить':"
        
        # Создаем клавиатуру с опцией очистки медиафайлов
        keyboard = [
            [InlineKeyboardButton(text="⏭️ Продолжить", callback_data="skip_media")]
        ]
        
        # Добавляем кнопку очистки только если есть медиафайлы
        if len(media_files) > 0:
            keyboard.append([InlineKeyboardButton(text="🗑️ Очистить медиафайлы", callback_data="clear_media")])
        
        keyboard.append([InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")])
        
        sent_message = await message.answer(
            message_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.update_data(media_info_message_id=sent_message.message_id)
    
    except Exception as e:
        pass


@router.callback_query(F.data == "clear_media")
async def clear_media_files(call: CallbackQuery, state: FSMContext):
    """Очищает все медиафайлы."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    # Отменяем все ожидающие задачи обработки медиагрупп
    data = await state.get_data()
    pending_tasks = data.get("pending_media_group_tasks", {})
    for task in pending_tasks.values():
        if not task.done():
            task.cancel()
    
    # Очищаем медиафайлы
    await state.update_data(media_files=[])
    
    # Удаляем сообщение с информацией о медиа (если есть)
    media_info_message_id = data.get("media_info_message_id")
    if media_info_message_id and isinstance(call.message, Message):
        try:
            await call.message.bot.delete_message(call.message.chat.id, media_info_message_id)
        except:
            pass
    
    # Показываем сообщение об очистке
    if isinstance(call.message, Message):
        try:
            sent_message = await call.message.edit_text(
                "🗑️ Все медиафайлы очищены!\n\n"
                "Отправьте новые файлы или нажмите 'Продолжить':",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏭️ Продолжить", callback_data="skip_media")],
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")]
                ])
            )
            await state.update_data(media_info_message_id=sent_message.message_id)
        except Exception as e:
            sent_message = await call.message.answer(
                "🗑️ Все медиафайлы очищены!\n\n"
                "Отправьте новые файлы или нажмите 'Продолжить':",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏭️ Продолжить", callback_data="skip_media")],
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")]
                ])
            )
            await state.update_data(media_info_message_id=sent_message.message_id)


@router.callback_query(F.data == "skip_media")
async def skip_media(call: CallbackQuery, state: FSMContext):
    """Пропускает добавление медиа и переходит к планированию."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    # Ждем завершения всех ожидающих задач обработки медиагрупп
    data = await state.get_data()
    pending_tasks = data.get("pending_media_group_tasks", {})
    
    if pending_tasks:
        # Ждем завершения всех задач (максимум 3 секунды)
        try:
            await asyncio.wait_for(
                asyncio.gather(*[task for task in pending_tasks.values() if not task.done()], return_exceptions=True),
                timeout=3.0
            )
        except asyncio.TimeoutError:
            # Если задачи не завершились за 3 секунды, отменяем их
            for task in pending_tasks.values():
                if not task.done():
                    task.cancel()
    
    # Получаем финальные данные после завершения всех задач
    final_data = await state.get_data()
    media_files = final_data.get("media_files", [])
    
    # Удаляем сообщение с информацией о медиа (если есть)
    media_info_message_id = final_data.get("media_info_message_id")
    if media_info_message_id and isinstance(call.message, Message):
        try:
            await call.message.bot.delete_message(call.message.chat.id, media_info_message_id)
        except:
            pass
    
    # Удаляем сообщение с инструкциями о медиа (если есть)
    media_instruction_message_id = final_data.get("media_instruction_message_id")
    if media_instruction_message_id and isinstance(call.message, Message):
        try:
            await call.message.bot.delete_message(call.message.chat.id, media_instruction_message_id)
        except:
            pass
    

    
    await state.set_state(NotificationStates.waiting_for_schedule)
    
    if isinstance(call.message, Message):
        try:
            sent_message = await call.message.edit_text(
                "⏰ Выберите время отправки:",
                reply_markup=get_schedule_kb()
            )
            # Сохраняем ID сообщения с выбором времени
            await state.update_data(schedule_message_id=sent_message.message_id)
        except Exception as e:
            # Если не удалось отредактировать, отправляем новое сообщение
            sent_message = await call.message.answer(
                "⏰ Выберите время отправки:",
                reply_markup=get_schedule_kb()
            )
            # Сохраняем ID сообщения с выбором времени
            await state.update_data(schedule_message_id=sent_message.message_id)





@router.callback_query(F.data == "schedule_now")
async def schedule_now(call: CallbackQuery, state: FSMContext):
    """Планирует отправку уведомления сейчас."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    await state.update_data(scheduled_at=None)
    
    # Удаляем сообщение с выбором времени
    if isinstance(call.message, Message):
        try:
            await call.message.delete()
        except:
            pass
    
    await show_confirmation(call, state)


@router.callback_query(F.data == "schedule_later")
async def schedule_later(call: CallbackQuery, state: FSMContext):
    """Запрашивает время для планирования."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    if isinstance(call.message, Message):
        # Сохраняем ID сообщения с выбором времени для последующего удаления
        await state.update_data(schedule_message_id=call.message.message_id)
        
        try:
            sent_message = await call.message.edit_text(
                "⏰ Введите время отправки в формате:\n\n"
                "• <b>13:40</b> - сегодня в указанное время\n"
                "• <b>25.12 13:40</b> - в указанную дату и время\n"
                "• <b>2024-12-25 13:40</b> - полная дата\n\n"
                "Время указывается в московском часовом поясе (UTC+3).",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_schedule")]
                ])
            )
            # Сохраняем ID сообщения с инструкциями
            await state.update_data(schedule_instruction_message_id=sent_message.message_id)
        except Exception as e:
            # Если не удалось отредактировать, отправляем новое сообщение
            sent_message = await call.message.answer(
                "⏰ Введите время отправки в формате:\n\n"
                "• <b>13:40</b> - сегодня в указанное время\n"
                "• <b>25.12 13:40</b> - в указанную дату и время\n"
                "• <b>2024-12-25 13:40</b> - полная дата\n\n"
                "Время указывается в московском часовом поясе (UTC+3).",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_schedule")]
                ])
            )
            # Сохраняем ID сообщения с инструкциями
            await state.update_data(schedule_instruction_message_id=sent_message.message_id)


@router.callback_query(F.data.startswith("back_to_"))
async def handle_back_navigation(call: CallbackQuery, state: FSMContext):
    """Универсальный обработчик навигации назад."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    # Получаем текущее состояние и данные
    current_state = await state.get_state()
    data = await state.get_data()
    
    # Определяем, куда возвращаться на основе callback_data
    back_target = call.data.replace("back_to_", "")
    
    if back_target == "text":
        # Отменяем все ожидающие задачи обработки медиагрупп
        pending_tasks = data.get("pending_media_group_tasks", {})
        for task in pending_tasks.values():
            if not task.done():
                task.cancel()
        
        # Удаляем сообщение с информацией о медиа (если есть)
        media_info_message_id = data.get("media_info_message_id")
        if media_info_message_id and isinstance(call.message, Message):
            try:
                await call.message.bot.delete_message(call.message.chat.id, media_info_message_id)
            except:
                pass
        
        # Удаляем сообщение с инструкциями о медиа (если есть)
        media_instruction_message_id = data.get("media_instruction_message_id")
        if media_instruction_message_id and isinstance(call.message, Message):
            try:
                await call.message.bot.delete_message(call.message.chat.id, media_instruction_message_id)
            except:
                pass
        
        # Удаляем сообщение с выбором времени (если есть)
        schedule_message_id = data.get("schedule_message_id")
        if schedule_message_id and isinstance(call.message, Message):
            try:
                await call.message.bot.delete_message(call.message.chat.id, schedule_message_id)
            except:
                pass
        
        # Очищаем медиафайлы при возврате к тексту
        await state.update_data(media_files=[])
        
        await state.set_state(NotificationStates.waiting_for_text)
        
        if isinstance(call.message, Message):
            try:
                sent_message = await call.message.edit_text(
                    TEXT_INSTRUCTION_TEXT,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_notifications")]
                    ])
                )
                # Сохраняем ID сообщения с инструкциями
                await state.update_data(instruction_message_id=sent_message.message_id)
            except Exception as e:
                # Если не удалось отредактировать, отправляем новое сообщение
                sent_message = await call.message.answer(
                    TEXT_INSTRUCTION_TEXT,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_notifications")]
                    ])
                )
                # Сохраняем ID сообщения с инструкциями
                await state.update_data(instruction_message_id=sent_message.message_id)
    
    elif back_target == "schedule":
        # Удаляем сообщение предпросмотра (если есть)
        preview_message_id = data.get("preview_message_id")
        if preview_message_id and isinstance(call.message, Message):
            try:
                await call.message.bot.delete_message(call.message.chat.id, preview_message_id)
            except:
                pass
        
        # Удаляем медиагруппу (если есть) - это исправляет проблему 2
        media_group_message_ids = data.get("media_group_message_ids", [])
        if media_group_message_ids and isinstance(call.message, Message):
            for msg_id in media_group_message_ids:
                try:
                    await call.message.bot.delete_message(call.message.chat.id, msg_id)
                except:
                    pass
        
        # Удаляем инструкционное сообщение (если есть)
        schedule_instruction_message_id = data.get("schedule_instruction_message_id")
        if schedule_instruction_message_id and isinstance(call.message, Message):
            try:
                await call.message.bot.delete_message(call.message.chat.id, schedule_instruction_message_id)
            except:
                pass
        
        # Возвращаемся к выбору времени
        await state.set_state(NotificationStates.waiting_for_schedule)
        
        if isinstance(call.message, Message):
            try:
                sent_message = await call.message.edit_text(
                    "⏰ Выберите время отправки:",
                    reply_markup=get_schedule_kb()
                )
                # Сохраняем ID сообщения с выбором времени
                await state.update_data(schedule_message_id=sent_message.message_id)
            except Exception as e:
                sent_message = await call.message.answer(
                    "⏰ Выберите время отправки:",
                    reply_markup=get_schedule_kb()
                )
                await state.update_data(schedule_message_id=sent_message.message_id)
    
    elif back_target == "media":
        # Удаляем сообщение с выбором времени (если есть)
        schedule_message_id = data.get("schedule_message_id")
        if schedule_message_id and isinstance(call.message, Message):
            try:
                await call.message.bot.delete_message(call.message.chat.id, schedule_message_id)
            except:
                pass
        
        # НЕ очищаем медиафайлы при возврате к медиафайлам - пользователь может хотеть добавить еще
        # Возвращаемся к добавлению медиафайлов
        await state.set_state(NotificationStates.waiting_for_media)
        
        if isinstance(call.message, Message):
            # Проверяем, есть ли уже добавленные медиафайлы
            media_files = data.get("media_files", [])
            
            if media_files:
                # Если есть медиафайлы, показываем информацию о них
                try:
                    # Создаем клавиатуру с опцией очистки медиафайлов
                    keyboard = [
                        [InlineKeyboardButton(text="⏭️ Продолжить", callback_data="skip_media")]
                    ]
                    
                    # Добавляем кнопку очистки только если есть медиафайлы
                    if len(media_files) > 0:
                        keyboard.append([InlineKeyboardButton(text="🗑️ Очистить медиафайлы", callback_data="clear_media")])
                    
                    keyboard.append([InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")])
                    
                    sent_message = await call.message.edit_text(
                        f"📎 Уже добавлено файлов: {len(media_files)}\n\n"
                        "Отправьте еще файлы или нажмите 'Продолжить':",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                    )
                    # Сохраняем ID сообщения с информацией о медиа
                    await state.update_data(media_info_message_id=sent_message.message_id)
                except Exception as e:
                    # Создаем клавиатуру с опцией очистки медиафайлов
                    keyboard = [
                        [InlineKeyboardButton(text="⏭️ Продолжить", callback_data="skip_media")]
                    ]
                    
                    # Добавляем кнопку очистки только если есть медиафайлы
                    if len(media_files) > 0:
                        keyboard.append([InlineKeyboardButton(text="🗑️ Очистить медиафайлы", callback_data="clear_media")])
                    
                    keyboard.append([InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")])
                    
                    sent_message = await call.message.answer(
                        f"📎 Уже добавлено файлов: {len(media_files)}\n\n"
                        "Отправьте еще файлы или нажмите 'Продолжить':",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                    )
                    await state.update_data(media_info_message_id=sent_message.message_id)
            else:
                # Если нет медиафайлов, показываем стандартные инструкции
                try:
                    sent_message = await call.message.edit_text(
                        MEDIA_INSTRUCTION_TEXT,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_media")],
                            [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")]
                        ])
                    )
                    # Сохраняем ID сообщения с инструкциями
                    await state.update_data(media_instruction_message_id=sent_message.message_id)
                except Exception as e:
                    sent_message = await call.message.answer(
                        MEDIA_INSTRUCTION_TEXT,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_media")],
                            [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_text")]
                        ])
                    )
                    await state.update_data(media_instruction_message_id=sent_message.message_id)
    
    else:
        # Если неизвестная цель, возвращаемся в главное меню уведомлений
        await state.clear()
        if isinstance(call.message, Message):
            await call.message.edit_text(
                "📢 Управление уведомлениями. Выберите действие:",
                reply_markup=get_notifications_menu_kb()
            )


@router.message(NotificationStates.waiting_for_schedule)
async def handle_schedule_time(message: Message, state: FSMContext):
    """Обрабатывает введенное время для планирования."""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    time_text = message.text.strip()
    
    # Парсим время
    scheduled_at = None
    try:
        # Формат "13:40" - сегодня в указанное время
        if re.match(r'^\d{1,2}:\d{2}$', time_text):
            hour, minute = map(int, time_text.split(':'))
            # Создаем время в московском часовом поясе (UTC+3)
            moscow_tz = timezone(timedelta(hours=3))
            now = datetime.now(moscow_tz)
            scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # Если время уже прошло, планируем на завтра
            if scheduled_at <= now:
                scheduled_at = scheduled_at + timedelta(days=1)
            # Конвертируем в UTC для хранения в базе
            scheduled_at = scheduled_at.astimezone(timezone.utc)
        
        # Формат "25.12 13:40" - день.месяц время
        elif re.match(r'^\d{1,2}\.\d{1,2}\s+\d{1,2}:\d{2}$', time_text):
            date_part, time_part = time_text.split()
            day, month = map(int, date_part.split('.'))
            hour, minute = map(int, time_part.split(':'))
            moscow_tz = timezone(timedelta(hours=3))
            now = datetime.now(moscow_tz)
            year = now.year
            # Если дата уже прошла в этом году, планируем на следующий год
            if month < now.month or (month == now.month and day < now.day):
                year += 1
            scheduled_at = datetime(year, month, day, hour, minute, tzinfo=moscow_tz)
            # Конвертируем в UTC для хранения в базе
            scheduled_at = scheduled_at.astimezone(timezone.utc)
        
        # Формат "2024-12-25 13:40" - полная дата
        elif re.match(r'^\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}$', time_text):
            date_part, time_part = time_text.split()
            year, month, day = map(int, date_part.split('-'))
            hour, minute = map(int, time_part.split(':'))
            moscow_tz = timezone(timedelta(hours=3))
            scheduled_at = datetime(year, month, day, hour, minute, tzinfo=moscow_tz)
            # Конвертируем в UTC для хранения в базе
            scheduled_at = scheduled_at.astimezone(timezone.utc)
        
        else:
            raise ValueError("Неверный формат времени")
        
        await state.update_data(scheduled_at=scheduled_at)
        
        # Удаляем сообщение с временем
        try:
            await message.delete()
        except:
            pass
        
        # Удаляем инструкционное сообщение
        data = await state.get_data()
        schedule_instruction_message_id = data.get("schedule_instruction_message_id")
        if schedule_instruction_message_id:
            try:
                await message.bot.delete_message(message.chat.id, schedule_instruction_message_id)
            except:
                pass
        
        # Удаляем сообщение с выбором времени (если есть)
        schedule_message_id = data.get("schedule_message_id")
        if schedule_message_id:
            try:
                await message.bot.delete_message(message.chat.id, schedule_message_id)
            except:
                pass
        
        await show_confirmation(message, state)
        
    except Exception as e:
        # Удаляем инструкционное сообщение при ошибке
        data = await state.get_data()
        schedule_instruction_message_id = data.get("schedule_instruction_message_id")
        if schedule_instruction_message_id:
            try:
                await message.bot.delete_message(message.chat.id, schedule_instruction_message_id)
            except:
                pass
        
        await message.answer(
            f"❌ Ошибка в формате времени: {str(e)}\n\n"
            "Попробуйте еще раз или нажмите 'Назад':",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="back_to_schedule")]
            ])
        )


async def show_confirmation(message_or_call, state: FSMContext):
    """Показывает предварительный просмотр уведомления для подтверждения."""
    data = await state.get_data()
    text = data.get("notification_text", "")
    media_files = data.get("media_files", [])
    scheduled_at = data.get("scheduled_at")
    
    # Формируем текст предварительного просмотра
    preview_text = f"📢 <b>Предварительный просмотр уведомления:</b>\n\n{text}\n\n"
    
    if media_files:
        preview_text += f"📎 Прикреплено файлов: {len(media_files)}\n"
        # Показываем информацию о каждом файле
        for i, media in enumerate(media_files, 1):
            media_type = media.get("type", "неизвестно")
            caption = media.get("caption", "")
            preview_text += f"   {i}. {media_type.upper()}"
            if caption:
                preview_text += f" (с подписью: {caption[:30]}{'...' if len(caption) > 30 else ''})"
            preview_text += "\n"
    
    if scheduled_at:
        # Конвертируем обратно в московское время для отображения
        moscow_tz = timezone(timedelta(hours=3))
        moscow_time = scheduled_at.astimezone(moscow_tz)
        preview_text += f"\n⏰ Запланировано на: {moscow_time.strftime('%d.%m.%Y %H:%M')} (МСК)"
        preview_text += f"\n📅 Точность: ±1 минута (умная проверка)"
    else:
        preview_text += "\n🚀 Отправка: немедленно"
    
    await state.set_state(NotificationStates.confirm_send)
    
    if isinstance(message_or_call, Message):
        # Если есть медиафайлы, отправляем их с предпросмотром
        if media_files:
            await send_media_preview(message_or_call, media_files, preview_text, state)
        else:
            sent_message = await message_or_call.answer(preview_text, parse_mode="HTML", reply_markup=get_confirm_kb())
            # Сохраняем ID сообщения предпросмотра
            await state.update_data(preview_message_id=sent_message.message_id)
    else:
        if isinstance(message_or_call.message, Message):
            # Если есть медиафайлы, отправляем их с предпросмотром
            if media_files:
                await send_media_preview(message_or_call.message, media_files, preview_text, state)
            else:
                await message_or_call.message.edit_text(preview_text, parse_mode="HTML", reply_markup=get_confirm_kb())
                # Сохраняем ID сообщения предпросмотра
                await state.update_data(preview_message_id=message_or_call.message.message_id)


async def send_media_preview(message_or_call, media_files, preview_text, state: FSMContext = None):
    """Отправляет предпросмотр с медиафайлами."""
    from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument
    
    media_group = []
    
    for i, media_info in enumerate(media_files):
        if media_info["type"] == "photo":
            media = InputMediaPhoto(
                media=media_info["file_id"],
                caption=preview_text if i == 0 else media_info.get("caption", ""),
                parse_mode="HTML"
            )
            media_group.append(media)
        elif media_info["type"] == "video":
            media = InputMediaVideo(
                media=media_info["file_id"],
                caption=preview_text if i == 0 else media_info.get("caption", ""),
                parse_mode="HTML"
            )
            media_group.append(media)
        elif media_info["type"] == "document":
            media = InputMediaDocument(
                media=media_info["file_id"],
                caption=preview_text if i == 0 else media_info.get("caption", ""),
                parse_mode="HTML"
            )
            media_group.append(media)
    
    if media_group:
        # Отправляем медиагруппу
        media_messages = await message_or_call.bot.send_media_group(
            chat_id=message_or_call.chat.id,
            media=media_group
        )
        # Сохраняем ID всех сообщений медиагруппы для последующего удаления
        if state:
            media_message_ids = [msg.message_id for msg in media_messages]
            await state.update_data(media_group_message_ids=media_message_ids)
        
        # Отправляем кнопки подтверждения отдельным сообщением
        sent_message = await message_or_call.answer(
            "Подтвердите отправку уведомления:",
            reply_markup=get_confirm_kb()
        )
        # Сохраняем ID сообщения предпросмотра
        if state:
            await state.update_data(preview_message_id=sent_message.message_id)


@router.callback_query(F.data == "confirm_send")
async def confirm_send_notification(call: CallbackQuery, state: FSMContext):
    """Подтверждает отправку уведомления."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    data = await state.get_data()
    text = data.get("notification_text", "")
    media_files = data.get("media_files", [])
    scheduled_at = data.get("scheduled_at")
    
    try:
        # Создаем уведомление в базе данных
        notification_id = await create_notification(
            text=text,
            media_files=media_files,
            scheduled_at=scheduled_at,
            created_by=call.from_user.id
        )
        
        if notification_id:
            # Получаем статистику пользователей
            total_users = await get_users_count(active_only=False)
            
            # Рассчитываем статистику батчей
            batch_size = 30
            total_batches = (total_users + batch_size - 1) // batch_size
            estimated_time = total_batches * 0.1  # 0.1 сек на батч
            
            success_text = (
                f"✅ Уведомление успешно создано!\n\n"
                f"📊 Будет отправлено {total_users} пользователям\n"
                f"🆔 ID уведомления: {notification_id}\n\n"
                f"🚀 <b>Система батчей:</b>\n"
                f"📦 Батчей для отправки: {total_batches}\n"
                f"⏱️ Примерное время: ~{estimated_time:.1f} сек\n"
                f"⚡ Скорость: ~{batch_size/0.1:.0f} сообщений/сек\n"
                f"📅 Точность времени: ±1 минута (умная проверка)"
            )
            
            if scheduled_at:
                # Конвертируем обратно в московское время для отображения
                moscow_tz = timezone(timedelta(hours=3))
                moscow_time = scheduled_at.astimezone(moscow_tz)
                success_text += f"\n⏰ Запланировано на: {moscow_time.strftime('%d.%m.%Y %H:%M')} (МСК)"
                success_text += f"\n📅 Точность: ±1 минута (умная проверка)"
            else:
                success_text += "\n🚀 Отправка: немедленно"
        else:
            success_text = "❌ Ошибка при создании уведомления"
        
        # Отменяем все ожидающие задачи обработки медиагрупп перед очисткой состояния
        pending_tasks = data.get("pending_media_group_tasks", {})
        for task in pending_tasks.values():
            if not task.done():
                task.cancel()
        
        await state.clear()
        
        if isinstance(call.message, Message):
            await call.message.edit_text(success_text, parse_mode="HTML")
            await call.message.answer(
                "🔧 Пункт администрирования:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Управление данными", callback_data="admin_data_management")],
                    [InlineKeyboardButton(text="👤 Управление подписками", callback_data="admin_subscriptions")],
                    [InlineKeyboardButton(text="🔧 Управление сервисами", callback_data="admin_services")],
                    [InlineKeyboardButton(text="📢 Уведомления", callback_data="admin_notifications")],
                    [InlineKeyboardButton(text="🔄 Импортировать данные", callback_data="admin_sync")],
                ])
            )
        
    except Exception as e:
        logger.error(f"Ошибка при создании уведомления: {e}")
        await call.answer("❌ Ошибка при создании уведомления", show_alert=True)


@router.callback_query(F.data == "admin_users_stats")
async def show_users_stats(call: CallbackQuery, state: FSMContext):
    """Показывает статистику пользователей."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    try:
        total_users = await get_users_count(active_only=False)
        active_users = await get_active_users_count()
        
        # Рассчитываем статистику рассылки
        batch_size = 30
        total_batches = (total_users + batch_size - 1) // batch_size
        
        # Примерное время рассылки (в секундах)
        estimated_time = total_batches * 0.1  # 0.1 сек на батч
        
        stats_text = (
            f"📊 <b>Статистика пользователей:</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🟢 Активных (30 дней): {active_users}\n"
            f"📈 Активность: {(active_users/total_users*100):.1f}%" if total_users > 0 else "📈 Активность: 0%\n\n"
            f"🚀 <b>Система рассылки:</b>\n"
            f"📦 Размер батча: {batch_size} пользователей\n"
            f"📊 Всего батчей: {total_batches}\n"
            f"⏱️ Время рассылки: ~{estimated_time:.1f} сек\n"
            f"⚡ Скорость: ~{batch_size/0.1:.0f} сообщений/сек\n"
            f"📅 Точность времени: ±1 минута (умная проверка)"
        )
        
        if isinstance(call.message, Message):
            await call.message.edit_text(
                stats_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_notifications")]
                ])
            )
    
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await call.answer("❌ Ошибка при получении статистики", show_alert=True)


@router.callback_query(F.data == "admin_notifications_history")
async def show_notifications_history(call: CallbackQuery, state: FSMContext):
    """Показывает историю уведомлений."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    try:
        notifications = await get_notifications_history(limit=10)
        
        if not notifications:
            history_text = "📋 История уведомлений пуста"
        else:
            history_text = "📋 <b>Последние уведомления:</b>\n\n"
            for notif in notifications:
                status = "✅ Отправлено" if notif["is_sent"] else "⏳ Ожидает"
                created = notif["created_at"].strftime("%d.%m %H:%M")
                history_text += f"🆔 {notif['id']} | {status} | {created}\n"
                history_text += f"📝 {notif['text'][:50]}{'...' if len(notif['text']) > 50 else ''}\n\n"
        
        if isinstance(call.message, Message):
            await call.message.edit_text(
                history_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_notifications")]
                ])
            )
    
    except Exception as e:
        logger.error(f"Ошибка при получении истории: {e}")
        await call.answer("❌ Ошибка при получении истории", show_alert=True)



def register_notifications_handlers(dp):
    """Регистрирует обработчики уведомлений."""
    dp.include_router(router) 