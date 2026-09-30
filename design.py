"""
Post rasmlari uchun dizayn shablonlari (Pillow).

Gemini FAQAT fon/sahna rasmini chizadi (matnsiz). Barcha yozuvlar shu yerda
kod orqali qo'yiladi — shuning uchun o'zbekcha harflar doim xatosiz chiqadi.

Uslublar (namuna sifatida ilhom olingan, ko'chirma emas):
  neon      — qorong'i fon, neon-rangli 3D sahna, katta tor shrift, urg'u plashkada
  editorial — och iliq fon, ikki rangli sarlavha, 3 qadam, CTA karta, qo'lyozma izoh
  photo     — real foto, ustida oq yumaloq kartada sarlavha, muhim so'zlar rangli
"""
from __future__ import annotations

import io
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT_DIR = Path(__file__).resolve().parent / "fonts"
STYLES = ("neon", "editorial", "photo")
STYLE_NAMES = {"neon": "Neon", "editorial": "Editorial", "photo": "Foto + karta"}
SIZES = {"neon": (1080, 1080), "editorial": (1080, 1350), "photo": (1080, 1080)}
ASPECT = {"neon": "1:1", "editorial": "4:5", "photo": "1:1"}

ACCENTS = {
    "red": (229, 40, 40),
    "crimson": (200, 16, 46),
    "orange": (226, 98, 44),
    "terracotta": (190, 82, 46),
    "gold": (232, 168, 20),
    "green": (22, 160, 100),
    "blue": (40, 100, 245),
    "purple": (124, 77, 255),
    "pink": (232, 56, 130),
}
STYLE_ACCENTS = {
    "neon": ["red", "crimson", "purple", "blue", "orange", "pink"],
    "editorial": ["orange", "terracotta", "green", "blue", "crimson", "gold"],
    "photo": ["red", "crimson", "blue", "green", "purple", "orange"],
}

INK = (20, 20, 22)
WHITE = (255, 255, 255)


@dataclass
class DesignSpec:
    headline: str
    highlight: str = ""
    tag: str = ""
    subline: str = ""
    points: list = field(default_factory=list)
    cta_bold: str = ""
    cta_rest: str = ""
    note: str = ""
    accent: str = ""


# ───────────────────────── yordamchilar ─────────────────────────
_font_cache: dict = {}


def font(name: str, size: int, weight: Optional[int] = None) -> ImageFont.FreeTypeFont:
    key = (name, size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(str(FONT_DIR / name), size)
        if weight is not None:
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
        _font_cache[key] = f
    return _font_cache[key]


def anton(size):
    return font("Anton-Regular.ttf", size)


def oswald(size, weight=600):
    return font("Oswald-VF.ttf", size, weight)


def mont(size, bold=False):
    return font("Montserrat-ExtraBold.ttf" if bold else "Montserrat-Medium.ttf", size)


def caveat(size):
    return font("Caveat-VF.ttf", size, 700)


def uz(text: str) -> str:
    """o' g' → o‘ g‘ ; boshqa tutuq belgisi → ’ ; ortiqcha bo'shliqlarni tozalash."""
    text = re.sub(r"\s+", " ", (text or "").replace("**", "")).strip()
    text = re.sub(r"([oOgG])['`ʻ’‘]", lambda m: m.group(1) + "‘", text)
    text = re.sub(r"['`ʼ]", "’", text)
    return text


def upper_uz(text: str) -> str:
    return uz(text).upper()


def accent_rgb(spec: DesignSpec, style: str) -> tuple:
    name = (spec.accent or "").strip().lower()
    if name not in ACCENTS or name not in STYLE_ACCENTS[style]:
        name = STYLE_ACCENTS[style][0]
    return ACCENTS[name]


def tw(f, s: str) -> float:
    return f.getlength(s)


def wrap(words: list, f, max_w: float) -> list:
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if cur and tw(f, test) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def fit_lines(words, fn, max_w, max_lines, hi, lo=20):
    """Eng katta shrift o'lchamini topadi: so'zlar max_lines qatorga va max_w kenglikka sig'sin."""
    for size in range(hi, lo - 1, -2):
        f = fn(size)
        lines = wrap(words, f, max_w)
        if len(lines) <= max_lines and all(tw(f, " ".join(l)) <= max_w for l in lines):
            return size, lines
    f = fn(lo)
    return lo, wrap(words, f, max_w)


def split_highlight(headline: str, highlight: str):
    """Sarlavhani (oldin, urg'u, keyin) qismlarga ajratadi."""
    words = headline.split()
    hl = highlight.split()
    if hl:
        low = [w.lower().strip(".,!?:;—-") for w in words]
        target = [w.lower().strip(".,!?:;—-") for w in hl]
        n = len(target)
        for i in range(len(words) - n + 1):
            if low[i:i + n] == target:
                return words[:i], words[i:i + n], words[i + n:]
    # topilmasa — oxirgi 1–2 so'z urg'u
    k = 1 if len(words) <= 3 else 2
    return words[:-k], words[-k:], []


def cover(img: Image.Image, size) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), size, Image.LANCZOS, centering=(0.5, 0.5))


