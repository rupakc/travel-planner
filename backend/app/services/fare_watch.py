"""Fare watch: re-check watched fares and decide when to tell the traveller.

``evaluate`` holds the trigger and anti-spam rules (pure). ``check_watch``
runs one check of one watch: expiry, the daily SerpAPI budget, the live
fare, history, failures and the resulting notification. The scheduler
loop that calls it lives further down (see ``run_scheduler``).
"""

import asyncio
import logging
import math
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from ..core.cache import fresh_reads
from ..core.config import settings
from ..db import fare_watch_db, notifications_db
from ..db.database import airport_city
from ..schemas.request import TravelSearchRequest
from . import alert_pipeline, price_rules, push, serp_flights
from .serp_flights import SerpAPIError

logger = logging.getLogger(__name__)

# ── Rule constants ────────────────────────────────────────────────────────────

# Own-dates rules are shared with price watches: see ``price_rules``.
DROP_MIN_USD = price_rules.FARE_STEP.min_usd  # any_drop: at least $15 …
DROP_MIN_PCT = price_rules.FARE_STEP.min_pct  # … and at least 5 % below
CHEAPER_DATE_MIN_USD = 25.0  # nearby date: at least $25 …
CHEAPER_DATE_MIN_PCT = 0.08  # … and 8 % cheaper than the selected dates
COOLDOWN = price_rules.COOLDOWN  # one alert per watch per day …
COOLDOWN_FURTHER_DROP_PCT = price_rules.COOLDOWN_FURTHER_DROP_PCT  # … unless 5 % lower

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
    # checked | expired | postponed | failed | errored | skipped | deleted
    # | budget_exhausted
    status: str
    watch: dict | None
    notification: dict | None = None
    reason: str | None = None  # budget_exhausted: "global" or "user"


# ── Wording helpers ───────────────────────────────────────────────────────────


def _city(label: str | None, code: str) -> str:
    name = (label or "").split(",")[0].strip() or code.split(",")[0]
    # a label that is itself an airport code ("LIS") reads as its city
    return airport_city(name)


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


def parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _links(watch: dict, dep: str, ret: str | None, cheapest: bool = False) -> dict:
    alerts = f"/alerts?watch={watch['id']}"
    return {
        "alerts": alerts,
        "replan": alerts + "&replan=1" + ("&cheapest=1" if cheapest else ""),
        "book": serp_flights.google_flights_url(
            watch["origin_code"], watch["destination_code"], dep, ret
        ),
    }


# ── Trigger rules ─────────────────────────────────────────────────────────────
#
# Two signals, each with its own reference (review ruling):
#   own dates  — fare_target / fare_drop / fare_low_level on the trip's dates;
#                state: last_notified_price (A), own_peak_price (P, highest
#                own-dates price since that alert), last_notified_at.
#   nearby     — fare_cheaper_date on the cheapest date ±N days;
#                state: cheaper_notified_price (C), cheaper_peak_price (Q),
#                cheaper_notified_at.
# A signal's first alert is measured from the baseline. A repeat needs a
# further step(A) below its last alert — unless it re-armed: any_drop
# re-arms once the price rebounds to A + step(A) (the reference becomes the
# peak since the alert); target re-arms once the price is back above the
# target by step(target). The 24 h cooldown is a per-watch cap on top.


def step(price: float) -> float:
    """The smallest move worth an alert: max($15, 5 %)."""
    return price_rules.FARE_STEP(price)


def _rearmed(last: float, peak: float | None) -> bool:
    return price_rules.rearmed(last, peak, price_rules.FARE_STEP)


