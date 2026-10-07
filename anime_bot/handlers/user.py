from __future__ import annotations

import datetime
import logging
import math
import random

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

import keyboards as kb
from database import Database
from handlers.common import (
    build_anime_card_text,
    build_subscribe_prompt,
    ensure_user,
    fmt_number,
    has_vip_access,
    is_subscribed_to_all,
)
from states import SearchStates, VipPaymentStates

logger = logging.getLogger("anime_bot.user")
router = Router(name="user")

PER_PAGE = 10


async def _single_episode_id(db: Database, anime_id: int, has_seasons: bool) -> int | None:
    """Agar anime fasllarsiz va atigi 1 qismdan iborat bo'lsa (film), o'sha qismning ID'sini qaytaradi."""
    if has_seasons:
        return None
    ep_count = await db.count_episodes(anime_id)
    if ep_count != 1:
        return None
    eps = await db.list_episodes_page(anime_id, 0, None)
    return eps[0]["id"] if eps else None


async def _vip_free_banner(db: Database) -> str:
    """Agar hozir vaqtinchalik 'VIP hammaga bepul' rejimi faol bo'lsa, banner matnini qaytaradi."""
    until = await db.get_vip_free_until()
    if until and until > datetime.datetime.utcnow():
        return (
            f"🎁 <b>E'lon:</b> hozirda VIP animelarni ham BEPUL tomosha qilishingiz mumkin! "
            f"({until.strftime('%d.%m.%Y')} kungacha)\n\n"
        )
    return ""


# ------------------------------------------------------------------ #
# /start
# ------------------------------------------------------------------ #
@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, state: FSMContext):
    await state.clear()
    user = await ensure_user(db, message.from_user)

    missing = await is_subscribed_to_all(message.bot, db, message.from_user.id)
    if missing:
        text, markup = build_subscribe_prompt(missing)
        await message.answer(text, reply_markup=markup)
        return

    # Kanaldagi "▶️ Animeni ko'rish" tugmasi orqali kirilgan bo'lishi mumkin:
    # https://t.me/<bot>?start=anime_<code>
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("anime_"):
        code = args[1][len("anime_"):]
        anime = await db.get_anime_by_code(code)
        if anime:
            await _send_start_message(message, db, is_admin=bool(user["is_admin"]))
            await show_anime_detail(message, db, anime["id"], message.from_user.id)
            return

    await _send_start_message(message, db, is_admin=bool(user["is_admin"]))
    await _maybe_show_continue_watching(message, db, message.from_user.id)


async def _maybe_show_continue_watching(message: Message, db: Database, telegram_id: int) -> None:
    """Agar foydalanuvchi ilgari biror anime ko'rgan bo'lsa, davom ettirish taklifini ko'rsatadi."""
    progress = await db.get_continue_watching(telegram_id)
    if not progress:
        return
    season_txt = f" {progress['season_number']}-fasl," if progress["season_number"] else ""
    text = (
        f"▶️ <b>Ko'rishni davom ettirish</b>\n\n"
        f"🎬 {progress['title']} —{season_txt} {progress['episode_number']}-qismdan keyin"
    )
    await message.answer(text, reply_markup=kb.continue_watching_keyboard(progress["id"]))


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


async def _send_start_message(message: Message, db: Database, is_admin: bool):
    text = await db.get_setting("start_text")
    photo = await db.get_setting("start_photo_file_id")
    markup = kb.main_menu(is_admin=is_admin)
    if photo:
        try:
            await message.answer_photo(photo, caption=text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "check_subs")
async def check_subs(call: CallbackQuery, db: Database):
    missing = await is_subscribed_to_all(call.bot, db, call.from_user.id)
    if missing:
        await call.answer("❗ Hali barcha kanallarga obuna bo'lmadingiz.", show_alert=True)
        return
    user = await ensure_user(db, call.from_user)
    await call.message.delete()
    await _send_start_message(call.message, db, is_admin=bool(user["is_admin"]))
    await _maybe_show_continue_watching(call.message, db, call.from_user.id)
    await call.answer("✅ Obuna tasdiqlandi!")


