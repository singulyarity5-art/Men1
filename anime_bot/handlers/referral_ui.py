"""
Referal tizimining ekranlari:
  * router        — foydalanuvchi: "🎁 Do'st taklif qilish" (profil tugmasi yoki /invite)
  * admin_router  — admin panel: "🎁 Referal" (yoqish/o'chirish, kunlar, oylik chegara, statistika)
Mantiq (mukofot berish) referral.py da.
"""
from __future__ import annotations

import html
import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import keyboards as kb
from database import Database
from handlers.common import IsAdminFilter
from referral import build_link, get_settings
from states import ReferralAdminStates

logger = logging.getLogger("anime_bot.referral_ui")

router = Router(name="referral")
admin_router = Router(name="referral_admin")
admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())

SHARE_TEXT = "🎬 Anime ko'rish uchun zo'r bot! Mening havolam orqali kiring va VIP sovg'a oling 🎁"


# ================================================================== #
# Foydalanuvchi
# ================================================================== #
async def _user_screen(bot: Bot, db: Database, telegram_id: int):
    cfg = await get_settings(db)
    if not cfg["enabled"]:
        return "🎁 Do'st taklif qilish tizimi hozircha o'chirilgan.", None
    link = await build_link(bot, telegram_id)
    total, rewarded, days = await db.referral_stats(telegram_id)
    reward_lines = []
    if cfg["inviter_days"] > 0:
        reward_lines.append(f"Har bir do'stingiz uchun siz <b>{cfg['inviter_days']} kun VIP</b> olasiz")
    if cfg["invitee_days"] > 0:
        reward_lines.append(f"do'stingiz esa <b>{cfg['invitee_days']} kun VIP</b> sovg'a oladi")
    rewards = ", ".join(reward_lines) + "." if reward_lines else "Hozircha mukofot belgilanmagan."
    limit_txt = (
        f"\n⚠️ Bir oyda ko'pi bilan {cfg['monthly_limit']} ta do'st uchun mukofot beriladi."
        if cfg["monthly_limit"] > 0 else ""
    )
    text = (
        "🎁 <b>Do'st taklif qiling — VIP oling!</b>\n\n"
        f"{rewards}\n"
        "Mukofot do'stingiz majburiy kanallarga obuna bo'lgach beriladi."
        f"{limit_txt}\n\n"
        f"🔗 <b>Sizning havolangiz:</b>\n<code>{link}</code>\n\n"
        f"👥 Taklif qilganlar: {total} ta\n"
        f"✅ Mukofot olingan: {rewarded} ta\n"
        f"💎 Jami olingan VIP: {days} kun"
    )
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(SHARE_TEXT, safe='')}"
    return text, kb.referral_share_keyboard(share_url)


@router.callback_query(F.data == "ref:open")
async def ref_open(call: CallbackQuery, db: Database, bot: Bot):
    text, markup = await _user_screen(bot, db, call.from_user.id)
    await call.message.answer(text, reply_markup=markup)
    await call.answer()


@router.message(F.text == "🎁 Do'st taklif qilish")
@router.message(Command("invite"))
async def ref_command(message: Message, db: Database, bot: Bot, state: FSMContext):
    await state.clear()
    text, markup = await _user_screen(bot, db, message.from_user.id)
    await message.answer(text, reply_markup=markup)


# ================================================================== #
# Admin
# ================================================================== #
_LABELS = {
    "inviter_days": "taklif qilgan odamga beriladigan VIP kunlari",
    "invitee_days": "taklif qilingan do'stga beriladigan VIP kunlari",
    "monthly_limit": "bir odam bir oyda mukofot olishi mumkin bo'lgan do'stlar soni (0 = chegarasiz)",
}


async def _admin_screen(db: Database):
    cfg = await get_settings(db)
    total, rewarded, days = await db.referral_totals()
    top = await db.top_referrers(5)
    lines = [
        "🎁 <b>Referal tizimi</b>",
        "",
        "Holati: " + ("✅ Yoqilgan" if cfg["enabled"] else "⏸ O'chirilgan"),
        f"Taklif qilgan odamga: <b>{cfg['inviter_days']} kun</b> VIP",
        f"Taklif qilingan do'stga: <b>{cfg['invitee_days']} kun</b> VIP",
        f"Oylik chegara: <b>{cfg['monthly_limit'] if cfg['monthly_limit'] else 'chegarasiz'}</b>",
        "",
        f"📊 Jami takliflar: {total} ta (mukofot berilgan: {rewarded} ta)",
        f"💎 Berilgan jami VIP: {days} kun",
    ]
    if top:
        lines += ["", "🏆 <b>Eng ko'p taklif qilganlar:</b>"]
        for i, r in enumerate(top, 1):
            name = html.escape(r["full_name"] or str(r["inviter_id"]))
            uname = f" (@{html.escape(r['username'])})" if r["username"] else ""
            lines.append(f"{i}. {name}{uname} — {r['rewarded']} ta, {r['days']} kun")
    return "\n".join(lines), kb.admin_referral_keyboard(cfg["enabled"])


async def _edit_or_send(call: CallbackQuery, text: str, markup) -> None:
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=markup)


@admin_router.callback_query(F.data == "adm:ref")
async def admin_ref_open(call: CallbackQuery, state: FSMContext, db: Database):
    await state.clear()
    text, markup = await _admin_screen(db)
    await _edit_or_send(call, text, markup)
    await call.answer()


@admin_router.callback_query(F.data == "adm_ref:toggle")
async def admin_ref_toggle(call: CallbackQuery, db: Database):
    cfg = await get_settings(db)
    await db.set_setting("referral_enabled", "0" if cfg["enabled"] else "1")
    text, markup = await _admin_screen(db)
    await _edit_or_send(call, text, markup)
    await call.answer("O'chirildi" if cfg["enabled"] else "Yoqildi")


@admin_router.callback_query(F.data.startswith("adm_ref:set:"))
async def admin_ref_set_start(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[2]
    if key not in _LABELS:
        await call.answer()
        return
    await state.clear()
    await state.update_data(ref_key=key)
    await state.set_state(ReferralAdminStates.waiting_value)
    await call.message.answer(
        f"✏️ Yangi qiymatni yozing — {_LABELS[key]}.\nButun son yuboring (masalan: 7).",
        reply_markup=kb.cancel_menu(),
    )
    await call.answer()


@admin_router.message(ReferralAdminStates.waiting_value, F.text)
async def admin_ref_set_save(message: Message, state: FSMContext, db: Database):
    raw = (message.text or "").strip()
    data = await state.get_data()
    key = data.get("ref_key")
    limit = 1000 if key == "monthly_limit" else 365
    if not raw.isdigit() or int(raw) > limit:
        await message.answer(f"❗ 0 dan {limit} gacha bo'lgan butun son yuboring.")
        return
    await db.set_setting(f"referral_{key}", str(int(raw)))
    await state.clear()
    await message.answer("✅ Saqlandi.", reply_markup=kb.main_menu(is_admin=True))
    text, markup = await _admin_screen(db)
    await message.answer(text, reply_markup=markup)


@admin_router.message(ReferralAdminStates.waiting_value)
async def admin_ref_set_wrong(message: Message):
    await message.answer("✍️ Iltimos, son yuboring yoki «❌ Bekor qilish» tugmasini bosing.")
