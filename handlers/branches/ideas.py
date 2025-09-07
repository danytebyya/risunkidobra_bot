import random
from aiogram import Router, F, types, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.core.start import START_TEXT, get_main_menu_kb
from handlers.core.subscription import is_subscribed
from utils.chatgpt.gpt import generate_ideas, generate_ideas_with_edits
from utils.payments.payment_functional import create_payment, check_payment_status
from utils.utils import safe_edit_text, safe_answer_callback
from utils.database.db import save_ideas_session, get_daily_surprise_used, mark_daily_surprise_used
from config import logger, SUPPORT_URL


# Константа для сообщения об оплате
PAYMENT_MESSAGE = """💡 Для генерации идей необходима оплата 100₽

✨ Что вы получите:
• 3 уникальные идеи
• Подробное описание каждой
• Практические рекомендации

💳 Нажмите кнопку ниже для оплаты:"""


router = Router()


class IdeasStates(StatesGroup):
    select_category = State()
    select_style = State()
    input_constraints = State()
    waiting_for_constraints = State()
    input_edit_prompt = State()
    waiting_for_category = State()
    waiting_for_style = State()
    waiting_for_name_purpose = State()
    waiting_for_business_purpose = State()
    # Новые состояния для запроса деталей при выборе "Другое"
    waiting_for_gift_recipient_other = State()
    waiting_for_gift_budget_other = State()
    waiting_for_gift_occasion_other = State()
    waiting_for_post_topic_other = State()
    waiting_for_post_format_other = State()
    waiting_for_post_audience_other = State()
    waiting_for_name_type_other = State()
    waiting_for_name_style_other = State()
    waiting_for_name_audience_other = State()
    waiting_for_business_sphere_other = State()
    waiting_for_business_budget_other = State()
    waiting_for_business_scale_other = State()


