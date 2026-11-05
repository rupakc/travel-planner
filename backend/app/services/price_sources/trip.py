"""Whole-trip price watch: the price of a saved plan — flights, hotel,
activities and the other priced parts — as one total.

The spec is just ``{plan_id}``: the server loads the traveller's own saved
plan (anyone else's, or a missing one, is the same 404 "Plan not found")
and turns its selections into **components**, mirroring the plan drawer's
cost breakdown (``frontend/src/utils/planHelpers.js``):

- the selected flight → **live** via the fare-watch path. This is Google
  Flights' *cheapest fare* for the plan's route, dates and travellers (as a
  fare watch tracks it), not the specific flight picked, and is labelled so;
  multi-city legs, or a route we can't price → estimate;
- the selected hotel → **live** via ``hotel_prices`` (Google Hotels, matched
  by name, ``ceil(travellers / 2)`` rooms; stored with the hotel watch's
  subject fields) → else estimate;
- selected activities → **live** via ``activity_prices`` (the GetYourGuide /
  Viator "from" price in Google results, **per person × travellers**;
  stored with the activity watch's subject fields) for the first
  ``MAX_LIVE_ACTIVITIES``; category pages, non-USD listings and the rest →
  estimates (the AI price, also per person × travellers);
- the SIM / eSIM plan → estimate ("other").

Every component carries a ``detail`` line saying what its price is ("Google
Flights · Berlin ⇄ Lisbon · 10–14 Dec · 2 travellers", "from $22.87 per
person × 2"). Estimates are the AI prices of the original search, **frozen
at creation** and labelled; they are part of the total but never move, so
they never alert on their own. A plan with no live part can't be watched
(422 ``no_live_price``).

A check re-prices the live parts (≤ ``CHECK_CALL_CAP`` SerpAPI calls; at
most ``MAX_LIVE_ACTIVITIES`` activities, least recently checked first — a
defensive rule, as creation makes at most that many live — the others keep
their last observed price marked ``stale``). A part that is unavailable (or
whose look failed) keeps its last observed price, flagged in the breakdown;
the look is ``unavailable`` only when no live part priced. Alerts use the
trip step (max $25, 4 %) on the total and explain the change by component,
measured against the stored breakdown of the reference look (the core's
``reference_looks``); without one only the total is explained.

SerpAPI calls are counted as made: each adapter lookup counts the cache
entries it newly filled (cached answers are free), or uses the count the
adapter returns.

The watch works on its frozen subject: deleting the plan afterwards doesn't
stop it (it still ends on the departure date).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable
from datetime import UTC, date, datetime

from ...core.cache import get_cache
from ...db import plans_db
from ...db.database import airport_city
from ...schemas.request import TravelSearchRequest
from .. import activity_prices, fare_watch, hotel_prices, price_rules, serp_flights
from ..activity_prices import ActivityListing
from ..fare_watch import date_range
from ..price_watch import (
    CreatedWatch,
    InvalidSpec,
    NoLivePrice,
    PriceObservation,
    format_price,
)

logger = logging.getLogger(__name__)

CREATE_CALL_CAP = 10  # SerpAPI calls a create may spend
CHECK_CALL_CAP = 8  # … and one check
MAX_LIVE_ACTIVITIES = 5  # activities looked up live per create / check
NO_LIVE_MESSAGE = "We can't find a live price for any part of this trip yet"
ESTIMATE = "ai_estimate"
DEFAULT_NIGHTS = 7  # as the plan drawer, when the plan has no return date
LIVE_FLIGHT_LABEL = "Flights — cheapest fare on your dates"
MAX_NAMED_ESTIMATES = 2  # in alert bodies: "SIM / eSIM, Fado night +3 more"

GROUPS = {"flight": "flights", "hotel": "stay", "activity": "activities"}
# How each group reads in "flights −$70, hotel −$42"
MOVE_LABELS = {
    "flights": "flights",
    "stay": "hotel",
    "activities": "activities",
    "other": "other",
}
_ANCHORS = ("flight", "hotel")
_PRIVATE = ("_try",)  # draft-only keys, never stored


class PlanNotFound(InvalidSpec):
    """Another user's plan or a missing one: the same 404, so nothing leaks."""

    status_code = 404

    def __init__(self) -> None:
        super().__init__("Plan not found")


