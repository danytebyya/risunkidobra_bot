import asyncio
import re, json
import random
import time
from datetime import datetime, timezone
from typing import Tuple, Optional

from openai import OpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam, ChatCompletionMessageParam

from config import OPENAI_API_KEY, logger
from utils.database import db

client = OpenAI(api_key=OPENAI_API_KEY)

# Простое кэширование для контекста психолога
_context_cache = {}
CACHE_TTL = 300  # 5 минут в секундах

# Кэш для счетчиков сообщений (чтобы не делать лишние запросы к БД)
_message_count_cache = {}
MESSAGE_COUNT_CACHE_TTL = 60  # 1 минута

# --- Психолог: работа с историей и резюме ---

PSYCHOLOGIST_SYSTEM_PROMPT = (
    "Вы психолог. Помогаете через эмпатию и практические советы. "
    "Работаете с эмоциями, стрессом, отношениями. Стиль бережный, без IT-советов. "
    "Начинайте с эмпатии, давайте конкретные рекомендации. "
    "Отвечайте полно (2-3 абзацев, но не более 8 предложений, не растягивай ответ, надо отвечать покороче, чтобв клиент не успевал заскучать во время чтения), но естественно - столько, сколько нужно для полного ответа."
)

SUMMARY_SYSTEM_PROMPT = (
    "Ты — ассистент, который читает стенограмму переписки и формирует ёмкое резюме: "
    "ключевые факты, эмоции, тревоги и потребности пользователя. "
    "Резюме должно быть кратким (2-4 предложения), но информативным."
)

COMBINED_SUMMARY_PROMPT = (
    "Ты — ассистент, который объединяет старое резюме с новой информацией из переписки. "
    "Создай обновленное резюме, которое включает:\n"
    "1. Ключевую информацию из предыдущего резюме (если она все еще актуальна)\n"
    "2. Новые факты, эмоции, тревоги и потребности из свежих сообщений\n"
    "3. Эволюцию проблем пользователя (что изменилось, что решилось, что появилось)\n\n"
    "Итоговое резюме должно быть кратким (3-5 предложений), но полным и актуальным."
)

SHORT_SUMMARY_PROMPT = (
    "Ты — ассистент, который читает одно сообщение пользователя и формирует очень краткий пересказ (1-2 предложения), чтобы понять суть запроса или темы. Не повторяй текст дословно, а перефразируй максимально кратко и понятно."
)

LAST_MESSAGE_GREETING_PROMPT = (
    "Ты — ассистент-психолог. Сформулируй краткое приветственное сообщение для пользователя (2-3 предложения), используя обращение (например, Добрый день!). Кратко и естественно укажи, о чём шла речь в последнем сообщении пользователя (текст ниже), перефразировав его. Заверши вопросом: хочет ли пользователь продолжить разговор или обсудить что-то новое? Не повторяй текст сообщения дословно, а перефразируй.\n"
    "Последнее сообщение пользователя: <текст>\n"
    "Пример: Добрый день! В прошлый раз мы обсуждали ваши переживания по поводу работы. Хотите продолжить разговор или обсудить что-то новое?"
)

CONVERSATION_GREETING_PROMPT = (
    "Ты — ассистент-психолог. Сформулируй краткое приветственное сообщение для пользователя (2-3 предложения), используя обращение (например, Добрый день!). "
    "Кратко и естественно резюмируй, о чём шла речь в последнем диалоге между пользователем и психологом. "
    "У тебя есть последнее сообщение пользователя и последний ответ психолога. "
    "Создай краткое резюме темы разговора и заверши вопросом: хочет ли пользователь продолжить разговор или обсудить что-то новое?\n\n"
    "Последнее сообщение пользователя: <user_message>\n"
    "Последний ответ психолога: <bot_message>\n\n"
    "Пример: Добрый день! В прошлый раз мы обсуждали ваши переживания по поводу работы и способы справиться со стрессом. Хотите продолжить разговор или обсудить что-то новое?"
)

