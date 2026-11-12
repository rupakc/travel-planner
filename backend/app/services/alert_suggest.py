"""Watch suggestions for a saved plan (built locally: no network, no AI).

Each suggestion's ``spec`` is exactly what ``POST /alerts/quick-watch``
accepts for its kind; a part whose spec the watch source would reject (past
dates, no city, ...) is simply not suggested.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from ..db import fare_watch_db, price_watch_db
from . import fare_watch, price_watch
from .activity_prices import page_kind, provider_of
from .price_sources import activity as activity_src
from .price_sources import hotel as hotel_src
from .price_sources import trip as trip_src
from .price_watch import InvalidSpec

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 5
MAX_HOTELS = 2
MAX_ACTIVITIES = 2
SOON_DAYS = 45


def _sd(plan: dict) -> dict:
    sd = plan.get("search_data")
    return sd if isinstance(sd, dict) else {}


def _sel(plan: dict) -> dict:
    sel = plan.get("selections")
    return sel if isinstance(sel, dict) else {}


def _dates(sd: dict) -> tuple[str | None, str | None]:
    dep, ret = (
        trip_src._iso(sd.get("departure_date")),
        trip_src._iso(sd.get("return_date")),
    )
    if dep and ret and ret <= dep:
        ret = None
    return dep, ret


def _live(row: dict | None) -> bool:
    return bool(row) and row.get("status") != "expired"


def _flight(plan: dict, sd: dict, dep: str | None, ret: str | None) -> dict | None:
    from ..api.routes.fare_watches import TripFields, _resolve

    destinations = sd.get("destinations")
    if isinstance(destinations, list) and len(destinations) > 1:
        return None
    if not (sd.get("origin") and sd.get("destination") and dep):
        return None
    n = trip_src._travellers(sd)
    try:
        req = _resolve(
            TripFields(
                origin=sd["origin"],
                destination=sd["destination"],
                departure_date=dep,
                return_date=ret,
                num_travelers=n,
            )
        )
    except (HTTPException, ValueError):  # unresolvable airports, bad fields
        return None
    except Exception:
        logger.warning("alert suggestion: flight spec failed", exc_info=True)
        return None
    days = (req.departure_date - fare_watch.utcnow().date()).days
    if days <= 0:
        return None
    existing = fare_watch_db.find_watch(
        plan["_user_id"],
        req.origin_iata,
        req.destination_iata,
        dep,
        ret,
        req.num_travelers,
    )
    spec = {
        "origin": sd["origin"],
        "destination": sd["destination"],
        "departure_date": dep,
        "return_date": ret,
        "num_travelers": n,
    }
    return {
        "kind": "flight",
        "title": f"{req.origin_iata} to {req.destination_iata}"[:120],
        "subtitle": fare_watch.date_range(dep, ret),
        "spec": spec,
        "reason": "departure_soon" if days <= SOON_DAYS else "selected_in_plan",
        "already_watching": _live(existing),
    }


def _watched(user_id: str, kind: str, spec: dict) -> bool:
    source = price_watch.get_source(kind)
    try:
        key = source.match_key(spec) if source else None
    except Exception:
        return False
    return bool(key) and _live(price_watch_db.find_watch(user_id, kind, key))


def _hotels(plan: dict, sd: dict, dep, ret) -> list[dict]:
    sel = _sel(plan)
    picked = [h for h in [sel.get("hotel")] if isinstance(h, dict)]
    picked += [h for h in sel.get("hotels") or [] if isinstance(h, dict)]
    city = str(sd.get("destination") or "")
    out: list[dict] = []
    seen: set[str] = set()
    for h in picked:
        name = str(h.get("name") or "").strip()
        if not name or name.lower() in seen or not (dep and ret and city):
            continue
        spec = {
            "name": name,
            "city": city,
            "check_in": dep,
            "check_out": ret,
            "adults": trip_src._travellers(sd),
        }
        try:
            clean = hotel_src._clean(spec)
        except InvalidSpec:
            continue
        except Exception:
            logger.warning("alert suggestion: hotel spec failed", exc_info=True)
            continue
        seen.add(name.lower())
        out.append(
            {
                "kind": "hotel",
                "title": name[:120],
                "subtitle": hotel_src.subtitle(
                    dep, ret, clean["adults"], clean["rooms"]
                ),
                "spec": spec,
                "reason": "selected_in_plan",
                "already_watching": False,
            }
        )
        if len(out) == MAX_HOTELS:
            break
    return out


def _listing_url(act: dict) -> str | None:
    for key in ("booking_url", "url", "link", "listing_url"):
        url = act.get(key)
        if isinstance(url, str) and provider_of(url) and page_kind(url) == "activity":
            return url
    return None


def _activities(plan: dict, sd: dict) -> list[dict]:
    city = str(sd.get("destination") or "")
    out: list[dict] = []
    for act in _sel(plan).get("activities") or []:
        if not isinstance(act, dict):
            continue
        name = str(act.get("name") or "").strip()
        url = _listing_url(act)
        if not (name and url and city):
            continue
        spec = {
            "name": name,
            "city": city,
            "travellers": trip_src._travellers(sd),
            "listing_url": url,
        }
        try:
            activity_src.parse_spec(spec)
        except InvalidSpec:
            continue
        except Exception:
            logger.warning("alert suggestion: activity spec failed", exc_info=True)
            continue
        out.append(
            {
                "kind": "activity",
                "title": name[:120],
                "subtitle": (str(act.get("provider") or "") or None),
                "spec": spec,
                "reason": "selected_in_plan",
                "already_watching": False,
            }
        )
        if len(out) == MAX_ACTIVITIES:
            break
    return out


def _trip(plan: dict, sd: dict) -> dict | None:
    try:
        ctx = trip_src._trip_context(plan)
        parts = [d for d in trip_src._drafts(plan, ctx) if d.get("price", 0) > 0]
    except InvalidSpec:
        return None
    except Exception:
        logger.warning("alert suggestion: trip spec failed", exc_info=True)
        return None
    if len(parts) < 2:
        return None
    place = ctx["city"] or "Your trip"
    return {
        "kind": "trip",
        "title": f"{place} trip total"[:120],
        "subtitle": f"{len(parts)} priced parts",
        "spec": {"plan_id": plan["id"]},
        "reason": "trip_total",
        "already_watching": False,
    }


def suggestions(plan: dict, user: dict) -> list[dict]:
    plan = {**plan, "_user_id": user["id"]}
    sd = _sd(plan)
    dep, ret = _dates(sd)
    out: list[dict] = []
    flight = _flight(plan, sd, dep, ret)
    if flight:
        out.append(flight)
    out += _hotels(plan, sd, dep, ret)
    out += _activities(plan, sd)
    trip = _trip(plan, sd)
    if trip:
        out.append(trip)
    for s in out:
        if s["kind"] != "flight":
            s["already_watching"] = _watched(user["id"], s["kind"], s["spec"])
    # The literal order is flight, hotels, activities, trip, so a full plan
    # (flight + 2 hotels + 2 activities) fills the cap and drops the trip total.
    return out[:MAX_SUGGESTIONS]
