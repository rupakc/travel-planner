"""Share card renderer (Phase 4): a PNG drawn from a public snapshot.

Pure Pillow, no network. The snapshot comes from
``share_public.build_snapshot`` so it can never carry exact dates. Colours are
a fixed brand palette copied from ``frontend/design/tokens.json`` (a test keeps
them in sync). The bundled default font has Latin glyphs only, so a headline
with other scripts falls back to a plain English one.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from datetime import date

from cachetools import TTLCache
from PIL import Image, ImageDraw, ImageFont

from .share_public import clip_headline

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

STAT_LABELS = {  # key -> (singular, plural)
    "activities": ("activity", "activities"),
    "hotels": ("hotel", "hotels"),
    "places": ("place", "places"),
    "drops_caught": ("drop caught", "drops caught"),
    "targets_hit": ("target hit", "targets hit"),
    "correct": ("correct answer", "correct answers"),
}

_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()

RENDER_WAIT_S = 5.0
_render_slots = threading.BoundedSemaphore(2)


class RenderBusy(Exception):
    """Too many renders in flight (the route answers 503)."""


_cache: TTLCache = TTLCache(maxsize=64, ttl=600)
_lock = threading.Lock()


def month_label(period: str | None) -> str | None:
    """``2026-04`` -> ``April 2026``; anything else -> None."""
    try:
        d = date.fromisoformat(f"{period}-01")
    except (TypeError, ValueError):
        return None
    return f"{_MONTHS[d.month - 1]} {d.year}"


def stat_text(stat: dict) -> str:
    n = int(stat.get("count") or 0)
    one, many = STAT_LABELS.get(stat.get("key"), (stat.get("key"),) * 2)
    return f"{n} {one if n == 1 else many}"


def _drawable(text: str) -> bool:
    return all(
        ord(c) < 0x250 or 0x2000 <= ord(c) <= 0x206F or c in "€£¥₹" for c in text
    )


def safe_headline(snapshot: dict) -> str:
    """The headline, or a plain English one if it needs glyphs we lack."""
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


def _font(size: int):
    return ImageFont.load_default(size=size)


def _fit(draw, text: str, font, width: int) -> int:
    """Longest prefix length of ``text`` (at least 1) that fits ``width``."""
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid], font=font) <= width:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    """Greedy word wrap into at most ``max_lines`` lines, linear in the text
    (binary search only for single words wider than a line). Stops as soon as
    the line budget is exceeded, so cost is bounded by what can be drawn."""
    lines: list[str] = []
    cur = ""
    words = text.split()
    for i, word in enumerate(words):
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = word
        while len(cur) > 1 and draw.textlength(cur, font=font) > width:
            cut = _fit(draw, cur, font, width)
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
        if draw.textlength(last, font=font) > width:
            last = lines[-1][: _fit(draw, lines[-1], font, width - 40)] + "..."
        lines[-1] = last
    return lines


def _ascii_only(text: str) -> str:
    return text if _drawable(text) else ""


def render(snapshot: dict, size: str = "link") -> bytes:
    w, h = SIZES.get(size, SIZES["link"])
    story = size == "story"
    img = Image.new("RGB", (w, h), PALETTE["bg"])
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, int(h * 0.72), w, h), fill=PALETTE["bg_dark"])
    pad = int(w * 0.075)
    inner = w - 2 * pad
    y = int(h * (0.10 if story else 0.11))

    draw.text((pad, y), BRAND, font=_font(int(w * 0.04)), fill=PALETTE["muted"])
    y += int(h * (0.16 if story else 0.22))

    head_font = _font(int(w * (0.085 if story else 0.07)))
    head_size = head_font.size
    for line in _wrap(
        draw, safe_headline(snapshot), head_font, inner, 4 if story else 3
    ):
        draw.text((pad, y), line, font=head_font, fill=PALETTE["text"])
        y += int(head_size * 1.25)
    y += int(head_size * 0.4)

    sub_font = _font(int(w * 0.036))
    subs = []
    month = month_label(snapshot.get("period"))
    if month:
        subs.append(month)
    owner = _ascii_only(str(snapshot.get("owner_name") or ""))
    if owner:
        subs.append(f"by {owner}")
    origin = _ascii_only(str(snapshot.get("origin") or ""))
    if origin:
        subs.append(f"from {origin}")
    for sub in subs:
        for line in _wrap(draw, sub, sub_font, inner, 1):
            draw.text((pad, y), line, font=sub_font, fill=PALETTE["muted"])
            y += int(w * 0.05)

    chip_font = _font(int(w * 0.034))
    cy = int(h * (0.76 if story else 0.78))
    cx = pad
    ch = int(w * 0.07)
    for stat in (snapshot.get("stats") or [])[:3]:
        label = stat_text(stat)
        cw = int(draw.textlength(label, font=chip_font)) + int(w * 0.05)
        if cx + cw > w - pad:
            cx = pad
            cy += ch + int(w * 0.02)
        draw.rounded_rectangle(
            (cx, cy, cx + cw, cy + ch), radius=ch // 2, fill=PALETTE["chip"]
        )
        draw.text(
            (cx + int(w * 0.025), cy + int(ch * 0.2)),
            label,
            font=chip_font,
            fill=PALETTE["chip_text"],
        )
        cx += cw + int(w * 0.02)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def get_card(token: str, snapshot: dict, size: str) -> bytes:
    """Cached :func:`render`; the key includes the snapshot so edited options
    never serve a stale card."""
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, default=str).encode()
    ).hexdigest()
    key = (token, size, digest)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    if not _render_slots.acquire(timeout=RENDER_WAIT_S):
        raise RenderBusy
    try:
        data = render(snapshot, size)
    finally:
        _render_slots.release()
    with _lock:
        _cache[key] = data
    return data


def invalidate(token: str) -> None:
    with _lock:
        for key in [k for k in _cache if k[0] == token]:
            del _cache[key]
