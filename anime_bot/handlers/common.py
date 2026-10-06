"""Umumiy yordamchi funksiyalar: majburiy obuna tekshiruvi va h.k."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware, Bot
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

import keyboards as kb
from database import Database


class IsAdminFilter(BaseFilter):
    """Faqat is_admin=1 bo'lgan foydalanuvchilarga ruxsat beradi."""

    async def __call__(self, event: TelegramObject, db: Database) -> bool:
        user = event.from_user
        if user is None:
            return False
        return await db.is_admin(user.id)


async def is_subscribed_to_all(bot: Bot, db: Database, telegram_id: int) -> list:
    """Obuna bo'lmagan kanallar ro'yxatini qaytaradi (bo'sh bo'lsa — hammasiga obuna)."""
    channels = await db.list_required_channels()
    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=telegram_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            # Bot kanalga admin qilib qo'shilmagan yoki chat topilmadi —
            # bunday holatda foydalanuvchini bloklamaslik uchun o'tkazib yuboramiz,
            # lekin adminlar buni logdan ko'rishi mumkin.
            continue
    return missing


async def has_vip_access(db: Database, telegram_id: int) -> bool:
    """
    Foydalanuvchi VIP kontentga kira oladimi: o'zi haqiqiy VIP bo'lsa,
    YOKI hozir admin yoqqan vaqtinchalik "hammaga bepul" VIP rejimi
    faol bo'lsa — True qaytaradi.
    """
    if await db.is_vip(telegram_id):
        return True
    return await db.is_vip_free_mode()


class SubscriptionMiddleware(BaseMiddleware):
    """
    Har bir foydalanuvchi harakatida (matn buyruq yoki inline tugma bosilganda)
    majburiy kanal(lar)ga obuna HALI HAM davom etayotganini qayta tekshiradi.

    Muammo: avvalgi kodda bu tekshiruv faqat /start bosilganda bo'lardi — foydalanuvchi
    bir marta obuna bo'lib, keyin kanaldan chiqib ketsa ham bot buni bilmasdi.
    Endi har bir harakatda (admin va /start/✅ Tekshirishdan tashqari) tekshiriladi.
    """

    SKIP_CALLBACKS = {"check_subs"}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user: Optional[TgUser] = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            if event.data in self.SKIP_CALLBACKS:
                return await handler(event, data)
        else:
            return await handler(event, data)

        db: Database = data["db"]
        bot: Bot = data["bot"]

        # Adminlar bloklanmaydi — ular botni boshqarishda davom etishi kerak.
        if await db.is_admin(tg_user.id):
            return await handler(event, data)

        missing = await is_subscribed_to_all(bot, db, tg_user.id)
        if missing:
            text = (
                "📢 Davom etish uchun quyidagi majburiy kanal(lar)ga obuna bo'ling "
                "(shekilli, avval obuna bo'lgan kanal(lar)dan chiqib ketgansiz), "
                "so'ng ✅ Tekshirish tugmasini bosing:"
            )
            markup = kb.subscribe_keyboard(missing)
            if isinstance(event, CallbackQuery):
                await event.answer("❗ Majburiy kanal(lar)ga obuna talab qilinadi.", show_alert=True)
                try:
                    await event.message.answer(text, reply_markup=markup)
                except Exception:
                    pass
            else:
                await event.answer(text, reply_markup=markup)
            return  # handlerga o'tkazmaymiz — harakat shu yerda to'xtaydi

        return await handler(event, data)


async def ensure_user(db: Database, tg_user: TgUser):
    user = await db.get_user(tg_user.id)
    if user is None:
        user = await db.create_user(tg_user.id, tg_user.full_name, tg_user.username)
    else:
        await db.touch_user(tg_user.id, tg_user.full_name, tg_user.username)
    return user


def fmt_number(n: int | str) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n:,}".replace(",", " ")
