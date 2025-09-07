import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any
import json
import time

from config import logger
from utils.database.db import (
    get_pending_notifications,
    mark_notification_sent,
    get_all_users,
    get_users_count,
    get_active_users_count,
    get_users_batch,
    get_next_notification_time
)
from utils.bot_instance import bot


async def send_notification_to_user(user_id: int, notification: Dict[str, Any]) -> bool:
    """Отправляет уведомление конкретному пользователю."""
    try:
        text = notification["text"]
        media_files = notification.get("media_files", [])
        
        if media_files:
            # Если есть медиафайлы, отправляем их
            media_group = []
            for i, media_info in enumerate(media_files):
                if media_info["type"] == "photo":
                    from aiogram.types import InputMediaPhoto
                    media = InputMediaPhoto(
                        media=media_info["file_id"],
                        caption=text if i == 0 else media_info.get("caption", ""),
                        parse_mode="HTML"
                    )
                    media_group.append(media)
                elif media_info["type"] == "video":
                    from aiogram.types import InputMediaVideo
                    media = InputMediaVideo(
                        media=media_info["file_id"],
                        caption=text if i == 0 else media_info.get("caption", ""),
                        parse_mode="HTML"
                    )
                    media_group.append(media)
                elif media_info["type"] == "document":
                    from aiogram.types import InputMediaDocument
                    media = InputMediaDocument(
                        media=media_info["file_id"],
                        caption=text if i == 0 else media_info.get("caption", ""),
                        parse_mode="HTML"
                    )
                    media_group.append(media)
            
            if media_group:
                await bot.send_media_group(chat_id=user_id, media=media_group)
                return True
        else:
            # Если нет медиафайлов, отправляем только текст
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML"
            )
            return True
            
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
        return False


async def send_notifications_batch(users_batch: List[Dict], notification: Dict[str, Any]) -> tuple:
    """
    Отправляет уведомления батчу пользователей параллельно.
    
    Args:
        users_batch: Список пользователей для отправки (батч)
        notification: Данные уведомления
        
    Returns:
        tuple: (успешные_отправки, неудачные_отправки)
    """
    successful_sends = 0
    failed_sends = 0
    
    # Создаем задачи для всех пользователей в батче
    tasks = [
        send_notification_to_user(user["user_id"], notification)
        for user in users_batch
    ]
    
    # Отправляем всем пользователям в батче параллельно
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Подсчитываем результаты
    for result in results:
        if isinstance(result, Exception):
            failed_sends += 1
            logger.error(f"Исключение при отправке уведомления: {result}")
        elif result:
            successful_sends += 1
        else:
            failed_sends += 1
    
    return successful_sends, failed_sends


