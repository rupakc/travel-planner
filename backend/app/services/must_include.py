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
# Travel and hotel logistics: never matched as a place, never replaced.
# Checked on every day, not just the first and last.
_LOGISTICS = re.compile(
    r"\b(arriv\w*|depart\w*|check(?:ing)?[- ]?(?:in|into|out)|flights?|fly|flying|"
    r"airports?|transfers?|trains?|rail\w*|shinkansen|tgv|eurostar|intercity|"
    r"bus(?:es)?|coach|ferr(?:y|ies)|drive|driving|car hire|rental car|taxi|uber|"
    r"travel (?:from|to)|head(?:ing)? (?:to|back)|move on|pack\w*|luggage|"
    r"comboio|zug|tren|treno|autobus)\b|→|->",
    re.IGNORECASE,
)
_LOGISTICS_TYPES = {
    "transport",
    "transit",
    "travel",
    "transfer",
    "arrival",
    "departure",
    "check-in",
    "check-out",
    "checkin",
    "checkout",
    "logistics",
}
# Only these words are ignored when matching a place's name; every other
# token counts, however short ("Tram 28", "LX Factory", "Sé Cathedral")
_NAME_FILLER = frozenset(
    "the a an of and at in on de da do das dos di del della la le les el los "
    "las y e et und".split()
)
# A replaced slot keeps none of the old activity's money or links
_SLOT_STALE_FIELDS = (
    "estimated_cost_usd",
    "cost",
    "price_usd",
    "booking_url",
    "url",
    "link",
    "tickets",
    "transport",
    "transport_mode",
    "notes",
    "start_time",
    "end_time",
    "category",
    "type",
)


_POSSESSIVE = re.compile(r"(\w)['’]s\b")


def _tokens(text: str) -> list[str]:
    """Accent-folded word tokens; hyphens, spaces and apostrophes all split,
    a possessive 's is dropped ("Giolitti's" → giolitti), filler dropped."""
    text = _POSSESSIVE.sub(r"\1", text or "")
    return [
        t
        for t in re.split(r"[^a-z0-9]+", fold_place(text))
        if t and t not in _NAME_FILLER
    ]


def _same_place(name: str, text: str) -> bool:
    """``text`` names the place: the name's tokens appear as one contiguous,
    ordered phrase in ``text``. Spacing variants count only when they line up
    on whole tokens ("Senso-ji" ~ "Sensoji", "Time Out" ~ "TimeOut"), so
    "Tokyo Tower" is not "Tokyo Skytree … tallest tower" and "Ark Hills" is
    not "Park Hills"."""
    wanted = "".join(_tokens(name))
    if not wanted:
        return False
    have = _tokens(text)
    for i in range(len(have)):
        joined = ""
        for token in have[i:]:
            joined += token
            if joined == wanted:
                return True
            if not wanted.startswith(joined):
                break
    return False


# Arrival, departure and hotel logistics never stand for a place, even when a
# place's name appears in them ("transfer to Memmo Alfama Hotel")
_ARRIVAL = re.compile(
    r"\b(arriv\w*|depart\w*|check(?:ing)?[- ]?(?:in|into|out)|flights?|fly|"
    r"flying|airports?|pack\w*|luggage)\b|\btransfer\b.*\bhotel\b",
    re.IGNORECASE,
)
_ARRIVAL_TYPES = {
    "arrival",
    "departure",
    "check-in",
    "check-out",
    "checkin",
    "checkout",
}
_TRANSIT_SEPARATOR = re.compile(r"[–—⇒→]|->|\s-\s|\bto\b|\bvia\b", re.IGNORECASE)


def _names_two_stops(text: str, stop_cities: set[str]) -> bool:
    """ "Lisbon – Porto on the Alfa Pendular", "Tokyo ⇒ Kyoto": two of the
    trip's stops with a separator between them."""
    raw = text or ""
    spots = []
    for city in stop_cities:
        if not city:
            continue
        pattern = r"\s+".join(re.escape(w) for w in city.split())
        m = re.search(rf"(?<!\w){pattern}(?!\w)", fold_place(raw))
        if m:
            spots.append(m)
    spots.sort(key=lambda m: m.start())
    folded = fold_place(raw)
    # fold_place drops symbols like "⇒", so look at the raw text between the
    # two names too (folding keeps word order, so find them again there)
    for first, second in zip(spots, spots[1:]):
        if _TRANSIT_SEPARATOR.search(folded[first.end() : second.start()]):
            return True
        a = raw.lower().find(first.group(0).split()[0])
        b = raw.lower().find(second.group(0).split()[0], a + 1) if a >= 0 else -1
        if a >= 0 and b > a and _TRANSIT_SEPARATOR.search(raw[a:b]):
            return True
    return False