# ——————————————————————
# Стартовое меню идей
# ——————————————————————
@router.callback_query(F.data == "ideas")
async def ideas_start(call: CallbackQuery, state: FSMContext):
    """Показывает стартовое меню генератора идей."""
    await state.clear()
    user_id = call.from_user.id if call.from_user else None
    logger.info(f"Пользователь {user_id} переключился на вкладку «Идеи для чего угодно»")
    
    # Проверяем доступность сервиса
    from utils.service_checker import check_service_availability
    is_available, maintenance_message, keyboard = await check_service_availability("ideas")
    
    if not is_available:
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text=maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard
            )
        await safe_answer_callback(call, state)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💡 Индивидуальная идея", callback_data="ideas_start_process")],
        [InlineKeyboardButton(text="🎲 Сюрприз-идея", callback_data="ideas_surprise")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text=(
                "✨ Привет! Я помогу придумать идею для чего угодно — будь то подарок, бизнес либо творческий проект.\n\n"
                "👇 Выберите тип идеи, который хотите получить"
            ),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Сюрприз-идея
# ——————————————————————
@router.callback_query(F.data == "ideas_surprise")
async def ideas_surprise(call: CallbackQuery, state: FSMContext):
    """Генерирует сюрприз-идею для пользователей с подпиской."""
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return

    # Проверяем подписку
    if not await is_subscribed(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Купить подписку", callback_data="subscription")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text="🎲 Сюрприз-идеи доступны только для пользователей с подпиской!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
        await safe_answer_callback(call, state)
        return

    # Проверяем, использовал ли пользователь сюрприз сегодня
    if await get_daily_surprise_used(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💡 Индивидуальная идея", callback_data="ideas_start_process")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text="🎲 Вы уже использовали сюрприз-идею сегодня. Ждем вас завтра!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
        await safe_answer_callback(call, state)
        return

    # Генерируем сюрприз-идею
    loading = None
    if call.message and call.bot is not None:
        loading = await call.bot.send_message(chat_id=call.message.chat.id, text="🎲 Создаем сюрприз-идею...")

    try:
        # Случайно выбираем категорию для сюрприз-идеи
        categories = [
            ("🎁 Подарок", "подарок"),
            ("📸 Пост для соцсетей", "пост для социальных сетей"), 
            ("✍️ Название", "название"),
            ("🚀 Бизнес-идея", "бизнес-идея")
        ]
        category_display, category_for_gpt = random.choice(categories)
        
        surprise_ideas = await generate_ideas(category_for_gpt, "случайный", "")
        
        # Добавляем информацию о категории в начало ответа
        formatted_ideas = f"🎲 **Сюрприз-идея: {category_display}**\n\n{surprise_ideas}"
        
        # Сохраняем сессию сюрприз-идеи в базу данных
        try:
            await save_ideas_session(
                user_id=user_id,
                category=category_for_gpt,
                style="случайный",
                constraints="",
                ideas_text=formatted_ideas,
                is_surprise=True
            )
            # Отмечаем, что пользователь использовал сюрприз-идею сегодня
            await mark_daily_surprise_used(user_id)
            logger.info(f"Сохранена сюрприз-идея для пользователя {user_id}, категория: {category_for_gpt}")
        except Exception as db_error:
            logger.error(f"Ошибка сохранения сюрприз-идеи для {user_id}: {db_error}")
        
        await state.update_data(
            is_surprise=True,
            regeneration_count=0,
            ideas_history=[formatted_ideas]
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])

        if call.message and call.bot is not None:
            # Редактируем стартовое сообщение, заменяя его на идеи
            await call.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✨ Вот что мы придумали:\n\n{formatted_ideas}",
                reply_markup=kb
            )
            # Удаляем сообщение о загрузке
            if loading:
                await call.bot.delete_message(chat_id=call.message.chat.id, message_id=loading.message_id)

    except Exception as e:
        logger.error(f"Ошибка генерации сюрприз-идеи для {user_id}: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="ideas_surprise")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        if call.message and call.bot is not None:
            await call.bot.edit_message_text(
                text="❌ Произошла ошибка при создании сюрприз-идеи. Попробуйте еще раз.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
            if loading:
                await call.bot.delete_message(chat_id=call.message.chat.id, message_id=loading.message_id)

    await safe_answer_callback(call, state)


# ——————————————————————
# Начало основного процесса
# ——————————————————————
@router.callback_query(F.data == "ideas_start_process")
async def ideas_start_process(call: CallbackQuery, state: FSMContext):
    """Начинает основной процесс генерации идей - шаг 1."""
    await state.clear()
    await state.set_state(IdeasStates.select_category)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Подарок", callback_data="ideas_category:gift")],
        [InlineKeyboardButton(text="📸 Пост", callback_data="ideas_category:post")],
        [InlineKeyboardButton(text="✍️ Название", callback_data="ideas_category:name")],
        [InlineKeyboardButton(text="🚀 Бизнес", callback_data="ideas_category:business")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_category:other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="start")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text='✨ Добро пожаловать в мастерскую идей!\n\n'
                '♡ Определите, для чего нужна идея: подарок, пост, название, бизнес, либо ваш вариант?\n'
                '✎ Уточните пожелания\n'
                '✓ Завершите оформление: оплатите заказ и получите 3 уникальные идеи\n\n'
                'Готовы вдохновиться?\n\n'
                '👇 Давайте начнем с выбора категории',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Выбор категории
# ——————————————————————
@router.callback_query(F.data.startswith("ideas_category:"))
async def ideas_select_category(call: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор категории идеи."""
    category = call.data.split(":", 1)[1] if call.data and ":" in call.data else ""
    
    if category == "other":
        # Если выбрано "Другое", запрашиваем ввод категории
        await state.set_state(IdeasStates.waiting_for_category)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
        ])
        
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text="✨ Введите, для чего именно нужна идея:\n\n"
                     "Например: название для кафе, идея для вечеринки, концепция для блога и т.д.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
        await safe_answer_callback(call, state)
        return
    
    # Сохраняем категорию в состоянии
    await state.update_data(category=category)
    
    if category == "gift":
        # Подарки: сразу показываем варианты "кому дарить"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👩 Маме", callback_data="ideas_detail:gift_who_mom")],
            [InlineKeyboardButton(text="👨 Папе", callback_data="ideas_detail:gift_who_dad")],
            [InlineKeyboardButton(text="💕 Девушке/Парню", callback_data="ideas_detail:gift_who_partner")],
            [InlineKeyboardButton(text="👶 Ребенку", callback_data="ideas_detail:gift_who_child")],
            [InlineKeyboardButton(text="👥 Другу", callback_data="ideas_detail:gift_who_friend")],
            [InlineKeyboardButton(text="👔 Коллеге", callback_data="ideas_detail:gift_who_colleague")],
            [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_who_other")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
        ])
        
        text = "🎁 Отлично! Кому дарите подарок?"
               
    elif category == "post":
        # Посты: сразу показываем варианты тем
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✈️ Путешествия", callback_data="ideas_detail:post_topic_travel")],
            [InlineKeyboardButton(text="🍳 Кулинария", callback_data="ideas_detail:post_topic_cooking")],
            [InlineKeyboardButton(text="💄 Красота", callback_data="ideas_detail:post_topic_beauty")],
            [InlineKeyboardButton(text="💪 Спорт", callback_data="ideas_detail:post_topic_sport")],
            [InlineKeyboardButton(text="📚 Образование", callback_data="ideas_detail:post_topic_education")],
            [InlineKeyboardButton(text="🎨 Творчество", callback_data="ideas_detail:post_topic_creativity")],
            [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_topic_other")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
        ])
        
        text = "📸 Отлично! О чем будет ваш пост?"
               
    elif category == "name":
        # Названия: показываем варианты типов бизнеса
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Кафе/Ресторан", callback_data="ideas_detail:name_type_cafe")],
            [InlineKeyboardButton(text="🛍️ Магазин/Бренд", callback_data="ideas_detail:name_type_shop")],
            [InlineKeyboardButton(text="📱 Приложение/IT", callback_data="ideas_detail:name_type_app")],
            [InlineKeyboardButton(text="📝 Блог/Канал", callback_data="ideas_detail:name_type_blog")],
            [InlineKeyboardButton(text="🏢 Компания/Стартап", callback_data="ideas_detail:name_type_company")],
            [InlineKeyboardButton(text="🎯 Проект/Мероприятие", callback_data="ideas_detail:name_type_project")],
            [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_type_other")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
        ])
        
        text = "✍️ Для чего нужно название?"
               
    elif category == "business":
        # Бизнес: показываем варианты сфер
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍽️ Общепит", callback_data="ideas_detail:business_sphere_food")],
            [InlineKeyboardButton(text="🛒 Торговля", callback_data="ideas_detail:business_sphere_retail")],
            [InlineKeyboardButton(text="💻 IT/Технологии", callback_data="ideas_detail:business_sphere_tech")],
            [InlineKeyboardButton(text="🎓 Образование", callback_data="ideas_detail:business_sphere_education")],
            [InlineKeyboardButton(text="💄 Красота/Здоровье", callback_data="ideas_detail:business_sphere_beauty")],
            [InlineKeyboardButton(text="🏠 Услуги", callback_data="ideas_detail:business_sphere_services")],
            [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_sphere_other")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
        ])
        
        text = "🚀 В какой сфере планируете бизнес?"
    
    # Показываем варианты для выбранной категории
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Функции для подкатегорий подарков
# ——————————————————————
async def show_gift_budget_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты бюджета для подарка."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 До 1000₽", callback_data="ideas_detail:gift_budget_1000")],
        [InlineKeyboardButton(text="💰 1000-3000₽", callback_data="ideas_detail:gift_budget_3000")],
        [InlineKeyboardButton(text="💰 3000-5000₽", callback_data="ideas_detail:gift_budget_5000")],
        [InlineKeyboardButton(text="💰 5000-10000₽", callback_data="ideas_detail:gift_budget_10000")],
        [InlineKeyboardButton(text="💰 От 10000₽", callback_data="ideas_detail:gift_budget_10000plus")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_budget_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_recipient")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="💰 Какой у вас бюджет на подарок?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


async def show_gift_occasion_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты повода для подарка."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎂 День рождения", callback_data="ideas_detail:gift_occasion_birthday")],
        [InlineKeyboardButton(text="💝 День святого Валентина", callback_data="ideas_detail:gift_occasion_valentine")],
        [InlineKeyboardButton(text="🎄 Новый год", callback_data="ideas_detail:gift_occasion_newyear")],
        [InlineKeyboardButton(text="👰 Свадьба", callback_data="ideas_detail:gift_occasion_wedding")],
        [InlineKeyboardButton(text="🎓 Выпускной", callback_data="ideas_detail:gift_occasion_graduation")],
        [InlineKeyboardButton(text="🏠 Новоселье", callback_data="ideas_detail:gift_occasion_housewarming")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_occasion_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_budget")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🎉 По какому поводу дарите подарок?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


# ——————————————————————
# Функции для подкатегорий постов
# ——————————————————————
async def show_post_format_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты формата для поста."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Сторис", callback_data="ideas_detail:post_format_story")],
        [InlineKeyboardButton(text="📷 Пост в ленту", callback_data="ideas_detail:post_format_feed")],
        [InlineKeyboardButton(text="🎠 Карусель", callback_data="ideas_detail:post_format_carousel")],
        [InlineKeyboardButton(text="🎬 Рилс", callback_data="ideas_detail:post_format_reel")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_format_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_topic")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="📱 В каком формате будет ваш пост?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


async def show_post_audience_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты аудитории для поста."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Друзья", callback_data="ideas_detail:post_audience_friends")],
        [InlineKeyboardButton(text="💼 Бизнес-аудитория", callback_data="ideas_detail:post_audience_business")],
        [InlineKeyboardButton(text="👤 Подписчики", callback_data="ideas_detail:post_audience_followers")],
        [InlineKeyboardButton(text="🌍 Широкая аудитория", callback_data="ideas_detail:post_audience_general")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_audience_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_format")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="👥 Для какой аудитории предназначен пост?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


# ——————————————————————
# Функции для подкатегорий названий
# ——————————————————————
async def show_name_style_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты стиля для названий."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Современный", callback_data="ideas_detail:name_style_modern")],
        [InlineKeyboardButton(text="🎨 Креативный", callback_data="ideas_detail:name_style_creative")],
        [InlineKeyboardButton(text="💼 Деловой", callback_data="ideas_detail:name_style_business")],
        [InlineKeyboardButton(text="🌸 Нежный", callback_data="ideas_detail:name_style_gentle")],
        [InlineKeyboardButton(text="⚡ Энергичный", callback_data="ideas_detail:name_style_energetic")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_style_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_type")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🎨 Какой стиль названия предпочитаете?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


async def show_name_audience_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты целевой аудитории для названий."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👶 Дети", callback_data="ideas_detail:name_audience_children")],
        [InlineKeyboardButton(text="🧑 Молодежь", callback_data="ideas_detail:name_audience_youth")],
        [InlineKeyboardButton(text="👨‍💼 Взрослые", callback_data="ideas_detail:name_audience_adults")],
        [InlineKeyboardButton(text="👵 Пожилые", callback_data="ideas_detail:name_audience_elderly")],
        [InlineKeyboardButton(text="🌍 Универсальное", callback_data="ideas_detail:name_audience_universal")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_audience_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_style")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="👥 Для какой аудитории предназначено?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


# ——————————————————————
# Функции для подкатегорий бизнеса
# ——————————————————————
async def show_business_budget_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты бюджета для бизнеса."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 До 100к₽", callback_data="ideas_detail:business_budget_100k")],
        [InlineKeyboardButton(text="💰 100к-500к₽", callback_data="ideas_detail:business_budget_500k")],
        [InlineKeyboardButton(text="💰 500к-1млн₽", callback_data="ideas_detail:business_budget_1m")],
        [InlineKeyboardButton(text="💰 1млн-5млн₽", callback_data="ideas_detail:business_budget_5m")],
        [InlineKeyboardButton(text="💰 От 5млн₽", callback_data="ideas_detail:business_budget_5mplus")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_budget_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_sphere")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="💰 Какой у вас стартовый бюджет?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


async def show_business_scale_options(call: CallbackQuery, state: FSMContext):
    """Показывает варианты масштаба для бизнеса."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Домашний бизнес", callback_data="ideas_detail:business_scale_home")],
        [InlineKeyboardButton(text="🏪 Локальный", callback_data="ideas_detail:business_scale_local")],
        [InlineKeyboardButton(text="🏙️ Городской", callback_data="ideas_detail:business_scale_city")],
        [InlineKeyboardButton(text="🌍 Региональный", callback_data="ideas_detail:business_scale_regional")],
        [InlineKeyboardButton(text="🌐 Онлайн", callback_data="ideas_detail:business_scale_online")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_scale_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_budget")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="📏 Какого масштаба планируете бизнес?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )


# ——————————————————————
# Обработка деталей
# ——————————————————————
@router.callback_query(F.data.startswith("ideas_detail:"))
async def ideas_select_detail(call: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор деталей для различных категорий."""
    detail_type = call.data.split(":", 1)[1] if call.data and ":" in call.data else ""
    
    # ——————————————————————
    # Обработка подарков - "Кому дарить"
    # ——————————————————————
    if detail_type.startswith("gift_who_"):
        recipient = detail_type.replace("gift_who_", "")
        if recipient == "mom":
            await state.update_data(gift_recipient="Маме")
        elif recipient == "dad":
            await state.update_data(gift_recipient="Папе")
        elif recipient == "partner":
            await state.update_data(gift_recipient="Девушке/Парню")
        elif recipient == "child":
            await state.update_data(gift_recipient="Ребенку")
        elif recipient == "friend":
            await state.update_data(gift_recipient="Другу")
        elif recipient == "colleague":
            await state.update_data(gift_recipient="Коллеге")
        elif recipient == "other":
            # Запрашиваем ввод получателя подарка
            await state.set_state(IdeasStates.waiting_for_gift_recipient_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_recipient")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="🎁 Кому именно дарите подарок?\n\n"
                         "Например: бабушке, учителю, начальнику, соседке и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_gift_budget_options(call, state)
    
    # ——————————————————————
    # Обработка подарков - "Бюджет"
    # ——————————————————————
    elif detail_type.startswith("gift_budget_"):
        budget = detail_type.replace("gift_budget_", "")
        if budget == "1000":
            await state.update_data(gift_budget="До 1000₽")
        elif budget == "3000":
            await state.update_data(gift_budget="1000-3000₽")
        elif budget == "5000":
            await state.update_data(gift_budget="3000-5000₽")
        elif budget == "10000":
            await state.update_data(gift_budget="5000-10000₽")
        elif budget == "10000plus":
            await state.update_data(gift_budget="От 10000₽")
        elif budget == "other":
            # Запрашиваем ввод бюджета подарка
            await state.set_state(IdeasStates.waiting_for_gift_budget_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_budget")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="💰 Укажите ваш бюджет на подарок:\n\n"
                         "Например: до 500 рублей, около 2000, без ограничений и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_gift_occasion_options(call, state)
    
    # ——————————————————————
    # Обработка подарков - "Повод"
    # ——————————————————————
    elif detail_type.startswith("gift_occasion_"):
        occasion = detail_type.replace("gift_occasion_", "")
        if occasion == "birthday":
            await state.update_data(gift_occasion="День рождения")
        elif occasion == "valentine":
            await state.update_data(gift_occasion="День святого Валентина")
        elif occasion == "newyear":
            await state.update_data(gift_occasion="Новый год")
        elif occasion == "wedding":
            await state.update_data(gift_occasion="Свадьба")
        elif occasion == "graduation":
            await state.update_data(gift_occasion="Выпускной")
        elif occasion == "housewarming":
            await state.update_data(gift_occasion="Новоселье")
        elif occasion == "other":
            # Запрашиваем ввод повода для подарка
            await state.set_state(IdeasStates.waiting_for_gift_occasion_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_occasion")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="🎉 По какому поводу дарите подарок?\n\n"
                         "Например: именины, повышение, годовщина, просто так и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await ideas_payment_step(call, state)  # Переходим к оплате после выбора всех деталей
    
    # ——————————————————————
    # Обработка постов - "Тема"
    # ——————————————————————
    elif detail_type.startswith("post_topic_"):
        topic = detail_type.replace("post_topic_", "")
        if topic == "travel":
            await state.update_data(post_topic="Путешествия")
        elif topic == "cooking":
            await state.update_data(post_topic="Кулинария")
        elif topic == "beauty":
            await state.update_data(post_topic="Красота")
        elif topic == "sport":
            await state.update_data(post_topic="Спорт")
        elif topic == "education":
            await state.update_data(post_topic="Образование")
        elif topic == "creativity":
            await state.update_data(post_topic="Творчество")
        elif topic == "other":
            # Запрашиваем ввод темы поста
            await state.set_state(IdeasStates.waiting_for_post_topic_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_topic")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="📸 О чем именно будет ваш пост?\n\n"
                         "Например: о работе, хобби, семье, питомцах, музыке и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_post_format_options(call, state)
    
    # ——————————————————————
    # Обработка постов - "Формат"
    # ——————————————————————
    elif detail_type.startswith("post_format_"):
        format_type = detail_type.replace("post_format_", "")
        if format_type == "story":
            await state.update_data(post_format="Сторис")
        elif format_type == "feed":
            await state.update_data(post_format="Пост в ленту")
        elif format_type == "carousel":
            await state.update_data(post_format="Карусель")
        elif format_type == "reel":
            await state.update_data(post_format="Рилс")
        elif format_type == "other":
            # Запрашиваем ввод формата поста
            await state.set_state(IdeasStates.waiting_for_post_format_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_format")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="📱 В каком именно формате будет ваш пост?\n\n"
                         "Например: TikTok, YouTube Shorts, Instagram TV, подкаст и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_post_audience_options(call, state)
    
    # ——————————————————————
    # Обработка постов - "Аудитория"
    # ——————————————————————
    elif detail_type.startswith("post_audience_"):
        audience = detail_type.replace("post_audience_", "")
        if audience == "friends":
            await state.update_data(post_audience="Друзья")
        elif audience == "business":
            await state.update_data(post_audience="Бизнес-аудитория")
        elif audience == "followers":
            await state.update_data(post_audience="Подписчики")
        elif audience == "general":
            await state.update_data(post_audience="Широкая аудитория")
        elif audience == "other":
            # Запрашиваем ввод аудитории поста
            await state.set_state(IdeasStates.waiting_for_post_audience_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_audience")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="👥 Для какой именно аудитории предназначен пост?\n\n"
                         "Например: коллеги, клиенты, студенты, единомышленники и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await ideas_payment_step(call, state)  # Переходим к оплате после выбора всех деталей
    
    # ——————————————————————
    # Обработка названий - "Тип бизнеса"
    # ——————————————————————
    elif detail_type.startswith("name_type_"):
        name_type = detail_type.replace("name_type_", "")
        if name_type == "cafe":
            await state.update_data(name_type="Кафе/Ресторан")
        elif name_type == "shop":
            await state.update_data(name_type="Магазин/Бренд")
        elif name_type == "app":
            await state.update_data(name_type="Приложение/IT")
        elif name_type == "blog":
            await state.update_data(name_type="Блог/Канал")
        elif name_type == "company":
            await state.update_data(name_type="Компания/Стартап")
        elif name_type == "project":
            await state.update_data(name_type="Проект/Мероприятие")
        elif name_type == "other":
            # Запрашиваем ввод типа названия
            await state.set_state(IdeasStates.waiting_for_name_type_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="✍️ Для чего именно нужно название?\n\n"
                         "Например: салон красоты, интернет-магазин, YouTube канал, подкаст и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_name_style_options(call, state)
    
    # ——————————————————————
    # Обработка названий - "Стиль"
    # ——————————————————————
    elif detail_type.startswith("name_style_"):
        style = detail_type.replace("name_style_", "")
        if style == "modern":
            await state.update_data(name_style="Современный")
        elif style == "creative":
            await state.update_data(name_style="Креативный")
        elif style == "business":
            await state.update_data(name_style="Деловой")
        elif style == "gentle":
            await state.update_data(name_style="Нежный")
        elif style == "energetic":
            await state.update_data(name_style="Энергичный")
        elif style == "other":
            # Запрашиваем ввод стиля названия
            await state.set_state(IdeasStates.waiting_for_name_style_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_type")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="🎨 Опишите желаемый стиль названия:\n\n"
                         "Например: минималистичный, винтажный, футуристичный, романтичный и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_name_audience_options(call, state)
    
    # ——————————————————————
    # Обработка названий - "Аудитория"
    # ——————————————————————
    elif detail_type.startswith("name_audience_"):
        audience = detail_type.replace("name_audience_", "")
        if audience == "children":
            await state.update_data(name_audience="Дети")
        elif audience == "youth":
            await state.update_data(name_audience="Молодежь")
        elif audience == "adults":
            await state.update_data(name_audience="Взрослые")
        elif audience == "elderly":
            await state.update_data(name_audience="Пожилые")
        elif audience == "universal":
            await state.update_data(name_audience="Универсальное")
        elif audience == "other":
            # Запрашиваем ввод аудитории названия
            await state.set_state(IdeasStates.waiting_for_name_audience_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_audience")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="👥 Опишите целевую аудиторию:\n\n"
                         "Например: студенты, предприниматели, молодые мамы, геймеры и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await ideas_payment_step(call, state)  # Переходим к оплате после выбора всех деталей
    
    # ——————————————————————
    # Обработка бизнеса - "Сфера"
    # ——————————————————————
    elif detail_type.startswith("business_sphere_"):
        sphere = detail_type.replace("business_sphere_", "")
        if sphere == "food":
            await state.update_data(business_sphere="Общепит")
        elif sphere == "retail":
            await state.update_data(business_sphere="Торговля")
        elif sphere == "tech":
            await state.update_data(business_sphere="IT/Технологии")
        elif sphere == "education":
            await state.update_data(business_sphere="Образование")
        elif sphere == "beauty":
            await state.update_data(business_sphere="Красота/Здоровье")
        elif sphere == "services":
            await state.update_data(business_sphere="Услуги")
        elif sphere == "other":
            # Запрашиваем ввод сферы бизнеса
            await state.set_state(IdeasStates.waiting_for_business_sphere_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_sphere")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="🚀 В какой именно сфере планируете бизнес?\n\n"
                         "Например: дропшиппинг, фриланс, консалтинг, производство и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_business_budget_options(call, state)
    
    # ——————————————————————
    # Обработка бизнеса - "Бюджет"
    # ——————————————————————
    elif detail_type.startswith("business_budget_"):
        budget = detail_type.replace("business_budget_", "")
        if budget == "100k":
            await state.update_data(business_budget="До 100к₽")
        elif budget == "500k":
            await state.update_data(business_budget="100к-500к₽")
        elif budget == "1m":
            await state.update_data(business_budget="500к-1млн₽")
        elif budget == "5m":
            await state.update_data(business_budget="1млн-5млн₽")
        elif budget == "5mplus":
            await state.update_data(business_budget="От 5млн₽")
        elif budget == "other":
            # Запрашиваем ввод бюджета бизнеса
            await state.set_state(IdeasStates.waiting_for_business_budget_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_budget")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="💰 Укажите ваш стартовый бюджет:\n\n"
                         "Например: без вложений, 50 тысяч, миллион рублей, привлеку инвестиции и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await show_business_scale_options(call, state)
    
    # ——————————————————————
    # Обработка бизнеса - "Масштаб"
    # ——————————————————————
    elif detail_type.startswith("business_scale_"):
        scale = detail_type.replace("business_scale_", "")
        if scale == "home":
            await state.update_data(business_scale="Домашний бизнес")
        elif scale == "local":
            await state.update_data(business_scale="Локальный")
        elif scale == "city":
            await state.update_data(business_scale="Городской")
        elif scale == "regional":
            await state.update_data(business_scale="Региональный")
        elif scale == "online":
            await state.update_data(business_scale="Онлайн")
        elif scale == "other":
            # Запрашиваем ввод масштаба бизнеса
            await state.set_state(IdeasStates.waiting_for_business_scale_other)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_scale")],
            ])
            
            if call.message and hasattr(call.message, "message_id") and call.bot is not None:
                await call.bot.edit_message_text(
                    text="📏 Опишите желаемый масштаб бизнеса:\n\n"
                         "Например: семейный бизнес, международная франшиза, B2B сервис, нишевый продукт и т.д.",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=kb
                )
                # Сохраняем ID сообщения с подсказкой для последующего удаления
                await state.update_data(hint_message_id=call.message.message_id)
            await safe_answer_callback(call, state)
            return
        
        await ideas_payment_step(call, state)  # Переходим к оплате после выбора всех деталей
    
    else:
        await call.answer(text="❌ Неизвестный вариант деталей.")
    
    await safe_answer_callback(call, state)


# ——————————————————————
# Выбор стиля
# ——————————————————————
@router.callback_query(F.data.startswith("ideas_style:"))
async def ideas_select_style(call: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор стиля идеи."""
    style = call.data.split(":", 1)[1] if call.data and ":" in call.data else ""
    
    if style == "other":
        # Если выбрано "Другое", запрашиваем ввод стиля
        await state.set_state(IdeasStates.waiting_for_style)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_category_back")],
        ])
        
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text="🌟 Введите, какое настроение или эффект должна передавать идея:\n\n"
                     "Например: загадочно, по-домашнему, по-деловому, романтично и т.д.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
        await safe_answer_callback(call, state)
        return
    
    # Сохраняем стиль и переходим к ограничениям
    await state.update_data(style=style)
    await state.set_state(IdeasStates.input_constraints)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, есть", callback_data="ideas_constraints:yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="ideas_constraints:no")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_category_back")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="Есть ли у тебя ограничения или пожелания?\n(например: коротко, только по-русски, без слов «lux»)",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Обработка ограничений
