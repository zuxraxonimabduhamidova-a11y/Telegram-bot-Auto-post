"""
SMM Post Agent — Telegram bot (Render uchun, 24/7)

Vazifa:
  • Har kuni belgilangan soatlarda (standart 09:00 va 19:00, Toshkent) Gemini orqali
    rasmli post tayyorlaydi.
  • Postni avval adminga yuboradi: ✅ Tasdiqlash / 🔄 Almashtirish / ❌ Bekor qilish.
  • 15 daqiqa ichida javob bo'lmasa — avtomatik kanalga chiqaradi.
  • Tayyorlash va yuklash paytida jonli soat animatsiyasi ko'rsatadi.

Xavfsizlik:
  • Barcha kalit/tokenlar FAQAT server muhit o'zgaruvchilarida (Render → Environment).
    Kodda hech qanday maxfiy qiymat yo'q.
  • Loglarda token va API kalit avtomatik yashiriladi (***).
  • Tugmalar va buyruqlar faqat ADMIN_IDS ro'yxatidagi foydalanuvchilarga ishlaydi.
  • Gemini matni HTML-escape qilinadi (injeksiya yo'q).
"""
from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import math
import os
import re
import secrets
import signal
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from aiohttp import ClientSession, ClientTimeout, web
from google import genai
from google.genai import types as gtypes
from pydantic import BaseModel
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import (
    BadRequest,
    Conflict,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
)

from prompts import IMAGE_STYLE, build_post_prompt

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("smmbot")


# ════════════════════════════ LOGGING (maxfiylarni yashirish) ════════════════════════════
def _secret_values() -> list[str]:
    vals = [os.getenv("BOT_TOKEN", ""), os.getenv("GEMINI_API_KEY", "")]
    out = []
    for v in vals:
        v = v.strip()
        if len(v) >= 8:
            out.append(v)
            if ":" in v:  # bot tokenining ikkinchi qismi alohida chiqsa ham
                out.append(v.split(":", 1)[1])
    return out