def _own_candidates(watch: dict, check: FareCheck) -> list[tuple[str, float, float]]:
    """Own-dates rules that fire, as (kind, price, reference price)."""
    p = check.price
    if p is None:
        return []
    signal = price_rules.own_signal(
        p,
        mode=watch["alert_mode"],
        target=watch.get("target_price"),
        baseline=watch["baseline_price"],
        last=watch.get("last_notified_price"),
        peak=watch.get("own_peak_price"),
        baseline_already_low=watch.get("baseline_price_level") == "low",
        step=price_rules.FARE_STEP,
    )
    out = []
    if signal.target:
        out.append(("fare_target", p, signal.reference))
    if signal.drop:
        out.append(("fare_drop", p, signal.reference))
    if watch["alert_mode"] == "any_drop":
        lowest = watch.get("own_lowest_price")
        new_low = lowest is None or p < lowest
        if check.price_level == "low" and new_low and signal.repeat_ok:
            out.append(("fare_low_level", p, signal.reference))
    return out


def _nearby_candidate(watch: dict, check: FareCheck) -> tuple[str, float, float] | None:
    p, c = check.price, check.cheapest_price
    mode, target = watch["alert_mode"], watch.get("target_price")
    if not (
        watch.get("flexible_days")
        and p is not None
        and c is not None
        and check.cheapest_departure_date
        and check.cheapest_departure_date != watch["departure_date"]
        and p - c >= max(CHEAPER_DATE_MIN_USD, CHEAPER_DATE_MIN_PCT * p)
    ):
        return None
    baseline = watch["baseline_price"]
    last = watch.get("cheaper_notified_price")
    peak = watch.get("cheaper_peak_price")
    if mode == "below_target":
        if target is None or c > target:
            return None
        if last is None:
            ok = c < baseline
        else:
            ok = c <= last - step(last) or (
                peak is not None and peak >= target + step(target)
            )
        return ("fare_cheaper_date", c, last or baseline) if ok else None
    if last is None:
        return ("fare_cheaper_date", c, baseline) if c < baseline else None
    ref = peak if _rearmed(last, peak) else last
    return ("fare_cheaper_date", c, ref) if c <= ref - step(ref) else None


def _latest_alert(watch: dict) -> tuple[datetime, float] | None:
    """When and at what price the watch last alerted (either signal)."""
    alerts = [
        (parse_ts(watch[at]), watch[price])
        for at, price in (
            ("last_notified_at", "last_notified_price"),
            ("cheaper_notified_at", "cheaper_notified_price"),
        )
        if watch.get(at) and watch.get(price) is not None
    ]
    return max(alerts) if alerts else None


def evaluate(watch: dict, check: FareCheck, now: datetime) -> list[dict]:
    """The notification (at most one) this check deserves.

    Rules, highest priority first: fare_target (price ≤ target), fare_drop
    (≥ step below the reference), fare_low_level (a new own-dates lowest
    Google calls "low"), fare_cheaper_date (a nearby date ≥ max($25, 8 %)
    cheaper than the trip's dates; in target mode it must also beat the
    target). References, repeats and re-arming: see the comment above.
    Never on the first check (the baseline). Within 24 h of the watch's
    last alert, only a price ≥ 5 % below that alert gets through.
    """
    if watch.get("baseline_price") is None or not watch.get("check_count"):
        return []
    found = _own_candidates(watch, check)
    nearby = _nearby_candidate(watch, check)
    if nearby:
        found.append(nearby)
    latest = _latest_alert(watch)
    by_kind = {kind: (price, ref) for kind, price, ref in found}
    for kind in _PRIORITY:
        if kind not in by_kind:
            continue
        price, ref = by_kind[kind]
        if price_rules.cooldown_blocks(price, latest, now):
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
    own_lowest = watch.get("own_lowest_price")
    is_lowest = own_lowest is None or p < own_lowest
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


def utcnow() -> datetime:
    return datetime.now(UTC)


def user_daily_cap() -> int:
    """SerpAPI calls one user's watches may spend per UTC day."""
    share = settings.fare_watch_daily_call_budget * settings.fare_watch_user_daily_share
    return max(1, math.floor(share + 1e-9))  # 10 × 0.3 is 2.999… in floats


