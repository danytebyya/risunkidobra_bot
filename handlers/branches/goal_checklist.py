import asyncio
import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

# Используем только стандартный FSMContext из aiogram 3.x
from utils.chatgpt.gpt import generate_goal_checklist
from utils.bot_instance import bot
from utils.payments.payment_functional import create_payment, check_payment_status
from handlers.core.subscription import is_subscribed

logger = logging.getLogger(__name__)
router = Router()

class GoalChecklistStates(StatesGroup):
    waiting_for_goal = State()
    waiting_for_timeframe = State()
    waiting_for_preferences = State()
    waiting_for_payment = State()
    generating = State()

# Стоимость услуги
GOAL_CHECKLIST_PRICE = 100

@router.callback_query(F.data == "start_goal_checklist")
async def start_goal_checklist(callback_query: CallbackQuery, state: FSMContext):
    """Начало процесса создания чек-листа достижения цели"""
    user_id = callback_query.from_user.id
    
    try:
        # Проверяем доступность сервиса
        from utils.service_checker import check_service_availability
        is_available, maintenance_message, keyboard = await check_service_availability("goal_checklist")
        
        if not is_available:
            await callback_query.message.edit_text(
                maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.", 
                reply_markup=keyboard
            )
            return
        
        # Начинаем сбор данных для чек-листа
        await proceed_with_goal_checklist(callback_query, state)
        
    except Exception as e:
        logger.error(f"Ошибка при запуске создания чек-листа: {e}")
        await callback_query.message.edit_text(
            "😔 Произошла ошибка. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
            ])
        )