# ── Small helpers ─────────────────────────────────────────────────────────────


def _amount(value) -> float:
    """A positive price, or 0 (AI prices may be strings or "varies")."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n if 0 < n < float("inf") else 0.0


def _plan_id(spec: dict) -> int:
    raw = spec.get("plan_id") if isinstance(spec, dict) else None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        pid = 0
    if isinstance(raw, bool) or pid <= 0:
        raise InvalidSpec("Choose a saved plan to watch.")
    return pid


def _city(destination) -> str:
    """ "Lisbon" for "Lisbon, Portugal" — and for "LIS", the airport code the
    search form stores (local airport data, no network)."""
    return airport_city(str(destination or "").split(",")[0].strip())


def _travellers(sd: dict) -> int:
    n = sd.get("num_travelers")
    if not n:
        n = sum(int(sd.get(k) or 0) for k in ("adults", "children", "seniors"))
    try:
        return max(1, min(int(n or 1), 20))
    except (TypeError, ValueError):
        return 1


def _rooms(n: int) -> int:
    """Rooms for the party: two to a room, as most hotel rates assume."""
    return max(1, math.ceil(n / 2))


def _iso(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat() if value else None
    except ValueError:
        return None


def _nights(dep: str | None, ret: str | None) -> int:
    if dep and ret:
        return max(1, (date.fromisoformat(ret) - date.fromisoformat(dep)).days)
    return DEFAULT_NIGHTS


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _money(amount: float, currency: str = "USD") -> str:
    """Like "$22.87", "$30", "€24", "$1,234": the UI's formatPrice rule."""
    return format_price(amount, currency)


def usd(amount: float) -> str:
    return format_price(amount, "USD")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _draft(cid: str, ctype: str, label: str, price: float, **extra) -> dict:
    return {
        "id": cid,
        "type": ctype,
        "group": GROUPS.get(ctype, "other"),
        "label": label,
        "live": False,
        "price": round(price, 2),
        "currency": "USD",
        "in_total": True,
        "source": ESTIMATE,
        "status": "estimate",
        **extra,
    }


def _public(comp: dict) -> dict:
    return {k: v for k, v in comp.items() if k not in _PRIVATE}


def _per_person_detail(unit: float, n: int, currency: str = "USD", *, live: bool):
    base = f"{_money(unit, currency)} per person × {n}"
    return f"from {base}" if live else f"{base} (estimate)"


def _hotel_detail(s: dict, nightly: float | None) -> str:
    parts = [
        "Google Hotels",
        _plural(_nights(s["check_in"], s["check_out"]), "night"),
        _plural(s.get("rooms") or 1, "room"),
    ]
    if nightly:
        parts.append(f"{_money(nightly)} per night")
    return " · ".join(parts)


def _flight_detail(fare: dict) -> str:
    arrow = "⇄" if fare.get("return_date") else "→"
    route = (
        f"{_city(fare['origin_label']) or fare['origin_code']} {arrow} "
        f"{_city(fare['destination_label']) or fare['destination_code']}"
    )
    when = date_range(fare["departure_date"], fare.get("return_date"))
    return (
        f"Google Flights · {route} · {when} · "
        f"{_plural(fare['num_travelers'], 'traveller')}"
    )


# ── SerpAPI call accounting (cached answers are free) ─────────────────────────


def _cached(key: str) -> bool:
    return key in get_cache()


async def _counted(keys: list[str], coro: Awaitable):
    """Await an adapter lookup; returns ``(result, calls, exc)``.

    Calls = the cache entries among ``keys`` that were missing before and
    are filled after (the adapters cache every answer they fetch), plus one
    for a failed call (failures are never cached)."""
    missing = [k for k in keys if not _cached(k)]
    try:
        result, exc = await coro, None
    except Exception as e:  # reported to the caller, which decides
        result, exc = None, e
    calls = sum(1 for k in missing if _cached(k))
    if exc is not None and any(not _cached(k) for k in missing):
        calls += 1
    return result, calls, exc


