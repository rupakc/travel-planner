"""Quiet hours, caps, grouping and the outbox loop for push and email.

``plan`` is the pure rule set (docs/Alerts-API.md, "Delivery rules");
``dispatch`` applies it to one stored notification and fills the outbox;
``flush`` sends what is due. The in-app row is never touched here."""

import asyncio
import logging
import re
import time as time_mod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.config import settings
from ..core.errors import ApiError
from ..db import alerts_db, fare_watch_db, price_watch_db
from ..db.alerts_db import DEFAULT_PREFS
from ..db.database import get_connection

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_PREFS", "Decision", "plan", "dispatch", "flush", "validate_prefs"]

KINDS = ("flight", "hotel", "activity", "trip")
LEGACY_NOTE_KINDS = ("watch_expired", "watch_error")
CHANNELS = ("push", "email")
FLUSH_BATCH = 200
STALE_AFTER = timedelta(hours=12)  # held longer than this: dropped, not sent
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass
class Decision:
    channels: list[str] = field(default_factory=list)
    due_at: datetime | None = None
    reason: str = "now"  # now | quiet | group | cap | targets_only | legacy
    # Email is never grouped, so a group hold does not delay it. ``None``
    # means "same as due_at".
    email_due_at: datetime | None = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _zone(tz: str | None) -> ZoneInfo | None:
    if not tz:
        return None
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _hhmm(s: str) -> time:
    return time(int(s[:2]), int(s[3:5]))


def quiet_active(prefs: dict, tz: str | None) -> bool:
    qh = prefs.get("quiet_hours") or {}
    return bool(
        qh.get("enabled")
        and _zone(tz)
        and qh.get("start") != qh.get("end")
        and _HHMM.match(str(qh.get("start")))
        and _HHMM.match(str(qh.get("end")))
    )


def quiet_until(now: datetime, tz: str | None, qh: dict) -> datetime | None:
    """The UTC time the current quiet window ends, or ``None`` when ``now``
    is not inside one (or quiet hours do not apply). ``[start, end)``."""
    zone = _zone(tz)
    if not zone or not qh.get("enabled"):
        return None
    if not (_HHMM.match(str(qh.get("start"))) and _HHMM.match(str(qh.get("end")))):
        return None
    start, end = _hhmm(qh["start"]), _hhmm(qh["end"])
    if start == end:
        return None
    local = now.astimezone(zone)
    t = local.time().replace(second=0, microsecond=0)
    inside = (start <= t < end) if start < end else (t >= start or t < end)
    if not inside:
        return None
    day = local.date() if end > local.time() else local.date() + timedelta(days=1)
    # wall-clock end in the local zone, then to UTC: DST is honoured
    return datetime.combine(day, end, tzinfo=zone).astimezone(UTC)


def _local_day_start(now: datetime, tz: str | None) -> datetime:
    zone = _zone(tz) or UTC
    local = now.astimezone(zone)
    return datetime.combine(local.date(), time(0, 0), tzinfo=zone).astimezone(UTC)


def _is_target_hit(note_row: dict) -> bool:
    data = note_row.get("data") or {}
    drop = data.get("drop") or {}
    return bool(drop.get("target_hit")) or str(note_row.get("kind", "")).endswith(
        "_target"
    )


def plan(
    note_row: dict,
    watch_kind: str,
    prefs: dict,
    tz: str | None,
    counts: dict,
    last_push_at: datetime | None,
    now: datetime,
    price_drops_enabled: bool = True,
) -> Decision:
    """The delivery rules for one new notification (pure).

    ``counts`` is ``{"push": n, "email": n}``: what this user already had
    sent in this category today (their local day)."""
    # 1. expired / error notes go out as today
    if note_row.get("kind") in LEGACY_NOTE_KINDS:
        return Decision(list(CHANNELS), now, "legacy")
    # 1b. Notifications 2.0: the user switched the price_drops category off
    if not price_drops_enabled:
        return Decision([], None, "category_off")
    # 2. targets only
    if prefs.get("instant") == "targets_only" and not _is_target_hit(note_row):
        return Decision([], None, "targets_only")
    # 3. daily cap, per channel
    cap = (prefs.get("daily_cap") or {}).get(watch_kind, 3)
    channels = [c for c in CHANNELS if int(counts.get(c, 0)) < cap]
    if not channels:
        return Decision([], None, "cap")
    # 4. quiet hours
    until = quiet_until(now, tz, prefs.get("quiet_hours") or {})
    if until:
        return Decision(channels, until, "quiet")
    # 5. grouping window (push only)
    window = int(prefs.get("group_window_min") or 0)
    if window and last_push_at and "push" in channels:
        ends = last_push_at + timedelta(minutes=window)
        if ends > now:
            return Decision(channels, ends, "group", email_due_at=now)
    return Decision(channels, now, "now")