async def proceed_with_goal_checklist(callback_query: types.CallbackQuery, state: FSMContext):
    """Продолжение процесса создания чек-листа после проверки оплаты"""
    user_id = callback_query.from_user.id
    
    # Устанавливаем состояние FSM
    await state.set_state(GoalChecklistStates.waiting_for_goal)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
    ])
    
    await callback_query.message.edit_text(
        "✨ Привет! Я помогу тебе составить чёткий и удобный чек-лист для достижения твоей цели.\n\n"
        "📋 Для создания персонального чек-листа расскажи мне:\n\n"
        "🎯 **Какую цель ты хочешь достичь?**\n"
        "_(например: выучить новый язык, начать заниматься спортом, организовать праздник, "
        "найти новую работу, освоить новое хобби)_\n\n"
        "Опиши свою цель подробно - чем яснее ты расскажешь, тем точнее будет чек-лист! 💫",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    # Сохраняем ID сообщения бота для последующего редактирования
    await state.update_data(bot_message_id=callback_query.message.message_id)

@router.message(GoalChecklistStates.waiting_for_goal)
async def handle_goal_input(message: Message, state: FSMContext):
    """Обработка ввода цели"""
    user_id = message.from_user.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    goal_text = message.text.strip()
    
    if len(goal_text) < 10:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
        ])
        
        # Получаем ID предыдущего сообщения бота
        data = await state.get_data()
        bot_message_id = data.get('bot_message_id')
        
        if bot_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=bot_message_id,
                    text="🤔 Опиши свою цель более подробно (минимум 10 символов).\n\n"
                         "Например: 'Хочу выучить английский язык, чтобы свободно общаться с иностранными коллегами'",
                    reply_markup=keyboard
                )
            except Exception:
                # Если редактирование не удалось, отправляем новое сообщение
                new_msg = await message.answer(
                    "🤔 Опиши свою цель более подробно (минимум 10 символов).\n\n"
                    "Например: 'Хочу выучить английский язык, чтобы свободно общаться с иностранными коллегами'",
                    reply_markup=keyboard
                )
                await state.update_data(bot_message_id=new_msg.message_id)
        else:
            new_msg = await message.answer(
                "🤔 Опиши свою цель более подробно (минимум 10 символов).\n\n"
                "Например: 'Хочу выучить английский язык, чтобы свободно общаться с иностранными коллегами'",
                reply_markup=keyboard
            )
            await state.update_data(bot_message_id=new_msg.message_id)
        return
    
    # Сохраняем цель
    await state.update_data(goal=goal_text)
    
    # Переходим к следующему шагу
    await state.set_state(GoalChecklistStates.waiting_for_timeframe)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏰ 1-2 дня", callback_data="timeframe_1-2_days"),
            InlineKeyboardButton(text="⏰ 3-7 дней", callback_data="timeframe_3-7_days"),
        ],
        [
            InlineKeyboardButton(text="⏰ 1-2 недели", callback_data="timeframe_1-2_weeks"),
            InlineKeyboardButton(text="⏰ 1 месяц", callback_data="timeframe_1_month"),
        ],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="timeframe_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
    ])
    
    # Получаем ID предыдущего сообщения бота
    data = await state.get_data()
    bot_message_id = data.get('bot_message_id')
    
    if bot_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=user_id,
                message_id=bot_message_id,
                text=f"🎯 Отлично! Твоя цель: _{goal_text}_\n\n"
                     f"⏰ **За какой срок ты хочешь это сделать?**\n\n"
                     f"Выбери подходящий вариант или укажи свой:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception:
            # Если редактирование не удалось, отправляем новое сообщение
            new_msg = await message.answer(
                f"🎯 Отлично! Твоя цель: _{goal_text}_\n\n"
                f"⏰ **За какой срок ты хочешь это сделать?**\n\n"
                f"Выбери подходящий вариант или укажи свой:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            await state.update_data(bot_message_id=new_msg.message_id)
    else:
        new_msg = await message.answer(
            f"🎯 Отлично! Твоя цель: _{goal_text}_\n\n"
            f"⏰ **За какой срок ты хочешь это сделать?**\n\n"
            f"Выбери подходящий вариант или укажи свой:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await state.update_data(bot_message_id=new_msg.message_id)

@router.callback_query(F.data.startswith("timeframe_"))
async def handle_timeframe_selection(callback_query: CallbackQuery, state: FSMContext):
    """Обработка выбора временных рамок"""
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    
    if data_parts[0] == "timeframe":
        if data_parts[1] == "other":
            # Переходим в состояние ввода пользовательских временных рамок
            await state.update_data(waiting_for_custom_timeframe=True)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
            ])
            
            await callback_query.message.edit_text(
                "⏰ Напиши, за какой срок ты хочешь достичь цель?\n\n"
                "_(например: за 3 дня, к следующей пятнице, до конца месяца, за 2 недели)_",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            # Сохраняем ID сообщения для последующего редактирования
            await state.update_data(bot_message_id=callback_query.message.message_id)
            return
        
        # Обрабатываем предустановленные варианты
        timeframe_map = {
            "1-2_days": "1-2 дня",
            "3-7_days": "3-7 дней", 
            "1-2_weeks": "1-2 недели",
            "1_month": "1 месяц"
        }
        
        timeframe_key = "_".join(data_parts[1:])
        timeframe = timeframe_map.get(timeframe_key, "не указано")
        
        logger.info(f"Выбран timeframe: {timeframe_key} -> {timeframe}")
        await state.update_data(timeframe=timeframe)
        
        await proceed_to_preferences(callback_query, state)

@router.message(GoalChecklistStates.waiting_for_timeframe)
async def handle_custom_timeframe(message: Message, state: FSMContext):
    """Обработка ввода пользовательских временных рамок"""
    user_id = message.from_user.id
    data = await state.get_data()
    
    # Проверяем, ожидаем ли мы пользовательский ввод временных рамок
    if not data.get("waiting_for_custom_timeframe"):
        return
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    timeframe_text = message.text.strip()
    
    if len(timeframe_text) < 3:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
        ])
        
        # Получаем ID предыдущего сообщения бота
        bot_message_id = data.get('bot_message_id')
        
        if bot_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=bot_message_id,
                    text="🤔 Укажи временные рамки более конкретно.\n\n"
                         "Например: 'за 5 дней', 'к следующему понедельнику', 'до 15 числа'",
                    reply_markup=keyboard
                )
            except Exception:
                # Если редактирование не удалось, отправляем новое сообщение
                new_msg = await message.answer(
                    "🤔 Укажи временные рамки более конкретно.\n\n"
                    "Например: 'за 5 дней', 'к следующему понедельнику', 'до 15 числа'",
                    reply_markup=keyboard
                )
                await state.update_data(bot_message_id=new_msg.message_id)
        else:
            new_msg = await message.answer(
                "🤔 Укажи временные рамки более конкретно.\n\n"
                "Например: 'за 5 дней', 'к следующему понедельнику', 'до 15 числа'",
                reply_markup=keyboard
            )
            await state.update_data(bot_message_id=new_msg.message_id)
        return
    
    await state.update_data(timeframe=timeframe_text, waiting_for_custom_timeframe=False)
    
    # Создаем callback_query объект для единообразия
    fake_callback = CallbackQuery(
        id="fake", from_user=message.from_user, 
        chat_instance="fake", message=message
    )
    
    await proceed_to_preferences(fake_callback, state, is_from_message=True)

