"""Trip-phase pushes: T-30 visa, T-7 packing, T-1 check-in and a morning brief
on each trip day. ``run_due(now)`` is called from the alert loop (flag
``notifications_v2_enabled``); delivery, quiet hours and caps live in
``notify_center``. Each push fires once (dedupe key per user, plan, kind and,
for the brief, the local day) and only inside its window, so a missed run is
never replayed late. No game wording and no coordinates here."""

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..agents.static_results import _DESTINATION_TIPS, _match_table_key
from ..db import trip_snapshot_db, user_settings_db
from ..db.database import get_connection
from ..db.plans_db import _row_to_dict
from . import notify_center, notify_settings, notify_text, trip_prep
from .trip_phase import day_index, trip_dates

logger = logging.getLogger(__name__)

MAX_PLANS = 500
LOOKAHEAD_DAYS = 31
TX_HOUR = 9  # local (or UTC without a timezone) hour T-x pushes go out
MORNING_HOUR = 8
LOG_RETENTION_DAYS = 60
# kind -> (window of days-to-start, newest first, prep item that must be open)
_TX = {
    "trip_t30": ((25, 30), "visa"),
    "trip_t7": ((5, 7), "packing"),
    "trip_t1": ((0, 1), "checkin"),
}
_SLOT_ORDER = {"morning": 0, "afternoon": 1, "evening": 2, "night": 3}


def _zone(tz: str | None):
    try:
        return ZoneInfo(tz) if tz else UTC
    except Exception:  # noqa: BLE001
        return UTC


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _candidates(now: datetime) -> list[dict]:
    lo = (now - timedelta(days=2)).date().isoformat()
    hi = (now + timedelta(days=LOOKAHEAD_DAYS + 1)).date().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT p.*, u.id AS user_id FROM plans p JOIN users u"
            " ON u.username = p.username WHERE u.is_active = 1"
            " AND p.start_date IS NOT NULL AND p.start_date <= ?"
            " AND COALESCE(p.end_date, p.start_date) >= ?"
            " ORDER BY p.start_date LIMIT ?",
            (hi, lo, MAX_PLANS),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _destination(plan: dict) -> str:
    sd = _dict(plan.get("search_data"))
    dest = sd.get("destination")
    if not dest and isinstance(sd.get("destinations"), list) and sd["destinations"]:
        dest = sd["destinations"][0]
    return dest if isinstance(dest, str) and dest else (plan.get("name") or "")


def _weather_line(snapshot: dict | None, day: date) -> str | None:
    days = _dict(_dict(snapshot).get("weather")).get("days")
    if not isinstance(days, list):
        return None
    for d in days:
        if isinstance(d, dict) and str(d.get("date"))[:10] == day.isoformat():
            desc = d.get("description")
            hi, lo = d.get("temp_high_c"), d.get("temp_low_c")
            nums = [x for x in (lo, hi) if isinstance(x, (int, float))]
            if not desc and not nums:
                return None
            temp = f"{round(min(nums))}-{round(max(nums))}°C" if nums else ""
            return " ".join(x for x in (str(desc or "").strip(), temp) if x)
    return None


def _slot_text(slot) -> str | None:
    if not isinstance(slot, dict):
        return None
    for k in ("activity", "name", "title"):
        if isinstance(slot.get(k), str) and slot[k].strip():
            return slot[k].strip()
    return None


def _first_slot(selections: dict, idx: int) -> str | None:
    slots = [
        s
        for s in _dict(selections).get("itinerary_slots") or []
        if isinstance(s, dict) and s.get("day_number") == idx
    ]
    if not slots:
        itin = _dict(selections).get("itinerary")
        days = itin.get("days") if isinstance(itin, dict) else itin
        if isinstance(days, list):
            day = next(
                (d for d in days if isinstance(d, dict) and d.get("day_number") == idx),
                days[idx - 1] if idx - 1 < len(days) else None,
            )
            slots = [s for s in _dict(day).get("slots") or [] if isinstance(s, dict)]
    slots.sort(
        key=lambda s: (
            str(s.get("start_time") or "99"),
            _SLOT_ORDER.get(s.get("time_of_day"), 9),
        )
    )
    for s in slots:
        if text := _slot_text(s):
            return text
    return None