def _invalidate_user_cache(user_id: int):
    """Инвалидирует кэш для конкретного пользователя."""
    keys_to_remove = [key for key in _context_cache.keys() if key.startswith(f"context_{user_id}_")]
    for key in keys_to_remove:
        del _context_cache[key]
    
    # Также инвалидируем кэш счетчика сообщений
    msg_count_key = f"msg_count_{user_id}"
    if msg_count_key in _message_count_cache:
        del _message_count_cache[msg_count_key]

async def save_message(user_id: int, role: str, content: str):
    """Сохраняет сообщение пользователя или ассистента в историю."""
    await db.save_history_message(user_id, role, content)
    # Инвалидируем кэш для этого пользователя
    _invalidate_user_cache(user_id)

async def get_message_count(user_id: int) -> int:
    """Возвращает количество сообщений в истории пользователя с кэшированием."""
    # Проверяем кэш
    cache_key = f"msg_count_{user_id}"
    if cache_key in _message_count_cache:
        cache_entry = _message_count_cache[cache_key]
        if (datetime.now().timestamp() - cache_entry['timestamp']) < MESSAGE_COUNT_CACHE_TTL:
            return cache_entry['count']
    
    # Если кэш устарел или отсутствует, делаем запрос к БД
    count = await db.count_history_messages(user_id)
    
    # Сохраняем в кэш
    _message_count_cache[cache_key] = {
        'count': count,
        'timestamp': datetime.now().timestamp()
    }
    
    return count

async def clear_history(user_id: int):
    """Очищает историю сообщений пользователя."""
    await db.clear_history(user_id)

async def get_last_user_message_time(user_id: int) -> float:
    """Возвращает timestamp последнего сообщения пользователя (или None)."""
    return await db.get_last_user_message_time(user_id)

async def save_summary_if_needed(user_id: int, threshold: int):
    """Если сообщений больше threshold, делает резюме по старым сообщениям и сохраняет его, удаляя старые сообщения."""
    start_time = time.time()
    # logger.info(f"[PERF] Начинаем проверку резюме для пользователя {user_id}")
    
    count_start = time.time()
    count = await db.count_history_messages(user_id)
    count_time = time.time() - count_start
    # logger.info(f"[PERF] Подсчет сообщений ({count}) занял: {count_time:.3f}s")
    
    if count > threshold:
        # logger.info(f"[PERF] Нужно создать резюме для пользователя {user_id} ({count} > {threshold})")
        
        # Получаем старые сообщения для создания резюме (те, которые будут удалены)
        old_msgs_start = time.time()
        old_msgs = await db.get_oldest_history_messages(user_id, count-threshold)
        old_msgs_time = time.time() - old_msgs_start
        # logger.info(f"[PERF] Получение старых сообщений заняло: {old_msgs_time:.3f}s")
        
        text_block = "\n".join([f"{m['role']}: {m['content']}" for m in old_msgs])
        
        # Проверяем есть ли уже существующее резюме
        existing_summary = await db.get_summary(user_id)
        
        summary_start = time.time()
        if existing_summary:
            # Объединяем старое резюме с новыми сообщениями
            summary = await make_combined_summary(existing_summary, text_block)
        else:
            # Создаем первое резюме
            summary = await make_summary(text_block)
        summary_time = time.time() - summary_start
        # logger.info(f"[PERF] Создание резюме через GPT заняло: {summary_time:.3f}s")
        
        save_start = time.time()
        await db.save_summary(user_id, summary)
        save_time = time.time() - save_start
        # logger.info(f"[PERF] Сохранение резюме заняло: {save_time:.3f}s")
        
        # Удаляем старые сообщения (оставляем threshold новых)
        delete_start = time.time()
        await db.delete_oldest_history_messages(user_id, count-threshold)
        delete_time = time.time() - delete_start
        # logger.info(f"[PERF] Удаление старых сообщений заняло: {delete_time:.3f}s")
    
    total_time = time.time() - start_time
    # logger.info(f"[PERF] Полная проверка резюме для пользователя {user_id} заняла: {total_time:.3f}s")

async def make_summary(text_block: str) -> str:
    """Генерирует краткое резюме переписки через OpenAI."""
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": SUMMARY_SYSTEM_PROMPT
    }
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": text_block}
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    model, timeout = _determine_model_for_task('summary', text_block)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        timeout=timeout
    )
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not result or not result.strip():
        return "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."
    return result.strip()