@router.message(F.text == "👤 Foydalanuvchi paneliga qaytish")
async def back_to_user_panel(message: Message, db: Database):
    user = await ensure_user(db, message.from_user)
    await message.answer("Bosh menyu:", reply_markup=kb.main_menu(is_admin=bool(user["is_admin"])))


# ------------------------------------------------------------------ #
# Qidiruv
# ------------------------------------------------------------------ #
@router.message(F.text == "🔎 Anime qidirish")
async def search_entry(message: Message, state: FSMContext, db: Database):
    await state.clear()
    banner = await _vip_free_banner(db)
    await message.answer(f"{banner}Qidiruv turini tanlang:", reply_markup=kb.search_menu())


@router.callback_query(F.data == "search:title")
async def search_by_title(call: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_title)
    await call.message.answer("🔤 Anime nomini kiriting:", reply_markup=kb.cancel_menu())
    await call.answer()


@router.callback_query(F.data == "search:code")
async def search_by_code(call: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_code)
    await call.message.answer("🆔 Anime ID (kod) ni kiriting:", reply_markup=kb.cancel_menu())
    await call.answer()


@router.callback_query(F.data == "search:top10")
async def search_top10(call: CallbackQuery, db: Database):
    rows = await db.list_top_rated(limit=10)
    if not rows:
        await call.answer("Hozircha baholangan anime yo'q.", show_alert=True)
        return
    lines = ["⭐ <b>Eng yuqori baholangan 10 ta anime:</b>\n"]
    for i, a in enumerate(rows, start=1):
        lines.append(f"{i}. {a['title']} — {a['avg_score']:.1f}⭐ ({a['rate_count']} baho)")
    await call.message.answer("\n".join(lines), reply_markup=kb.anime_list_keyboard(rows, 0, 1, "top10"))
    await call.answer()


@router.message(F.text == "❌ Bekor qilish")
async def cancel_any(message: Message, db: Database, state: FSMContext):
    await state.clear()
    user = await ensure_user(db, message.from_user)
    await message.answer("Bekor qilindi.", reply_markup=kb.main_menu(is_admin=bool(user["is_admin"])))


@router.message(SearchStates.waiting_title)
async def do_search_title(message: Message, db: Database, state: FSMContext):
    query = message.text.strip()
    await state.update_data(search_query=query)
    await state.clear()
    rows = await db.search_anime_by_title(query, limit=PER_PAGE)
    if not rows:
        await message.answer("😕 Hech narsa topilmadi.", reply_markup=kb.main_menu())
        return
    await message.answer(
        f"🔎 «{query}» bo'yicha natijalar:",
        reply_markup=kb.anime_list_keyboard(rows, 0, 1, "search_title"),
    )


@router.message(SearchStates.waiting_code)
async def do_search_code(message: Message, db: Database, state: FSMContext):
    code = message.text.strip()
    await state.clear()
    anime = await db.get_anime_by_code(code)
    if not anime:
        await message.answer("😕 Bunday ID bilan anime topilmadi.", reply_markup=kb.main_menu())
        return
    await show_anime_detail(message, db, anime["id"], message.from_user.id)


# ------------------------------------------------------------------ #
# Katalog / Yangi / Mashhur / Janrlar
# ------------------------------------------------------------------ #
@router.message(F.text == "🆕 Yangi animelar")
async def new_anime(message: Message, db: Database):
    rows = await db.list_new_anime(page=0, per_page=PER_PAGE)
    if not rows:
        await message.answer("Hozircha anime qo'shilmagan.")
        return
    total_pages = max(1, math.ceil(await db.count_published_anime() / PER_PAGE))
    await message.answer("🆕 Yangi qo'shilgan animelar:",
                          reply_markup=kb.anime_list_keyboard(rows, 0, total_pages, "new"))


@router.message(F.text == "🔥 Mashhur animelar")
async def popular_anime(message: Message, db: Database):
    rows = await db.list_popular_anime(page=0, per_page=PER_PAGE)
    if not rows:
        await message.answer("Hozircha anime qo'shilmagan.")
        return
    total_pages = max(1, math.ceil(await db.count_published_anime() / PER_PAGE))
    await message.answer("🔥 Mashhur animelar:",
                          reply_markup=kb.anime_list_keyboard(rows, 0, total_pages, "popular"))


