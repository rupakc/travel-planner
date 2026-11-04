"""Places from an imported link ("must include") in activities and itinerary.

- ``merge_into_activities``: the link's places lead the activities result as
  ``source: "your_link"`` items (an agent copy of the same place is folded
  in), and survive an activities-agent failure.
- ``itinerary_prompt_block``: tells the itinerary agent to schedule each one.
- ``ensure_must_include``: a deterministic post-check on any itinerary (AI or
  template). Slots already naming a place are marked ``from_link``; a missing
  place takes the most replaceable slot on a day in its city (free time
  first, never arrival/departure logistics, meals at meal times); when every
  such slot already holds a link place it becomes a day note
  (``link_extras``). ``link_coverage`` reports the outcome.
"""

from __future__ import annotations

import copy
import re
from urllib.parse import quote_plus

from ..core.places import fold_place
from ..schemas.request import MustIncludePlace, TravelSearchRequest
from .name_match import STOP_WORDS

VERIFIED_NOTE = "Located on Google Maps"
UNVERIFIED_NOTE = "From your link — not independently checked"

_DURATION = {
    "food": 1.5,
    "drink": 1.5,
    "nightlife": 2.5,
    "shopping": 2.0,
    "nature": 3.0,
    "activity": 3.0,
    "event": 3.0,
    "area": 2.5,
    "stay": 1.0,
    "transport": 1.0,
}
_MEAL_KINDS = {"food", "drink", "nightlife"}
_FREE_TIME = re.compile(
    r"\bfree (time|morning|afternoon|evening)\b|at your own pace|\bleisure\b|"
    r"\brelax|\brest\b|\boptional\b|explore the neighbou?rhood|spontaneous",
    re.IGNORECASE,
)
_LOGISTICS = re.compile(
    r"\b(arriv\w*|check[- ]?in|check[- ]?out|depart\w*|flight|airport|transfer|"
    r"travel from|train to|pack\w*)\b",
    re.IGNORECASE,
)


def _words(text: str) -> set[str]:
    return {
        w
        for w in re.split(r"[^a-z0-9]+", fold_place(text or ""))
        if len(w) > 2 and w not in STOP_WORDS
    }


def _same_place(name: str, text: str) -> bool:
    """``text`` names the place: its folded name appears, or every one of its
    distinctive words does."""
    folded_name, folded_text = fold_place(name), fold_place(text or "")
    if folded_name and re.search(rf"\b{re.escape(folded_name)}\b", folded_text):
        return True
    words = _words(name)
    return bool(words) and words <= _words(text)


def _city_key(text: str | None) -> str:
    return fold_place((text or "").split(",")[0]).strip()


def _maps_url(place: MustIncludePlace) -> str:
    where = ", ".join(p for p in (place.name, place.town or place.city) if p)
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(where)}"


def _activity_item(place: MustIncludePlace, request: TravelSearchRequest) -> dict:
    title = request.import_source.title if request.import_source else None
    return {
        "name": place.name,
        "category": place.kind,
        "description": place.note
        or (f"Recommended in “{title}”." if title else "From your link."),
        "location": place.town or place.city or request.destination,
        "city": place.city,
        "lat": place.lat,
        "lng": place.lng,
        "duration_hours": _DURATION.get(place.kind, 2.0),
        "price_usd": None,
        "similarity_score": 1.0,
        "source": "your_link",
        "from_link": True,
        "link_quote": place.quote,
        "verification_note": VERIFIED_NOTE if place.verified else UNVERIFIED_NOTE,
        "booking_url": _maps_url(place),
    }


_AGENT_FIELDS = ("rating", "review_count", "price_usd", "booking_url", "image_url")


def merge_into_activities(result: dict, request: TravelSearchRequest) -> dict:
    """Link places first (always kept), then the agent's other activities."""
    if not request.must_include:
        return result
    base = result if isinstance(result, dict) and not result.get("error") else {}
    others = [a for a in base.get("results") or [] if isinstance(a, dict)]
    linked = []
    for place in request.must_include:
        item = _activity_item(place, request)
        for other in others:
            if _same_place(place.name, other.get("name", "")):
                for key in _AGENT_FIELDS:
                    if other.get(key) is not None:
                        item[key] = other[key]
                if not place.note and other.get("description"):
                    item["description"] = other["description"]
                others = [o for o in others if o is not other]
                break
        linked.append(item)
    return {**base, "results": linked + others}


def itinerary_prompt_block(request: TravelSearchRequest) -> str:
    if not request.must_include:
        return ""
    lines = []
    for p in request.must_include:
        where = p.city or request.destination
        if p.town and p.town != p.city:
            where = f"{where} (day trip to {p.town})"
        line = f"- {p.name} ({p.kind}) — {where}"
        if p.note:
            line += f" — {p.note}"
        lines.append(line)
    return (
        "\n\nMUST-INCLUDE PLACES (from the link the traveller imported). "
        "You MUST schedule every one of these — each in its own slot on a day "
        "in its city, with the place's exact name in the slot's activity text "
        'and "from_link": true on that slot. Never drop one to fit the pace; '
        "group nearby ones on the same day and put food/drink places at "
        "lunch or dinner:\n" + "\n".join(lines) + "\n"
    )