def _flight_cost(fw: dict) -> int:
    return serp_flights.watch_call_estimate(fare_watch.watch_request(fw))


def _hotel_find_key(name: str, city: str, ci: str, co: str, n: int) -> str:
    q = " ".join(p.strip() for p in (name, city) if p and p.strip())
    return hotel_prices.find_cache_key(q, ci, co, n, _rooms(n))


def _hotel_price_key(s: dict) -> str:
    return hotel_prices.price_cache_key(
        s["property_token"], s["check_in"], s["check_out"], s["adults"], s["rooms"]
    )


def _activity_keys(name: str, city: str) -> list[str]:
    return [
        activity_prices.search_cache_key(activity_prices.build_query(name, city, p))
        for p in ("getyourguide", "viator")
    ]


def _uncached(keys: list[str]) -> int:
    return sum(0 if _cached(k) else 1 for k in keys)


# ── Building the components from a saved plan ─────────────────────────────────


def _load_plan(spec: dict, user: dict) -> dict:
    plan = plans_db.get_plan(_plan_id(spec))
    if not plan or plan.get("username") != user.get("username"):
        raise PlanNotFound()
    return plan


def _trip_context(plan: dict) -> dict:
    sd = plan.get("search_data") or {}
    dep = _iso(sd.get("departure_date"))
    if not dep:
        raise InvalidSpec(
            "This plan has no departure date, so its price can't be watched."
        )
    if date.fromisoformat(dep) <= fare_watch.utcnow().date():
        raise InvalidSpec(
            "This trip has already started, so its price can't be watched."
        )
    ret = _iso(sd.get("return_date"))
    if ret and ret <= dep:
        ret = None
    destinations = sd.get("destinations") or []
    return {
        "sd": sd,
        "dep": dep,
        "ret": ret,
        "n": _travellers(sd),
        "city": _city(sd.get("destination")),
        "multi_city": isinstance(destinations, list) and len(destinations) > 1,
    }


def _fare_subject(ctx: dict) -> dict | None:
    """The flight's fare-watch fields (resolved airports), or None."""
    sd = ctx["sd"]
    if ctx["multi_city"] or not sd.get("origin") or not sd.get("destination"):
        return None
    try:
        req = TravelSearchRequest(
            origin=sd["origin"],
            destination=sd["destination"],
            departure_date=ctx["dep"],
            return_date=ctx["ret"],
            num_travelers=ctx["n"],
            nationality="",
        )
    except Exception:  # unparseable plan fields: the flight stays an estimate
        return None
    if not req.origin_iata or not req.destination_iata:
        return None
    return {
        "origin_label": req.origin,
        "destination_label": req.destination,
        "origin_code": req.origin_iata,
        "destination_code": req.destination_iata,
        "departure_date": ctx["dep"],
        "return_date": ctx["ret"],
        "num_travelers": ctx["n"],
    }


