"""Price watch: watch a hotel's, an activity's or a whole trip's price and
get told when it drops — the generic pipeline behind every kind.

Each kind plugs in a **price source** (``PriceSource``) registered with
``register_source``; this module owns everything shared: the watch row and
its history, the trigger rules (``price_rules``, the same as fare watches),
the shared SerpAPI budget, failures, unavailable looks, expiry,
notifications, email and the scheduler pass (``run_due``, driven by the
fare-watch loop so one loop serves both).

Honesty rules (see the plan): observed prices only ever come from a
source's live look; estimates are frozen at creation and never alert on
their own — a source that mixes them (trips) reports the total with the
estimate parts held fixed.
"""

import asyncio
import importlib
import logging
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from ..core.config import settings
from ..db import fare_watch_db, notifications_db, price_watch_db
from . import fare_watch, price_rules
from .fare_watch import CheckOutcome

logger = logging.getLogger(__name__)

UNAVAILABLE_BEFORE_ERROR = 3  # consecutive "unavailable" looks before pausing
FAILURES_BEFORE_ERROR = fare_watch.FAILURES_BEFORE_ERROR
RETRY_AFTER_FAILURE = fare_watch.RETRY_AFTER_FAILURE
LEASE = fare_watch.LEASE
CLAIM_BATCH = fare_watch.CLAIM_BATCH
CONCURRENCY = 3


# ── Source interface ──────────────────────────────────────────────────────────


@dataclass
class PriceObservation:
    """One live look at a watched price.

    - ``price``: the total in USD (all nights / rooms, all travellers, or the
      whole trip); None when ``status`` is ``"unavailable"``.
    - ``unit_price``: the per-unit price shown next to it (per night, per
      person "from"), when the source has one.
    - ``status``: ``"ok"`` or ``"unavailable"`` (sold out / listing gone for
      the watch's dates: no alert, not a failure — three in a row pause the
      watch).
    - ``source``: where the price came from, e.g. ``google_hotels``,
      ``getyourguide_via_google``; ``link``: where to see / book it.
    - ``breakdown``: trip watches only — one dict per component, e.g.
      ``{"label": "Flights", "group": "flights", "price": 612.0,
      "live": True, "source": "google_flights"}``.
    - ``observed``: raw details kept in history and shown by the UI
      (rating, listing title, nightly rate …), JSON-serialisable.
    - ``calls``: SerpAPI calls this look actually spent (0 when cached).
    """

    price: float | None
    unit_price: float | None = None
    status: Literal["ok", "unavailable"] = "ok"
    source: str = ""
    link: str | None = None
    breakdown: list[dict] | None = None
    observed: dict = field(default_factory=dict)
    calls: int = 0


@dataclass
class CreatedWatch:
    """A source's answer to ``create`` when it found a live price.

    ``subject`` is the kind-specific JSON stored on the watch and handed back
    to ``check`` (e.g. hotel ``{name, city, property_token, check_in,
    check_out, adults, rooms}``); ``baseline`` the first live look;
    ``title`` / ``subtitle`` the card and notification wording ("Lumen
    Hotel" / "Lisbon · 10–14 Dec"); ``expires_on`` the ISO date checking
    stops (check-in, activity date, trip departure); ``plan_id`` the saved
    plan it came from, if any; ``currency`` the currency of every price the
    watch records (activities keep the listing's own currency).
    """

    subject: dict
    baseline: PriceObservation
    title: str
    subtitle: str | None
    expires_on: str
    plan_id: int | None = None
    currency: str = "USD"  # prices are compared in this currency only


@dataclass
class NoLivePrice:
    """A source's answer to ``create`` when nothing live matched: the API
    answers 422 ``{code: "no_live_price", message, suggestions, estimate}``
    and the UI offers to watch a suggestion instead. ``suggestions`` are up to
    3 live alternatives, each ``{"title", "subtitle"?, "price"?, "link"?,
    "spec"}`` — ``spec`` is sent back as-is to watch that one instead;
    ``estimate`` the AI estimate to show, labelled as such (e.g.
    ``{"price": 420.0, "source": "ai_estimate"}``); ``calls`` the SerpAPI
    calls the search spent."""

    message: str
    suggestions: list[dict] = field(default_factory=list)
    estimate: dict | None = None
    calls: int = 0


