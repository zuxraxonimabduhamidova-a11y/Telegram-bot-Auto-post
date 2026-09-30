# SMM Post Agent — Telegram bot (Render, 24/7)

Bot har kuni belgilangan soatlarda (standart **09:00** va **19:00**, Toshkent vaqti) Gemini orqali
**rasmli post** tayyorlaydi va avval sizga yuboradi:

| Tugma | Natija |
|---|---|
| ✅ Tasdiqlash | Darhol @marketingsotuv kanaliga chiqadi |
| 🔄 Almashtirish | Yangi variant (boshqa mavzu burchagida) tayyorlab ko'rsatadi, 15 daqiqa qaytadan boshlanadi |
| ❌ Bekor qilish | Shu vaqtdagi post chiqmaydi |
| (javob yo'q) | 15 daqiqadan so'ng avtomatik kanalga chiqadi |

Tayyorlash va yuklash paytida jonli **soat animatsiyasi** (🕐→🕑… + progress + taymer) ko'rinib turadi,
preview tugmasida esa "⏱ N daqiqadan so'ng avtomatik chiqadi" har daqiqa yangilanadi.

---

## 1. Tayyorgarlik (5 daqiqa)

1. **Bot token** — @BotFather → `/mybots` → @zuxraxonimsmmpostagentbot → *API Token*.
2. **Gemini API key** — https://aistudio.google.com/apikey
   ⚠️ Rasm yaratish modellari faqat **pullik (billing yoqilgan)** Gemini loyihasida ishlaydi.
   Billing bo'lmasa bot baribir ishlaydi, lekin postlar rasmsiz chiqadi (sizga ogohlantirish keladi).
3. **Admin ID** — botga `/start` yozing, u sizning ID raqamingizni ko'rsatadi
   (yoki @userinfobot dan oling).
4. **Botni kanalga admin qiling** — @marketingsotuv → Administratorlar → botni qo'shing →
   «Post yozish» (Post messages) huquqini yoqing.

## 2. GitHub'ga yuklash

Papkadagi fayllarni yangi **private** repozitoriyaga yuklang. `.env` fayl yaratmang va yuklamang —
maxfiy qiymatlar faqat Render'da turadi.

## 3. Render'da ishga tushirish

1. https://dashboard.render.com → **New → Blueprint** → repozitoriyani tanlang (`render.yaml` avtomatik o'qiladi).
   *Yoki* **New → Web Service**: Build `pip install -r requirements.txt`, Start `python bot.py`.
2. **Environment** bo'limida kiriting:
   - `BOT_TOKEN` = BotFather tokeni
   - `GEMINI_API_KEY` = Gemini kaliti
   - `ADMIN_IDS` = sizning ID (bir nechta bo'lsa vergul bilan)
3. **Deploy**. 1–2 daqiqada botdan "🟢 Bot ishga tushdi" xabari keladi.
4. Tekshirish: botga `/now` yozing — darhol post tayyorlaydi.

### 24/7 ishlashi haqida
- Render **Free** tarifi 15 daqiqa so'rovsiz qolsa "uxlaydi". Bot buni oldini olish uchun har
  10 daqiqada o'zini ping qiladi (`/health`).
- Qo'shimcha kafolat uchun bepul **UptimeRobot** (uptimerobot.com) da `https://<sizning-servis>.onrender.com/health`
  manzilini 5 daqiqalik monitor qilib qo'ying.
- Eng ishonchli variant — Render **Starter** ($7/oy): hech qachon uxlamaydi.
- Restart bo'lsa: kutilayotgan post tiklanadi, o'tib ketgan slot (30 daqiqagacha) avtomatik bajariladi.

## 4. Buyruqlar (faqat adminlar uchun)

| Buyruq | Vazifa |
|---|---|
| `/start` | Yordam |
| `/now` | Hozir post tayyorlash |
| `/status` | Holat, keyingi post vaqti, kanal huquqlari |
| `/topics` | Mavzular ro'yxati (navbatdagisi 👉) |

## 5. Sozlamalar (Render → Environment)

| O'zgaruvchi | Standart | Izoh |
|---|---|---|
| `POST_TIMES` | `09:00,19:00` | Post vaqtlari |
| `APPROVAL_MINUTES` | `15` | Avto-chiqishgacha kutish |
| `CHANNEL_ID` | `@marketingsotuv` | Kanal |
| `CHANNEL_SIGNATURE` | `@marketingsotuv` | Post oxiridagi imzo |
| `GEMINI_TEXT_MODEL` | `gemini-3.8-flash` | Matn modeli |
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | Rasm modeli (arzonroq: `gemini-3.1-flash-lite-image`) |
| `POST_MAX_CHARS` | `950` | Post uzunligi (1024 gacha rasm tagiga sig'adi) |
| `MAX_REGENERATIONS` | `5` | Bitta slotda almashtirish limiti |
| `TOPICS` | — | `Mavzu 1;Mavzu 2` — berilsa `topics.txt` o'rniga |

Mavzularni o'zgartirish: `topics.txt` ni tahrirlang → GitHub'ga push → Render avtomatik qayta deploy qiladi.
Yozish uslubi `prompts.py` da (kanal postlaringiz asosida tuzilgan).

## 6. Xavfsizlik

- Kodda **hech qanday** token/kalit yo'q — faqat Render muhit o'zgaruvchilari.
- Loglarda token va API kalit avtomatik `***` bilan yashiriladi.
- Tugma va buyruqlar faqat `ADMIN_IDS` dagi odamlarga ishlaydi; begona foydalanuvchi tugma bossa "⛔ Ruxsat yo'q".
- Eskirgan tugmalar (almashtirilgan/chiqib ketgan post) ishlamaydi, ikki marta bosish ikki marta post chiqarmaydi.
- AI matni HTML-escape qilinadi.
- Token biror joyda oshkor bo'lsa: @BotFather → *Revoke current token* → Render'da yangilang.
