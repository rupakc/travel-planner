"""Idea snapshots (Phase 5): what a plan or recap shows on the public feed.

Built from the same whitelist and privacy defaults as a share (dates hidden,
origin and name off, owner-private notes dropped) and then cut down to
destinations, trip length, interest tags, counts and the names of the
selected items. No prices, links, dates, origin, name or email. Pure.
"""

import re

from . import moderation, share_public
from .feed_rank import interest_tokens

SNAPSHOT_MAX_BYTES = 64 * 1024
ITEM_KEYS = ("activities", "places_to_see", "hotels", "walking_tours", "events")
MAX_ITEMS = 25
NAME_MAX = 80
_NAME_FIELDS = ("name", "title", "hotel_name", "place_name")
_DATEY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _name(item) -> str | None:
    if isinstance(item, str):
        raw = item
    elif isinstance(item, dict):
        raw = next((item[k] for k in _NAME_FIELDS if isinstance(item.get(k), str)), "")
    else:
        return None
    name = moderation.plain_text(raw, NAME_MAX)
    if not name or _DATEY.search(name) or "@" in name:
        return None
    return name


def _items(selections: dict, key: str) -> list[dict]:
    value = selections.get(key)
    if key == "hotels" and not value:
        value = selections.get("hotel")
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    names = [_name(v) for v in value]
    return [{"name": n} for n in names if n][:MAX_ITEMS]


def build(plan: dict, kind: str) -> dict:
    """The snapshot dict for ``plan`` (a plans_db row)."""
    search = plan.get("search_data") or {}
    clean = share_public.scrub_selections(
        plan.get("selections") or {},
        "hidden",
        show_origin=False,
        origin=search.get("origin"),
    )
    origin = str(search.get("origin") or "").strip().casefold()
    dests = [
        moderation.plain_text(d, NAME_MAX)
        for d in share_public._destinations(search)
        if str(d).strip().casefold() != origin
    ]
    items = {k: v for k in ITEM_KEYS if (v := _items(clean, k))}
    return {
        "v": 1,
        "kind": kind,
        "destinations": [d for d in dests if d][:5],
        "days": share_public._trip_days(search, clean),
        "interests": interest_tokens(search.get("interests")),
        "stats": share_public._stats("recap" if kind == "recap" else "plan", clean),
        "items": items,
    }


def to_plan(
    title: str, snapshot: dict, idea_id: int, handle: str
) -> tuple[str, dict, dict]:
    """Remix: ``(name, search_data, selections)`` for a new plan in the
    saver's account. Only whitelisted snapshot fields are copied; the source
    is noted as ``search_data.remix_of`` (never part of a public share)."""
    dests = list(snapshot.get("destinations") or [])
    search = {
        "destination": dests[0] if dests else "",
        "destinations": dests if len(dests) > 1 else [],
        "interests": list(snapshot.get("interests") or []),
        "remix_of": {"idea_id": idea_id, "handle": handle},
    }
    selections = {
        k: [{"name": i["name"]} for i in v]
        for k, v in (snapshot.get("items") or {}).items()
        if k in ITEM_KEYS
    }
    return moderation.plain_text(title, NAME_MAX), search, selections