# ——————————————————————
@router.callback_query(F.data.startswith("ideas_constraints:"))
async def ideas_constraints_choice(call: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор наличия ограничений."""
    choice = call.data.split(":", 1)[1] if call.data and ":" in call.data else ""
    
    if choice == "yes":
        # Запрашиваем ввод ограничений
        await state.set_state(IdeasStates.waiting_for_constraints)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_style_back")],
        ])
        
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text="Введите ваши ограничения или пожелания:",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
    else:
        # Переходим к оплате без ограничений
        await state.update_data(constraints="")
        await ideas_payment_step(call, state)
    
    await safe_answer_callback(call, state)


# ——————————————————————
# Ввод ограничений
# ——————————————————————
@router.message(IdeasStates.waiting_for_constraints)
async def ideas_input_constraints(message: types.Message, state: FSMContext):
    """Получает ограничения от пользователя."""
    constraints = message.text or ""
    if len(constraints) > 255:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткие ограничения.")
        return

    await state.update_data(constraints=constraints)
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Переходим к оплате
    await ideas_payment_step_from_message(message, state)


# ——————————————————————
# Шаг оплаты
# ——————————————————————
async def ideas_payment_step(call: CallbackQuery, state: FSMContext):
    """Показывает шаг оплаты."""
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return

    # Проверяем подписку
    if await is_subscribed(user_id):
        # Если есть подписка, сразу генерируем идеи
        await generate_ideas_for_user(call, state)
    else:
        # Определяем правильный callback для кнопки "Назад" в зависимости от категории
        data = await state.get_data()
        category = data.get("category", "")
        
        if category == "gift":
            back_callback = "gift_back_to_occasion"
        elif category == "post":
            back_callback = "post_back_to_audience"
        elif category == "name":
            back_callback = "name_back_to_audience"
        elif category == "business":
            back_callback = "business_back_to_scale"
        else:
            # Для других случаев (например, при выборе ограничений)
            back_callback = "ideas_constraints_back"
        
        # Создаем платеж
        url, pid = await create_payment(user_id, 100, "Оплата за идеи")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 100₽", url=url)],
            [InlineKeyboardButton(text="📬 Получить идеи", callback_data=f"check_ideas:{pid}")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data=back_callback)],
        ])
        
        if call.message and hasattr(call.message, "message_id") and call.bot is not None:
            await call.bot.edit_message_text(
                text=PAYMENT_MESSAGE,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )


async def ideas_payment_step_from_message(message: types.Message, state: FSMContext):
    """Показывает шаг оплаты из сообщения."""
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("❌ Не удалось определить пользователя. Попробуйте еще раз.")
        return

    # Проверяем подписку
    if await is_subscribed(user_id):
        # Если есть подписка, сразу генерируем идеи
        await generate_ideas_for_user_from_message(message, state)
    else:
        # Определяем правильный callback для кнопки "Назад" в зависимости от категории
        data = await state.get_data()
        category = data.get("category", "")
        
        if category == "gift":
            back_callback = "gift_back_to_occasion"
        elif category == "post":
            back_callback = "post_back_to_audience"
        elif category == "name":
            back_callback = "name_back_to_audience"
        elif category == "business":
            back_callback = "business_back_to_scale"
        else:
            # Для других случаев (например, при выборе ограничений)
            back_callback = "ideas_constraints_back"
        
        # Создаем платеж
        url, pid = await create_payment(user_id, 100, "Оплата за идеи")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить 100₽", url=url)],
            [InlineKeyboardButton(text="📬 Получить идеи", callback_data=f"check_ideas:{pid}")],
            [InlineKeyboardButton(text="⏎ Назад", callback_data=back_callback)],
        ])
        
        await message.answer(
            text=PAYMENT_MESSAGE,
            reply_markup=kb
        )


# ——————————————————————
# Проверка оплаты
# ——————————————————————
@router.callback_query(F.data.startswith("check_ideas:"))
async def check_ideas_payment(call: CallbackQuery, state: FSMContext):
    """Проверяет статус платежа и генерирует идеи."""
    pid = call.data.split(":", 1)[1] if call.data and ":" in call.data else None
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return

    status = await check_payment_status(pid)

    if status != "succeeded":
        await call.answer(text="❌ Платёж не подтверждён", show_alert=True)
        logger.warning(
            f"Платёж {pid} пользователя {user_id} для идей не подтверждён "
            f"(статус={status})"
        )
        return

    logger.info(f"Пользователь {user_id} получил идеи (payment_id={pid})")

    await safe_answer_callback(call, state)
    
    # Удаляем сообщение с оплатой
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)

    await generate_ideas_for_user(call, state)


# ——————————————————————
# Генерация идей для пользователя
# ——————————————————————
async def generate_ideas_for_user(call: CallbackQuery, state: FSMContext):
    """Генерирует идеи для пользователя."""
    data = await state.get_data()
    category = data.get("category", "")
    style = data.get("style", "")
    constraints = data.get("constraints", "")
    
    # Формируем подробное описание на основе выбранных деталей
    details = []
    
    # Для подарков
    if category == "gift":
        recipient = data.get("gift_recipient", "")
        budget = data.get("gift_budget", "")
        occasion = data.get("gift_occasion", "")
        
        if recipient:
            details.append(f"Кому: {recipient}")
        if budget:
            details.append(f"Бюджет: {budget}")
        if occasion:
            details.append(f"Повод: {occasion}")
    
    # Для постов
    elif category == "post":
        topic = data.get("post_topic", "")
        format_type = data.get("post_format", "")
        audience = data.get("post_audience", "")
        
        if topic:
            details.append(f"Тема: {topic}")
        if format_type:
            details.append(f"Формат: {format_type}")
        if audience:
            details.append(f"Аудитория: {audience}")
    
    # Для названий
    elif category == "name":
        name_type = data.get("name_type", "")
        name_style = data.get("name_style", "")
        name_audience = data.get("name_audience", "")
        
        if name_type:
            details.append(f"Тип: {name_type}")
        if name_style:
            details.append(f"Стиль: {name_style}")
        if name_audience:
            details.append(f"Аудитория: {name_audience}")
    
    # Для бизнеса
    elif category == "business":
        business_sphere = data.get("business_sphere", "")
        business_budget = data.get("business_budget", "")
        business_scale = data.get("business_scale", "")
        
        if business_sphere:
            details.append(f"Сфера: {business_sphere}")
        if business_budget:
            details.append(f"Бюджет: {business_budget}")
        if business_scale:
            details.append(f"Масштаб: {business_scale}")
    
    # Объединяем детали в строку
    detailed_category = category
    if details:
        detailed_category += " (" + ", ".join(details) + ")"
    
    loading = None
    if call.message and call.bot is not None:
        loading = await call.bot.send_message(chat_id=call.message.chat.id, text="⚙️ Создаем идеи...")

    try:
        # Получаем предыдущие идеи для избежания повторов
        previous_ideas_history = data.get("ideas_history", [])
        ideas = await generate_ideas(detailed_category, style, constraints, previous_ideas_history)
        
        # Обновляем историю идей
        updated_history = previous_ideas_history + [ideas]
        await state.update_data(
            current_ideas=ideas,
            regeneration_count=0,
            is_surprise=False,
            ideas_history=updated_history,
            edits=[]  # Инициализируем пустой список правок
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Сгенерировать ещё (0/5)", callback_data="regenerate_ideas"),
                InlineKeyboardButton(text="🎯 Хочу доработать (0/5)", callback_data="edit_ideas"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])

        if call.message and call.bot is not None:
            await call.bot.send_message(
                chat_id=call.message.chat.id,
                text=f"✨ Вот что мы придумали:\n\n{ideas}",
                reply_markup=kb
            )
            if loading:
                await call.bot.delete_message(chat_id=call.message.chat.id, message_id=loading.message_id)

    except Exception as e:
        logger.error(f"Ошибка генерации идей для {call.from_user.id}: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="ideas_start_process")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        if call.message and call.bot is not None:
            await call.bot.edit_message_text(
                text="❌ Произошла ошибка при создании идей. Попробуйте еще раз.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
            if loading:
                await call.bot.delete_message(chat_id=call.message.chat.id, message_id=loading.message_id)


async def generate_ideas_for_user_from_message(message: types.Message, state: FSMContext):
    """Генерирует идеи для пользователя из сообщения."""
    data = await state.get_data()
    category = data.get("category", "")
    style = data.get("style", "")
    constraints = data.get("constraints", "")
    
    # Формируем подробное описание на основе выбранных деталей
    details = []
    
    # Для подарков
    if category == "gift":
        recipient = data.get("gift_recipient", "")
        budget = data.get("gift_budget", "")
        occasion = data.get("gift_occasion", "")
        
        if recipient:
            details.append(f"Кому: {recipient}")
        if budget:
            details.append(f"Бюджет: {budget}")
        if occasion:
            details.append(f"Повод: {occasion}")
    
    # Для постов
    elif category == "post":
        topic = data.get("post_topic", "")
        format_type = data.get("post_format", "")
        audience = data.get("post_audience", "")
        
        if topic:
            details.append(f"Тема: {topic}")
        if format_type:
            details.append(f"Формат: {format_type}")
        if audience:
            details.append(f"Аудитория: {audience}")
    
    # Для названий
    elif category == "name":
        name_type = data.get("name_type", "")
        name_style = data.get("name_style", "")
        name_audience = data.get("name_audience", "")
        
        if name_type:
            details.append(f"Тип: {name_type}")
        if name_style:
            details.append(f"Стиль: {name_style}")
        if name_audience:
            details.append(f"Аудитория: {name_audience}")
    
    # Для бизнеса
    elif category == "business":
        business_sphere = data.get("business_sphere", "")
        business_budget = data.get("business_budget", "")
        business_scale = data.get("business_scale", "")
        
        if business_sphere:
            details.append(f"Сфера: {business_sphere}")
        if business_budget:
            details.append(f"Бюджет: {business_budget}")
        if business_scale:
            details.append(f"Масштаб: {business_scale}")
    
    # Объединяем детали в строку
    detailed_category = category
    if details:
        detailed_category += " (" + ", ".join(details) + ")"
    
    loading = await message.answer("⚙️ Создаем идеи...")

    try:
        # Получаем предыдущие идеи для избежания повторов
        previous_ideas_history = data.get("ideas_history", [])
        ideas = await generate_ideas(detailed_category, style, constraints, previous_ideas_history)
        
        # Обновляем историю идей
        updated_history = previous_ideas_history + [ideas]
        await state.update_data(
            current_ideas=ideas,
            regeneration_count=0,
            is_surprise=False,
            ideas_history=updated_history,
            edits=[]  # Инициализируем пустой список правок
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Сгенерировать ещё (0/5)", callback_data="regenerate_ideas"),
                InlineKeyboardButton(text="🎯 Хочу доработать (0/5)", callback_data="edit_ideas"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])

        await message.answer(
            text=f"✨ Вот что мы придумали:\n\n{ideas}",
            reply_markup=kb
        )
        await loading.delete()

    except Exception as e:
        logger.error(f"Ошибка генерации идей для {message.from_user.id}: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="ideas_start_process")],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        await message.answer(
            text="❌ Произошла ошибка при создании идей. Попробуйте еще раз.",
            reply_markup=kb
        )
        await loading.delete()


# ——————————————————————
# Редактирование идей
# ——————————————————————
@router.callback_query(F.data == "edit_ideas")
async def edit_ideas_start(call: CallbackQuery, state: FSMContext):
    """Запрашивает уточнения для идей."""
    data = await state.get_data()
    cnt = data.get("regeneration_count", 0)
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return

    max_attempts = 10 if await is_subscribed(user_id) else 5
    if cnt >= max_attempts:
        await call.answer(text="❌ Достигнут лимит попыток", show_alert=True)
        return

    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🎯 Что бы вы хотели изменить или уточнить в идеях?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_ideas")]
            ])
        )
        # Сохраняем ID сообщения с подсказкой для последующего удаления
        await state.update_data(edit_hint_message_id=call.message.message_id)
    await state.set_state(IdeasStates.input_edit_prompt)
    await safe_answer_callback(call, state)


@router.message(IdeasStates.input_edit_prompt)
async def input_edit_prompt(message: types.Message, state: FSMContext):
    """Получает уточнения от пользователя."""
    edit_text = (message.text or "").strip()
    await message.delete()

    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение с подсказкой, если оно есть
    edit_hint_message_id = data.get("edit_hint_message_id")
    if edit_hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=edit_hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    loading = await message.answer("⚙️ Вносим изменения...")

    category = data.get("category", "")
    style = data.get("style", "")
    constraints = data.get("constraints", "")
    edits = data.get("edits", [])
    edits.append(edit_text)
    cnt = data.get("regeneration_count", 0) + 1
    await state.update_data(edits=edits, regeneration_count=cnt)

    try:
        # Получаем предыдущие идеи для избежания повторов
        previous_ideas_history = data.get("ideas_history", [])
        new_ideas = await generate_ideas_with_edits(category, style, constraints, edits, previous_ideas_history)
        
        # Обновляем историю идей
        updated_history = previous_ideas_history + [new_ideas]
        await state.update_data(current_ideas=new_ideas, ideas_history=updated_history)

        user_id = message.from_user.id if message.from_user else None
        if user_id is None:
            await message.answer("❌ Не удалось определить пользователя. Попробуйте еще раз.")
            return

        max_attempts = 10 if await is_subscribed(user_id) else 5
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔄 Сгенерировать ещё ({cnt}/{max_attempts})", callback_data="regenerate_ideas"),
                InlineKeyboardButton(text=f"🎯 Хочу доработать ({cnt}/{max_attempts})", callback_data="edit_ideas"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        await message.answer(new_ideas, reply_markup=kb)
    except Exception as e:
        logger.error(f"Ошибка редактирования идей для {message.from_user.id}: {e}")
        await message.answer("❌ Произошла ошибка при редактировании идей. Попробуйте еще раз.")

    if loading and hasattr(loading, 'chat') and hasattr(loading, 'message_id') and message.bot is not None:
        await message.bot.delete_message(chat_id=loading.chat.id, message_id=loading.message_id)
    await state.set_state(None)


# ——————————————————————
# Регенерация идей
# ——————————————————————
@router.callback_query(F.data == "regenerate_ideas")
async def regenerate_ideas(call: CallbackQuery, state: FSMContext):
    """Создает новые идеи с учетом лимита попыток."""
    user_id = call.from_user.id if call.from_user else None
    if user_id is None:
        await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
        return

    max_attempts = 10 if await is_subscribed(user_id) else 5
    data = await state.get_data()
    cnt = data.get("regeneration_count", 0)
    if cnt >= max_attempts:
        await call.answer(text="❌ Достигнут лимит попыток", show_alert=True)
        return

    cnt += 1
    await state.update_data(regeneration_count=cnt)

    category = data.get("category", "")
    style = data.get("style", "")
    constraints = data.get("constraints", "")
    edits = data.get("edits", [])

    # Формируем подробное описание на основе выбранных деталей
    details = []
    
    # Для подарков
    if category == "gift":
        recipient = data.get("gift_recipient", "")
        budget = data.get("gift_budget", "")
        occasion = data.get("gift_occasion", "")
        
        if recipient:
            details.append(f"Кому: {recipient}")
        if budget:
            details.append(f"Бюджет: {budget}")
        if occasion:
            details.append(f"Повод: {occasion}")
    
    # Для постов
    elif category == "post":
        topic = data.get("post_topic", "")
        format_type = data.get("post_format", "")
        audience = data.get("post_audience", "")
        
        if topic:
            details.append(f"Тема: {topic}")
        if format_type:
            details.append(f"Формат: {format_type}")
        if audience:
            details.append(f"Аудитория: {audience}")
    
    # Для названий
    elif category == "name":
        name_type = data.get("name_type", "")
        name_style = data.get("name_style", "")
        name_audience = data.get("name_audience", "")
        
        if name_type:
            details.append(f"Тип: {name_type}")
        if name_style:
            details.append(f"Стиль: {name_style}")
        if name_audience:
            details.append(f"Аудитория: {name_audience}")
    
    # Для бизнеса
    elif category == "business":
        business_sphere = data.get("business_sphere", "")
        business_budget = data.get("business_budget", "")
        business_scale = data.get("business_scale", "")
        
        if business_sphere:
            details.append(f"Сфера: {business_sphere}")
        if business_budget:
            details.append(f"Бюджет: {business_budget}")
        if business_scale:
            details.append(f"Масштаб: {business_scale}")
    
    # Объединяем детали в строку
    detailed_category = category
    if details:
        detailed_category += " (" + ", ".join(details) + ")"

    # Удаляем текущее сообщение с идеями
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        try:
            await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except TelegramBadRequest:
            pass

    # Отправляем сообщение ожидания
    loading = None
    if call.message and call.bot is not None:
        loading = await call.bot.send_message(chat_id=call.message.chat.id, text="⚙️ Создаем новые идеи...")

    try:
        # Получаем предыдущие идеи для избежания повторов
        previous_ideas_history = data.get("ideas_history", [])
        
        if edits:
            new_ideas = await generate_ideas_with_edits(detailed_category, style, constraints, edits, previous_ideas_history)
        else:
            new_ideas = await generate_ideas(detailed_category, style, constraints, previous_ideas_history)
    except Exception as e:
        logger.error(f"Ошибка регенерации идей для {user_id}: {e}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="regenerate_ideas")],
            [InlineKeyboardButton(text="✉️ Написать в поддержку", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="⏎ Назад", callback_data="go_back_ideas")],
        ])
        if loading and call.bot is not None and call.message is not None:
            try:
                await call.bot.edit_message_text(
                    text="❌ Произошла ошибка при создании идей.",
                    chat_id=call.message.chat.id,
                    message_id=loading.message_id,
                    reply_markup=kb
                )
            except TelegramBadRequest:
                pass
        await safe_answer_callback(call, state)
        return

    # Обновляем историю идей
    previous_ideas_history = data.get("ideas_history", [])
    updated_history = previous_ideas_history + [new_ideas]
    await state.update_data(current_ideas=new_ideas, ideas_history=updated_history)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🔄 Сгенерировать ещё ({cnt}/{max_attempts})", callback_data="regenerate_ideas"),
            InlineKeyboardButton(text=f"🎯 Хочу доработать ({cnt}/{max_attempts})", callback_data="edit_ideas"),
        ],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
    ])

    # Удаляем сообщение ожидания и отправляем новые идеи
    if loading and call.bot is not None and call.message is not None:
        try:
            await call.bot.delete_message(chat_id=call.message.chat.id, message_id=loading.message_id)
        except TelegramBadRequest:
            pass
        await call.bot.send_message(
            chat_id=call.message.chat.id,
            text=f"✨ Вот что мы придумали:\n\n{new_ideas}",
            reply_markup=kb
        )


# ——————————————————————
# Получение пользовательской категории
# ——————————————————————
@router.message(IdeasStates.waiting_for_category)
async def input_custom_category(message: types.Message, state: FSMContext):
    """Получает пользовательскую категорию от пользователя."""
    category = (message.text or "").strip()
    if len(category) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(category=category)
    await state.set_state(IdeasStates.select_style)
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Переходим к выбору стиля
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😊 Веселье", callback_data="ideas_style:fun")],
        [InlineKeyboardButton(text="🌸 Нежность", callback_data="ideas_style:tender")],
        [InlineKeyboardButton(text="🔥 Дерзко", callback_data="ideas_style:bold")],
        [InlineKeyboardButton(text="🎩 Стильно", callback_data="ideas_style:stylish")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_style:other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_category_back")],
    ])
    
    await message.answer(
        text="🌟 Поделитесь, какое настроение или эффект должна нести ваша идея",
        reply_markup=kb
    )


# ——————————————————————
# Получение пользовательского стиля
# ——————————————————————
@router.message(IdeasStates.waiting_for_style)
async def input_custom_style(message: types.Message, state: FSMContext):
    """Получает пользовательский стиль от пользователя."""
    style = (message.text or "").strip()
    if len(style) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(style=style)
    await state.set_state(IdeasStates.input_constraints)
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Переходим к ограничениям
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, есть", callback_data="ideas_constraints:yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="ideas_constraints:no")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_style_back")],
    ])
    
    await message.answer(
        text="Есть ли у тебя ограничения или пожелания?\n(например: коротко, только по-русски, без слов «lux»)",
        reply_markup=kb
    )


# ——————————————————————
# Получение назначения для названий
# ——————————————————————
@router.message(IdeasStates.waiting_for_name_purpose)
async def input_name_purpose(message: types.Message, state: FSMContext):
    """Получает назначение для названий от пользователя."""
    purpose = (message.text or "").strip()
    if len(purpose) > 200:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(name_purpose=purpose, category=f"название для {purpose}")
    await state.set_state(IdeasStates.select_style)
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Переходим к выбору стиля
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😊 Веселье", callback_data="ideas_style:fun")],
        [InlineKeyboardButton(text="🌸 Нежность", callback_data="ideas_style:tender")],
        [InlineKeyboardButton(text="🔥 Дерзко", callback_data="ideas_style:bold")],
        [InlineKeyboardButton(text="🎩 Стильно", callback_data="ideas_style:stylish")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_style:other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_category_back")],
    ])
    
    await message.answer(
        text="🌟 Поделитесь, какое настроение или эффект должно передавать название",
        reply_markup=kb
    )


# ——————————————————————
# Получение назначения для бизнеса
# ——————————————————————
@router.message(IdeasStates.waiting_for_business_purpose)
async def input_business_purpose(message: types.Message, state: FSMContext):
    """Получает назначение для бизнеса от пользователя."""
    purpose = (message.text or "").strip()
    if len(purpose) > 200:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(business_purpose=purpose, category=f"бизнес-идея для {purpose}")
    await state.set_state(IdeasStates.select_style)
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Переходим к выбору стиля
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😊 Веселье", callback_data="ideas_style:fun")],
        [InlineKeyboardButton(text="🌸 Нежность", callback_data="ideas_style:tender")],
        [InlineKeyboardButton(text="🔥 Дерзко", callback_data="ideas_style:bold")],
        [InlineKeyboardButton(text="🎩 Стильно", callback_data="ideas_style:stylish")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_style:other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_category_back")],
    ])
    
    await message.answer(
        text="🌟 Поделитесь, какое настроение или эффект должна передавать бизнес-идея",
        reply_markup=kb
    )


# ——————————————————————
# Обработка кнопок "Назад" для каждого шага
# ——————————————————————
@router.callback_query(F.data == "ideas_select_category_back")
async def go_back_to_category_selection(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору категории."""
    await state.set_state(IdeasStates.select_category)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Подарок", callback_data="ideas_category:gift")],
        [InlineKeyboardButton(text="📸 Пост", callback_data="ideas_category:post")],
        [InlineKeyboardButton(text="✍️ Название", callback_data="ideas_category:name")],
        [InlineKeyboardButton(text="🚀 Бизнес", callback_data="ideas_category:business")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_category:other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="start")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text='✨ Добро пожаловать в мастерскую идей!\n\n'
                '♡ Определите, для чего нужна идея: подарок, пост, название, бизнес, либо ваш вариант?\n'
                '✎ Уточните пожелания\n'
                '✓ Завершите оформление: оплатите заказ и получите 3 уникальные идеи\n\n'
                'Готовы вдохновиться?\n\n'
                '👇 Давайте начнем с выбора категории',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "ideas_select_style_back")
