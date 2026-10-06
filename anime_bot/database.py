"""
Test2 Bot — SQLite ma'lumotlar bazasi qatlami.

Barcha DB operatsiyalari shu faylda to'plangan, handlerlar bevosita SQL
yozmaydi — shu orqali bazaga oid mantiqni bir joyda ushlab turamiz va
kelajakda (masalan PostgreSQL'ga) ko'chirishni osonlashtiramiz.
"""
from __future__ import annotations

import datetime
import logging
import os
import shutil
from typing import Any, Optional

import aiosqlite

import config

logger = logging.getLogger("anime_bot.db")


async def validate_sqlite_backup(path: str) -> tuple[bool, str]:
    """
    Berilgan fayl haqiqiy va bizning botimizga mos SQLite zaxira ekanligini tekshiradi.
    (ok, xabar) qaytaradi — ok=False bo'lsa, xabar foydalanuvchiga ko'rsatiladigan sabab.
    """
    try:
        conn = await aiosqlite.connect(path)
        try:
            cur = await conn.execute("PRAGMA integrity_check")
            row = await cur.fetchone()
            if not row or row[0] != "ok":
                return False, "fayl buzilgan yoki noto'g'ri SQLite bazasi (integrity_check xato)"
            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            rows = await cur.fetchall()
            table_names = {r[0] for r in rows}
            required = {"users", "anime", "episodes", "genres", "settings"}
            missing = required - table_names
            if missing:
                return False, f"kerakli jadvallar topilmadi: {', '.join(sorted(missing))}"
        finally:
            await conn.close()
        return True, ""
    except Exception as e:
        return False, f"fayl SQLite bazasi sifatida ochilmadi ({e})"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   INTEGER UNIQUE NOT NULL,
    full_name     TEXT,
    username      TEXT,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    vip_until     TEXT,              -- ISO datetime yoki NULL
    balance       INTEGER NOT NULL DEFAULT 0,
    joined_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS genres (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    emoji    TEXT NOT NULL,
    name     TEXT NOT NULL UNIQUE,
    is_vip   INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anime (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_code   TEXT UNIQUE NOT NULL,     -- foydalanuvchiga ko'rinadigan ID
    title        TEXT NOT NULL,
    description  TEXT,
    poster_file_id TEXT,
    is_vip       INTEGER NOT NULL DEFAULT 0,
    is_published INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anime_genres (
    anime_id  INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    genre_id  INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (anime_id, genre_id)
);

CREATE TABLE IF NOT EXISTS seasons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id      INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    season_number INTEGER NOT NULL,
    title         TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (anime_id, season_number)
);

-- season_id = NULL bo'lsa — "oddiy" (fasllarsiz) anime qismi.
-- Bir anime ichida fasllar bo'lsa, har bir fasl o'z ichida 1 dan boshlab raqamlanadi.
CREATE TABLE IF NOT EXISTS episodes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id       INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    season_id      INTEGER REFERENCES seasons(id) ON DELETE CASCADE,
    episode_number INTEGER NOT NULL,
    video_file_id  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (anime_id, season_id, episode_number)
);

CREATE TABLE IF NOT EXISTS watch_progress (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anime_id    INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    episode_id  INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    updated_at  TEXT NOT NULL,
    UNIQUE (user_id, anime_id)
);

CREATE TABLE IF NOT EXISTS follows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anime_id    INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    followed_at TEXT NOT NULL,
    UNIQUE (user_id, anime_id)
);

CREATE TABLE IF NOT EXISTS notified_episodes (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    episode_id  INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    notified_at TEXT NOT NULL,
    PRIMARY KEY (user_id, episode_id)
);

CREATE TABLE IF NOT EXISTS ratings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id  INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score     INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10),
    rated_at  TEXT NOT NULL,
    UNIQUE (anime_id, user_id)
);

CREATE TABLE IF NOT EXISTS favorites (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anime_id  INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    added_at  TEXT NOT NULL,
    UNIQUE (user_id, anime_id)
);

CREATE TABLE IF NOT EXISTS watch_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anime_id    INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE,
    episode_id  INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
    watched_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vip_purchases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    months         INTEGER NOT NULL,
    price          INTEGER NOT NULL,
    source         TEXT NOT NULL,     -- 'payment' | 'admin_grant'
    approved_by    INTEGER,           -- admin telegram_id
    purchased_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_payments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    months            INTEGER NOT NULL,
    price             INTEGER NOT NULL,
    screenshot_file_id TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    created_at        TEXT NOT NULL,
    resolved_at       TEXT,
    resolved_by       INTEGER
);

CREATE TABLE IF NOT EXISTS required_channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL UNIQUE,   -- @username yoki -100...
    title       TEXT,
    invite_link TEXT                   -- -100... ID orqali qo'shilgan kanallar uchun avtomatik yaratilgan taklif linki
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type   TEXT NOT NULL,      -- 'text' | 'copy' (forward/copy of a message)
    payload        TEXT NOT NULL,      -- JSON: matn yoki source chat/message id
    status         TEXT NOT NULL DEFAULT 'running',  -- running|paused|done|cancelled
    total_count    INTEGER NOT NULL DEFAULT 0,
    sent_count     INTEGER NOT NULL DEFAULT 0,
    failed_count   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    created_by     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_anime ON episodes(anime_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id);
