from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from datetime import datetime, timezone
from utils.chatgpt.gpt import get_psychologist_response, get_psychologist_context, save_message, get_message_count, clear_history, get_last_user_message_time, save_summary_if_needed
from handlers.core.subscription import is_subscribed
import asyncio
import random
import time
from utils.session_timer import start_session_timer, cancel_session_timer
from utils.database.db import get_free_count, increment_free_count, reset_free_count, set_free_count, fetch_subscription, get_summary
import re
from config import logger

router = Router()

QUESTIONS = (
    "Пожалуйста, ответьте на следующие вопросы:\n"
    "1. Как вы себя чувствуете в данный момент?\n"
    "2. Что вас заставило обратиться за поддержкой?\n"
    "3. Насколько остро вы сейчас переживаете свою проблему?\n"
    "4. Как давно вы заметили первые проявления того, что вас беспокоит?\n"
    "5. В каких ситуациях (день, люди, события) это ощущение проявляется сильнее всего?\n"
    "6. Есть ли у вас уже какие-то мысли о том, что могло бы помочь (или, наоборот, мешает) справиться с этим?\n"
    "7. Какие основные эмоции вы сейчас испытываете (например: тревога, грусть, злость, бессилие)?\n"
    "8. Какие мысли чаще всего сопровождают эти эмоции?\n"
    "9. Есть ли рядом люди, которым вы можете довериться и обратиться за помощью?\n"
    "10. Какие ресурсы (друзья, семья, хобби, речь и т. д.) помогают вам чувствовать себя чуть лучше?\n"
    "11. Как часто вы позволяете себе просить об опоре у близких или специалистов?\n"
    "12. Что помогает вам снять напряжение или отвлечься (прогулка, музыка, спорт и пр.)?\n"
    "13. Какие способы самоуспокоения вы уже пробовали? Насколько они эффективны?\n\n"
    "Пожалуйста, сформулируйте ответы как небольшой рассказ о себе, чтобы мы могли более детально изучить ваш случай и оказать нужную поддержку 🫶🏻"
)

THANK_YOU = [
  "Спасибо, что поделились своими мыслями. Мы обрабатываем ваш запрос и скоро вернемся с ответом. Пожалуйста, подождите несколько секунд…",
  "Пока мы готовим для вас ответ, хотим напомнить: если вы почувствуете, что ваше состояние ухудшается — пожалуйста, не откладывайте и обратитесь к живому специалисту. В этом нет ничего «неправильного» — наоборот, это знак силы и заботы о себе! ♡",
  "Ваше благополучие очень важно для нас. Мы скоро вернемся с ответом, который поможет вам лучше разобраться в своих чувствах. ♡"
]


SUBSCRIPTION_PRICE = 990
FREE_MESSAGES = 3
SESSION_TIMEOUT = 600
THRESHOLD = 25  # Увеличили с 10 до 25 для более редкого создания резюме

# --- Клавиатуры ---
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="start")],
    ])

def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оформить подписку", callback_data="buy_psychologist:30:990")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_psychologist")],
    ])

def session_expired_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продолжить сессию", callback_data="continue_psy_session")],
        [InlineKeyboardButton(text="🏠 Вернуться в главное меню", callback_data="main_menu_psychologist")],
    ])

# --- Таймаут сессии ---
async def on_psy_session_timeout(user_id: int, bot: Bot, state: FSMContext):
    data = await state.get_data()
    
    # Проверяем, что сессия все еще активна
    if not data.get("session_active", False):
        logger.info(f"Сессия для пользователя {user_id} уже была завершена, пропускаем уведомление")
        return
    
    last_menu_message_id = data.get("last_menu_message_id")
    continue_session_message_id = data.get("continue_session_message_id")
    
    # Удаляем кнопку, если есть
    if last_menu_message_id:
        try:
            await bot.delete_message(user_id, last_menu_message_id)
        except Exception:
            pass
    
    # Удаляем сообщение "Сессия продолжена!", если есть
    if continue_session_message_id:
        try:
            await bot.delete_message(user_id, continue_session_message_id)
        except Exception:
            pass
    
    await state.update_data(session_active=False)
    # Отправляем уведомление о завершении сессии
    await bot.send_message(
        user_id,
        "Сессия завершена из-за неактивности.\n\nВыберите действие:",
        reply_markup=session_expired_kb()
    )

