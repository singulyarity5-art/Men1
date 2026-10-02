"""
Test2 Bot — konfiguratsiya fayli.

Bot tokenni va boshqa maxfiy qiymatlarni .env faylidan o'qiydi.
Ishga tushirishdan oldin .env.example asosida .env fayl yarating.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv o'rnatilmagan bo'lsa ham bot ishga tushaveradi,
    # lekin bu holda BOT_TOKEN ni muhit o'zgaruvchisi sifatida berish kerak.
    pass

# --- Majburiy sozlamalar ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Botni birinchi marta ishga tushirganda super-admin bo'lib kiradigan
# Telegram ID(lar). Vergul bilan ajratib bir nechtasini yozish mumkin:
# SUPER_ADMIN_IDS=123456789,987654321
_super_admins_raw = os.getenv("SUPER_ADMIN_IDS", "")
SUPER_ADMIN_IDS: list[int] = [
    int(x.strip()) for x in _super_admins_raw.split(",") if x.strip().isdigit()
]

# Asosiy anime kanali (yangi anime e'lonlari shu yerga yuboriladi).
# @kanal_username yoki -100... ko'rinishidagi ID bo'lishi mumkin.
MAIN_CHANNEL: str = os.getenv("MAIN_CHANNEL", "")

# --- Fayl yo'llari ---
DB_PATH: str = os.getenv("DB_PATH", "anime.db")
BACKUP_DIR: str = os.getenv("BACKUP_DIR", "backups")
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")

# --- Sahifalash sozlamalari ---
EPISODES_PER_PAGE = 12
EPISODE_BUTTONS_COLUMNS = 6  # 6 x 2 = 12 ta tugma bitta sahifada
USERS_PER_PAGE = 10

# --- VIP muddatlari (kunlarda) ---
VIP_DAYS = {
    1: 30,
    2: 60,
    3: 90,
}

# --- Oddiy janrlar (emoji, nomi) ---
NORMAL_GENRES: list[tuple[str, str]] = [
    ("⚔️", "Jangari"),
    ("🏔️", "Sarguzasht"),
    ("😂", "Komediya"),
    ("🎭", "Drama"),
    ("🧙", "Fantastika"),
    ("👻", "Qo'rqinchli"),
    ("🤖", "Mecha"),
    ("🎵", "Musiqiy"),
    ("🔍", "Sirli"),
    ("🧠", "Psixologik"),
    ("❤️", "Romantika"),
    ("🚀", "Ilmiy fantastika"),
    ("🌿", "Kundalik hayot"),
    ("🏆", "Sport"),
    ("👻", "G'ayritabiiy"),
    ("🔥", "Triller"),
]

# --- VIP janrlar ---
VIP_GENRES: list[tuple[str, str]] = [
    ("💎", "Ecchi"),
    ("💎", "Sehrli qizlar"),
    ("💎", "Hentay"),
]

# Standart sozlamalar (settings jadvaliga birinchi ishga tushirishda yoziladi)
DEFAULT_SETTINGS = {
    "start_text": (
        "🎬 <b>Anime Bot</b>ga xush kelibsiz!\n\n"
        "Bu yerda siz minglab anime va animelarning barcha qismlarini "
        "bepul tomosha qilishingiz mumkin. Pastdagi menyudan foydalaning 👇"
    ),
    "start_photo_file_id": "",
    "help_text": (
        "🆘 <b>Yordam</b>\n\n"
        "Botdan foydalanish bo'yicha savollaringiz bo'lsa, admin bilan bog'laning."
    ),
    "help_admin_username": "",
    "vip_price_1": "0",
    "vip_price_2": "0",
    "vip_price_3": "0",
    "payment_card_number": "",
    "payment_card_holder": "",
}