CREATE INDEX IF NOT EXISTS idx_seasons_anime ON seasons(anime_id);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_history_user ON watch_history(user_id);
CREATE INDEX IF NOT EXISTS idx_anime_genres_anime ON anime_genres(anime_id);
CREATE INDEX IF NOT EXISTS idx_anime_genres_genre ON anime_genres(genre_id);
CREATE INDEX IF NOT EXISTS idx_watch_progress_user ON watch_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_follows_user ON follows(user_id);
CREATE INDEX IF NOT EXISTS idx_follows_anime ON follows(anime_id);
"""


def _now() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds")


class Database:
    """Butun bot davomida ishlatiladigan yagona ulanish (WAL rejimida)."""

    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------ #
    # Ulanish / sozlash
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA foreign_keys=ON;")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        await self._migrate()
        await self._seed_defaults()
        logger.info("Baza ulandi: %s", self.path)

    async def _migrate(self) -> None:
        """Eski (allaqachon deploy qilingan) bazalarga yangi ustunlarni xavfsiz qo'shadi."""
        cur = await self.conn.execute("PRAGMA table_info(required_channels)")
        cols = {row[1] for row in await cur.fetchall()}
        if "invite_link" not in cols:
            await self.conn.execute("ALTER TABLE required_channels ADD COLUMN invite_link TEXT")
            await self.conn.commit()

        # Fasllar (seasons) tizimi: eski "episodes" jadvalida season_id ustuni
        # bo'lmasa — jadvalni xavfsiz qayta quramiz (barcha eski qismlar
        # season_id=NULL, ya'ni "oddiy anime" sifatida saqlanib qoladi,
        # HECH QANDAY ma'lumot o'chmaydi/yo'qolmaydi).
        cur = await self.conn.execute("PRAGMA table_info(episodes)")
        cols = {row[1] for row in await cur.fetchall()}
        if "season_id" not in cols:
            await self.conn.execute(
                "CREATE TABLE IF NOT EXISTS seasons ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE, "
                "season_number INTEGER NOT NULL, "
                "title TEXT, "
                "created_at TEXT NOT NULL, "
                "UNIQUE (anime_id, season_number))"
            )
            await self.conn.execute(
                "CREATE TABLE episodes_new ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE, "
                "season_id INTEGER REFERENCES seasons(id) ON DELETE CASCADE, "
                "episode_number INTEGER NOT NULL, "
                "video_file_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL, "
                "UNIQUE (anime_id, season_id, episode_number))"
            )
            await self.conn.execute(
                "INSERT INTO episodes_new (id, anime_id, season_id, episode_number, video_file_id, created_at) "
                "SELECT id, anime_id, NULL, episode_number, video_file_id, created_at FROM episodes"
            )
            await self.conn.execute("DROP TABLE episodes")
            await self.conn.execute("ALTER TABLE episodes_new RENAME TO episodes")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_anime ON episodes(anime_id)")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id)")
            await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_seasons_anime ON seasons(anime_id)")
            await self.conn.commit()
            logger.info("Migratsiya: episodes jadvaliga season_id qo'shildi, eski qismlar saqlanib qoldi.")

        # Yangi funksiyalar uchun jadvallar (agar hali yo'q bo'lsa) — CREATE TABLE
        # IF NOT EXISTS xavfsiz, eski ma'lumotlarga tegmaydi.
        await self.conn.executescript(
            "CREATE TABLE IF NOT EXISTS watch_progress ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE, "
            "episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE, "
            "updated_at TEXT NOT NULL, "
            "UNIQUE (user_id, anime_id));"
            "CREATE TABLE IF NOT EXISTS follows ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "anime_id INTEGER NOT NULL REFERENCES anime(id) ON DELETE CASCADE, "
            "followed_at TEXT NOT NULL, "
            "UNIQUE (user_id, anime_id));"
            "CREATE TABLE IF NOT EXISTS notified_episodes ("
            "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE, "
            "notified_at TEXT NOT NULL, "
            "PRIMARY KEY (user_id, episode_id));"
            "CREATE INDEX IF NOT EXISTS idx_watch_progress_user ON watch_progress(user_id);"
            "CREATE INDEX IF NOT EXISTS idx_follows_user ON follows(user_id);"
            "CREATE INDEX IF NOT EXISTS idx_follows_anime ON follows(anime_id);"
        )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _seed_defaults(self) -> None:
        # Sozlamalar
        for key, value in config.DEFAULT_SETTINGS.items():
            await self.conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        # Janrlar (faqat jadval bo'sh bo'lsa)
        cur = await self.conn.execute("SELECT COUNT(*) FROM genres")
        (count,) = await cur.fetchone()
        if count == 0:
            order = 0
            for emoji, name in config.NORMAL_GENRES:
                await self.conn.execute(
                    "INSERT INTO genres (emoji, name, is_vip, sort_order) VALUES (?,?,0,?)",
                    (emoji, name, order),
                )
                order += 1
            for emoji, name in config.VIP_GENRES:
                await self.conn.execute(
                    "INSERT INTO genres (emoji, name, is_vip, sort_order) VALUES (?,?,1,?)",
                    (emoji, name, order),
                )
                order += 1
        # Super adminlar
        for tg_id in config.SUPER_ADMIN_IDS:
            existing = await self.get_user(tg_id)
            if existing is None:
                await self.create_user(tg_id, full_name="Admin", username=None)
            await self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE telegram_id = ?", (tg_id,)
            )
        await self.conn.commit()

    async def backup(self) -> str:
        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(config.BACKUP_DIR, f"anime_{stamp}.db")
        await self.conn.commit()
        shutil.copyfile(self.path, dest)
        logger.info("Backup yaratildi: %s", dest)
        return dest

    async def replace_with(self, new_db_path: str) -> None:
        """
        Joriy bazani berilgan fayl bilan TO'LIQ almashtiradi (zaxiradan tiklash uchun):
        ulanishni to'g'ri yopadi (WAL checkpoint bo'lishi uchun), eski -wal/-shm
        qoldiqlarini tozalaydi, faylni ko'chiradi va qayta ulanadi.
        """
        if self.conn:
            await self.conn.commit()
            await self.conn.close()
        for suffix in ("-wal", "-shm"):
            stale = self.path + suffix
            if os.path.exists(stale):
                try:
                    os.remove(stale)
                except OSError:
                    pass
        shutil.copyfile(new_db_path, self.path)
        await self.connect()

    # ------------------------------------------------------------------ #
    # Settings (key-value)
    # ------------------------------------------------------------------ #
    async def get_setting(self, key: str, default: str = "") -> str:
        cur = await self.conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row and row["value"] is not None else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------ #
    # Users
    # ------------------------------------------------------------------ #
    async def create_user(
        self, telegram_id: int, full_name: str, username: Optional[str]
    ) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, full_name, username, joined_at) "
            "VALUES (?,?,?,?)",
            (telegram_id, full_name, username, _now()),
        )
        await self.conn.commit()
        return await self.get_user(telegram_id)

    async def get_user(self, telegram_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)
        )
        return await cur.fetchone()

    async def get_user_by_pk(self, user_pk: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM users WHERE id=?", (user_pk,))
        return await cur.fetchone()

    async def touch_user(self, telegram_id: int, full_name: str, username: Optional[str]) -> None:
        """Har safar /start bosilganda ism/username yangilanadi."""
        await self.conn.execute(
            "UPDATE users SET full_name=?, username=? WHERE telegram_id=?",
            (full_name, username, telegram_id),
        )
        await self.conn.commit()

    async def is_admin(self, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        return bool(user and user["is_admin"])

    async def set_admin(self, telegram_id: int, value: bool) -> None:
        await self.conn.execute(
            "UPDATE users SET is_admin=? WHERE telegram_id=?", (1 if value else 0, telegram_id)
        )
        await self.conn.commit()

    async def is_vip(self, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        if not user or not user["vip_until"]:
            return False
        return datetime.datetime.fromisoformat(user["vip_until"]) > datetime.datetime.utcnow()

    async def grant_vip(self, telegram_id: int, months: int, price: int, source: str,
                         approved_by: Optional[int] = None) -> datetime.datetime:
        """VIP muddatini uzaytiradi (eski faol muddat bo'lsa unga qo'shiladi)."""
        user = await self.get_user(telegram_id)
        days = config.VIP_DAYS.get(months, 30 * months)
        now = datetime.datetime.utcnow()
        current_until = None
        if user and user["vip_until"]:
            current_until = datetime.datetime.fromisoformat(user["vip_until"])
        base = current_until if (current_until and current_until > now) else now
        new_until = base + datetime.timedelta(days=days)
        await self.conn.execute(
            "UPDATE users SET vip_until=? WHERE telegram_id=?",
            (new_until.isoformat(timespec="seconds"), telegram_id),
        )
        await self.conn.execute(
            "INSERT INTO vip_purchases (user_id, months, price, source, approved_by, purchased_at) "
            "SELECT id, ?, ?, ?, ?, ? FROM users WHERE telegram_id=?",
            (months, price, source, approved_by, _now(), telegram_id),
        )
        await self.conn.commit()
        return new_until

    async def expire_vips(self) -> list[int]:
        """Muddati tugagan foydalanuvchilarni tozalaydi, telegram_id ro'yxatini qaytaradi."""
        now = datetime.datetime.utcnow().isoformat(timespec="seconds")
        cur = await self.conn.execute(
            "SELECT telegram_id FROM users WHERE vip_until IS NOT NULL AND vip_until <= ?",
            (now,),
        )
        rows = await cur.fetchall()
        ids = [r["telegram_id"] for r in rows]
        if ids:
            await self.conn.execute(
                "UPDATE users SET vip_until=NULL WHERE vip_until IS NOT NULL AND vip_until <= ?",
                (now,),
            )
            await self.conn.commit()
        return ids

    async def revoke_vip(self, telegram_id: int) -> None:
        """Foydalanuvchining VIP holatini adminlik qaroriga ko'ra darhol bekor qiladi."""
        await self.conn.execute(
            "UPDATE users SET vip_until=NULL WHERE telegram_id=?", (telegram_id,)
        )
        await self.conn.commit()

    # ------------------------------------------------------------------ #
    # VIP'ni vaqtincha hammaga bepul qilish (promo rejim)
    # ------------------------------------------------------------------ #
    async def get_vip_free_until(self) -> Optional[datetime.datetime]:
        raw = await self.get_setting("vip_free_until", "")
        if not raw:
            return None
        try:
            return datetime.datetime.fromisoformat(raw)
        except ValueError:
            return None

    async def set_vip_free_until(self, dt: Optional[datetime.datetime]) -> None:
        await self.set_setting("vip_free_until", dt.isoformat(timespec="seconds") if dt else "")

    async def is_vip_free_mode(self) -> bool:
        until = await self.get_vip_free_until()
        return bool(until and until > datetime.datetime.utcnow())

    async def count_users(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) FROM users")
        (n,) = await cur.fetchone()
        return n

    async def count_vip_users(self) -> int:
        now = datetime.datetime.utcnow().isoformat(timespec="seconds")
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE vip_until IS NOT NULL AND vip_until > ?", (now,)
        )
        (n,) = await cur.fetchone()
        return n

    async def list_users(self, page: int, per_page: int = config.USERS_PER_PAGE) -> list[aiosqlite.Row]:
        offset = page * per_page
        cur = await self.conn.execute(
            "SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset)
        )
        return await cur.fetchall()

    async def all_telegram_ids(self) -> list[int]:
        cur = await self.conn.execute("SELECT telegram_id FROM users")
        rows = await cur.fetchall()
        return [r["telegram_id"] for r in rows]

    # ------------------------------------------------------------------ #
    # Genres
    # ------------------------------------------------------------------ #
    async def list_genres(self, vip_only: Optional[bool] = None) -> list[aiosqlite.Row]:
        if vip_only is None:
            cur = await self.conn.execute("SELECT * FROM genres ORDER BY is_vip DESC, sort_order")
        else:
            cur = await self.conn.execute(
                "SELECT * FROM genres WHERE is_vip=? ORDER BY sort_order", (1 if vip_only else 0,)
            )
        return await cur.fetchall()

    async def get_genre(self, genre_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM genres WHERE id=?", (genre_id,))
        return await cur.fetchone()

    # ------------------------------------------------------------------ #
    # Anime
    # ------------------------------------------------------------------ #
    async def _next_anime_code(self) -> str:
        cur = await self.conn.execute("SELECT COUNT(*) FROM anime")
        (n,) = await cur.fetchone()
        return str(n + 1)

    async def create_anime(self, title: str, description: str, poster_file_id: Optional[str],
                            genre_ids: list[int]) -> aiosqlite.Row:
        code = await self._next_anime_code()
        is_vip = 0
        if genre_ids:
            cur = await self.conn.execute(
                f"SELECT COUNT(*) FROM genres WHERE id IN ({','.join('?' * len(genre_ids))}) AND is_vip=1",
                genre_ids,
            )
            (vip_count,) = await cur.fetchone()
            is_vip = 1 if vip_count > 0 else 0
        cur = await self.conn.execute(
            "INSERT INTO anime (anime_code, title, description, poster_file_id, is_vip, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (code, title, description, poster_file_id, is_vip, _now()),
        )
        anime_pk = cur.lastrowid
        for gid in genre_ids:
            await self.conn.execute(
                "INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?,?)",
                (anime_pk, gid),
            )
        await self.conn.commit()
        return await self.get_anime(anime_pk)

    async def update_anime_genres(self, anime_id: int, genre_ids: list[int]) -> None:
        await self.conn.execute("DELETE FROM anime_genres WHERE anime_id=?", (anime_id,))
        for gid in genre_ids:
            await self.conn.execute(
                "INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?,?)",
                (anime_id, gid),
            )
        is_vip = 0
        if genre_ids:
            cur = await self.conn.execute(
                f"SELECT COUNT(*) FROM genres WHERE id IN ({','.join('?' * len(genre_ids))}) AND is_vip=1",
                genre_ids,
            )
            (vip_count,) = await cur.fetchone()
            is_vip = 1 if vip_count > 0 else 0
        await self.conn.execute("UPDATE anime SET is_vip=? WHERE id=?", (is_vip, anime_id))
        await self.conn.commit()

    async def get_anime(self, anime_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM anime WHERE id=?", (anime_id,))
        return await cur.fetchone()

    async def get_anime_by_code(self, code: str) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM anime WHERE anime_code=?", (code,))
        return await cur.fetchone()

    async def get_anime_genres(self, anime_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT g.* FROM genres g JOIN anime_genres ag ON ag.genre_id=g.id "
            "WHERE ag.anime_id=? ORDER BY g.is_vip DESC, g.sort_order",
            (anime_id,),
        )
        return await cur.fetchall()

    async def search_anime_by_title(self, query: str, limit: int = 15) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM anime WHERE title LIKE ? AND is_published=1 ORDER BY title LIMIT ?",
            (f"%{query}%", limit),
        )
        return await cur.fetchall()

    async def list_anime_by_genre(self, genre_id: int, page: int, per_page: int = 10) -> list[aiosqlite.Row]:
        offset = page * per_page
        cur = await self.conn.execute(
            "SELECT a.* FROM anime a JOIN anime_genres ag ON ag.anime_id=a.id "
            "WHERE ag.genre_id=? AND a.is_published=1 ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
            (genre_id, per_page, offset),
        )
        return await cur.fetchall()

    async def count_published_anime(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) FROM anime WHERE is_published=1")
        (n,) = await cur.fetchone()
        return n

    async def count_anime_by_genre(self, genre_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM anime a JOIN anime_genres ag ON ag.anime_id=a.id "
            "WHERE ag.genre_id=? AND a.is_published=1",
            (genre_id,),
        )
        (n,) = await cur.fetchone()
        return n

    async def list_new_anime(self, page: int = 0, per_page: int = 10) -> list[aiosqlite.Row]:
        offset = page * per_page
        cur = await self.conn.execute(
            "SELECT * FROM anime WHERE is_published=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        )
        return await cur.fetchall()

    async def list_popular_anime(self, page: int = 0, per_page: int = 10) -> list[aiosqlite.Row]:
        """Sevimlilar soni bo'yicha mashhurlik."""
        offset = page * per_page
        cur = await self.conn.execute(
            "SELECT a.*, COUNT(f.id) as fav_count FROM anime a "
            "LEFT JOIN favorites f ON f.anime_id=a.id "
            "WHERE a.is_published=1 GROUP BY a.id ORDER BY fav_count DESC, a.created_at DESC "
            "LIMIT ? OFFSET ?",
            (per_page, offset),
        )
        return await cur.fetchall()

    async def list_top_rated(self, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT a.*, AVG(r.score) as avg_score, COUNT(r.id) as rate_count FROM anime a "
            "JOIN ratings r ON r.anime_id=a.id WHERE a.is_published=1 "
            "GROUP BY a.id HAVING rate_count > 0 ORDER BY avg_score DESC, rate_count DESC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()

    async def anime_avg_rating(self, anime_id: int) -> tuple[float, int]:
        cur = await self.conn.execute(
            "SELECT AVG(score), COUNT(*) FROM ratings WHERE anime_id=?", (anime_id,)
        )
        avg, count = await cur.fetchone()
        return (round(avg, 1) if avg else 0.0, count or 0)

    async def all_anime_for_random(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM anime WHERE is_published=1")
        return await cur.fetchall()

    # ------------------------------------------------------------------ #
    # Seasons (fasllar)
    # ------------------------------------------------------------------ #
    async def list_seasons(self, anime_id: int) -> list[aiosqlite.Row]:
        """Anime fasllarini (bo'lsa) episode_count bilan qaytaradi. Bo'sh ro'yxat = anime fasllarga bo'linmagan."""
        cur = await self.conn.execute(
            "SELECT s.*, COUNT(e.id) as episode_count FROM seasons s "
            "LEFT JOIN episodes e ON e.season_id=s.id "
            "WHERE s.anime_id=? GROUP BY s.id ORDER BY s.season_number",
            (anime_id,),
        )
        return await cur.fetchall()

    async def get_season(self, season_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM seasons WHERE id=?", (season_id,))
        return await cur.fetchone()

    async def next_season_number(self, anime_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COALESCE(MAX(season_number),0)+1 FROM seasons WHERE anime_id=?", (anime_id,)
        )
        (n,) = await cur.fetchone()
        return n

    async def create_season(self, anime_id: int, season_number: int, title: Optional[str] = None) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT OR IGNORE INTO seasons (anime_id, season_number, title, created_at) VALUES (?,?,?,?)",
            (anime_id, season_number, title, _now()),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT * FROM seasons WHERE anime_id=? AND season_number=?", (anime_id, season_number)
        )
        return await cur.fetchone()

    async def ensure_season_migration(self, anime_id: int) -> None:
        """
        Agar anime hali umuman fasllarga bo'linmagan bo'lsa-yu, endi birinchi marta
        fasl qo'shilayotgan bo'lsa — mavjud (season_id=NULL) qismlarni avtomatik
        ravishda "1-fasl" sifatida ko'chiradi. Eski ma'lumot yo'qolmaydi, faqat
        endi rasman "1-fasl" ostida ko'rinadi.
        """
        seasons = await self.list_seasons(anime_id)
        if seasons:
            return
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=? AND season_id IS NULL", (anime_id,)
        )
        (orphan_count,) = await cur.fetchone()
        if orphan_count == 0:
            return
        season1 = await self.create_season(anime_id, 1)
        await self.conn.execute(
            "UPDATE episodes SET season_id=? WHERE anime_id=? AND season_id IS NULL",
            (season1["id"], anime_id),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------ #
    # Episodes
    # ------------------------------------------------------------------ #
    async def add_episode(self, anime_id: int, video_file_id: str, season_id: Optional[int] = None) -> aiosqlite.Row:
        cur = await self.conn.execute(
            "SELECT COALESCE(MAX(episode_number),0)+1 FROM episodes WHERE anime_id=? AND season_id IS ?",
            (anime_id, season_id),
        )
        (next_num,) = await cur.fetchone()
        await self.conn.execute(
            "INSERT INTO episodes (anime_id, season_id, episode_number, video_file_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (anime_id, season_id, next_num, video_file_id, _now()),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT * FROM episodes WHERE anime_id=? AND season_id IS ? AND episode_number=?",
            (anime_id, season_id, next_num),
        )
        return await cur.fetchone()

    async def count_episodes(self, anime_id: int) -> int:
        """Anime bo'yicha JAMI qismlar soni (barcha fasllar bilan birga)."""
        cur = await self.conn.execute("SELECT COUNT(*) FROM episodes WHERE anime_id=?", (anime_id,))
        (n,) = await cur.fetchone()
        return n

    async def count_episodes_in_season(self, anime_id: int, season_id: Optional[int]) -> int:
        """Bitta fasl (yoki fasllarsiz anime, season_id=None) ichidagi qismlar soni."""
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=? AND season_id IS ?", (anime_id, season_id)
        )
        (n,) = await cur.fetchone()
        return n

    async def list_episodes_page(self, anime_id: int, page: int, season_id: Optional[int] = None) -> list[aiosqlite.Row]:
        per_page = config.EPISODES_PER_PAGE
        offset = page * per_page
        cur = await self.conn.execute(
            "SELECT * FROM episodes WHERE anime_id=? AND season_id IS ? ORDER BY episode_number LIMIT ? OFFSET ?",
            (anime_id, season_id, per_page, offset),
        )
        return await cur.fetchall()

    async def get_episode(self, episode_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,))
        return await cur.fetchone()

    async def get_episode_by_number(self, anime_id: int, number: int, season_id: Optional[int] = None) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM episodes WHERE anime_id=? AND season_id IS ? AND episode_number=?",
            (anime_id, season_id, number),
        )
        return await cur.fetchone()

    async def get_next_episode(self, anime_id: int, current_episode_id: int) -> Optional[aiosqlite.Row]:
        """Berilgan qismdan keyingisini topadi: avval xuddi shu fasl ichida, bo'lmasa keyingi fasldan 1-qism."""
        cur_ep = await self.get_episode(current_episode_id)
        if not cur_ep:
            return None
        cur = await self.conn.execute(
            "SELECT * FROM episodes WHERE anime_id=? AND season_id IS ? AND episode_number=?",
            (anime_id, cur_ep["season_id"], cur_ep["episode_number"] + 1),
        )
        nxt = await cur.fetchone()
        if nxt:
            return nxt
        if cur_ep["season_id"] is not None:
            season = await self.get_season(cur_ep["season_id"])
            if season:
                cur = await self.conn.execute(
                    "SELECT id FROM seasons WHERE anime_id=? AND season_number=?",
                    (anime_id, season["season_number"] + 1),
                )
                next_season = await cur.fetchone()
                if next_season:
                    cur = await self.conn.execute(
                        "SELECT * FROM episodes WHERE anime_id=? AND season_id=? AND episode_number=1",
                        (anime_id, next_season["id"]),
                    )
                    return await cur.fetchone()
        return None

    async def list_recent_episodes(self, limit: int = 30) -> list[aiosqlite.Row]:
        """So'nggi qo'shilgan qismlar ("🔥 Yangi qismlar" bo'limi uchun), anime va fasl ma'lumotlari bilan."""
        cur = await self.conn.execute(
            "SELECT e.*, a.title as anime_title, a.anime_code, a.is_vip as anime_is_vip, "
            "s.season_number FROM episodes e "
            "JOIN anime a ON a.id=e.anime_id "
            "LEFT JOIN seasons s ON s.id=e.season_id "
            "WHERE a.is_published=1 "
            "ORDER BY e.created_at DESC, e.id DESC LIMIT ?",
            (limit,),
        )
        return await cur.fetchall()

    # ------------------------------------------------------------------ #
    # Ko'rish jarayoni (continue watching)
    # ------------------------------------------------------------------ #
    async def set_watch_progress(self, telegram_id: int, anime_id: int, episode_id: int) -> None:
        user = await self.get_user(telegram_id)
        await self.conn.execute(
            "INSERT INTO watch_progress (user_id, anime_id, episode_id, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id, anime_id) DO UPDATE SET episode_id=excluded.episode_id, updated_at=excluded.updated_at",
            (user["id"], anime_id, episode_id, _now()),
        )
        await self.conn.commit()

    async def get_watch_progress_for_anime(self, telegram_id: int, anime_id: int) -> Optional[aiosqlite.Row]:
        user = await self.get_user(telegram_id)
        if not user:
            return None
        cur = await self.conn.execute(
            "SELECT * FROM watch_progress WHERE user_id=? AND anime_id=?", (user["id"], anime_id)
        )
        return await cur.fetchone()

    async def get_continue_watching(self, telegram_id: int) -> Optional[aiosqlite.Row]:
        """Foydalanuvchi so'nggi ko'rgan bitta animeni (anime ma'lumotlari + oxirgi qism) qaytaradi."""
        rows = await self.list_watch_history(telegram_id, limit=1)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ #
    # Kuzatish (follow) va yangi qism bildirishnomalari
    # ------------------------------------------------------------------ #
    async def toggle_follow(self, anime_id: int, telegram_id: int) -> bool:
        """True — kuzatishga qo'shildi, False — kuzatish bekor qilindi."""
        user = await self.get_user(telegram_id)
        cur = await self.conn.execute(
            "SELECT id FROM follows WHERE user_id=? AND anime_id=?", (user["id"], anime_id)
        )
        row = await cur.fetchone()
        if row:
            await self.conn.execute("DELETE FROM follows WHERE id=?", (row["id"],))
            await self.conn.commit()
            return False
        await self.conn.execute(
            "INSERT INTO follows (user_id, anime_id, followed_at) VALUES (?,?,?)",
            (user["id"], anime_id, _now()),
        )
        await self.conn.commit()
        return True

    async def is_following(self, anime_id: int, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        if not user:
            return False
        cur = await self.conn.execute(
            "SELECT 1 FROM follows WHERE user_id=? AND anime_id=?", (user["id"], anime_id)
        )
        return (await cur.fetchone()) is not None

    async def list_followers(self, anime_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT u.id as user_pk, u.telegram_id FROM follows f "
            "JOIN users u ON u.id=f.user_id WHERE f.anime_id=?",
            (anime_id,),
        )
        return await cur.fetchall()

    async def try_mark_notified(self, user_pk: int, episode_id: int) -> bool:
        """True — bu foydalanuvchiga shu qism haqida ENDI birinchi marta xabar berilmoqda."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO notified_episodes (user_id, episode_id, notified_at) VALUES (?,?,?)",
            (user_pk, episode_id, _now()),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # Ratings
    # ------------------------------------------------------------------ #
    async def rate_anime(self, anime_id: int, telegram_id: int, score: int) -> None:
        user = await self.get_user(telegram_id)
        await self.conn.execute(
            "INSERT INTO ratings (anime_id, user_id, score, rated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(anime_id, user_id) DO UPDATE SET score=excluded.score, rated_at=excluded.rated_at",
            (anime_id, user["id"], score, _now()),
        )
        await self.conn.commit()

    async def has_rated(self, anime_id: int, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        if not user:
            return False
        cur = await self.conn.execute(
            "SELECT 1 FROM ratings WHERE anime_id=? AND user_id=?", (anime_id, user["id"])
        )
        return (await cur.fetchone()) is not None

    # ------------------------------------------------------------------ #
    # Favorites
    # ------------------------------------------------------------------ #
    async def toggle_favorite(self, anime_id: int, telegram_id: int) -> bool:
        """True qaytarsa — qo'shildi, False — olib tashlandi."""
        user = await self.get_user(telegram_id)
        cur = await self.conn.execute(
            "SELECT id FROM favorites WHERE user_id=? AND anime_id=?", (user["id"], anime_id)
        )
        row = await cur.fetchone()
        if row:
            await self.conn.execute("DELETE FROM favorites WHERE id=?", (row["id"],))
            await self.conn.commit()
            return False
        await self.conn.execute(
            "INSERT INTO favorites (user_id, anime_id, added_at) VALUES (?,?,?)",
            (user["id"], anime_id, _now()),
        )
        await self.conn.commit()
        return True

    async def is_favorite(self, anime_id: int, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        if not user:
            return False
        cur = await self.conn.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND anime_id=?", (user["id"], anime_id)
        )
        return (await cur.fetchone()) is not None

    async def list_favorites(self, telegram_id: int) -> list[aiosqlite.Row]:
        user = await self.get_user(telegram_id)
        if not user:
            return []
        cur = await self.conn.execute(
            "SELECT a.* FROM anime a JOIN favorites f ON f.anime_id=a.id "
            "WHERE f.user_id=? ORDER BY f.added_at DESC",
            (user["id"],),
        )
        return await cur.fetchall()

    # ------------------------------------------------------------------ #
    # Watch history
    # ------------------------------------------------------------------ #
    async def log_watch(self, telegram_id: int, anime_id: int, episode_id: int) -> None:
        user = await self.get_user(telegram_id)
        await self.conn.execute(
            "INSERT INTO watch_history (user_id, anime_id, episode_id, watched_at) VALUES (?,?,?,?)",
            (user["id"], anime_id, episode_id, _now()),
        )
        await self.conn.commit()

    async def list_watch_history(self, telegram_id: int, limit: int = 20) -> list[aiosqlite.Row]:
        """
        Har bir anime bo'yicha FAQAT eng oxirgi ko'rilgan qismni qaytaradi
        (watch_progress jadvali allaqachon har (foydalanuvchi, anime) juftligi
        uchun bitta qatorni saqlaydi — shu bilan "davom ettirish" uchun ham,
        "ko'rish tarixi" uchun ham bitta manba ishlatiladi).
        """
        user = await self.get_user(telegram_id)
        if not user:
            return []
        cur = await self.conn.execute(
            "SELECT a.*, wp.episode_id, e.episode_number, s.season_number, "
            "wp.updated_at as last_watched FROM watch_progress wp "
            "JOIN anime a ON a.id=wp.anime_id "
            "JOIN episodes e ON e.id=wp.episode_id "
            "LEFT JOIN seasons s ON s.id=e.season_id "
            "WHERE wp.user_id=? ORDER BY wp.updated_at DESC LIMIT ?",
            (user["id"], limit),
        )
        return await cur.fetchall()

    # ------------------------------------------------------------------ #
    # VIP to'lovlari
    # ------------------------------------------------------------------ #
    async def create_pending_payment(self, telegram_id: int, months: int, price: int,
                                      screenshot_file_id: str) -> int:
        user = await self.get_user(telegram_id)
        cur = await self.conn.execute(
            "INSERT INTO pending_payments (user_id, months, price, screenshot_file_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (user["id"], months, price, screenshot_file_id, _now()),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_pending_payment(self, payment_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM pending_payments WHERE id=?", (payment_id,))
        return await cur.fetchone()

    async def resolve_payment(self, payment_id: int, status: str, resolved_by: int) -> None:
        await self.conn.execute(
            "UPDATE pending_payments SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
            (status, _now(), resolved_by, payment_id),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------ #
    # Majburiy obuna kanallari
    # ------------------------------------------------------------------ #
    async def list_required_channels(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM required_channels ORDER BY id")
        return await cur.fetchall()

    async def add_required_channel(self, chat_id: str, title: str, invite_link: Optional[str] = None) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO required_channels (chat_id, title, invite_link) VALUES (?,?,?)",
            (chat_id, title, invite_link),
        )
        await self.conn.commit()

    async def set_channel_invite_link(self, channel_pk: int, invite_link: str) -> None:
        await self.conn.execute(
            "UPDATE required_channels SET invite_link=? WHERE id=?", (invite_link, channel_pk)
        )
        await self.conn.commit()

    async def remove_required_channel(self, channel_pk: int) -> None:
        await self.conn.execute("DELETE FROM required_channels WHERE id=?", (channel_pk,))
        await self.conn.commit()

    # ------------------------------------------------------------------ #
    # Broadcasts
    # ------------------------------------------------------------------ #
    async def create_broadcast(self, content_type: str, payload: str, total: int,
                                created_by: int) -> int:
        cur = await self.conn.execute(
            "INSERT INTO broadcasts (content_type, payload, total_count, created_at, created_by) "
            "VALUES (?,?,?,?,?)",
            (content_type, payload, total, _now(), created_by),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def update_broadcast_progress(self, broadcast_id: int, sent: int, failed: int) -> None:
        await self.conn.execute(
            "UPDATE broadcasts SET sent_count=?, failed_count=? WHERE id=?",
            (sent, failed, broadcast_id),
        )
        await self.conn.commit()

    async def set_broadcast_status(self, broadcast_id: int, status: str) -> None:
        await self.conn.execute(
            "UPDATE broadcasts SET status=? WHERE id=?", (status, broadcast_id)
        )
        await self.conn.commit()

    async def get_broadcast(self, broadcast_id: int) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM broadcasts WHERE id=?", (broadcast_id,))
        return await cur.fetchone()

    async def get_latest_active_broadcast(self) -> Optional[aiosqlite.Row]:
        """Hozir 'running' yoki 'paused' holatidagi eng so'nggi reklamani qaytaradi (bo'lsa)."""
        cur = await self.conn.execute(
            "SELECT * FROM broadcasts WHERE status IN ('running','paused') ORDER BY id DESC LIMIT 1"
        )
        return await cur.fetchone()

    # ------------------------------------------------------------------ #
    # Statistika
    # ------------------------------------------------------------------ #
    async def stats(self) -> dict[str, Any]:
        cur = await self.conn.execute("SELECT COUNT(*) FROM anime")
        (anime_count,) = await cur.fetchone()
        cur = await self.conn.execute("SELECT COUNT(*) FROM episodes")
        (episode_count,) = await cur.fetchone()
        return {
            "users": await self.count_users(),
            "vip_users": await self.count_vip_users(),
            "anime": anime_count,
            "episodes": episode_count,
        }
