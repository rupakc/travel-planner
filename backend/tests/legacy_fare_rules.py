"""Frozen copy of the fare-watch trigger rules as they were before the
``price_rules`` extraction (commit baca0cd, ``app/services/fare_watch.py``).

Used only by ``test_price_rules_equivalence.py`` as the reference ("old
path"). Verbatim except that ``evaluate`` returns ``(kind, price, ref)``
tuples instead of composed notifications. Never edit to match new code.
"""

from datetime import UTC, datetime, timedelta

from app.services.fare_watch import FareCheck

DROP_MIN_USD = 15.0
DROP_MIN_PCT = 0.05
CHEAPER_DATE_MIN_USD = 25.0
CHEAPER_DATE_MIN_PCT = 0.08
COOLDOWN = timedelta(hours=24)
COOLDOWN_FURTHER_DROP_PCT = 0.05
_PRIORITY = ("fare_target", "fare_drop", "fare_low_level", "fare_cheaper_date")


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def step(price: float) -> float:
    """The smallest move worth an alert: max($15, 5 %)."""
    return max(DROP_MIN_USD, DROP_MIN_PCT * price)


def _rearmed(last: float, peak: float | None) -> bool:
    return peak is not None and peak >= last + step(last)


def _own_candidates(watch: dict, check: FareCheck) -> list[tuple[str, float, float]]:
    """Own-dates rules that fire, as (kind, price, reference price)."""
    p = check.price
    if p is None:
        return []
    mode, target = watch["alert_mode"], watch.get("target_price")
    baseline = watch["baseline_price"]
    last = watch.get("last_notified_price")
    peak = watch.get("own_peak_price")
    lowest = watch.get("own_lowest_price")
    # Already good when watching started (under the target / Google "low"):
    # that signal's first alert needs a full step below the baseline.
    full_step = p <= baseline - step(baseline)
    if last is None:
        drop_ref = baseline
        repeat_ok = p < baseline  # never for a rise above where we started
        if watch.get("baseline_price_level") == "low":
            repeat_ok = full_step
    else:
        drop_ref = peak if _rearmed(last, peak) else last
        repeat_ok = p <= last - step(last) or _rearmed(last, peak)
    out = []
    if mode == "below_target" and target is not None and p <= target:
        target_rearmed = (
            last is not None and peak is not None and peak >= target + step(target)
        )
        if last is None:
            ok = full_step if baseline <= target else p < baseline
        else:
            ok = p <= last - step(last) or target_rearmed
        if ok:
            out.append(("fare_target", p, drop_ref))
    if mode == "any_drop":
        if p <= drop_ref - step(drop_ref):
            out.append(("fare_drop", p, drop_ref))
        new_low = lowest is None or p < lowest
        if check.price_level == "low" and new_low and repeat_ok:
            out.append(("fare_low_level", p, drop_ref))
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
        (_parse_ts(watch[at]), watch[price])
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
    cooling = latest is not None and now - latest[0] < COOLDOWN
    by_kind = {kind: (price, ref) for kind, price, ref in found}
    for kind in _PRIORITY:
        if kind not in by_kind:
            continue
        price, ref = by_kind[kind]
        if cooling and price > latest[1] * (1 - COOLDOWN_FURTHER_DROP_PCT):
            continue
        return [(kind, price, ref)]
    return []