@router.message(F.text == "🔥 Yangi qismlar")
async def recent_episodes(message: Message, db: Database, telegram_id: int | None = None):
    """Oldindan mavjud animelarga yaqinda qo'shilgan qismlar (🆕 Yangi animelardan farqli)."""
    telegram_id = telegram_id or message.from_user.id
    rows = await db.list_recent_episodes(limit=50)
    viewer_has_vip = await has_vip_access(db, telegram_id)
    visible = [r for r in rows if viewer_has_vip or not r["anime_is_vip"]]
    visible = visible[:PER_PAGE]
    if not visible:
        await message.answer("Hozircha yangi qism qo'shilmagan.")
        return
    await message.answer("🔥 Yaqinda qo'shilgan qismlar:", reply_markup=kb.recent_episodes_keyboard(visible))


@router.message(F.text == "🎲 Tasodifiy anime")
async def random_anime(message: Message, db: Database, telegram_id: int | None = None):
    """
    MUHIM: bu funksiya (random tanlash/VIP filtrlash mantig'i) o'zgartirilmagan —
    faqat qayerdan chaqirilishi o'zgardi: endi asosiy menyuda alohida tugma emas,
    balki "🎬 Anime ko'rish" markazi ichida (va eski matnli buyruq ham ishlayveradi).
    """
    telegram_id = telegram_id or message.from_user.id
    rows = await db.all_anime_for_random()
    if not rows:
        await message.answer("Hozircha anime qo'shilmagan.")
        return
    viewer_has_vip = await has_vip_access(db, telegram_id)
    candidates = [a for a in rows if viewer_has_vip or not a["is_vip"]]
    if not candidates:
        candidates = rows  # hammasi VIP bo'lsa ham ko'rsatamiz — anime sahifasi o'zi bloklaydi
    anime = random.choice(candidates)
    await message.answer("🎲 Bugungi tasodifiy anime:")
    await show_anime_detail(message, db, anime["id"], telegram_id)


# ------------------------------------------------------------------ #
# "🎬 Anime ko'rish" markazi — mavjud brauzing funksiyalarini (qayta
# yozmasdan) bitta joydan ochish uchun. Har bir tugma MAVJUD funksiyani
# chaqiradi, yangi parallel mantiq yaratilmaydi.
# ------------------------------------------------------------------ #
@router.message(F.text == "🎬 Anime ko'rish")
async def anime_browse_hub(message: Message):
    await message.answer("🎬 Anime ko'rish:", reply_markup=kb.anime_browse_hub_keyboard())


@router.callback_query(F.data == "browse:hub")
async def browse_hub_cb(call: CallbackQuery):
    await call.answer()
    await call.message.answer("🎬 Anime ko'rish:", reply_markup=kb.anime_browse_hub_keyboard())


@router.callback_query(F.data == "browse:search")
async def browse_search(call: CallbackQuery, state: FSMContext, db: Database):
    await call.answer()
    await search_entry(call.message, state, db)


@router.callback_query(F.data == "browse:catalog")
async def browse_catalog(call: CallbackQuery, db: Database):
    await call.answer()
    await catalog(call.message, db)


@router.callback_query(F.data == "browse:genres")
async def browse_genres(call: CallbackQuery, db: Database):
    await call.answer()
    await genres_list(call.message, db)


@router.callback_query(F.data == "browse:new")
async def browse_new(call: CallbackQuery, db: Database):
    await call.answer()
    await new_anime(call.message, db)


@router.callback_query(F.data == "browse:popular")
async def browse_popular(call: CallbackQuery, db: Database):
    await call.answer()
    await popular_anime(call.message, db)


@router.callback_query(F.data == "browse:recent_episodes")
async def browse_recent_episodes(call: CallbackQuery, db: Database):
    await call.answer()
    await recent_episodes(call.message, db, telegram_id=call.from_user.id)


@router.callback_query(F.data == "browse:random")
async def browse_random(call: CallbackQuery, db: Database):
    await call.answer()
    await random_anime(call.message, db, telegram_id=call.from_user.id)


@router.message(F.text == "📚 Katalog")
async def catalog(message: Message, db: Database):
    genres = await db.list_genres()
    banner = await _vip_free_banner(db)
    await message.answer(f"{banner}📚 Janr bo'yicha katalog. Janrni tanlang:", reply_markup=kb.genres_menu(genres))


