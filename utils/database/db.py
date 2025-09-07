import os
import asyncpg
from datetime import datetime, timezone, timedelta, date
from dateutil.relativedelta import relativedelta
from typing import Optional, List, Dict, Any

DATABASE_URL = os.getenv("DATABASE_URL")

# Пул соединений для оптимизации производительности
_connection_pool = None

async def init_connection_pool():
    """Инициализирует пул соединений к базе данных."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=5,  # Минимум соединений
            max_size=20,  # Максимум соединений
            command_timeout=30,  # Таймаут команд
            server_settings={
                'jit': 'off'  # Отключаем JIT для стабильности
            }
        )
    return _connection_pool

async def get_connection():
    """Получает соединение из пула."""
    pool = await init_connection_pool()
    return await pool.acquire()

async def release_connection(conn):
    """Возвращает соединение в пул."""
    pool = await init_connection_pool()
    await pool.release(conn)

async def init_db():
    conn = await get_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id     BIGINT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'main',
            expires_at  TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (user_id, type)
        );
    """)
    
    # Инициализируем таблицы для идей
    await init_ideas_tables()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     BIGINT PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            last_activity TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    
    # Создаем индексы для оптимизации запросов
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity);
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id          SERIAL PRIMARY KEY,
            text        TEXT NOT NULL,
            media_files TEXT, -- JSON строка с медиафайлами
            scheduled_at TIMESTAMP WITH TIME ZONE,
            sent_at     TIMESTAMP WITH TIME ZONE,
            created_by  BIGINT NOT NULL,
            created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            is_sent     BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    
    # Миграция: изменяем тип поля media_files с TEXT[] на TEXT если нужно
    try:
        await conn.execute("""
            ALTER TABLE notifications 
            ALTER COLUMN media_files TYPE TEXT;
        """)
    except Exception:
        # Поле уже имеет правильный тип или таблица не существует
        pass
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_quotes (
            user_id     BIGINT,
            quote_date  DATE,
            quote       TEXT,
            source      TEXT,
            PRIMARY KEY(user_id, quote_date)
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS fonts (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL UNIQUE,
            font_path    TEXT NOT NULL,
            sample_path  TEXT NOT NULL,
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS colors (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL UNIQUE,
            hex_code     TEXT NOT NULL,
            sample_path  TEXT NOT NULL,
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS future_letters (
            id          SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TIMESTAMP WITH TIME ZONE NOT NULL,
            send_after  TIMESTAMP WITH TIME ZONE NOT NULL,
            is_sent     BOOLEAN NOT NULL,
            is_free     BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS psychologist_history (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TIMESTAMP WITH TIME ZONE NOT NULL
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS psychologist_summary (
            user_id BIGINT PRIMARY KEY,
            summary TEXT NOT NULL,
            ts TIMESTAMP WITH TIME ZONE NOT NULL
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS psychologist_free_count (
            user_id BIGINT PRIMARY KEY,
            free_count INT NOT NULL DEFAULT 0
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS service_status (
            service_name TEXT PRIMARY KEY,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            maintenance_message TEXT,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    await conn.close()

async def upsert_subscription(user_id: int, expires_at: str, type: str = 'main'):
    conn = await get_connection()
    await conn.execute("""
        INSERT INTO subscriptions(user_id, type, expires_at)
        VALUES ($1, $2, $3)
        ON CONFLICT(user_id, type) DO UPDATE SET expires_at = EXCLUDED.expires_at;
    """, user_id, type, expires_at)
    await conn.close()

async def fetch_subscription(user_id: int, type: str = 'main'):
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT user_id, type, expires_at FROM subscriptions WHERE user_id = $1 AND type = $2;",
        user_id, type
    )
    await conn.close()
    if not row:
        return None
    uid, sub_type, expires = row["user_id"], row["type"], row["expires_at"]
    return {"user_id": uid, "type": sub_type, "expires_at": expires}

async def delete_subscription(user_id: int, type: str = 'main'):
    conn = await get_connection()
    await conn.execute(
        "DELETE FROM subscriptions WHERE user_id = $1 AND type = $2;",
        user_id, type
    )
    await conn.close()

# Для совместимости: старые вызовы без type
# (оставить, если где-то используется)
# async def upsert_subscription(user_id: int, expires_at: str): ...
# async def fetch_subscription(user_id: int): ...
# async def delete_subscription(user_id: int): ...

async def fetch_daily_quote(user_id: int, quote_date: str):
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT quote, source FROM daily_quotes WHERE user_id = $1 AND quote_date = $2;",
        user_id, quote_date
    )
    await conn.close()
    if not row:
        return None
    return row["quote"], row["source"]

async def upsert_daily_quote(user_id: int, quote_date: str, quote: str, source: str | None):
    conn = await get_connection()
    await conn.execute("""
        INSERT INTO daily_quotes(user_id, quote_date, quote, source)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT(user_id, quote_date) DO UPDATE SET
            quote = EXCLUDED.quote,
            source = EXCLUDED.source;
    """, user_id, quote_date, quote, source)
    await conn.close()

async def add_font(name: str, font_path: str, sample_path: str):
    now = datetime.now(timezone.utc)
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO fonts(name, font_path, sample_path, created_at) VALUES ($1, $2, $3, $4);",
        name, font_path, sample_path, now
    )
    await conn.close()

async def list_fonts():
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT id, name, font_path, sample_path FROM fonts ORDER BY id;"
    )
    await conn.close()
    return [
        {"id": r["id"], "name": r["name"], "font_path": r["font_path"], "sample_path": r["sample_path"]}
        for r in rows
    ]

async def delete_font(font_id: int):
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT font_path, sample_path FROM fonts WHERE id = $1;",
        font_id
    )
    await conn.execute(
        "DELETE FROM fonts WHERE id = $1;",
        font_id
    )
    await conn.close()
    if not row:
        return None
    return row["font_path"], row["sample_path"]

async def add_color(name: str, hex_code: str, sample_path: str):
    now = datetime.now(timezone.utc)
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO colors(name, hex_code, sample_path, created_at) VALUES ($1, $2, $3, $4);",
        name, hex_code, sample_path, now
    )
    await conn.close()

async def list_colors():
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT id, name, hex_code, sample_path FROM colors ORDER BY id;"
    )
    await conn.close()
    return [
        {"id": r["id"], "name": r["name"], "hex_code": r["hex_code"], "sample_path": r["sample_path"]}
        for r in rows
    ]

async def delete_color(color_id: int):
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT sample_path FROM colors WHERE id = $1;",
        color_id
    )
    await conn.execute(
        "DELETE FROM colors WHERE id = $1;",
        color_id
    )
    await conn.close()
    if not row:
        return None
    return row["sample_path"]

