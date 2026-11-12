"""Notifications 2.0 delivery core for category pushes (trip reminders,
morning brief, ...). Price drops keep ``alert_delivery``.

Order: category enabled? -> dedupe -> quiet hours (hold) -> daily cap -> send.
The in-app row is always written. ``enqueue_category`` records the decision in
``notify_log``; ``flush_due`` releases held items and sends. Pushes go through
``push.send_to_user`` only."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..db import alerts_db, devices_db, notifications_db, user_settings_db
from ..db.database import get_connection
from ..db.users_db import get_user_by_id
from . import alert_delivery, notify_settings, push

logger = logging.getLogger(__name__)

FLUSH_BATCH = 100
STALE_AFTER = timedelta(hours=12)
LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")


@dataclass
class Decision:
    action: str  # send | hold | drop
    due_at: datetime | None = None
    reason: str = "now"  # now | quiet | disabled | cap


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def decide(
    category: str, prefs: dict, tz: str | None, counts: int, now: datetime
) -> Decision:
    """Pure. ``prefs`` = ``{"categories": {name: bool}, "daily_cap": int,
    "quiet_hours": {...}}``; ``counts`` = category pushes already sent in the
    user's local day. No tz means no quiet hours."""
    if not (prefs.get("categories") or {}).get(category, True):
        return Decision("drop", None, "disabled")
    until = alert_delivery.quiet_until(now, tz, prefs.get("quiet_hours") or {})
    if until:
        return Decision("hold", until, "quiet")
    if counts >= int(prefs.get("daily_cap") or notify_settings.DEFAULT_CAP):
        return Decision("drop", None, "cap")
    return Decision("send", now, "now")


def user_locale(user_id: str) -> str:
    """Language setting, else the newest device locale, else ``en``."""
    try:
        lang = user_settings_db.get_settings(user_id).get("language")
        if lang in LANGS:
            return lang
        user = get_user_by_id(user_id)
        for d in devices_db.list_devices(user["username"]) if user else []:
            base = (d.get("locale") or "").replace("_", "-").split("-")[0].lower()
            if base in LANGS:
                return base
    except Exception:  # noqa: BLE001
        logger.warning("locale lookup failed", exc_info=True)
    return "en"


def _prefs(user_id: str) -> dict:
    st = notify_settings.stored(user_id)
    return {
        "categories": st["categories"],
        "daily_cap": st["daily_cap"],
        "quiet_hours": alerts_db.get_prefs(user_id)["quiet_hours"],
    }


def _tz(user_id: str) -> str | None:
    return alert_delivery._user_tz(user_id)


def _sent_today(user_id: str, now: datetime, tz: str | None) -> int:
    start = _iso(alert_delivery._local_day_start(now, tz))
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM notify_log WHERE user_id = ? AND status = 'sent'"
            " AND sent_at >= ?",
            (user_id, start),
        ).fetchone()[0]


