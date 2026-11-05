"""Fare and price alert emails over SMTP (stdlib only), sent only when SMTP_HOST is set,
the watch has email on and its owner has an address.

Multipart plain text + inline-styled HTML with no remote images, and a
signed one-click link that turns email off for that watch without login.
Failures are logged (never the password or the address) and never break a
check.
"""

import asyncio
import html
import logging
import smtplib
import ssl
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from urllib.parse import urlparse

import jwt
from jwt import PyJWTError

from ..core.config import settings
from ..db import fare_watch_db, notifications_db, price_watch_db
from .fare_watch import date_range, route_label, travellers, usd

logger = logging.getLogger(__name__)

_UNSUB_PURPOSE = "fare-watch-unsubscribe"
PRICE_UNSUB_PURPOSE = "price-watch-unsubscribe"
_BARS = "▁▂▃▄▅▆▇█"
FARE_KINDS = ("fare_drop", "fare_target", "fare_low_level", "fare_cheaper_date")


def email_available() -> bool:
    return bool(settings.smtp_host)


# ── Unsubscribe token ─────────────────────────────────────────────────────────


def unsubscribe_token(watch_id: int, purpose: str = _UNSUB_PURPOSE) -> str:
    """Signed, non-expiring token naming one watch (no user data inside).
    ``purpose`` tells fare watches from price watches (separate id spaces)."""
    return jwt.encode(
        {"wid": watch_id, "purpose": purpose},
        settings.jwt_secret_key,
        algorithm="HS256",
    )


def read_unsubscribe_token(token: str, purpose: str = _UNSUB_PURPOSE) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except PyJWTError:
        return None
    wid = payload.get("wid")
    if payload.get("purpose") != purpose or not isinstance(wid, int):
        return None
    return wid


# ── Content ───────────────────────────────────────────────────────────────────


def sparkline(prices: list[float | None], width: int = 12) -> str:
    """Text sparkline of the latest prices, e.g. '▆▄█▁'."""
    points = [p for p in prices if p is not None][-width:]
    if not points:
        return ""
    lo, hi = min(points), max(points)
    if hi == lo:
        return _BARS[3] * len(points)
    return "".join(_BARS[round((p - lo) / (hi - lo) * 7)] for p in points)


def _url(path: str) -> str:
    return settings.app_base_url.rstrip("/") + path


def _facts(note: dict, watch: dict, history: list[dict]) -> dict:
    data = note["data"]
    cheaper = note["kind"] == "fare_cheaper_date"
    dep = data["cheapest_departure_date"] if cheaper else watch["departure_date"]
    ret = data["cheapest_return_date"] if cheaper else watch.get("return_date")
    old = data["selected_price"] if cheaper else data["previous_price"]
    new = data["price"]
    lowest = min(
        [v for v in (watch.get("lowest_price"), new) if v is not None], default=new
    )
    links = data.get("links") or {}
    return {
        "route": route_label(watch),
        "dates": date_range(dep, ret),
        "who": travellers(watch["num_travelers"]),
        "old": usd(old),
        "new": usd(new),
        "delta": f"−{usd(old - new)}" if new < old else "",
        "lowest": usd(lowest),
        "spark": sparkline([h.get("price") for h in history]),
        "see": _url(links.get("alerts", f"/alerts?watch={watch['id']}")),
        "replan": _url(links.get("replan", f"/alerts?watch={watch['id']}&replan=1")),
        "unsubscribe": _url(
            f"/api/fare-watches/unsubscribe?token={unsubscribe_token(watch['id'])}"
        ),
    }


def _text(note: dict, f: dict) -> str:
    lines = [
        note["title"],
        "",
        note["body"],
        "",
        f"{f['route']} · {f['dates']} · {f['who']}",
        f"Price: {f['old']} → {f['new']}" + (f" ({f['delta']})" if f["delta"] else ""),
        f"Lowest seen: {f['lowest']}",
    ]
    if f["spark"]:
        lines.append(f"Recent checks: {f['spark']}")
    lines += [
        "",
        f"See flights: {f['see']}",
        f"Re-plan with this fare: {f['replan']}",
        "",
        "Fares change fast — book soon if this one works for you.",
        "",
        f"Stop emails for this watch: {f['unsubscribe']}",
    ]
    return "\n".join(lines) + "\n"


