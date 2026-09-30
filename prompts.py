"""
Gemini uchun promptlar: yozish uslubi, namunalar va rasm uslubi.
Uslub siz yuborgan kanal eksportidan (messages.html) tahlil qilib olingan.
"""
from __future__ import annotations

STYLE_GUIDE = """
YOZISH USLUBI (qat'iy amal qil):
- Til: o'zbek tili, LOTIN yozuvi. Apostrof sifatida ' belgisidan foydalan (o', g', ma'no).
- Ohang: samimiy, ekspert, 1-shaxsda ("men", "ko'rganman"), o'quvchiga "siz" deb murojaat.
  Ortiqcha "hayp", manipulyatsiya, yolg'on va'da YO'Q. Aniq, hayotiy, foydali.
- 1-qator — kuchli HOOK: paradoks, og'riqli muammo yoki keskin fikr.
  Masalan: "Obunachi bor, oxvat bor, sotuv yo'q. Nima uchun bunday?"
  Birinchi qatorni **qalin** qilib yoz (faqat ** belgilari bilan).
- Qisqa paragraflar: 1–3 jumla, har paragraf orasida bo'sh qator.
- Tuzilma: muammo → sabab → farq/taqqoslash yoki 1️⃣ 2️⃣ 3️⃣ ro'yxat → hayotiy misol →
  "Xulosa shu: ..." jumlasi → amaliy vazifa ("Bugun shunday qiling: ...") → izohga chaqiriq.
- Misollar: "Masalan, bir mutaxassis..." ko'rinishida umumiy misol keltir.
  Haqiqiy odam ismlari, brendlar, aniq mijozlar yoki o'ylab topilgan statistik raqamlarni
  haqiqat sifatida YOZMA.
- Oxirgi qator: auditoriyaga savol yoki chaqiriq ("Izohda yozing 💬", "Foydali bo'lsa 🔥 qoldiring").
- Emoji kam: butun postda 2–5 ta. Hashtag YO'Q. Kanal imzosi/username YOZMA (bot o'zi qo'shadi).
- Markdown faqat **qalin**. Sarlavha belgilari (#), jadval, havola ishlatma.
"""

EXAMPLES = """
--- NAMUNA 1 ---
**Tadbirkor bilan mutaxassisning shaxsiy brendi bir-biridan farq qiladi!**

Kuzatuvimga ko'ra, media bozorida ko'pchilik bir xil strategiyada kontent qilyapti. Bu postda farqini tushuntirib beraman.

Mutaxassisning kuchli tarafi — tajribasi va keyslari. Uning brendi tajribasiga quriladi. Keyslari, ishlari, natijalari gapiradi.

Shuning uchun unga ishonch tez keladi. Mijoz siz bilan uchrashishdan oldin blogingizni ko'rib, tayyor bo'lib keladi.

Tadbirkorning kuchli tarafi — vizionerlik va uzoqni ko'ra olishi. Uning brendi kasbga emas, odamga quriladi.

Farqi bitta jumlada: mutaxassisga blog mijoz olib keladi, tadbirkorga — imkoniyat.

Bu fikrga qo'shilasizmi? Izohda yozing 💬

--- NAMUNA 2 ---
**Obunachisi yuz mingdan oshgan, lekin bironta xizmatini sota olmaydigan odamlarni ko'p ko'rganman.**

Sababi oddiy: tanilish bilan shaxsiy brend — ikki xil narsa. Tanilganda sizni ko'rishadi. Brend bo'lganda sizga ishonishadi.

Ko'pchilik shu yerda adashadi. Strategiyasiz kameraga chiqadi va g'oyalari bir oyda tugaydi.

Xulosa shu: obunachi soni maqsad emas. Maqsad — sizga ishonadigan odam.

Bugun shunday qiling: kim uchun gapirasiz, ular qaysi dardi bilan keladi, siz nima taklif qilasiz — shu uchta savolga yozma javob bering.

Foydali bo'lsa 🔥 qoldiring
"""

_NO_TEXT = (" STRICT RULES: absolutely NO text, letters, numbers, words, captions, logos, brand "
            "marks, app icons, UI screenshots or watermarks anywhere. No real or famous people.")

# Har uslub uchun fon rasmi shabloni. Matn uchun bo'sh joy qoldirish — eng muhim qoida,
# chunki sarlavhani kod shu bo'sh joyga yozadi.
IMAGE_STYLES = {
    "neon": (
        "Square 1:1 minimalist creative 3D render for a marketing post. Concept: {scene}. "
        "Look: pure black background, dramatic glossy 3D objects with a strong {accent} neon glow "
        "and rim light, subtle reflective floor, cinematic, premium, high contrast. "
        "COMPOSITION: all objects are placed in the LOWER 40% of the frame; the UPPER 60% is "
        "completely empty, clean dark background (reserved for a headline)." + _NO_TEXT
    ),
    "editorial": (
        "Vertical 4:5 minimalist editorial lifestyle photograph for a marketing post. Concept: {scene}. "
        "Look: warm beige / cream tones, soft natural window light with gentle leaf or window-frame "
        "shadows, clean aesthetic still life on a light desk, calm and premium, shallow depth of field. "
        "COMPOSITION: objects are placed ONLY on the RIGHT 35% of the frame and along the very bottom "
        "edge; the LEFT 65% is an empty, plain, softly lit wall (reserved for text)." + _NO_TEXT
    ),
    "photo": (
        "Square 1:1 realistic professional photograph for a marketing post. Concept: {scene}. "
        "Look: natural soft light, authentic, warm, premium commercial photography, shallow depth "
        "of field; if people appear they look like Central Asian (Uzbek) people. "
        "COMPOSITION: the main subject is in the LOWER two thirds; the UPPER third is calm, softly "
        "blurred background without important details (a caption card will cover it)." + _NO_TEXT
    ),
}

