import aiosqlite

from pathlib import Path
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta


DB_PATH = Path(__file__).parent / "subscriptions.db"


async def init_db():
    """
    Инициализирует БД: создаёт таблицы subscriptions и daily_quotes, если их ещё нет.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id     INTEGER PRIMARY KEY,
                expires_at  TEXT NOT NULL
            )
        """
        )

        await db.execute("""
                    CREATE TABLE IF NOT EXISTS daily_quotes (
                        user_id     INTEGER,
                        quote_date  TEXT,
                        quote       TEXT,
                        source      TEXT,
                        PRIMARY KEY(user_id, quote_date)
                    )
                """
        )

        await db.execute("""
                    CREATE TABLE IF NOT EXISTS fonts (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        name         TEXT NOT NULL UNIQUE,
                        font_path    TEXT NOT NULL,
                        sample_path  TEXT NOT NULL,
                        created_at   TEXT NOT NULL
                    )
                """
        )

        await db.execute("""
                    CREATE TABLE IF NOT EXISTS colors (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        name         TEXT NOT NULL UNIQUE,
                        hex_code     TEXT NOT NULL,
                        sample_path  TEXT NOT NULL,
                        created_at   TEXT NOT NULL
                    )
                """
        )

        await db.execute("""
                    CREATE TABLE IF NOT EXISTS future_letters (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id     INTEGER NOT NULL,
                        content     TEXT NOT NULL,
                        created_at  TEXT NOT NULL,
                        send_after  TEXT NOT NULL,
                        is_sent     INTEGER NOT NULL,
                        is_free     INTEGER NOT NULL  DEFAULT 0
                    )
                """
        )

        await db.commit()


async def upsert_subscription(user_id: int, expires_at: str):
    """
    Добавляет или обновляет подписку пользователя.
    expires_at — ISO-строка времени окончания.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO subscriptions(user_id, expires_at)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              expires_at = excluded.expires_at
        """, (user_id, expires_at))
        await db.commit()


async def fetch_subscription(user_id: int):
    """
    Возвращает словарь {'user_id': ..., 'expires_at': datetime} или None.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT user_id, expires_at FROM subscriptions WHERE user_id = ?",
            (user_id,)
        )
        row = await cur.fetchone()
        await cur.close()

    if not row:
        return None

    uid, expires_str = row
    try:
        expires = datetime.fromisoformat(expires_str)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except ValueError:
        expires = datetime.now(timezone.utc)

    return {"user_id": uid, "expires_at": expires}


async def delete_subscription(user_id: int):
    """
    Удаляет запись о подписке.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM subscriptions WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()


async def fetch_daily_quote(user_id: int, quote_date: str) -> tuple[str, str | None] | None:
    """
    Возвращает кортеж (quote, source) или None, если нет записи.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cur = await db.execute(
            "SELECT quote, source FROM daily_quotes WHERE user_id = ? AND quote_date = ?",
            (user_id, quote_date)
        )
        row = await cur.fetchone()
        await cur.close()

    if not row:
        return None
    return row[0], row[1]


async def upsert_daily_quote(user_id: int, quote_date: str, quote: str, source: str | None):
    """
    Сохраняет сгенерированную цитату и автора для user_id и quote_date.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO daily_quotes(user_id, quote_date, quote, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, quote_date) DO UPDATE SET
              quote  = excluded.quote,
              source = excluded.source
        """, (user_id, quote_date, quote, source))
        await db.commit()


async def add_font(name: str, font_path: str, sample_path: str):
    """
    Добавляет новый шрифт в таблицу fonts.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO fonts(name, font_path, sample_path, created_at) VALUES (?, ?, ?, ?)",
            (name, font_path, sample_path, now)
        )
        await db.commit()


async def list_fonts():
    """
    Возвращает список всех шрифтов:
    [{"id":..., "name":..., "font_path":..., "sample_path":...}, ...]
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name, font_path, sample_path FROM fonts ORDER BY id"
        )
        rows = await cur.fetchall()
        await cur.close()
    return [
        {"id": r[0], "name": r[1], "font_path": r[2], "sample_path": r[3]}
        for r in rows
    ]


async def delete_font(font_id: int):
    """
    Удаляет шрифт из таблицы и возвращает (font_path, sample_path) или None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT font_path, sample_path FROM fonts WHERE id = ?",
            (font_id,)
        )
        row = await cur.fetchone()
        if not row:
            await cur.close()
            return None
        await db.execute(
            "DELETE FROM fonts WHERE id = ?",
            (font_id,)
        )
        await db.commit()
    return row


async def add_color(name: str, hex_code: str, sample_path: str):
    """
    Добавляет новый цвет в таблицу colors.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO colors(name, hex_code, sample_path, created_at) VALUES (?, ?, ?, ?)",
            (name, hex_code, sample_path, now)
        )
        await db.commit()


async def list_colors():
    """
    Возвращает список всех цветов:
    [{"id":..., "name":..., "hex":..., "sample_path":...}, ...]
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name, hex_code, sample_path FROM colors ORDER BY id"
        )
        rows = await cur.fetchall()
        await cur.close()
    return [
        {"id": r[0], "name": r[1], "hex": r[2], "sample_path": r[3]}
        for r in rows
    ]


async def delete_color(color_id: int):
    """
    Удаляет цвет из таблицы и возвращает sample_path или None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT sample_path FROM colors WHERE id = ?",
            (color_id,)
        )
        row = await cur.fetchone()
        if not row:
            await cur.close()
            return None
        await db.execute(
            "DELETE FROM colors WHERE id = ?",
            (color_id,)
        )
        await db.commit()
    return row[0]


async def upsert_future_letter(user_id: int, content: str, send_after: datetime, *, is_free: bool = False):
    now = datetime.now(timezone.utc).isoformat()
    sa = send_after.isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO future_letters
              (user_id, content, created_at, send_after, is_sent, is_free)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (user_id, content, now, sa, int(is_free)))
        await db.commit()


async def fetch_due_letters() -> list[dict]:
    """Берём письма, которым настало время отправки (send_after <= now)."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id,
                   user_id,
                   content,
                   created_at,
                   send_after
            FROM future_letters
            WHERE is_sent = 0
                AND send_after <= ?
            """,
            (now,)
        )
        rows = await cur.fetchall()
        await cur.close()
    return [{"id": r[0], "user_id": r[1], "content": r[2], "created_at": r[3], "send_at": r[4],} for r in rows]


async def fetch_all_unsent_letters() -> list[dict]:
    """Берём все неотправленные письма (независимо от времени отправки)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id,
                   user_id,
                   content,
                   created_at,
                   send_after
            FROM future_letters
            WHERE is_sent = 0
            """
        )
        rows = await cur.fetchall()
        await cur.close()
        return [{"id": r[0], "user_id": r[1], "content": r[2], "created_at": r[3], "send_at": r[4],} for r in rows]


async def mark_letter_sent(letter_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE future_letters SET is_sent=1 WHERE id=?",
            (letter_id,)
        )
        await db.commit()


async def count_free_letters_in_month(user_id: int, reference_date: datetime = None) -> int:
    """
    Считает, сколько бесплатных писем (is_free = TRUE) пользователь уже запланировал
    на текущий календарный месяц.
    """
    now = reference_date or datetime.now(timezone.utc).isoformat()
    first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_next = first_day + relativedelta(months=1)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM future_letters
            WHERE user_id = ?
              AND is_free = 1
              AND send_after >= ?
              AND send_after < ?
            """,
            (user_id, first_day.isoformat(), first_next.isoformat())
        )
        row = await cur.fetchone()
        await cur.close()

    return row[0] or 0
