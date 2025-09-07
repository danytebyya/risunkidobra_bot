from utils.database.db import is_service_active, get_service_status
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

async def check_service_availability(service_name: str) -> tuple[bool, str, InlineKeyboardMarkup]:
    """
    Проверяет доступность сервиса.
    
    Returns:
        tuple: (is_available, message, keyboard)
    """
    is_active = await is_service_active(service_name)
    
    if is_active:
        return True, "", None
    
    # Сервис отключен, получаем сообщение об обслуживании
    status = await get_service_status(service_name)
    maintenance_message = status.get("maintenance_message") if status else None
    
    # Если сообщение не установлено, используем стандартное
    if not maintenance_message:
        maintenance_message = "Сервис временно недоступен. Приносим извинения за неудобства."
    
    # Создаем клавиатуру для возврата в главное меню
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
    ])
    
    return False, maintenance_message, keyboard 