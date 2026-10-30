"""
Anime qo'shishda AniList'dan avtomatik to'ldirish (admin uchun).

Oqim: nom kiritiladi -> [🔎 AniList'dan to'ldirish] / [✍️ Qo'lda kiritish]
      AniList: natijalar ro'yxati -> bittasini tanlaydi -> tavsif, plakat, janr, yil, davlat avtomatik olinadi
      -> admin janrlarni tekshiradi (✅ Tayyor) -> til va subtitr tanlanadi -> anime saqlanadi.
"""
from __future__ import annotations

import html
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import anilist
import keyboards as kb
from database import Database
from handlers.common import IsAdminFilter
from states import AddAnimeStates

logger = logging.getLogger("anime_bot.anilist_ui")
router = Router(name="anilist_ui")
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())

STATES_OK = (AddAnimeStates.waiting_source, AddAnimeStates.waiting_al_query)


async def _continue_manual(message: Message, state: FSMContext) -> None:
    await state.set_state(AddAnimeStates.waiting_description)
    await message.answer("📝 Anime tavsifini kiriting (yoki «-» deb yozing, tavsifsiz qo'shish uchun):")


async def _run_search(message: Message, state: FSMContext, query: str) -> None:
    wait = await message.answer(f"🔎 AniList'da «{html.escape(query)}» qidirilmoqda...")
    try:
        results = await anilist.search(query, limit=5)
    except Exception as e:
        logger.warning("AniList qidiruvi xato: %s", e)
        await wait.edit_text(
            "❌ AniList bilan bog'lanib bo'lmadi (internet yoki sayt vaqtincha ishlamayapti). "
            "Qo'lda kiritishingiz yoki keyinroq urinib ko'rishingiz mumkin.",
            reply_markup=kb.anilist_retry_keyboard(),
        )
        await state.set_state(AddAnimeStates.waiting_source)
        return
    if not results:
        await wait.edit_text(
            f"😕 «{html.escape(query)}» bo'yicha hech narsa topilmadi. "
            "Inglizcha yoki yapon (romaji) nomini yozib ko'ring.",
            reply_markup=kb.anilist_retry_keyboard(),
        )
        await state.set_state(AddAnimeStates.waiting_source)
        return
    await state.update_data(al_results={str(r["id"]): r for r in results})
    await state.set_state(AddAnimeStates.waiting_source)
    await wait.edit_text(
        "Mos keladiganini tanlang:",
        reply_markup=kb.anilist_results_keyboard([(r["id"], anilist.button_label(r)) for r in results]),
    )


@router.callback_query(AddAnimeStates.waiting_source, F.data == "al:search")
async def al_search(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await call.answer()
    await _run_search(call.message, state, data.get("new_title", ""))


@router.callback_query(AddAnimeStates.waiting_source, F.data == "al:retry")
async def al_retry(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddAnimeStates.waiting_al_query)
    await call.message.answer("✍️ Anime nomini (inglizcha yoki romaji) yozing:", reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(AddAnimeStates.waiting_al_query)
async def al_query_text(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("✏️ Iltimos, nomni matn ko'rinishida yuboring.")
        return
    await _run_search(message, state, message.text.strip())


@router.callback_query(AddAnimeStates.waiting_source, F.data == "al:manual")
async def al_manual(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await _continue_manual(call.message, state)


@router.message(AddAnimeStates.waiting_source)
async def al_source_wrong(message: Message):
    await message.answer(
        "👆 Iltimos, yuqoridagi tugmalardan birini tanlang: AniList'dan to'ldirish yoki qo'lda kiritish.",
        reply_markup=kb.anilist_source_keyboard(),
    )


async def _poster_file_id(bot: Bot, chat_id: int, url: str) -> Optional[str]:
    """Plakat rasmini Telegramga yuklab, file_id oladi (admin ko'rishi uchun chatga ham tushadi)."""
    if not url:
        return None
    try:
        msg = await bot.send_photo(chat_id, url, caption="🖼 AniList plakati (anime kartasida shu rasm bo'ladi)")
        return msg.photo[-1].file_id
    except Exception as e:
        logger.warning("Plakatni yuklab bo'lmadi: %s", e)
        return None


@router.callback_query(AddAnimeStates.waiting_source, F.data.startswith("al:pick:"))
async def al_pick(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    al_id = call.data.split(":")[2]
    data = await state.get_data()
    item = (data.get("al_results") or {}).get(al_id)
    if not item:
        await call.answer("Natija eskirgan. Qaytadan qidiring.", show_alert=True)
        return
    await call.answer()
    chat_id = call.message.chat.id

    poster = await _poster_file_id(bot, chat_id, item["cover_url"])
    genres = await db.list_genres()
    genre_ids = anilist.match_genre_ids(item["genres"], genres)

    await state.update_data(
        anilist_id=item["id"],
        new_description=item["description"],
        new_poster=poster,
        al_country=item["country"],
        al_year=item["year"] or None,
        selected_genres=genre_ids,
        al_results=None,
    )

    names = {g["id"]: g["name"] for g in genres}
    lines = [f"✅ «{html.escape(item['title'])}» ma'lumotlari AniList'dan olindi:"]
    lines.append(f"📖 Tavsif: {len(item['description'])} belgi" if item["description"] else "📖 Tavsif: topilmadi")
    lines.append("🖼 Plakat: " + ("olindi" if poster else "olib bo'lmadi (keyin «Posterni almashtirish» orqali qo'shing)"))
    lines.append("📅 Yil: " + (item["year"] or "—") + " · 🌍 Davlat: " + (item["country"] or "tanlanadi"))
    if genre_ids:
        lines.append("🎭 Janr: " + ", ".join(names[i] for i in genre_ids))
    lines.append("")
    lines.append("ℹ️ Tavsif inglizcha bo'lishi mumkin — kerak bo'lsa, anime saqlangandan keyin «✏️ Tavsifni tahrirlash» orqali o'zbekchaga o'zgartiring.")
    await bot.send_message(chat_id, "\n".join(lines))

    await state.set_state(AddAnimeStates.waiting_genres)
    await bot.send_message(
        chat_id,
        "🎭 Janrlarni tekshiring (kerak bo'lsa o'zgartiring), so'ng ✅ Tayyor bosing:",
        reply_markup=kb.genres_menu(genres, selected_ids=set(genre_ids), for_admin_add=True),
    )
