from aiogram import Router, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from utils.utils import safe_answer_callback
from config import ADMIN_IDS, logger
from utils.database.dropbox_storage import sync_resources_hash


router = Router()


START_TEXT = (
    "🔧 Пункт администрирования:"
)


def get_admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Управление данными", callback_data="admin_data_management")],
        [InlineKeyboardButton(text="🔧 Управление сервисами", callback_data="admin_services")],
        [InlineKeyboardButton(text="👤 Управление подписками", callback_data="admin_subscriptions")],
        [InlineKeyboardButton(text="📢 Уведомления", callback_data="admin_notifications")],
    ])


# --- Клавиатура для подменю управления данными ---
def get_admin_data_management_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼️ Изображения", callback_data="admin_img")],
        [InlineKeyboardButton(text="🎨 Цвета", callback_data="admin_colors")],
        [InlineKeyboardButton(text="🔤 Шрифты", callback_data="admin_fonts")],
        [InlineKeyboardButton(text="🔄 Импортировать данные", callback_data="admin_sync")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_back")],
    ])


# --- Клавиатура для подменю изображений ---
def get_admin_images_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼️ Открытки", callback_data="admin_images")],
        [InlineKeyboardButton(text="🌄 Фоны", callback_data="admin_backgrounds")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="admin_data_management")],
    ])


@router.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    """Обрабатывает команду /admin и показывает главное меню админа."""
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ У вас нет доступа к админ-панели.")
    
    # Сбрасываем сессию психолога, если пользователь был в ней
    data = await state.get_data()
    if data.get("session_active") and data.get("psychologist_stage"):
        logger.info(f"Сбрасываем сессию психолога для пользователя {message.from_user.id}")
    
    await state.clear()
    await message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


@router.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя в главное меню администрирования."""
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа", show_alert=True)
    await safe_answer_callback(call, state)
    await state.clear()
    if isinstance(call.message, Message):
        try:
            await call.message.edit_text(START_TEXT, reply_markup=get_admin_menu_kb())
        except Exception as e:
            if "message is not modified" in str(e):
                pass  # Игнорируем ошибку, если сообщение не изменилось
            else:
                raise


@router.callback_query(F.data == "admin_sync")
async def admin_sync(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    await safe_answer_callback(call, state)
    msg = call.message
    if not msg:
        return
    # Сначала редактируем текущее сообщение
    try:
        await msg.edit_text("⏳ Импорт данных из Dropbox...", reply_markup=None)
    except Exception:
        msg = await msg.answer("⏳ Импорт данных из Dropbox...")
    try:
        sync_resources_hash()
        result_text = "✅ Импорт завершён! Локальные ресурсы приведены к виду Dropbox."
    except Exception as e:
        result_text = f"❌ Ошибка импорта: {str(e)}"
    # После завершения снова редактируем (или отправляем новое)
    try:
        await msg.edit_text(result_text)
    except Exception:
        msg = await msg.answer(result_text)
    # В конце отправляем главное меню админа
    await msg.answer(START_TEXT, reply_markup=get_admin_menu_kb())


@router.callback_query(F.data == "admin_data_management")
async def admin_data_management_menu(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    await safe_answer_callback(call, state)
    if not call.message:
        return
    if isinstance(call.message, Message):
        await call.message.edit_text(
            "📊 Управление данными. Выберите раздел:",
            reply_markup=get_admin_data_management_kb()
        )


@router.callback_query(F.data == "admin_img")
async def admin_images_menu(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа", show_alert=True)
        return
    await safe_answer_callback(call, state)
    if not call.message:
        return
    if isinstance(call.message, Message):
        await call.message.edit_text(
            "⚙️ Раздел изображений. Выберите, с чем работать:",
            reply_markup=get_admin_images_menu_kb()
        )


def register_admin(dp: Dispatcher):
    """Регистрирует роутер меню админа и роутеры дочерних модулей."""
    dp.include_router(router)