async def make_combined_summary(existing_summary: str, new_messages: str) -> str:
    """Объединяет существующее резюме с новыми сообщениями в одно обновленное резюме."""
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": COMBINED_SUMMARY_PROMPT
    }
    
    combined_content = f"ПРЕДЫДУЩЕЕ РЕЗЮМЕ:\n{existing_summary}\n\nНОВЫЕ СООБЩЕНИЯ:\n{new_messages}"
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": combined_content}
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    
    model, timeout = _determine_model_for_task('summary', combined_content)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        timeout=timeout
    )
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not result or not result.strip():
        return existing_summary  # Возвращаем старое резюме если GPT не ответил
    return result.strip()

async def make_short_summary(text: str) -> str:
    """Генерирует краткий пересказ одного сообщения пользователя через OpenAI."""
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": SHORT_SUMMARY_PROMPT
    }
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": text}
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    model, timeout = _determine_model_for_task('short_summary', text)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        timeout=timeout
    )
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not result or not result.strip():
        return "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."
    return result.strip()

async def make_last_message_greeting(last_message: str, greeting: str) -> str:
    """Генерирует приветственное сообщение с кратким пересказом последнего сообщения пользователя."""
    prompt = LAST_MESSAGE_GREETING_PROMPT.replace('<текст>', last_message)
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": prompt
    }
    messages: list[ChatCompletionMessageParam] = [system_message]
    model, timeout = _determine_model_for_task('greeting', last_message)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        temperature=0.7,  # Для более предсказуемых результатов
        max_tokens=100,   # Ограничиваем для скорости
        timeout=timeout
    )
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not result or not result.strip():
        return "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."
    return result.strip()

async def make_conversation_greeting(user_message: str, bot_message: str, greeting: str) -> str:
    """Генерирует приветственное сообщение на основе последнего диалога между пользователем и ботом."""
    prompt = CONVERSATION_GREETING_PROMPT.replace('<user_message>', user_message).replace('<bot_message>', bot_message)
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": prompt
    }
    messages: list[ChatCompletionMessageParam] = [system_message]
    model, timeout = _determine_model_for_task('conversation_greeting', user_message + bot_message)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        temperature=0.7,  # Для более предсказуемых результатов
        max_tokens=100,   # Ограничиваем для скорости
        timeout=timeout,
    )
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not result or not result.strip():
        return "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."
    return result.strip()

def _is_cache_valid(cache_entry) -> bool:
    """Проверяет, не истек ли кэш."""
    return (datetime.now().timestamp() - cache_entry['timestamp']) < CACHE_TTL

def _cleanup_expired_cache():
    """Очищает истекший кэш."""
    current_time = datetime.now().timestamp()
    expired_keys = [
        key for key, value in _context_cache.items()
        if (current_time - value['timestamp']) >= CACHE_TTL
    ]
    for key in expired_keys:
        del _context_cache[key]

async def get_psychologist_context(user_id: int, m: int = 3) -> list[ChatCompletionMessageParam]:
    """Формирует список сообщений для ChatGPT: системный промпт, резюме (если есть), последние m сообщений."""
    start_time = time.time()
    # logger.info(f"[PERF] Начинаем формирование контекста для пользователя {user_id}")
    
    # Периодически очищаем истекший кэш
    if len(_context_cache) > 50:  # Очищаем если кэш слишком большой
        _cleanup_expired_cache()
    
    # Проверяем кэш
    cache_start = time.time()
    cache_key = f"context_{user_id}_{m}"
    if cache_key in _context_cache and _is_cache_valid(_context_cache[cache_key]):
        cache_time = time.time() - cache_start
        total_time = time.time() - start_time
        # logger.info(f"[PERF] Контекст взят из кэша для пользователя {user_id}. Время кэша: {cache_time:.3f}s, общее: {total_time:.3f}s")
        return _context_cache[cache_key]['data']
    
    cache_time = time.time() - cache_start
    # logger.info(f"[PERF] Кэш не найден для пользователя {user_id}. Время проверки кэша: {cache_time:.3f}s")
    
    context: list[ChatCompletionMessageParam] = []
    system_prompt: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": PSYCHOLOGIST_SYSTEM_PROMPT
    }
    context.append(system_prompt)
    
    # Получаем резюме и последние сообщения одним запросом
    db_start = time.time()
    summary, last_msgs = await db.get_summary_and_history(user_id, m)
    db_time = time.time() - db_start
    # logger.info(f"[PERF] Запрос к БД для пользователя {user_id} занял: {db_time:.3f}s")
    
    if summary:
        context.append({"role": "system", "content": f"Память: {summary}"})
    for msg in last_msgs:
        context.append({"role": msg["role"], "content": msg["content"]})
    
    # Кэшируем результат
    _context_cache[cache_key] = {
        'data': context,
        'timestamp': datetime.now().timestamp()
    }
    
    total_time = time.time() - start_time
    # logger.info(f"[PERF] Формирование контекста для пользователя {user_id} завершено за: {total_time:.3f}s (БД: {db_time:.3f}s)")
    
    return context

