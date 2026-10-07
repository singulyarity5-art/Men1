"""Umumiy yordamchi funksiyalar: majburiy obuna tekshiruvi va h.k."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

import keyboards as kb
from database import Database
from states import VipPaymentStates


class IsAdminFilter(BaseFilter):
    """Faqat is_admin=1 bo'lgan foydalanuvchilarga ruxsat beradi."""

    async def __call__(self, event: TelegramObject, db: Database) -> bool:
        user = event.from_user
        if user is None:
            return False
        return await db.is_admin(user.id)


async def is_subscribed_to_all(bot: Bot, db: Database, telegram_id: int) -> list:
    """
    Obuna bo'lmagan (yoki holatini ANIQLAB BO'LMAGAN) kanallar ro'yxatini qaytaradi
    (bo'sh ro'yxat = hammasiga obuna tasdiqlangan).

    Agar bot shu kanal/guruhda admin qilib qo'shilmagan bo'lsa (yoki chat topilmasa),
    foydalanuvchining haqiqiy obunasini TASDIQLAB bo'lmaydi — xavfsizlik uchun bu
    holat ham "obuna emas" deb hisoblanadi (silently o'tkazib yuborilmaydi), va
    natijadagi qatorga "_bot_not_admin" belgisi qo'shiladi — shu orqali chaqiruvchi
    kod (build_subscribe_prompt) foydalanuvchiga aniq sabab ko'rsata oladi.
    """
    channels = await db.list_required_channels()
    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=telegram_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except (TelegramBadRequest, TelegramForbiddenError):
            # Odatda bu "bot kanalda admin emas" yoki "chat topilmadi" degani.
            row = dict(ch)
            row["_bot_not_admin"] = True
            missing.append(row)
        except Exception:
            # Kutilmagan/noma'lum xato — avvalgidek, foydalanuvchini bloklamaymiz.
            continue
    return missing


def build_subscribe_prompt(missing: list) -> tuple[str, "kb.InlineKeyboardMarkup"]:
    """
    is_subscribed_to_all() natijasidan foydalanuvchiga ko'rsatiladigan matn va
    klaviaturani tayyorlaydi. Agar kanallardan birortasida bot admin emasligi
    aniqlangan bo'lsa (ko'rinishidan sabab shu), aniq diagnostika xabari chiqadi.
    """
    bot_issue = any(isinstance(ch, dict) and ch.get("_bot_not_admin") for ch in missing)
    if bot_issue:
        text = (
            "⚠️ Bot kanal/guruhda admin emas. Kanal sozlamalaridan botga admin huquqi bering.\n\n"
            "Shundan keyin ✅ Tekshirish tugmasini qayta bosing."
        )
    else:
        text = (
            "📢 Davom etish uchun quyidagi majburiy kanal(lar)ga obuna bo'ling, "
            "so'ng ✅ Tekshirish tugmasini bosing:"
        )
    return text, kb.subscribe_keyboard(missing)


async def build_anime_card_text(db: Database, anime) -> str:
    """
    Anime haqida avtomatik, bir xil ko'rinishdagi matn tayyorlaydi — admin buni
    qo'lda yozmaydi, database ma'lumotlaridan hosil bo'ladi. Shu funksiya HAM
    anime sahifasida (user.py), HAM kanalga e'lon qilishda (admin.py) bir xil
    ko'rinishni ta'minlash uchun qayta ishlatiladi (ikki joyda alohida-alohida
    yozilmaydi).
    """
    genres = await db.get_anime_genres(anime["id"])
    genre_txt = ", ".join(g["name"] for g in genres) or "—"
    seasons = await db.list_seasons(anime["id"])
    ep_count = await db.count_episodes(anime["id"])
    avg, rated_count = await db.anime_avg_rating(anime["id"])

    lines = [
        f"🎬 <b>{anime['title']}</b>",
        f"🆔 Anime ID: <code>{anime['anime_code']}</code>",
        "",
        f"🎭 Janr: {genre_txt}",
    ]
    if anime["country"]:
        lines.append(f"🌍 Davlat: {anime['country']}")
    if anime["release_year"]:
        lines.append(f"📅 Yil: {anime['release_year']}")
    if seasons:
        lines.append(f"🎬 {len(seasons)} fasl • {ep_count} qism")
    elif ep_count == 1:
        lines.append("🎬 Film")
    elif ep_count > 1:
        lines.append(f"🎬 {ep_count} qism")
    if anime["language"]:
        lines.append(f"🇺🇿 Til: {anime['language']}")
    lines.append("")
    if anime["description"]:
        lines.append(f"📖 {anime['description']}")
    lines.append("")
    lines.append(f"⭐ Reyting: {avg}/10" if rated_count else "⭐ Reyting: hali baholanmagan")
    if anime["is_vip"]:
        lines.append("\n💎 VIP anime")
    return "\n".join(lines)


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

    SKIP_CALLBACKS = {"check_subs", "vip_open"}

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
            if event.data in self.SKIP_CALLBACKS or (event.data and event.data.startswith("vip_buy:")):
                return await handler(event, data)
        else:
            return await handler(event, data)

        db: Database = data["db"]
        bot: Bot = data["bot"]

        # Adminlar bloklanmaydi — ular botni boshqarishda davom etishi kerak.
        if await db.is_admin(tg_user.id):
            return await handler(event, data)

        # "💎 VIP olish" majburiy obuna oynasidan ham chaqirilishi mumkin (talab
        # qilingan) — shuning uchun to'lov skrinshotini kutish bosqichida ham
        # obuna tekshiruvi bloklamasligi kerak, aks holda oqim yarim yo'lda to'xtab qoladi.
        state = data.get("state")
        if state is not None:
            current = await state.get_state()
            if current == VipPaymentStates.waiting_screenshot.state:
                return await handler(event, data)

        missing = await is_subscribed_to_all(bot, db, tg_user.id)
        if missing:
            text, markup = build_subscribe_prompt(missing)
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