def _drafts(plan: dict, ctx: dict) -> list[dict]:
    """Every priced part of the plan, as estimates; ``_try`` marks the parts
    to look up live."""
    sel = plan.get("selections") or {}
    n, city, dep, ret = ctx["n"], ctx["city"], ctx["dep"], ctx["ret"]
    out: list[dict] = []

    flight = sel.get("flight") if isinstance(sel.get("flight"), dict) else None
    legs = [f for f in sel.get("flights") or [] if isinstance(f, dict)]
    if flight or legs:
        price = _amount((flight or {}).get("price_usd")) + sum(
            _amount(f.get("price_usd")) for f in legs
        )
        detail = (
            f"{_plural(len(legs), 'flight leg')} you picked (estimate)"
            if legs
            else "The flight you picked (estimate)"
        )
        d = _draft("flight", "flight", "Flights", price, detail=detail)
        fare = _fare_subject(ctx) if flight and not legs else None
        if fare:
            d["_try"] = fare
        out.append(d)

    hotel = sel.get("hotel") if isinstance(sel.get("hotel"), dict) else None
    if hotel:
        nights = _nights(dep, ret)
        price = _amount(hotel.get("total_price_usd")) or (
            _amount(hotel.get("price_per_night_usd")) * nights
        )
        name = str(hotel.get("name") or "").strip()
        d = _draft(
            "hotel",
            "hotel",
            name or "Hotel",
            price,
            detail=f"{_plural(nights, 'night')} (estimate)",
        )
        if name and city and ret and not ctx["multi_city"]:
            d["_try"] = {"name": name, "city": city}
        out.append(d)

    tried = 0
    for i, act in enumerate(sel.get("activities") or []):
        if not isinstance(act, dict):
            continue
        name = str(act.get("name") or "").strip()
        unit = _amount(act.get("price_usd"))
        d = _draft(
            f"activity-{i}",
            "activity",
            name or "Activity",
            unit * n,
            detail=_per_person_detail(unit, n, live=False) if unit else None,
        )
        # each activity's own leg city; on a multi-city trip one without a
        # city is never guessed
        where = _city(act.get("city")) or ("" if ctx["multi_city"] else city)
        if name and where and tried < MAX_LIVE_ACTIVITIES:
            tried += 1
            d["_try"] = {"name": name, "city": where}
        out.append(d)

    sim = sel.get("sim") if isinstance(sel.get("sim"), dict) else None
    if sim:
        out.append(
            _draft(
                "sim",
                "other",
                "SIM / eSIM",
                _amount(sim.get("price_usd")),
                detail="From your search (estimate)",
            )
        )
    return out


# ── Live lookups at creation: each returns (calls, quota error or None) ───────


def _failed(label: str, exc: Exception) -> Exception | None:
    """A quota error stops the create; any other leaves the part an estimate."""
    if getattr(exc, "quota_exceeded", False):
        return exc
    logger.info("Trip watch: %s lookup failed: %s", label, type(exc).__name__)
    return None


async def _create_flight(d: dict, api_key: str):
    fare = d["_try"]
    worst = _flight_cost(fare)
    try:
        check = await fare_watch.fetch_fares({**fare, "flexible_days": 0}, api_key)
    except Exception as exc:
        return worst, _failed("flight", exc)
    if check.price is not None:
        d.update(
            live=True,
            label=LIVE_FLIGHT_LABEL,
            detail=_flight_detail(fare),
            price=round(float(check.price), 2),
            source="google_flights",
            status="ok",
            subject=fare,
            link=serp_flights.google_flights_url(
                fare["origin_code"],
                fare["destination_code"],
                fare["departure_date"],
                fare["return_date"],
            ),
        )
    return check.calls, None


async def _create_hotel(d: dict, ctx: dict, api_key: str):
    name, city, n = d["_try"]["name"], d["_try"]["city"], ctx["n"]
    rooms = _rooms(n)
    offers, calls, exc = await _counted(
        [_hotel_find_key(name, city, ctx["dep"], ctx["ret"], n)],
        hotel_prices.find_properties(
            name, city, ctx["dep"], ctx["ret"], n, api_key, rooms=rooms
        ),
    )
    if exc is not None:
        return calls, _failed("hotel", exc)
    match = hotel_prices.match_property(name, offers or [], city)
    if match is None or not match.total_rate:
        return calls, None
    subject = {
        "name": match.name,
        "requested_name": name,
        "city": city,
        "property_token": match.property_token,
        "check_in": ctx["dep"],
        "check_out": ctx["ret"],
        "adults": n,
        "rooms": rooms,
    }
    d.update(
        live=True,
        label=match.name,
        detail=_hotel_detail(subject, match.rate_per_night),
        price=round(float(match.total_rate), 2),
        unit_price=match.rate_per_night,
        unit="per night",
        source=hotel_prices.SOURCE,
        status="ok",
        link=match.link,
        subject=subject,
    )
    return calls, None