# ── Preferences ───────────────────────────────────────────────────────────────


def _invalid(msg: str) -> ApiError:
    return ApiError(422, "alert_prefs_invalid", msg)


def _int(v, lo: int, hi: int, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise _invalid(f"{name} must be an integer from {lo} to {hi}")
    return v


def validate_prefs(patch: dict) -> dict:
    """Validate a partial prefs update; returns the cleaned partial patch.
    ``timezone`` and ``quiet_hours_active`` are read-only and ignored."""
    if not isinstance(patch, dict):
        raise _invalid("Body must be an object")
    out: dict = {}
    for key, v in patch.items():
        if key in ("timezone", "quiet_hours_active"):
            continue
        if key in ("digest_weekly", "digest_push"):
            if not isinstance(v, bool):
                raise _invalid(f"{key} must be a boolean")
            out[key] = v
        elif key == "digest_day":
            out[key] = _int(v, 1, 7, key)
        elif key == "instant":
            if v not in ("all", "targets_only"):
                raise _invalid("instant must be 'all' or 'targets_only'")
            out[key] = v
        elif key == "group_window_min":
            out[key] = _int(v, 0, 120, key)
        elif key == "quiet_hours":
            if not isinstance(v, dict):
                raise _invalid("quiet_hours must be an object")
            qh: dict = {}
            for k, x in v.items():
                if k == "enabled" and isinstance(x, bool):
                    qh[k] = x
                elif k in ("start", "end") and isinstance(x, str) and _HHMM.match(x):
                    qh[k] = x
                else:
                    raise _invalid(f"quiet_hours.{k} is invalid")
            out[key] = qh
        elif key == "daily_cap":
            if not isinstance(v, dict):
                raise _invalid("daily_cap must be an object")
            caps: dict = {}
            for k, x in v.items():
                if k not in KINDS:
                    raise _invalid(f"daily_cap.{k} is not a watch kind")
                caps[k] = _int(x, 1, 10, f"daily_cap.{k}")
            out[key] = caps
        else:
            raise _invalid(f"Unknown preference: {key}")
    return out


def merge_prefs(current: dict, patch: dict) -> dict:
    merged = {**current}
    for k, v in patch.items():
        merged[k] = {**current.get(k, {}), **v} if isinstance(v, dict) else v
    return merged


# ── Dispatch ──────────────────────────────────────────────────────────────────

_tasks: set[asyncio.Task] = set()


def _user_tz(user_id: str) -> str | None:
    from ..db import user_settings_db

    try:
        return user_settings_db.get_settings(user_id).get("timezone")
    except Exception:  # noqa: BLE001
        return None


def _last_push_at(user_id: str) -> datetime | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(sent_at) AS t FROM alert_outbox"
            " WHERE user_id = ? AND channel = 'push' AND sent_at IS NOT NULL",
            (user_id,),
        ).fetchone()
    return _parse_iso(row["t"]) if row and row["t"] else None


