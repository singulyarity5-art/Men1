"""
Test2 Bot — Webhook va Aiohttp Server.
"""
from __future__ import annotations
import os
import asyncio
import logging
import random
from logging.handlers import RotatingFileHandler

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

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


async def daily_backup_job(db: Database) -> None:
    """Har 24 soatda avtomatik zaxira nusxa oladi."""
    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            await db.backup()
        except Exception:
            logger.exception("daily_backup_job xatolik")


async def daily_random_announcement(bot: Bot, db: Database) -> None:
    """Har kuni tasodifiy anime e'lon qilinadi."""
    from handlers.admin import _post_announcement

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


def main() -> None:
    setup_logging()

    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi. .env faylida BOT_TOKEN=... qiymatini kiriting.")

    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        raise SystemExit("RENDER_EXTERNAL_URL topilmadi.")

    webhook_path = f"/webhook/{config.BOT_TOKEN}"
    webhook_url = f"{render_url}{webhook_path}"

    db = Database(config.DB_PATH)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # db obyektini barcha handlerlarga uzatamiz
    dp["db"] = db

    # Har bir harakatda majburiy obunani qayta tekshiradigan middleware
    dp.message.outer_middleware(SubscriptionMiddleware())
    dp.callback_query.outer_middleware(SubscriptionMiddleware())

    dp.include_router(admin.router)
    dp.include_router(user.router)

    background_tasks = []

    async def on_startup(app: web.Application) -> None:
        await db.connect()
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info("Webhook o'rnatildi: %s", webhook_url)

        # Orqa fondagi (background) vazifalarni ishga tushiramiz
        background_tasks.extend([
            asyncio.create_task(vip_expiry_watcher(bot, db)),
            asyncio.create_task(daily_backup_job(db)),
            asyncio.create_task(daily_random_announcement(bot, db)),
        ])

    async def on_cleanup(app: web.Application) -> None:
        for task in background_tasks:
            task.cancel()
        await bot.delete_webhook()
        await db.close()
        await bot.session.close()

    app = web.Application()

    # Aiogram tayyor webhook ishlovchisi
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    port = int(os.getenv("PORT", "10000"))

    web.run_app(
        app,
        host="0.0.0.0",
        port=port
    )


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