def _determine_model_for_task(task_type: str, content: str = "", additional_params: dict = None) -> tuple[str, int]:
    """
    Универсальная функция для определения модели и timeout на основе типа задачи.
    
    Args:
        task_type: Тип задачи ('psychologist', 'greeting', 'summary', 'ideas', 'quote', 'congrats')
        content: Содержимое для анализа
        additional_params: Дополнительные параметры для анализа
    
    Returns:
        Tuple[model_name, timeout]
    """
    additional_params = additional_params or {}
    
    # Простые задачи - используем gpt-5-nano для максимальной скорости
    simple_tasks = {
        'quote': ('gpt-3.5-turbo', 8),      # Цитаты: максимально быстро с GPT-3.5
        'short_summary': ('gpt-5-nano', 10), # Краткие резюме: быстро
        'simple_greeting': ('gpt-3.5-turbo', 8), # Простые приветствия: быстро с GPT-3.5
    }
    
    if task_type in simple_tasks:
        return simple_tasks[task_type]
    
    # Анализ сложности для остальных задач
    is_complex = False
    
    if task_type == 'psychologist':
        # Психология использует gpt-5-mini для оптимального баланса качества и экономии
        is_complex = _analyze_query_complexity(content)
        return ('gpt-5-mini', 30 if is_complex else 25)  # Оптимизированные таймауты
    
    elif task_type == 'summary':
        # Резюме - простая задача, используем gpt-5-nano
        return ('gpt-5-nano', 15)
    
    elif task_type == 'greeting':
        # Все приветствия используем GPT-3.5-turbo для скорости
        return ('gpt-3.5-turbo', 8)
    
    elif task_type == 'conversation_greeting':
        # Диалоговые приветствия - используем GPT-3.5-turbo для скорости
        return ('gpt-3.5-turbo', 8)
    
    elif task_type == 'ideas':
        previous_ideas = additional_params.get('previous_ideas', [])
        constraints = additional_params.get('constraints', '')
        category = additional_params.get('category', '')
        
        is_complex = (
            previous_ideas and len(previous_ideas) > 0 or
            len(constraints) > 100 or
            'бизнес' in category.lower() or
            len(category) > 50
        )
        return ('gpt-5-mini' if is_complex else 'gpt-5-nano', 45 if is_complex else 25)
    
    elif task_type == 'ideas_with_edits':
        edits = additional_params.get('edits', [])
        constraints = additional_params.get('constraints', '')
        category = additional_params.get('category', '')
        
        is_complex = (
            len(edits) > 2 or
            any(len(edit) > 50 for edit in edits) or
            len(constraints) > 100 or
            'бизнес' in category.lower()
        )
        return ('gpt-5-mini' if is_complex else 'gpt-5-nano', 50 if is_complex else 30)
    
    elif task_type == 'congrats':
        # Все поздравления используют gpt-5-mini для стабильности
        is_complex = len(content) > 50  # Простые vs развернутые
        return ('gpt-5-mini', 45 if is_complex else 35)
    
    elif task_type == 'congrats_with_edits':
        # Правки поздравлений всегда требуют качественной модели
        return ('gpt-5-mini', 45)
    
    # По умолчанию для неизвестных задач
    return ('gpt-5-nano', 20)