async def upsert_future_letter(user_id: int, content: str, send_after: datetime, *, is_free: bool = False):
    now = datetime.now(timezone.utc)
    conn = await get_connection()
    row = await conn.fetchrow(
        """
        INSERT INTO future_letters(user_id, content, created_at, send_after, is_sent, is_free)
        VALUES ($1, $2, $3, $4, FALSE, $5)
        RETURNING id
        """, user_id, content, now, send_after, is_free)
    await conn.close()
    return row['id'] if row else None

async def fetch_due_letters():
    now = datetime.now(timezone.utc)
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT * FROM future_letters WHERE is_sent = FALSE AND send_after <= $1;",
        now
    )
    await conn.close()
    return [dict(r) for r in rows]

async def fetch_all_unsent_letters():
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT * FROM future_letters WHERE is_sent = FALSE;"
    )
    await conn.close()
    return [dict(r) for r in rows]

async def mark_letter_sent(letter_id: int):
    conn = await get_connection()
    await conn.execute(
        "UPDATE future_letters SET is_sent = TRUE WHERE id = $1;",
        letter_id
    )
    await conn.close()

async def count_free_letters_in_month(user_id: int, reference_date: Optional[datetime] = None) -> int:
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    month_start = reference_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start + relativedelta(months=1))
    conn = await get_connection()
    row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS cnt FROM future_letters
        WHERE user_id = $1 AND is_free = TRUE AND created_at >= $2 AND created_at < $3;
        """,
        user_id, month_start, next_month
    )
    await conn.close()
    return row["cnt"] if row else 0

# --- Психолог: история и резюме ---

async def save_history_message(user_id: int, role: str, content: str):
    """Сохраняет сообщение в историю пользователя."""
    now = datetime.now(timezone.utc)
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO psychologist_history(user_id, role, content, ts) VALUES ($1, $2, $3, $4);",
        user_id, role, content, now
    )
    await conn.close()

async def save_user_and_bot_messages(user_id: int, user_message: str, bot_message: str):
    """Сохраняет сообщение пользователя и ответ бота в одной транзакции для ускорения."""
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    
    try:
        # Используем транзакцию для атомарности и скорости
        async with conn.transaction():
            # Сохраняем оба сообщения одним запросом для максимальной скорости
            await conn.executemany(
                "INSERT INTO psychologist_history(user_id, role, content, ts) VALUES ($1, $2, $3, $4);",
                [
                    (user_id, "user", user_message, now),
                    (user_id, "assistant", bot_message, now)
                ]
            )
    finally:
        await release_connection(conn)

async def count_history_messages(user_id: int) -> int:
    """Возвращает количество сообщений в истории пользователя."""
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM psychologist_history WHERE user_id = $1;",
            user_id
        )
        return row["cnt"] if row else 0
    finally:
        await release_connection(conn)

async def clear_history(user_id: int):
    """Очищает историю сообщений пользователя."""
    conn = await get_connection()
    await conn.execute(
        "DELETE FROM psychologist_history WHERE user_id = $1;",
        user_id
    )
    await conn.close()

async def get_last_user_message_time(user_id: int) -> float:
    """Возвращает timestamp последнего сообщения пользователя (или None)."""
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT ts FROM psychologist_history WHERE user_id = $1 AND role = 'user' ORDER BY ts DESC LIMIT 1;",
        user_id
    )
    await conn.close()
    if row and row["ts"]:
        return row["ts"].timestamp()
    return None

async def get_oldest_history_messages(user_id: int, n: int):
    """Возвращает n самых старых сообщений пользователя (список словарей)."""
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT role, content FROM psychologist_history WHERE user_id = $1 ORDER BY ts ASC LIMIT $2;",
        user_id, n
    )
    await conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

async def save_summary(user_id: int, summary: str):
    """Сохраняет или обновляет резюме пользователя."""
    now = datetime.now(timezone.utc)
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO psychologist_summary(user_id, summary, ts)
        VALUES ($1, $2, $3)
        ON CONFLICT(user_id) DO UPDATE SET summary = EXCLUDED.summary, ts = EXCLUDED.ts;
        """,
        user_id, summary, now
    )
    await conn.close()