def _day_city(day: dict, request: TravelSearchRequest) -> str:
    if day.get("city"):
        return _city_key(day["city"])
    stays = request.city_stays
    if stays and day.get("date"):
        for stay in stays:
            if str(stay["start_date"]) <= str(day["date"]) < str(stay["end_date"]):
                return _city_key(stay["city"])
        return _city_key(stays[-1]["city"])
    return _city_key(request.destination)


_LINK_FIELDS = ("from_link", "link_place", "link_places", "link_quote", "link_note")


def _mark(slot: dict, place: MustIncludePlace) -> None:
    """Tag ``slot`` with ``place``; a slot may cover several link places
    ("Santos and the Time Out Market")."""
    if not slot.get("from_link"):
        slot["from_link"] = True
        slot["link_place"] = place.name
        slot["link_places"] = []
        if place.quote:
            slot["link_quote"] = place.quote
        if place.note:
            slot["link_note"] = place.note
    slot["link_places"].append(place.name)


def _candidate_days(days: list[dict], place, request) -> list[dict]:
    if request.is_multi_city and place.city:
        target = _city_key(place.city)
        matching = [d for d in days if _day_city(d, request) == target]
        if matching:
            days = matching
    return days


def _slot_rank(day: dict, slot: dict, place: MustIncludePlace, linked_per_day):
    free = bool(_FREE_TIME.search(slot.get("activity", "")))
    tod = (slot.get("time_of_day") or "").lower()
    fits = (tod in ("afternoon", "evening")) == (place.kind in _MEAL_KINDS)
    return (
        not free,
        not fits,
        linked_per_day.get(id(day), 0),
        slot.get("duration_hours") or 0,
    )


def ensure_must_include(itinerary: dict, request: TravelSearchRequest) -> dict:
    """Every must-include place scheduled (or noted) in ``itinerary``."""
    if not request.must_include or not isinstance(itinerary, dict):
        return itinerary
    days = [d for d in itinerary.get("days") or [] if isinstance(d, dict)]
    if not days:
        return itinerary
    itinerary = copy.deepcopy(itinerary)
    days = [d for d in itinerary["days"] if isinstance(d, dict)]
    last = len(days) - 1

    def slots_of(day):
        return [s for s in day.get("slots") or [] if isinstance(s, dict)]

    # Only this check decides what is "from your link" — never the model
    for day in days:
        for slot in slots_of(day):
            for key in _LINK_FIELDS:
                slot.pop(key, None)

    scheduled, extras, missing = [], [], []
    linked_per_day: dict[int, int] = {}

    def visit_slots():
        return [
            (day, slot)
            for day in days
            for slot in slots_of(day)
            if not _LOGISTICS.search(slot.get("activity", ""))
        ]

    # Places the itinerary already names: by activity text first (strongest),
    # then by location ("Embaixada Palace" sits in Príncipe Real — the
    # palace's slot must not claim Príncipe Real while another slot names it)
    pending = list(request.must_include)
    for field in ("activity", "location"):
        still = []
        for place in pending:
            hit = next(
                (
                    (day, slot)
                    for day, slot in visit_slots()
                    if _same_place(place.name, slot.get(field, ""))
                    and (field == "activity" or not slot.get("from_link"))
                ),
                None,
            )
            if hit:
                _mark(hit[1], place)
                linked_per_day[id(hit[0])] = linked_per_day.get(id(hit[0]), 0) + 1
                scheduled.append(place.name)
            else:
                still.append(place)
        pending = still

    for place in pending:
        candidates = _candidate_days(days, place, request)
        if not candidates:
            missing.append(place.name)
            continue
        # Arrival and departure days only when nothing else is in this city
        inner = [d for d in candidates if days.index(d) not in (0, last)]
        pool = [
            (day, slot)
            for day in (inner or candidates)
            for slot in slots_of(day)
            if not slot.get("from_link")
            and not _LOGISTICS.search(slot.get("activity", ""))
        ]
        if pool:
            day, slot = min(
                pool, key=lambda ds: _slot_rank(ds[0], ds[1], place, linked_per_day)
            )
            where = place.town or place.city or request.destination
            slot["activity"] = f"{place.name}" + (
                f" — {place.note}" if place.note else ""
            )
            slot["location"] = f"{place.name}, {where}"
            slot["duration_hours"] = _DURATION.get(place.kind, 2.0)
            slot.pop("notes", None)
            if place.lat is not None and place.lng is not None:
                slot["lat"], slot["lng"] = place.lat, place.lng
            _mark(slot, place)
            linked_per_day[id(day)] = linked_per_day.get(id(day), 0) + 1
            scheduled.append(place.name)
        else:
            day = min(inner or candidates, key=lambda d: linked_per_day.get(id(d), 0))
            day.setdefault("link_extras", []).append(
                {"name": place.name, "note": place.note, "quote": place.quote}
            )
            linked_per_day[id(day)] = linked_per_day.get(id(day), 0) + 1
            extras.append(place.name)

    itinerary["link_coverage"] = {
        "total": len(request.must_include),
        "scheduled": scheduled,
        "extras": extras,
        "missing": missing,
    }
    return itinerary