def _analyze_query_complexity(user_message: str) -> bool:
    """
    Анализирует сложность запроса пользователя.
    Возвращает True если запрос требует глубокого анализа (gpt-5-mini),
    False для простых запросов (gpt-5-nano).
    """
    if not user_message:
        return False
    
    # Сначала проверяем сложные паттерны (приоритет)
    complex_patterns = [
        # Вопросы о проблемах и эмоциях (высокий приоритет)
        any(word in user_message.lower() for word in [
            'проблем', 'депресс', 'тревож', 'стресс', 'паник', 'страх', 
            'отношени', 'конфликт', 'семь', 'работ', 'карьер', 'здоровь',
            'болезн', 'смерт', 'потер', 'развод', 'измен', 'предательств'
        ]),
        # Вопросительные слова требующие анализа
        any(word in user_message.lower() for word in [
            'почему', 'зачем', 'как быть', 'что делать', 'помогите', 'посоветуйте'
        ]),
        # Длинные сообщения требуют анализа
        len(user_message) > 80,
        # Множественные предложения
        user_message.count('.') > 2 or user_message.count('?') > 1,
    ]
    
    # Если есть признаки сложности - сразу возвращаем True
    if any(complex_patterns):
        return True
    
    # Простые критерии (только если нет сложных)
    simple_patterns = [
        # Очень короткие сообщения
        len(user_message) < 20,
        # Простые вопросы
        user_message.lower().startswith(('как дела', 'привет', 'спасибо', 'да', 'нет', 'хорошо', 'плохо')),
        # Односложные ответы
        len(user_message.split()) <= 3,
        # Эмодзи без текста
        len(user_message.strip()) <= 5 and any(ord(char) > 127 for char in user_message),
    ]
    
    # Если есть явные признаки простоты
    if any(simple_patterns):
        return False
    
    # По умолчанию для средних запросов используем nano для скорости
    return False

async def get_psychologist_response(context: list[ChatCompletionMessageParam], user_message: str) -> str:
    """Отправляет контекст и сообщение пользователя в OpenAI, возвращает ответ психолога."""
    start_time = time.time()
    # logger.info(f"[PERF] Начинаем запрос к OpenAI. Размер контекста: {len(context)} сообщений")
    
    messages = context + [{"role": "user", "content": user_message}]
    
    # Подсчитываем приблизительное количество токенов
    total_chars = sum(len(msg.get("content", "")) for msg in messages)
    estimated_tokens = total_chars // 4  # Приблизительно 4 символа = 1 токен
    
    # Определяем модель на основе сложности запроса
    model, timeout = _determine_model_for_task('psychologist', user_message)
    
    # logger.info(f"[PERF] Приблизительно {estimated_tokens} токенов. Модель: {model}")
    
    # Оптимизированные параметры для скорости
    gpt_start = time.time()
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        timeout=timeout
    )
    gpt_time = time.time() - gpt_start
    
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    finish_reason = response.choices[0].finish_reason if response and response.choices else "unknown"
    
    total_time = time.time() - start_time
    # logger.info(f"[PERF] Запрос к OpenAI завершен за: {total_time:.3f}s (чистое время GPT: {gpt_time:.3f}s)")
    # logger.info(f"[PERF] Получен ответ длиной {len(result)} символов, finish_reason: {finish_reason}")
    
    # Отладка пустых ответов
    if not result.strip():
        logger.warning(f"[GPT] ПУСТОЙ ОТВЕТ! finish_reason: {finish_reason}, model: {model}")
        logger.warning(f"[GPT] Пользователь: {user_message[:200]}...")
    
    return result

async def generate_response(prompt):
    """
    Генерирует поздравление по тексту prompt. Возвращает готовый текст (~10 предложений).
    """
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": (
            "Напиши красивое развернутое поздравление на русском языке (4-7 предложений). "
            "Учитывай пожелания пользователя. Поздравление должно быть теплым и искренним."
        )
    }
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": f"Пожелания при создании: {prompt}"}
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    # Определяем модель для генерации поздравлений
    model, timeout = _determine_model_for_task('congrats', prompt)
    
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        # temperature=1.0 по умолчанию для GPT-5
        timeout=timeout
    )
    answer = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not answer or not answer.strip():
        return "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."
    return answer.strip()


