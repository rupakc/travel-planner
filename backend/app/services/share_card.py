"""Share card renderer (Phase 4): a PNG drawn from a public snapshot.

Pure Pillow, no network. The snapshot comes from
``share_public.build_snapshot`` so it can never carry exact dates. Colours are
a fixed brand palette copied from ``frontend/design/tokens.json`` (a test keeps
them in sync).

Languages: cards render in en es de fr hi zh bn (``lang``). Strings come from
``share_card_i18n``; fonts are OFL Noto subsets in ``app/assets/fonts`` (see
``scripts/build_card_fonts.py``). Devanagari and Bengali need complex-text
shaping (libraqm); where Pillow has no raqm the hi/bn cards degrade to the
English card (Latin font, never tofu). Any user text (place, name) with a glyph
the fonts lack is dropped, never drawn as a box.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

from cachetools import TTLCache
from PIL import Image, ImageDraw, ImageFont, features

from . import share_card_i18n as i18n
from .share_public import clip_headline

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"

SIZES = {"link": (1200, 630), "story": (1080, 1920)}
BRAND = "Voyager"

# Copied from frontend/design/tokens.json (palette.teal / gray).
PALETTE = {
    "bg": "#0f766e",  # teal.700
    "bg_dark": "#115e59",  # teal.800
    "text": "#ffffff",
    "muted": "#ccfbf1",  # teal.100
    "chip": "#134e4a",  # teal.900
    "chip_text": "#f0fdfa",  # teal.50
}

RENDER_WAIT_S = 5.0
_render_slots = threading.BoundedSemaphore(2)


class RenderBusy(Exception):
    """Too many renders in flight (the route answers 503)."""


_cache: TTLCache = TTLCache(maxsize=256, ttl=600)
_lock = threading.Lock()


# --- fonts -----------------------------------------------------------------

LATIN_FILE = "noto-sans-latin.ttf"
NATIVE = {  # lang -> (font file, predicate for characters drawn with it)
    "hi": ("noto-sans-devanagari.ttf", lambda c: 0x900 <= ord(c) <= 0x97F),
    "bn": ("noto-sans-bengali.ttf", lambda c: 0x980 <= ord(c) <= 0x9FF),
    "zh": (
        "noto-sans-sc.ttf",
        lambda c: 0x2E80 <= ord(c) <= 0x9FFF or 0xFF00 <= ord(c) <= 0xFFEF,
    ),
}
COMPLEX_SCRIPTS = ("hi", "bn")  # need libraqm for correct shaping


def raqm_available() -> bool:
    return bool(features.check("raqm"))


@lru_cache(maxsize=1)
def _coverage() -> dict[str, frozenset[int]]:
    raw = json.loads((FONT_DIR / "coverage.json").read_text())
    return {
        name: frozenset(c for lo, hi in ranges for c in range(lo, hi + 1))
        for name, ranges in raw.items()
    }


@lru_cache(maxsize=64)
def _truetype(file: str, size: int, raqm: bool):
    engine = ImageFont.Layout.RAQM if raqm else ImageFont.Layout.BASIC
    return ImageFont.truetype(str(FONT_DIR / file), size, layout_engine=engine)


class Face:
    """A Latin font plus, for hi/bn/zh, the script's font, at one size."""

    def __init__(self, lang: str, size: int):
        raqm = raqm_available()
        self.size = size
        self.latin = _truetype(LATIN_FILE, size, raqm)
        self.native_file = None
        self.is_native = lambda c: False
        self.native = None
        if lang in NATIVE:
            self.native_file, self.is_native = NATIVE[lang]
            self.native = _truetype(self.native_file, size, raqm)
        self.ascent = self.latin.getmetrics()[0]

    def runs(self, text: str):
        """Split ``text`` into (chunk, font) runs, one font per script."""
        out: list[list] = []
        for ch in text:
            f = self.native if self.native and self.is_native(ch) else self.latin
            if out and out[-1][1] is f:
                out[-1][0] += ch
            else:
                out.append([ch, f])
        return out


def supported(text: str, lang: str) -> bool:
    """True when every character of ``text`` has a glyph in the font it would
    be drawn with (so a card never shows tofu)."""
    cov = _coverage()
    native = NATIVE.get(lang)
    for ch in text:
        if unicodedata.category(ch).startswith("C") and ch not in "‌‍":
            return False
        file = native[0] if native and native[1](ch) else LATIN_FILE
        if ord(ch) not in cov[file]:
            return False
    return True