async def go_back_to_style_selection(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору стиля."""
    data = await state.get_data()
    category = data.get("category", "")
    
    await state.set_state(IdeasStates.select_style)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😊 Веселье", callback_data="ideas_style:fun")],
        [InlineKeyboardButton(text="🌸 Нежность", callback_data="ideas_style:tender")],
        [InlineKeyboardButton(text="🔥 Дерзко", callback_data="ideas_style:bold")],
        [InlineKeyboardButton(text="🎩 Стильно", callback_data="ideas_style:stylish")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_style:other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_category_back")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🌟 Поделитесь, какое настроение или эффект должна нести ваша идея",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "ideas_constraints_back")
async def go_back_to_constraints_selection(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору ограничений."""
    await state.set_state(IdeasStates.input_constraints)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, есть", callback_data="ideas_constraints:yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="ideas_constraints:no")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_select_style_back")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="Есть ли у тебя ограничения или пожелания?\n(например: коротко, только по-русски, без слов «lux»)",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Универсальный возврат назад
# ——————————————————————
@router.callback_query(F.data == "go_back_ideas")
async def go_back_ideas(call: CallbackQuery, state: FSMContext):
    """Универсальный «Назад» для flow идей."""
    current = await state.get_state()
    data = await state.get_data()

    if current == IdeasStates.input_edit_prompt.state:
        ideas = data.get("current_ideas", "")
        cnt = data.get("regeneration_count", 0)
        user_id = call.from_user.id if call.from_user else None
        if user_id is None:
            await call.answer(text="❌ Не удалось определить пользователя.", show_alert=True)
            return
        max_attempts = 10 if await is_subscribed(user_id) else 5
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔄 Сгенерировать ещё ({cnt}/{max_attempts})", callback_data="regenerate_ideas"),
                InlineKeyboardButton(text=f"🎯 Хочу доработать ({cnt}/{max_attempts})", callback_data="edit_ideas"),
            ],
            [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
        ])
        await safe_edit_text(call.message, text=f"✨ Вот что мы придумали:\n\n{ideas}", reply_markup=kb)
        await state.set_state(None)
        await safe_answer_callback(call, state)
        return

    if current in [IdeasStates.select_category.state, IdeasStates.select_style.state, 
                   IdeasStates.input_constraints.state, IdeasStates.waiting_for_constraints.state]:
        await ideas_start_process(call, state)
        return

    await state.clear()
    if call.message and hasattr(call.message, "chat") and hasattr(call.message, "message_id") and call.bot is not None:
        # Сначала убираем кнопки из сообщения с идеями, сохраняя текст
        try:
            await call.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except TelegramBadRequest:
            # Если не удалось убрать кнопки, игнорируем ошибку
            pass
        
        # Потом отправляем новое сообщение с главным меню
        await call.bot.send_message(
            chat_id=call.message.chat.id,
            text=START_TEXT,
            reply_markup=get_main_menu_kb()
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Обработчики пользовательского ввода для "Другое"
# ——————————————————————
@router.message(IdeasStates.waiting_for_gift_recipient_other)
async def input_gift_recipient_other(message: types.Message, state: FSMContext):
    """Получает получателя подарка от пользователя."""
    recipient = (message.text or "").strip()
    if len(recipient) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(gift_recipient=recipient)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору бюджета
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 До 1000₽", callback_data="ideas_detail:gift_budget_1000")],
        [InlineKeyboardButton(text="💰 1000-3000₽", callback_data="ideas_detail:gift_budget_3000")],
        [InlineKeyboardButton(text="💰 3000-5000₽", callback_data="ideas_detail:gift_budget_5000")],
        [InlineKeyboardButton(text="💰 5000-10000₽", callback_data="ideas_detail:gift_budget_10000")],
        [InlineKeyboardButton(text="💰 От 10000₽", callback_data="ideas_detail:gift_budget_10000plus")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_budget_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_recipient")],
    ])
    
    await message.answer(
        text="💰 Какой у вас бюджет на подарок?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_gift_budget_other)
async def input_gift_budget_other(message: types.Message, state: FSMContext):
    """Получает бюджет подарка от пользователя."""
    budget = (message.text or "").strip()
    if len(budget) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(gift_budget=budget)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору повода
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎂 День рождения", callback_data="ideas_detail:gift_occasion_birthday")],
        [InlineKeyboardButton(text="💝 День святого Валентина", callback_data="ideas_detail:gift_occasion_valentine")],
        [InlineKeyboardButton(text="🎄 Новый год", callback_data="ideas_detail:gift_occasion_newyear")],
        [InlineKeyboardButton(text="👰 Свадьба", callback_data="ideas_detail:gift_occasion_wedding")],
        [InlineKeyboardButton(text="🎓 Выпускной", callback_data="ideas_detail:gift_occasion_graduation")],
        [InlineKeyboardButton(text="🏠 Новоселье", callback_data="ideas_detail:gift_occasion_housewarming")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_occasion_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_budget")],
    ])
    
    await message.answer(
        text="🎉 По какому поводу дарите подарок?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_gift_occasion_other)
async def input_gift_occasion_other(message: types.Message, state: FSMContext):
    """Получает повод для подарка от пользователя."""
    occasion = (message.text or "").strip()
    if len(occasion) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(gift_occasion=occasion)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к оплате
    await ideas_payment_step_from_message(message, state)


@router.message(IdeasStates.waiting_for_post_topic_other)
async def input_post_topic_other(message: types.Message, state: FSMContext):
    """Получает тему поста от пользователя."""
    topic = (message.text or "").strip()
    if len(topic) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(post_topic=topic)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору формата
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Сторис", callback_data="ideas_detail:post_format_story")],
        [InlineKeyboardButton(text="📷 Пост в ленту", callback_data="ideas_detail:post_format_feed")],
        [InlineKeyboardButton(text="🎠 Карусель", callback_data="ideas_detail:post_format_carousel")],
        [InlineKeyboardButton(text="🎬 Рилс", callback_data="ideas_detail:post_format_reel")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_format_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_topic")],
    ])
    
    await message.answer(
        text="📱 В каком формате будет ваш пост?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_post_format_other)
async def input_post_format_other(message: types.Message, state: FSMContext):
    """Получает формат поста от пользователя."""
    format_type = (message.text or "").strip()
    if len(format_type) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(post_format=format_type)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору аудитории
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Друзья", callback_data="ideas_detail:post_audience_friends")],
        [InlineKeyboardButton(text="💼 Бизнес-аудитория", callback_data="ideas_detail:post_audience_business")],
        [InlineKeyboardButton(text="👤 Подписчики", callback_data="ideas_detail:post_audience_followers")],
        [InlineKeyboardButton(text="🌍 Широкая аудитория", callback_data="ideas_detail:post_audience_general")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_audience_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_format")],
    ])
    
    await message.answer(
        text="👥 Для какой аудитории предназначен пост?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_post_audience_other)
async def input_post_audience_other(message: types.Message, state: FSMContext):
    """Получает аудитории поста от пользователя."""
    audience = (message.text or "").strip()
    if len(audience) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(post_audience=audience)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к оплате
    await ideas_payment_step_from_message(message, state)


# ——————————————————————
# Обработчики кнопок "Назад" для "Другое"
# ——————————————————————
@router.callback_query(F.data == "gift_back_to_recipient")
async def gift_back_to_recipient(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору получателя подарка."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👩 Маме", callback_data="ideas_detail:gift_who_mom")],
        [InlineKeyboardButton(text="👨 Папе", callback_data="ideas_detail:gift_who_dad")],
        [InlineKeyboardButton(text="💕 Девушке/Парню", callback_data="ideas_detail:gift_who_partner")],
        [InlineKeyboardButton(text="👶 Ребенку", callback_data="ideas_detail:gift_who_child")],
        [InlineKeyboardButton(text="👥 Другу", callback_data="ideas_detail:gift_who_friend")],
        [InlineKeyboardButton(text="👔 Коллеге", callback_data="ideas_detail:gift_who_colleague")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_who_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🎁 Отлично! Кому дарите подарок?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "gift_back_to_budget")