async def delete_oldest_history_messages(user_id: int, n: int):
    """Удаляет n самых старых сообщений пользователя."""
    conn = await get_connection()
    # Получаем id старейших сообщений
    rows = await conn.fetch(
        "SELECT id FROM psychologist_history WHERE user_id = $1 ORDER BY ts ASC LIMIT $2;",
        user_id, n
    )
    ids = [r["id"] for r in rows]
    if ids:
        await conn.execute(
            f"DELETE FROM psychologist_history WHERE id = ANY($1);",
            ids
        )
    await conn.close()

async def get_summary(user_id: int) -> str:
    """Возвращает текущее резюме пользователя (или None)."""
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT summary FROM psychologist_summary WHERE user_id = $1;",
        user_id
    )
    await conn.close()
    return row["summary"] if row else None

async def get_summary_and_history(user_id: int, m: int = 5):
    """Возвращает резюме и последние m сообщений одним запросом для оптимизации."""
    conn = await get_connection()
    
    try:
        # Получаем резюме и историю в одном подключении
        summary_row = await conn.fetchrow(
            "SELECT summary FROM psychologist_summary WHERE user_id = $1;",
            user_id
        )
        
        history_rows = await conn.fetch(
            "SELECT role, content FROM psychologist_history WHERE user_id = $1 ORDER BY ts DESC LIMIT $2;",
            user_id, m
        )
        
        summary = summary_row["summary"] if summary_row else None
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]
        
        return summary, history
    finally:
        await release_connection(conn)