class InvalidSpec(ValueError):
    """Raised by a source for a spec it can't use; the API answers
    ``status_code`` (422; a subclass may say 404) with ``str(exc)`` as the
    (user-facing) detail."""

    status_code: int = 422


@runtime_checkable
class PriceSource(Protocol):
    """What a kind of price watch plugs in (one instance per kind).

    - ``kind``: ``"hotel"`` | ``"activity"`` | ``"trip"`` (``"test"`` in
      tests); notification kinds are ``f"{kind}_drop"`` / ``f"{kind}_target"``.
    - ``match_key(spec)``: a stable key for "is this already watched?",
      computed from the client's spec alone (no live calls); raises
      ``InvalidSpec`` for a spec it can't use.
    - ``create(spec, user, api_key)``: match the spec to a live subject and
      take the baseline look → ``CreatedWatch``, or ``NoLivePrice``. May
      raise ``InvalidSpec``.
    - ``check(watch, api_key)``: one live look at ``watch["subject"]`` →
      ``PriceObservation``. Raise on failure (an exception with a truthy
      ``quota_exceeded`` attribute postpones to tomorrow without a strike).
      Set ``obs.calls`` to the calls really spent: the reservation is settled
      to it. ``status`` other than ``"ok"`` / ``"unavailable"`` is a failure.
    - Exceptions from ``create`` may carry ``calls`` (int, the SerpAPI calls
      spent before failing) so the shared budget is settled correctly.
    - ``estimate_calls(watch)``: SerpAPI calls ``check`` may spend, reserved
      all-or-nothing from the shared daily budget before it runs.
    - ``compose(kind, watch, obs, ref)``: the alert for notification kind
      ``kind`` at ``obs.price`` against reference price ``ref`` →
      ``{"kind", "title", "body", "data"}``. ``data`` may add kind-specific
      fields; the pipeline adds ``watch_id``, ``watch_kind``, ``price``,
      ``previous_price``, ``delta``, ``baseline_price``, ``target_price``,
      ``is_lowest`` and ``links`` unless the source set them.

    Optional: ``step`` (a ``price_rules.Step``; default ``FARE_STEP``,
    max($15, 5 %)) — trips use ``TRIP_STEP``, max($25, 4 %).
    """

    kind: str

    def match_key(self, spec: dict) -> str: ...

    async def create(
        self, spec: dict, user: dict, api_key: str
    ) -> CreatedWatch | NoLivePrice: ...

    async def check(self, watch: dict, api_key: str) -> PriceObservation: ...

    def estimate_calls(self, watch: dict) -> int: ...

    def compose(
        self, kind: str, watch: dict, obs: PriceObservation, ref: float
    ) -> dict: ...


_SOURCES: dict[str, PriceSource] = {}


def register_source(source: PriceSource) -> None:
    """Make ``source`` handle watches of ``source.kind`` (replaces any)."""
    if not isinstance(source, PriceSource) or not getattr(source, "kind", None):
        raise TypeError(
            "a price source needs kind, match_key, create, check, "
            "estimate_calls and compose"
        )
    _SOURCES[source.kind] = source


def unregister_source(kind: str) -> None:
    _SOURCES.pop(kind, None)


def get_source(kind: str) -> PriceSource | None:
    return _SOURCES.get(kind)


def registered_kinds() -> list[str]:
    return sorted(_SOURCES)


# Modules that provide the built-in sources, each exposing ``SOURCE`` (a
# PriceSource instance). One line per kind, e.g. "app.services.hotel_source".
SOURCE_MODULES: tuple[str, ...] = (
    "app.services.price_sources.activity",
    "app.services.price_sources.hotel",
    "app.services.price_sources.trip",
)  # fmt: skip (one line per kind)


