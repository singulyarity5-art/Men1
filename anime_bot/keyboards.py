"""Test2 Bot — barcha klaviaturalar (reply va inline) shu yerda to'plangan."""
from __future__ import annotations

import math

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config

# ---------------------------------------------------------------------- #
# Reply (asosiy menyu) klaviaturalar
# ---------------------------------------------------------------------- #

def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🎬 Anime ko'rish")],
        [KeyboardButton(text="📚 Katalog"), KeyboardButton(text="🆕 Yangi animelar")],
        [KeyboardButton(text="🔥 Mashhur animelar"), KeyboardButton(text="🔥 Yangi qismlar")],
        [KeyboardButton(text="❤️ Sevimlilar"), KeyboardButton(text="🎭 Janrlar")],
        [KeyboardButton(text="🕐 Ko'rish tarixi")],
        [KeyboardButton(text="👤 Profil"), KeyboardButton(text="🆘 Yordam")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Admin panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def anime_browse_hub_keyboard() -> InlineKeyboardMarkup:
    """
    '🎬 Anime ko'rish' bosilganda chiqadigan markaz: 🎲 Tasodifiy Anime shu yerga
    ko'chirildi (asosiy menyuda alohida tugma sifatida endi yo'q), qolgan mavjud
    anime ko'rish funksiyalariga ham qulay kirish uchun.
    """
    b = InlineKeyboardBuilder()
    b.button(text="🔎 Anime qidirish", callback_data="browse:search")
    b.button(text="📚 Katalog", callback_data="browse:catalog")
    b.button(text="🎭 Janrlar", callback_data="browse:genres")
    b.button(text="🆕 Yangi animelar", callback_data="browse:new")
    b.button(text="🔥 Mashhur animelar", callback_data="browse:popular")
    b.button(text="🔥 Yangi qismlar", callback_data="browse:recent_episodes")
    b.button(text="🎲 Tasodifiy Anime", callback_data="browse:random")
    b.adjust(1)
    return b.as_markup()


def admin_back_to_user_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="👤 Foydalanuvchi paneliga qaytish")]],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------- #
# Qidiruv
# ---------------------------------------------------------------------- #

def search_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔤 Nom bo'yicha", callback_data="search:title")
    b.button(text="🆔 Anime ID bo'yicha", callback_data="search:code")
    b.button(text="⭐ Eng yuqori baholangan 10 ta", callback_data="search:top10")
    b.adjust(1)
    return b.as_markup()


# ---------------------------------------------------------------------- #
# Janrlar
# ---------------------------------------------------------------------- #

def genres_menu(genres, selected_ids: set[int] | None = None, for_admin_add: bool = False) -> InlineKeyboardMarkup:
    """
    genres — Database.list_genres() natijasi (VIP janrlar avval keladi).
    selected_ids — anime qo'shishda tanlangan janrlarni belgilash uchun.

    Dizayn:
      - Eng tepada VIP janrlar — har biri alohida qatorda (1 tadan),
        nomining ham boshida, ham oxirida 💎 belgisi bilan.
      - Pastda qolgan barcha oddiy janrlar (Triller ham shu qatorda) —
        2 tadan qilib joylashtiriladi.
    """
    selected_ids = selected_ids or set()
    vip_genres = [g for g in genres if g["is_vip"]]
    normal_genres = [g for g in genres if not g["is_vip"]]
    prefix = "pick_genre" if for_admin_add else "search_genre"

    b = InlineKeyboardBuilder()
    for g in vip_genres:
        mark = "✅ " if g["id"] in selected_ids else ""
        b.button(text=f"{mark}💎 {g['name']} 💎", callback_data=f"{prefix}:{g['id']}")
    for g in normal_genres:
        mark = "✅ " if g["id"] in selected_ids else ""
        b.button(text=f"{mark}{g['emoji']} {g['name']}", callback_data=f"{prefix}:{g['id']}")

    sizes = [1] * len(vip_genres) + [2]
    b.adjust(*sizes)

    if for_admin_add:
        b.row(InlineKeyboardButton(text="✅ Tayyor", callback_data="pick_genre:done"))
    return b.as_markup()


# ---------------------------------------------------------------------- #
# Anime kartasi / ro'yxatlar
# ---------------------------------------------------------------------- #