def effective_lang(lang: str | None) -> str:
    """The language actually drawn: hi/bn fall back to English without raqm."""
    lang = i18n.norm_lang(lang)
    if lang in COMPLEX_SCRIPTS and not raqm_available():
        return i18n.DEFAULT_LANG
    return lang


# --- text pieces -------------------------------------------------------------


def month_label(period: str | None, lang: str = "en") -> str | None:
    """``2026-04`` -> ``April 2026``; anything else -> None."""
    try:
        d = date.fromisoformat(f"{period}-01")
    except (TypeError, ValueError):
        return None
    t = i18n.STRINGS[i18n.norm_lang(lang)]
    return t["month_fmt"].format(month=t["months"][d.month - 1], year=d.year)


def stat_text(stat: dict, lang: str = "en") -> str:
    t = i18n.STRINGS[i18n.norm_lang(lang)]
    n = int(stat.get("count") or 0)
    one, many = t["stats"].get(stat.get("key"), (stat.get("key"),) * 2)
    return t["stat_fmt"].format(n=n, label=one if n == 1 else many)


def _drawable(text: str) -> bool:
    return supported(text, "en")


def safe_headline(snapshot: dict) -> str:
    """The (English) headline, or a plain one if it needs glyphs we lack."""
    head = clip_headline(snapshot.get("headline") or "")
    if head and _drawable(head):
        return head
    kind = snapshot.get("kind")
    days = snapshot.get("days")
    if kind == "savings":
        return "Watching prices for my next trip"
    if kind == "recap":
        return "My trip: recap"
    if kind == "quiz":
        return "My Voyager quiz score"
    if kind == "status":
        return "On a trip"
    if isinstance(days, int) and days > 0:
        return f"{days} day{'s' if days != 1 else ''} away"
    return "My trip"


def localized_headline(snapshot: dict, lang: str) -> str:
    """The headline re-worded from the snapshot's structured fields. A place
    the fonts cannot draw is left out (the headline then has no place)."""
    t = i18n.STRINGS[lang]
    kind = snapshot.get("kind")
    hl = snapshot.get("hl") or {}
    place = snapshot.get("destination")
    if not (isinstance(place, str) and place and supported(place, lang)):
        place = None
    days = snapshot.get("days")
    if kind == "savings":
        total = float(hl.get("total_usd") or 0)
        if total > 0:
            amt = f"${total:,.0f}" if total.is_integer() else f"${total:,.2f}"
            return t["savings_total"].format(amount=amt)
        return t["savings_watch"]
    if kind == "quiz":
        label = (
            t["quiz_daily"]
            if hl.get("mode") == "daily"
            else t["quiz_packs"].get(hl.get("pack"), t["quiz"])
        )
        total = int(hl.get("total") or 0)
        if not total:
            return label
        return t["quiz_score"].format(
            label=label, correct=int(hl.get("correct") or 0), total=total
        )
    if kind == "status":
        day = hl.get("day")
        if day and place:
            return t["status_day"].format(n=day, place=place)
        return t["status_place"].format(place=place) if place else t["status"]
    if kind == "recap":
        return t["recap_place"].format(place=place) if place else t["recap"]
    if place and isinstance(days, int) and days > 0:
        key = "days_in_one" if days == 1 else "days_in_other"
        return t[key].format(n=days, place=place)
    if place:
        return t["trip"].format(place=place)
    if isinstance(days, int) and days > 0:
        return t["trip_days"].format(n=days)
    name = str(snapshot.get("title") or "")
    if name and supported(name, lang):
        return clip_headline(name)
    return t["generic"]


def headline_for(snapshot: dict, lang: str) -> str:
    if lang == "en":
        return safe_headline(snapshot)
    return clip_headline(localized_headline(snapshot, lang))


# --- drawing -----------------------------------------------------------------


def _tlen(draw, text: str, face: Face) -> float:
    return sum(draw.textlength(chunk, font=f) for chunk, f in face.runs(text))


def _put(draw, xy, text: str, face: Face, fill) -> None:
    """Draw ``text`` with its top at ``xy[1]``, one run per font, on a shared
    baseline."""
    x, y = xy
    base = y + face.ascent
    for chunk, font in face.runs(text):
        draw.text((x, base), chunk, font=font, fill=fill, anchor="ls")
        x += draw.textlength(chunk, font=font)


def _fit(draw, text: str, face: Face, width: int) -> int:
    """Longest prefix length of ``text`` (at least 1) that fits ``width``,
    never splitting a combining sequence."""
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _tlen(draw, text[:mid], face) <= width:
            lo = mid
        else:
            hi = mid - 1
    while (
        lo > 1
        and lo < len(text)
        and (unicodedata.category(text[lo]).startswith("M") or text[lo] in "‌‍")
    ):
        lo -= 1
    return lo