@router.message(F.text == "🎭 Janrlar")
async def genres_list(message: Message, db: Database):
    genres = await db.list_genres()
    banner = await _vip_free_banner(db)
    await message.answer(f"{banner}🎭 Janrni tanlang:", reply_markup=kb.genres_menu(genres))


@router.callback_query(F.data.startswith("search_genre:"))
async def genre_selected(call: CallbackQuery, db: Database, state: FSMContext):
    genre_id = int(call.data.split(":")[1])
    genre = await db.get_genre(genre_id)
    if not genre:
        await call.answer("Janr topilmadi.", show_alert=True)
        return
    if genre["is_vip"] and not await has_vip_access(db, call.from_user.id):
        await call.answer(
            "💎 Bu VIP janr. Ko'rish uchun VIP obuna kerak (👤 Profil → 💎 VIP olish).",
            show_alert=True,
        )
        return
    await state.update_data(genre_id=genre_id)
    rows = await db.list_anime_by_genre(genre_id, page=0, per_page=PER_PAGE)
    if not rows:
        await call.answer("Bu janrda hali anime yo'q.", show_alert=True)
        return
    total_pages = max(1, math.ceil(await db.count_anime_by_genre(genre_id) / PER_PAGE))
    await call.message.answer(
        f"{genre['emoji']} <b>{genre['name']}</b> janridagi animelar:",
        reply_markup=kb.anime_list_keyboard(rows, 0, total_pages, "genre"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("list:"))
async def list_pagination(call: CallbackQuery, db: Database, state: FSMContext):
    _, kind, page_str = call.data.split(":")
    page = int(page_str)
    per_page = PER_PAGE

    if kind == "new":
        rows = await db.list_new_anime(page=page, per_page=per_page)
        title = "🆕 Yangi qo'shilgan animelar:"
        total_pages = max(1, math.ceil(await db.count_published_anime() / per_page))
    elif kind == "popular":
        rows = await db.list_popular_anime(page=page, per_page=per_page)
        title = "🔥 Mashhur animelar:"
        total_pages = max(1, math.ceil(await db.count_published_anime() / per_page))
    elif kind == "genre":
        data = await state.get_data()
        genre_id = data.get("genre_id")
        genre = await db.get_genre(genre_id) if genre_id else None
        rows = await db.list_anime_by_genre(genre_id, page=page, per_page=per_page) if genre_id else []
        title = f"{genre['emoji']} {genre['name']} janridagi animelar:" if genre else "Natijalar:"
        total_pages = max(1, math.ceil((await db.count_anime_by_genre(genre_id) if genre_id else 0) / per_page))
    elif kind == "favorites":
        all_rows = await db.list_favorites(call.from_user.id)
        rows = all_rows[page * per_page:(page + 1) * per_page]
        title = "❤️ Sevimli animelaringiz:"
        total_pages = max(1, math.ceil(len(all_rows) / per_page))
    elif kind == "search_title":
        data = await state.get_data()
        query = data.get("search_query", "")
        all_rows = await db.search_anime_by_title(query, limit=200)
        rows = all_rows[page * per_page:(page + 1) * per_page]
        title = f"🔎 «{query}» bo'yicha natijalar:"
        total_pages = max(1, math.ceil(len(all_rows) / per_page))
    else:
        rows = []
        title = "Natijalar:"
        total_pages = 1

    if not rows and page > 0:
        await call.answer("Boshqa natija yo'q.", show_alert=True)
        return

    try:
        await call.message.edit_text(title, reply_markup=kb.anime_list_keyboard(rows, page, total_pages, kind))
    except TelegramBadRequest:
        await call.message.answer(title, reply_markup=kb.anime_list_keyboard(rows, page, total_pages, kind))
    await call.answer()


# ------------------------------------------------------------------ #
# Anime detali
# ------------------------------------------------------------------ #
async def show_anime_detail(message: Message, db: Database, anime_id: int, viewer_telegram_id: int, edit: bool = False):
    anime = await db.get_anime(anime_id)
    if not anime:
        await message.answer("Bu anime topilmadi (o'chirilgan bo'lishi mumkin).")
        return

    if anime["is_vip"] and not await has_vip_access(db, viewer_telegram_id):
        text = (
            f"💎 <b>{anime['title']}</b>\n\n"
            "Bu anime VIP foydalanuvchilar uchun mo'ljallangan.\n"
            "Ko'rish uchun 👤 Profil → 💎 VIP olish orqali VIP xarid qiling."
        )
        await message.answer(text, reply_markup=kb.profile_keyboard())
        return

    ep_count = await db.count_episodes(anime_id)
    is_fav = await db.is_favorite(anime_id, viewer_telegram_id)
    is_following = await db.is_following(anime_id, viewer_telegram_id)
    seasons = await db.list_seasons(anime_id)
    has_seasons = bool(seasons)

    # Agar anime fasllarsiz va atigi 1 qismdan iborat bo'lsa (masalan, film) —
    # "1-fasl"/"1-qism" kabi keraksiz oraliq qadam ko'rsatilmaydi: tugma
    # to'g'ridan-to'g'ri videoni ochadi (mavjud watch: oqimi orqali).
    single_episode_id = await _single_episode_id(db, anime_id, has_seasons)

    caption = await build_anime_card_text(db, anime)
    markup = kb.anime_detail_keyboard(anime_id, is_fav, is_following, has_seasons, single_episode_id)
    if anime["poster_file_id"]:
        await message.answer_photo(anime["poster_file_id"], caption=caption, reply_markup=markup)
    else:
        await message.answer(caption, reply_markup=markup)


@router.callback_query(F.data.startswith("seasons:"))
async def show_seasons(call: CallbackQuery, db: Database):
    anime_id = int(call.data.split(":")[1])
    anime = await db.get_anime(anime_id)
    if not anime:
        await call.answer("Anime topilmadi.", show_alert=True)
        return
    if anime["is_vip"] and not await has_vip_access(db, call.from_user.id):
        await call.answer("💎 Bu VIP anime. Ko'rish uchun VIP kerak.", show_alert=True)
        return
    seasons = await db.list_seasons(anime_id)
    if not seasons:
        await call.answer("Fasllar topilmadi.", show_alert=True)
        return
    text = f"🎬 <b>{anime['title']}</b>\nFaslni tanlang:"
    markup = kb.seasons_keyboard(anime_id, seasons)
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("follow:"))
async def toggle_follow_cb(call: CallbackQuery, db: Database):
    anime_id = int(call.data.split(":")[1])
    following = await db.toggle_follow(anime_id, call.from_user.id)
    await call.answer("🔔 Kuzatishga qo'shildingiz." if following else "🔕 Kuzatish bekor qilindi.")
    anime = await db.get_anime(anime_id)
    if not anime:
        return
    is_fav = await db.is_favorite(anime_id, call.from_user.id)
    seasons = await db.list_seasons(anime_id)
    single_episode_id = await _single_episode_id(db, anime_id, bool(seasons))
    try:
        await call.message.edit_reply_markup(
            reply_markup=kb.anime_detail_keyboard(anime_id, is_fav, following, bool(seasons), single_episode_id)
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("anime:"))
async def anime_detail_cb(call: CallbackQuery, db: Database):
    anime_id = int(call.data.split(":")[1])
    await show_anime_detail(call.message, db, anime_id, call.from_user.id)
    await call.answer()


