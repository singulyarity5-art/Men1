"""
Test2 Bot — ishga tushirish nuqtasi.

    python main.py

Ishga tushirishdan oldin:
    1. requirements.txt dagi paketlarni o'rnating: pip install -r requirements.txt
    2. .env.example asosida .env fayl yarating va BOT_TOKEN, SUPER_ADMIN_IDS
       qiymatlarini to'ldiring.
"""
from __future__ import annotations

import asyncio
import logging
import random
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import Database
from handlers import admin, user
from handlers.common import SubscriptionMiddleware

logger = logging.getLogger("anime_bot")


def setup_logging() -> None:
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
    )
    # Kutubxonalarning haddan tashqari batafsil loglarini kamaytiramiz
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def vip_expiry_watcher(bot: Bot, db: Database) -> None:
    """Har 10 daqiqada VIP muddati tugagan foydalanuvchilarni tekshiradi."""
    while True:
        try:
            expired_ids = await db.expire_vips()
            for tg_id in expired_ids:
                try:
                    await bot.send_message(
                        tg_id,
                        "⏳ 💎 VIP obunangiz muddati tugadi. Davom ettirish uchun "
                        "👤 Profil → 💎 VIP olish bo'limidan foydalaning.",
                    )
                except Exception:
                    pass
            if expired_ids:
                logger.info("VIP muddati tugagan foydalanuvchilar: %s", expired_ids)
        except Exception:
            logger.exception("vip_expiry_watcher xatolik")
        await asyncio.sleep(600)


async def daily_backup_job(bot: Bot, db: Database) -> None:
    """Har 24 soatda zaxira nusxa olib, SUPER_ADMIN_IDS ga Telegram orqali yuboradi."""
    from aiogram.types import FSInputFile

    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            path = await db.backup()
        except Exception:
            logger.exception("daily_backup_job xatolik")
            continue
        for admin_id in config.SUPER_ADMIN_IDS:
            try:
                await bot.send_document(
                    admin_id,
                    FSInputFile(path),
                    caption="💾 Avtomatik kunlik zaxira nusxa.",
                )
            except Exception:
                logger.exception("Zaxirani adminga yuborib bo'lmadi: %s", admin_id)


async def daily_random_announcement(bot: Bot, db: Database) -> None:
    """19-band: har kuni tasodifiy anime e'lon qilinadi (agar MAIN_CHANNEL sozlangan bo'lsa)."""
    from handlers.admin import _post_announcement  # aylanma import'dan qochish uchun shu yerda

    while True:
        await asyncio.sleep(24 * 60 * 60)
        if not config.MAIN_CHANNEL:
            continue
        try:
            rows = await db.all_anime_for_random()
            if not rows:
                continue
            anime = random.choice(rows)
            await _post_announcement(bot, db, anime["id"])
            logger.info("Kunlik random anime e'loni yuborildi: %s", anime["title"])
        except Exception:
            logger.exception("daily_random_announcement xatolik")


async def main() -> None:
    setup_logging()

    if not config.BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN topilmadi. .env faylida BOT_TOKEN=... qiymatini kiriting."
        )

    db = Database(config.DB_PATH)
    await db.connect()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # db obyektini barcha handlerlarga avtomatik uzatish
    dp["db"] = db

    # Har bir harakatda majburiy obunani qayta tekshiradigan middleware
    # (Inner) middleware — shunda data["state"] (FSMContext) kafolatlangan holda
    # mavjud bo'ladi, bu "💎 VIP olish" oqimini obunasiz ham ishlashi uchun kerak.
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(admin.router)  # admin filtri o'zida bo'lgani uchun avval ulaymiz
    dp.include_router(user.router)

    dp.startup.register(lambda: logger.info("Bot ishga tushdi."))

    background_tasks = [
        asyncio.create_task(vip_expiry_watcher(bot, db)),
        asyncio.create_task(daily_backup_job(bot, db)),
        asyncio.create_task(daily_random_announcement(bot, db)),
    ]

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