def _wrap(draw, text: str, face: Face, width: int, max_lines: int) -> list[str]:
    """Greedy word wrap into at most ``max_lines`` lines, linear in the text
    (binary search only for single words wider than a line, e.g. Chinese,
    which has no spaces). Stops as soon as the line budget is exceeded, so
    cost is bounded by what can be drawn."""
    lines: list[str] = []
    cur = ""
    words = text.split()
    for word in words:
        trial = f"{cur} {word}".strip()
        if _tlen(draw, trial, face) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = word
        while len(cur) > 1 and _tlen(draw, cur, face) > width:
            cut = _fit(draw, cur, face, width)
            lines.append(cur[:cut])
            cur = cur[cut:]
            if len(lines) > max_lines:
                break
        if len(lines) > max_lines:
            break
    if cur and len(lines) <= max_lines:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1] + "..."
        if _tlen(draw, last, face) > width:
            last = lines[-1][: _fit(draw, lines[-1], face, width - 40)] + "..."
        lines[-1] = last
    return lines


def _clean(text: str, lang: str) -> str:
    """User text we can draw, else empty (never tofu)."""
    return text if supported(text, lang) else ""


def render(snapshot: dict, size: str = "link", lang: str = "en") -> bytes:
    lang = effective_lang(lang)
    t = i18n.STRINGS[lang]
    w, h = SIZES.get(size, SIZES["link"])
    story = size == "story"
    img = Image.new("RGB", (w, h), PALETTE["bg"])
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, int(h * 0.72), w, h), fill=PALETTE["bg_dark"])
    pad = int(w * 0.075)
    inner = w - 2 * pad
    y = int(h * (0.10 if story else 0.11))
    lead = 1.4 if lang in COMPLEX_SCRIPTS else 1.25

    _put(draw, (pad, y), BRAND, Face(lang, int(w * 0.04)), PALETTE["muted"])
    y += int(h * (0.16 if story else 0.22))

    head_size = int(w * (0.085 if story else 0.07))
    head_face = Face(lang, head_size)
    for line in _wrap(
        draw, headline_for(snapshot, lang), head_face, inner, 4 if story else 3
    ):
        _put(draw, (pad, y), line, head_face, PALETTE["text"])
        y += int(head_size * lead)
    y += int(head_size * 0.4)

    sub_face = Face(lang, int(w * 0.036))
    subs = []
    month = month_label(snapshot.get("period"), lang)
    if month:
        subs.append(month)
    owner = _clean(str(snapshot.get("owner_name") or ""), lang)
    if owner:
        subs.append(t["by"].format(name=owner))
    origin = _clean(str(snapshot.get("origin") or ""), lang)
    if origin:
        subs.append(t["from"].format(origin=origin))
    for sub in subs:
        for line in _wrap(draw, sub, sub_face, inner, 1):
            _put(draw, (pad, y), line, sub_face, PALETTE["muted"])
            y += int(w * 0.05)

    chip_face = Face(lang, int(w * 0.034))
    cy = int(h * (0.76 if story else 0.78))
    cx = pad
    ch = int(w * 0.07)
    for stat in (snapshot.get("stats") or [])[:3]:
        label = stat_text(stat, lang)
        cw = int(_tlen(draw, label, chip_face)) + int(w * 0.05)
        if cx + cw > w - pad:
            cx = pad
            cy += ch + int(w * 0.02)
        draw.rounded_rectangle(
            (cx, cy, cx + cw, cy + ch), radius=ch // 2, fill=PALETTE["chip"]
        )
        _put(
            draw,
            (cx + int(w * 0.025), cy + int(ch * 0.2)),
            label,
            chip_face,
            PALETTE["chip_text"],
        )
        cx += cw + int(w * 0.02)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def get_card(token: str, snapshot: dict, size: str, lang: str = "en") -> bytes:
    """Cached :func:`render`; the key includes the snapshot and language so
    edited options never serve a stale card."""
    lang = effective_lang(lang)
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, default=str).encode()
    ).hexdigest()
    key = (token, size, lang, digest)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    if not _render_slots.acquire(timeout=RENDER_WAIT_S):
        raise RenderBusy
    try:
        data = render(snapshot, size, lang)
    finally:
        _render_slots.release()
    with _lock:
        _cache[key] = data
    return data


def invalidate(token: str) -> None:
    with _lock:
        for key in [k for k in _cache if k[0] == token]:
            del _cache[key]
