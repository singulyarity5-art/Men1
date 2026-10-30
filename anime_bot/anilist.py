"""
AniList (https://anilist.co) dan anime ma'lumotlarini olish: qidiruv va keyingi qism chiqish vaqti.
Bepul, API kalit kerak emas. Ulanish xatosi bo'lsa bot ishlashda davom etadi (faqat avto-to'ldirish ishlamaydi).
"""
from __future__ import annotations

import datetime
import html
import logging
import re
import time
from typing import Any, Optional

import aiohttp

import config

logger = logging.getLogger("anime_bot.anilist")

API_URL = "https://graphql.anilist.co"

SEARCH_QUERY = """
query ($search: String, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english native }
      description(asHtml: false)
      genres
      format
      status
      episodes
      seasonYear
      startDate { year }
      countryOfOrigin
      coverImage { extraLarge large }
      nextAiringEpisode { airingAt episode }
    }
  }
}
"""

AIRING_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    status
    nextAiringEpisode { airingAt episode }
  }
}
"""

# AniList janri -> botdagi janr nomi (config.NORMAL_GENRES / VIP_GENRES dagi nomlar bilan bir xil)
GENRE_MAP: dict[str, str] = {
    "action": "Jangari",
    "adventure": "Sarguzasht",
    "comedy": "Komediya",
    "drama": "Drama",
    "fantasy": "Fantastika",
    "horror": "Qo'rqinchli",
    "mahou shoujo": "Sehrli qizlar",
    "mecha": "Mecha",
    "music": "Musiqiy",
    "mystery": "Sirli",
    "psychological": "Psixologik",
    "romance": "Romantika",
    "sci-fi": "Ilmiy fantastika",
    "slice of life": "Kundalik hayot",
    "sports": "Sport",
    "supernatural": "G'ayritabiiy",
    "thriller": "Triller",
    "ecchi": "Ecchi",
}

COUNTRY_MAP: dict[str, str] = {"JP": "Yaponiya", "KR": "Koreya", "CN": "Xitoy", "US": "AQSh"}

_AIRING_TTL = 1800.0
_AIRING_FAIL_TTL = 300.0
_airing_cache: dict[int, tuple[float, Optional[dict]]] = {}


async def _post(query: str, variables: dict, timeout: float = 8.0) -> dict:
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.post(
            API_URL,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"AniList HTTP {resp.status}")
            payload = await resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"AniList xatosi: {payload['errors'][0].get('message', '')}")
    return payload["data"]


def clean_description(raw: Optional[str], limit: int = 500) -> str:
    """HTML teglarni olib tashlaydi, uzun bo'lsa gap oxirida qisqartiradi va Telegram HTML uchun xavfsiz qiladi."""
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\(Source:[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\[Written by[^\]]*\]", "", text, flags=re.I)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        cut = cut[: end + 1] if end > limit * 0.5 else cut.rstrip() + "…"
        text = cut
    return html.escape(text.strip(), quote=False)


def normalize_media(m: dict[str, Any]) -> dict[str, Any]:
    title = m.get("title") or {}
    display = title.get("english") or title.get("romaji") or title.get("native") or "—"
    year = m.get("seasonYear") or (m.get("startDate") or {}).get("year")
    cover = m.get("coverImage") or {}
    nxt = m.get("nextAiringEpisode") or None
    return {
        "id": int(m["id"]),
        "title": display,
        "romaji": title.get("romaji") or "",
        "year": str(year) if year else "",
        "format": m.get("format") or "",
        "status": m.get("status") or "",
        "episodes": m.get("episodes"),
        "genres": list(m.get("genres") or []),
        "country": COUNTRY_MAP.get(m.get("countryOfOrigin") or ""),
        "description": clean_description(m.get("description")),
        "cover_url": cover.get("extraLarge") or cover.get("large") or "",
        "next_airing": {"episode": nxt["episode"], "at": nxt["airingAt"]} if nxt else None,
    }


async def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    data = await _post(SEARCH_QUERY, {"search": query, "perPage": limit})
    return [normalize_media(m) for m in (data.get("Page", {}).get("media") or [])]


async def get_next_airing(anilist_id: int) -> Optional[dict[str, Any]]:
    """Keyingi qism ma'lumoti: {'episode': 12, 'at': epoch} yoki None. Natija 30 daqiqa keshlanadi."""
    now = time.time()
    cached = _airing_cache.get(anilist_id)
    if cached and cached[0] > now:
        return cached[1]
    try:
        data = await _post(AIRING_QUERY, {"id": int(anilist_id)}, timeout=4.0)
        nxt = (data.get("Media") or {}).get("nextAiringEpisode")
        result = {"episode": nxt["episode"], "at": nxt["airingAt"]} if nxt else None
        _airing_cache[anilist_id] = (now + _AIRING_TTL, result)
        return result
    except Exception as e:
        logger.warning("AniList keyingi qism ma'lumotini olib bo'lmadi: %s", e)
        _airing_cache[anilist_id] = (now + _AIRING_FAIL_TTL, None)
        return None


def format_airing_line(info: Optional[dict[str, Any]]) -> str:
    """Anime kartasi uchun qator yoki bo'sh satr (agar keyingi qism yo'q yoki vaqti o'tgan bo'lsa)."""
    if not info or info.get("at", 0) <= time.time():
        return ""
    when = datetime.datetime.fromtimestamp(info["at"], config.LOCAL_TZ).strftime("%d.%m %H:%M")
    return f"📅 Keyingi qism: {info['episode']}-qism — {when} (O'zbekiston vaqti)"


def match_genre_ids(al_genres: list[str], db_genres: list[Any]) -> list[int]:
    """AniList janrlarini botdagi janrlarga moslaydi (nomlar bo'yicha). Topilmaganlari tashlab ketiladi."""
    by_name = {str(g["name"]).strip().lower(): g["id"] for g in db_genres}
    result: list[int] = []
    for genre in al_genres:
        uz = GENRE_MAP.get(genre.strip().lower())
        if uz and uz.lower() in by_name and by_name[uz.lower()] not in result:
            result.append(by_name[uz.lower()])
    return result


def button_label(item: dict[str, Any]) -> str:
    parts = [item["title"]]
    extra = ", ".join(x for x in (item["year"], item["format"]) if x)
    if extra:
        parts.append(f"({extra})")
    label = " ".join(parts)
    return label if len(label) <= 60 else label[:57] + "…"
