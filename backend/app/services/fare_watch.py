"""Fare watch: re-check watched fares and decide when to tell the traveller.

``evaluate`` holds the trigger and anti-spam rules (pure). ``check_watch``
runs one check of one watch: expiry, the daily SerpAPI budget, the live
fare, history, failures and the resulting notification. The scheduler
loop that calls it lives further down (see ``run_scheduler``).
"""

import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from ..core.config import settings
from ..db import fare_watch_db, notifications_db
from ..schemas.request import TravelSearchRequest
from . import serp_flights
from .serp_flights import SerpAPIError

logger = logging.getLogger(__name__)

# ── Rule constants ────────────────────────────────────────────────────────────

DROP_MIN_USD = 15.0  # any_drop: at least $15 …
DROP_MIN_PCT = 0.05  # … and at least 5 % below the reference price
CHEAPER_DATE_MIN_USD = 25.0  # nearby date: at least $25 …
CHEAPER_DATE_MIN_PCT = 0.08  # … and 8 % cheaper than the selected dates
COOLDOWN = timedelta(hours=24)  # one alert per watch per day …
COOLDOWN_FURTHER_DROP_PCT = 0.05  # … unless 5 % below the last alert

FAILURES_BEFORE_ERROR = 3
RETRY_AFTER_FAILURE = timedelta(hours=1)
JITTER = 0.10  # ±10 % on the check interval

# Highest priority first: one check yields at most one notification.
_PRIORITY = ("fare_target", "fare_drop", "fare_low_level", "fare_cheaper_date")


@dataclass
class FareCheck:
    """One live look at a watched fare (prices are totals for all travellers)."""

    price: float | None  # cheapest fare for the selected dates
    price_level: str | None = None  # Google: low / typical / high
    typical_low: float | None = None
    typical_high: float | None = None
    cheapest_price: float | None = None  # flexible: cheapest of ±N days
    cheapest_departure_date: str | None = None
    cheapest_return_date: str | None = None
    calls: int = 0  # SerpAPI calls this check spent


@dataclass
class CheckOutcome:
    # checked | expired | postponed | failed | errored | skipped | budget_exhausted
    status: str
    watch: dict | None
    notification: dict | None = None


# ── Wording helpers ───────────────────────────────────────────────────────────


def _city(label: str | None, code: str) -> str:
    name = (label or "").split(",")[0].strip()
    return name or code.split(",")[0]


def route_label(watch: dict) -> str:
    return (
        f"{_city(watch.get('origin_label'), watch['origin_code'])} → "
        f"{_city(watch.get('destination_label'), watch['destination_code'])}"
    )


def usd(amount: float) -> str:
    return f"${round(amount):,}"


def date_range(dep: str, ret: str | None) -> str:
    """'1–8 Dec', '28 Nov – 5 Dec', '28 Dec 2026 – 4 Jan 2027', '1 Dec'."""
    d = date.fromisoformat(dep)
    if not ret:
        return f"{d.day} {d:%b}"
    r = date.fromisoformat(ret)
    if d.year != r.year:
        return f"{d.day} {d:%b %Y} – {r.day} {r:%b %Y}"
    if d.month != r.month:
        return f"{d.day} {d:%b} – {r.day} {r:%b}"
    return f"{d.day}–{r.day} {r:%b}"


def travellers(n: int) -> str:
    return f"total for {n} traveller{'s' if n != 1 else ''}"


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _links(watch: dict, dep: str, ret: str | None, cheapest: bool = False) -> dict:
    alerts = f"/alerts?watch={watch['id']}"
    return {
        "alerts": alerts,
        "replan": alerts + "&replan=1" + ("&cheapest=1" if cheapest else ""),
        "book": serp_flights._google_flights_url(
            watch["origin_code"], watch["destination_code"], dep, ret
        ),
    }


# ── Trigger rules ─────────────────────────────────────────────────────────────


def _candidates(watch: dict, check: FareCheck) -> list[tuple[str, float]]:
    """Every rule that fires, as (kind, featured price), unordered."""
    p = check.price
    mode = watch["alert_mode"]
    target = watch.get("target_price")
    baseline = watch["baseline_price"]
    ref = watch.get("last_notified_price") or baseline
    lowest = watch.get("lowest_price")
    out: list[tuple[str, float]] = []
    if p is None:
        return out
    if mode == "below_target" and target is not None and p <= target:
        out.append(("fare_target", p))
    if mode == "any_drop":
        if p <= ref - max(DROP_MIN_USD, DROP_MIN_PCT * ref):
            out.append(("fare_drop", p))
        if check.price_level == "low" and lowest is not None and p < lowest:
            out.append(("fare_low_level", p))
    c = check.cheapest_price
    if (
        watch.get("flexible_days")
        and c is not None
        and check.cheapest_departure_date
        and check.cheapest_departure_date != watch["departure_date"]
        and p - c >= max(CHEAPER_DATE_MIN_USD, CHEAPER_DATE_MIN_PCT * p)
        and (mode == "any_drop" or (target is not None and c <= target))
    ):
        out.append(("fare_cheaper_date", c))
    return out


