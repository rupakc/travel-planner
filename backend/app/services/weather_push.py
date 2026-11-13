"""Weather-change pushes for today's outdoor itinerary slots (category
``weather``, kinds ``weather_rain`` / ``weather_heat`` / ``weather_cold``).

``run_due(now)`` runs from the alert loop (flags ``notifications_v2_enabled``
and ``weather_push_enabled``, default off) every ``weather_push_interval_hours``.
Only trips ``on_the_road`` today are considered, with one forecast call per
trip city per pass (further cached by the client and capped per hour). Delivery,
quiet hours, caps and the user's ``weather`` switch are applied by
``notify_center``; each (user, trip, slot, condition, day) fires once via the
notify log's dedupe key. Weather data by Open-Meteo.com (CC BY 4.0)."""

import logging
import re
import time as time_mod
from collections import deque
from datetime import UTC, datetime, timedelta

from ..core.config import settings
from ..db import user_settings_db
from ..db.places_db import resolve_place
from ..utils.geo import lookup_coords
from . import alert_delivery, notify_center, notify_settings, notify_text, trip_pushes
from .trip_geo import city_for_day
from .trip_phase import day_index, effective_phase, trip_dates
from .weather_client import Forecast, OpenMeteoClient, WeatherClient

logger = logging.getLogger(__name__)

RAIN_PROB_PCT = 60.0
RAIN_MM = 1.0
HEAT_C = 35.0
COLD_C = 0.0
LOOKAHEAD_H = 3  # alert for slots starting within this many hours
_HOURS = {"morning": 9, "afternoon": 14, "evening": 19}  # night: no outdoor alert
_OUTDOOR = re.compile(
    r"\b(park|garden|beach|hike|hiking|trek|walk|walking|tour|market|temple|"
    r"shrine|viewpoint|lookout|trail|boat|cruise|kayak|surf|snorkel|safari|"
    r"waterfall|island|mountain|castle|ruins|square|bridge|street|picnic|"
    r"zoo|bike|cycling|outdoor|sunrise|sunset)\b",
    re.I,
)
_INDOOR = re.compile(
    r"\b(museum|gallery|mall|cinema|theat(er|re)|aquarium|spa|restaurant|cafe|"
    r"café|hotel|indoor|class|workshop|library|cathedral|church|mosque)\b",
    re.I,
)

_calls: deque[float] = deque()  # monotonic times of recent forecast calls
_client: WeatherClient | None = None


def is_outdoor(slot: dict) -> bool:
    """Explicit ``outdoor`` / ``indoor`` flags win, else a keyword heuristic."""
    if isinstance(slot.get("outdoor"), bool):
        return slot["outdoor"]
    if isinstance(slot.get("indoor"), bool):
        return not slot["indoor"]
    text = " ".join(
        str(slot.get(k) or "")
        for k in ("activity", "name", "title", "category", "type")
    )
    if _INDOOR.search(text):
        return False
    return bool(_OUTDOOR.search(text))


def slot_hour(slot: dict) -> int | None:
    """Local start hour: ``start_time`` HH:MM, else a part-of-day default."""
    st = slot.get("start_time")
    if isinstance(st, str) and re.match(r"^([01]\d|2[0-3]):[0-5]\d", st):
        return int(st[:2])
    return _HOURS.get(slot.get("time_of_day"))


def evaluate(fc: Forecast, day: str, hour: int) -> str | None:
    """``rain`` | ``heat`` | ``cold`` | None for one destination-local hour."""
    key = f"{day}T{hour:02d}:00"
    prob, mm, feel = (
        fc.precip_prob.get(key),
        fc.precip_mm.get(key),
        fc.apparent_c.get(key),
    )
    if (prob is not None and prob >= RAIN_PROB_PCT) or (
        mm is not None and mm >= RAIN_MM
    ):
        return "rain"
    if feel is not None and feel >= HEAT_C:
        return "heat"
    if feel is not None and feel <= COLD_C:
        return "cold"
    return None