async def get_last_history_messages(user_id: int, m: int):
    """Возвращает m последних сообщений пользователя (список словарей)."""
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT role, content FROM psychologist_history WHERE user_id = $1 ORDER BY ts DESC LIMIT $2;",
        user_id, m
    )
    await conn.close()
    # Возвращаем в хронологическом порядке (от старых к новым)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def get_last_user_messages(user_id: int, m: int):
    """Возвращает m последних сообщений пользователя (только с role='user')."""
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT role, content FROM psychologist_history WHERE user_id = $1 AND role = 'user' ORDER BY ts DESC LIMIT $2;",
        user_id, m
    )
    await conn.close()
    # Возвращаем в хронологическом порядке (от старых к новым)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def get_last_conversation_messages(user_id: int):
    """Возвращает последнюю связанную пару сообщений: вопрос пользователя и ответ бота."""
    conn = await get_connection()
    
    # Получаем последние 4 сообщения, чтобы найти последнюю пару "пользователь -> бот"
    rows = await conn.fetch(
        "SELECT role, content FROM psychologist_history WHERE user_id = $1 ORDER BY ts DESC LIMIT 4;",
        user_id
    )
    
    await conn.close()
    
    if not rows:
        return None, None
    
    # Ищем последнюю пару: сообщение пользователя, за которым следует ответ бота
    user_message = None
    bot_message = None
    
    # Проходим по сообщениям в хронологическом порядке (от новых к старым)
    for i in range(len(rows) - 1):
        current_msg = rows[i]
        next_msg = rows[i + 1]
        
        # Если текущее сообщение от бота, а следующее (более раннее) от пользователя
        if current_msg['role'] == 'assistant' and next_msg['role'] == 'user':
            bot_message = current_msg['content']
            user_message = next_msg['content']
            break
    
    # Если не нашли пару, возвращаем просто последнее сообщение пользователя
    if not user_message:
        for row in rows:
            if row['role'] == 'user':
                user_message = row['content']
                break
    
    return user_message, bot_message

async def get_free_count(user_id: int) -> int:
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT free_count FROM psychologist_free_count WHERE user_id = $1;",
        user_id
    )
    await conn.close()
    return row["free_count"] if row else 0

async def increment_free_count(user_id: int) -> int:
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO psychologist_free_count(user_id, free_count)
        VALUES ($1, 1)
        ON CONFLICT(user_id) DO UPDATE SET free_count = psychologist_free_count.free_count + 1;
        """,
        user_id
    )
    row = await conn.fetchrow(
        "SELECT free_count FROM psychologist_free_count WHERE user_id = $1;",
        user_id
    )
    await conn.close()
    return row["free_count"] if row else 1

async def reset_free_count(user_id: int):
    conn = await get_connection()
    await conn.execute(
        "DELETE FROM psychologist_free_count WHERE user_id = $1;",
        user_id
    )
    await conn.close()

async def set_free_count(user_id: int, value: int):
    conn = await get_connection()
    await conn.execute(
        """
        INSERT INTO psychologist_free_count(user_id, free_count)
        VALUES ($1, $2)
        ON CONFLICT(user_id) DO UPDATE SET free_count = $2;
        """,
        user_id, value
    )
    await conn.close()

# --- Функции управления сервисами ---

async def get_service_status(service_name: str) -> dict:
    """Получает статус сервиса."""
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT service_name, is_active, maintenance_message, updated_at FROM service_status WHERE service_name = $1;",
        service_name
    )
    await conn.close()
    if row:
        return {
            "service_name": row["service_name"],
            "is_active": row["is_active"],
            "maintenance_message": row["maintenance_message"],
            "updated_at": row["updated_at"]
        }
    return None

async def set_service_status(service_name: str, is_active: bool, maintenance_message: str = None):
    """Устанавливает статус сервиса."""
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO service_status(service_name, is_active, maintenance_message, updated_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT(service_name) DO UPDATE SET
            is_active = EXCLUDED.is_active,
            maintenance_message = EXCLUDED.maintenance_message,
            updated_at = EXCLUDED.updated_at;
        """,
        service_name, is_active, maintenance_message, now
    )
    await conn.close()