def vgrad(size, top_rgba, bottom_rgba, start=0.0, end=1.0) -> Image.Image:
    w, h = size
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        t = min(1, max(0, (y / h - start) / max(1e-6, end - start)))
        g.putpixel((0, y), tuple(int(top_rgba[i] + (bottom_rgba[i] - top_rgba[i]) * t) for i in range(4)))
    return g.resize((w, h))


def hgrad(size, left_rgba, right_rgba, start=0.0, end=1.0) -> Image.Image:
    w, h = size
    g = Image.new("RGBA", (w, 1))
    for x in range(w):
        t = min(1, max(0, (x / w - start) / max(1e-6, end - start)))
        g.putpixel((x, 0), tuple(int(left_rgba[i] + (right_rgba[i] - left_rgba[i]) * t) for i in range(4)))
    return g.resize((w, h))


def glow_text(base: Image.Image, xy, text, f, fill, glow, radius=18, strength=2):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text(xy, text, font=f, fill=glow + (255,))
    blur = layer.filter(ImageFilter.GaussianBlur(radius))
    for _ in range(strength):
        base.alpha_composite(blur)
    ImageDraw.Draw(base).text(xy, text, font=f, fill=fill)


def shadow_box(base, box, radius, blur=24, alpha=90, offset=(0, 10)):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]), radius, fill=(0, 0, 0, alpha))
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def sparkle(d: ImageDraw.ImageDraw, cx, cy, r, fill):
    k = r * 0.28
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
               (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=fill)


def cap(f, sample="H") -> tuple:
    """(yuqori siljish, bosh harf balandligi) — matnni aniq vizual tepadan joylash uchun."""
    b = f.getbbox(sample)
    return b[1], b[3] - b[1]


def draw_top(d, x, y_top, text, f, fill, sample="H"):
    off, _ = cap(f, sample)
    d.text((x, y_top - off), text, font=f, fill=fill)


def handle_text(base, text, xy, fill, size=26, anchor="rs", outline=False):
    if not text:
        return
    if outline:  # har qanday fonda o'qilishi uchun yumshoq soya
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(xy, text, font=mont(size), fill=(0, 0, 0, 170), anchor=anchor,
                                   stroke_width=3, stroke_fill=(0, 0, 0, 170))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(3)))
    ImageDraw.Draw(base).text(xy, text, font=mont(size), fill=fill, anchor=anchor)


# ───────────────────────── zaxira fonlar (AI rasm bo'lmasa) ─────────────────────────
def fallback_bg(style: str, accent) -> Image.Image:
    w, h = SIZES[style]
    if style == "neon":
        img = Image.new("RGBA", (w, h), (8, 6, 8, 255))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((w * 0.05, h * 0.55, w * 0.95, h * 1.35), fill=accent + (150,))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
        d = ImageDraw.Draw(img)
        for i in range(7):  # yengil perspektiv chiziqlari
            y = int(h * (0.78 + i * 0.035))
            d.line((0, y, w, y), fill=accent + (40,), width=2)
        return img
    if style == "editorial":
        img = Image.new("RGBA", (w, h), (239, 231, 220, 255))
        light = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(light).polygon([(w * 0.55, 0), (w, 0), (w, h * 0.55)], fill=(255, 250, 240, 120))
        img.alpha_composite(light.filter(ImageFilter.GaussianBlur(60)))
        return img
    base = Image.new("RGBA", (w, h))
    base.alpha_composite(vgrad((w, h), (238, 236, 240, 255), tuple(int(c * 0.35 + 150) for c in accent) + (255,)))
    return base