# ------------------------------------------------------------------ #
# Sevimlilar
# ------------------------------------------------------------------ #
@router.callback_query(F.data.startswith("fav:"))
async def toggle_fav(call: CallbackQuery, db: Database):
    anime_id = int(call.data.split(":")[1])
    added = await db.toggle_favorite(anime_id, call.from_user.id)
    await call.answer("❤️ Sevimlilarga qo'shildi!" if added else "💔 Sevimlilardan olib tashlandi.")
    anime = await db.get_anime(anime_id)
    if not anime:
        return
    is_fav = await db.is_favorite(anime_id, call.from_user.id)
    is_following = await db.is_following(anime_id, call.from_user.id)
    seasons = await db.list_seasons(anime_id)
    single_episode_id = await _single_episode_id(db, anime_id, bool(seasons))
    try:
        await call.message.edit_reply_markup(
            reply_markup=kb.anime_detail_keyboard(anime_id, is_fav, is_following, bool(seasons), single_episode_id)
        )
    except TelegramBadRequest:
        pass


@router.message(F.text == "❤️ Sevimlilar")
async def favorites_menu(message: Message, db: Database):
    rows = await db.list_favorites(message.from_user.id)
    if not rows:
        await message.answer("❤️ Sevimlilar ro'yxati hozircha bo'sh.")
        return
    page_rows = rows[:PER_PAGE]
    total_pages = max(1, math.ceil(len(rows) / PER_PAGE))
    await message.answer(
        "❤️ Sevimli animelaringiz:",
        reply_markup=kb.anime_list_keyboard(page_rows, 0, total_pages, "favorites"),
    )