async def get_all_services_status() -> list:
    """Получает статус всех сервисов."""
    conn = await get_connection()
    rows = await conn.fetch(
        "SELECT service_name, is_active, maintenance_message, updated_at FROM service_status ORDER BY service_name;"
    )
    await conn.close()
    return [
        {
            "service_name": row["service_name"],
            "is_active": row["is_active"],
            "maintenance_message": row["maintenance_message"],
            "updated_at": row["updated_at"]
        }
        for row in rows
    ]

async def is_service_active(service_name: str) -> bool:
    """Проверяет, активен ли сервис."""
    status = await get_service_status(service_name)
    return status["is_active"] if status else True  # По умолчанию сервис активен

# --- Функции для работы с пользователями ---

async def upsert_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    """Добавляет или обновляет информацию о пользователе."""
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO users(user_id, username, first_name, last_name, created_at, last_activity)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            first_name = COALESCE(EXCLUDED.first_name, users.first_name),
            last_name = COALESCE(EXCLUDED.last_name, users.last_name),
            last_activity = EXCLUDED.last_activity;
        """,
        user_id, username, first_name, last_name, now, now
    )
    await conn.close()

async def get_all_users(active_only: bool = False, limit: int = None) -> list:
    """
    Получает список всех пользователей с возможностью фильтрации.
    
    Args:
        active_only: Если True, возвращает только активных пользователей (за последние 30 дней)
        limit: Максимальное количество пользователей для возврата (None = все)
    
    Returns:
        list: Список пользователей
    """
    conn = await get_connection()
    
    if active_only:
        thirty_days_ago = datetime.now(timezone.utc) - relativedelta(days=30)
        if limit:
            rows = await conn.fetch(
                """
                SELECT user_id, username, first_name, last_name, created_at, last_activity 
                FROM users 
                WHERE last_activity >= $1
                ORDER BY last_activity DESC 
                LIMIT $2;
                """,
                thirty_days_ago, limit
            )
        else:
            rows = await conn.fetch(
                """
                SELECT user_id, username, first_name, last_name, created_at, last_activity 
                FROM users 
                WHERE last_activity >= $1
                ORDER BY last_activity DESC;
                """,
                thirty_days_ago
            )
    else:
        if limit:
            rows = await conn.fetch(
                """
                SELECT user_id, username, first_name, last_name, created_at, last_activity 
                FROM users 
                ORDER BY last_activity DESC 
                LIMIT $1;
                """,
                limit
            )
        else:
            rows = await conn.fetch(
                """
                SELECT user_id, username, first_name, last_name, created_at, last_activity 
                FROM users 
                ORDER BY last_activity DESC;
                """
            )
    
    await conn.close()
    return [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "created_at": row["created_at"],
            "last_activity": row["last_activity"]
        }
        for row in rows
    ]

async def get_users_batch(limit: int = 1000, offset: int = 0, active_only: bool = True) -> list:
    """
    Получает пользователей порциями для оптимизации больших рассылок.
    
    Args:
        limit: Количество пользователей для получения
        offset: Смещение от начала списка
        active_only: Если True, возвращает только активных пользователей (за последние 30 дней)
    
    Returns:
        list: Список пользователей
    """
    conn = await get_connection()
    
    if active_only:
        thirty_days_ago = datetime.now(timezone.utc) - relativedelta(days=30)
        rows = await conn.fetch(
            """
            SELECT user_id, username, first_name, last_name, created_at, last_activity 
            FROM users 
            WHERE last_activity >= $1
            ORDER BY last_activity DESC 
            LIMIT $2 OFFSET $3;
            """,
            thirty_days_ago, limit, offset
        )
    else:
        rows = await conn.fetch(
            """
            SELECT user_id, username, first_name, last_name, created_at, last_activity 
            FROM users 
            ORDER BY last_activity DESC 
            LIMIT $1 OFFSET $2;
            """,
            limit, offset
        )
    
    await conn.close()
    return [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "created_at": row["created_at"],
            "last_activity": row["last_activity"]
        }
        for row in rows
    ]

async def get_users_count(active_only: bool = True) -> int:
    """
    Получает общее количество пользователей.
    
    Args:
        active_only: Если True, считает только активных пользователей (за последние 30 дней)
    
    Returns:
        int: Количество пользователей
    """
    conn = await get_connection()
    
    if active_only:
        thirty_days_ago = datetime.now(timezone.utc) - relativedelta(days=30)
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM users WHERE last_activity >= $1;",
            thirty_days_ago
        )
    else:
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM users;")
    
    await conn.close()
    return row["cnt"] if row else 0

async def get_active_users_count() -> int:
    """Получает количество активных пользователей (за последние 30 дней)."""
    conn = await get_connection()
    thirty_days_ago = datetime.now(timezone.utc) - relativedelta(days=30)
    row = await conn.fetchrow(
        "SELECT COUNT(*) AS cnt FROM users WHERE last_activity >= $1;",
        thirty_days_ago
    )
    await conn.close()
    return row["cnt"] if row else 0

# --- Функции для работы с уведомлениями ---

async def create_notification(text: str, media_files: list = None, scheduled_at: datetime = None, created_by: int = None) -> int:
    """Создает новое уведомление и возвращает его ID."""
    import json
    
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    
    # Если media_files не передан, используем пустой список
    if media_files is None:
        media_files = []
    
    # Сериализуем media_files в JSON строку
    media_files_json = json.dumps(media_files) if media_files else "[]"
    
    row = await conn.fetchrow(
        """
        INSERT INTO notifications(text, media_files, scheduled_at, created_by, created_at)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        text, media_files_json, scheduled_at, created_by, now
    )
    await conn.close()
    return row['id'] if row else None