def register_builtin_sources() -> list[str]:
    """Import every module in SOURCE_MODULES and register its ``SOURCE``
    (called once at startup). A module that fails to load is logged and
    skipped: its watches wait, without strikes, until it loads again."""
    kinds = []
    for name in SOURCE_MODULES:
        try:
            source = importlib.import_module(name).SOURCE
            register_source(source)
        except Exception:
            logger.exception("Price source module %s failed to load", name)
            continue
        kinds.append(source.kind)
    return kinds


def step_for(source: PriceSource) -> price_rules.Step:
    return getattr(source, "step", None) or price_rules.DEFAULT_STEP


# ── Shared helpers ────────────────────────────────────────────────────────────


def active_watch_count(user_id: str) -> int:
    """Active fare + price watches: FARE_WATCH_MAX_ACTIVE_PER_USER caps both."""
    return fare_watch_db.count_active(user_id) + price_watch_db.count_active(user_id)


def limit_reached(user_id: str) -> bool:
    return active_watch_count(user_id) >= settings.fare_watch_max_active_per_user


_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "INR": "₹",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
    "BRL": "R$",
    "MXN": "MX$",
}
_NO_CENTS = frozenset({"JPY"})


def format_price(amount: float, currency: str | None = "USD") -> str:
    """A watched price in its own currency: cents under 100 when there are
    any ("$9.90", "€33.46", but "$46"), whole amounts from 100 ("$1,240" —
    as ``usd``); unknown currencies read "12.50 XYZ"."""
    code = (currency or "USD").upper()
    if amount < 100 and code not in _NO_CENTS and round(amount, 2) != round(amount):
        number = f"{amount:,.2f}"
    else:
        number = f"{round(amount):,}"
    symbol = _SYMBOLS.get(code)
    return f"{symbol}{number}" if symbol else f"{number} {currency}"


def limit_message() -> str:
    """The 409 wording when the shared active-watch limit is reached."""
    n = settings.fare_watch_max_active_per_user
    return (
        f"You already have {n} active watches — pause or remove one to watch another."
    )


def calls_spent(exc: BaseException, default: int) -> int:
    """SerpAPI calls a failing ``create`` reports having spent (``exc.calls``),
    else ``default``."""
    calls = getattr(exc, "calls", None)
    return calls if isinstance(calls, int) and calls >= 0 else default


def alerts_link(watch: dict) -> str:
    return f"/alerts?kind={watch['kind']}&watch={watch['id']}"


def _observation_json(obs: PriceObservation, stamp: str) -> dict:
    out = asdict(obs)
    out.pop("calls", None)
    out["observed_at"] = stamp
    return out


def friendly_problem(raw: str | None) -> str | None:
    """What to tell the traveller about a failed check (raw text stays
    server-side: it can name keys, hosts or internals)."""
    if not raw:
        return None
    text = raw.lower()
    if raw == _UNAVAILABLE:
        return "Not available for your dates in the last few checks."
    if "timeout" in text:
        return "Live prices took too long to answer."
    if "http" in text:
        return "Live prices aren't available right now."
    return "Live prices sent something we couldn't read."


_UNAVAILABLE = "unavailable"


def record_created(
    user_id: str,
    kind: str,
    created: CreatedWatch,
    *,
    match_key: str | None,
    alert_mode: str,
    target_price: float | None,
    email_enabled: bool,
    now: datetime,
    rand: Callable[[], float] = random.random,
) -> dict:
    """Store a new watch with its baseline look (the first check: never an
    alert) and schedule the next one."""
    obs = created.baseline
    stamp = now.isoformat()
    watch = price_watch_db.create_watch(
        user_id,
        {
            "kind": kind,
            "plan_id": created.plan_id,
            "title": created.title,
            "subtitle": created.subtitle,
            "subject": created.subject,
            "match_key": match_key,
            "currency": created.currency,
            "alert_mode": alert_mode,
            "target_price": target_price,
            "email_enabled": email_enabled,
            "expires_on": created.expires_on,
            "baseline_price": obs.price,
            "last_price": obs.price,
            "lowest_price": obs.price,
            "check_count": 1,
            "last_checked_at": stamp,
            "next_check_at": fare_watch.next_check(now, rand).isoformat(),
            "last_observation": _observation_json(obs, stamp),
            "reference_looks": (
                {"baseline": obs.breakdown} if obs.breakdown is not None else None
            ),
        },
        now=now,
    )
    price_watch_db.add_history(
        watch["id"],
        {
            "checked_at": stamp,
            "price": obs.price,
            "breakdown": obs.breakdown,
            "observed": {**obs.observed, "status": obs.status},
        },
    )
    return watch


