"""Priority and adaptive intervals for the watch scheduler (flag-gated by the
callers: with PRICE_ALERTS_V2_ENABLED off none of this is consulted)."""

from datetime import date, datetime, timedelta

NO_DATE_DAYS = 60  # days-to-go assumed when a watch has no date
_NEAR_TARGET = 0.10  # within 10 % above the target: look twice as often
_FLAT = 0.01  # last looks within 1 %: look a day less often
_FLAT_LOOKS = 5

_DATE_KEYS = ("departure_date", "check_in", "date")


def _parse(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def days_to_go(watch: dict, today: date) -> int:
    subject = watch.get("subject")
    sources = [watch] + ([subject] if isinstance(subject, dict) else [])
    for src in sources:
        for key in _DATE_KEYS:
            d = _parse(src.get(key)) if src.get(key) else None
            if d is not None:
                return (d - today).days
    return NO_DATE_DAYS


def target_gap(watch: dict) -> float:
    """(latest - target) / target, or 1.0 without a target or a latest price."""
    target, latest = watch.get("target_price"), watch.get("last_price")
    if not target or latest is None or target <= 0:
        return 1.0
    return (latest - target) / target


def _is_pending(watch: dict) -> bool:
    return bool(watch.get("pending_first_check"))


def priority(watch_kind: str, watch: dict, today: date) -> tuple:
    """Smaller runs first: pending first looks, then the nearest date, then
    the watch closest to its target."""
    return (
        0 if _is_pending(watch) else 1,
        days_to_go(watch, today),
        target_gap(watch),
    )


def _base_days(days: int) -> int:
    if days <= 14:
        return 1
    if days <= 45:
        return 2
    if days <= 120:
        return 4
    return 7


def _is_flat(prices: list[float]) -> bool:
    last = [p for p in prices if p][-_FLAT_LOOKS:]
    if len(last) < _FLAT_LOOKS:
        return False
    return (max(last) - min(last)) / min(last) <= _FLAT


def next_interval(
    watch_kind: str,
    watch: dict,
    today: date,
    history: list[float] | None = None,
) -> timedelta:
    """Re-check interval before jitter. ``history`` is the recent prices,
    oldest first (None prices ignored)."""
    days = float(_base_days(days_to_go(watch, today)))
    gap = target_gap(watch)
    if watch.get("target_price") and 0 <= gap <= _NEAR_TARGET:
        days = max(1.0, days / 2)
    if history and _is_flat([p for p in history if p is not None]):
        days += 1
    return timedelta(days=days)


STARVED_AFTER = timedelta(days=7)
STARVED_INTERVALS = 3


def _starved(kind: str, watch: dict, now) -> bool:
    """Overdue by more than 7 days, or by more than 3x its own interval."""
    try:
        overdue = now - datetime.fromisoformat(watch["next_check_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return overdue > STARVED_AFTER or overdue > STARVED_INTERVALS * next_interval(
        kind, watch, now.date()
    )


def order_due_ids(db, kind_of, now, batch: int) -> list[int]:
    """Due watch ids for one scheduler pass (flag on), by ``priority``.
    ``db.due_watch_ids`` yields a pool of 4x ``batch`` oldest-due first. When
    the longest-waiting watch is starved (see ``_starved``) and the pass has
    at least 2 picks, it keeps the first slot so nothing waits forever;
    otherwise the order is pure priority."""
    pool = db.due_watch_ids(now, batch, candidates=4)
    watches = {i: db.get_watch(i) for i in pool}
    ranked = sorted(
        (priority(kind_of(w), w, now.date()), i)
        for i, w in watches.items()
        if w is not None
    )
    ids = [i for _, i in ranked]
    if batch >= 2 and pool and watches.get(pool[0]) is not None:
        first = pool[0]
        if _starved(kind_of(watches[first]), watches[first], now):
            ids = [first] + [i for i in ids if i != first]
    return ids[:batch]