async def get_notification(notification_id: int) -> dict:
    """Получает уведомление по ID."""
    import json
    
    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT * FROM notifications WHERE id = $1;",
        notification_id
    )
    await conn.close()
    if row:
        result = dict(row)
        # Десериализуем media_files из JSON
        if result.get('media_files') and result['media_files'] != '[]':
            try:
                result['media_files'] = json.loads(result['media_files'])
            except (json.JSONDecodeError, TypeError):
                result['media_files'] = []
        else:
            result['media_files'] = []
        return result
    return None

async def get_pending_notifications() -> list:
    """Получает все ожидающие отправки уведомления."""
    import json
    
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    
    # Для запланированных уведомлений проверяем, что время прошло
    # Для немедленных уведомлений (scheduled_at IS NULL) отправляем сразу
    rows = await conn.fetch(
        """
        SELECT * FROM notifications 
        WHERE is_sent = FALSE 
        AND (scheduled_at IS NULL OR scheduled_at <= $1)
        ORDER BY 
            CASE WHEN scheduled_at IS NULL THEN 0 ELSE 1 END,  -- Сначала немедленные
            scheduled_at ASC,  -- Затем по времени планирования
            created_at ASC     -- Наконец по времени создания
        """,
        now
    )
    await conn.close()
    
    result = []
    for row in rows:
        notification = dict(row)
        # Десериализуем media_files из JSON
        if notification.get('media_files') and notification['media_files'] != '[]':
            try:
                notification['media_files'] = json.loads(notification['media_files'])
            except (json.JSONDecodeError, TypeError):
                notification['media_files'] = []
        else:
            notification['media_files'] = []
        result.append(notification)
    
    return result

async def mark_notification_sent(notification_id: int):
    """Отмечает уведомление как отправленное."""
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    await conn.execute(
        "UPDATE notifications SET is_sent = TRUE, sent_at = $1 WHERE id = $2;",
        now, notification_id
    )
    await conn.close()