# ── Rules and wording ─────────────────────────────────────────────────────────


def _latest_alert(watch: dict) -> tuple[datetime, float] | None:
    at, price = watch.get("last_notified_at"), watch.get("last_notified_price")
    if not at or price is None:
        return None
    return fare_watch.parse_ts(at), price


def evaluate(
    watch: dict, obs: PriceObservation, now: datetime, source: PriceSource
) -> dict | None:
    """The notification (at most one) this look deserves: ``<kind>_target``
    before ``<kind>_drop``, by the shared ``price_rules``."""
    p = obs.price
    if obs.status != "ok" or p is None:
        return None
    if watch.get("baseline_price") is None or not watch.get("check_count"):
        return None
    signal = price_rules.own_signal(
        p,
        mode=watch["alert_mode"],
        target=watch.get("target_price"),
        baseline=watch["baseline_price"],
        last=watch.get("last_notified_price"),
        peak=watch.get("own_peak_price"),
        step=step_for(source),
    )
    latest = _latest_alert(watch)
    for name, hit in (("target", signal.target), ("drop", signal.drop)):
        if hit and not price_rules.cooldown_blocks(p, latest, now):
            return _compose(source, f"{watch['kind']}_{name}", watch, obs, signal)
    return None


def _compose(
    source: PriceSource,
    kind: str,
    watch: dict,
    obs: PriceObservation,
    signal: price_rules.OwnSignal,
) -> dict:
    ref = signal.reference
    note = source.compose(kind, watch, obs, ref)
    lowest = watch.get("lowest_price")
    links = {"alerts": alerts_link(watch)}
    if obs.link:
        links["book"] = obs.link
    data = {
        "price": obs.price,
        "previous_price": ref,
        "delta": round(obs.price - ref, 2),
        "baseline_price": watch["baseline_price"],
        "target_price": watch.get("target_price"),
        "is_lowest": lowest is None or obs.price < lowest,
        "title": watch["title"],
        "subtitle": watch.get("subtitle"),
        "links": links,
    }
    data.update(note.get("data") or {})
    data.update(watch_id=watch["id"], watch_kind=watch["kind"])
    return {
        "kind": kind,
        "title": note["title"],
        "body": note.get("body", ""),
        "data": data,
    }


def _expired_note(watch: dict) -> dict:
    d = date.fromisoformat(watch["expires_on"])
    body = f"{d.day} {d:%b} has arrived, so we've stopped checking."
    if watch.get("lowest_price") is not None:
        lowest = format_price(watch["lowest_price"], watch.get("currency"))
        body += f" The lowest price we saw was {lowest}."
    return {
        "kind": "watch_expired",
        "title": f"Your {watch['title']} price watch has ended",
        "body": body,
        "data": {
            "watch_id": watch["id"],
            "watch_kind": watch["kind"],
            "title": watch["title"],
            "links": {"alerts": alerts_link(watch)},
        },
    }


def _error_note(watch: dict, reason: str) -> dict:
    if reason == _UNAVAILABLE:
        body = (
            f"It hasn't been available for your dates in {UNAVAILABLE_BEFORE_ERROR}"
            " checks in a row, so we've paused this watch. Retry whenever you like."
        )
    else:
        body = (
            "Live prices failed three times in a row, so we've paused this "
            "watch. Retry whenever you like."
        )
    return {
        "kind": "watch_error",
        "title": f"We couldn't check {watch['title']}",
        "body": body,
        "data": {
            "watch_id": watch["id"],
            "watch_kind": watch["kind"],
            "title": watch["title"],
            "reason": reason,
            "action": "retry",
            "links": {"alerts": alerts_link(watch)},
        },
    }