def already_good(watch: dict) -> dict:
    """Whether the fare was already good when watching started."""
    base, target = watch.get("baseline_price"), watch.get("target_price")
    return {
        "already_below_target": watch.get("alert_mode") == "below_target"
        and base is not None
        and target is not None
        and base <= target,
        "already_low": base is not None and watch.get("baseline_price_level") == "low",
    }


def friendly_problem(raw: str | None) -> str | None:
    """What to tell the traveller about a failed check (raw text stays
    server-side: it can name keys, hosts or internals)."""
    if not raw:
        return None
    text = raw.lower()
    if "timeout" in text:
        return "Live fares took too long to answer."
    if "http" in text and "serpapi" in text:
        return "Live fares aren't available right now."
    if "request error" in text:
        return "We couldn't reach live fares."
    return "Live fares sent something we couldn't read."


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


def next_day(now: datetime, rand: Callable[[], float]) -> datetime:
    """Early next UTC day, spread over its first hour."""
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return midnight.replace(tzinfo=UTC) + timedelta(minutes=int(rand() * 59))


def next_check(now: datetime, rand: Callable[[], float]) -> datetime:
    factor = 1 + JITTER * (2 * rand() - 1)
    return now + timedelta(hours=settings.fare_watch_interval_hours * factor)


def _notify(watch: dict, note: dict, now: datetime) -> dict:
    v2 = alert_pipeline.enabled()
    if v2:
        try:
            note = alert_pipeline.enrich(watch, "flight", note)
        except Exception:  # v2 must never lose an alert: send it unenriched
            logger.warning("alert pipeline enrich failed", exc_info=True)
    row = notifications_db.add_notification(
        watch["user_id"],
        note["kind"],
        note["title"],
        note["body"],
        note["data"],
        now=now,
    )
    took_over = False
    if v2:
        try:
            took_over = bool(alert_pipeline.after_insert(watch, "flight", row, now))
        except Exception:  # fall through to the legacy push and email
            logger.warning("alert pipeline after_insert failed", exc_info=True)
    if took_over:
        # after_insert persisted `_v2` in the stored row; mirror it on the
        # returned row so the email step skips this notification too
        row["data"]["_v2"] = True
        return row
    # Also to the owner's phones, in the background (a no-op when push is off)
    push.notify(watch["user_id"], row, f"/alerts?watch={watch['id']}")
    return row


async def check_watch(
    watch_id: int,
    *,
    now: datetime,
    api_key: str,
    fetch: Callable[[dict, str], Awaitable[FareCheck]] | None = None,
    rand: Callable[[], float] = random.random,
    manual: bool = False,
    fresh: bool = False,
) -> CheckOutcome:
    """Check one watch now and persist the result (``_check_watch``).

    ``fresh`` ("Check now") ignores fares already in the shared 30-minute
    cache, so the look is live and refreshes the cache; its calls are
    reserved from the daily budget and the owner's share exactly as any
    other look's. Scheduled checks and a new watch's baseline reuse cached
    fares (cached answers are free).
    """
    kwargs = dict(now=now, api_key=api_key, fetch=fetch, rand=rand, manual=manual)
    if fresh:
        with fresh_reads():
            return await _check_watch(watch_id, **kwargs)
    return await _check_watch(watch_id, **kwargs)