async def get_notifications_history(limit: int = 50) -> list:
    """Получает историю уведомлений."""
    import json
    
    conn = await get_connection()
    rows = await conn.fetch(
        """
        SELECT * FROM notifications 
        ORDER BY created_at DESC 
        LIMIT $1;
        """,
        limit
    )
    await conn.close()
    
    result = []
    for row in rows:
        notification = dict(row)
        # Десериализуем media_files из JSON
        if notification.get('media_files') and notification['media_files'] != '[]':
            try:
                notification['media_files'] = json.loads(notification['media_files'])
            except (json.JSONDecodeError, TypeError):
                notification['media_files'] = []
        else:
            notification['media_files'] = []
        result.append(notification)
    
    return result


async def get_next_notification_time() -> Optional[datetime]:
    """Получает время следующего запланированного уведомления."""
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    
    # Ищем ближайшее запланированное уведомление в ближайшие 5 минут
    row = await conn.fetchrow(
        """
        SELECT scheduled_at FROM notifications 
        WHERE is_sent = FALSE 
        AND scheduled_at IS NOT NULL 
        AND scheduled_at > $1 
        AND scheduled_at <= $2
        ORDER BY scheduled_at ASC 
        LIMIT 1;
        """,
        now, now + timedelta(minutes=5)
    )
    await conn.close()
    
    return row['scheduled_at'] if row else None




async def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя."""
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO users(user_id, last_activity)
        VALUES ($1, $2)
        ON CONFLICT(user_id) DO UPDATE SET last_activity = EXCLUDED.last_activity;
        """,
        user_id, now
    )
    await conn.close()


async def batch_update_user_activity(user_ids: list):
    """Пакетное обновление активности пользователей (оптимизированная версия)."""
    if not user_ids:
        return
    
    conn = await get_connection()
    now = datetime.now(timezone.utc)
    
    try:
        # Используем VALUES для пакетной вставки без временной таблицы
        values_list = []
        for user_id in user_ids:
            values_list.append(f"({user_id}, '{now.isoformat()}')")
        
        values_str = ", ".join(values_list)
        
        # Обновляем активность всех пользователей одним запросом
        await conn.execute(f"""
            INSERT INTO users(user_id, last_activity)
            VALUES {values_str}
            ON CONFLICT(user_id) DO UPDATE SET last_activity = EXCLUDED.last_activity;
        """)
        
    except Exception as e:
        # Если пакетная вставка не удалась, используем обычную
        for user_id in user_ids:
            try:
                await conn.execute(
                    """
                    INSERT INTO users(user_id, last_activity)
                    VALUES ($1, $2)
                    ON CONFLICT(user_id) DO UPDATE SET last_activity = EXCLUDED.last_activity;
                    """,
                    user_id, now
                )
            except Exception as inner_e:
                # Логируем ошибку, но продолжаем обработку
                print(f"Ошибка при обновлении активности пользователя {user_id}: {inner_e}")
    
    finally:
        await conn.close()

# --- Функции для работы с идеями ---

async def init_ideas_tables():
    """Инициализирует таблицы для идей."""
    conn = await get_connection()
    
    # Таблица для сессий идей
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ideas_sessions (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT NOT NULL,
            category        TEXT NOT NULL,
            style           TEXT NOT NULL,
            constraints     TEXT,
            ideas_text      TEXT NOT NULL,
            is_surprise     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    
    # Таблица для отслеживания ежедневных сюрприз-идей
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_surprise_ideas (
            user_id         BIGINT NOT NULL,
            used_date       DATE NOT NULL,
            created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, used_date)
        );
    """)
    
    # Создаем индексы для оптимизации
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ideas_sessions_user_id ON ideas_sessions(user_id);
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ideas_sessions_created_at ON ideas_sessions(created_at);
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_surprise_ideas_user_date ON daily_surprise_ideas(user_id, used_date);
    """)
    
    await conn.close()


