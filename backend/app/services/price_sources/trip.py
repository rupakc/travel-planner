"""Whole-trip price watch: the price of a saved plan — flights, hotel,
activities and the other priced parts — as one total.

The spec is just ``{plan_id}``: the server loads the traveller's own saved
plan (anyone else's, or a missing one, is the same 404 "Plan not found")
and turns its selections into **components**, mirroring the plan drawer's
cost breakdown (``frontend/src/utils/planHelpers.js``):

- the selected flight → **live** via the fare-watch path (Google Flights'
  cheapest fare for the plan's route, dates and travellers, as a fare watch
  tracks it); multi-city legs, or a route we can't price → estimate;
- the selected hotel → **live** via ``hotel_prices`` (Google Hotels, matched
  by name; stored with the hotel watch's subject fields) → else estimate;
- selected activities → **live** via ``activity_prices`` (the GetYourGuide /
  Viator "from" price in Google results, per person × travellers; stored
  with the activity watch's subject fields) for at most
  ``MAX_LIVE_ACTIVITIES``; category pages, non-USD listings and the rest →
  estimates;
- the SIM / eSIM plan → estimate ("other").

Estimates are the AI prices of the original search, **frozen at creation**
and labelled; they are part of the total but never move, so they never
alert on their own. A plan with no live part can't be watched (422
``no_live_price``).

A check re-prices the live parts (≤ ``CHECK_CALL_CAP`` SerpAPI calls; at
most ``MAX_LIVE_ACTIVITIES`` activities, least recently checked first, the
others keep their last observed price marked ``stale``). A part that is
unavailable (or whose look failed) keeps its last observed price, flagged
in the breakdown; when the flight and hotel are both unavailable the whole
look is ``unavailable``. Alerts use the trip step (max $25, 4 %) on the
total and explain the change by component.

The watch works on its frozen subject: deleting the plan afterwards doesn't
stop it (it still ends on the departure date).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, date, datetime

from ...core.cache import get_cache
from ...db import plans_db, price_watch_db
from ...schemas.request import TravelSearchRequest
from .. import activity_prices, fare_watch, hotel_prices, price_rules, serp_flights
from ..activity_prices import ActivityListing
from ..fare_watch import date_range, usd
from ..price_watch import CreatedWatch, InvalidSpec, NoLivePrice, PriceObservation

logger = logging.getLogger(__name__)

CREATE_CALL_CAP = 10  # SerpAPI calls a create may spend
CHECK_CALL_CAP = 8  # … and one check
MAX_LIVE_ACTIVITIES = 5  # activities looked up live per create / check
NO_LIVE_MESSAGE = "We can't find a live price for any part of this trip yet"
ESTIMATE = "ai_estimate"
DEFAULT_NIGHTS = 7  # as the plan drawer, when the plan has no return date

GROUPS = {"flight": "flights", "hotel": "stay", "activity": "activities"}
# How each group reads in "flights −$70, hotel −$42"
MOVE_LABELS = {
    "flights": "flights",
    "stay": "hotel",
    "activities": "activities",
    "other": "other",
}
_ANCHORS = ("flight", "hotel")  # both unavailable → the look is unavailable
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
    return n if n > 0 and n != float("inf") else 0.0


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
    return str(destination or "").split(",")[0].strip()


def _travellers(sd: dict) -> int:
    n = sd.get("num_travelers")
    if not n:
        n = sum(int(sd.get(k) or 0) for k in ("adults", "children", "seniors"))
    try:
        return max(1, min(int(n or 1), 20))
    except (TypeError, ValueError):
        return 1


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


# ── SerpAPI call accounting (cached answers are free) ─────────────────────────


def _cached(key: str) -> bool:
    return key in get_cache()


def _flight_cost(fw: dict) -> int:
    return serp_flights.watch_call_estimate(fare_watch.watch_request(fw))


def _hotel_find_cost(name: str, city: str, ci: str, co: str, adults: int) -> int:
    q = " ".join(p.strip() for p in (name, city) if p and p.strip())
    return 0 if _cached(hotel_prices._find_key(q, ci, co, adults, 1)) else 1


def _hotel_price_cost(s: dict) -> int:
    key = hotel_prices._price_key(
        s["property_token"], s["check_in"], s["check_out"], s["adults"], s["rooms"]
    )
    return 0 if _cached(key) else 1


def _activity_queries(name: str, city: str) -> tuple[str, str]:
    return (
        activity_prices.build_query(name, city, "getyourguide"),
        activity_prices.build_query(name, city, "viator"),
    )


def _activity_find_cost(name: str, city: str) -> int:
    """Worst case: the GetYourGuide query, then the Viator one."""
    return sum(
        0 if _cached(activity_prices._cache_key(q)) else 1
        for q in _activity_queries(name, city)
    )


def _activity_price_cost(s: dict) -> int:
    return 0 if _cached(activity_prices._cache_key(s["query"])) else 1


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
    ret = _iso(sd.get("return_date"))
    if ret and ret <= dep:
        ret = None
    destinations = sd.get("destinations") or []
    return {
        "sd": sd,
        "dep": dep,
        "ret": ret,
        "n": _travellers(sd),
        "city": _city(sd.get("destination")) or "your",
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
        d = _draft("flight", "flight", "Flights", price)
        fare = _fare_subject(ctx) if flight and not legs else None
        if fare:
            d["_try"] = fare
        out.append(d)

    hotel = sel.get("hotel") if isinstance(sel.get("hotel"), dict) else None
    if hotel:
        price = _amount(hotel.get("total_price_usd")) or _amount(
            hotel.get("price_per_night_usd")
        ) * _nights(dep, ret)
        name = str(hotel.get("name") or "").strip()
        d = _draft("hotel", "hotel", name or "Hotel", price)
        if name and ret and not ctx["multi_city"]:
            d["_try"] = {"name": name, "city": city}
        out.append(d)

    tried = 0
    for i, act in enumerate(sel.get("activities") or []):
        if not isinstance(act, dict):
            continue
        name = str(act.get("name") or "").strip()
        d = _draft(
            f"activity-{i}",
            "activity",
            name or "Activity",
            _amount(act.get("price_usd")) * n,
        )
        if name and tried < MAX_LIVE_ACTIVITIES:
            tried += 1
            d["_try"] = {"name": name, "city": city}
        out.append(d)

    sim = sel.get("sim") if isinstance(sel.get("sim"), dict) else None
    if sim:
        out.append(_draft("sim", "other", "SIM / eSIM", _amount(sim.get("price_usd"))))
    return out


# ── Live lookups at creation ──────────────────────────────────────────────────


async def _create_flight(d: dict, api_key: str) -> None:
    fare = d["_try"]
    check = await fare_watch.fetch_fares({**fare, "flexible_days": 0}, api_key)
    if check.price is None:
        return
    d.update(
        live=True,
        price=round(float(check.price), 2),
        source="google_flights",
        status="ok",
        subject=fare,
        link=serp_flights._google_flights_url(
            fare["origin_code"],
            fare["destination_code"],
            fare["departure_date"],
            fare["return_date"],
        ),
    )


async def _create_hotel(d: dict, ctx: dict, api_key: str) -> None:
    name, city = d["_try"]["name"], d["_try"]["city"]
    offers = await hotel_prices.find_properties(
        name, city, ctx["dep"], ctx["ret"], ctx["n"], api_key, rooms=1
    )
    match = hotel_prices.match_property(name, offers, city)
    if match is None or not match.total_rate:
        return
    d.update(
        live=True,
        price=round(float(match.total_rate), 2),
        unit_price=match.rate_per_night,
        unit="per night",
        source=hotel_prices.SOURCE,
        status="ok",
        link=match.link,
        subject={
            "name": match.name,
            "requested_name": name,
            "city": city,
            "property_token": match.property_token,
            "check_in": ctx["dep"],
            "check_out": ctx["ret"],
            "adults": ctx["n"],
            "rooms": 1,
        },
    )


async def _create_activity(d: dict, ctx: dict, api_key: str) -> int:
    """Look the activity up; returns the SerpAPI calls it spent."""
    name, city, n = d["_try"]["name"], d["_try"]["city"], ctx["n"]
    gyg_q, viator_q = _activity_queries(name, city)
    gyg_new = not _cached(activity_prices._cache_key(gyg_q))
    viator_new = not _cached(activity_prices._cache_key(viator_q))
    listings = await activity_prices.find_listings(name, city, api_key)
    gyg_best = activity_prices.match_listing(
        name, [x for x in listings if x.provider == "getyourguide"], city
    )
    spent = int(gyg_new) + int(
        viator_new and (gyg_best is None or gyg_best.is_category)
    )
    match = activity_prices.match_listing(name, listings, city)
    if match is None or match.is_category or not match.price_from:
        return spent
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
            )
        return spent
    d.update(
        live=True,
        price=round(match.price_from * n, 2),
        unit_price=match.price_from,
        unit="per person",
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
    return spent


async def _guarded(coro: Awaitable, label: str, worst: int) -> int:
    """Run one create lookup: a failure leaves that part an estimate (a
    quota error stops the create). Returns the calls it spent."""
    try:
        spent = await coro
    except Exception as exc:
        if getattr(exc, "quota_exceeded", False):
            raise
        logger.info("Trip watch: %s lookup failed: %s", label, type(exc).__name__)
        return worst
    return worst if spent is None else spent


async def _resolve_live(drafts: list[dict], ctx: dict, api_key: str) -> int:
    """Look up the live parts within CREATE_CALL_CAP; returns calls spent."""
    budget = CREATE_CALL_CAP
    first: list[Awaitable] = []
    for d in drafts:
        if "_try" not in d or d["type"] == "activity":
            continue
        if d["type"] == "flight":
            cost = _flight_cost(d["_try"])
            coro = _create_flight(d, api_key)
        else:
            t = d["_try"]
            cost = _hotel_find_cost(
                t["name"], t["city"], ctx["dep"], ctx["ret"], ctx["n"]
            )
            coro = _create_hotel(d, ctx, api_key)
        if cost > budget:
            coro.close()
            continue
        budget -= cost
        first.append(_guarded(_with_cost(coro, cost), d["id"], cost))

    queue = [d for d in drafts if "_try" in d and d["type"] == "activity"]
    spent = 0
    pending = first
    while pending or queue:
        batch: list[tuple[dict, int]] = []
        while queue:
            cost = _activity_find_cost(
                queue[0]["_try"]["name"], queue[0]["_try"]["city"]
            )
            if cost > budget:
                break
            budget -= cost
            batch.append((queue.pop(0), cost))
        if not batch and not pending:
            break
        jobs = pending + [
            _guarded(_create_activity(d, ctx, api_key), d["id"], cost)
            for d, cost in batch
        ]
        results = await asyncio.gather(*jobs)
        used = list(results)
        spent += sum(used)
        # refund what the batch reserved but didn't spend
        budget += sum(cost for _, cost in batch) - sum(used[len(pending) :])
        pending = []
    return spent


async def _with_cost(coro: Awaitable, cost: int) -> int:
    await coro
    return cost


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
        range(len(acts)), key=lambda i: (prev[acts[i]["id"]].get("checked_at") or "", i)
    )
    return core + [acts[i] for i in order[:MAX_LIVE_ACTIVITIES]]


def _check_cost(comp: dict) -> int:
    s = comp["subject"]
    if comp["type"] == "flight":
        return _flight_cost(s)
    if comp["type"] == "hotel":
        return _hotel_price_cost(s)
    return _activity_price_cost(s)


async def _look(comp: dict, api_key: str) -> tuple[float | None, dict]:
    """(price, extras) for one live part; price None = unavailable."""
    s = comp["subject"]
    if comp["type"] == "flight":
        check = await fare_watch.fetch_fares({**s, "flexible_days": 0}, api_key)
        return (None if check.price is None else float(check.price)), {}
    if comp["type"] == "hotel":
        hp = await hotel_prices.price_property(
            s["property_token"],
            s["check_in"],
            s["check_out"],
            s["adults"],
            api_key,
            rooms=s.get("rooms") or 1,
        )
        if not hp.available or not hp.total:
            return None, {}
        return float(hp.total), {
            "unit_price": hp.nightly,
            "link": hp.link or comp.get("link"),
        }
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
    ap = await activity_prices.price_listing(listing, s["query"], api_key)
    if not ap.available or not ap.is_usd or not ap.price_from:
        return None, {}  # gone, unpriced, or now in another currency
    n = s.get("travellers") or 1
    return round(ap.price_from * n, 2), {"unit_price": ap.price_from, "link": ap.url}


def _row(comp: dict, prev: dict, **fields) -> dict:
    row = {k: v for k, v in comp.items() if k != "subject"}
    if "checked_at" in prev:
        row["checked_at"] = prev["checked_at"]
    if prev.get("unit_price") is not None and comp.get("live"):
        row["unit_price"] = prev["unit_price"]
    row.update(fields)
    before = prev.get("price", comp["price"])
    row["previous_price"] = before
    row["delta"] = round(row["price"] - before, 2)
    return row


def _total(rows: list[dict]) -> float:
    return round(sum(r["price"] for r in rows if r.get("in_total", True)), 2)


# ── Notification wording ──────────────────────────────────────────────────────


def _reference_prices(watch: dict, ref: float) -> dict[str, float]:
    """Component prices at the look whose total was ``ref`` (the baseline,
    the last alert or the peak since it); the baseline if it's gone."""
    for h in reversed(price_watch_db.get_history(watch["id"])):
        if (
            h.get("price") is not None
            and abs(h["price"] - ref) < 0.01
            and h.get("breakdown")
        ):
            return {r["id"]: r["price"] for r in h["breakdown"] if "id" in r}
    return {c["id"]: c["price"] for c in watch["subject"].get("components") or []}


