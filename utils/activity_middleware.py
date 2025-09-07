from typing import Any, Awaitable, Callable, Dict
import asyncio
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from utils.database.db import batch_update_user_activity


class ActivityMiddleware(BaseMiddleware):
    """Middleware для автоматического обновления активности пользователей."""
    
    def __init__(self):
        super().__init__()
        self._update_queue = asyncio.Queue()
        self._background_task = None
    
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Добавляем обновление активности в очередь (не блокируем)
        if hasattr(event, 'from_user') and event.from_user:
            try:
                self._update_queue.put_nowait(event.from_user.id)
            except asyncio.QueueFull:
                # Если очередь переполнена, пропускаем обновление
                pass
        
        # Продолжаем обработку немедленно
        return await handler(event, data)
    
    async def start_background_processor(self):
        """Запускает фоновую обработку обновлений активности."""
        if self._background_task is None or self._background_task.done():
            self._background_task = asyncio.create_task(self._process_updates())
    
    async def _process_updates(self):
        """Фоновая обработка обновлений активности."""
        while True:
            try:
                # Ждем обновления с таймаутом
                user_id = await asyncio.wait_for(self._update_queue.get(), timeout=5.0)
                
                # Обрабатываем пакет обновлений
                user_ids = [user_id]
                
                # Собираем все доступные обновления (максимум 10)
                for _ in range(9):
                    try:
                        user_ids.append(self._update_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                
                # Обновляем активность для всех пользователей одним запросом
                await self._batch_update_activity(user_ids)
                
            except asyncio.TimeoutError:
                # Таймаут - продолжаем цикл
                continue
            except Exception as e:
                # Логируем ошибку и продолжаем (только для критических ошибок)
                if "connection" in str(e).lower() or "database" in str(e).lower():
                    print(f"Критическая ошибка в фоновой обработке активности: {e}")
                continue
    
    async def _batch_update_activity(self, user_ids: list):
        """Пакетное обновление активности пользователей."""
        if not user_ids:
            return
        
        try:
            # Используем оптимизированную пакетную функцию
            await batch_update_user_activity(user_ids)
        except Exception as e:
            # Логируем только критические ошибки
            if "connection" in str(e).lower() or "database" in str(e).lower():
                print(f"Критическая ошибка при пакетном обновлении активности: {e}")
            # Для остальных ошибок просто продолжаем работу
            pass 