def _notify(watch: dict, note: dict, now: datetime) -> dict:
    return notifications_db.add_notification(
        watch["user_id"],
        note["kind"],
        note["title"],
        note["body"],
        note["data"],
        now=now,
    )


# ── One check ─────────────────────────────────────────────────────────────────

_budget_logged_day: str | None = None


async def check_watch(
    watch_id: int,
    *,
    now: datetime,
    api_key: str,
    rand: Callable[[], float] = random.random,
    manual: bool = False,
) -> CheckOutcome:
    """Check one price watch now and persist the result.

    Same contract as ``fare_watch.check_watch`` (the caller holds the lease;
    ``manual`` is "Check now"; always releases the lease), plus the
    ``unavailable`` outcome. A watch whose kind has no registered source is
    skipped to its next regular check, with no strike.
    """
    global _budget_logged_day
    watch = price_watch_db.get_watch(watch_id)
    if watch is None:
        return CheckOutcome("skipped", None)
    stamp = now.isoformat()
    allowed = ("active", "paused") if manual else ("active",)
    if watch["status"] not in allowed:
        price_watch_db.update_watch(watch_id, lease_until=None)
        return CheckOutcome("skipped", watch)

    if date.fromisoformat(watch["expires_on"]) <= now.date():
        note = _notify(watch, _expired_note(watch), now)
        watch = price_watch_db.update_watch(
            watch_id, status="expired", lease_until=None, updated_at=stamp
        )
        return CheckOutcome("expired", watch, note)

    source = get_source(watch["kind"])
    if source is None:
        logger.warning("Price watch %d: no source for kind %r", watch_id, watch["kind"])
        watch = price_watch_db.update_watch(
            watch_id,
            next_check_at=fare_watch.next_check(now, rand).isoformat(),
            lease_until=None,
            updated_at=stamp,
        )
        return CheckOutcome("skipped", watch)

    day = now.date().isoformat()
    try:
        cost = int(source.estimate_calls(watch) or 0)
    except Exception as exc:
        logger.warning("Price watch %d: estimate_calls raised", watch_id, exc_info=True)
        return _record_failure(watch, f"{type(exc).__name__}: {exc}", now)
    budget = settings.fare_watch_daily_call_budget
    if cost and not fare_watch_db.reserve_calls(
        day,
        cost,
        budget,
        user_id=watch["user_id"],
        user_cap=fare_watch.user_daily_cap(),
    ):
        pool_left = budget - fare_watch_db.calls_used(day) >= cost
        reason = "user" if pool_left else "global"
        if manual:
            price_watch_db.update_watch(watch_id, lease_until=None)
            return CheckOutcome("budget_exhausted", watch, reason=reason)
        if reason == "global" and _budget_logged_day != day:
            _budget_logged_day = day
            logger.warning(
                "Watch SerpAPI budget (%d calls) spent for %s; postponing "
                "price watch checks to tomorrow",
                budget,
                day,
            )
        watch = price_watch_db.update_watch(
            watch_id,
            next_check_at=fare_watch.next_day(now, rand).isoformat(),
            lease_until=None,
            updated_at=stamp,
        )
        return CheckOutcome("postponed", watch)

    try:
        obs = await source.check(watch, api_key)
    except Exception as exc:
        if getattr(exc, "quota_exceeded", False):  # the account: no strike
            logger.warning("SerpAPI quota exceeded during price watch %d", watch_id)
            watch = price_watch_db.update_watch(
                watch_id,
                next_check_at=fare_watch.next_day(now, rand).isoformat(),
                lease_until=None,
                updated_at=stamp,
            )
            return CheckOutcome("postponed", watch)
        logger.info("Price watch %d check raised", watch_id, exc_info=True)
        return _record_failure(watch, f"{type(exc).__name__}: {exc}", now)

    spent = getattr(obs, "calls", cost) or 0
    if spent != cost:  # settle the reservation to what the look really spent
        fare_watch_db.adjust_calls(day, spent - cost, user_id=watch["user_id"])
    if obs.status == "ok" and obs.price is None:
        return _record_failure(watch, "ValueError: no price in an ok look", now)
    if obs.status == "unavailable":
        return _record_unavailable(watch, obs, now, rand)
    if obs.status != "ok":
        return _record_failure(watch, f"ValueError: unknown status {obs.status!r}", now)

    try:
        outcome = _record_success(watch, obs, now, rand, source)
    except Exception as exc:  # e.g. the source's compose: a strike, not a loop
        logger.warning(
            "Price watch %d: recording the look failed", watch_id, exc_info=True
        )
        return _record_failure(watch, f"{type(exc).__name__}: {exc}", now)
    if outcome.notification:
        from .alert_email import deliver_price

        await deliver_price(outcome.watch, outcome.notification, now)
    return outcome