async def gift_back_to_budget(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору бюджета подарка."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 До 1000₽", callback_data="ideas_detail:gift_budget_1000")],
        [InlineKeyboardButton(text="💰 1000-3000₽", callback_data="ideas_detail:gift_budget_3000")],
        [InlineKeyboardButton(text="💰 3000-5000₽", callback_data="ideas_detail:gift_budget_5000")],
        [InlineKeyboardButton(text="💰 5000-10000₽", callback_data="ideas_detail:gift_budget_10000")],
        [InlineKeyboardButton(text="💰 От 10000₽", callback_data="ideas_detail:gift_budget_10000plus")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_budget_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_recipient")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="💰 Какой у вас бюджет на подарок?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "gift_back_to_occasion")
async def gift_back_to_occasion(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору повода для подарка."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎂 День рождения", callback_data="ideas_detail:gift_occasion_birthday")],
        [InlineKeyboardButton(text="💝 День святого Валентина", callback_data="ideas_detail:gift_occasion_valentine")],
        [InlineKeyboardButton(text="🎄 Новый год", callback_data="ideas_detail:gift_occasion_newyear")],
        [InlineKeyboardButton(text="👰 Свадьба", callback_data="ideas_detail:gift_occasion_wedding")],
        [InlineKeyboardButton(text="🎓 Выпускной", callback_data="ideas_detail:gift_occasion_graduation")],
        [InlineKeyboardButton(text="🏠 Новоселье", callback_data="ideas_detail:gift_occasion_housewarming")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:gift_occasion_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="gift_back_to_budget")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🎉 По какому поводу дарите подарок?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "post_back_to_topic")