# ------------------------------------------------------------------ #
# Ko'rish tarixi
# ------------------------------------------------------------------ #
@router.message(F.text == "🕐 Ko'rish tarixi")
async def history_menu(message: Message, db: Database):
    rows = await db.list_watch_history(message.from_user.id, limit=PER_PAGE)
    if not rows:
        await message.answer("🕐 Ko'rish tarixingiz hozircha bo'sh.")
        return
    lines = ["🕐 <b>Ko'rish tarixi</b>\n"]
    for r in rows:
        season_txt = f" {r['season_number']}-fasl," if r["season_number"] else ""
        lines.append(f"🎬 {r['title']} —{season_txt} {r['episode_number']}-qism")
    await message.answer("\n".join(lines), reply_markup=kb.history_keyboard(rows))


# ------------------------------------------------------------------ #
# Reyting
# ------------------------------------------------------------------ #
@router.callback_query(F.data.startswith("rate_open:"))
async def rate_open(call: CallbackQuery, db: Database):
    anime_id = int(call.data.split(":")[1])
    if await db.has_rated(anime_id, call.from_user.id):
        await call.answer("Siz bu animega allaqachon baho bergansiz.", show_alert=True)
        return
    await call.message.answer("Animeni baholang:", reply_markup=kb.rating_keyboard(anime_id))
    await call.answer()


@router.callback_query(F.data.startswith("rate:"))
async def rate_submit(call: CallbackQuery, db: Database):
    _, anime_id_str, score_str = call.data.split(":")
    anime_id, score = int(anime_id_str), int(score_str)
    await db.rate_anime(anime_id, call.from_user.id, score)
    try:
        await call.message.edit_text(f"✅ Bahoyingiz qabul qilindi: {score}⭐")
    except TelegramBadRequest:
        await call.message.answer(f"✅ Bahoyingiz qabul qilindi: {score}⭐")
    await call.answer("Rahmat!")


# ------------------------------------------------------------------ #
# Qismlar / video ko'rish
# ------------------------------------------------------------------ #
@router.callback_query(F.data.startswith("episodes:"))
async def show_episodes(call: CallbackQuery, db: Database):
    _, anime_id_str, season_token, page_str = call.data.split(":")
    anime_id, page = int(anime_id_str), int(page_str)
    season_id = None if season_token == "0" else int(season_token)
    anime = await db.get_anime(anime_id)
    if not anime:
        await call.answer("Anime topilmadi.", show_alert=True)
        return
    if anime["is_vip"] and not await has_vip_access(db, call.from_user.id):
        await call.answer("💎 Bu VIP anime. Ko'rish uchun VIP kerak.", show_alert=True)
        return
    total = await db.count_episodes_in_season(anime_id, season_id)
    if total == 0:
        await call.answer("Hali qismlar qo'shilmagan.", show_alert=True)
        return
    episodes = await db.list_episodes_page(anime_id, page, season_id)
    season_label = ""
    if season_id:
        season = await db.get_season(season_id)
        if season:
            season_label = f" — {season['season_number']}-fasl"
    text = f"🎬 <b>{anime['title']}</b>{season_label}\nQism raqamini tanlang ({total} ta qism):"
    markup = kb.episodes_keyboard(anime_id, episodes, page, total, season_token)
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=markup)
    await call.answer()