async def generate_response_with_edits(base_prompt, edits):
    """
    base_prompt   — исходный запрос пользователя
    edits         — список строк с пожеланиями правок
    """
    edit_instructions = "\n".join(f"{i+1}. {e}" for i, e in enumerate(edits))
    system: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": (
            f'Ты — генератор поздравлений. У тебя есть базовый запрос: "{base_prompt}".\n'
            f'Пользователь просит внести следующие правки:\n{edit_instructions}\n'
            'Сформируй обновлённый развернутый вариант (4-8 предложений).'
        )
    }
    messages: list[ChatCompletionMessageParam] = [system]
    # Правки поздравлений обычно требуют более качественной модели
    model, timeout = _determine_model_for_task('congrats_with_edits', base_prompt)
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=model,
        messages=messages,
        # temperature=1.0 по умолчанию для GPT-5
        timeout=timeout
    )
    result = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    # Fallback для пустых ответов от GPT-5
    if not result or not result.strip():
        return "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."
    return result.strip()


async def generate_daily_quote_model() -> dict:
    """
    Запрашивает у модели одну короткую вдохновляющую цитату и источник.
    Модель обязана вернуть JSON с полями:
      - quote (строка)
      - source (строка или пустая)
    При невалидном JSON возвращается fallback: весь ответ - quote, source=None.
    """
    system_msg: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": (
            "Ты — генератор коротких тёплых вдохновляющих цитат (1-2 предложения). "
            "ВАЖНО: Все цитаты должны быть строго на русском языке. "
            "Отвечай строго JSON-объектом с полями \"quote\" и \"source\". "
            "Если цитата твоего собственного сочинения, оставляй source пустым. "
            "Будь кратким и точным в ответе."
        )
    }
    if random.random() < 0.2:
        user_content = "Сгенерируй одну короткую тёплую цитату собственного сочинения на русском языке."
    else:
        user_content = (
            "Приведи одну короткую тёплую вдохновляющую цитату на русском языке из книги, фильма или сериала, "
            "и обязательно укажи её источник."
        )

    user_msg: ChatCompletionUserMessageParam = {"role": "user", "content": user_content}

    model, timeout = _determine_model_for_task('quote', user_content)
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model=model,
        messages=[system_msg, user_msg],
        temperature=0.7,  # Для более предсказуемых результатов
        max_tokens=100,   # Ограничиваем для скорости
        timeout=timeout
    )
    raw = resp.choices[0].message.content.strip() if resp and resp.choices and resp.choices[0].message.content else ""
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw, re.DOTALL)
    blob = (m.group(1) if m else raw).strip("` \n")

    try:
        data = json.loads(blob)
        quote = data.get("quote", "").strip("` \n")
        source = data.get("source", "").strip("` \n") or None
    except json.JSONDecodeError:
        quote = raw.strip("` \n")
        source = None

    return {"quote": quote, "source": source}

# --- Генерация идей ---

# Маппинг категорий и стилей для более понятных промптов
CATEGORY_MAPPING = {
    "gift": "подарок",
    "post": "пост для социальных сетей",
    "name": "название",
    "business": "бизнес-идея",
    "other": "идея",
    "сюрприз": "случайная идея"
}

STYLE_MAPPING = {
    "fun": "веселый и юмористический",
    "tender": "нежный и милый",
    "bold": "дерзкий и креативный",
    "stylish": "стильный и премиум",
    "other": "универсальный",
    "случайный": "случайный"
}