async def save_ideas_session(
    user_id: int,
    category: str,
    style: str,
    constraints: str,
    ideas_text: str,
    is_surprise: bool = False
) -> int:
    """
    Сохраняет сессию генерации идей.
    
    Args:
        user_id: ID пользователя
        category: Категория идеи
        style: Стиль идеи
        constraints: Ограничения пользователя
        ideas_text: Сгенерированные идеи
        is_surprise: Является ли сюрприз-идеей
    
    Returns:
        ID сохраненной сессии
    """
    conn = await get_connection()
    
    try:
        result = await conn.fetchrow("""
            INSERT INTO ideas_sessions 
            (user_id, category, style, constraints, ideas_text, is_surprise)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """, user_id, category, style, constraints, ideas_text, is_surprise)
        
        return result['id'] if result else None
    finally:
        await conn.close()


async def get_user_ideas_history(user_id: int, limit: int = 10) -> list[Dict[str, Any]]:
    """
    Получает историю идей пользователя.
    
    Args:
        user_id: ID пользователя
        limit: Количество записей для получения
    
    Returns:
        Список сессий идей
    """
    conn = await get_connection()
    
    try:
        rows = await conn.fetch("""
            SELECT id, category, style, constraints, ideas_text, is_surprise, created_at
            FROM ideas_sessions
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        """, user_id, limit)
        
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def get_daily_surprise_used(user_id: int) -> bool:
    """
    Проверяет, использовал ли пользователь сюрприз-идею сегодня.
    
    Args:
        user_id: ID пользователя
    
    Returns:
        True если сюрприз уже использован сегодня
    """
    conn = await get_connection()
    
    try:
        today = date.today()
        result = await conn.fetchrow("""
            SELECT 1 FROM daily_surprise_ideas
            WHERE user_id = $1 AND used_date = $2
        """, user_id, today)
        
        return result is not None
    finally:
        await conn.close()


async def mark_daily_surprise_used(user_id: int) -> None:
    """
    Отмечает, что пользователь использовал сюрприз-идею сегодня.
    
    Args:
        user_id: ID пользователя
    """
    conn = await get_connection()
    
    try:
        today = date.today()
        await conn.execute("""
            INSERT INTO daily_surprise_ideas (user_id, used_date)
            VALUES ($1, $2)
            ON CONFLICT (user_id, used_date) DO NOTHING
        """, user_id, today)
    finally:
        await conn.close()


async def get_ideas_stats(user_id: int) -> Dict[str, Any]:
    """
    Получает статистику по идеям пользователя.
    
    Args:
        user_id: ID пользователя
    
    Returns:
        Словарь со статистикой
    """
    conn = await get_connection()
    
    try:
        # Общее количество сессий
        total_sessions = await conn.fetchval("""
            SELECT COUNT(*) FROM ideas_sessions WHERE user_id = $1
        """, user_id)
        
        # Количество сюрприз-идей
        surprise_count = await conn.fetchval("""
            SELECT COUNT(*) FROM ideas_sessions 
            WHERE user_id = $1 AND is_surprise = TRUE
        """, user_id)
        
        # Самая популярная категория
        popular_category = await conn.fetchval("""
            SELECT category FROM ideas_sessions 
            WHERE user_id = $1 
            GROUP BY category 
            ORDER BY COUNT(*) DESC 
            LIMIT 1
        """, user_id)
        
        # Последняя сессия
        last_session = await conn.fetchrow("""
            SELECT created_at FROM ideas_sessions 
            WHERE user_id = $1 
            ORDER BY created_at DESC 
            LIMIT 1
        """, user_id)
        
        return {
            "total_sessions": total_sessions or 0,
            "surprise_count": surprise_count or 0,
            "popular_category": popular_category,
            "last_session": last_session['created_at'] if last_session else None
        }
    finally:
        await conn.close()


async def cleanup_old_ideas_sessions(days: int = 30) -> int:
    """
    Удаляет старые сессии идей.
    
    Args:
        days: Количество дней для хранения
    
    Returns:
        Количество удаленных записей
    """
    conn = await get_connection()
    
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        result = await conn.execute("""
            DELETE FROM ideas_sessions 
            WHERE created_at < $1
        """, cutoff_date)
        
        # Получаем количество удаленных строк
        deleted_count = int(result.split()[-1]) if result else 0
        return deleted_count
    finally:
        await conn.close()