def evaluate(watch: dict, check: FareCheck, now: datetime) -> list[dict]:
    """The notification (at most one) this check deserves.

    Rules (highest priority wins; see the plan's Design section):
    1. below_target — price ≤ target.
    2. any_drop — price ≤ reference − max($15, 5 %).
    3. any_drop — a new lowest since watching that Google calls "low".
    4. flexible — a nearby date ≥ max($25, 8 %) cheaper than the selected
       dates (in below_target mode only when that date also beats the target).
    Anti-spam, for every rule: never on the first check (it is the
    baseline); never unless the featured price is below the reference (the
    last alerted price, else the baseline) — so never for increases or
    repeats; within 24 h of an alert only for a further ≥ 5 % drop.
    """
    if watch.get("baseline_price") is None or not watch.get("check_count"):
        return []
    ref = watch.get("last_notified_price") or watch["baseline_price"]
    last_at = watch.get("last_notified_at")
    cooling = bool(last_at) and now - _parse_ts(last_at) < COOLDOWN
    found = dict(_candidates(watch, check))
    for kind in _PRIORITY:
        if kind not in found:
            continue
        featured = found[kind]
        if featured >= ref:
            continue
        if cooling and featured > watch["last_notified_price"] * (
            1 - COOLDOWN_FURTHER_DROP_PCT
        ):
            continue
        return [_compose(kind, watch, check, ref)]
    return []


def _compose(kind: str, watch: dict, check: FareCheck, ref: float) -> dict:
    route = route_label(watch)
    n = watch["num_travelers"]
    dep, ret = watch["departure_date"], watch.get("return_date")
    lowest = watch.get("lowest_price")
    data = {
        "watch_id": watch["id"],
        "route": route,
        "num_travelers": n,
        "previous_price": ref,
        "baseline_price": watch["baseline_price"],
        "target_price": watch.get("target_price"),
        "departure_date": dep,
        "return_date": ret,
        "price_level": check.price_level,
    }
    if kind == "fare_cheaper_date":
        c = check.cheapest_price
        cdep, cret = check.cheapest_departure_date, check.cheapest_return_date
        save = check.price - c
        data.update(
            price=c,
            selected_price=check.price,
            delta=round(c - ref, 2),
            saving=round(save, 2),
            cheapest_departure_date=cdep,
            cheapest_return_date=cret,
            is_lowest=lowest is None or c < lowest,
            links=_links(watch, cdep, cret, cheapest=True),
        )
        d = date.fromisoformat(cdep)
        title = f"Fly {route} on {d.day} {d:%b} and save {usd(save)}"
        body = (
            f"{usd(c)} for {date_range(cdep, cret)} vs {usd(check.price)} for "
            f"your dates · {travellers(n)}."
        )
        return {"kind": kind, "title": title, "body": body, "data": data}

    p = check.price
    is_lowest = lowest is None or p < lowest
    data.update(
        price=p,
        delta=round(p - ref, 2),
        is_lowest=is_lowest,
        links=_links(watch, dep, ret),
    )
    when = f"For {date_range(dep, ret)} · {travellers(n)}."
    extras = []
    if is_lowest:
        extras.append("The lowest we've seen since you started watching.")
    google_low = "Google says this is a low price for this route."
    if kind == "fare_target":
        title = (
            f"{route} is now {usd(p)} — under your {usd(watch['target_price'])} target"
        )
        if check.price_level == "low":
            extras.append(google_low)
    elif kind == "fare_drop":
        title = f"{route} dropped to {usd(p)} (−{usd(ref - p)})"
        if check.price_level == "low":
            extras.append(google_low)
    else:  # fare_low_level
        title = f"{route}: {usd(p)} is a low price"
        extras = [
            "Google Flights rates this as low for the route — and it's the "
            "lowest we've seen since you started watching."
        ]
    body = " ".join([when, *extras])
    return {"kind": kind, "title": title, "body": body, "data": data}