def _html(note: dict, f: dict) -> str:
    e = {k: html.escape(v) for k, v in f.items()}
    title, body = html.escape(note["title"]), html.escape(note["body"])
    delta = (
        f'<span style="color:#047857;font-weight:600;"> {e["delta"]}</span>'
        if f["delta"]
        else ""
    )
    spark = (
        f'<p style="margin:12px 0 0;font-size:13px;color:#64748b;">Recent checks '
        f'<span style="letter-spacing:1px;color:#0284c7;">{e["spark"]}</span></p>'
        if f["spark"]
        else ""
    )
    btn = (
        "display:inline-block;padding:10px 18px;border-radius:999px;"
        "font-weight:600;font-size:14px;text-decoration:none;"
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f0f9ff;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:16px;border:1px solid #e2e8f0;">
<tr><td style="padding:24px 28px;">
<p style="margin:0 0 4px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0d9488;font-weight:700;">Fare watch</p>
<h1 style="margin:0 0 8px;font-size:20px;line-height:1.3;">{title}</h1>
<p style="margin:0 0 16px;font-size:14px;color:#475569;">{body}</p>
<p style="margin:0;font-size:13px;color:#64748b;">{e["route"]} · {e["dates"]} · {e["who"]}</p>
<p style="margin:8px 0 0;font-size:16px;"><span style="color:#94a3b8;text-decoration:line-through;">{e["old"]}</span> → <strong style="font-size:24px;">{e["new"]}</strong>{delta}</p>
<p style="margin:6px 0 0;font-size:13px;color:#64748b;">Lowest seen: {e["lowest"]}</p>
{spark}
<p style="margin:20px 0 0;">
<a href="{e["see"]}" style="{btn}background:#0284c7;color:#ffffff;">See flights</a>
&nbsp;
<a href="{e["replan"]}" style="{btn}background:#ecfeff;color:#0f766e;border:1px solid #99f6e4;">Re-plan with this fare</a>
</p>
<p style="margin:20px 0 0;font-size:12px;color:#94a3b8;">Fares change fast — book soon if this one works for you.</p>
</td></tr></table>
<p style="max-width:520px;margin:12px auto 0;font-size:11px;color:#94a3b8;text-align:center;">You're getting this because you watch this fare. <a href="{e["unsubscribe"]}" style="color:#64748b;">Stop emails for this watch</a></p>
</body></html>
"""


# Long header lines are legal up to 998 octets; the default policy's 78
# would RFC 2047-encode the unbreakable List-Unsubscribe URL into something
# no mail client can use.
_POLICY = policy.default.clone(max_line_length=998)


def _sender() -> str:
    return settings.smtp_from or settings.smtp_username or "alerts@localhost"


def _mail_domain() -> str:
    """Domain for Message-ID: the sender's, else the app's host."""
    addr = parseaddr(_sender())[1]
    if "@" in addr and addr.rsplit("@", 1)[1] != "localhost":
        return addr.rsplit("@", 1)[1]
    return urlparse(settings.app_base_url).hostname or "localhost"


def build_message(note: dict, watch: dict, to_addr: str, history: list[dict]):
    f = _facts(note, watch, history)
    msg = EmailMessage(policy=_POLICY)
    msg["Subject"] = note["title"]
    msg["From"] = _sender()
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain=_mail_domain())
    # RFC 8058 one-click: mail clients POST "List-Unsubscribe=One-Click"
    msg["List-Unsubscribe"] = f"<{f['unsubscribe']}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(_text(note, f))
    msg.add_alternative(_html(note, f), subtype="html")
    return msg


# ── Sending ───────────────────────────────────────────────────────────────────


def send_message(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def deliver(watch: dict, note: dict, now: datetime) -> bool:
    """Email a fare alert if this watch should get one. Never raises."""
    if watch is None or note["kind"] not in FARE_KINDS:
        return False
    if not watch.get("email_enabled"):
        return False
    if not email_available():
        return False
    try:
        from ..db.users_db import get_user_by_id

        user = get_user_by_id(watch["user_id"])
        if not user or not user.get("email"):
            return False
        msg = build_message(
            note, watch, user["email"], fare_watch_db.get_history(watch["id"])
        )
        await asyncio.to_thread(send_message, msg)
        notifications_db.mark_emailed(note["id"], now=now)
        logger.info("Fare alert email sent for watch %d", watch["id"])
        return True
    except Exception as exc:
        logger.warning(
            "Fare alert email for watch %d failed: %s", watch["id"], type(exc).__name__
        )
        return False


# ── Price watches (hotel / activity / trip) ───────────────────────────────────

# Eyebrow and main button per watch kind; unknown kinds read generically.
PRICE_KIND_LABELS = {
    "hotel": ("Hotel price watch", "See hotel"),
    "activity": ("Activity price watch", "See activity"),
    "trip": ("Trip price watch", "See trip"),
}
_PRICE_ALERT_SUFFIXES = ("_drop", "_target")


def _price_facts(note: dict, watch: dict, history: list[dict]) -> dict:
    data = note["data"]
    old, new = data["previous_price"], data["price"]
    lowest = min(
        [v for v in (watch.get("lowest_price"), new) if v is not None], default=new
    )
    links = data.get("links") or {}
    eyebrow, see = PRICE_KIND_LABELS.get(watch["kind"], ("Price watch", "See details"))
    token = unsubscribe_token(watch["id"], PRICE_UNSUB_PURPOSE)
    return {
        "eyebrow": eyebrow,
        "see_label": see,
        "subject": " · ".join(
            x for x in (watch.get("title"), watch.get("subtitle")) if x
        ),
        "old": usd(old),
        "new": usd(new),
        "delta": f"−{usd(old - new)}" if new < old else "",
        "lowest": usd(lowest),
        "spark": sparkline([h.get("price") for h in history]),
        "see": _url(
            links.get("alerts", f"/alerts?kind={watch['kind']}&watch={watch['id']}")
        ),
        "book": links.get("book") or "",
        "unsubscribe": _url(f"/api/price-watches/unsubscribe?token={token}"),
    }


def _price_text(note: dict, f: dict) -> str:
    lines = [
        note["title"],
        "",
        note["body"],
        "",
        f["subject"],
        f"Price: {f['old']} → {f['new']}" + (f" ({f['delta']})" if f["delta"] else ""),
        f"Lowest seen: {f['lowest']}",
    ]
    if f["spark"]:
        lines.append(f"Recent checks: {f['spark']}")
    lines += ["", f"{f['see_label']}: {f['see']}"]
    if f["book"]:
        lines.append(f"Open the listing: {f['book']}")
    lines += [
        "",
        "Prices change fast — book soon if this one works for you.",
        "",
        f"Stop emails for this watch: {f['unsubscribe']}",
    ]
    return "\n".join(lines) + "\n"


def _price_html(note: dict, f: dict) -> str:
    e = {k: html.escape(v) for k, v in f.items()}
    title, body = html.escape(note["title"]), html.escape(note["body"])
    delta = (
        f'<span style="color:#047857;font-weight:600;"> {e["delta"]}</span>'
        if f["delta"]
        else ""
    )
    spark = (
        f'<p style="margin:12px 0 0;font-size:13px;color:#64748b;">Recent checks '
        f'<span style="letter-spacing:1px;color:#0284c7;">{e["spark"]}</span></p>'
        if f["spark"]
        else ""
    )
    btn = (
        "display:inline-block;padding:10px 18px;border-radius:999px;"
        "font-weight:600;font-size:14px;text-decoration:none;"
    )
    book = (
        f'&nbsp;<a href="{e["book"]}" style="{btn}background:#ecfeff;color:#0f766e;'
        f'border:1px solid #99f6e4;">Open the listing</a>'
        if f["book"]
        else ""
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f0f9ff;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:16px;border:1px solid #e2e8f0;">
<tr><td style="padding:24px 28px;">
<p style="margin:0 0 4px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0d9488;font-weight:700;">{e["eyebrow"]}</p>
<h1 style="margin:0 0 8px;font-size:20px;line-height:1.3;">{title}</h1>
<p style="margin:0 0 16px;font-size:14px;color:#475569;">{body}</p>
<p style="margin:0;font-size:13px;color:#64748b;">{e["subject"]}</p>
<p style="margin:8px 0 0;font-size:16px;"><span style="color:#94a3b8;text-decoration:line-through;">{e["old"]}</span> → <strong style="font-size:24px;">{e["new"]}</strong>{delta}</p>
<p style="margin:6px 0 0;font-size:13px;color:#64748b;">Lowest seen: {e["lowest"]}</p>
{spark}
<p style="margin:20px 0 0;">
<a href="{e["see"]}" style="{btn}background:#0284c7;color:#ffffff;">{e["see_label"]}</a>
{book}
</p>
<p style="margin:20px 0 0;font-size:12px;color:#94a3b8;">Prices change fast — book soon if this one works for you.</p>
</td></tr></table>
<p style="max-width:520px;margin:12px auto 0;font-size:11px;color:#94a3b8;text-align:center;">You're getting this because you watch this price. <a href="{e["unsubscribe"]}" style="color:#64748b;">Stop emails for this watch</a></p>
</body></html>
"""


def build_price_message(note: dict, watch: dict, to_addr: str, history: list[dict]):
    """A price-watch alert email (any kind; the wording comes from the
    notification, the eyebrow and button from PRICE_KIND_LABELS)."""
    f = _price_facts(note, watch, history)
    msg = EmailMessage(policy=_POLICY)
    msg["Subject"] = note["title"]
    msg["From"] = _sender()
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain=_mail_domain())
    msg["List-Unsubscribe"] = f"<{f['unsubscribe']}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(_price_text(note, f))
    msg.add_alternative(_price_html(note, f), subtype="html")
    return msg


def is_price_alert(note: dict, watch: dict) -> bool:
    kind = note.get("kind") or ""
    return kind in (f"{watch['kind']}{s}" for s in _PRICE_ALERT_SUFFIXES)


async def deliver_price(watch: dict, note: dict, now: datetime) -> bool:
    """Email a price-watch alert (``<kind>_drop`` / ``<kind>_target``) if
    this watch should get one. Never raises."""
    if watch is None or not is_price_alert(note, watch):
        return False
    if not watch.get("email_enabled") or not email_available():
        return False
    try:
        from ..db.users_db import get_user_by_id

        user = get_user_by_id(watch["user_id"])
        if not user or not user.get("email"):
            return False
        msg = build_price_message(
            note, watch, user["email"], price_watch_db.get_history(watch["id"])
        )
        await asyncio.to_thread(send_message, msg)
        notifications_db.mark_emailed(note["id"], now=now)
        logger.info("Price alert email sent for price watch %d", watch["id"])
        return True
    except Exception as exc:
        logger.warning(
            "Price alert email for price watch %d failed: %s",
            watch["id"],
            type(exc).__name__,
        )
        return False
