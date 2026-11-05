"""When a watched price is worth an alert: the kind-agnostic own-price rules
shared by fare watches (``fare_watch``) and price watches (``price_watch``).

Pure functions, no I/O. One signal per watch — the watched price itself —
with this state on the watch row: ``baseline_price`` (first look),
``last_notified_price`` (A, the last alerted price), ``own_peak_price`` (P,
the highest price since that alert) and ``last_notified_at``.

- The first alert is measured from the baseline; never on a rise, never on
  the baseline check itself (callers skip ``check_count == 0``).
- A repeat needs a further ``step(A)`` below A — unless the signal re-armed:
  any_drop re-arms once the price rebounds to A + step(A) (the reference
  becomes the peak); target re-arms once the price is back above the target
  by step(target).
- Baseline already good (at or under the target, or Google already calling
  the fare "low"): that signal's first alert needs a full step below the
  baseline.
- A 24 h cooldown caps alerts per watch: inside it, only a price ≥ 5 %
  below the most recent alert gets through (``cooldown_blocks``).

``step`` is max($15, 5 %) for fares, hotels and activities (``FARE_STEP``)
and max($25, 4 %) for whole-trip totals (``TRIP_STEP``).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

COOLDOWN = timedelta(hours=24)  # one alert per watch per day …
COOLDOWN_FURTHER_DROP_PCT = 0.05  # … unless 5 % below the last alert

MODES = ("any_drop", "below_target")


@dataclass(frozen=True)
class Step:
    """The smallest move worth an alert: max(``min_usd``, ``min_pct`` × price)."""

    min_usd: float
    min_pct: float

    def __call__(self, price: float) -> float:
        return max(self.min_usd, self.min_pct * price)


FARE_STEP = Step(15.0, 0.05)
TRIP_STEP = Step(25.0, 0.04)
DEFAULT_STEP = FARE_STEP


def rearmed(last: float, peak: float | None, step: Step = DEFAULT_STEP) -> bool:
    """True once the price rebounded a full step above the last alert."""
    return peak is not None and peak >= last + step(last)


@dataclass(frozen=True)
class OwnSignal:
    """What the own-price rules say about one observed price.

    ``reference`` — the price a drop is measured from (baseline, last alert,
    or the peak once re-armed); ``target`` / ``drop`` — whether the
    below-target / any-drop rule fires; ``repeat_ok`` — whether a further
    alert would be news at all (used by fare watches' Google-"low" rule).
    """

    reference: float
    repeat_ok: bool
    target: bool
    drop: bool


def own_signal(
    price: float,
    *,
    mode: str,
    target: float | None,
    baseline: float,
    last: float | None,
    peak: float | None,
    baseline_already_low: bool = False,
    step: Step = DEFAULT_STEP,
) -> OwnSignal:
    """Apply the shared rules to ``price`` (see the module docstring). An
    unknown ``mode`` never fires (as the fare rules always behaved)."""
    if mode not in MODES:
        return OwnSignal(baseline, False, False, False)
    full_step = price <= baseline - step(baseline)
    if last is None:
        reference = baseline
        repeat_ok = full_step if baseline_already_low else price < baseline
    else:
        is_rearmed = rearmed(last, peak, step)
        reference = peak if is_rearmed else last
        repeat_ok = price <= last - step(last) or is_rearmed

    target_hit = False
    if mode == "below_target" and target is not None and price <= target:
        if last is None:
            target_hit = full_step if baseline <= target else price < baseline
        else:
            target_rearmed = peak is not None and peak >= target + step(target)
            target_hit = price <= last - step(last) or target_rearmed
    drop_hit = mode == "any_drop" and price <= reference - step(reference)
    return OwnSignal(reference, repeat_ok, target_hit, drop_hit)


def cooldown_blocks(
    price: float, latest: tuple[datetime, float] | None, now: datetime
) -> bool:
    """True when ``price`` must wait: within COOLDOWN of the latest alert
    ``(when, price)`` and not ≥ 5 % below it."""
    if latest is None or now - latest[0] >= COOLDOWN:
        return False
    return price > latest[1] * (1 - COOLDOWN_FURTHER_DROP_PCT)


def advance_own(
    price: float,
    *,
    alerted: bool,
    last: float | None,
    peak: float | None,
    stamp: str,
) -> dict:
    """Signal state a check leaves behind: an alert resets the reference and
    the peak; otherwise the peak since the last alert follows rebounds."""
    if alerted:
        return {
            "last_notified_price": price,
            "last_notified_at": stamp,
            "own_peak_price": price,
        }
    if last is not None:
        return {"own_peak_price": max(peak or price, price)}
    return {}