async def _create_activity(d: dict, ctx: dict, api_key: str):
    name, city, n = d["_try"]["name"], d["_try"]["city"], ctx["n"]
    listings, calls, exc = await _counted(
        _activity_keys(name, city),
        activity_prices.find_listings(name, city, api_key),
    )
    if exc is not None:
        return calls, _failed(d["id"], exc)
    match = activity_prices.match_listing(name, listings or [], city)
    if match is None or match.is_category or not match.price_from:
        return calls, None
    if not match.is_usd:
        # Non-USD prices can't join a USD total: keep the AI estimate, or —
        # without one — show the listing's price, frozen, outside the total.
        if not d["price"]:
            d.update(
                price=round(match.price_from * n, 2),
                currency=match.currency,
                in_total=False,
                unit_price=match.price_from,
                unit="per person",
                source=match.source,
                link=match.url,
                detail=f"{_per_person_detail(match.price_from, n, match.currency, live=True)}"
                " (estimate, not in the US-dollar total)",
            )
        return calls, None
    d.update(
        live=True,
        price=round(match.price_from * n, 2),
        unit_price=match.price_from,
        unit="per person",
        detail=_per_person_detail(match.price_from, n, live=True),
        source=match.source,
        status="ok",
        link=match.url,
        subject={
            "name": name,
            "city": city,
            "listing_url": match.url,
            "listing_title": match.title,
            "provider": match.provider,
            "query": match.query,
            "travellers": n,
            "currency": match.currency,
            "page_kind": match.page_kind,
            "price_from": match.price_from,
            "rating": match.rating,
            "reviews": match.reviews,
        },
    )
    return calls, None


async def _resolve_live(drafts: list[dict], ctx: dict, api_key: str) -> int:
    """Look up the live parts within CREATE_CALL_CAP; returns the calls made.

    Each lookup reserves its worst case from the cap and gives back what it
    didn't use, so later activities can still run. A quota error stops the
    create, carrying the calls made so far (``exc.calls``)."""
    budget = CREATE_CALL_CAP
    pending: list[tuple[Awaitable, int]] = []
    for d in drafts:
        if "_try" not in d or d["type"] == "activity":
            continue
        t = d["_try"]
        if d["type"] == "flight":
            worst = _flight_cost(t)
            job = _create_flight(d, api_key)
        else:
            worst = _uncached(
                [
                    _hotel_find_key(
                        t["name"], t["city"], ctx["dep"], ctx["ret"], ctx["n"]
                    )
                ]
            )
            job = _create_hotel(d, ctx, api_key)
        if worst > budget:
            job.close()
            continue
        budget -= worst
        pending.append((job, worst))

    queue = [d for d in drafts if "_try" in d and d["type"] == "activity"]
    spent = 0
    quota: Exception | None = None
    while pending or queue:
        while queue:
            t = queue[0]["_try"]
            worst = _uncached(_activity_keys(t["name"], t["city"]))
            if worst > budget:
                break
            budget -= worst
            pending.append((_create_activity(queue.pop(0), ctx, api_key), worst))
        if not pending:
            break
        results = await asyncio.gather(*(job for job, _ in pending))
        for (_, worst), (calls, exc) in zip(pending, results, strict=True):
            spent += calls
            budget += worst - calls  # give back what wasn't used
            quota = quota or exc
        pending = []
        if quota is not None:
            break
    if quota is not None:
        quota.calls = spent
        raise quota
    return spent


# ── Checking ──────────────────────────────────────────────────────────────────


def _previous(watch: dict) -> dict[str, dict]:
    """Each component's last look (its baseline before the first check)."""
    rows = ((watch.get("last_observation") or {}).get("breakdown")) or []
    prev = {c["id"]: dict(c) for c in watch["subject"].get("components") or []}
    for row in rows:
        if isinstance(row, dict) and row.get("id") in prev:
            prev[row["id"]] = row
    return prev