async def post_back_to_topic(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору темы поста."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✈️ Путешествия", callback_data="ideas_detail:post_topic_travel")],
        [InlineKeyboardButton(text="🍳 Кулинария", callback_data="ideas_detail:post_topic_cooking")],
        [InlineKeyboardButton(text="💄 Красота", callback_data="ideas_detail:post_topic_beauty")],
        [InlineKeyboardButton(text="💪 Спорт", callback_data="ideas_detail:post_topic_sport")],
        [InlineKeyboardButton(text="📚 Образование", callback_data="ideas_detail:post_topic_education")],
        [InlineKeyboardButton(text="🎨 Творчество", callback_data="ideas_detail:post_topic_creativity")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_topic_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="📸 Отлично! О чем будет ваш пост?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "post_back_to_format")
async def post_back_to_format(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору формата поста."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Сторис", callback_data="ideas_detail:post_format_story")],
        [InlineKeyboardButton(text="📷 Пост в ленту", callback_data="ideas_detail:post_format_feed")],
        [InlineKeyboardButton(text="🎠 Карусель", callback_data="ideas_detail:post_format_carousel")],
        [InlineKeyboardButton(text="🎬 Рилс", callback_data="ideas_detail:post_format_reel")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_format_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_topic")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="📱 В каком формате будет ваш пост?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "post_back_to_audience")