def _expired_note(watch: dict) -> dict:
    route = route_label(watch)
    d = date.fromisoformat(watch["departure_date"])
    body = f"Departure day ({d.day} {d:%b}) has arrived, so we've stopped checking."
    if watch.get("lowest_price") is not None:
        body += f" The lowest fare we saw was {usd(watch['lowest_price'])}."
    return {
        "kind": "watch_expired",
        "title": f"Your {route} fare watch has ended",
        "body": body,
        "data": {"watch_id": watch["id"], "route": route},
    }


def _error_note(watch: dict) -> dict:
    route = route_label(watch)
    return {
        "kind": "watch_error",
        "title": f"We couldn't check {route}",
        "body": (
            "Live fares failed three times in a row, so we've paused this "
            "watch. Retry whenever you like."
        ),
        "data": {
            "watch_id": watch["id"],
            "route": route,
            "action": "retry",
            "links": {"alerts": f"/alerts?watch={watch['id']}"},
        },
    }


# ── Live fares ────────────────────────────────────────────────────────────────


def watch_request(watch: dict) -> TravelSearchRequest:
    """A search request for the watched trip, with its resolved codes."""
    ret = watch.get("return_date")
    return TravelSearchRequest.model_construct(
        origin=watch["origin_label"],
        destination=watch["destination_label"],
        departure_date=date.fromisoformat(watch["departure_date"]),
        return_date=date.fromisoformat(ret) if ret else None,
        nationality="",
        num_travelers=watch["num_travelers"],
        origin_iata=watch["origin_code"],
        destination_iata=watch["destination_code"],
    )


def _estimate_calls(watch: dict) -> int:
    return serp_flights.watch_call_estimate(
        watch_request(watch), watch.get("flexible_days") or 0
    )


async def fetch_fares(watch: dict, api_key: str) -> FareCheck:
    """Live fare for a watch (SerpAPIError when the selected dates fail)."""
    fares = await serp_flights.watch_fares(
        api_key, watch_request(watch), watch.get("flexible_days") or 0
    )
    insights = fares.get("price_insights") or {}
    rng = insights.get("typical_price_range") or [None, None]
    check = FareCheck(
        price=fares["price"],
        price_level=insights.get("price_level"),
        typical_low=rng[0],
        typical_high=rng[1],
        calls=fares["calls"],
    )
    priced = [d for d in fares.get("dates", []) if d.get("cheapest_usd") is not None]
    if priced:
        best = min(priced, key=lambda d: (d["cheapest_usd"], d["departure_date"]))
        check.cheapest_price = float(best["cheapest_usd"])
        check.cheapest_departure_date = best["departure_date"]
        check.cheapest_return_date = best["return_date"]
    return check


# ── One check ─────────────────────────────────────────────────────────────────

_budget_logged_day: str | None = None


def _next_day(now: datetime, rand: Callable[[], float]) -> datetime:
    """Early next UTC day, spread over its first hour."""
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return midnight.replace(tzinfo=UTC) + timedelta(minutes=int(rand() * 59))


def _next_check(now: datetime, rand: Callable[[], float]) -> datetime:
    factor = 1 + JITTER * (2 * rand() - 1)
    return now + timedelta(hours=settings.fare_watch_interval_hours * factor)


def _notify(watch: dict, note: dict, now: datetime) -> dict:
    return notifications_db.add_notification(
        watch["user_id"],
        note["kind"],
        note["title"],
        note["body"],
        note["data"],
        now=now,
    )