def redact(text: str) -> str:
    for s in _secret_values():
        text = text.replace(s, "***")
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(RedactingFormatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)
    # httpx so'rov URL'larida bot tokeni bo'ladi — INFO darajada umuman chiqarmaymiz
    for noisy in ("httpx", "httpcore", "apscheduler", "google_genai", "google", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ════════════════════════════ CONFIG ════════════════════════════
DEFAULT_TOPICS = [
    "Shaxsiy brend qurish: noldan boshlash",
    "Instagram orqali mijoz olish",
    "Sotuvni oshiradigan kontent formatlari",
]


@dataclass(frozen=True)
class Config:
    bot_token: str
    gemini_key: str
    admin_ids: frozenset
    channel_id: str
    channel_signature: str
    post_times: tuple
    tz: ZoneInfo
    approval_seconds: int
    text_model: str
    image_model: str
    post_max_chars: int
    max_regens: int
    data_dir: Path
    port: Optional[int]
    public_url: Optional[str]
    keep_alive: bool
    topics: tuple


def _parse_times(raw: str) -> tuple:
    out = []
    for part in re.split(r"[,\s;]+", raw.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", part)
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise SystemExit(f"❌ POST_TIMES noto'g'ri: {part!r} (masalan: 09:00,19:00)")
        out.append((int(m[1]), int(m[2])))
    if not out:
        raise SystemExit("❌ POST_TIMES bo'sh")
    return tuple(sorted(set(out)))


def _load_topics() -> tuple:
    env = os.getenv("TOPICS", "").strip()
    if env:
        items = [t.strip() for t in env.split(";") if t.strip()]
    else:
        f = BASE_DIR / "topics.txt"
        items = []
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append(line)
    return tuple(items or DEFAULT_TOPICS)


def load_config() -> Config:
    missing = [k for k in ("BOT_TOKEN", "GEMINI_API_KEY", "ADMIN_IDS") if not os.getenv(k, "").strip()]
    if missing:
        raise SystemExit("❌ Muhit o'zgaruvchilari o'rnatilmagan: " + ", ".join(missing))

    token = os.environ["BOT_TOKEN"].strip()
    if not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{30,}", token):
        raise SystemExit("❌ BOT_TOKEN formati noto'g'ri (BotFather bergan tokenni qo'ying)")

    try:
        admins = frozenset(int(x) for x in re.split(r"[,\s;]+", os.environ["ADMIN_IDS"].strip()) if x)
    except ValueError:
        raise SystemExit("❌ ADMIN_IDS faqat raqamlardan iborat bo'lsin, masalan: 123456789,987654321")
    if not admins:
        raise SystemExit("❌ ADMIN_IDS bo'sh")

    channel = os.getenv("CHANNEL_ID", "@marketingsotuv").strip()
    if not re.fullmatch(r"@[A-Za-z0-9_]{4,}|-100\d{5,}", channel):
        raise SystemExit("❌ CHANNEL_ID '@kanal' yoki '-100...' ko'rinishida bo'lsin")

    port = os.getenv("PORT", "").strip()
    data_dir = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        bot_token=token,
        gemini_key=os.environ["GEMINI_API_KEY"].strip(),
        admin_ids=admins,
        channel_id=channel,
        channel_signature=os.getenv("CHANNEL_SIGNATURE", channel if channel.startswith("@") else "").strip(),
        post_times=_parse_times(os.getenv("POST_TIMES", "09:00,19:00")),
        tz=ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent")),
        approval_seconds=max(60, int(float(os.getenv("APPROVAL_MINUTES", "15")) * 60)),
        text_model=os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash").strip(),
        image_model=os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip(),
        post_max_chars=int(os.getenv("POST_MAX_CHARS", "950")),
        max_regens=int(os.getenv("MAX_REGENERATIONS", "5")),
        data_dir=data_dir,
        port=int(port) if port.isdigit() else None,
        public_url=(os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").strip() or None,
        keep_alive=os.getenv("KEEP_ALIVE", "1").strip() not in ("0", "false", "no"),
        topics=_load_topics(),
    )


# ════════════════════════════ YORDAMCHI FUNKSIYALAR ════════════════════════════
def esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def tg_len(s: str) -> int:
    """Telegram belgilarni UTF-16 birliklarda sanaydi (emoji = 2)."""
    return len(s.encode("utf-16-le")) // 2


def strip_md(s: str) -> str:
    return s.replace("**", "")


def md_to_html(text: str) -> str:
    safe = esc(text.strip())
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe, flags=re.S)


def compose(text: str, signature: str) -> str:
    return f"{text.strip()}\n\n{signature}" if signature else text.strip()


def short_err(e: BaseException) -> str:
    msg = f"{type(e).__name__}: {e}"
    return redact(msg)[:180]


def _secs(v) -> float:
    return v.total_seconds() if isinstance(v, timedelta) else float(v)


async def tg_retry(factory: Callable[[], Awaitable], retry_timeouts: bool = True, attempts: int = 4):
    """Telegram so'rovini flood-limit va tarmoq xatolarida qayta yuboradi."""
    delay = 2.0
    for n in range(1, attempts + 1):
        try:
            return await factory()
        except RetryAfter as e:
            await asyncio.sleep(_secs(e.retry_after) + 1)
        except TimedOut:
            # Timeout'da xabar aslida yetib borgan bo'lishi mumkin — kanal uchun takrorlamaymiz
            if not retry_timeouts or n == attempts:
                raise
            await asyncio.sleep(delay)
            delay *= 2
        except NetworkError:
            if n == attempts:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    return await factory()


async def send_post(bot, chat_id, text: str, image: Optional[bytes], reply_markup=None,
                    retry_timeouts: bool = True) -> list[int]:
    """Postni yuboradi. Matn caption limitiga (1024) sig'masa — rasm + alohida matn."""
    body = md_to_html(text)
    plain = strip_md(text)
    if tg_len(plain) > 4000:
        plain = plain[:3990] + "…"
        body = esc(plain)
    no_preview = LinkPreviewOptions(is_disabled=True)

    if image:
        if tg_len(plain) <= 1024:
            m = await tg_retry(lambda: bot.send_photo(chat_id, photo=image, caption=body,
                                                      reply_markup=reply_markup), retry_timeouts)
            return [m.message_id]
        p = await tg_retry(lambda: bot.send_photo(chat_id, photo=image), retry_timeouts)
        m = await tg_retry(lambda: bot.send_message(chat_id, body, reply_markup=reply_markup,
                                                    link_preview_options=no_preview), retry_timeouts)
        return [p.message_id, m.message_id]
    m = await tg_retry(lambda: bot.send_message(chat_id, body, reply_markup=reply_markup,
                                                link_preview_options=no_preview), retry_timeouts)
    return [m.message_id]


# ════════════════════════════ HOLAT (STATE) ════════════════════════════
ACTIVE = ("generating", "pending", "publishing")


@dataclass
class Draft:
    id: str
    slot_key: str
    label: str
    topic: str
    status: str = "generating"
    text: str = ""
    hook: str = ""
    image_path: Optional[str] = None
    image_error: Optional[str] = None
    created: float = field(default_factory=time.time)
    deadline: float = 0.0
    regen_count: int = 0
    auto: bool = True
    admin_msgs: dict = field(default_factory=dict)  # "admin_id" -> [message_id, ...]

    def load_image(self) -> Optional[bytes]:
        if self.image_path and Path(self.image_path).exists():
            return Path(self.image_path).read_bytes()
        return None

    def save_image(self, data: Optional[bytes], folder: Path) -> None:
        self.remove_image()
        if data:
            p = folder / f"{self.id}-{self.regen_count}.png"
            p.write_bytes(data)
            self.image_path = str(p)

    def remove_image(self) -> None:
        if self.image_path:
            with suppress(OSError):
                Path(self.image_path).unlink()
        self.image_path = None


class Store:
    """Kichik JSON holat fayli (atomik yoziladi)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"topic_idx": 0, "handled": [], "hooks": [], "pending": None}

    def load(self) -> None:
        try:
            if self.path.exists():
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception as e:  # buzilgan fayl botni to'xtatmasin
            log.warning("Holat faylini o'qib bo'lmadi, yangidan boshlanadi: %s", e)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def is_handled(self, key: str) -> bool:
        return key in self.data["handled"]

    def mark(self, key: str) -> None:
        if key not in self.data["handled"]:
            self.data["handled"] = (self.data["handled"] + [key])[-60:]

    def unmark(self, key: str) -> None:
        self.data["handled"] = [k for k in self.data["handled"] if k != key]

    def add_hook(self, hook: str) -> None:
        if hook:
            self.data["hooks"] = (self.data["hooks"] + [hook[:150]])[-20:]


# ════════════════════════════ GEMINI ════════════════════════════
class PostOut(BaseModel):
    hook: str
    post: str
    image_prompt: str


class ContentEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = genai.Client(api_key=cfg.gemini_key)

    async def _call(self, what: str, fn: Callable[[], Awaitable], attempts: int = 3, timeout: float = 150):
        delay, last = 3.0, None
        for n in range(1, attempts + 1):
            try:
                return await asyncio.wait_for(fn(), timeout)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last = e
                log.warning("%s: %d-urinish muvaffaqiyatsiz — %s", what, n, short_err(e))
                if n < attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
        raise RuntimeError(f"{what} xatosi — {short_err(last)}") from last

    @staticmethod
    def _clean(text: str) -> str:
        text = text.replace("\r\n", "\n").strip()
        lines = [ln.rstrip() for ln in text.split("\n")]
        # model imzo yoki hashtag qo'shib yuborsa — olib tashlaymiz
        while lines and (re.fullmatch(r"\s*(@\w+|#\w+(\s+#\w+)*)\s*", lines[-1]) or not lines[-1].strip()):
            lines.pop()
        text = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", text)

    @staticmethod
    def _parse(resp) -> PostOut:
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, PostOut):
            return parsed
        raw = (resp.text or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        return PostOut.model_validate_json(raw)

    async def write_post(self, topic: str, recent: list[str]) -> tuple[str, str, str]:
        sig_len = tg_len(self.cfg.channel_signature) + 2
        limit = self.cfg.post_max_chars
        prompt = build_post_prompt(topic, recent, limit)
        conf = gtypes.GenerateContentConfig(
            temperature=0.95,
            response_mime_type="application/json",
            response_schema=PostOut,
        )
        text = hook = img = ""
        for attempt in range(3):
            resp = await self._call(
                "Matn", lambda: self.client.aio.models.generate_content(
                    model=self.cfg.text_model, contents=prompt, config=conf))
            out = self._parse(resp)
            text, hook, img = self._clean(out.post), out.hook.strip(), out.image_prompt.strip()
            if not text:
                continue
            if tg_len(strip_md(text)) + sig_len <= 1024:
                break
            prompt += (f"\n\nDIQQAT: oldingi variant {tg_len(text)} belgi — juda uzun. "
                       f"Qisqaroq yoz, {limit - 100} belgidan oshirma!")
        if not text:
            raise RuntimeError("Model bo'sh matn qaytardi")
        return text, img or topic, hook or strip_md(text.split("\n", 1)[0])

    async def draw(self, scene: str) -> bytes:
        kw = {"response_modalities": ["TEXT", "IMAGE"]}
        if hasattr(gtypes, "ImageConfig"):
            kw["image_config"] = gtypes.ImageConfig(aspect_ratio="4:3")
        conf = gtypes.GenerateContentConfig(**kw)
        prompt = IMAGE_STYLE.format(scene=scene)

        async def go() -> bytes:
            r = await self.client.aio.models.generate_content(
                model=self.cfg.image_model, contents=prompt, config=conf)
            for c in (r.candidates or []):
                parts = c.content.parts if c.content and c.content.parts else []
                for p in parts:
                    data = getattr(getattr(p, "inline_data", None), "data", None)
                    if data:
                        return base64.b64decode(data) if isinstance(data, str) else data
            raise RuntimeError("model rasm qaytarmadi")

        return await self._call("Rasm", go, attempts=3, timeout=180)


# ════════════════════════════ SOAT ANIMATSIYASI ════════════════════════════
class Spinner:
    """Uzoq jarayon paytida adminga jonli soat + progress ko'rsatadi."""
    FRAMES = ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛"]
    BAR = 8

    def __init__(self, bot, chat_ids, title: str, action=ChatAction.UPLOAD_PHOTO, interval: float = 2.0):
        self.bot, self.chat_ids, self.title = bot, list(chat_ids), title
        self.action, self.interval = action, interval
        self.stage = "⏳ Boshlanmoqda…"
        self.msgs: dict = {}
        self.t0 = 0.0
        self.task: Optional[asyncio.Task] = None

    def _render(self, i: int) -> str:
        el = int(time.monotonic() - self.t0)
        pos = i % self.BAR
        bar = "".join("▰" if j <= pos else "▱" for j in range(self.BAR))
        return (f"{self.FRAMES[i % 12]} <b>{esc(self.title)}</b>\n{esc(self.stage)}\n\n"
                f"{bar}  ⏱ {el // 60:02d}:{el % 60:02d}\n<i>Bot ishlayapti, biroz kuting…</i>")

    async def __aenter__(self):
        self.t0 = time.monotonic()
        for cid in self.chat_ids:
            try:
                m = await self.bot.send_message(cid, self._render(0), disable_notification=True)
                self.msgs[cid] = m.message_id
                await self.bot.send_chat_action(cid, self.action)
            except TelegramError as e:
                log.debug("Spinner yuborilmadi %s: %s", cid, e)
        self.task = asyncio.create_task(self._loop())
        return self

    async def _loop(self):
        i = 0
        while True:
            await asyncio.sleep(self.interval)
            i += 1
            for cid, mid in list(self.msgs.items()):
                try:
                    await self.bot.edit_message_text(self._render(i), chat_id=cid, message_id=mid)
                    if i % 2 == 0:
                        await self.bot.send_chat_action(cid, self.action)
                except RetryAfter as e:
                    await asyncio.sleep(_secs(e.retry_after))
                except TelegramError:
                    pass

    async def __aexit__(self, *exc):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        for cid, mid in self.msgs.items():
            with suppress(TelegramError):
                await self.bot.delete_message(cid, mid)
        return False


# ════════════════════════════ ASOSIY MANTIQ ════════════════════════════
class PostManager:
    def __init__(self, app, cfg: Config, store: Store, engine: ContentEngine):
        self.app, self.cfg, self.store, self.engine = app, cfg, store, engine
        self.lock = asyncio.Lock()
        self.draft: Optional[Draft] = None
        self.timer: Optional[asyncio.Task] = None
        self.started = time.time()
        self.channel_problem: Optional[str] = None

    @property
    def bot(self):
        return self.app.bot

    # ---------- yordamchilar ----------
    def _spawn(self, coro):
        return asyncio.create_task(coro)

    def _persist(self) -> None:
        d = self.draft
        self.store.data["pending"] = asdict(d) if d and d.status in ACTIVE else None
        try:
            self.store.save()
        except OSError as e:
            log.error("Holat saqlanmadi: %s", e)

    def next_topic(self) -> str:
        topics = self.cfg.topics
        i = int(self.store.data.get("topic_idx", 0)) % len(topics)
        self.store.data["topic_idx"] = i + 1
        return topics[i]

    async def notify(self, text: str, **kw) -> None:
        for aid in self.cfg.admin_ids:
            try:
                await tg_retry(lambda: self.bot.send_message(aid, text, **kw))
            except TelegramError as e:
                log.warning("Admin %s ga xabar yetmadi: %s", aid, e)

    def _link(self, message_id: int) -> Optional[str]:
        ch = self.cfg.channel_id
        if ch.startswith("@"):
            return f"https://t.me/{ch[1:]}/{message_id}"
        if ch.startswith("-100"):
            return f"https://t.me/c/{ch[4:]}/{message_id}"
        return None

    def _kb(self, d: Draft) -> InlineKeyboardMarkup:
        if d.auto:
            left = max(1, math.ceil((d.deadline - time.time()) / 60))
            info = f"⏱ {left} daqiqadan so'ng avtomatik chiqadi"
        else:
            info = "⏸ Avtomatik chiqish o'chirilgan"
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ok:{d.id}"),
             InlineKeyboardButton("🔄 Almashtirish", callback_data=f"re:{d.id}")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"no:{d.id}")],
            [InlineKeyboardButton(info, callback_data="noop")],
        ])

    async def _set_keyboards(self, d: Draft, markup) -> None:
        for aid, ids in d.admin_msgs.items():
            if not ids:
                continue
            try:
                await tg_retry(lambda: self.bot.edit_message_reply_markup(
                    chat_id=int(aid), message_id=ids[-1], reply_markup=markup))
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    log.debug("Klaviatura yangilanmadi: %s", e)
            except TelegramError as e:
                log.debug("Klaviatura yangilanmadi: %s", e)

    async def _delete_admin_msgs(self, d: Draft) -> None:
        for aid, ids in d.admin_msgs.items():
            for mid in ids:
                with suppress(TelegramError):
                    await self.bot.delete_message(int(aid), mid)
        d.admin_msgs = {}

    def _start_timer(self, d: Draft) -> None:
        self._stop_timer()
        if d.auto:
            self.timer = self._spawn(self._countdown(d.id))

    def _stop_timer(self) -> None:
        t, self.timer = self.timer, None
        if t and not t.done() and t is not asyncio.current_task():
            t.cancel()

    async def _countdown(self, did: str) -> None:
        try:
            while True:
                d = self.draft
                if not d or d.id != did or d.status != "pending":
                    return
                rem = d.deadline - time.time()
                if rem <= 0:
                    break
                step = rem % 60 or 60
                await asyncio.sleep(min(step, rem))
                d = self.draft
                if d and d.id == did and d.status == "pending" and d.deadline - time.time() > 1:
                    await self._set_keyboards(d, self._kb(d))
            await self.publish(did, by=None)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Taymer xatosi")

    async def _build(self, topic: str, sp: Spinner) -> tuple[str, str, Optional[bytes], Optional[str]]:
        last: Optional[Exception] = None
        for attempt in range(2):
            try:
                sp.stage = "✍️ Matn yozilmoqda…" if attempt == 0 else "🔁 Qayta urinilmoqda: matn…"
                text, scene, hook = await self.engine.write_post(topic, self.store.data.get("hooks", []))
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last = e
                if attempt == 0:
                    sp.stage = "⚠️ Gemini javob bermadi, 30 soniyadan so'ng qayta urinaman…"
                    await asyncio.sleep(30)
        else:
            raise last or RuntimeError("Matn yaratilmadi")

        sp.stage = "🎨 Rasm chizilmoqda…"
        img, err = None, None
        try:
            img = await self.engine.draw(scene)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err = short_err(e)
            log.warning("Rasm yaratilmadi: %s", err)
        sp.stage = "📦 Yakunlanmoqda…"
        return text, hook, img, err

    async def _present(self, d: Draft, keep_deadline: bool = False) -> None:
        if not keep_deadline or not d.deadline:
            d.deadline = time.time() + self.cfg.approval_seconds
        img = d.load_image()
        mins = max(1, math.ceil((d.deadline - time.time()) / 60))
        header = (f"📝 <b>Yangi post tayyor</b> — {esc(d.label)}\n"
                  f"🏷 Mavzu: {esc(d.topic)}\n"
                  f"🔄 Almashtirish: {d.regen_count}/{self.cfg.max_regens}\n")
        if not img:
            header += f"⚠️ Rasm yaratilmadi ({esc(d.image_error or 'nomaʼlum')}). Post rasmsiz chiqadi.\n"
        header += (f"\n⏱ {mins} daqiqa ichida javob bo'lmasa — avtomatik kanalga chiqadi."
                   if d.auto else "\n⏸ Bu post uchun avtomatik chiqish o'chirilgan.")

        full = compose(d.text, self.cfg.channel_signature)
        d.admin_msgs = {}
        for aid in self.cfg.admin_ids:
            ids: list[int] = []
            try:
                h = await tg_retry(lambda: self.bot.send_message(aid, header))
                ids.append(h.message_id)
                ids += await send_post(self.bot, aid, full, img, reply_markup=self._kb(d))
            except TelegramError as e:
                log.error("Admin %s ga preview yuborilmadi: %s", aid, e)
            if ids:
                d.admin_msgs[str(aid)] = ids
        if not d.admin_msgs:
            log.error("Preview hech bir adminga yetmadi — taymer baribir ishlaydi")
        async with self.lock:
            d.status = "pending"
            self._persist()
        self._start_timer(d)

    # ---------- asosiy amallar ----------
    async def run_slot(self, slot_key: str, label: str) -> None:
        busy = False
        async with self.lock:
            if self.draft and self.draft.status in ACTIVE:
                busy = True
            elif self.store.is_handled(slot_key):
                return
            else:
                self.store.mark(slot_key)
                d = Draft(id=secrets.token_hex(6), slot_key=slot_key, label=label, topic=self.next_topic())
                self.draft = d
                self._persist()
        if busy:
            await self.notify(f"⏭ {esc(label)} posti o'tkazib yuborildi: oldingi post hali jarayonda.")
            return

        log.info("Post tayyorlanmoqda: %s | %s", label, d.topic)
        try:
            async with Spinner(self.bot, self.cfg.admin_ids, f"Post tayyorlanmoqda — {label}") as sp:
                text, hook, img, err = await self._build(d.topic, sp)
        except Exception as e:
            log.exception("Post yaratilmadi")
            async with self.lock:
                self.draft = None
                self._persist()
            await self.notify(f"⚠️ <b>{esc(label)} posti tayyorlanmadi.</b>\n{esc(short_err(e))}\n\n"
                              "Qayta urinish uchun: /now")
            return

        d.text, d.hook, d.image_error = text, hook, err
        d.save_image(img, self.cfg.data_dir)
        await self._present(d)

    async def publish(self, did: str, by: Optional[str]) -> None:
        async with self.lock:
            d = self.draft
            if not d or d.id != did or d.status != "pending":
                return
            d.status = "publishing"
            self._stop_timer()
            self._persist()
        await self._set_keyboards(d, None)
        how = f"tasdiqladi: {esc(by)}" if by else "avtomatik (javob bo'lmadi)"
        log.info("Kanalga chiqarilmoqda (%s)", "admin" if by else "avto")
        try:
            async with Spinner(self.bot, [int(a) for a in d.admin_msgs] or self.cfg.admin_ids,
                               "Kanalga yuklanmoqda") as sp:
                sp.stage = f"📤 {self.cfg.channel_id} ga yuborilmoqda…"
                ids = await send_post(self.bot, self.cfg.channel_id,
                                      compose(d.text, self.cfg.channel_signature),
                                      d.load_image(), retry_timeouts=False)
        except Exception as e:
            log.exception("Kanalga chiqarilmadi")
            async with self.lock:
                d.status, d.auto = "pending", True
                d.deadline = time.time() + 5 * 60
                self._persist()
            await self._set_keyboards(d, self._kb(d))
            await self.notify(f"⚠️ <b>Kanalga chiqarib bo'lmadi</b>\n{esc(short_err(e))}\n\n"
                              "Bot kanalda admin ekanini va «Post yozish» huquqi borligini tekshiring. "
                              "5 daqiqadan so'ng qayta urinaman yoki ✅ ni bosing.")
            self._start_timer(d)
            return

        link = self._link(ids[0])
        async with self.lock:
            d.status = "published"
            self.store.add_hook(d.hook)
            self.draft = None
            self._persist()
        d.remove_image()
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Kanalda ko'rish", url=link)]]) if link else None
        await self._set_keyboards(d, markup)
        await self.notify(f"✅ <b>Kanalga chiqdi</b> — {how}", reply_markup=markup)

    async def cancel(self, did: str, by: str) -> None:
        async with self.lock:
            d = self.draft
            if not d or d.id != did or d.status != "pending":
                return
            d.status = "cancelled"
            self._stop_timer()
            self.draft = None
            self._persist()
        d.remove_image()
        await self._set_keyboards(d, None)
        await self.notify(f"❌ <b>Bekor qilindi</b> ({esc(by)}). {esc(d.label)} posti kanalga chiqmaydi.")

    async def regenerate(self, did: str, by: str) -> None:
        async with self.lock:
            d = self.draft
            if not d or d.id != did or d.status != "pending" or d.regen_count >= self.cfg.max_regens:
                return
            d.status = "generating"
            self._stop_timer()
            self._persist()
        await self._set_keyboards(d, None)
        log.info("Almashtirish so'raldi (%s)", by)
        try:
            async with Spinner(self.bot, self.cfg.admin_ids, "Yangi variant tayyorlanmoqda") as sp:
                topic = self.next_topic()
                text, hook, img, err = await self._build(topic, sp)
        except Exception as e:
            log.exception("Yangi variant yaratilmadi")
            async with self.lock:
                d.status = "pending"
                d.deadline = max(d.deadline, time.time() + 5 * 60)
                self._persist()
            await self._set_keyboards(d, self._kb(d))
            self._start_timer(d)
            await self.notify(f"⚠️ Yangi variant yaratilmadi: {esc(short_err(e))}\nOldingi variant kuchda.")
            return

        await self._delete_admin_msgs(d)
        d.regen_count += 1
        d.topic, d.text, d.hook, d.image_error = topic, text, hook, err
        d.save_image(img, self.cfg.data_dir)
        await self._present(d)
        if len(self.cfg.admin_ids) > 1:
            await self.notify(f"ℹ️ Post {esc(by)} tomonidan almashtirildi.", disable_notification=True)

    # ---------- ishga tushish ----------
    async def check_channel(self) -> Optional[str]:
        try:
            me = await self.bot.get_me()
            mem = await self.bot.get_chat_member(self.cfg.channel_id, me.id)
            if mem.status != "administrator":
                return "Bot kanalda admin emas"
            if getattr(mem, "can_post_messages", True) is False:
                return "Botda «Post yozish» huquqi yo'q"
            return None
        except TelegramError as e:
            return f"Kanalni tekshirib bo'lmadi: {e}"

    async def restore(self) -> None:
        p = self.store.data.get("pending")
        if not p:
            return
        try:
            d = Draft(**p)
        except TypeError:
            self.store.data["pending"] = None
            return
        if d.status == "generating" or not d.text:
            # yaratish paytida restart bo'lgan — catch-up qayta ishga tushiradi
            self.store.unmark(d.slot_key)
            self.store.data["pending"] = None
            self.store.save()
            return
        await self._set_keyboards(d, None)
        with suppress(Exception):
            await self._delete_admin_msgs(d)
        if d.status == "publishing":
            # kanalga chiqqan-chiqmagani noma'lum — takror chiqmasligi uchun admin qaror qiladi
            d.auto = False
            await self.notify("⚠️ Restart paytida post kanalga yuklanayotgan edi. "
                              "Kanalni tekshiring: chiqmagan bo'lsa ✅, chiqqan bo'lsa ❌ bosing.")
        d.status = "generating"
        self.draft = d
        if d.auto and d.deadline and d.deadline <= time.time():
            d.deadline = time.time() + 60  # restartdan keyin 1 daqiqa imkon
        log.info("Kutilayotgan post tiklandi: %s", d.label)
        await self._present(d, keep_deadline=True)

    async def catch_up(self) -> None:
        """Restart sabab o'tib ketgan slotni (30 daqiqagacha) bajaradi."""
        now = datetime.now(self.cfg.tz)
        for h, m in self.cfg.post_times:
            slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if timedelta(0) <= now - slot <= timedelta(minutes=30):
                key = f"{now:%Y-%m-%d} {h:02d}:{m:02d}"
                if not self.store.is_handled(key):
                    log.info("O'tib ketgan slot bajarilmoqda: %s", key)
                    self._spawn(self.run_slot(key, f"{h:02d}:{m:02d}"))

    async def _slot_job(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        hm = ctx.job.data
        key = f"{datetime.now(self.cfg.tz):%Y-%m-%d} {hm}"
        self._spawn(self.run_slot(key, hm))

    def schedule(self) -> None:
        jq = self.app.job_queue
        for h, m in self.cfg.post_times:
            jq.run_daily(self._slot_job, time=dtime(h, m, tzinfo=self.cfg.tz),
                         name=f"slot {h:02d}:{m:02d}", data=f"{h:02d}:{m:02d}",
                         job_kwargs={"misfire_grace_time": 900, "coalesce": True})

    def next_run(self) -> str:
        now = datetime.now(self.cfg.tz)
        cands = []
        for h, m in self.cfg.post_times:
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            cands.append(t if t > now else t + timedelta(days=1))
        return min(cands).strftime("%d.%m %H:%M")

    async def on_startup(self) -> None:
        self.store.load()
        self.channel_problem = await self.check_channel()
        await self.restore()
        self.schedule()
        await self.catch_up()
        with suppress(TelegramError):
            await self.bot.set_my_commands([
                BotCommand("start", "Yordam"),
                BotCommand("now", "Hozir post tayyorlash"),
                BotCommand("status", "Holat"),
                BotCommand("topics", "Mavzular ro'yxati"),
            ])
        msg = f"🟢 Bot ishga tushdi. Keyingi post: <b>{self.next_run()}</b>"
        if self.channel_problem:
            msg += f"\n\n⚠️ {esc(self.channel_problem)}\nBotni {esc(self.cfg.channel_id)} kanaliga admin qiling."
        await self.notify(msg, disable_notification=True)
        log.info("Tayyor. Slotlar: %s | Kanal: %s", self.cfg.post_times, self.cfg.channel_id)


# ════════════════════════════ HANDLERLAR ════════════════════════════
def _mgr(ctx: ContextTypes.DEFAULT_TYPE) -> PostManager:
    return ctx.application.bot_data["mgr"]


def _is_admin(ctx, uid: int) -> bool:
    return uid in _mgr(ctx).cfg.admin_ids


HELP = (
    "🤖 <b>SMM Post Agent</b>\n\n"
    "Har kuni <b>{times}</b> da ({tz}) kanal uchun rasmli post tayyorlayman va sizga yuboraman:\n"
    "✅ Tasdiqlash — darhol kanalga chiqadi\n"
    "🔄 Almashtirish — yangi variant tayyorlanadi\n"
    "❌ Bekor qilish — shu vaqtdagi post chiqmaydi\n"
    "⏱ {mins} daqiqa javob bo'lmasa — avtomatik chiqadi\n\n"
    "Buyruqlar:\n/now — hozir post tayyorlash\n/status — holat\n/topics — mavzular"
)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if not u or not update.effective_message:
        return
    if not _is_admin(ctx, u.id):
        await update.effective_message.reply_text(
            f"👋 Salom! Bu bot yopiq, faqat adminlar uchun.\nSizning ID: <code>{u.id}</code>")
        return
    cfg = _mgr(ctx).cfg
    times = ", ".join(f"{h:02d}:{m:02d}" for h, m in cfg.post_times)
    await update.effective_message.reply_text(
        HELP.format(times=times, tz=cfg.tz.key, mins=cfg.approval_seconds // 60))


async def cmd_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if not u or not _is_admin(ctx, u.id):
        return
    mgr = _mgr(ctx)
    if mgr.draft and mgr.draft.status in ACTIVE:
        await update.effective_message.reply_text("⏳ Hozir bitta post jarayonda. Avval unga javob bering.")
        return
    mgr._spawn(mgr.run_slot(f"manual-{int(time.time())}", "qo'lda (/now)"))


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if not u or not _is_admin(ctx, u.id):
        return
    mgr = _mgr(ctx)
    cfg = mgr.cfg
    mgr.channel_problem = await mgr.check_channel()
    up = int(time.time() - mgr.started)
    d = mgr.draft
    state = "yo'q"
    if d:
        state = {"generating": "tayyorlanmoqda", "pending": "tasdiq kutmoqda",
                 "publishing": "kanalga yuklanmoqda"}.get(d.status, d.status)
        if d.status == "pending" and d.auto:
            state += f" (≈{max(0, math.ceil((d.deadline - time.time()) / 60))} daq qoldi)"
    await update.effective_message.reply_text(
        f"📊 <b>Holat</b>\n"
        f"🟢 Ishlayapti: {up // 3600} soat {up % 3600 // 60} daq\n"
        f"📅 Keyingi post: {mgr.next_run()}\n"
        f"📝 Joriy post: {esc(state)}\n"
        f"📣 Kanal: {esc(cfg.channel_id)} — {'✅ OK' if not mgr.channel_problem else '⚠️ ' + esc(mgr.channel_problem)}\n"
        f"🧠 Matn modeli: <code>{esc(cfg.text_model)}</code>\n"
        f"🎨 Rasm modeli: <code>{esc(cfg.image_model)}</code>")


async def cmd_topics(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    if not u or not _is_admin(ctx, u.id):
        return
    mgr = _mgr(ctx)
    topics = mgr.cfg.topics
    nxt = int(mgr.store.data.get("topic_idx", 0)) % len(topics)
    lines = [("👉 " if i == nxt else "• ") + esc(t) for i, t in enumerate(topics)]
    await update.effective_message.reply_text("🏷 <b>Mavzular</b> (👉 — navbatdagi):\n\n" + "\n".join(lines))


CB_RE = re.compile(r"(ok|re|no):([0-9a-f]{12})")


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    if not _is_admin(ctx, q.from_user.id):
        await q.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    if q.data == "noop":
        await q.answer("Shu vaqt ichida javob bo'lmasa, post avtomatik chiqadi.")
        return
    m = CB_RE.fullmatch(q.data or "")
    if not m:
        await q.answer()
        return
    action, did = m.groups()
    mgr = _mgr(ctx)
    d = mgr.draft
    if not d or d.id != did:
        await q.answer("Bu post eskirgan.", show_alert=True)
        with suppress(TelegramError):
            await q.edit_message_reply_markup(None)
        return
    if d.status != "pending":
        await q.answer("⏳ Jarayon ketmoqda, biroz kuting…")
        return
    who = q.from_user.full_name or str(q.from_user.id)
    if action == "ok":
        await q.answer("✅ Kanalga yuklanmoqda…")
        mgr._spawn(mgr.publish(did, by=who))
    elif action == "re":
        if d.regen_count >= mgr.cfg.max_regens:
            await q.answer(f"Almashtirish limiti tugadi ({mgr.cfg.max_regens}). Tasdiqlang yoki bekor qiling.",
                           show_alert=True)
            return
        await q.answer("🔄 Yangi variant tayyorlanmoqda…")
        mgr._spawn(mgr.regenerate(did, by=who))
    else:
        await q.answer("❌ Bekor qilindi")
        mgr._spawn(mgr.cancel(did, by=who))


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    err = ctx.error
    if isinstance(err, Conflict):
        log.warning("Boshqa nusxa ham ishlayapti (deploy paytida bir necha soniya normal holat).")
        return
    if isinstance(err, (TimedOut, NetworkError)):
        log.warning("Tarmoq xatosi: %s", short_err(err))
        return
    log.error("Kutilmagan xato: %s", short_err(err), exc_info=err)


# ════════════════════════════ HEALTH SERVER (Render) ════════════════════════════
async def start_web(port: int, mgr: PostManager) -> web.AppRunner:
    async def health(_req):
        return web.json_response({"ok": True, "uptime_s": int(time.time() - mgr.started),
                                  "pending": bool(mgr.draft)})

    wapp = web.Application()
    wapp.router.add_get("/", health)
    wapp.router.add_get("/health", health)
    runner = web.AppRunner(wapp, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Health server: :%s/health", port)
    return runner


async def keep_alive(url: str) -> None:
    """Render bepul tarifida 15 daqiqa so'rovsiz qolsa uxlaydi — o'zimizni ping qilamiz."""
    target = url.rstrip("/") + "/health"
    async with ClientSession(timeout=ClientTimeout(total=20)) as s:
        while True:
            await asyncio.sleep(600)
            try:
                async with s.get(target) as r:
                    await r.read()
            except Exception as e:
                log.debug("keep-alive: %s", e)


# ════════════════════════════ MAIN ════════════════════════════
async def main() -> None:
    cfg = load_config()
    store = Store(cfg.data_dir / "state.json")
    engine = ContentEngine(cfg)

    app = (ApplicationBuilder()
           .token(cfg.bot_token)
           .defaults(Defaults(parse_mode=ParseMode.HTML, tzinfo=cfg.tz))
           .connect_timeout(20).read_timeout(60).write_timeout(120).pool_timeout(30)
           .media_write_timeout(180)
           .get_updates_read_timeout(45)
           .build())
    mgr = PostManager(app, cfg, store, engine)
    app.bot_data["mgr"] = mgr
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("topics", cmd_topics))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    runner = await start_web(cfg.port, mgr) if cfg.port else None
    ka = asyncio.create_task(keep_alive(cfg.public_url)) if (cfg.port and cfg.public_url and cfg.keep_alive) else None

    async with app:
        await app.start()
        await app.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            bootstrap_retries=-1, timeout=30)
        await mgr.on_startup()
        await stop.wait()
        log.info("To'xtatish signali olindi, holat saqlanmoqda…")
        mgr._stop_timer()
        mgr._persist()
        await app.updater.stop()
        await app.stop()

    if ka:
        ka.cancel()
    if runner:
        await runner.cleanup()


def run() -> None:
    setup_logging()
    backoff = 5
    while True:
        try:
            asyncio.run(main())
            break  # SIGTERM bilan normal to'xtadi
        except SystemExit:
            raise
        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("Bot yiqildi — %s soniyadan so'ng qayta ishga tushadi", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)


if __name__ == "__main__":
    run()