async def post_back_to_audience(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору аудитории поста."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Друзья", callback_data="ideas_detail:post_audience_friends")],
        [InlineKeyboardButton(text="💼 Бизнес-аудитория", callback_data="ideas_detail:post_audience_business")],
        [InlineKeyboardButton(text="👤 Подписчики", callback_data="ideas_detail:post_audience_followers")],
        [InlineKeyboardButton(text="🌍 Широкая аудитория", callback_data="ideas_detail:post_audience_general")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:post_audience_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="post_back_to_format")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="👥 Для какой аудитории предназначен пост?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "name_back_to_audience")
async def name_back_to_audience(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору аудитории для названий."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👶 Дети", callback_data="ideas_detail:name_audience_children")],
        [InlineKeyboardButton(text="🧑 Молодежь", callback_data="ideas_detail:name_audience_youth")],
        [InlineKeyboardButton(text="👨‍💼 Взрослые", callback_data="ideas_detail:name_audience_adults")],
        [InlineKeyboardButton(text="👵 Пожилые", callback_data="ideas_detail:name_audience_elderly")],
        [InlineKeyboardButton(text="🌍 Универсальное", callback_data="ideas_detail:name_audience_universal")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_audience_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_style")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="👥 Для какой аудитории предназначено?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "name_back_to_type")