# ───────────────────────── 1) NEON ─────────────────────────
def render_neon(bg: Image.Image, spec: DesignSpec, accent, handle: str) -> Image.Image:
    W, H = SIZES["neon"]
    img = cover(bg, (W, H)).convert("RGBA")
    img.alpha_composite(vgrad((W, H), (0, 0, 0, 225), (0, 0, 0, 0), 0.0, 0.62))

    before, hl, after = split_highlight(upper_uz(spec.headline), upper_uz(spec.highlight))
    if not before and not after:
        # butun sarlavha = urg'u (masalan bitta so'z) → katta neon harf
        blocks = [("big", hl)]
    elif not after and len(before) >= 1 and len(hl) >= 1:
        # urg'u oxirda bo'lsa: urg'u — katta rangli qator, plashka yo'q
        blocks = [("white", before), ("big", hl)]
    else:
        blocks = [("white", before), ("box", hl), ("big", after)]
    blocks = [(k, w) for k, w in blocks if w]

    max_w, top, region = 920, 80, 560
    GAP = 34
    scale = 1.0
    for _ in range(14):
        plan, total = [], 0
        for kind, words in blocks:
            if kind == "white":
                sz, lines = fit_lines(words, anton, max_w, 2, int(118 * scale), 40)
            elif kind == "box":
                sz, lines = fit_lines(words, anton, max_w - 90, 1, int(92 * scale), 34)
            else:
                sz, lines = fit_lines(words, anton, max_w, 2, int(186 * scale), 50)
            ch = cap(anton(sz))[1]
            pad = int(ch * 0.34) if kind == "box" else 0
            step = ch + (2 * pad if kind == "box" else int(ch * 0.2))
            h = step * len(lines) - (0 if kind == "box" else int(ch * 0.2))
            plan.append((kind, sz, lines, ch, pad, step))
            total += h + GAP
        total -= GAP
        if total <= region:
            break
        scale *= 0.92

    y = top + max(0, (region - total) // 3)
    d = ImageDraw.Draw(img)
    for kind, sz, lines, ch, pad, step in plan:
        f = anton(sz)
        for ln in lines:
            t = " ".join(ln)
            wlen = tw(f, t)
            x = (W - wlen) / 2
            if kind == "white":
                draw_top(d, x, y, t, f, WHITE)
            elif kind == "box":
                box = (x - 36, y, x + wlen + 36, y + ch + 2 * pad)
                glowl = Image.new("RGBA", img.size, (0, 0, 0, 0))
                ImageDraw.Draw(glowl).rounded_rectangle(box, 18, fill=accent + (190,))
                img.alpha_composite(glowl.filter(ImageFilter.GaussianBlur(22)))
                d = ImageDraw.Draw(img)
                d.rounded_rectangle(box, 18, fill=tuple(int(c * 0.72) for c in accent) + (255,),
                                    outline=tuple(min(255, c + 60) for c in accent) + (255,), width=3)
                draw_top(d, x, y + pad, t, f, WHITE)
            else:
                off, _ = cap(f)
                glow_text(img, (x, y - off), t, f, accent + (255,), accent, radius=20, strength=2)
                d = ImageDraw.Draw(img)
            y += step
        y += GAP - (0 if kind == "box" else int(ch * 0.2))
    handle_text(img, handle, (W - 40, H - 34), (255, 255, 255, 200), 24, outline=True)
    return img


# ───────────────────────── 2) EDITORIAL ─────────────────────────
def bookmark(d, cx, cy, s, fill):
    w, h = s * 0.62, s * 0.8
    x0, y0 = cx - w / 2, cy - h / 2
    d.line([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (cx, y0 + h * 0.72), (x0, y0 + h), (x0, y0)],
           fill=fill, width=max(4, int(s * 0.09)), joint="curve")


def render_editorial(bg: Image.Image, spec: DesignSpec, accent, handle: str) -> Image.Image:
    W, H = SIZES["editorial"]
    img = cover(bg, (W, H)).convert("RGBA")
    img.alpha_composite(hgrad((W, H), (244, 238, 229, 225), (244, 238, 229, 0), 0.0, 0.78))
    img.alpha_composite(vgrad((W, H), (244, 238, 229, 120), (244, 238, 229, 0), 0.0, 0.25))
    d = ImageDraw.Draw(img)
    L, colw = 72, 700

    # yuqori panel
    tag = uz(spec.tag)[:18]
    d.text((L, 96), tag, font=mont(28), fill=INK, anchor="ls")
    x_line0 = L + (tw(mont(28), tag) + 30 if tag else 0)
    d.line((x_line0, 86, W - 340, 86), fill=(40, 40, 40), width=2)
    handle_text(img, handle, (W - L, 96), INK, 26)

    # sarlavha: oldin — qora, urg'u+keyingi — aksent
    before, hl, after = split_highlight(upper_uz(spec.headline), upper_uz(spec.highlight))
    words = [(w, INK) for w in before] + [(w, accent) for w in hl + after]
    s, lines = fit_lines([w for w, _ in words], anton, colw, 3, 128, 60)
    f = anton(s)
    ch = cap(f)[1]
    y, i = 180, 0
    for ln in lines:
        x = L
        for w in ln:
            draw_top(d, x, y, w, f, words[i][1])
            x += tw(f, w + " ")
            i += 1
        y += ch + int(ch * 0.16)
    y -= int(ch * 0.16)
    # qo'lda chizilgandek to'lqin chiziq
    uy = y + 30
    pts = [(L + 140 + t * 7, uy + math.sin(t / 9) * 5 - t * 0.12) for t in range(0, 62)]
    d.line(pts, fill=accent, width=7, joint="curve")
    y = uy + 62

    # 3 qadam
    pts3 = [uz(p)[:14] for p in (spec.points or [])][:3]
    if len(pts3) == 3:
        r, gap = 62, 222
        for k, label in enumerate(pts3):
            cx = L + r + k * gap
            d.ellipse((cx - r, y, cx + r, y + 2 * r), fill=(232, 222, 208, 255))
            d.text((cx, y + r), str(k + 1), font=anton(64), fill=accent, anchor="mm")
            d.text((cx, y + 2 * r + 44), label, font=mont(30), fill=INK, anchor="mm")
            if k < 2:
                ax = cx + r + 22
                d.line((ax, y + r, ax + gap - 2 * r - 44, y + r), fill=(60, 60, 60), width=2)
                d.polygon([(ax + gap - 2 * r - 44, y + r - 7), (ax + gap - 2 * r - 32, y + r),
                           (ax + gap - 2 * r - 44, y + r + 7)], fill=(60, 60, 60))
        y += 2 * r + 100

    # qisqa izoh
    if spec.subline:
        sf = mont(38)
        for ln in wrap(uz(spec.subline).split(), sf, colw - 60)[:2]:
            draw_top(d, L, y, " ".join(ln), sf, INK, "Hg")
            y += 50
        y += 30

    # CTA karta
    if spec.cta_bold or spec.cta_rest:
        bw, bf, rf = 640, mont(34, True), mont(34)
        words = [(w, bf, accent) for w in uz(spec.cta_bold).split()] + \
                [(w, rf, INK) for w in uz(spec.cta_rest).split()]
        tx0, maxw = L + 200, bw - 200 - 36
        rows, cur, curw = [], [], 0
        for w, ff, col in words:
            ww = tw(ff, w + " ")
            if cur and curw + ww > maxw:
                rows.append(cur)
                cur, curw = [], 0
            cur.append((w, ff, col))
            curw += ww
        if cur:
            rows.append(cur)
        rows = rows[:3]
        LH = 48
        bh = max(170, LH * len(rows) + 84)
        box = (L, y, L + bw, y + bh)
        shadow_box(img, box, 36, blur=20, alpha=40, offset=(0, 8))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, 36, fill=(250, 246, 240, 235))
        cx, cy = L + 92, y + bh / 2
        d.ellipse((cx - 62, cy - 62, cx + 62, cy + 62), fill=accent)
        bookmark(d, cx, cy, 60, WHITE)
        d.line((L + 178, y + 40, L + 178, y + bh - 40), fill=(90, 90, 90), width=2)
        chm = cap(rf, "Hg")[1]
        ty = cy - (LH * (len(rows) - 1) + chm) / 2
        for row in rows:
            x = tx0
            for w, ff, col in row:
                draw_top(d, x, ty, w, ff, col, "Hg")
                x += tw(ff, w + " ")
            ty += LH
        y += bh + 40

    # qo'lyozma izoh (pastda)
    if spec.note:
        note = uz(spec.note)[:48]
        nf = caveat(58)
        layer = Image.new("RGBA", (W, 200), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((10, 20), note, font=nf, fill=tuple(int(c * 0.85) for c in accent) + (255,))
        layer = layer.rotate(3, resample=Image.BICUBIC, center=(0, 100))
        if y + 90 <= H - 30:  # joy bo'lsagina qo'yamiz — hech narsaga tegmasin
            img.alpha_composite(layer, (L - 10, int(y - 20)))
    return img


# ───────────────────────── 3) FOTO + KARTA ─────────────────────────
def render_photo(bg: Image.Image, spec: DesignSpec, accent, handle: str) -> Image.Image:
    W, H = SIZES["photo"]
    img = cover(bg, (W, H)).convert("RGBA")
    text = uz(spec.headline)
    before, hl, after = split_highlight(text, uz(spec.highlight))
    words = [(w, INK) for w in before] + [(w, accent) for w in hl] + [(w, INK) for w in after]
    max_card, pad_x, pad_y = 900, 56, 40
    s, lines = fit_lines([w for w, _ in words], lambda z: oswald(z, 600), max_card - 2 * pad_x - 90, 3, 72, 34)
    f = oswald(s, 600)
    lh = int(s * 1.18)
    line_ws = [tw(f, " ".join(l)) for l in lines]
    cw = min(max_card, int(max(line_ws) + 2 * pad_x + 90))
    ch = int(lh * len(lines) + 2 * pad_y - (lh - s * 1.02))
    x0 = (W - cw) // 2
    y0 = 150
    box = (x0, y0, x0 + cw, y0 + ch)
    shadow_box(img, box, 30, blur=26, alpha=110, offset=(0, 12))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, 30, fill=(255, 255, 255, 250))
    y, i = y0 + pad_y, 0
    text_right = x0 + cw - 90
    for ln, lw in zip(lines, line_ws):
        x = x0 + pad_x + (text_right - x0 - pad_x - lw) / 2
        for w in ln:
            d.text((x, y), w, font=f, fill=words[i][1])
            x += tw(f, w + " ")
            i += 1
        y += lh
    # kichik bezak: yulduzchalar
    sx, sy = x0 + cw - 60, y0 + ch / 2
    sparkle(d, sx, sy - 14, 22, accent)
    sparkle(d, sx + 22, sy + 22, 12, accent)
    sparkle(d, sx - 16, sy + 30, 8, accent)
    handle_text(img, handle, (W - 36, H - 30), (255, 255, 255, 235), 24, outline=True)
    return img