def markdown_to_html(text: str) -> str:
    # Жирный **текст** или __текст__ -> <b>текст</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
    # Курсив *текст* или _текст_ -> <i>текст</i>
    text = re.sub(r'(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)  # одиночные *курсив*
    text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)
    # Моноширинный `код` -> <code>код</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text

# --- Callback для запуска психолога из главного меню ---
@router.callback_query(F.data == "psychologist_advice")
async def psychologist_advice_start(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id if call.from_user else None
    if user_id:
        # Отменяем предыдущий таймер, если он был
        cancel_session_timer(user_id)
    
    await state.clear()
    await state.update_data(session_active=True)
    if not user_id:
        await call.answer()
        return

    logger.info(f"Пользователь {user_id} запустил психолога через кнопку")

    # Проверяем доступность сервиса
    from utils.service_checker import check_service_availability
    is_available, maintenance_message, keyboard = await check_service_availability("psychologist_advice")
    
    if not is_available:
        if call.message and isinstance(call.message, Message):
            await call.message.edit_text(maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.", reply_markup=keyboard)
        await call.answer()
        return

    wait_msg = None
    if call.message and isinstance(call.message, Message):
        try:
            wait_msg = await call.message.edit_text("⚙️ Готовим ответ...", reply_markup=None)
        except Exception:
            pass
    await call.answer()

    # --- Проверка лимита бесплатных сообщений ДО генерации приветствия ---
    subscribed = await is_subscribed(user_id, 'psychologist')
    if not subscribed:
        free_count = await get_free_count(user_id)
        if free_count >= FREE_MESSAGES:
            if call.message and isinstance(call.message, Message):
                await call.message.edit_text(
                    "Ваши бесплатные сообщения с ботом закончились.\n\nОформите подписку, чтобы продолжить получать поддержку.",
                    reply_markup=subscribe_kb()
                )
            await call.answer()
            return

    from utils.database.db import get_last_user_messages, get_last_conversation_messages
    from utils.database.db import get_summary
    from utils.chatgpt.gpt import make_last_message_greeting, make_conversation_greeting

    # УМНОЕ ПРИВЕТСТВИЕ: Сначала проверяем есть ли история
    greeting = get_greeting_by_time()
    
    # Быстро проверяем есть ли у пользователя история
    from utils.chatgpt.gpt import get_message_count
    msg_count = await get_message_count(user_id)
    summary = await get_summary(user_id)
    
    await state.update_data(psychologist_stage="dialog", session_start=datetime.now().timestamp())
    
    if msg_count > 0 or summary:
        # Есть история - показываем "вспоминаю" и потом обновляем персональным приветствием
        quick_greeting = f"{greeting}! Рад вас видеть. Секундочку, вспоминаю о чем мы общались..."
        if call.message and isinstance(call.message, Message):
            await call.message.edit_text(quick_greeting, reply_markup=main_menu_kb())
            await state.update_data(last_menu_message_id=call.message.message_id)
        
        # В фоне генерируем персональное приветствие - определяем функцию ниже
        pass
    else:
        # Новый пользователь без истории - показываем вопросы для первичной оценки
        await state.update_data(psychologist_stage="questions", free_count=0, session_start=datetime.now().timestamp())
        logger.info(f"Пользователь {user_id} установлен psychologist_stage=questions")
        if call.message and isinstance(call.message, Message):
            await call.message.edit_text(QUESTIONS, reply_markup=main_menu_kb())
            # Сохраняем ID сообщения с кнопкой для последующего удаления
            await state.update_data(last_menu_message_id=call.message.message_id)
        await call.answer()
        return
    
    # Функция обновления приветствия (только для пользователей с историей)
    async def update_greeting_in_background():
        try:
            prompt = None
            
            # 1. Проверяем историю диалога (последние сообщения от обеих сторон)
            user_message, bot_message = await get_last_conversation_messages(user_id)
            if user_message and bot_message:
                # Есть диалог — генерируем персональное приветствие через GPT
                prompt = await make_conversation_greeting(user_message, bot_message, greeting)
            # 2. Если есть только сообщения пользователя
            elif user_message:
                # Персональное приветствие через GPT
                prompt = await make_last_message_greeting(user_message, greeting)
            # 3. Если есть summary
            else:
                summary = await get_summary(user_id)
                if summary:
                    # Персональное приветствие на основе summary
                    prompt = await make_last_message_greeting(summary, greeting)
            
            # Обновляем сообщение только если получили персональное приветствие
            if prompt and prompt.strip():
                data = await state.get_data()
                last_menu_message_id = data.get("last_menu_message_id")
                if last_menu_message_id and call.message:
                    try:
                        await call.message.bot.edit_message_text(
                            chat_id=user_id,
                            message_id=last_menu_message_id,
                            text=prompt,
                            reply_markup=main_menu_kb()
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось обновить приветствие для {user_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Ошибка в фоновом обновлении приветствия для {user_id}: {e}")
    
    # Запускаем обновление приветствия в фоне
    asyncio.create_task(update_greeting_in_background())
    await call.answer()
    return

# --- Хэндлеры ---
@router.message(lambda m: m.text == "Совет от ИИ-психолога")
async def start_psychologist(message: types.Message, state: FSMContext):
    await state.update_data(session_active=True)
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return
    
    # Проверяем доступность сервиса
    from utils.service_checker import check_service_availability
    is_available, maintenance_message, keyboard = await check_service_availability("psychologist_advice")
    
    if not is_available:
        await message.answer(maintenance_message or "Сервис временно недоступен. Приносим извинения за неудобства.", reply_markup=keyboard)
        return
    from utils.chatgpt.gpt import get_message_count
    from utils.database.db import get_summary, get_last_conversation_messages
    msg_count = await get_message_count(user_id)
    summary = await get_summary(user_id)
    if msg_count > 0 or summary:
        await state.update_data(psychologist_stage="dialog", free_count=0, session_start=datetime.now().timestamp())
        
        # МГНОВЕННОЕ приветствие без GPT
        greeting = get_greeting_by_time()
        quick_greeting = f"{greeting}! Рад вас видеть снова. О чём пообщаемся сегодня?"
        
        greeting_msg = await message.answer(quick_greeting, reply_markup=main_menu_kb())
        # Сохраняем ID сообщения с кнопкой для последующего удаления
        await state.update_data(last_menu_message_id=greeting_msg.message_id)
        
        # В фоне можем обновить приветствие более персональным (опционально)
        # Но для скорости пока оставляем простое
        return
    await state.update_data(psychologist_stage="questions", free_count=0, session_start=datetime.now().timestamp())
    if message and message.text:
        questions_msg = await message.answer(QUESTIONS, reply_markup=main_menu_kb())
        # Сохраняем ID сообщения с кнопкой для последующего удаления
        await state.update_data(last_menu_message_id=questions_msg.message_id)

@router.message()
async def handle_psychologist_message(message: types.Message, state: FSMContext):
    if not message or not message.text:
        return
    data = await state.get_data()
    if not message.from_user:
        return
    user_id = message.from_user.id
    
    # Добавляем отладочную информацию
    logger.info(f"Пользователь {user_id} отправил сообщение в психологе. Данные состояния: {data}")
    
    # --- Проверяем, что пользователь находится в сессии психолога ---
    if not data.get("session_active"):
        # Игнорируем сообщения если пользователь не в сессии психолога
        logger.info(f"Пользователь {user_id} не в сессии психолога. session_active: {data.get('session_active')}")
        return
    
    # Если session_active=True, но psychologist_stage не установлен, устанавливаем его
    if data.get("session_active") and not data.get("psychologist_stage"):
        logger.info(f"Пользователь {user_id} в сессии, но psychologist_stage не установлен. Устанавливаем dialog")
        await state.update_data(psychologist_stage="dialog", session_start=datetime.now().timestamp())
        data = await state.get_data()  # Обновляем данные состояния
    
    # --- Блокировка если сессия неактивна ---
    if data.get("session_active") is False:
        # Игнорируем сообщения пользователя если сессия завершена
        logger.info(f"Пользователь {user_id} сессия неактивна")
        return
    # --- Запуск/обновление таймера ---
    start_session_timer(user_id, SESSION_TIMEOUT, on_psy_session_timeout, message.bot, state)

    now = datetime.now().timestamp()
    session_start = data.get("session_start")
    # Если сессия истекла, но пользователь отправил сообщение - продлеваем сессию
    if session_start and now - session_start > SESSION_TIMEOUT:
        await state.update_data(session_start=now)
        # Перезапускаем таймер сессии
        start_session_timer(user_id, SESSION_TIMEOUT, on_psy_session_timeout, message.bot, state)

    # Проверка выхода в главное меню
    if message.text and message.text.lower() in ["/start", "/help", "/subscription", "/admin", "главное меню"]:
        # Отменяем таймер сессии перед сбросом состояния
        cancel_session_timer(user_id)
        await state.clear()
        await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu_kb())
        return

    # --- Удаляем кнопку "Вернуться в главное меню" из предыдущего сообщения ---
    last_menu_message_id = data.get("last_menu_message_id")
    if last_menu_message_id:
        logger.info(f"Попытка удалить кнопку меню для пользователя {user_id}, message_id: {last_menu_message_id}")
        try:
            await message.bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=last_menu_message_id,
                reply_markup=None
            )
            
            # Очищаем ID после успешного удаления
            await state.update_data(last_menu_message_id=None)
        except Exception as e:
            logger.warning(f"Не удалось удалить кнопку меню для пользователя {user_id}: {e}")
            # Очищаем ID даже если удаление не удалось (возможно, сообщение уже удалено)
            await state.update_data(last_menu_message_id=None)
    
    # --- Удаляем сообщение "Сессия продолжена!" если оно есть ---
    continue_session_message_id = data.get("continue_session_message_id")
    if continue_session_message_id:
        logger.info(f"Попытка удалить сообщение 'Сессия продолжена!' для пользователя {user_id}, message_id: {continue_session_message_id}")
        try:
            await message.bot.delete_message(
                chat_id=user_id,
                message_id=continue_session_message_id
            )
            logger.info(f"Сообщение 'Сессия продолжена!' успешно удалено для пользователя {user_id}")
            # Очищаем ID после успешного удаления
            await state.update_data(continue_session_message_id=None)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение 'Сессия продолжена!' для пользователя {user_id}: {e}")
            # Очищаем ID даже если удаление не удалось (возможно, сообщение уже удалено)
            await state.update_data(continue_session_message_id=None)
    
    # --- Проверка лимита бесплатных сообщений ДО сообщения ожидания ---
    subscribed = await is_subscribed(user_id, 'psychologist')
    if not subscribed:
        free_count = await get_free_count(user_id)
        if free_count >= FREE_MESSAGES:
            await message.answer(
                "Ваши бесплатные сообщения с ботом-психологом закончились.\n\nОформите подписку, чтобы продолжить получать поддержку.",
                reply_markup=subscribe_kb()
            )
            # Завершаем сессию без уведомления
            await state.update_data(session_active=False)
            return
    
    # --- Сообщение ожидания отправляем только если лимит не превышен ---
    wait_text = random.choice(THANK_YOU)
    wait_msg = await message.answer(wait_text, reply_markup=None)

    # Первый этап — ответы на вопросы
    if data.get("psychologist_stage") == "questions":
        if message.text:
            stage_start = time.time()
            # logger.info(f"[PERF] Начинаем обработку вопросов для пользователя {user_id}")
            
            # Обновляем session_start
            await state.update_data(session_start=now)
            
            context = await get_psychologist_context(user_id)
            response = await get_psychologist_response(context, message.text or "")
            
            # Проверяем, что ответ не пустой
            if not response or not response.strip():
                response = "Извините, произошла ошибка при обработке вашего сообщения. Попробуйте переформулировать ваш вопрос."
            
            html_start = time.time()
            response = markdown_to_html(response)
            html_time = time.time() - html_start
            # logger.info(f"[PERF] Конвертация markdown в HTML заняла: {html_time:.3f}s")
            
            main_processing_time = time.time() - stage_start
            # logger.info(f"[PERF] Основная обработка вопросов (без БД) заняла: {main_processing_time:.3f}s")
            
            # СНАЧАЛА ОТВЕЧАЕМ ПОЛЬЗОВАТЕЛЮ
            # Удаляем сообщение ожидания
            try:
                await wait_msg.delete()
            except Exception:
                pass
            # Ответ бота без кнопки
            await message.answer(response, reply_markup=None, parse_mode='HTML')
            # Следующее сообщение с кнопкой и сохранение его ID
            menu_msg = await message.answer("Если потребуется — вы всегда можете вернуться в главное меню.", reply_markup=main_menu_kb())
            await state.update_data(psychologist_stage="dialog", last_menu_message_id=menu_msg.message_id)
            
            # ЗАТЕМ В ФОНЕ СОХРАНЯЕМ В БД
            async def background_save():
                try:
                    bg_start = time.time()
                    # logger.info(f"[PERF] Начинаем фоновое сохранение для пользователя {user_id}")
                    
                    # Сохраняем оба сообщения одной транзакцией
                    from utils.database.db import save_user_and_bot_messages
                    await save_user_and_bot_messages(user_id, message.text, response or "")
                    
                    bg_time = time.time() - bg_start
                    # logger.info(f"[PERF] Фоновое сохранение для пользователя {user_id} завершено за: {bg_time:.3f}s")
                    
                    total_stage_time = time.time() - stage_start
                    # logger.info(f"[PERF] Полная обработка вопросов для пользователя {user_id} заняла: {total_stage_time:.3f}s")
                    
                except Exception as e:
                    logger.error(f"Ошибка в фоновом сохранении для пользователя {user_id}: {e}")
            
            # Запускаем сохранение в фоне
            asyncio.create_task(background_save())
        return
    # Диалог с психологом
    if data.get("psychologist_stage") == "dialog":
        try:
            dialog_start = time.time()
            # logger.info(f"[PERF] Начинаем обработку диалога для пользователя {user_id}")
            
            # Обновляем session_start
            await state.update_data(session_start=now)
            
            context = await get_psychologist_context(user_id)
            response = await get_psychologist_response(context, message.text or "")
            
            # Проверяем, что ответ не пустой
            if not response or not response.strip():
                response = "Извините, произошла ошибка при обработке вашего сообщения. Попробуйте переформулировать ваш вопрос."
            
            html_start = time.time()
            response = markdown_to_html(response)
            html_time = time.time() - html_start
            # logger.info(f"[PERF] Конвертация markdown в HTML заняла: {html_time:.3f}s")
            
            main_processing_time = time.time() - dialog_start
            # logger.info(f"[PERF] Основная обработка (без БД) заняла: {main_processing_time:.3f}s")
            
            # СНАЧАЛА ОТВЕЧАЕМ ПОЛЬЗОВАТЕЛЮ
            # Удаляем сообщение ожидания
            try:
                await wait_msg.delete()
            except Exception:
                pass
            # Ответ бота без кнопки
            await message.answer(response, reply_markup=None, parse_mode='HTML')
            # Следующее сообщение с кнопкой и сохранение его ID
            menu_msg = await message.answer("Если потребуется — вы всегда можете вернуться в главное меню.", reply_markup=main_menu_kb())
            await state.update_data(last_menu_message_id=menu_msg.message_id)
            
            # ЗАТЕМ В ФОНЕ ВЫПОЛНЯЕМ БД ОПЕРАЦИИ
            async def background_db_operations():
                try:
                    bg_start = time.time()
                    # logger.info(f"[PERF] Начинаем фоновые БД операции для пользователя {user_id}")
                    
                    # Увеличиваем счетчик бесплатных сообщений только для неподписанных пользователей
                    if not subscribed:
                        count_start = time.time()
                        await increment_free_count(user_id)
                        count_time = time.time() - count_start
                        # logger.info(f"[PERF] Увеличение счетчика заняло: {count_time:.3f}s")
                    
                    # Сохраняем оба сообщения одной транзакцией
                    from utils.database.db import save_user_and_bot_messages
                    save_both_start = time.time()
                    await save_user_and_bot_messages(user_id, message.text or "", response or "")
                    save_both_time = time.time() - save_both_start
                    # logger.info(f"[PERF] Сохранение обоих сообщений в одной транзакции заняло: {save_both_time:.3f}s")
                    
                    # Проверяем и создаем резюме если нужно
                    summary_start = time.time()
                    await save_summary_if_needed(user_id, THRESHOLD)
                    summary_time = time.time() - summary_start
                    # logger.info(f"[PERF] Проверка/сохранение резюме заняло: {summary_time:.3f}s")
                    
                    bg_total_time = time.time() - bg_start
                    # logger.info(f"[PERF] Фоновые БД операции для пользователя {user_id} завершены за: {bg_total_time:.3f}s")
                    
                    total_dialog_time = time.time() - dialog_start
                    # logger.info(f"[PERF] Полная обработка диалога для пользователя {user_id} заняла: {total_dialog_time:.3f}s")
                    
                except Exception as e:
                    logger.error(f"Ошибка в фоновых БД операциях для пользователя {user_id}: {e}")
            
            # Запускаем БД операции в фоне, не ожидая их завершения
            asyncio.create_task(background_db_operations())
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения пользователя {user_id}: {e}")
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await message.answer("Извините, произошла ошибка при обработке вашего сообщения. Попробуйте еще раз.", reply_markup=main_menu_kb())

@router.callback_query(F.data == "main_menu_psychologist")
async def back_to_main_menu(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id if call.from_user else None
    if user_id:
        # Отменяем таймер сессии перед сбросом состояния
        cancel_session_timer(user_id)
    
    await state.clear()
    
    # Удаляем сообщение вместо редактирования
    if call.message and isinstance(call.message, Message):
        try:
            await call.message.delete()
        except Exception:
            # Если удаление не удалось, редактируем сообщение
            await call.message.edit_text("Главное меню", reply_markup=main_menu_kb())
            await call.answer()
            return
    
    # Импортируем необходимые функции для главного меню
    from handlers.core.start import START_TEXT, get_main_menu_kb
    
    # Отправляем новое сообщение с главным меню
    await call.message.answer(START_TEXT, reply_markup=get_main_menu_kb())
    
    await call.answer()

# --- Callback: Продолжить сессию ---
@router.callback_query(F.data == "continue_psy_session")
async def continue_psy_session(call: CallbackQuery, state: FSMContext):
    # Сбрасываем флаги и переводим в режим диалога
    now = datetime.now().timestamp()
    await state.update_data(session_active=True, psychologist_stage="dialog", session_start=now)
    
    # Запускаем таймер сессии заново
    user_id = call.from_user.id if call.from_user else None
    if user_id:
        from utils.session_timer import start_session_timer
        start_session_timer(user_id, SESSION_TIMEOUT, on_psy_session_timeout, call.bot, state)
    
    # Редактируем текущее сообщение, заменяя его на сообщение о продолжении сессии
    if call.message and isinstance(call.message, Message):
        try:
            await call.message.edit_text("Сессия продолжена! Можете продолжать общение.", reply_markup=main_menu_kb())
            # Сохраняем ID сообщения с кнопкой для последующего удаления
            await state.update_data(continue_session_message_id=call.message.message_id, last_menu_message_id=call.message.message_id)
        except Exception:
            # Если редактирование не удалось, отправляем новое сообщение
            new_msg = await call.message.answer("Сессия продолжена! Можете продолжать общение.", reply_markup=main_menu_kb())
            await state.update_data(continue_session_message_id=new_msg.message_id, last_menu_message_id=new_msg.message_id)
    else:
        new_msg = await call.message.answer("Сессия продолжена! Можете продолжать общение.", reply_markup=main_menu_kb())
        await state.update_data(continue_session_message_id=new_msg.message_id, last_menu_message_id=new_msg.message_id)
    
    await call.answer()

# --- Регистрация хэндлеров ---
def register_psychologist_handlers(dp):
    dp.include_router(router) 

def get_greeting_by_time():
    now = datetime.now()
    hour = now.hour
    if 6 <= hour < 12:
        return "Доброе утро"
    elif 12 <= hour < 18:
        return "Добрый день"
    elif 18 <= hour < 24:
        return "Добрый вечер"
    else:
        return "Доброй ночи" 