async def name_back_to_type(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору типа названия."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Кафе/Ресторан", callback_data="ideas_detail:name_type_cafe")],
        [InlineKeyboardButton(text="🛍️ Магазин/Бренд", callback_data="ideas_detail:name_type_shop")],
        [InlineKeyboardButton(text="📱 Приложение/IT", callback_data="ideas_detail:name_type_app")],
        [InlineKeyboardButton(text="📝 Блог/Канал", callback_data="ideas_detail:name_type_blog")],
        [InlineKeyboardButton(text="🏢 Компания/Стартап", callback_data="ideas_detail:name_type_company")],
        [InlineKeyboardButton(text="🎯 Проект/Мероприятие", callback_data="ideas_detail:name_type_project")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_type_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="✍️ Для чего нужно название?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "name_back_to_style")
async def name_back_to_style(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору стиля названия."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Современный", callback_data="ideas_detail:name_style_modern")],
        [InlineKeyboardButton(text="🎨 Креативный", callback_data="ideas_detail:name_style_creative")],
        [InlineKeyboardButton(text="💼 Деловой", callback_data="ideas_detail:name_style_business")],
        [InlineKeyboardButton(text="🌸 Нежный", callback_data="ideas_detail:name_style_gentle")],
        [InlineKeyboardButton(text="⚡ Энергичный", callback_data="ideas_detail:name_style_energetic")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_style_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_type")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🎨 Какой стиль названия предпочитаете?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


@router.callback_query(F.data == "business_back_to_scale")
async def business_back_to_scale(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору масштаба бизнеса."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Домашний бизнес", callback_data="ideas_detail:business_scale_home")],
        [InlineKeyboardButton(text="🏪 Локальный", callback_data="ideas_detail:business_scale_local")],
        [InlineKeyboardButton(text="🏙️ Городской", callback_data="ideas_detail:business_scale_city")],
        [InlineKeyboardButton(text="🌍 Региональный", callback_data="ideas_detail:business_scale_regional")],
        [InlineKeyboardButton(text="🌐 Онлайн", callback_data="ideas_detail:business_scale_online")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_scale_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_budget")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="📏 Какого масштаба планируете бизнес?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Обработчики ввода пользовательского текста для "Другое"
# ——————————————————————
@router.message(IdeasStates.waiting_for_name_type_other)
async def input_name_type_other(message: types.Message, state: FSMContext):
    """Получает тип названия от пользователя."""
    name_type = (message.text or "").strip()
    if len(name_type) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(name_type=name_type)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору стиля названия
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Современный", callback_data="ideas_detail:name_style_modern")],
        [InlineKeyboardButton(text="🎨 Креативный", callback_data="ideas_detail:name_style_creative")],
        [InlineKeyboardButton(text="💼 Деловой", callback_data="ideas_detail:name_style_business")],
        [InlineKeyboardButton(text="🌸 Нежный", callback_data="ideas_detail:name_style_gentle")],
        [InlineKeyboardButton(text="⚡ Энергичный", callback_data="ideas_detail:name_style_energetic")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_style_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_type")],
    ])
    
    await message.answer(
        text="🎨 Какой стиль названия предпочитаете?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_business_sphere_other)
async def input_business_sphere_other(message: types.Message, state: FSMContext):
    """Получает сферу бизнеса от пользователя."""
    business_sphere = (message.text or "").strip()
    if len(business_sphere) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(business_sphere=business_sphere)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору бюджета бизнеса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 До 100к₽", callback_data="ideas_detail:business_budget_100k")],
        [InlineKeyboardButton(text="💰 100к-500к₽", callback_data="ideas_detail:business_budget_500k")],
        [InlineKeyboardButton(text="💰 500к-1млн₽", callback_data="ideas_detail:business_budget_1m")],
        [InlineKeyboardButton(text="💰 1млн-5млн₽", callback_data="ideas_detail:business_budget_5m")],
        [InlineKeyboardButton(text="💰 От 5млн₽", callback_data="ideas_detail:business_budget_5mplus")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_budget_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_sphere")],
    ])
    
    await message.answer(
        text="💰 Какой у вас бюджет для бизнеса?",
        reply_markup=kb
    )


# Добавим обработчик для business_back_to_sphere
@router.callback_query(F.data == "business_back_to_sphere")
async def business_back_to_sphere(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору сферы бизнеса."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍽️ Общепит", callback_data="ideas_detail:business_sphere_food")],
        [InlineKeyboardButton(text="🛒 Торговля", callback_data="ideas_detail:business_sphere_retail")],
        [InlineKeyboardButton(text="💻 IT/Технологии", callback_data="ideas_detail:business_sphere_tech")],
        [InlineKeyboardButton(text="🎓 Образование", callback_data="ideas_detail:business_sphere_education")],
        [InlineKeyboardButton(text="💄 Красота/Здоровье", callback_data="ideas_detail:business_sphere_beauty")],
        [InlineKeyboardButton(text="🏠 Услуги", callback_data="ideas_detail:business_sphere_services")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_sphere_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="ideas_start_process")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="🚀 В какой сфере планируете бизнес?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# ——————————————————————
# Обработчики ввода пользовательского текста для остальных "Другое"
# ——————————————————————
@router.message(IdeasStates.waiting_for_name_style_other)
async def input_name_style_other(message: types.Message, state: FSMContext):
    """Получает стиль названия от пользователя."""
    name_style = (message.text or "").strip()
    if len(name_style) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(name_style=name_style)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору аудитории названия
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👶 Дети", callback_data="ideas_detail:name_audience_children")],
        [InlineKeyboardButton(text="🧑 Молодежь", callback_data="ideas_detail:name_audience_youth")],
        [InlineKeyboardButton(text="👨‍💼 Взрослые", callback_data="ideas_detail:name_audience_adults")],
        [InlineKeyboardButton(text="👵 Пожилые", callback_data="ideas_detail:name_audience_elderly")],
        [InlineKeyboardButton(text="🌍 Универсальное", callback_data="ideas_detail:name_audience_universal")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:name_audience_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="name_back_to_style")],
    ])
    
    await message.answer(
        text="👥 Для какой аудитории предназначено?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_name_audience_other)
async def input_name_audience_other(message: types.Message, state: FSMContext):
    """Получает аудитории названия от пользователя."""
    name_audience = (message.text or "").strip()
    if len(name_audience) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(name_audience=name_audience)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к оплате после выбора всех деталей для названий
    await ideas_payment_step_from_message(message, state)


@router.message(IdeasStates.waiting_for_business_budget_other)
async def input_business_budget_other(message: types.Message, state: FSMContext):
    """Получает бюджет бизнеса от пользователя."""
    business_budget = (message.text or "").strip()
    if len(business_budget) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(business_budget=business_budget)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к выбору масштаба бизнеса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Домашний бизнес", callback_data="ideas_detail:business_scale_home")],
        [InlineKeyboardButton(text="🏪 Локальный", callback_data="ideas_detail:business_scale_local")],
        [InlineKeyboardButton(text="🏙️ Городской", callback_data="ideas_detail:business_scale_city")],
        [InlineKeyboardButton(text="🌍 Региональный", callback_data="ideas_detail:business_scale_regional")],
        [InlineKeyboardButton(text="🌐 Онлайн", callback_data="ideas_detail:business_scale_online")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_scale_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_budget")],
    ])
    
    await message.answer(
        text="📏 Какого масштаба планируете бизнес?",
        reply_markup=kb
    )


@router.message(IdeasStates.waiting_for_business_scale_other)
async def input_business_scale_other(message: types.Message, state: FSMContext):
    """Получает масштаб бизнеса от пользователя."""
    business_scale = (message.text or "").strip()
    if len(business_scale) > 100:
        await message.answer("❌ Слишком длинный текст! Пожалуйста, введите более короткое описание.")
        return

    await state.update_data(business_scale=business_scale)
    
    data = await state.get_data()
    chat_id = message.chat.id
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    # Удаляем сообщение с подсказкой, если оно есть
    hint_message_id = data.get("hint_message_id")
    if hint_message_id and message.bot is not None:
        try:
            await message.bot.delete_message(chat_id=chat_id, message_id=hint_message_id)
        except Exception:
            # Игнорируем ошибки удаления (сообщение может быть уже удалено)
            pass

    # Переходим к оплате после выбора всех деталей для бизнеса
    await ideas_payment_step_from_message(message, state)


# Добавим обработчики кнопок "Назад" для новых состояний
@router.callback_query(F.data == "business_back_to_budget")
async def business_back_to_budget(call: CallbackQuery, state: FSMContext):
    """Возвращает к выбору бюджета бизнеса."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 До 100к₽", callback_data="ideas_detail:business_budget_100k")],
        [InlineKeyboardButton(text="💰 100к-500к₽", callback_data="ideas_detail:business_budget_500k")],
        [InlineKeyboardButton(text="💰 500к-1млн₽", callback_data="ideas_detail:business_budget_1m")],
        [InlineKeyboardButton(text="💰 1млн-5млн₽", callback_data="ideas_detail:business_budget_5m")],
        [InlineKeyboardButton(text="💰 От 5млн₽", callback_data="ideas_detail:business_budget_5mplus")],
        [InlineKeyboardButton(text="🧩 Другое", callback_data="ideas_detail:business_budget_other")],
        [InlineKeyboardButton(text="⏎ Назад", callback_data="business_back_to_sphere")],
    ])
    
    if call.message and hasattr(call.message, "message_id") and call.bot is not None:
        await call.bot.edit_message_text(
            text="💰 Какой у вас стартовый бюджет?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )
    await safe_answer_callback(call, state)


# Вспомогательная функция для перехода к оплате из message обработчика
async def ideas_payment_step_from_message(message: types.Message, state: FSMContext):
    """Переход к оплате из message обработчика (аналог ideas_payment_step для CallbackQuery)."""
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    # Проверяем подписку
    if await is_subscribed(user_id):
        # Если есть подписка, сразу генерируем идеи
        await generate_ideas_for_user_from_message(message, state)
    else:
        # Определяем правильный callback для кнопки "Назад" в зависимости от категории
        data = await state.get_data()
        category = data.get("category", "")
        
        if category == "gift":
            back_callback = "gift_back_to_occasion"
        elif category == "post":
            back_callback = "post_back_to_audience"
        elif category == "name":
            back_callback = "name_back_to_audience"
        elif category == "business":
            back_callback = "business_back_to_scale"
        else:
            # Для других случаев (например, при выборе ограничений)
            back_callback = "ideas_constraints_back"
        
        # Создаем платеж
        payment_url, payment_id = await create_payment(user_id, 100, "ideas")
        if payment_url and payment_id:
            await state.update_data(payment_id=payment_id)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить 100₽", url=payment_url)],
                [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_ideas:{payment_id}")],
                [InlineKeyboardButton(text="⏎ Назад", callback_data=back_callback)],
            ])
            
            await message.answer(
                text=PAYMENT_MESSAGE,
                reply_markup=kb
            )
        else:
            await message.answer("❌ Ошибка создания платежа. Попробуйте позже.")


# ——————————————————————
# Регистрация роутера
# ——————————————————————
def register_ideas_handlers(dp: Dispatcher):
    """Регистрирует маршрутизатор для генератора идей."""
    dp.include_router(router)