def _record_failure(watch: dict, error: str, now: datetime) -> CheckOutcome:
    watch = price_watch_db.get_watch(watch["id"])
    if watch is None:
        return CheckOutcome("deleted", None)
    failures = (watch.get("failure_count") or 0) + 1
    stamp = now.isoformat()
    logger.info("Price watch %d check failed (%d): %s", watch["id"], failures, error)
    if failures >= FAILURES_BEFORE_ERROR:
        note = _notify(watch, _error_note(watch, "failed"), now)
        watch = price_watch_db.update_watch(
            watch["id"],
            status="error",
            unavailable_count=0,
            failure_count=failures,
            last_error=error[:300],
            lease_until=None,
            updated_at=stamp,
        )
        return CheckOutcome("errored", watch, note)
    watch = price_watch_db.update_watch(
        watch["id"],
        failure_count=failures,
        unavailable_count=0,  # a failure breaks an "unavailable" streak
        last_error=error[:300],
        next_check_at=(now + RETRY_AFTER_FAILURE).isoformat(),
        lease_until=None,
        updated_at=stamp,
    )
    return CheckOutcome("failed", watch)


def _record_unavailable(
    watch: dict, obs: PriceObservation, now: datetime, rand: Callable[[], float]
) -> CheckOutcome:
    watch = price_watch_db.get_watch(watch["id"])
    if watch is None:
        return CheckOutcome("deleted", None)
    stamp = now.isoformat()
    price_watch_db.add_history(
        watch["id"],
        {
            "checked_at": stamp,
            "price": None,
            "breakdown": obs.breakdown,
            "observed": {**obs.observed, "status": obs.status},
        },
    )
    streak = (watch.get("unavailable_count") or 0) + 1
    fields = {
        "unavailable_count": streak,
        "failure_count": 0,
        "last_observation": _observation_json(obs, stamp),
        "last_checked_at": stamp,
        "lease_until": None,
        "updated_at": stamp,
    }
    if streak >= UNAVAILABLE_BEFORE_ERROR:
        note = _notify(watch, _error_note(watch, _UNAVAILABLE), now)
        fields.update(status="error", last_error=_UNAVAILABLE)
        return CheckOutcome(
            "errored", price_watch_db.update_watch(watch["id"], **fields), note
        )
    fields.update(
        last_error=None, next_check_at=fare_watch.next_check(now, rand).isoformat()
    )
    return CheckOutcome(
        "unavailable", price_watch_db.update_watch(watch["id"], **fields)
    )