def _picks(watch: dict) -> list[dict]:
    """The live parts this check looks at: the flight and hotel, and up to
    MAX_LIVE_ACTIVITIES activities, least recently checked first."""
    comps = [c for c in watch["subject"].get("components") or [] if c.get("live")]
    prev = _previous(watch)
    core = [c for c in comps if c["type"] in _ANCHORS]
    acts = [c for c in comps if c["type"] == "activity"]
    order = sorted(
        range(len(acts)),
        key=lambda i: (prev[acts[i]["id"]].get("checked_at") or "", i),
    )
    return core + [acts[i] for i in order[:MAX_LIVE_ACTIVITIES]]


def _check_cost(comp: dict) -> int:
    s = comp["subject"]
    if comp["type"] == "flight":
        return _flight_cost(s)
    if comp["type"] == "hotel":
        return _uncached([_hotel_price_key(s)])
    return _uncached([activity_prices.search_cache_key(s["query"])])


async def _look(comp: dict, api_key: str):
    """One live part → ``(price or None if unavailable, extras, calls, exc)``."""
    s = comp["subject"]
    if comp["type"] == "flight":
        worst = _flight_cost(s)
        try:
            check = await fare_watch.fetch_fares({**s, "flexible_days": 0}, api_key)
        except Exception as exc:
            return None, {}, worst, exc
        price = None if check.price is None else float(check.price)
        return price, {}, check.calls, None
    if comp["type"] == "hotel":
        hp, calls, exc = await _counted(
            [_hotel_price_key(s)],
            hotel_prices.price_property(
                s["property_token"],
                s["check_in"],
                s["check_out"],
                s["adults"],
                api_key,
                rooms=s.get("rooms") or 1,
            ),
        )
        if exc is not None:
            return None, {}, calls, exc
        if not hp.available or not hp.total:
            return None, {}, calls, None
        extras = {
            "unit_price": hp.nightly,
            "detail": _hotel_detail(s, hp.nightly),
            "link": hp.link or comp.get("link"),
        }
        return float(hp.total), extras, calls, None
    listing = ActivityListing(
        provider=s["provider"],
        url=s["listing_url"],
        title=s["listing_title"],
        price_from=s.get("price_from") or 0.0,
        currency=s.get("currency") or "USD",
        is_usd=True,
        rating=s.get("rating"),
        reviews=s.get("reviews"),
        snippet="",
        page_kind=s.get("page_kind") or "activity",
        query=s["query"],
    )
    ap, calls, exc = await _counted(
        [activity_prices.search_cache_key(s["query"])],
        activity_prices.price_listing(listing, s["query"], api_key),
    )
    if exc is not None:
        return None, {}, calls, exc
    if not ap.available or not ap.is_usd or not ap.price_from:
        return None, {}, calls, None  # gone, unpriced, or now in another currency
    n = s.get("travellers") or 1
    extras = {
        "unit_price": ap.price_from,
        "detail": _per_person_detail(ap.price_from, n, live=True),
        "link": ap.url,
    }
    return round(ap.price_from * n, 2), extras, calls, None


def _row(comp: dict, prev: dict, **fields) -> dict:
    row = {k: v for k, v in comp.items() if k != "subject"}
    for key in ("checked_at", "unit_price", "detail"):
        if key in prev and comp.get("live"):
            row[key] = prev[key]
    row.update(fields)
    before = prev.get("price", comp["price"])
    row["previous_price"] = before
    row["delta"] = round(row["price"] - before, 2)
    return row


def _total(rows: list[dict]) -> float:
    return round(sum(r["price"] for r in rows if r.get("in_total", True)), 2)


def _observed(rows: list[dict]) -> dict:
    def ids(status: str) -> list[str]:
        return [r["id"] for r in rows if r.get("status") == status]

    return {
        "live": sum(1 for r in rows if r.get("live")),
        "estimates": sum(1 for r in rows if not r.get("live")),
        "unavailable": ids("unavailable"),
        "stale": ids("stale"),
        "errors": ids("error"),
    }


# ── Notification wording ──────────────────────────────────────────────────────