def _sent_today(user_id: str, kind: str, day_start_utc: str, channel: str) -> int:
    """Like ``alerts_db.sent_today`` but expired/error notes do not count."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM alert_outbox o"
            " JOIN notifications n ON n.id = o.notification_id"
            " WHERE o.user_id = ? AND o.watch_kind = ? AND o.channel = ?"
            " AND o.sent_at IS NOT NULL AND o.sent_at >= ?"
            " AND n.kind NOT IN ('watch_expired', 'watch_error')",
            (user_id, kind, channel, day_start_utc),
        ).fetchone()[0]


def _counts(user_id: str, kind: str, now: datetime, tz: str | None) -> dict:
    start = _iso(_local_day_start(now, tz))
    return {c: _sent_today(user_id, kind, start, c) for c in CHANNELS}


def dispatch(watch: dict, watch_kind: str, row: dict, now: datetime) -> None:
    """Apply the delivery rules to one stored notification and enqueue each
    channel with its due time (or record why it was dropped)."""
    user_id = watch["user_id"]
    prefs = alerts_db.get_prefs(user_id)
    tz = _user_tz(user_id)
    category_on = True
    if settings.notifications_v2_enabled:
        from . import notify_settings

        category_on = notify_settings.category_enabled(user_id, "price_drops")
    decision = plan(
        row,
        watch_kind,
        prefs,
        tz,
        _counts(user_id, watch_kind, now, tz),
        _last_push_at(user_id),
        now,
        category_on,
    )
    wanted = [
        c for c in CHANNELS if c != "email" or watch.get("email_enabled")
    ]  # email keeps the per-watch opt-in
    if not decision.channels:
        for c in wanted:
            alerts_db.enqueue(user_id, row["id"], c, watch_kind, _iso(now))
            _drop(row["id"], c, decision.reason)
        return
    kick = False
    for c in wanted:
        if c not in decision.channels:  # one channel capped, the other not
            alerts_db.enqueue(user_id, row["id"], c, watch_kind, _iso(now))
            _drop(row["id"], c, "cap")
            continue
        due = decision.due_at
        if c == "email" and decision.email_due_at:
            due = decision.email_due_at
        alerts_db.enqueue(user_id, row["id"], c, watch_kind, _iso(due))
        kick = kick or due <= now
    if kick:
        _kick(now)


def _drop(notification_id: int, channel: str, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE alert_outbox SET dropped_reason = ?"
            " WHERE notification_id = ? AND channel = ?",
            (reason, notification_id, channel),
        )


def _kick(now: datetime) -> None:
    """Send what is due right away when an event loop is running; otherwise
    the next loop pass does it."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_safe_flush(now))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _safe_flush(now: datetime) -> None:
    try:
        await asyncio.to_thread(flush, now)
    except Exception:  # noqa: BLE001
        logger.warning("alert flush failed", exc_info=True)


# ── Flush ─────────────────────────────────────────────────────────────────────


def _note(notification_id: int) -> dict | None:
    from ..db import notifications_db

    with get_connection() as conn:
        r = conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        ).fetchone()
    return notifications_db._row(r) if r else None


def _load_watch(watch_kind: str, notification: dict) -> dict | None:
    wid = (notification.get("data") or {}).get("watch_id")
    if wid is None:
        return None
    store = fare_watch_db if watch_kind == "flight" else price_watch_db
    return store.get_watch(int(wid))


def _unclaim_dropped(item_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE alert_outbox SET sent_at = NULL, dropped_reason = ? WHERE id = ?",
            (reason, item_id),
        )


def _enforce_caps(items: list[dict], now: datetime) -> list[dict]:
    """Items held for hours may pile up past the daily cap: keep the first
    ``cap - already_sent`` of each (user, kind, channel) and drop the rest."""
    kept: list[dict] = []
    seen: dict[tuple, int] = {}
    tzs: dict[str, str | None] = {}
    prefs_by: dict[str, dict] = {}
    for it in items:
        uid = it["user_id"]
        note = _note(it["notification_id"])
        if note and note.get("kind") in LEGACY_NOTE_KINDS:
            kept.append(it)  # expired / error notes are never capped
            continue
        if uid not in tzs:
            tzs[uid] = _user_tz(uid)
            prefs_by[uid] = alerts_db.get_prefs(uid)
        cap = (prefs_by[uid].get("daily_cap") or {}).get(it["watch_kind"], 3)
        key = (uid, it["watch_kind"], it["channel"])
        if key not in seen:
            start = _iso(_local_day_start(now, tzs[uid]))
            total = _sent_today(uid, it["watch_kind"], start, it["channel"])
            in_batch = sum(
                1
                for x in items
                if (x["user_id"], x["watch_kind"], x["channel"]) == key
                and not _is_legacy(x)
            )
            seen[key] = max(0, cap - (total - in_batch))
        if seen[key] > 0:
            seen[key] -= 1
            kept.append(it)
        else:
            _unclaim_dropped(it["id"], "cap")
    return kept


def _is_legacy(item: dict) -> bool:
    note = _note(item["notification_id"])
    return bool(note and note.get("kind") in LEGACY_NOTE_KINDS)