def _is_arrival(slot: dict) -> bool:
    kind = str(slot.get("category") or slot.get("type") or "").strip().lower()
    return kind in _ARRIVAL_TYPES or bool(_ARRIVAL.search(slot.get("activity", "")))


def _is_logistics(slot: dict, stop_cities: set[str]) -> bool:
    kind = str(slot.get("category") or slot.get("type") or "").strip().lower()
    if kind in _LOGISTICS_TYPES:
        return True
    text = f"{slot.get('activity', '')}"
    if _LOGISTICS.search(text):
        return True
    folded = fold_place(text)
    # "… to Porto": moving between the trip's own stops
    if any(re.search(rf"\bto {re.escape(c)}\b", folded) for c in stop_cities if c):
        return True
    return _names_two_stops(text, stop_cities)


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


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _drop_cost(day: dict, slot: dict) -> float:
    """Take a replaced slot's cost out of its day's total; returns it."""
    cost = slot.get("estimated_cost_usd")
    if not _is_number(cost):
        return 0.0
    if _is_number(day.get("daily_estimated_cost_usd")):
        day["daily_estimated_cost_usd"] = round(
            max(0.0, day["daily_estimated_cost_usd"] - cost), 2
        )
    return float(cost)


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
    stop_cities = {
        _city_key(c) for c in (request.destinations or [request.destination]) if c
    }
    multi = request.is_multi_city

    def logistics(slot):
        return _is_logistics(slot, stop_cities)

    def right_city(day, place):
        return not (multi and place.city) or _day_city(day, request) == _city_key(
            place.city
        )

    # Each stop's travel-in day (its first day after another city's) is kept
    # for arriving, like the trip's first and last days
    travel_in = {
        id(d)
        for i, d in enumerate(days)
        if i > 0 and _day_city(d, request) != _day_city(days[i - 1], request)
    }

    def slots_of(day):
        return [s for s in day.get("slots") or [] if isinstance(s, dict)]

    # Only this check decides what is "from your link" — never the model
    for day in days:
        for slot in slots_of(day):
            for key in _LINK_FIELDS:
                slot.pop(key, None)
        day.pop("link_extras", None)

    scheduled, extras, missing = [], [], []
    linked_per_day: dict[int, int] = {}

    def visit_slots(field):
        # Travel slots may name a place ("Train to Sintra for Pena Palace",
        # "Hop on Tram 28") by their activity text; arrival and hotel
        # logistics never do, and a travel slot's location never does
        return [
            (day, slot)
            for day in days
            for slot in slots_of(day)
            if not _is_arrival(slot) and (field == "activity" or not logistics(slot))
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
                    for day, slot in visit_slots(field)
                    if right_city(day, place)
                    and _same_place(place.name, slot.get(field, ""))
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

    removed_cost = 0.0
    # Slots first, notes after: the notes then land on the least busy day
    # whatever order the places came in, so a second pass changes nothing
    pending.sort(key=lambda p: p.kind == "transport")

    for place in pending:
        candidates = _candidate_days(days, place, request)
        if not candidates:
            missing.append(place.name)
            continue
        # Arrival and departure days only when nothing else is in this city
        inner = [
            d
            for d in candidates
            if days.index(d) not in (0, last) and id(d) not in travel_in
        ]
        inner = inner or [d for d in candidates if days.index(d) not in (0, last)]

        def pool_of(day_list):
            return [
                (day, slot)
                for day in day_list
                for slot in slots_of(day)
                if not slot.get("from_link") and not logistics(slot)
            ]

        # A transport place ("Tram 28") is a way of getting around, never a
        # slot of its own: unmatched, it becomes a note on one of its days
        if place.kind == "transport":
            pool = []
        else:
            pool = pool_of(inner) or pool_of(candidates)
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
            removed_cost += _drop_cost(day, slot)
            for key in _SLOT_STALE_FIELDS:
                slot.pop(key, None)
            slot["estimated_cost_usd"] = None
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

    total = itinerary.get("total_estimated_cost_usd")
    if removed_cost and _is_number(total):
        itinerary["total_estimated_cost_usd"] = round(max(0.0, total - removed_cost), 2)
    itinerary["link_coverage"] = {
        "total": len(request.must_include),
        "scheduled": scheduled,
        "extras": extras,
        "missing": missing,
    }
    return itinerary