def _record_success(
    watch: dict,
    obs: PriceObservation,
    now: datetime,
    rand: Callable[[], float],
    source: PriceSource,
) -> CheckOutcome:
    stamp = now.isoformat()
    # The look took a while: use the current row (settings may have changed),
    # or stop if the traveller deleted the watch meanwhile.
    watch = price_watch_db.get_watch(watch["id"])
    if watch is None:
        return CheckOutcome("deleted", None)
    # Decide (source code may raise) before anything is written
    proposed = evaluate(watch, obs, now, source)
    price_watch_db.add_history(
        watch["id"],
        {
            "checked_at": stamp,
            "price": obs.price,
            "breakdown": obs.breakdown,
            "observed": {**obs.observed, "status": obs.status},
        },
    )
    note = _notify(watch, proposed, now) if proposed else None
    p = obs.price
    fields: dict = {
        "failure_count": 0,
        "unavailable_count": 0,
        "last_error": None,
        "last_price": p,
        "check_count": (watch.get("check_count") or 0) + 1,
        "last_observation": _observation_json(obs, stamp),
        "last_checked_at": stamp,
        "next_check_at": fare_watch.next_check(now, rand).isoformat(),
        "lease_until": None,
        "updated_at": stamp,
    }
    if watch.get("baseline_price") is None:
        fields["baseline_price"] = p
    if watch.get("lowest_price") is None or p < watch["lowest_price"]:
        fields["lowest_price"] = p
    fields.update(
        price_rules.advance_own(
            p,
            alerted=note is not None,
            last=watch.get("last_notified_price"),
            peak=watch.get("own_peak_price"),
            stamp=stamp,
        )
    )
    looks = _reference_looks(watch, obs, fields)
    if looks is not None:
        fields["reference_looks"] = looks
    updated = price_watch_db.update_watch(watch["id"], **fields)
    return CheckOutcome("checked", updated, note)


def _reference_looks(watch: dict, obs: PriceObservation, fields: dict) -> dict | None:
    """The breakdowns alerts are measured from (``reference_looks``, sources
    with a ``breakdown`` only): ``baseline`` (at create), ``last_alert`` (the
    look of the latest alert) and ``peak`` (the look of the highest price
    since it, the reference once re-armed). None when nothing changed."""
    if obs.breakdown is None:
        return None
    looks = dict(watch.get("reference_looks") or {})
    if fields.get("last_notified_at"):  # alerted: the reference and the peak
        looks.update(last_alert=obs.breakdown, peak=obs.breakdown)
    elif fields.get("own_peak_price") is not None and fields[
        "own_peak_price"
    ] != watch.get("own_peak_price"):
        looks["peak"] = obs.breakdown
    else:
        return None
    return looks


# ── Scheduler pass (driven by fare_watch.run_scheduler) ───────────────────────


async def run_due(
    api_key: str,
    *,
    clock: Callable[[], datetime] = fare_watch.utcnow,
    rand: Callable[[], float] = random.random,
) -> list[CheckOutcome | None]:
    """Check the due price watches, CONCURRENCY at a time, leasing each one
    only when its turn comes (as ``fare_watch.run_due``). A crashing check is
    logged and recorded as a failure strike (retry in an hour, on hold after
    three), so it is never retried every tick; it never stops the others."""
    now = clock()
    price_watch_db.expire_inactive_past(now.date().isoformat(), now=now)
    ids = price_watch_db.due_watch_ids(now, CLAIM_BATCH)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(watch_id: int) -> CheckOutcome | None:
        async with sem:
            started = clock()
            if not price_watch_db.claim_watch(
                watch_id, started, started + LEASE, due_only=True
            ):
                return None
            try:
                return await check_watch(
                    watch_id, now=clock(), api_key=api_key, rand=rand
                )
            except Exception as exc:
                logger.exception("Price watch %d check failed unexpectedly", watch_id)
                try:
                    _record_failure(
                        {"id": watch_id}, f"{type(exc).__name__}: {exc}", clock()
                    )
                except Exception:
                    logger.exception(
                        "Price watch %d: recording the crash failed", watch_id
                    )
                    price_watch_db.update_watch(
                        watch_id,
                        lease_until=None,
                        next_check_at=(clock() + RETRY_AFTER_FAILURE).isoformat(),
                    )
                return None

    return list(await asyncio.gather(*(one(i) for i in ids)))


def seconds_to_next_utc_day(now: datetime) -> int:
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return int((nxt.replace(tzinfo=now.tzinfo or UTC) - now).total_seconds())
