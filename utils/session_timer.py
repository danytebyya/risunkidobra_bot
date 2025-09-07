import asyncio
from typing import Callable, Dict, Optional

# user_id -> asyncio.Task
_session_timers: Dict[int, asyncio.Task] = {}


def start_session_timer(user_id: int, timeout: int, on_timeout: Callable, *args, **kwargs):
    """
    Запускает или перезапускает таймер для пользователя.
    on_timeout — корутина, вызываемая по истечении тайм-аута.
    *args, **kwargs — дополнительные параметры для on_timeout
    """
    cancel_session_timer(user_id)
    task = asyncio.create_task(_timer_task(user_id, timeout, on_timeout, *args, **kwargs))
    _session_timers[user_id] = task


def cancel_session_timer(user_id: int):
    """Отменяет таймер пользователя, если он есть."""
    task = _session_timers.pop(user_id, None)
    if task and not task.done():
        task.cancel()


def is_timer_active(user_id: int) -> bool:
    """Проверяет, есть ли активный таймер для пользователя."""
    task = _session_timers.get(user_id)
    return task is not None and not task.done()


async def _timer_task(user_id: int, timeout: int, on_timeout: Callable, *args, **kwargs):
    try:
        await asyncio.sleep(timeout)
        await on_timeout(user_id, *args, **kwargs)
    except asyncio.CancelledError:
        pass 
    