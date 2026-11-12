"""Opt-in weekly price digest: an in-app ``price_digest`` notification, plus
email (verified address, SMTP set) and, only when ``digest_push`` is on, a push.
Observed prices only; never calls SerpAPI."""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from ..core.config import settings
from ..db import alerts_db, fare_watch_db, notifications_db, price_watch_db, users_db
from ..db.database import get_connection
from . import alert_delivery, alert_email, alert_moments, alert_story, fare_watch

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=7)


def _utc(now: datetime) -> datetime:
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)


def _opted_in_users() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT user_id, data FROM alert_prefs").fetchall()
    out = []
    for r in rows:
        try:
            if json.loads(r["data"]).get("digest_weekly") is True:
                out.append(r["user_id"])
        except (ValueError, AttributeError):
            continue
    return out


def _local(now: datetime, tz: str | None) -> datetime:
    zone = alert_delivery._zone(tz)
    return now.astimezone(zone) if zone else now


def is_due(prefs: dict, tz: str | None, now: datetime) -> tuple[bool, str]:
    """(due, ISO week key) for the user's local time."""
    local = _local(now, tz)
    iso = local.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    due = (
        bool(prefs.get("digest_weekly"))
        and local.isoweekday() == prefs.get("digest_day", 1)
        and local.hour >= settings.alert_digest_hour_local
    )
    return due, week


def _set_status(user_id: str, week: str, status: str, sent: bool = False) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE alert_digests SET status = ?, sent_at = ? WHERE user_id = ? AND week = ?",
            (status, alerts_db._now() if sent else None, user_id, week),
        )


def _change_7d(points: list[dict], now: datetime) -> float | None:
    if len(points) < 2:
        return None
    cutoff = (now - WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = None
    for p in points:
        if p["at"] <= cutoff:
            base = p
    if base is None:
        inside = [p for p in points if p["at"] > cutoff]
        base = inside[0] if inside else None
    latest = points[-1]
    if base is None or base is latest:
        return None
    return round(latest["price"] - base["price"], 2)


def _active_watches(user_id: str) -> list[tuple[str, dict, list[dict]]]:
    out = []
    for w in fare_watch_db.list_watches(user_id):
        out.append(("flight", w, fare_watch_db.get_history(w["id"])))
    for w in price_watch_db.list_watches(user_id):
        out.append((w.get("kind"), w, price_watch_db.get_history(w["id"])))
    return [t for t in out if t[1].get("status", "active") == "active"]


def build_digest(user_id: str, now: datetime) -> dict | None:
    """The digest payload, or ``None`` when nothing looked or dropped this week."""
    iso = now.isocalendar()
    cutoff = (now - WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    watches, looked = [], False
    for kind, w, hist in _active_watches(user_id):
        story = alert_story.build_story(
            kind, w, hist, live_prices=bool(settings.serpapi_key), now=now
        )
        points = story["points"]
        if any(p["at"] > cutoff for p in points) or (
            story["checked_at"] and story["checked_at"] > cutoff
        ):
            looked = True
        if not points:
            continue
        title = fare_watch.route_label(w) if kind == "flight" else w.get("title")
        watches.append(
            {
                "kind": kind,
                "watch_id": w["id"],
                "title": title,
                "currency": story["currency"],
                "latest": story["latest"]["price"],
                "change_7d": _change_7d(points, now),
                "lowest": story["lowest"]["price"],
                "checked_at": story["checked_at"],
                "spark": [p["price"] for p in points][-12:],
            }
        )
    dropped = any(s["created_at"] > cutoff for s in alerts_db.savings_rows(user_id))
    if not looked and not dropped:
        return None
    return {
        "week": f"{iso.year}-W{iso.week:02d}",
        "watches": watches,
        "savings": alert_moments.summary(user_id),
    }


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _title_body(digest: dict) -> tuple[str, str]:
    n = len(digest["watches"])
    caught = digest["savings"].get("total_usd") or 0
    body = f"{n} watch{'es' if n != 1 else ''} checked this week"
    if caught:
        body += f", ${caught:,.0f} caught so far"
    return "Your weekly price digest", body


def _deliver(user: dict, prefs: dict, note: dict, digest: dict) -> None:
    if (
        user.get("email")
        and user.get("email_verified")
        and alert_email.email_available()
    ):
        try:
            alert_email.send_message(alert_email.build_digest_message(user, digest))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Digest email failed: %s", type(exc).__name__)
    if prefs.get("digest_push") is True:
        try:
            from . import push

            title, body = _title_body(digest)
            data = {
                "kind": "price_digest",
                "notification_id": str(note["id"]),
                "link": "/alerts",
            }
            _run(push.send_to_user(user["username"], title, body, data))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Digest push failed: %s", type(exc).__name__)


def run_due(now: datetime) -> int:
    """Send every due digest once per user and ISO week; returns how many."""
    now = _utc(now)
    sent = 0
    for user_id in _opted_in_users():
        try:
            prefs = alerts_db.get_prefs(user_id)
            due, week = is_due(prefs, alert_delivery._user_tz(user_id), now)
            if not due or not alerts_db.digest_claim(user_id, week):
                continue
            user = users_db.get_user_by_id(user_id)
            if not user or not user.get("is_active", True):
                _set_status(user_id, week, "skipped")
                continue
            digest = build_digest(user_id, now)
            if digest is None:
                _set_status(user_id, week, "skipped")
                continue
            title, body = _title_body(digest)
            note = notifications_db.add_notification(
                user_id, "price_digest", title, body, {"digest": digest}, now=now
            )
            _deliver(user, prefs, note, digest)
            _set_status(user_id, week, "sent", sent=True)
            sent += 1
        except Exception:  # noqa: BLE001
            logger.warning("weekly digest failed", exc_info=True)
    return sent