def _tip(destination: str, idx: int) -> str | None:
    key = _match_table_key(destination, _DESTINATION_TIPS) if destination else None
    tips = _DESTINATION_TIPS.get(key) if key else None
    if not tips:
        return None
    t = tips[(idx - 1) % len(tips)]
    return t.get("title") if isinstance(t, dict) else None


def _send(uid, plan, kind, category, key, body, link, now) -> bool:
    r = notify_center.enqueue_category(
        uid,
        plan["id"],
        kind,
        category,
        key,
        "Voyager",
        body,
        {"link": link},
        now,
    )
    return r is not None


def _lines(locale: str, dest: str, kind: str, extras: list[tuple[str, str | None]]):
    parts = [notify_text.render(kind, locale, destination=dest)]
    for key, val in extras:
        if val:
            param = key.rsplit("_", 1)[-1]
            parts.append(notify_text.render(key, locale, **{param: val}))
    return "\n".join(parts)


def _plan_pushes(plan: dict, now: datetime, ctx: dict) -> int:
    uid = plan["user_id"]
    u = ctx.setdefault(uid, {})
    if "tz" not in u:
        u["tz"] = user_settings_db.get_settings(uid).get("timezone")
        u["cats"] = notify_settings.stored(uid)["categories"]
        u["locale"] = notify_center.user_locale(uid)
    tz, cats, locale = u["tz"], u["cats"], u["locale"]
    local = now.astimezone(_zone(tz))
    today = local.date()
    start, end = trip_dates(plan)
    if start is None:
        return 0
    dest = _destination(plan)
    snapshot = None
    sent = 0
    link = f"/trips/{plan['id']}"
    to_start = (start - today).days

    for kind, ((lo, hi), item_id) in _TX.items():
        if not cats.get("trip_reminders", True) or not (lo <= to_start <= hi):
            continue
        if local.hour < TX_HOUR:
            continue
        prep = trip_prep.prep_payload(plan, today)
        item = next((i for i in prep["items"] if i["id"] == item_id), None)
        # no flight (check-in "na") still gets the day-before nudge
        open_ = item and (
            item["status"] != "done" if kind == "trip_t1" else item["status"] == "todo"
        )
        if not open_:
            continue
        extras = []
        if kind == "trip_t1" and cats.get("weather", True):
            snapshot = snapshot or trip_snapshot_db.get_snapshot(plan["id"]) or {}
            extras.append(("trip_morning_weather", _weather_line(snapshot, start)))
        body = _lines(locale, dest, kind, extras)
        key = f"trip:{uid}:{plan['id']}:{kind}"
        sent += _send(uid, plan, kind, "trip_reminders", key, body, link, now)

    idx = day_index(start, end, today)
    if idx and tz and local.hour >= MORNING_HOUR and cats.get("morning_brief", True):
        snapshot = snapshot or trip_snapshot_db.get_snapshot(plan["id"]) or {}
        extras = [
            ("trip_morning_slot", _first_slot(_dict(plan.get("selections")), idx)),
            ("trip_morning_tip", _tip(dest, idx)),
        ]
        if cats.get("weather", True):
            extras.append(("trip_morning_weather", _weather_line(snapshot, today)))
        body = _lines(locale, dest, "trip_morning", extras)
        key = f"trip:{uid}:{plan['id']}:trip_morning:{today.isoformat()}"
        sent += _send(
            uid, plan, "trip_morning", "morning_brief", key, body, link + "/today", now
        )
    return sent


def run_due(now: datetime) -> int:
    """Enqueue every push that is due now; returns how many were enqueued.
    One failing plan never stops the pass."""
    now = now.astimezone(UTC)
    total, ctx = 0, {}
    for plan in _candidates(now):
        try:
            total += _plan_pushes(plan, now, ctx)
        except Exception:  # noqa: BLE001
            logger.warning(
                "trip push failed for plan %s", plan.get("id"), exc_info=True
            )
    return total


def prune_log(now: datetime) -> int:
    cutoff = (now - timedelta(days=LOG_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection() as conn:
        return conn.execute(
            "DELETE FROM notify_log WHERE created_at < ?", (cutoff,)
        ).rowcount