async def _check_watch(
    watch_id: int,
    *,
    now: datetime,
    api_key: str,
    fetch: Callable[[dict, str], Awaitable[FareCheck]] | None = None,
    rand: Callable[[], float] = random.random,
    manual: bool = False,
) -> CheckOutcome:
    """Check one watch now and persist the result.

    The caller holds the watch's lease (``claim_watch``, or
    ``create_watch(lease_until=...)``). The scheduler only checks active
    watches; ``manual`` ("Check now") also checks paused ones and, when
    today's budget (or the owner's share of it) is spent, reports
    ``budget_exhausted`` instead of moving the schedule. A watch deleted
    while its fares are fetched ends as ``deleted`` with nothing recorded.
    Always releases the watch's lease.
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
    budget = settings.fare_watch_daily_call_budget
    if cost and not fare_watch_db.reserve_calls(
        day, cost, budget, user_id=watch["user_id"], user_cap=user_daily_cap()
    ):
        pool_left = budget - fare_watch_db.calls_used(day) >= cost
        reason = "user" if pool_left else "global"
        if manual:
            fare_watch_db.update_watch(watch_id, lease_until=None)
            return CheckOutcome("budget_exhausted", watch, reason=reason)
        if reason == "user":
            logger.info(
                "Fare watch %d: owner's daily share spent; checking tomorrow",
                watch_id,
            )
        elif _budget_logged_day != day:
            _budget_logged_day = day
            logger.warning(
                "Fare watch daily SerpAPI budget (%d calls) spent for %s; "
                "postponing remaining checks to tomorrow",
                settings.fare_watch_daily_call_budget,
                day,
            )
        watch = fare_watch_db.update_watch(
            watch_id,
            next_check_at=next_day(now, rand).isoformat(),
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
                next_check_at=next_day(now, rand).isoformat(),
                lease_until=None,
                updated_at=stamp,
            )
            return CheckOutcome("postponed", watch)
        return _record_failure(watch, str(exc), now)
    except Exception as exc:  # a malformed response is a failed check too
        logger.exception("Fare watch %d check crashed", watch_id)
        return _record_failure(watch, f"{type(exc).__name__}: {exc}", now)

    outcome = _record_success(watch, check, now, rand)
    if outcome.notification and not outcome.notification["data"].get("_v2"):
        from .alert_email import deliver

        await deliver(outcome.watch, outcome.notification, now)
    return outcome


def _record_failure(watch: dict, error: str, now: datetime) -> CheckOutcome:
    watch = fare_watch_db.get_watch(watch["id"])
    if watch is None:  # deleted while we were fetching
        return CheckOutcome("deleted", None)
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
    # The fetch took a while: the traveller may have deleted the watch (or
    # changed its settings) meanwhile — use the current row, or stop here.
    watch = fare_watch_db.get_watch(watch["id"])
    if watch is None:
        return CheckOutcome("deleted", None)
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
    kind = note["kind"] if note else None

    fields: dict = {
        "failure_count": 0,
        "last_error": None,
        "last_checked_at": stamp,
        "next_check_at": next_check(now, rand).isoformat(),
        "lease_until": None,
        "updated_at": stamp,
    }
    if check.price_level:
        fields["google_price_level"] = check.price_level
    if check.typical_low is not None:
        fields["google_typical_low"] = check.typical_low
        fields["google_typical_high"] = check.typical_high
    p = check.price
    if p is not None:
        fields["last_price"] = p
        fields["check_count"] = (watch.get("check_count") or 0) + 1
        if watch.get("baseline_price") is None:
            fields["baseline_price"] = p
            fields["baseline_price_level"] = check.price_level
        own_lowest = watch.get("own_lowest_price")
        if own_lowest is None or p < own_lowest:
            fields["own_lowest_price"] = p
        # Own-dates signal: a new alert resets its reference and peak;
        # otherwise the peak since the last alert follows rebounds.
        fields.update(
            price_rules.advance_own(
                p,
                alerted=kind in ("fare_target", "fare_drop", "fare_low_level"),
                last=watch.get("last_notified_price"),
                peak=watch.get("own_peak_price"),
                stamp=stamp,
            )
        )
    c = check.cheapest_price
    if c is not None:
        if kind == "fare_cheaper_date":
            fields.update(
                cheaper_notified_price=c,
                cheaper_notified_at=stamp,
                cheaper_peak_price=c,
            )
        elif watch.get("cheaper_notified_price") is not None:
            fields["cheaper_peak_price"] = max(watch.get("cheaper_peak_price") or c, c)
    seen = [(p, watch["departure_date"]), (c, check.cheapest_departure_date)]
    for price, dep in seen:
        if price is None:
            continue
        lowest = fields.get("lowest_price", watch.get("lowest_price"))
        if lowest is None or price < lowest:
            fields["lowest_price"] = price
            fields["lowest_price_date"] = dep
    updated = fare_watch_db.update_watch(watch["id"], **fields)
    return CheckOutcome("checked", updated, note)


# ── Scheduler ─────────────────────────────────────────────────────────────────

LEASE = timedelta(minutes=10)  # a crashed worker's claim frees up after this
CLAIM_BATCH = 50
NOTIFICATION_RETENTION = timedelta(days=180)
_swept_day: date | None = None
CONCURRENCY = 3


async def run_due(
    api_key: str,
    *,
    clock: Callable[[], datetime] = utcnow,
    fetch: Callable[[dict, str], Awaitable[FareCheck]] | None = None,
    rand: Callable[[], float] = random.random,
) -> list[CheckOutcome | None]:
    """Check the due watches, CONCURRENCY at a time. Each watch is leased
    only when its turn comes (``claim_watch``), so one taken meanwhile by
    "Check now" or another scheduler is skipped, and a long batch never
    outlives its leases. A crashing check is logged, its lease released, and
    never stops the others. Once per UTC day, old notifications are swept."""
    global _swept_day
    now = clock()
    if _swept_day != now.date():
        _swept_day = now.date()
        removed = notifications_db.delete_older_than(now - NOTIFICATION_RETENTION)
        if removed:
            logger.info("Removed %d notifications older than 180 days", removed)
    fare_watch_db.expire_inactive_past(now.date().isoformat(), now=now)
    ids = fare_watch_db.due_watch_ids(now, CLAIM_BATCH)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(watch_id: int) -> CheckOutcome | None:
        async with sem:
            started = clock()
            if not fare_watch_db.claim_watch(
                watch_id, started, started + LEASE, due_only=True
            ):
                return None  # someone else is checking it
            try:
                return await check_watch(
                    watch_id, now=clock(), api_key=api_key, fetch=fetch, rand=rand
                )
            except Exception:
                logger.exception("Fare watch %d check failed unexpectedly", watch_id)
                fare_watch_db.update_watch(watch_id, lease_until=None)
                return None

    return list(await asyncio.gather(*(one(i) for i in ids)))


async def run_scheduler(
    api_key: str,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Every FARE_WATCH_TICK_SECONDS, check the due fare watches, then start
    a pass over the due price watches (``price_watch.run_due``) as its own
    task, so a slow price pass never delays the next fare pass. At most one
    price pass is in flight: a tick that finds one still running starts
    none. Runs until cancelled, then cancels and awaits the price pass in
    flight; one bad pass is logged and the loop goes on."""
    logger.info(
        "Fare watch scheduler started (tick %ss)", settings.fare_watch_tick_seconds
    )
    price_task: asyncio.Task | None = None
    try:
        while True:
            try:
                await run_due(api_key)
            except Exception:
                logger.exception("Fare watch scheduler tick failed")
            if price_task is None or price_task.done():
                price_task = asyncio.create_task(_price_pass(api_key))
            await sleep(settings.fare_watch_tick_seconds)
    finally:
        if price_task is not None and not price_task.done():
            price_task.cancel()
            try:
                await price_task
            except asyncio.CancelledError:
                pass


async def _price_pass(api_key: str) -> None:
    """One price-watch pass; a crash is logged, never raised."""
    from . import price_watch

    try:
        await price_watch.run_due(api_key)
    except Exception:
        logger.exception("Price watch scheduler tick failed")


def start_scheduler() -> asyncio.Task | None:
    """Start the loop when live fares are configured and watching is on."""
    if not (settings.serpapi_key and settings.fare_watch_enabled):
        return None
    return asyncio.create_task(run_scheduler(settings.serpapi_key))


async def stop_scheduler(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