async def generate_ideas(category: str, style: str, constraints: str, previous_ideas: list = None) -> str:
    """
    Генерирует 3 идеи по заданным параметрам.
    
    Args:
        category: Категория идеи (может быть детализированной, например "gift (Кому: Маме, Бюджет: До 1000₽)")
        style: Стиль идеи (fun, tender, bold, stylish, other, случайный)
        constraints: Ограничения или пожелания пользователя
        previous_ideas: Список предыдущих идей для избежания повторов
    
    Returns:
        Строка с 3 идеями
    """
    # Если категория содержит детали в скобках, используем её как есть
    # Иначе пытаемся найти в маппинге
    if "(" in category and ")" in category:
        category_text = category  # Используем детализированную категорию как есть
    else:
        category_text = CATEGORY_MAPPING.get(category, category)
    
    style_text = STYLE_MAPPING.get(style, style)
    
    # Определяем модель на основе сложности задачи
    model, timeout = _determine_model_for_task('ideas', '', {
        'previous_ideas': previous_ideas,
        'constraints': constraints,
        'category': category_text
    })
    
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": (
            "Ты — креативный генератор идей. Твоя задача — придумать 3 уникальные, "
            "практичные и интересные идеи по запросу пользователя.\n\n"
            "Правила:\n"
            "- Каждая идея должна быть краткой (1-2 предложения)\n"
            "- Идеи должны быть реалистичными и выполнимыми\n"
            "- Используй эмодзи для визуального разделения\n"
            "- Формат ответа: пронумерованный список с эмодзи (всего 3 идеи)\n"
            "- Пиши на русском языке\n"
            "- Учитывай стиль и ограничения пользователя"
        )
    }
    
    user_content = f"Придумай 3 идеи для: {category_text}\n"
    user_content += f"Стиль: {style_text}\n"
    if constraints:
        user_content += f"Ограничения/пожелания: {constraints}\n"
    
    # Добавляем предыдущие идеи для избежания повторов
    if previous_ideas:
        user_content += f"\nИЗБЕГАЙ повторения этих уже предложенных идей:\n"
        for i, prev_idea in enumerate(previous_ideas, 1):
            user_content += f"- {prev_idea.strip()}\n"
        user_content += "\nСоздай 3 НОВЫЕ, УНИКАЛЬНЫЕ идеи, которые отличаются от уже предложенных.\n"
    
    user_content += "\nПредоставь 3 разные идеи в формате:\n1) [идея]\n2) [идея]\n3) [идея]"
    
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": user_content}
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        # temperature=1.0 по умолчанию для GPT-5
        timeout=timeout
    )
    
    answer = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    
    # Если ответ пустой, возвращаем fallback
    if not answer.strip():
        return "1) 🎁 Классический подарок с персональным подходом\n2) 🌟 Неожиданное решение с творческим подходом\n3) ✨ Инновационная идея с современным взглядом"
    
    return answer


async def generate_ideas_with_edits(category: str, style: str, constraints: str, edits: list, previous_ideas: list = None) -> str:
    """
    Генерирует обновленные идеи с учетом правок пользователя.
    
    Args:
        category: Категория идеи (может быть детализированной)
        style: Стиль идеи
        constraints: Исходные ограничения
        edits: Список правок от пользователя
        previous_ideas: Список предыдущих идей для избежания повторов
    
    Returns:
        Строка с обновленными идеями
    """
    # Если категория содержит детали в скобках, используем её как есть
    if "(" in category and ")" in category:
        category_text = category
    else:
        category_text = CATEGORY_MAPPING.get(category, category)
    
    style_text = STYLE_MAPPING.get(style, style)
    
    system_message: ChatCompletionSystemMessageParam = {
        "role": "system",
        "content": (
            "Ты — креативный генератор идей. Пользователь хочет доработать свои идеи. "
            "Учти все его пожелания и создай 3 обновленные идеи.\n\n"
            "Правила:\n"
            "- Каждая идея должна быть краткой (1-2 предложения)\n"
            "- Идеи должны быть реалистичными и выполнимыми\n"
            "- Используй эмодзи для визуального разделения\n"
            "- Формат ответа: пронумерованный список с эмодзи (всего 3 идеи)\n"
            "- Пиши на русском языке\n"
            "- Внимательно учти все правки пользователя"
        )
    }
    
    edit_instructions = "\n".join(f"{i+1}. {edit}" for i, edit in enumerate(edits))
    
    user_content = f"Исходные параметры:\n"
    user_content += f"- Категория: {category_text}\n"
    user_content += f"- Стиль: {style_text}\n"
    if constraints:
        user_content += f"- Ограничения: {constraints}\n"
    user_content += f"\nПравки пользователя:\n{edit_instructions}\n"
    
    # Добавляем предыдущие идеи для избежания повторов
    if previous_ideas:
        user_content += f"\nИЗБЕГАЙ повторения этих уже предложенных идей:\n"
        for i, prev_idea in enumerate(previous_ideas, 1):
            user_content += f"- {prev_idea.strip()}\n"
        user_content += "\nСоздай 3 НОВЫЕ идеи с учетом правок, но отличающиеся от уже предложенных.\n"
    
    user_content += "\nСоздай 3 обновленные идеи с учетом всех правок в формате:\n1) [идея]\n2) [идея]\n3) [идея]"
    
    user_message: ChatCompletionUserMessageParam = {"role": "user", "content": user_content}
    messages: list[ChatCompletionMessageParam] = [system_message, user_message]
    
    # Определяем модель на основе сложности правок
    model, timeout = _determine_model_for_task('ideas_with_edits', '', {
        'edits': edits,
        'constraints': constraints,
        'category': category_text
    })
    
    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        # temperature=1.0 по умолчанию для GPT-5
        timeout=timeout
    )
    
    answer = response.choices[0].message.content if response and response.choices and response.choices[0].message.content else ""
    
    # Если ответ пустой, возвращаем fallback
    if not answer.strip():
        return "1) 🎁 Обновленная идея с учетом ваших пожеланий\n2) 🌟 Улучшенное решение по вашим критериям\n3) ✨ Новая версия с вашими правками"
    
    return answer


