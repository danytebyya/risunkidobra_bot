import asyncio
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.database.db import get_service_status, set_service_status, get_all_services_status, is_service_active
from config import ADMIN_IDS, logger
from utils.utils import safe_answer_callback

router = Router()

class ServiceManagementStates(StatesGroup):
    waiting_for_maintenance_message = State()

# Список всех сервисов
SERVICES = {
    "create_card": "🖼️ Персональная открытка",
    "congrats": "💌 Теплое поздравление",
    "psychologist_advice": "💬 Совет от психолога", 
    "ideas": "💡 Идеи для чего угодно",
    "goal_checklist": "📋 Чек-лист достижения цели",
    "future_letter": "⏳ Письмо в будущее",
    "quote_of_day": "📜 Цитата дня",
    "shop": "🛒 Магазин"
}

def get_services_menu_kb() -> InlineKeyboardMarkup:
    """Создает клавиатуру для меню управления сервисами."""
    keyboard = []
    for service_id, service_name in SERVICES.items():
        keyboard.append([InlineKeyboardButton(
            text=f"{service_name}", 
            callback_data=f"service_toggle:{service_id}"
        )])
    keyboard.append([InlineKeyboardButton(text="⏎ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_service_status_kb(service_id: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для управления конкретным сервисом."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Включить сервис", callback_data=f"service_enable:{service_id}")],
        [InlineKeyboardButton(text="🔴 Отключить сервис", callback_data=f"service_disable:{service_id}")],
        [InlineKeyboardButton(text="✏️ Изменить сообщение", callback_data=f"service_message:{service_id}")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_services")]
    ])

@router.callback_query(F.data == "admin_services")
async def admin_services_menu(call: CallbackQuery, state: FSMContext):
    """Показывает меню управления сервисами."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    await safe_answer_callback(call, state)
    
    # Получаем статус всех сервисов
    services_status = await get_all_services_status()
    status_dict = {s["service_name"]: s for s in services_status}
    
    # Формируем текст с информацией о статусе
    text = "🔧 Управление сервисами\n\n"
    for service_id, service_name in SERVICES.items():
        status = status_dict.get(service_id, {})
        is_active = status.get("is_active", True) if status else True
        status_icon = "🟢" if is_active else "🔴"
        text += f"{status_icon} {service_name}\n"
    
    text += "\nВыберите сервис для управления:"
    
    if isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=get_services_menu_kb())

@router.callback_query(F.data.startswith("service_toggle:"))
async def service_toggle_menu(call: CallbackQuery, state: FSMContext):
    """Показывает меню управления конкретным сервисом."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    service_id = call.data.split(":", 1)[1]
    service_name = SERVICES.get(service_id, service_id)
    
    # Получаем текущий статус сервиса
    status = await get_service_status(service_id)
    is_active = status["is_active"] if status else True
    maintenance_message = status.get("maintenance_message", "Сервис временно недоступен. Приносим извинения за неудобства.") if status else "Сервис временно недоступен. Приносим извинения за неудобства."
    
    status_icon = "🟢" if is_active else "🔴"
    status_text = "активен" if is_active else "отключен"
    
    text = f"🔧 Управление сервисом: {service_name}\n\n"
    text += f"Статус: {status_icon} {status_text}\n"
    text += f"Сообщение при отключении:\n{maintenance_message}\n\n"
    text += "Выберите действие:"
    
    await safe_answer_callback(call, state)
    
    if isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=get_service_status_kb(service_id))

@router.callback_query(F.data.startswith("service_enable:"))
async def enable_service(call: CallbackQuery, state: FSMContext):
    """Включает сервис."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    service_id = call.data.split(":", 1)[1]
    service_name = SERVICES.get(service_id, service_id)
    
    # Получаем текущее сообщение, чтобы сохранить его
    current_status = await get_service_status(service_id)
    maintenance_message = current_status.get("maintenance_message") if current_status else None
    
    # Включаем сервис, сохраняя текущее сообщение
    await set_service_status(service_id, True, maintenance_message)
    
    await call.answer(f"✅ Сервис '{service_name}' включен!", show_alert=True)
    logger.info(f"Админ {call.from_user.id} включил сервис {service_id}")
    
    # Возвращаемся в меню управления сервисом
    await service_toggle_menu(call, state)

@router.callback_query(F.data.startswith("service_disable:"))
async def disable_service(call: CallbackQuery, state: FSMContext):
    """Отключает сервис."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    service_id = call.data.split(":", 1)[1]
    service_name = SERVICES.get(service_id, service_id)
    
    # Получаем текущее сообщение, чтобы сохранить его
    current_status = await get_service_status(service_id)
    maintenance_message = current_status.get("maintenance_message") if current_status else None
    
    # Отключаем сервис, сохраняя текущее сообщение
    await set_service_status(service_id, False, maintenance_message)
    
    await call.answer(f"🔴 Сервис '{service_name}' отключен!", show_alert=True)
    logger.info(f"Админ {call.from_user.id} отключил сервис {service_id}")
    
    # Возвращаемся в меню управления сервисом
    await service_toggle_menu(call, state)

@router.callback_query(F.data.startswith("service_message:"))
async def change_maintenance_message(call: CallbackQuery, state: FSMContext):
    """Запрашивает новое сообщение для отключенного сервиса."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    service_id = call.data.split(":", 1)[1]
    service_name = SERVICES.get(service_id, service_id)
    
    await state.update_data(editing_service=service_id)
    await state.set_state(ServiceManagementStates.waiting_for_maintenance_message)
    
    text = f"✏️ Изменение сообщения для сервиса: {service_name}\n\n"
    text += "Введите новое сообщение, которое будет показываться пользователям при попытке использовать отключенный сервис:\n\n"
    text += "Например: 'Сервис временно недоступен. Приносим извинения за неудобства.'"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏎ Назад", callback_data=f"service_toggle:{service_id}")]
    ])
    
    await safe_answer_callback(call, state)
    
    if isinstance(call.message, Message):
        await call.message.edit_text(text, reply_markup=kb)
        # Сохраняем ID сообщения для последующего удаления
        await state.update_data(edit_message_id=call.message.message_id)

@router.message(ServiceManagementStates.waiting_for_maintenance_message)
async def save_maintenance_message(message: Message, state: FSMContext):
    """Сохраняет новое сообщение для отключенного сервиса."""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    service_id = data.get("editing_service")
    
    if not service_id:
        await message.answer("❌ Ошибка: сервис не найден")
        await state.clear()
        return
    
    service_name = SERVICES.get(service_id, service_id)
    maintenance_message = message.text
    
    # Получаем текущий статус сервиса
    current_status = await get_service_status(service_id)
    is_active = current_status["is_active"] if current_status else True
    
    # Сохраняем сообщение, сохраняя текущий статус сервиса
    await set_service_status(service_id, is_active, maintenance_message)
    
    # Удаляем сообщение с запросом на ввод текста
    data = await state.get_data()
    edit_message_id = data.get("edit_message_id")
    
    if edit_message_id and message.bot:
        try:
            await message.bot.delete_message(message.chat.id, edit_message_id)
        except Exception:
            pass
    
    # Отправляем уведомление об успешном изменении
    await message.answer(f"✅ Сообщение для сервиса '{service_name}' успешно обновлено!")
    logger.info(f"Админ {message.from_user.id} изменил сообщение для сервиса {service_id}")
    
    # Показываем меню управления сервисом
    await show_service_management_menu(message, service_id, state)
    
    await state.clear()

async def show_service_management_menu(message: Message, service_id: str, state: FSMContext):
    """Показывает меню управления конкретным сервисом."""
    service_name = SERVICES.get(service_id, service_id)
    
    # Получаем текущий статус сервиса
    status = await get_service_status(service_id)
    is_active = status["is_active"] if status else True
    maintenance_message = status.get("maintenance_message", "Сервис временно недоступен. Приносим извинения за неудобства.") if status else "Сервис временно недоступен. Приносим извинения за неудобства."
    
    status_icon = "🟢" if is_active else "🔴"
    status_text = "активен" if is_active else "отключен"
    
    text = f"🔧 Управление сервисом: {service_name}\n\n"
    text += f"Статус: {status_icon} {status_text}\n"
    text += f"Сообщение при отключении:\n{maintenance_message}\n\n"
    text += "Выберите действие:"
    
    await message.answer(text, reply_markup=get_service_status_kb(service_id))

@router.callback_query(F.data.startswith("service_toggle:"))
async def service_toggle_menu_from_edit(call: CallbackQuery, state: FSMContext):
    """Обработчик кнопки отмены при редактировании сообщения."""
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    
    # Очищаем состояние редактирования
    await state.clear()
    
    # Возвращаемся в меню управления сервисом
    await service_toggle_menu(call, state)

def register_admin_services(dp):
    dp.include_router(router) 