async def _send_episode(db: Database, bot: Bot, telegram_id: int, anime, episode) -> None:
    """Video yuborish + ko'rish tarixi/progressni saqlash + (kerak bo'lsa) baholash taklifi."""
    season_txt = ""
    season = await db.get_season(episode["season_id"]) if episode["season_id"] else None
    if season:
        season_txt = f" {season['season_number']}-fasl,"
    await bot.send_video(
        chat_id=telegram_id,
        video=episode["video_file_id"],
        caption=f"🎬 {anime['title']} —{season_txt} {episode['episode_number']}-qism",
        protect_content=bool(anime["is_vip"]),
    )
    await db.log_watch(telegram_id, anime["id"], episode["id"])
    await db.set_watch_progress(telegram_id, anime["id"], episode["id"])

    # Baholash FAQAT animening eng oxirgi qismi (barcha fasllar bo'yicha haqiqiy
    # oxirgisi, fasl oxiri emas) tomosha qilingandan keyin chiqadi.
    # get_next_episode() fasldan-faslga to'g'ri o'tadi, shuning uchun bu yerda
    # "keyingi qism yo'q" = "bu animening haqiqiy oxirgi qismi" degani.
    next_ep = await db.get_next_episode(anime["id"], episode["id"])
    is_final_episode = next_ep is None
    if is_final_episode and not await db.has_rated(anime["id"], telegram_id):
        await bot.send_message(
            telegram_id,
            "Ushbu animeni baholashni unutmang 👇",
            reply_markup=kb.post_watch_rate_keyboard(anime["id"]),
        )


@router.callback_query(F.data.startswith("watch:"))
async def watch_episode(call: CallbackQuery, db: Database, bot: Bot):
    episode_id = int(call.data.split(":")[1])
    episode = await db.get_episode(episode_id)
    if not episode:
        await call.answer("Video topilmadi.", show_alert=True)
        return
    anime = await db.get_anime(episode["anime_id"])
    if not anime:
        await call.answer("Anime topilmadi.", show_alert=True)
        return
    if anime["is_vip"] and not await has_vip_access(db, call.from_user.id):
        await call.answer("💎 Bu VIP anime. Ko'rish uchun VIP kerak.", show_alert=True)
        return
    await _send_episode(db, bot, call.from_user.id, anime, episode)
    await call.answer()


@router.callback_query(F.data.startswith("continue_watch:"))
async def continue_watch(call: CallbackQuery, db: Database, bot: Bot):
    anime_id = int(call.data.split(":")[1])
    anime = await db.get_anime(anime_id)
    if not anime:
        await call.answer("Anime topilmadi.", show_alert=True)
        return
    if anime["is_vip"] and not await has_vip_access(db, call.from_user.id):
        await call.answer("💎 Bu VIP anime. Ko'rish uchun VIP kerak.", show_alert=True)
        return
    progress = await db.get_watch_progress_for_anime(call.from_user.id, anime_id)
    if not progress:
        await call.answer("Bu anime bo'yicha ko'rish tarixi topilmadi.", show_alert=True)
        return
    next_ep = await db.get_next_episode(anime_id, progress["episode_id"])
    target_ep = next_ep or await db.get_episode(progress["episode_id"])
    if not target_ep:
        await call.answer("Qism topilmadi.", show_alert=True)
        return
    await _send_episode(db, bot, call.from_user.id, anime, target_ep)
    await call.answer()


# ------------------------------------------------------------------ #
# Profil
# ------------------------------------------------------------------ #
@router.message(F.text == "👤 Profil")
async def profile(message: Message, db: Database):
    user = await ensure_user(db, message.from_user)
    is_vip = await db.is_vip(message.from_user.id)
    favs = await db.list_favorites(message.from_user.id)
    history = await db.list_watch_history(message.from_user.id, limit=1000)
    status = "💎 VIP" if is_vip else "👤 Oddiy foydalanuvchi"
    vip_until_txt = ""
    if is_vip and user["vip_until"]:
        vip_until_txt = f"\n⏳ VIP tugash sanasi: {user['vip_until'][:10]}"

    username_line = f"🔗 Username: @{user['username']}\n" if user["username"] else "🔗 Username: —\n"
    text = (
        f"👤 <b>Profil</b>\n\n"
        f"🆔 ID: <code>{user['telegram_id']}</code>\n"
        f"👨‍💼 Ism: {user['full_name']}\n"
        f"{username_line}"
    )
    text += (
        f"📊 Status: {status}{vip_until_txt}\n"
        f"💰 Balans: {fmt_number(user['balance'])} so'm\n"
        f"❤️ Sevimlilar: {len(favs)} ta\n"
        f"📚 Ko'rilganlar: {len(history)} ta"
    )
    await message.answer(text, reply_markup=kb.profile_keyboard())