def _reference_prices(watch: dict, ref: float) -> dict[str, float] | None:
    """Component prices of the look the alert is measured from — stored by
    the core in ``reference_looks`` (baseline, last alert, re-arm peak).
    None when it isn't stored or doesn't add up to ``ref``: then only the
    total is explained, never invented component moves."""
    looks = watch.get("reference_looks") or {}
    last, peak = watch.get("last_notified_price"), watch.get("own_peak_price")
    if last is None:
        key = "baseline"
    elif price_rules.rearmed(last, peak, price_rules.TRIP_STEP):
        key = "peak"
    else:
        key = "last_alert"
    rows = looks.get(key)
    if not isinstance(rows, list) or not rows:
        return None
    if abs(_total(rows) - ref) > 0.01:
        return None
    return {r["id"]: r["price"] for r in rows if "id" in r}


def _moves(watch: dict, obs: PriceObservation, ref: float) -> list[dict]:
    """Live groups whose price moved since the reference, biggest drop first."""
    before = _reference_prices(watch, ref)
    if before is None:
        return []
    groups: dict[str, float] = {}
    for row in obs.breakdown or []:
        if not row.get("live") or not row.get("in_total", True):
            continue
        d = row["price"] - before.get(row["id"], row["price"])
        groups[row["group"]] = groups.get(row["group"], 0.0) + d
    moves = [
        {"group": g, "label": MOVE_LABELS.get(g, g), "delta": round(d, 2)}
        for g, d in groups.items()
        if round(d) != 0
    ]
    return sorted(moves, key=lambda m: m["delta"])


def _signed(delta: float) -> str:
    return f"{'−' if delta < 0 else '+'}{usd(abs(delta))}"


def _phrase(moves: list[dict]) -> str:
    return ", ".join(f"{m['label']} {_signed(m['delta'])}" for m in moves)


def _estimates_sentence(rows: list[dict]) -> str | None:
    names = [r["label"] for r in rows if not r.get("live")]
    if not names:
        return None
    shown = ", ".join(names[:MAX_NAMED_ESTIMATES])
    if len(names) > MAX_NAMED_ESTIMATES:
        shown += f" +{len(names) - MAX_NAMED_ESTIMATES} more"
    return f"Estimates ({shown}) are held fixed and never trigger alerts."


