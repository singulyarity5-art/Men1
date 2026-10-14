# Test2 Bot

Anime kutubxonasi va VIP obuna tizimiga ega Telegram bot (aiogram 3 + SQLite).

## O'rnatish

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env faylini oching va BOT_TOKEN, SUPER_ADMIN_IDS, MAIN_CHANNEL qiymatlarini to'ldiring
python main.py
```

`SUPER_ADMIN_IDS` ga yozilgan Telegram ID(lar) bot birinchi ishga tushganda
avtomatik admin bo'lib qoladi (⚙️ Admin panel tugmasi asosiy menyuda ko'rinadi).
Boshqa foydalanuvchilarni keyinchalik 👥 Foydalanuvchilar bo'limi orqali admin
qilishingiz mumkin.

## Loyihaning tuzilishi

```
anime_bot/
├── main.py            — ishga tushirish, fon vazifalari (VIP muddati, kunlik backup, kunlik e'lon)
├── config.py           — sozlamalar, konstantalar (janrlar ro'yxati, sahifalash va h.k.)
├── database.py         — SQLite bilan ishlash (yagona joy, handlerlar to'g'ridan-to'g'ri SQL yozmaydi)
├── keyboards.py         — barcha reply/inline klaviaturalar
├── states.py            — FSM holatlar
└── handlers/
    ├── common.py         — umumiy yordamchilar (majburiy obuna tekshiruvi, admin filtri)
    ├── user.py            — foydalanuvchi paneli: qidiruv, katalog, janrlar, reyting, VIP xarid, profil
    └── admin.py           — admin panel: anime/qism qo'shish, foydalanuvchilar, broadcast, sozlamalar
```

## Talablar ro'yxati bo'yicha qamrov

Loyiha sizning 24 bandlik texnik topshiriqingiz asosida qurilgan. Asosiy oqimlar
(user panel, qidiruv, anime ID tizimi, qismlar sahifalashi 12/sahifa 6×2 tugma,
1–10 baholash, oddiy/VIP janrlar va ularning avtomatik VIP belgilanishi, VIP
1/2/3 oylik tizimi va narxlarni admin panelidan sozlash, karta orqali to'lov +
chek yuborish + admin tasdiqlashi, admindan to'g'ridan-to'g'ri VIP berish,
majburiy obuna, profil, yordam, /start rasm/matn, kanal e'loni, broadcast
navbat bilan yuborish va pauza/davom, foydalanuvchilar ro'yxati va batafsil
profili, admin↔user panel, bloklash tugmalari olib tashlangan) to'liq amalga
oshirilgan.

Bir nechta joyni o'zingizga moslab sozlashingiz kerak bo'lishi mumkin:

- **VIP kontent himoyasi**: video `protect_content=True` bilan yuboriladi
  (forward/saqlashni Telegram darajasida cheklaydi). VIP tugagach botda
  saqlangan xabarlarni ommaviy o'chirish alohida chat_id/message_id jurnalini
  yuritishni talab qiladi — hozircha kod bazasi buni loglamaydi, agar kerak
  bo'lsa `watch_history` jadvaliga `message_id` ustunini qo'shib, VIP tugaganda
  shu xabarlarni `bot.delete_message` bilan o'chiradigan job qo'shish mumkin.
- **Broadcast**: jarayon xotirada (`asyncio.create_task`) ishlaydi — bot qayta
  ishga tushsa, tugallanmagan broadcastni davom ettirmaydi (faqat holatini
  `broadcasts` jadvalida "paused" deb saqlab qoladi). To'liq "resume after
  restart" kerak bo'lsa, yuborilgan user_id'lar alohida jadvalda belgilab
  borilishi kerak.
- **Majburiy obuna**: bot kanalga **admin** qilib qo'shilgan bo'lishi shart,
  aks holda obunani tekshira olmaydi (bunday holatda foydalanuvchini
  bloklamaslik uchun o'sha kanal shartsiz o'tkazib yuboriladi — buni
  `handlers/common.py::is_subscribed_to_all` da qattiqroq qilish mumkin).
- **Balans (💰)**: profil va admin foydalanuvchi profilida ko'rsatiladi, lekin
  uni to'ldirish/ayirish uchun alohida funksiya so'ralmagan edi — hozircha 0
  dan boshlanadi, DB darajasida tayyor.

## Baza

SQLite (`anime.db`, WAL rejimida). `⚙️ Admin panel → 💾 Zaxira nusxa (Backup)`
orqali istalgan vaqtda qo'lda, shuningdek har 24 soatda avtomatik zaxira
olinadi (`backups/` papkasiga).

## Filler qismlar
- Admin qism yuklayotganda **🟡 Filler qo'shish** tugmasini bosib, nechta ketma-ket filler borligini yozadi (video yuborish shart emas).
- Fillerlar qism raqamlashida o'z o'rnini egallaydi (raqamlar buzilmaydi), lekin tugma/video bo'lmaydi.
- Foydalanuvchi qismlar ro'yxatida "5-qismdan 10-qismgacha — filler" ko'rinishidagi yozuvni ko'radi.
- "Keyingi qism", "Davom ettirish" va "Yangi qismlar" fillerlarni o'tkazib yuboradi.

## Kanal e'lonidagi reyting
- Kanalga e'lon yuborilganda xabar ID'si saqlanadi. Foydalanuvchi baho bersa, e'londagi reyting avtomatik yangilanadi
  (har bir anime uchun ko'pi bilan 90 soniyada bir marta).
- Bu o'zgarishdan oldin yuborilgan eski e'lonlar yangilanmaydi.

## Rangli tugmalar
- Tugmalar matniga qarab avtomatik ranglanadi: yashil (ko'rish/qo'shish/tasdiqlash/VIP), qizil (o'chirish/bekor qilish), ko'k (qolganlari).
  Raqamli tugmalar va ⬅️ ➡️ navigatsiya tugmalari rangsiz qoladi.
- Qoidalar `button_style.py` ichida (`pick_style`). Talab: aiogram 3.25+ va yangi Telegram ilovasi (eskilarida rang ko'rinmaydi).

## 1-bosqich yangiliklari
- **Anime qo'shish:** janrlardan keyin davlat → til (ovoz) → subtitr → yil inline tugma bilan tanlanadi
  (bir nechta til/subtitr belgilash mumkin, "✍️ Boshqa" bilan qo'lda yozish, "⏭ O'tkazib yuborish").
  Tahrirlashda ham shu tugmalar (anime sahifasidagi 🌍 Davlat / 📅 Yil / 🎙 Til / 💬 Subtitr).
- **🖼 Poster** tugmasi: animeni o'chirmasdan rasmni almashtirish yoki olib tashlash.
- **🎭 Janrlar** (admin panel): yangi janr, nom/emoji tahrirlash, 💎 VIP ↔ 🆓 oddiy, o'chirish.
  Janr VIP bo'lsa, undagi animelar avtomatik VIP bo'ladi (tasdiqlash bilan). **Harem** VIP janr sifatida qo'shildi.
- **🕐 Kunlik e'lon** (admin panel): vaqtni tanlash/yozish, yoqish/o'chirish, sinab ko'rish. Vaqt O'zbekiston (UTC+5) bo'yicha;
  boshqa mintaqa uchun `.env` da `TZ_OFFSET_HOURS`.

## 2-bosqich: Referal tizimi
- Har bir foydalanuvchining shaxsiy havolasi: `https://t.me/<bot>?start=ref_<uning Telegram ID'si>`
  (👤 Profil → 🎁 Do'st taklif qilish yoki `/invite`). "📤 Do'stlarga ulashish" tugmasi bor.
- Taklif qilgan odamga **7 kun**, taklif qilingan do'stga **2 kun** VIP (admin paneldan o'zgartiriladi).
- Mukofot do'st **majburiy kanallarga obuna bo'lgach** beriladi. Faqat YANGI foydalanuvchi hisoblanadi; o'zini taklif qilib bo'lmaydi;
  har kim faqat bir marta taklif qilinadi; mukofot ikki marta berilmaydi. VIP muddati mavjud muddatga qo'shiladi.
- Oylik chegara (standart 30): taklif qiluvchi bir oyda shuncha do'st uchun mukofot oladi (do'st baribir oladi). 0 = chegarasiz.
- Admin panel → 🎁 Referal: yoqish/o'chirish, kunlar, oylik chegara, statistika va eng ko'p taklif qilganlar.

## 3-bosqich: 🎯 Kashf qilish
- Asosiy menyuda **🎯 Kashf qilish** (va "🎬 Anime ko'rish" markazida ham). Kayfiyatni tanlaysiz: 😂 Kulgim kelyapti, 😭 Yig'lagim kelyapti,
  🔥 Adrenalin, 💕 Sevgi, 😱 Qo'rqinch, 🎲 Aralash — bot mos janrlardagi anime kartasini (poster, janr, reyting, qisqa tavsif) ko'rsatadi.
- Tugmalar: ❤️ Ko'raman («📌 Keyin ko'raman» ro'yxatiga tushadi), 👎 Qiziq emas, ⏭ Keyingisi, 🎬 Ko'rish (oddiy anime sahifasi, VIP tekshiruvi o'sha yerda).
- Bot didingizni o'rganadi: ❤️ bosilgan, sevimlilar va ko'rilgan animelar janrlari ko'proq, 👎 bosilganlari kamroq chiqadi.
- Chiqmaydi: videosi yo'q animelar, ko'rishni boshlagan/belgilagan animelar; VIP animelar faqat VIP huquqi borlarga.
- Kayfiyat → janr moslashuvi `config.py` dagi `MOODS` da (janr nomlari bazadagi bilan bir xil bo'lishi kerak).

## Asosiy menyu
💎 VIP olish (1-qator, VIP bo'lganlarga muddatini ko'rsatadi va uzaytirishni taklif qiladi) → 🎬 Anime ko'rish → 🎯 Kashf qilish / 🆕 Yangi animelar →
🔥 Mashhur / 🔥 Yangi qismlar → ❤️ Sevimlilar / 🎭 Janrlar → 🕐 Ko'rish tarixi / 🎁 Do'st taklif qilish → 👤 Profil / 🆘 Yordam.
"📚 Katalog" tugmasi olib tashlandi (Janrlar bilan bir xil edi).

## Ulashish (inline rejim)
- 🎁 Do'st taklif qilish → **📤 Do'stlarga ulashish**: suhbat tanlanadi va tayyor xabar chiqadi — rasm (/start rasmi), matn va
  **🚀 Botga o'tish** tugmasi (taklif qiluvchining havolasi bilan). "N kun VIP" admin paneldagi qiymatdan olinadi.
- **Bir martalik sozlama:** @BotFather → `/setinline` → botni tanlang → placeholder yozing. Bu bo'lmasa inline rejim ishlamaydi
  (zaxira: «🔗 Oddiy havola bilan ulashish» tugmasi).
- Webhook `allowed_updates` ga `inline_query` avtomatik qo'shiladi (main.py).