def _day_slots(selections: dict, idx: int) -> list[dict]:
    sel = selections if isinstance(selections, dict) else {}
    slots = [
        s
        for s in sel.get("itinerary_slots") or []
        if isinstance(s, dict) and s.get("day_number") == idx
    ]
    if not slots:
        itin = sel.get("itinerary")
        days = itin.get("days") if isinstance(itin, dict) else itin
        if isinstance(days, list):
            day = next(
                (d for d in days if isinstance(d, dict) and d.get("day_number") == idx),
                days[idx - 1] if 0 < idx <= len(days) else None,
            )
            if isinstance(day, dict):
                slots = [s for s in day.get("slots") or [] if isinstance(s, dict)]
    return slots


def _coords(city: str) -> tuple[float, float] | None:
    try:
        p = resolve_place(city)
        if p and p.lat is not None and p.lng is not None:
            return p.lat, p.lng
    except Exception:  # noqa: BLE001
        pass
    return lookup_coords(city)


def _budget_ok() -> bool:
    now = time_mod.monotonic()
    while _calls and now - _calls[0] > 3600:
        _calls.popleft()
    return len(_calls) < settings.weather_push_max_calls_per_hour


def _get_client() -> WeatherClient:
    global _client
    if _client is None:
        _client = OpenMeteoClient()
    return _client


def _slot_name(slot: dict) -> str:
    return (trip_pushes._slot_text(slot) or "")[:60]


def _plan_alerts(plan, now, ctx, fetch) -> int:
    uid = plan["user_id"]
    u = ctx.setdefault(uid, {})
    if "tz" not in u:
        tz0 = user_settings_db.get_settings(uid).get("timezone")
        u["tz"] = tz0 if alert_delivery._zone(tz0) else None
        u["on"] = notify_settings.stored(uid)["categories"].get("weather", True)
        u["locale"] = notify_center.user_locale(uid)
    if not u["on"]:
        return 0
    today = now.astimezone(trip_pushes._zone(u["tz"])).date()
    start, end = trip_dates(plan)
    if (
        start is None
        or effective_phase(start, end, plan.get("phase"), today, False) != "on_the_road"
    ):
        return 0
    idx = day_index(start, end, today)
    slots = [
        s
        for s in _day_slots(plan.get("selections"), idx or 0)
        if is_outdoor(s) and slot_hour(s) is not None
    ]
    if not slots:
        return 0
    city = city_for_day(plan.get("search_data") or {}, start, end, idx)
    xy = _coords(city) if city else None
    if not xy:
        return 0
    fc = fetch(xy)
    if fc is None:
        return 0
    dest_now = now + timedelta(seconds=fc.utc_offset_s)
    day = dest_now.date().isoformat()
    sent = 0
    for s in slots:
        h = slot_hour(s)
        if not dest_now.hour <= h <= dest_now.hour + LOOKAHEAD_H:
            continue
        cond = evaluate(fc, day, h)
        if not cond:
            continue
        name = _slot_name(s)
        kind = f"weather_{cond}"
        body = notify_text.render(
            kind, u["locale"], slot=name or "", time=f"{h:02d}:00"
        )
        key = f"weather:{uid}:{plan['id']}:{day}:{h}:{name.lower()}:{cond}"
        sent += trip_pushes._send(
            uid, plan, kind, "weather", key, body, f"/trips/{plan['id']}/today", now
        )
    return sent


def run_due(now: datetime, client: WeatherClient | None = None) -> int:
    """Enqueue due weather pushes; returns how many. One failing plan never
    stops the pass, and at most one forecast call is made per place."""
    now = now.astimezone(UTC)
    client = client or _get_client()
    memo: dict[tuple, Forecast | None] = {}

    def fetch(xy):
        key = (round(xy[0], 1), round(xy[1], 1))
        if key not in memo:
            if not _budget_ok():
                logger.warning("weather push hourly call budget reached")
                return None
            _calls.append(time_mod.monotonic())
            memo[key] = client.forecast(*xy)
        return memo[key]

    total, ctx = 0, {}
    for plan in trip_pushes._candidates(now):
        try:
            total += _plan_alerts(plan, now, ctx, fetch)
        except Exception:  # noqa: BLE001
            logger.warning(
                "weather push failed for plan %s", plan.get("id"), exc_info=True
            )
    return total