async def proceed_to_preferences(callback_query: CallbackQuery, state: FSMContext, is_from_message=False):
    """Переход к вопросу о предпочтениях"""
    user_id = callback_query.from_user.id
    
    await state.set_state(GoalChecklistStates.waiting_for_preferences)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Минималистичный стиль", callback_data="pref_minimalist")],
        [InlineKeyboardButton(text="🌟 Яркий и красочный", callback_data="pref_colorful")],
        [InlineKeyboardButton(text="📋 Простой и понятный", callback_data="pref_simple")],
        [InlineKeyboardButton(text="💼 Деловой стиль", callback_data="pref_business")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="pref_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
    ])
    
    data = await state.get_data()
    goal = data.get('goal', 'цель')
    timeframe = data.get('timeframe', 'срок')
    
    text = (f"🎯 Цель: _{goal}_\n"
            f"⏰ Срок: _{timeframe}_\n\n"
            f"🎨 **Есть ли у тебя особенности или предпочтения для чек-листа?**\n\n"
            f"_(например: стиль оформления, уровень детализации, формат подачи информации)_\n\n"
            f"Выбери подходящий вариант или опиши свои предпочтения:")
    
    # Получаем ID предыдущего сообщения бота
    data = await state.get_data()
    bot_message_id = data.get('bot_message_id')
    
    if bot_message_id:
        try:
            await callback_query.message.bot.edit_message_text(
                chat_id=user_id,
                message_id=bot_message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception:
            # Если редактирование не удалось, отправляем новое сообщение
            new_msg = await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
            await state.update_data(bot_message_id=new_msg.message_id)
    else:
        if is_from_message:
            new_msg = await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
            await state.update_data(bot_message_id=new_msg.message_id)
        else:
            await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            await state.update_data(bot_message_id=callback_query.message.message_id)

@router.callback_query(F.data.startswith("pref_"))
async def handle_preferences_selection(callback_query: CallbackQuery, state: FSMContext):
    """Обработка выбора предпочтений"""
    user_id = callback_query.from_user.id
    data_parts = callback_query.data.split("_")
    
    if data_parts[0] == "pref":
        if data_parts[1] == "other":
            # Переходим в состояние ввода пользовательских предпочтений
            await state.update_data(waiting_for_custom_preferences=True)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
            ])
            
            await callback_query.message.edit_text(
                "🎨 Опиши свои предпочтения для оформления чек-листа:\n\n"
                "_(например: подробные шаги, краткие пункты, мотивирующие фразы, "
                "временные рамки для каждого этапа, особый стиль оформления)_",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            # Сохраняем ID сообщения для последующего редактирования
            await state.update_data(bot_message_id=callback_query.message.message_id)
            return
        
        # Обрабатываем предустановленные варианты
        preferences_map = {
            "minimalist": "минималистичный стиль",
            "colorful": "яркий и красочный стиль", 
            "simple": "простой и понятный стиль",
            "business": "деловой стиль"
        }
        
        preferences = preferences_map.get(data_parts[1], "не указано")
        
        logger.info(f"Выбраны предпочтения: {data_parts[1]} -> {preferences}")
        await state.update_data(preferences=preferences)
        
        await show_payment_step(callback_query, state)

@router.message(GoalChecklistStates.waiting_for_preferences)
async def handle_custom_preferences(message: Message, state: FSMContext):
    """Обработка ввода пользовательских предпочтений"""
    user_id = message.from_user.id
    data = await state.get_data()
    
    # Проверяем, ожидаем ли мы пользовательский ввод предпочтений
    if not data.get("waiting_for_custom_preferences"):
        return
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    preferences_text = message.text.strip()
    
    if len(preferences_text) < 5:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
        ])
        
        # Получаем ID предыдущего сообщения бота
        bot_message_id = data.get('bot_message_id')
        
        if bot_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=bot_message_id,
                    text="🎨 Опиши свои предпочтения для оформления чек-листа:\n\n"
                         "_(например: подробные шаги, краткие пункты, мотивирующие фразы, "
                         "временные рамки для каждого этапа, особый стиль оформления)_\n\n"
                         "❌ **Слишком короткое описание!** Пожалуйста, опиши подробнее свои предпочтения.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}")
                # Если не удалось отредактировать, отправляем новое сообщение
                new_msg = await message.answer(
                    "🎨 Опиши свои предпочтения для оформления чек-листа:\n\n"
                    "_(например: подробные шаги, краткие пункты, мотивирующие фразы, "
                    "временные рамки для каждого этапа, особый стиль оформления)_\n\n"
                    "❌ **Слишком короткое описание!** Пожалуйста, опиши подробнее свои предпочтения.",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                await state.update_data(bot_message_id=new_msg.message_id)
        return
    
    await state.update_data(preferences=preferences_text, waiting_for_custom_preferences=False)
    
    # Показываем сообщение ожидания
    keyboard = None
    
    loading_text = (
        "✨ Создаю персональный чек-лист для твоей цели...\n\n"
        "⏳ Это займёт некоторое время"
    )
    
    # Получаем ID предыдущего сообщения бота
    bot_message_id = data.get('bot_message_id')
    
    if bot_message_id:
        try:
            loading_msg = await message.bot.edit_message_text(
                chat_id=user_id,
                message_id=bot_message_id,
                text=loading_text,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            # Если не удалось отредактировать, отправляем новое сообщение
            loading_msg = await message.answer(loading_text, reply_markup=keyboard)
    else:
        loading_msg = await message.answer(loading_text, reply_markup=keyboard)
    
    await state.set_state(GoalChecklistStates.generating)
    
    # Создаем callback_query объект для единообразия
    fake_callback = CallbackQuery(
        id="fake", from_user=message.from_user,
        chat_instance="fake", message=loading_msg
    )
    
    await show_payment_step(fake_callback, state)

async def generate_checklist(callback_query: CallbackQuery, state: FSMContext, is_from_message=False):
    """Генерация чек-листа"""
    user_id = callback_query.from_user.id
    
    try:
        # Показываем индикатор загрузки
        keyboard = None
        
        loading_text = (
            "✨ Создаю персональный чек-лист для твоей цели...\n\n"
            "⏳ Это займёт несколько секунд"
        )
        
        if is_from_message:
            loading_msg = await callback_query.message.answer(loading_text, reply_markup=keyboard)
        else:
            loading_msg = await callback_query.message.edit_text(loading_text, reply_markup=keyboard)
        
        await state.set_state(GoalChecklistStates.generating)
        
        # Получаем данные
        data = await state.get_data()
        goal = data.get('goal', '')
        timeframe = data.get('timeframe', '')
        preferences = data.get('preferences', '')
        
        logger.info(f"Данные для генерации: goal='{goal}', timeframe='{timeframe}', preferences='{preferences}'")
        
        # Проверяем статус платежа из состояния
        payment_id = data.get('payment_id')
        if not payment_id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
            ])
            
            await loading_msg.edit_text(
                "😔 Ошибка: платеж не найден!",
                reply_markup=keyboard
            )
            await state.clear()
            return
        
        status = await check_payment_status(payment_id)
        if status != 'succeeded':
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
            ])
            
            await loading_msg.edit_text(
                "😔 Оплата не подтверждена!",
                reply_markup=keyboard
            )
            await state.clear()
            return
        
        # Генерируем чек-лист
        checklist = await generate_goal_checklist(goal, timeframe, preferences)
        
        if not checklist:
            raise Exception("Не удалось сгенерировать чек-лист")
        
        # Показываем результат
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start_from_checklist")]
        ])
        
        result_text = f"✨ **Твой персональный чек-лист готов!**\n\n{checklist}"
        
        await loading_msg.edit_text(
            result_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        # Очищаем состояние
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при генерации чек-листа: {e}")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")]
        ])
        
        error_text = "😔 Произошла ошибка при создании чек-листа. Попробуйте позже."
        
        if is_from_message:
            await callback_query.message.answer(error_text, reply_markup=keyboard)
        else:
            await callback_query.message.edit_text(error_text, reply_markup=keyboard)
        
        await state.clear()

# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_goal_checklist")
async def go_back_goal_checklist(callback_query: CallbackQuery, state: FSMContext):
    """Универсальный возврат назад в flow чек-листа"""
    current = await state.get_state()
    data = await state.get_data()
    
    if current == GoalChecklistStates.waiting_for_timeframe.state:
        # Возврат к вводу цели
        await proceed_with_goal_checklist(callback_query, state)
    elif current == GoalChecklistStates.waiting_for_preferences.state:
        # Возврат к выбору временных рамок
        await back_to_timeframe_selection(callback_query, state)
    elif current == GoalChecklistStates.waiting_for_payment.state:
        # Возврат к выбору предпочтений
        await back_to_preferences_selection(callback_query, state)
    else:
        # В остальных случаях - в главное меню
        from handlers.core.start import START_TEXT, get_main_menu_kb
        await callback_query.message.edit_text(START_TEXT, reply_markup=get_main_menu_kb())
        await state.clear()

# Обработчики кнопок "Назад"
@router.callback_query(F.data == "back_to_goal_input")
async def back_to_goal_input(callback_query: CallbackQuery, state: FSMContext):
    """Возврат к вводу цели"""
    await proceed_with_goal_checklist(callback_query, state)

@router.callback_query(F.data == "back_to_timeframe_selection")
async def back_to_timeframe_selection(callback_query: CallbackQuery, state: FSMContext):
    """Возврат к выбору временных рамок"""
    user_id = callback_query.from_user.id
    
    data = await state.get_data()
    goal = data.get('goal', '')
    
    await state.set_state(GoalChecklistStates.waiting_for_timeframe)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏰ 1-2 дня", callback_data="timeframe_1-2_days"),
            InlineKeyboardButton(text="⏰ 3-7 дней", callback_data="timeframe_3-7_days"),
        ],
        [
            InlineKeyboardButton(text="⏰ 1-2 недели", callback_data="timeframe_1-2_weeks"),
            InlineKeyboardButton(text="⏰ 1 месяц", callback_data="timeframe_1_month"),
        ],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="timeframe_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
    ])
    
    await callback_query.message.edit_text(
        f"🎯 Твоя цель: _{goal}_\n\n"
        f"⏰ **За какой срок ты хочешь это сделать?**\n\n"
        f"Выбери подходящий вариант или укажи свой:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_to_preferences_selection")