RENDERERS = {"neon": render_neon, "editorial": render_editorial, "photo": render_photo}


def render(style: str, spec: DesignSpec, bg_bytes: Optional[bytes], handle: str = "") -> bytes:
    style = style if style in RENDERERS else "photo"
    acc = accent_rgb(spec, style)
    bg = None
    if bg_bytes:
        try:
            bg = Image.open(io.BytesIO(bg_bytes))
            bg.load()
        except Exception:
            bg = None
    if bg is None:
        bg = fallback_bg(style, acc)
    out = RENDERERS[style](bg, spec, acc, handle).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92, optimize=True, progressive=True)
    return buf.getvalue()


def spec_from(data, fallback_headline: str) -> DesignSpec:
    """Gemini javobidagi dizayn maydonlarini xavfsiz DesignSpec ga aylantiradi."""
    g = (lambda k, d="": (getattr(data, k, None) if not isinstance(data, dict) else data.get(k)) or d)
    headline = uz(g("headline", fallback_headline))
    if len(headline) > 70:
        headline = headline[:70].rsplit(" ", 1)[0]
    points = [uz(p) for p in (g("points", []) or []) if str(p).strip()][:3]
    return DesignSpec(
        headline=headline or uz(fallback_headline)[:60],
        highlight=uz(g("highlight"))[:40],
        tag=uz(g("tag"))[:18],
        subline=uz(g("subline"))[:90],
        points=points,
        cta_bold=uz(g("cta_bold"))[:30],
        cta_rest=uz(g("cta_rest"))[:60],
        note=uz(g("note"))[:48],
        accent=str(g("accent")).lower().strip(),
    )