def enqueue_category(
    user_id: str,
    plan_id: int | None,
    kind: str,
    category: str,
    key: str,
    title: str,
    body: str,
    data: dict,
    now: datetime,
) -> dict | None:
    """Record one category notification. ``key`` is the dedupe key (unique per
    user via the log's unique column; callers include the user and plan, and the
    local day for the morning brief). Returns ``None`` when ``key`` was already
    enqueued, else ``{"notification_id", "status", "due_at", "reason"}``.
    ``data`` should carry ``link``; ``category`` and ``plan_id`` are added.
    Text is rendered by the caller (see ``user_locale``)."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO notify_log (user_id, plan_id, kind, dedupe_key,"
            " category, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, plan_id, kind, key, category, _iso(now)),
        )
        if cur.rowcount == 0:
            return None
        log_id = cur.lastrowid
    row_data = {**data, "category": category, "plan_id": plan_id}
    note = notifications_db.add_notification(
        user_id, kind, title, body, row_data, now=now
    )
    tz = _tz(user_id)
    d = decide(category, _prefs(user_id), tz, _sent_today(user_id, now, tz), now)
    status = "pending" if d.action != "drop" else "dropped"
    due = _iso(d.due_at) if d.due_at else None
    with get_connection() as conn:
        conn.execute(
            "UPDATE notify_log SET notification_id = ?, status = ?, due_at = ?,"
            " dropped_reason = ? WHERE id = ?",
            (note["id"], status, due, d.reason if d.action == "drop" else None, log_id),
        )
    return {
        "notification_id": note["id"],
        "status": status,
        "due_at": d.due_at,
        "reason": d.reason,
    }


def _claim(now: datetime) -> list[dict]:
    """Atomically move due pending items to ``sending``; each is claimed once."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notify_log WHERE status = 'pending' AND due_at <= ?"
            " ORDER BY due_at, id LIMIT ?",
            (_iso(now), FLUSH_BATCH),
        ).fetchall()
        out = []
        for r in rows:
            cur = conn.execute(
                "UPDATE notify_log SET status = 'sending' WHERE id = ?"
                " AND status = 'pending'",
                (r["id"],),
            )
            if cur.rowcount:
                out.append(dict(r))
    return out


def _finish(log_id: int, status: str, now: datetime, reason: str | None = None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE notify_log SET status = ?, sent_at = ?, dropped_reason = ?"
            " WHERE id = ?",
            (status, _iso(now) if status == "sent" else None, reason, log_id),
        )


def _rehold(log_id: int, due: datetime) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE notify_log SET status = 'pending', due_at = ? WHERE id = ?",
            (_iso(due), log_id),
        )


INTERRUPTED_AFTER = timedelta(minutes=10)


def _reset_interrupted(now: datetime) -> int:
    """Items claimed by a run that died mid-send never finish: drop them."""
    with get_connection() as conn:
        return conn.execute(
            "UPDATE notify_log SET status = 'dropped', dropped_reason = 'interrupted'"
            " WHERE status = 'sending' AND due_at < ?",
            (_iso(now - INTERRUPTED_AFTER),),
        ).rowcount


async def _flush(now: datetime) -> int:
    sent = 0
    _reset_interrupted(now)
    for it in _claim(now):
        try:
            if _parse(it["created_at"]) < now - STALE_AFTER:
                _finish(it["id"], "dropped", now, "stale")
                continue
            uid = it["user_id"]
            tz = _tz(uid)
            d = decide(it["category"], _prefs(uid), tz, _sent_today(uid, now, tz), now)
            if d.action == "hold":
                _rehold(it["id"], d.due_at)
                continue
            if d.action == "drop":
                _finish(it["id"], "dropped", now, d.reason)
                continue
            with get_connection() as conn:
                r = conn.execute(
                    "SELECT * FROM notifications WHERE id = ?",
                    (it["notification_id"],),
                ).fetchone()
            user = get_user_by_id(uid)
            if not r or not user or not user.get("is_active"):
                _finish(it["id"], "dropped", now, "no_user")
                continue
            note = notifications_db._row(r)
            payload = {
                "kind": note["kind"],
                "notification_id": str(note["id"]),
                "category": it["category"],
                "plan_id": "" if it["plan_id"] is None else str(it["plan_id"]),
                "link": (note["data"] or {}).get("link", ""),
            }
            n = await push.send_to_user(
                user["username"], note["title"], note["body"], payload
            )
            if n > 0:
                _finish(it["id"], "sent", now)
                sent += 1
            else:
                _finish(it["id"], "dropped", now, "no_device")
        except Exception:  # noqa: BLE001
            logger.warning("notify flush item failed", exc_info=True)
            _finish(it["id"], "dropped", now, "error")
    return sent


def flush_due(now: datetime) -> int:
    """Send every due, claimed-once item; returns how many pushes went out.
    Synchronous (the loop runs it in a thread)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_flush(now))
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, _flush(now)).result()