async def check_watch(
    watch_id: int,
    *,
    now: datetime,
    api_key: str,
    fetch: Callable[[dict, str], Awaitable[FareCheck]] | None = None,
    rand: Callable[[], float] = random.random,
    manual: bool = False,
) -> CheckOutcome:
    """Check one watch now and persist the result.

    The scheduler only checks active watches; ``manual`` ("Check now") also
    checks paused ones and, when today's budget is spent, reports
    ``budget_exhausted`` instead of moving the schedule. Always releases the
    watch's lease.
    """
    global _budget_logged_day
    fetch = fetch or fetch_fares
    watch = fare_watch_db.get_watch(watch_id)
    if watch is None:
        return CheckOutcome("skipped", None)
    stamp = now.isoformat()
    allowed = ("active", "paused") if manual else ("active",)
    if watch["status"] not in allowed:
        fare_watch_db.update_watch(watch_id, lease_until=None)
        return CheckOutcome("skipped", watch)

    if date.fromisoformat(watch["departure_date"]) <= now.date():
        note = _notify(watch, _expired_note(watch), now)
        watch = fare_watch_db.update_watch(
            watch_id, status="expired", lease_until=None, updated_at=stamp
        )
        return CheckOutcome("expired", watch, note)

    day = now.date().isoformat()
    cost = _estimate_calls(watch)
    if cost and not fare_watch_db.reserve_calls(
        day, cost, settings.fare_watch_daily_call_budget
    ):
        if manual:
            fare_watch_db.update_watch(watch_id, lease_until=None)
            return CheckOutcome("budget_exhausted", watch)
        if _budget_logged_day != day:
            _budget_logged_day = day
            logger.warning(
                "Fare watch daily SerpAPI budget (%d calls) spent for %s; "
                "postponing remaining checks to tomorrow",
                settings.fare_watch_daily_call_budget,
                day,
            )
        watch = fare_watch_db.update_watch(
            watch_id,
            next_check_at=_next_day(now, rand).isoformat(),
            lease_until=None,
            updated_at=stamp,
        )
        return CheckOutcome("postponed", watch)

    try:
        check = await fetch(watch, api_key)
    except SerpAPIError as exc:
        if exc.quota_exceeded:  # the account, not this watch: no strike
            logger.warning("SerpAPI quota exceeded during fare watch %d", watch_id)
            watch = fare_watch_db.update_watch(
                watch_id,
                next_check_at=_next_day(now, rand).isoformat(),
                lease_until=None,
                updated_at=stamp,
            )
            return CheckOutcome("postponed", watch)
        return _record_failure(watch, str(exc), now)
    except Exception as exc:  # a malformed response is a failed check too
        logger.exception("Fare watch %d check crashed", watch_id)
        return _record_failure(watch, f"{type(exc).__name__}: {exc}", now)

    return _record_success(watch, check, now, rand)


def _record_failure(watch: dict, error: str, now: datetime) -> CheckOutcome:
    failures = (watch.get("failure_count") or 0) + 1
    stamp = now.isoformat()
    logger.info("Fare watch %d check failed (%d): %s", watch["id"], failures, error)
    if failures >= FAILURES_BEFORE_ERROR:
        note = _notify(watch, _error_note(watch), now)
        watch = fare_watch_db.update_watch(
            watch["id"],
            status="error",
            failure_count=failures,
            last_error=error[:300],
            lease_until=None,
            updated_at=stamp,
        )
        return CheckOutcome("errored", watch, note)
    watch = fare_watch_db.update_watch(
        watch["id"],
        failure_count=failures,
        last_error=error[:300],
        next_check_at=(now + RETRY_AFTER_FAILURE).isoformat(),
        lease_until=None,
        updated_at=stamp,
    )
    return CheckOutcome("failed", watch)


def _record_success(
    watch: dict, check: FareCheck, now: datetime, rand: Callable[[], float]
) -> CheckOutcome:
    stamp = now.isoformat()
    fare_watch_db.add_history(
        watch["id"],
        {
            "checked_at": stamp,
            "price": check.price,
            "cheapest_price": check.cheapest_price,
            "cheapest_departure_date": check.cheapest_departure_date,
            "cheapest_return_date": check.cheapest_return_date,
            "price_level": check.price_level,
        },
    )
    notes = evaluate(watch, check, now)
    note = _notify(watch, notes[0], now) if notes else None

    fields: dict = {
        "failure_count": 0,
        "last_error": None,
        "last_checked_at": stamp,
        "next_check_at": _next_check(now, rand).isoformat(),
        "lease_until": None,
        "updated_at": stamp,
    }
    if check.price_level:
        fields["google_price_level"] = check.price_level
    if check.typical_low is not None:
        fields["google_typical_low"] = check.typical_low
        fields["google_typical_high"] = check.typical_high
    if check.price is not None:
        fields["last_price"] = check.price
        fields["check_count"] = (watch.get("check_count") or 0) + 1
        if watch.get("baseline_price") is None:
            fields["baseline_price"] = check.price
    seen = [(check.price, watch["departure_date"])]
    if check.cheapest_price is not None:
        seen.append((check.cheapest_price, check.cheapest_departure_date))
    for price, dep in seen:
        if price is None:
            continue
        lowest = fields.get("lowest_price", watch.get("lowest_price"))
        if lowest is None or price < lowest:
            fields["lowest_price"] = price
            fields["lowest_price_date"] = dep
    if note:
        fields["last_notified_price"] = note["data"]["price"]
        fields["last_notified_at"] = stamp
    watch = fare_watch_db.update_watch(watch["id"], **fields)
    return CheckOutcome("checked", watch, note)