def _push_payload(rows: list[dict]) -> tuple[str, str, dict]:
    last = rows[-1]
    if len(rows) == 1:
        extra = last.get("data") or {}
        data = {
            "kind": last["kind"],
            "notification_id": str(last["id"]),
            "link": (extra.get("links") or {}).get("alerts")
            or f"/alerts?watch={extra.get('watch_id')}",
            "category": "price_drops",
            "plan_id": "",
        }
        for key in ("watch_id", "watch_kind"):
            if extra.get(key) is not None:
                data[key] = str(extra[key])
        return last["title"], last["body"], data
    body = "; ".join(r["title"] for r in rows[:3])
    if len(rows) > 3:
        body += f" and {len(rows) - 3} more"
    data = {
        "kind": last["kind"],
        "notification_id": str(last["id"]),
        "link": "/alerts",
        "category": "price_drops",
        "plan_id": "",
        "group_count": str(len(rows)),
    }
    return f"{len(rows)} prices dropped", body, data


async def _send_push(user_id: str, rows: list[dict]) -> None:
    from ..db.users_db import get_user_by_id
    from . import push

    user = get_user_by_id(user_id)
    if not user or not user.get("is_active"):
        return
    title, body, data = _push_payload(rows)
    await push.send_to_user(user["username"], title, body, data)


def flush(now: datetime) -> int:
    """Send every due outbox item exactly once; returns how many were sent.
    Push items due together for one user go out as one grouped push.
    Synchronous (callable from a thread); the loop runs it off the event
    loop with ``asyncio.to_thread``."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_flush(now))
    with ThreadPoolExecutor(max_workers=1) as ex:  # called from inside a loop
        return ex.submit(asyncio.run, _flush(now)).result()


async def _flush(now: datetime) -> int:
    from . import alert_email

    claimed = alerts_db.claim_due(_iso(now), FLUSH_BATCH)
    if not claimed:
        return 0
    cutoff = _iso(now - STALE_AFTER)
    fresh = []
    for it in claimed:
        if it["due_at"] < cutoff:
            _unclaim_dropped(it["id"], "stale")
        else:
            fresh.append(it)
    claimed = _enforce_caps(fresh, now) if fresh else []
    sent = 0
    pushes: dict[str, list[dict]] = {}
    for it in claimed:
        note = _note(it["notification_id"])
        if note is None:
            continue
        if it["channel"] == "push":
            pushes.setdefault(it["user_id"], []).append(note)
            sent += 1
            continue
        watch = _load_watch(it["watch_kind"], note)
        if watch is None:
            continue
        try:
            if await alert_email.deliver_one(it["watch_kind"], watch, note, now):
                sent += 1
        except Exception:  # noqa: BLE001
            logger.warning("alert email flush failed", exc_info=True)
    for user_id, rows in pushes.items():
        try:
            # expired/error notes go out alone, with today's text and priority
            groupable = [r for r in rows if r["kind"] not in LEGACY_NOTE_KINDS]
            for r in rows:
                if r["kind"] in LEGACY_NOTE_KINDS:
                    await _send_push(user_id, [r])
            if groupable:
                await _send_push(user_id, groupable)
        except Exception:  # noqa: BLE001
            logger.warning("alert push flush failed", exc_info=True)
    return sent


# ── Loop ──────────────────────────────────────────────────────────────────────


DIGEST_INTERVAL_S = 300
TRIP_PUSH_INTERVAL_S = 300


async def _loop(interval: int) -> None:
    from . import alert_digest

    last_digest = 0.0
    last_trip = -TRIP_PUSH_INTERVAL_S
    while True:
        try:
            await asyncio.to_thread(flush, datetime.now(UTC))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("alert flush pass failed", exc_info=True)
        if settings.notifications_v2_enabled:
            try:
                from . import notify_center

                await asyncio.to_thread(notify_center.flush_due, datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("notify flush pass failed", exc_info=True)
            try:
                from . import trip_pushes

                if time_mod.monotonic() - last_trip >= TRIP_PUSH_INTERVAL_S:
                    last_trip = time_mod.monotonic()
                    t = datetime.now(UTC)
                    await asyncio.to_thread(trip_pushes.run_due, t)
                    await asyncio.to_thread(trip_pushes.prune_log, t)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("trip push pass failed", exc_info=True)
        if time_mod.monotonic() - last_digest >= DIGEST_INTERVAL_S:
            last_digest = time_mod.monotonic()
            try:
                await asyncio.to_thread(alert_digest.run_due, datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.warning("weekly digest pass failed", exc_info=True)
        await asyncio.sleep(interval)


def start_loop() -> asyncio.Task | None:
    """The outbox flush loop; ``None`` while the v2 flag is off. Items left
    over from a stopped loop stay due and go out on the next start."""
    if not settings.price_alerts_v2_enabled:
        return None
    return asyncio.create_task(_loop(max(1, settings.alert_flush_interval_s)))


async def stop_loop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
