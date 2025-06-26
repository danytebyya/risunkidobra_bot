from aiogram import Router, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from utils.utils import safe_call_answer
from config import ADMIN_IDS


router = Router()


START_TEXT = (
    "🔧 Пункт администрирования:"
)


def get_admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Изображения", callback_data="admin_images")],
        [InlineKeyboardButton(text="📁 Фоны", callback_data="admin_backgrounds")],
        [InlineKeyboardButton(text="🔤 Шрифты", callback_data="admin_fonts")],
        [InlineKeyboardButton(text="🎨 Цвета", callback_data="admin_colors")],
        [InlineKeyboardButton(text="👤 Управление подпиской", callback_data="admin_subscriptions")],
    ])


@router.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    """Обрабатывает команду /admin и показывает главное меню админа."""
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ У вас нет доступа к админ-панели.")
    await state.clear()
    await message.answer(START_TEXT, reply_markup=get_admin_menu_kb())


@router.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery, state: FSMContext):
    """Возвращает пользователя в главное меню администрирования."""
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Нет доступа", show_alert=True)
    await safe_call_answer(call)
    await state.clear()
    await call.message.edit_text(START_TEXT, reply_markup=get_admin_menu_kb())
    await call.answer()


def register_admin(dp: Dispatcher):
    """Регистрирует роутер меню админа и роутеры дочерних модулей."""
    dp.include_router(router)