async def back_to_preferences_selection(callback_query: CallbackQuery, state: FSMContext):
    """Возврат к выбору предпочтений"""
    await proceed_to_preferences(callback_query, state)


async def show_payment_step(callback_query: CallbackQuery, state: FSMContext):
    """Показывает экран оплаты"""
    user_id = callback_query.from_user.id
    
    try:
        # Создаем платеж
        payment_url, payment_id = await create_payment(
            user_id,
            GOAL_CHECKLIST_PRICE,
            "Создание чек-листа достижения цели"
        )
        
        if not payment_url or not payment_id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
            ])
            
            await callback_query.message.edit_text(
                "❌ Ошибка создания платежа. Попробуйте позже.",
                reply_markup=keyboard
            )
            return
        
        # Сохраняем payment_id в состоянии
        await state.update_data(payment_id=payment_id)
        
        # Устанавливаем состояние ожидания оплаты
        await state.set_state(GoalChecklistStates.waiting_for_payment)
        
        # Показываем кнопки оплаты
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 100₽", url=payment_url)],
            [InlineKeyboardButton(text="🎯 Получить чек-лист", callback_data=f"check_goal_checklist:{payment_id}")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
        ])
        
        await callback_query.message.edit_text(
            f"💳 Для создания персонального чек-листа необходимо оплатить {GOAL_CHECKLIST_PRICE}₽\n\n"
            f"После оплаты нажмите «🎯 Получить чек-лист»",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при создании платежа: {e}")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_goal_checklist")]
        ])
        
        await callback_query.message.edit_text(
            "😔 Произошла ошибка. Попробуйте позже.",
            reply_markup=keyboard
        )

@router.callback_query(F.data.startswith("check_goal_checklist:"))
async def check_goal_checklist_payment(callback_query: CallbackQuery, state: FSMContext):
    """Проверка оплаты чек-листа"""
    user_id = callback_query.from_user.id
    payment_id = callback_query.data.split(":", 1)[1]
    
    try:
        status = await check_payment_status(payment_id)
        
        if status == 'succeeded':
            # Оплата прошла успешно, сохраняем payment_id и запускаем генерацию чек-листа
            await state.update_data(payment_id=payment_id)
            await generate_checklist(callback_query, state)
        else:
            await callback_query.answer(
                f"😔 Оплата не подтверждена. Статус: {status}",
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Ошибка при проверке платежа: {e}")
        await callback_query.answer("😔 Ошибка проверки платежа", show_alert=True)

@router.callback_query(F.data == "start_from_checklist")
async def start_from_checklist(callback_query: CallbackQuery, state: FSMContext):
    """Возврат в главное меню после генерации чек-листа - удаляем кнопки и отправляем новое сообщение"""
    from handlers.core.start import START_TEXT, get_main_menu_kb
    
    # Удаляем кнопки из текущего сообщения (оставляем только текст чек-листа)
    try:
        # Получаем текст сообщения без кнопок
        message_text = callback_query.message.text
        await callback_query.message.edit_text(
            message_text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при удалении кнопок: {e}")
    
    # Отправляем новое сообщение с главным меню
    await callback_query.message.answer(
        START_TEXT, 
        reply_markup=get_main_menu_kb()
    )
    
    # Очищаем состояние
    await state.clear()
    await callback_query.answer()

def register_goal_checklist_handlers(dp):
    """Регистрация обработчиков чек-листа достижения цели"""
    dp.include_router(router)
