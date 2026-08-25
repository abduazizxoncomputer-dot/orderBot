import datetime

import aiosqlite

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    message_id  INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    text              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    group_message_id  INTEGER,
    created_at        TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)

        # Eski (group_message_id ustunisiz) bazalarni migratsiya qilish
        cursor = await db.execute("PRAGMA table_info(orders)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "group_message_id" not in columns:
            await db.execute("ALTER TABLE orders ADD COLUMN group_message_id INTEGER")

        await db.commit()


# ---------- posts ----------

async def add_post(message_id: int, chat_id: int, text: str, created_at: str | None = None) -> None:
    """created_at berilmasa - hozirgi vaqt qo'yiladi (masalan yangi kanal posti uchun).
    Backfill/refresh paytida postning kanaldagi haqiqiy joylangan vaqtini berish mumkin."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO posts (message_id, chat_id, text, created_at) VALUES (?, ?, ?, ?)",
            (message_id, chat_id, text, created_at or _now()),
        )
        await db.commit()


async def delete_post(message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE message_id = ?", (message_id,))
        await db.commit()


def _like_pattern(raw: str) -> str:
    """LIKE ichida %, _ va \\ belgilarini literal deb ko'rsatish uchun escape qiladi."""
    escaped = raw.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def get_post_by_text(text: str) -> dict | None:
    """Postlar sarlavha+tavsif ko'rinishida saqlanadi, shuning uchun qisman
    (substring) moslik bo'yicha qidiriladi - masalan "Avatar" so'zi
    "Avatar: The Last Airbender ..." captionli postni topadi."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM posts WHERE text LIKE ? ESCAPE '\\' COLLATE NOCASE ORDER BY message_id DESC LIMIT 1",
            (_like_pattern(text),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_post_ids() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT message_id, chat_id FROM posts")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_posts_since(since_iso: str | None) -> list[dict]:
    """since_iso berilmasa (None) - barcha postlarni qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if since_iso is None:
            cursor = await db.execute("SELECT message_id, chat_id, created_at FROM posts")
        else:
            cursor = await db.execute(
                "SELECT message_id, chat_id, created_at FROM posts WHERE created_at >= ?",
                (since_iso,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ---------- users ----------

async def add_user(user_id: int, username: str | None, full_name: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name
            """,
            (user_id, username, full_name, _now()),
        )
        await db.commit()


async def user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row is not None


async def get_all_users() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


# ---------- orders ----------

async def add_order(user_id: int, text: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, text, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, text, _now()),
        )
        await db.commit()
        return cursor.lastrowid


async def set_order_group_message_id(order_id: int, group_message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET group_message_id = ? WHERE id = ?",
            (group_message_id, order_id),
        )
        await db.commit()


async def get_pending_orders_by_text(post_text: str) -> list[dict]:
    """post_text - kanalga tushgan yangi postning to'liq matni (caption).
    Shu matn ICHIDA order.text (user so'ragan qisqa nom) uchraydigan barcha
    kutilayotgan orderlarni qaytaradi (masalan order "Avatar", post caption
    "Avatar: The Last Airbender ⭐ IMDB ...")."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM orders WHERE status = 'pending' AND ? LIKE '%' || text || '%' COLLATE NOCASE",
            (post_text.strip(),),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def mark_order_fulfilled(order_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = 'fulfilled' WHERE id = ?", (order_id,))
        await db.commit()


# ---------- /db buyrug'i uchun statistika ----------

async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        posts_count = (await (await db.execute("SELECT COUNT(*) FROM posts")).fetchone())[0]
        users_count = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        orders_count = (await (await db.execute("SELECT COUNT(*) FROM orders")).fetchone())[0]
        pending_count = (
            await (await db.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")).fetchone()
        )[0]
        return {
            "posts": posts_count,
            "users": users_count,
            "orders": orders_count,
            "orders_pending": pending_count,
            "orders_fulfilled": orders_count - pending_count,
        }


async def get_recent_posts(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT message_id, chat_id, text, created_at FROM posts ORDER BY message_id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_orders(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, user_id, text, status, created_at FROM orders ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_users(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, full_name, created_at FROM users ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