async def send_pending_notifications():
    """Отправляет все ожидающие уведомления с использованием батчей."""
    try:
        notifications = await get_pending_notifications()
        
        if not notifications:
            return
        
        # Получаем количество пользователей для планирования
        total_users = await get_users_count(active_only=False)
        
        if total_users == 0:
            logger.info("Нет пользователей для рассылки уведомлений")
            return
        
        # Настройки батчей
        batch_size = 30  # Оптимальный размер батча для Telegram API
        users_batch_size = 1000  # Размер порции для загрузки пользователей из БД
        
        total_successful_sends = 0
        total_failed_sends = 0
        
        logger.info(f"🚀 Начинаем отправку {len(notifications)} уведомлений")
        logger.info(f"📊 Пользователей: {total_users} всего")
        logger.info(f"📦 Размер батча: {batch_size}, размер порции: {users_batch_size}")
        
        start_time = time.time()
        
        for notification in notifications:
            notification_id = notification["id"]
            notification_successful = 0
            notification_failed = 0
            
            # Логируем время отправки
            scheduled_time = notification.get("scheduled_at")
            if scheduled_time:
                moscow_tz = timezone(timedelta(hours=3))
                moscow_time = scheduled_time.astimezone(moscow_tz)
                logger.info(f"📢 Отправляем уведомление {notification_id} (запланировано на {moscow_time.strftime('%d.%m.%Y %H:%M:%S')} МСК)")
            else:
                logger.info(f"📢 Отправляем уведомление {notification_id} (немедленно)")
            
            # Загружаем пользователей порциями для экономии памяти
            offset = 0
            total_batches_processed = 0
            
            while True:
                # Получаем порцию пользователей
                users_batch = await get_users_batch(
                    limit=users_batch_size, 
                    offset=offset, 
                    active_only=False  # Все пользователи
                )
                
                if not users_batch:
                    break  # Больше пользователей нет
                
                # Отправляем пользователей из этой порции батчами
                for i in range(0, len(users_batch), batch_size):
                    batch = users_batch[i:i + batch_size]
                    total_batches_processed += 1
                    
                    logger.info(f"📦 Батч {total_batches_processed} ({len(batch)} пользователей)")
                    
                    # Отправляем батч
                    successful, failed = await send_notifications_batch(batch, notification)
                    notification_successful += successful
                    notification_failed += failed
                    
                    # Небольшая пауза между батчами (чтобы не перегрузить Telegram API)
                    if i + batch_size < len(users_batch):  # Не делаем паузу после последнего батча в порции
                        await asyncio.sleep(0.1)
                
                offset += users_batch_size
                
                # Логируем прогресс
                if offset % 5000 == 0:  # Каждые 5000 пользователей
                    logger.info(f"📈 Обработано пользователей: {offset}")
            
            # Отмечаем уведомление как отправленное
            await mark_notification_sent(notification_id)
            
            total_successful_sends += notification_successful
            total_failed_sends += notification_failed
            
            logger.info(f"✅ Уведомление {notification_id} завершено: успешно {notification_successful}, ошибок {notification_failed}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"🎉 Отправка завершена за {duration:.2f} секунд")
        logger.info(f"📊 Итого: успешно {total_successful_sends}, ошибок {total_failed_sends}")
        if duration > 0:
            logger.info(f"⚡ Средняя скорость: {total_successful_sends / duration:.1f} сообщений/сек")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомлений: {e}")


# Оставляем старую функцию для совместимости (если где-то используется)
async def send_pending_notifications_old():
    """Старая версия отправки уведомлений (последовательно)."""
    try:
        notifications = await get_pending_notifications()
        
        if not notifications:
            return
        
        users = await get_all_users()
        total_users = len(users)
        successful_sends = 0
        failed_sends = 0
        
        logger.info(f"Начинаем отправку {len(notifications)} уведомлений для {total_users} пользователей")
        
        for notification in notifications:
            notification_id = notification["id"]
            logger.info(f"Отправляем уведомление {notification_id}")
            
            # Отправляем всем пользователям
            for user in users:
                user_id = user["user_id"]
                success = await send_notification_to_user(user_id, notification)
                
                if success:
                    successful_sends += 1
                else:
                    failed_sends += 1
                
                # Небольшая задержка между отправками
                await asyncio.sleep(0.05)
            
            # Отмечаем уведомление как отправленное
            await mark_notification_sent(notification_id)
            logger.info(f"Уведомление {notification_id} отмечено как отправленное")
        
        logger.info(f"Отправка завершена. Успешно: {successful_sends}, Ошибок: {failed_sends}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")


async def notification_scheduler():
    """Планировщик для регулярной проверки и отправки уведомлений."""
    while True:
        try:
            # Отправляем ожидающие уведомления
            await send_pending_notifications()
            
            # Проверяем, есть ли запланированные уведомления в ближайшие 5 минут
            next_check_time = await get_next_notification_time()
            
            if next_check_time:
                # Если есть уведомления в ближайшие 5 минут, проверяем каждую минуту
                await asyncio.sleep(60)
            else:
                # Если нет запланированных уведомлений, проверяем каждые 5 минут
                await asyncio.sleep(300)
                
        except Exception as e:
            logger.error(f"Ошибка в планировщике уведомлений: {e}")
            await asyncio.sleep(60)  # При ошибке проверяем каждую минуту


def start_notification_scheduler():
    """Запускает планировщик уведомлений в отдельной задаче."""
    asyncio.create_task(notification_scheduler())