def anime_list_keyboard(anime_rows, page: int, total_pages: int, list_kind: str) -> InlineKeyboardMarkup:
    """list_kind: 'new' | 'popular' | 'genre:<id>' | 'favorites' | 'history' | 'search'"""
    b = InlineKeyboardBuilder()
    for a in anime_rows:
        b.button(text=f"{a['title']} (ID: {a['anime_code']})", callback_data=f"anime:{a['id']}")
    b.adjust(1)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"list:{list_kind}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"list:{list_kind}:{page+1}"))
        b.row(*nav)
    return b.as_markup()


def anime_detail_keyboard(
    anime_id: int,
    is_favorite: bool,
    is_following: bool,
    has_seasons: bool = False,
    single_episode_id: int | None = None,
) -> InlineKeyboardMarkup:
    """
    Eslatma: "⭐ Baholash" tugmasi endi bu yerda YO'Q — u endi foydalanuvchi biror
    qismni ochib ko'rgandan KEYIN chiqadi (qarang: post_watch_rate_keyboard).

    single_episode_id — agar anime fasllarsiz va atigi 1 qismdan iborat bo'lsa
    (film), "qismlar ro'yxati" bosqichi o'tkazib yuborilib, to'g'ridan-to'g'ri
    video ochiladigan qilib beriladi.
    """
    b = InlineKeyboardBuilder()
    if has_seasons:
        b.button(text="🎬 Fasllarni ko'rish", callback_data=f"seasons:{anime_id}")
    elif single_episode_id:
        b.button(text="▶️ Ko'rish", callback_data=f"watch:{single_episode_id}")
    else:
        b.button(text="▶️ Qismlarni ko'rish", callback_data=f"episodes:{anime_id}:0:0")
    fav_text = "💔 Sevimlilardan olib tashlash" if is_favorite else "❤️ Sevimlilarga qo'shish"
    b.button(text=fav_text, callback_data=f"fav:{anime_id}")
    follow_text = "🔕 Kuzatishni to'xtatish" if is_following else "🔔 Kuzatish"
    b.button(text=follow_text, callback_data=f"follow:{anime_id}")
    b.adjust(1)
    return b.as_markup()


def post_watch_rate_keyboard(anime_id: int) -> InlineKeyboardMarkup:
    """Qism yuborilgandan keyin chiqadigan yagona '⭐ Baholash' tugmasi."""
    b = InlineKeyboardBuilder()
    b.button(text="⭐ Baholash", callback_data=f"rate_open:{anime_id}")
    return b.as_markup()


def seasons_keyboard(anime_id: int, seasons) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in seasons:
        b.button(
            text=f"📁 {s['season_number']}-fasl ({s['episode_count']} qism)",
            callback_data=f"episodes:{anime_id}:{s['id']}:0",
        )
    b.adjust(1)
    b.row(InlineKeyboardButton(text="⬅️ Anime sahifasiga", callback_data=f"anime:{anime_id}"))
    return b.as_markup()