def _unpriced_sentences(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        if (
            r.get("live")
            and r["type"] in _ANCHORS
            and r["status"]
            in (
                "unavailable",
                "error",
            )
        ):
            name = "Flights" if r["type"] == "flight" else r["label"]
            out.append(
                f"{name}: no live price on this check (last seen {usd(r['price'])})."
            )
    return out


def _your_trip(city: str | None) -> str:
    return f"Your {city} trip" if city else "Your trip"


# ── The source ────────────────────────────────────────────────────────────────


class TripSource:
    kind = "trip"
    step = price_rules.TRIP_STEP

    def match_key(self, spec: dict) -> str:
        return f"plan:{_plan_id(spec)}"

    async def create(
        self, spec: dict, user: dict, api_key: str
    ) -> CreatedWatch | NoLivePrice:
        plan = _load_plan(spec, user)
        ctx = _trip_context(plan)
        drafts = _drafts(plan, ctx)
        calls = await _resolve_live(drafts, ctx, api_key)
        stamp = _now()
        comps = [_public(d) for d in drafts if d["live"] or d["price"] > 0]
        rows = [
            _row(c, {}, **({"checked_at": stamp} if c["live"] else {})) for c in comps
        ]
        total = _total(rows)
        if not any(c["live"] for c in comps):
            return NoLivePrice(
                message=NO_LIVE_MESSAGE,
                estimate={"price": total, "source": ESTIMATE} if comps else None,
                calls=calls,
            )
        n, city = ctx["n"], ctx["city"]
        where = city or "Your trip"
        return CreatedWatch(
            subject={
                "plan_id": plan["id"],
                "plan_name": plan.get("name"),
                "city": city or None,
                "departure_date": ctx["dep"],
                "return_date": ctx["ret"],
                "travellers": n,
                "components": comps,
            },
            baseline=PriceObservation(
                price=total,
                source="trip",
                breakdown=rows,
                observed=_observed(rows),
                calls=calls,
            ),
            title=plan.get("name") or (f"{city} trip" if city else "Your trip"),
            subtitle=f"{where} · {date_range(ctx['dep'], ctx['ret'])} · "
            f"{_plural(n, 'traveller')}",
            expires_on=ctx["dep"],
            plan_id=plan["id"],
        )

    def estimate_calls(self, watch: dict) -> int:
        return min(sum(_check_cost(c) for c in _picks(watch)), CHECK_CALL_CAP)

    async def check(self, watch: dict, api_key: str) -> PriceObservation:
        picks = _picks(watch)
        prev = _previous(watch)
        results = await asyncio.gather(*(_look(c, api_key) for c in picks))
        calls = sum(r[2] for r in results)
        errors = [r[3] for r in results if r[3] is not None]
        for exc in errors:
            if getattr(exc, "quota_exceeded", False):
                exc.calls = calls
                raise exc
        if picks and len(errors) == len(picks):
            errors[0].calls = calls
            raise errors[0]

        stamp = _now()
        looked = dict(zip((c["id"] for c in picks), results, strict=True))
        rows = []
        for comp in watch["subject"].get("components") or []:
            p = prev.get(comp["id"], comp)
            last = p.get("price", comp["price"])
            if not comp.get("live"):
                rows.append(_row(comp, {}, status="estimate"))
                continue
            if comp["id"] not in looked:
                rows.append(_row(comp, p, price=last, status="stale"))
                continue
            price, extras, _, exc = looked[comp["id"]]
            if exc is not None:
                logger.info(
                    "Trip watch %s: %s look failed: %s",
                    watch.get("id"),
                    comp["id"],
                    type(exc).__name__,
                )
                rows.append(_row(comp, p, price=last, status="error"))
            elif price is None:
                rows.append(
                    _row(comp, p, price=last, status="unavailable", checked_at=stamp)
                )
            else:
                rows.append(
                    _row(comp, p, price=price, status="ok", checked_at=stamp, **extras)
                )

        # Unavailable only when no live part priced on this check; otherwise
        # the others are carried at their last observed price (flagged).
        priced = any(r["status"] == "ok" for r in rows if r.get("live"))
        return PriceObservation(
            price=_total(rows) if priced else None,
            status="ok" if priced else "unavailable",
            source="trip",
            breakdown=rows,
            observed=_observed(rows),
            calls=calls,
        )

    def compose(
        self, kind: str, watch: dict, obs: PriceObservation, ref: float
    ) -> dict:
        s = watch["subject"]
        city, p = s.get("city"), obs.price
        rows = obs.breakdown or []
        moves = _moves(watch, obs, ref)
        phrase = _phrase(moves)
        if kind.endswith("_target"):
            title = (
                f"🧳 {_your_trip(city)} is now {usd(p)} — below your "
                f"{usd(watch['target_price'])} target"
            )
        else:
            title = f"🧳 {_your_trip(city)} is {usd(ref - p)} cheaper"
            if phrase:
                title += f": {phrase}"
        body = [f"Now {usd(p)}, was {usd(ref)}."]
        if phrase:
            body.append(f"{phrase[0].upper()}{phrase[1:]}.")
        body += _unpriced_sentences(rows)
        if any(r.get("live") and r["type"] == "flight" for r in rows):
            body.append(
                "Flights are the cheapest Google Flights fare on your dates, "
                "not one specific flight."
            )
        estimates = _estimates_sentence(rows)
        if estimates:
            body.append(estimates)
        if s.get("departure_date"):
            body.append(
                f"For {date_range(s['departure_date'], s.get('return_date'))}"
                f" · {_plural(s.get('travellers') or 1, 'traveller')}."
            )
        return {
            "kind": kind,
            "title": title,
            "body": " ".join(body),
            "data": {"components": moves, "plan_id": s.get("plan_id"), "city": city},
        }


SOURCE = TripSource()

__all__: list[str] = ["SOURCE", "PlanNotFound", "TripSource"]