ACCENT_WORDS = {
    "red": "red", "crimson": "deep crimson", "orange": "warm orange", "terracotta": "terracotta",
    "gold": "golden", "green": "emerald green", "blue": "electric blue", "purple": "violet",
    "pink": "hot pink",
}

DESIGN_BRIEF = {
    "neon": """DIZAYN USLUBI: "Neon" — qora fon, neon rangli 3D sahna, katta TOR harfli sarlavha.
- headline: 3–6 so'zli kuchli, qisqa sarlavha (post g'oyasining eng o'tkir ifodasi, 45 belgigacha).
- highlight: headline ICHIDAN aynan olingan 1–3 so'z — rangli plashkada ajratiladi.
- accent: quyidagilardan biri: red, crimson, purple, blue, orange, pink — mavzu kayfiyatiga mos.
- scene: INGLIZCHA, bitta kuchli vizual metafora (3D obyektlar: o'sayotgan grafik, nishon, magnit,
  telefon, kalit, zinapoya, sovg'a qutisi va h.k.). Brend logotiplari YO'Q.
- tag, subline, points, cta_bold, cta_rest, note: bo'sh qoldirsa bo'ladi.""",
    "editorial": """DIZAYN USLUBI: "Editorial" — och iliq fon, ikki rangli sarlavha, 3 qadam, CTA karta.
- headline: 3–6 so'zli sarlavha (45 belgigacha). Oxirgi qismi rangli bo'ladi.
- highlight: headline ICHIDAN aynan olingan, OXIRIDAGI 1–3 so'z (rangli qism).
- tag: 1–2 so'zli rukn (masalan: "Reels", "Sotuv", "Brend").
- points: post mazmunidan AYNAN 3 ta qisqa kalit so'z (har biri 1 so'z, 12 harfgacha).
- subline: 1 qisqa amaliy jumla (70 belgigacha).
- cta_bold: 2–3 so'zli chaqiriq (masalan "Saqlab qo'ying"); cta_rest: davomi (40 belgigacha).
- note: 2–4 so'zli qo'lyozma uslubidagi qisqa xulosa.
- accent: orange, terracotta, green, blue, crimson, gold dan biri.
- scene: INGLIZCHA, stol ustidagi mavzuga mos 2–3 buyum (telefon, bloknot, kofe, kitob, o'simlik...).""",
    "photo": """DIZAYN USLUBI: "Foto + karta" — real foto, ustida oq kartada sarlavha.
- headline: 5–10 so'zli, qiziqtiradigan jumla-sarlavha (70 belgigacha), oddiy yozuvda (katta harf emas).
- highlight: headline ICHIDAN aynan olingan 1–3 so'z — rangli bo'ladi (eng "sotadigan" qism).
- accent: red, crimson, blue, green, purple, orange dan biri.
- scene: INGLIZCHA, post mavzusiga mos real hayotiy sahna (odamlar, ish jarayoni, mijoz bilan
  uchrashuv, telefon bilan ishlash va h.k.).
- tag, subline, points, cta_bold, cta_rest, note: bo'sh qoldirsa bo'ladi.""",
}


def build_image_prompt(style: str, scene: str, accent: str) -> str:
    tpl = IMAGE_STYLES.get(style, IMAGE_STYLES["photo"])
    return tpl.format(scene=scene.strip().rstrip("."), accent=ACCENT_WORDS.get(accent, "red"))


def build_post_prompt(topic: str, recent_hooks: list[str], max_chars: int, style: str = "photo") -> str:
    recent = "\n".join(f"- {h}" for h in recent_hooks[-15:]) or "- (hali yo'q)"
    return f"""Sen "Marketing va Sotuv" Telegram kanalining tajribali SMM muallifisan.
Kanal auditoriyasi: tadbirkorlar, mutaxassislar, SMM va sotuv bilan shug'ullanuvchilar.

VAZIFA: quyidagi mavzuda BITTA yangi, foydali Telegram post yoz.
MAVZU: {topic}

{STYLE_GUIDE}

USLUB NAMUNALARI (faqat ohang va tuzilma uchun, matnni ko'chirma):
{EXAMPLES}

YAQINDA CHIQQAN POSTLAR (bularni TAKRORLAMA, boshqa burchakdan yondash):
{recent}

UZUNLIK: post {max_chars} belgidan OSHMASIN (bo'sh joylar bilan). Bu qat'iy talab.

POST RASMI UCHUN DIZAYN MATNLARI (rasm ustiga yoziladi, post matniga va mavzuga MOS bo'lsin):
{DESIGN_BRIEF.get(style, DESIGN_BRIEF["photo"])}
Dizayndagi barcha o'zbekcha matnlar lotin yozuvida, imlo xatosiz, qisqa va kuchli bo'lsin.

JAVOBNI JSON ko'rinishida qaytar:
- "hook": postning 1-qatori (qalin belgisiz, 120 belgigacha)
- "post": to'liq post matni
- "design": {{headline, highlight, tag, subline, points, cta_bold, cta_rest, note, accent, scene}}
"""