def continue_watching_keyboard(anime_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Davom ettirish", callback_data=f"continue_watch:{anime_id}")
    return b.as_markup()


def history_keyboard(rows) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rows:
        b.button(text=f"▶️ {r['title']}", callback_data=f"continue_watch:{r['id']}")
    b.adjust(1)
    return b.as_markup()


def recent_episodes_keyboard(rows) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rows:
        season_txt = f" {r['season_number']}-fasl," if r["season_number"] else ""
        b.button(
            text=f"🔥 {r['anime_title']}{season_txt} {r['episode_number']}-qism",
            callback_data=f"watch:{r['id']}",
        )
    b.adjust(1)
    return b.as_markup()


def new_episode_notify_keyboard(episode_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Ko'rish", callback_data=f"watch:{episode_id}")
    return b.as_markup()


def rating_keyboard(anime_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        b.button(text=f"{i}⭐", callback_data=f"rate:{anime_id}:{i}")
    for i in range(6, 11):
        b.button(text=f"{i}⭐", callback_data=f"rate:{anime_id}:{i}")
    b.adjust(5, 5)
    return b.as_markup()


def episode_upload_keyboard() -> InlineKeyboardMarkup:
    """Qism (video) yuklash jarayonida ko'rsatiladigan ✅ Tayyor / ❌ Bekor qilish tugmalari."""
    b = InlineKeyboardBuilder()
    b.button(text="🟡 Filler qo'shish (video kerak emas)", callback_data="adm:episodes_filler")
    b.button(text="✅ Tayyor", callback_data="adm:episodes_done")
    b.button(text="❌ Bekor qilish", callback_data="adm:episodes_cancel")
    b.adjust(1, 2)
    return b.as_markup()


def episode_filler_back_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Orqaga", callback_data="adm:episodes_filler_back")
    return b.as_markup()


def episodes_keyboard(anime_id: int, episodes, page: int, total_episodes: int, season_token: str = "0") -> InlineKeyboardMarkup:
    """season_token: "0" = fasllarsiz (oddiy) anime, aks holda season_id (str)."""
    b = InlineKeyboardBuilder()
    for ep in episodes:
        if ep["is_filler"]:
            continue  # filler qismda video yo'q — tugma ko'rsatilmaydi, matnda "filler" deb yoziladi
        b.button(text=str(ep["episode_number"]), callback_data=f"watch:{ep['id']}")
    b.adjust(config.EPISODE_BUTTONS_COLUMNS)

    total_pages = max(1, math.ceil(total_episodes / config.EPISODES_PER_PAGE))
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"episodes:{anime_id}:{season_token}:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="🔜", callback_data=f"episodes:{anime_id}:{season_token}:{page+1}"))
        b.row(*nav)
    if season_token != "0":
        b.row(InlineKeyboardButton(text="⬅️ Fasllar", callback_data=f"seasons:{anime_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Anime sahifasiga", callback_data=f"anime:{anime_id}"))
    return b.as_markup()


# ---------------------------------------------------------------------- #
# VIP
# ---------------------------------------------------------------------- #

def vip_menu(prices: dict[int, str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"1 oylik — {prices.get(1, '?')} so'm", callback_data="vip_buy:1")
    b.button(text=f"2 oylik — {prices.get(2, '?')} so'm", callback_data="vip_buy:2")
    b.button(text=f"3 oylik — {prices.get(3, '?')} so'm", callback_data="vip_buy:3")
    b.adjust(1)
    return b.as_markup()


def vip_payment_confirm_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash", callback_data=f"pay_approve:{payment_id}")
    b.button(text="❌ Rad etish", callback_data=f"pay_reject:{payment_id}")
    b.adjust(2)
    return b.as_markup()


def grant_vip_keyboard(user_telegram_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 1 oylik VIP", callback_data=f"grant_vip:{user_telegram_id}:1")
    b.button(text="💎 2 oylik VIP", callback_data=f"grant_vip:{user_telegram_id}:2")
    b.button(text="💎 3 oylik VIP", callback_data=f"grant_vip:{user_telegram_id}:3")
    b.adjust(1)
    return b.as_markup()


# ---------------------------------------------------------------------- #
# Majburiy obuna
# ---------------------------------------------------------------------- #

def subscribe_keyboard(channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        chat_id = ch["chat_id"]
        title = ch["title"] or chat_id
        invite_link = ch["invite_link"] if "invite_link" in ch.keys() else None

        if chat_id.startswith("@"):
            link = f"https://t.me/{chat_id.lstrip('@')}"
        elif chat_id.startswith("http"):
            link = chat_id
        elif invite_link:
            # -100... ko'rinishidagi ID orqali qo'shilgan kanal — faqat oldindan
            # yaratilgan haqiqiy taklif linki mavjud bo'lsagina tugma qo'yamiz.
            link = invite_link
        else:
            # Taklif linki yo'q — ishlamaydigan havola yasashdan ko'ra, tugmani
            # umuman qo'ymay, kanal nomini oddiy noop qatorida ko'rsatamiz.
            b.button(text=f"⚠️ {title} (admin bilan bog'laning)", callback_data="noop")
            continue

        b.button(text=f"📢 {title}", url=link)
    b.adjust(1)
    b.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subs"))
    b.row(InlineKeyboardButton(text="💎 VIP olish", callback_data="vip_open"))
    return b.as_markup()


# ---------------------------------------------------------------------- #
# Profil
# ---------------------------------------------------------------------- #

def profile_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 VIP olish", callback_data="vip_open")
    b.adjust(1)
    return b.as_markup()


# ---------------------------------------------------------------------- #
# Admin panel
# ---------------------------------------------------------------------- #

def admin_panel_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Anime qo'shish", callback_data="adm:add_anime")
    b.button(text="🎬 Animelar ro'yxati", callback_data="adm:anime_list:0")
    b.button(text="📚 Mavjud animega fasl qo'shish", callback_data="adm:season_pick:0")
    b.button(text="👥 Foydalanuvchilar", callback_data="adm:users:0")
    b.button(text="📊 Statistika", callback_data="adm:stats")
    b.button(text="📢 Reklama", callback_data="adm:broadcast")
    b.button(text="📢 Majburiy kanallar", callback_data="adm:channels")
    b.button(text="💰 VIP narxlari", callback_data="adm:vip_prices")
    b.button(text="🎁 VIP'ni vaqtincha bepul qilish", callback_data="adm:vip_free_menu")
    b.button(text="💳 To'lov ma'lumotlari", callback_data="adm:payment_info")
    b.button(text="🖼 /start rasm/matn", callback_data="adm:start_settings")
    b.button(text="🆘 Yordam matni", callback_data="adm:help_settings")
    b.button(text="💾 Zaxira nusxa (Backup)", callback_data="adm:backup_menu")
    b.adjust(2)
    return b.as_markup()


def admin_back_button(target: str = "adm:panel") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Orqaga", callback_data=target)
    return b.as_markup()


def vip_granted_all_keyboard() -> InlineKeyboardMarkup:
    """'🎉 Barcha foydalanuvchilarga VIP berildi!' xabari ostidagi tugmalar."""
    b = InlineKeyboardBuilder()
    b.button(text="💎 VIP animelarga kirish", callback_data="browse:catalog")
    b.button(text="🎬 Anime ko'rish", callback_data="browse:hub")
    b.adjust(1)
    return b.as_markup()


def vip_free_menu(active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📅 1 hafta bepul", callback_data="adm:vip_free_set:7")
    b.button(text="📅 2 hafta bepul", callback_data="adm:vip_free_set:14")
    b.button(text="📅 1 oy bepul", callback_data="adm:vip_free_set:30")
    b.adjust(1)
    if active:
        b.row(InlineKeyboardButton(text="🛑 Bepul rejimni to'xtatish", callback_data="adm:vip_free_stop"))
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:panel"))
    return b.as_markup()


def vip_prices_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ 1 oylik narxni o'zgartirish", callback_data="adm:set_price:1")
    b.button(text="✏️ 2 oylik narxni o'zgartirish", callback_data="adm:set_price:2")
    b.button(text="✏️ 3 oylik narxni o'zgartirish", callback_data="adm:set_price:3")
    b.button(text="⬅️ Orqaga", callback_data="adm:panel")
    b.adjust(1)
    return b.as_markup()


def payment_info_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Karta raqamini o'zgartirish", callback_data="adm:set_card_number")
    b.button(text="✏️ Karta egasini o'zgartirish", callback_data="adm:set_card_holder")
    b.button(text="⬅️ Orqaga", callback_data="adm:panel")
    b.adjust(1)
    return b.as_markup()


def start_settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Matnni o'zgartirish", callback_data="adm:set_start_text")
    b.button(text="🖼 Rasmni o'zgartirish", callback_data="adm:set_start_photo")
    b.button(text="⬅️ Orqaga", callback_data="adm:panel")
    b.adjust(1)
    return b.as_markup()


def help_settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Yordam matnini o'zgartirish", callback_data="adm:set_help_text")
    b.button(text="✏️ Admin usernameni o'zgartirish", callback_data="adm:set_help_admin")
    b.button(text="⬅️ Orqaga", callback_data="adm:panel")
    b.adjust(1)
    return b.as_markup()


def channels_menu(channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.button(text=f"❌ {ch['title'] or ch['chat_id']}", callback_data=f"adm:del_channel:{ch['id']}")
    b.button(text="➕ Kanal qo'shish", callback_data="adm:add_channel")
    b.button(text="⬅️ Orqaga", callback_data="adm:panel")
    b.adjust(1)
    return b.as_markup()


def admin_anime_list_keyboard(anime_rows, page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for a in anime_rows:
        b.button(text=f"{a['title']} (ID:{a['anime_code']})", callback_data=f"adm:anime:{a['id']}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:anime_list:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="🔜", callback_data=f"adm:anime_list:{page+1}"))
    if total_pages > 1:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:panel"))
    return b.as_markup()


def admin_anime_detail_keyboard(anime_id: int, has_seasons: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_seasons:
        b.button(text="📚 Fasllarni boshqarish", callback_data=f"adm:seasons_of:{anime_id}")
    else:
        b.button(text="➕ Qism qo'shish (video yuborish)", callback_data=f"adm:add_episode:{anime_id}")
    b.button(text="✏️ Nomi", callback_data=f"adm:edit_title:{anime_id}")
    b.button(text="✏️ Tavsifi", callback_data=f"adm:edit_desc:{anime_id}")
    b.button(text="✏️ Davlat", callback_data=f"adm:edit_country:{anime_id}")
    b.button(text="✏️ Yil", callback_data=f"adm:edit_year:{anime_id}")
    b.button(text="✏️ Til", callback_data=f"adm:edit_language:{anime_id}")
    b.button(text="🎭 Janrlarni o'zgartirish", callback_data=f"adm:edit_genres:{anime_id}")
    b.button(text="📢 Kanalga e'lon qilish", callback_data=f"adm:announce:{anime_id}")
    b.button(text="🗑 O'chirish", callback_data=f"adm:delete_anime_confirm:{anime_id}")
    b.button(text="⬅️ Orqaga", callback_data="adm:anime_list:0")
    b.adjust(1)
    return b.as_markup()


def admin_pick_anime_for_season_keyboard(anime_rows, page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for a in anime_rows:
        b.button(text=f"{a['title']} (ID:{a['anime_code']})", callback_data=f"adm:season_pick_anime:{a['id']}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:season_pick:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="🔜", callback_data=f"adm:season_pick:{page+1}"))
    if total_pages > 1:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:panel"))
    return b.as_markup()


def admin_seasons_keyboard(anime_id: int, seasons) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in seasons:
        b.button(
            text=f"📁 {s['season_number']}-fasl ({s['episode_count']} qism)",
            callback_data=f"adm:season:{s['id']}",
        )
    b.adjust(1)
    b.row(InlineKeyboardButton(text="➕ Yangi fasl qo'shish", callback_data=f"adm:add_season:{anime_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Anime sahifasiga", callback_data=f"adm:anime:{anime_id}"))
    return b.as_markup()


def admin_season_detail_keyboard(season_id: int, anime_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Qism qo'shish", callback_data=f"adm:add_episode_season:{season_id}")
    b.button(text="⬅️ Fasllarga qaytish", callback_data=f"adm:seasons_of:{anime_id}")
    b.adjust(1)
    return b.as_markup()


def confirm_delete_keyboard(anime_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, o'chirish", callback_data=f"adm:delete_anime:{anime_id}")
    b.button(text="❌ Bekor qilish", callback_data=f"adm:anime:{anime_id}")
    b.adjust(2)
    return b.as_markup()


def admin_users_list_keyboard(users, page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        name = u["full_name"] or "Noma'lum"
        b.button(text=f"{name} (ID:{u['telegram_id']})", callback_data=f"adm:user:{u['telegram_id']}")
    b.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:users:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="🔜", callback_data=f"adm:users:{page+1}"))
    if total_pages > 1:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="adm:panel"))
    return b.as_markup()


def admin_user_detail_keyboard(telegram_id: int, is_admin_flag: bool, is_vip_flag: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 VIP berish", callback_data=f"adm:grant_vip_menu:{telegram_id}")
    if is_vip_flag:
        b.button(text="❌ VIP'ni bekor qilish", callback_data=f"adm:revoke_vip:{telegram_id}")
    if is_admin_flag:
        b.button(text="👤 Admin huquqini olib tashlash", callback_data=f"adm:revoke_admin:{telegram_id}")
    else:
        b.button(text="🛡 Admin qilish", callback_data=f"adm:make_admin:{telegram_id}")
    b.button(text="⬅️ Orqaga", callback_data="adm:users:0")
    b.adjust(1)
    return b.as_markup()


def backup_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💾 Zaxira olish", callback_data="adm:backup_export")
    b.button(text="📥 Zaxiradan tiklash", callback_data="adm:backup_import")
    b.button(text="⬅️ Orqaga", callback_data="adm:panel")
    b.adjust(1)
    return b.as_markup()


def confirm_restore_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, tiklash", callback_data="adm:backup_import_confirm")
    b.button(text="❌ Bekor qilish", callback_data="adm:backup_import_cancel")
    b.adjust(2)
    return b.as_markup()


def broadcast_control_keyboard(broadcast_id: int, paused: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if paused:
        b.button(text="▶️ Davom ettirish", callback_data=f"adm:bc_resume:{broadcast_id}")
    else:
        b.button(text="⏸ To'xtatish", callback_data=f"adm:bc_pause:{broadcast_id}")
    return b.as_markup()