def _moves(watch: dict, obs: PriceObservation, ref: float) -> list[dict]:
    """Live groups whose price moved since the reference, biggest drop first."""
    before = _reference_prices(watch, ref)
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


def _travellers_text(n: int) -> str:
    return f"{n} traveller{'s' if n != 1 else ''}"


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
        n = ctx["n"]
        return CreatedWatch(
            subject={
                "plan_id": plan["id"],
                "plan_name": plan.get("name"),
                "city": ctx["city"],
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
            title=plan.get("name") or f"{ctx['city']} trip",
            subtitle=f"{ctx['city']} · {date_range(ctx['dep'], ctx['ret'])} · "
            f"{_travellers_text(n)}",
            expires_on=ctx["dep"],
            plan_id=plan["id"],
        )

    def estimate_calls(self, watch: dict) -> int:
        return min(sum(_check_cost(c) for c in _picks(watch)), CHECK_CALL_CAP)

    async def check(self, watch: dict, api_key: str) -> PriceObservation:
        picks = _picks(watch)
        prev = _previous(watch)
        costs = {c["id"]: _check_cost(c) for c in picks}
        results = await asyncio.gather(
            *(_look(c, api_key) for c in picks), return_exceptions=True
        )
        for r in results:
            if isinstance(r, BaseException) and getattr(r, "quota_exceeded", False):
                raise r
        errors = [r for r in results if isinstance(r, BaseException)]
        if picks and len(errors) == len(picks):
            raise errors[0]

        stamp = _now()
        looked = dict(zip((c["id"] for c in picks), results, strict=True))
        rows = []
        for comp in watch["subject"].get("components") or []:
            p = prev.get(comp["id"], comp)
            last = p.get("price", comp["price"])
            if not comp.get("live"):
                rows.append(_row(comp, {}, status="estimate"))
            elif comp["id"] not in looked:
                rows.append(_row(comp, p, price=last, status="stale"))
            else:
                got = looked[comp["id"]]
                if isinstance(got, BaseException):
                    logger.info(
                        "Trip watch %s: %s look failed: %s",
                        watch.get("id"),
                        comp["id"],
                        type(got).__name__,
                    )
                    rows.append(_row(comp, p, price=last, status="error"))
                elif got[0] is None:
                    rows.append(
                        _row(
                            comp, p, price=last, status="unavailable", checked_at=stamp
                        )
                    )
                else:
                    rows.append(
                        _row(
                            comp,
                            p,
                            price=got[0],
                            status="ok",
                            checked_at=stamp,
                            **got[1],
                        )
                    )

        status = _look_status(rows, picks)
        if status == "failed":
            raise next(
                r
                for c, r in zip(picks, results, strict=True)
                if c["type"] in _ANCHORS and isinstance(r, BaseException)
            )
        return PriceObservation(
            price=_total(rows) if status == "ok" else None,
            status=status,
            source="trip",
            breakdown=rows,
            observed=_observed(rows),
            calls=sum(costs.values()),
        )

    def compose(
        self, kind: str, watch: dict, obs: PriceObservation, ref: float
    ) -> dict:
        s = watch["subject"]
        city, p = s.get("city") or "your", obs.price
        moves = _moves(watch, obs, ref)
        phrase = _phrase(moves)
        if kind.endswith("_target"):
            title = (
                f"🧳 Your {city} trip is now {usd(p)} — below your "
                f"{usd(watch['target_price'])} target"
            )
        else:
            title = f"🧳 Your {city} trip is {usd(ref - p)} cheaper"
            if phrase:
                title += f": {phrase}"
        body = [f"Now {usd(p)}, was {usd(ref)}."]
        if phrase:
            body.append(f"{phrase[0].upper()}{phrase[1:]}.")
        estimates = [r["label"] for r in obs.breakdown or [] if not r.get("live")]
        if estimates:
            body.append(
                f"Estimates ({', '.join(estimates)}) are held fixed and never "
                "trigger alerts."
            )
        if s.get("departure_date"):
            body.append(
                f"For {date_range(s['departure_date'], s.get('return_date'))}"
                f" · {_travellers_text(s.get('travellers') or 1)}."
            )
        return {
            "kind": kind,
            "title": title,
            "body": " ".join(body),
            "data": {
                "components": moves,
                "plan_id": s.get("plan_id"),
                "city": city,
            },
        }


def _look_status(rows: list[dict], picks: list[dict]) -> str:
    """ok / unavailable / failed for one check (see the module docstring)."""
    by_id = {r["id"]: r for r in rows}
    picked = [by_id[c["id"]] for c in picks]
    anchors = [r for r in picked if r["type"] in _ANCHORS]
    judged = anchors or picked
    if any(r["status"] == "ok" for r in judged):
        return "ok"
    if any(r["status"] == "unavailable" for r in judged):
        return "unavailable"
    return "failed" if anchors else "ok"


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


SOURCE = TripSource()

__all__: list[str] = ["SOURCE", "PlanNotFound", "TripSource"]