async def generate_goal_checklist(goal: str, timeframe: str, preferences: str) -> str:
    """
    Генерирует чек-лист для достижения цели
    
    Args:
        goal: Цель пользователя
        timeframe: Временные рамки для достижения цели
        preferences: Предпочтения и особенности пользователя
    
    Returns:
        str: Сгенерированный чек-лист
    """
    try:
        prompt = f"""Создай подробный и практичный чек-лист для достижения цели.

ЦЕЛЬ: {goal}
ВРЕМЕННЫЕ РАМКИ: {timeframe}
ПРЕДПОЧТЕНИЯ ПОЛЬЗОВАТЕЛЯ: {preferences}

ТРЕБОВАНИЯ к чек-листу:
- Разбей цель на конкретные, выполнимые шаги
- Каждый шаг должен быть четким и измеримым
- Учти указанные временные рамки
- Ограничь ответ до 1500 символов для удобства чтения

ФОРМАТ ОТВЕТА:
Если у пользователя есть особые предпочтения по стилю - следуй им строго.
Если предпочтения стандартные (минималистичный, яркий, простой, деловой стиль) или "другое" без деталей - используй красивый стандартный формат:

🎯 **ЦЕЛЬ: [название цели]**
⏰ **СРОК: [временные рамки]**

📋 **ЧЕК-ЛИСТ ДОСТИЖЕНИЯ:**

✅ **Шаг 1:** [конкретное действие]
   💡 *Совет: [практический совет]*

✅ **Шаг 2:** [конкретное действие]
   💡 *Совет: [практический совет]*

[продолжай в том же формате...]

[Мотивирующий текст о том, как здорово будет достичь эту цель]

[Вдохновляющие слова на успех]

ВАЖНО: 
1. Если пользователь указал конкретные требования (без эмодзи, в форме ТЗ, краткие пункты и т.д.) - строго следуй им
2. Если предпочтения общие или стандартные - используй красивый формат выше
3. Создай чек-лист, который действительно поможет достичь цели!"""

        # logger.info(f"Отправляем запрос к GPT для генерации чек-листа цели")
        
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты профессиональный коуч по достижению целей. Создаешь практичные и мотивирующие чек-листы в красивом формате для открыток."},
                {"role": "user", "content": prompt}
            ]
        )
        
        answer = response.choices[0].message.content.strip()
        
        if not answer:
            return "❌ Не удалось создать чек-лист. Попробуйте еще раз с более подробным описанием цели."
        
        return answer
        
    except Exception as e:
        logger.error(f"Ошибка при генерации чек-листа цели: {e}")
        return "❌ Произошла ошибка при создании чек-листа. Попробуйте еще раз."