# ------------------------------------------------------------------ #
# VIP sotib olish
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "vip_open")
async def vip_open(call: CallbackQuery, db: Database):
    if await db.is_vip(call.from_user.id):
        await call.answer("Siz allaqachon VIP foydalanuvchisiz 💎", show_alert=True)
        return
    prices = {
        1: await db.get_setting("vip_price_1", "0"),
        2: await db.get_setting("vip_price_2", "0"),
        3: await db.get_setting("vip_price_3", "0"),
    }
    await call.message.answer("💎 <b>VIP — cheklovlarsiz kirish</b>\n\nMuddatni tanlang:",
                               reply_markup=kb.vip_menu(prices))
    await call.answer()


@router.callback_query(F.data.startswith("vip_buy:"))
async def vip_buy(call: CallbackQuery, db: Database, state: FSMContext):
    months = int(call.data.split(":")[1])
    price = await db.get_setting(f"vip_price_{months}", "0")
    card_number = await db.get_setting("payment_card_number", "—")
    card_holder = await db.get_setting("payment_card_holder", "—")

    await state.set_state(VipPaymentStates.waiting_screenshot)
    await state.update_data(vip_months=months, vip_price=price)

    text = (
        f"💳 <b>{months} oylik VIP — {fmt_number(price)} so'm</b>\n\n"
        f"To'lovni quyidagi kartaga amalga oshiring:\n"
        f"💳 Karta: <code>{card_number}</code>\n"
        f"👤 Egasi: {card_holder}\n\n"
        f"To'lovni amalga oshirgach, chek (screenshot) rasmini shu yerga yuboring 📸"
    )
    await call.message.answer(text, reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(VipPaymentStates.waiting_screenshot, F.photo)
async def vip_receive_screenshot(message: Message, db: Database, state: FSMContext, bot: Bot):
    data = await state.get_data()
    months = data.get("vip_months")
    price = data.get("vip_price", "0")
    await state.clear()

    screenshot_file_id = message.photo[-1].file_id
    payment_id = await db.create_pending_payment(message.from_user.id, months, int(price or 0), screenshot_file_id)

    user = await ensure_user(db, message.from_user)
    await message.answer(
        "✅ Chekingiz qabul qilindi. Admin tasdiqlagach VIP faollashadi. Iltimos kuting.",
        reply_markup=kb.main_menu(is_admin=bool(user["is_admin"])),
    )

    admins_cur = await db.conn.execute("SELECT telegram_id FROM users WHERE is_admin=1")
    admin_ids = [r["telegram_id"] for r in await admins_cur.fetchall()]
    caption = (
        f"💳 <b>Yangi VIP to'lov</b>\n\n"
        f"👤 Foydalanuvchi: {message.from_user.full_name} (@{message.from_user.username or '—'})\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"📦 Paket: {months} oylik\n"
        f"💰 Narx: {fmt_number(price)} so'm"
    )
    for admin_id in admin_ids:
        try:
            await bot.send_photo(
                admin_id, screenshot_file_id, caption=caption,
                reply_markup=kb.vip_payment_confirm_keyboard(payment_id),
            )
        except Exception:
            logger.exception("Adminga to'lov xabari yuborilmadi: %s", admin_id)


@router.message(VipPaymentStates.waiting_screenshot)
async def vip_screenshot_wrong_type(message: Message):
    await message.answer("📸 Iltimos, to'lov chekining rasmini (screenshot) yuboring.")


# ------------------------------------------------------------------ #
# Yordam
# ------------------------------------------------------------------ #
@router.message(F.text == "🆘 Yordam")
async def help_menu(message: Message, db: Database):
    text = await db.get_setting("help_text")
    admin_username = await db.get_setting("help_admin_username")
    full = text
    if admin_username:
        full += f"\n\n📢 Reklama va murojaat uchun\n👤 Admin: @{admin_username.lstrip('@')}"
    await message.answer(full)
