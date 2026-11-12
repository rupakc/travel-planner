"""Public share snapshots (Phase 4). Pure: no network, DB or LLM calls.

Two outputs, both built from whitelists so nothing private can leak:

* :func:`sanitize_plan` - the JSON a public ``GET /api/share/{token}`` returns
  for a plan (legacy shape plus ``kind``/``options``/``owner_name``), with the
  sharer's date, origin and name choices applied.
* :func:`build_snapshot` - the small dict the card renderer and the OG page
  draw from. It never carries exact dates: at most ``period`` (``YYYY-MM``).
"""

from __future__ import annotations

import re
from datetime import date

KINDS = ("plan", "recap", "savings")
DATE_MODES = ("hidden", "month", "exact")
DEFAULT_OPTIONS = {"dates": "hidden", "show_origin": False, "show_name": False}

# search_data fields safe to expose on a public share link. Personal fields
# (nationality, visas, permits, accessibility) are never listed.
PUBLIC_SEARCH_FIELDS = (
    "origin",
    "destination",
    "destinations",
    "departure_date",
    "return_date",
    "interests",
    "num_travelers",
    "adults",
    "children",
    "seniors",
    "infants",
    "pace",
)

_STAT_SOURCES = {
    "plan": (
        ("activities", "activities"),
        ("hotels", "hotels"),
        ("places", "places_to_see"),
    ),
    "recap": (("places", "places_to_see"), ("activities", "activities")),
}
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})")


def normalize_options(raw: dict | None) -> dict:
    """Options with defaults filled and junk values replaced by the private default."""
    raw = raw or {}
    dates = raw.get("dates")
    return {
        "dates": dates if dates in DATE_MODES else "hidden",
        "show_origin": raw.get("show_origin") is True,
        "show_name": raw.get("show_name") is True,
    }


def owner_display_name(user: dict | None, options: dict) -> str | None:
    """The sharer's name, only with ``show_name``. Never the email."""
    if not user or not options.get("show_name"):
        return None
    name = (user.get("display_name") or "").strip() or (user.get("username") or "")
    name = name.strip()
    if "@" in name:  # a username that is an email must not leak it
        return None
    return name[:80] or None


def _month(value) -> str | None:
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value)
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return f"{m.group(1)}-{m.group(2)}"


def _day(value) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _destinations(search: dict) -> list[str]:
    raw = search.get("destinations")
    names = (
        [d for d in raw if isinstance(d, str) and d.strip()]
        if isinstance(raw, list)
        else []
    )
    if not names and isinstance(search.get("destination"), str):
        names = [search["destination"]]
    return [n.strip()[:80] for n in names if n.strip()][:5]


def _trip_days(search: dict, selections: dict) -> int | None:
    start, end = _day(search.get("departure_date")), _day(search.get("return_date"))
    if start and end and end >= start:
        return (end - start).days + 1
    itinerary = selections.get("itinerary")
    days = itinerary.get("days") if isinstance(itinerary, dict) else None
    return len(days) if isinstance(days, list) and days else None


def _count(selections: dict, src: str) -> int:
    value = selections.get(src)
    if src == "hotels" and not value:
        value = selections.get("hotel")
    if isinstance(value, list):
        return len(value)
    return 1 if isinstance(value, dict) and value else 0


def _stats(kind: str, selections: dict) -> list[dict]:
    stats = [
        {"key": key, "count": _count(selections, src)}
        for key, src in _STAT_SOURCES[kind]
    ]
    return [s for s in stats if s["count"] > 0][:3]


_DATE_KEY_RE = re.compile(
    r"date|time|departure|arrival|check[_-]?in|check[_-]?out", re.IGNORECASE
)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}.*)?$")
_DROP = object()


def _scrub_value(value, mode: str, key_hit: bool):
    if isinstance(value, str):
        if _ISO_RE.match(value.strip()):
            return _DROP if mode == "hidden" else (_month(value) or _DROP)
        return _DROP if key_hit else value
    if isinstance(value, dict):
        return {} if key_hit and mode == "hidden" else _scrub(value, mode)
    if isinstance(value, list):
        out = [_scrub_value(v, mode, False) for v in value]
        return [v for v in out if v is not _DROP]
    return _DROP if key_hit else value


def _scrub(obj: dict, mode: str) -> dict:
    out = {}
    for key, value in obj.items():
        hit = bool(_DATE_KEY_RE.search(str(key)))
        if hit and mode == "hidden":
            continue
        cleaned = _scrub_value(value, mode, hit)
        if cleaned is not _DROP:
            out[key] = cleaned
    return out


def scrub_selections(selections: dict, mode: str) -> dict:
    """Selections with dates removed (``hidden``) or cut to ``YYYY-MM``
    (``month``); ``exact`` returns them unchanged. Keys that look like dates or
    times go, and so does any ISO date or datetime string value."""
    if mode == "exact":
        return selections
    return _scrub(selections, "month" if mode == "month" else "hidden")


def sanitize_plan(plan: dict, options: dict | None, owner_name: str | None) -> dict:
    """Public JSON of a plan share: legacy keys with the options applied."""
    opts = normalize_options(options)
    search = plan.get("search_data") or {}
    public = {k: v for k, v in search.items() if k in PUBLIC_SEARCH_FIELDS}
    if opts["dates"] == "hidden":
        public.pop("departure_date", None)
        public.pop("return_date", None)
    elif opts["dates"] == "month":
        for key in ("departure_date", "return_date"):
            if key in public:
                month = _month(public[key])
                if month:
                    public[key] = month
                else:
                    public.pop(key)
    if not opts["show_origin"]:
        public.pop("origin", None)
    out = {
        "name": plan.get("name"),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "search_data": public,
        "selections": scrub_selections(plan.get("selections") or {}, opts["dates"]),
    }
    return out


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def savings_card(summary: dict) -> dict:
    total = float(summary.get("total_usd") or 0)
    drops = int(summary.get("drops_caught") or 0)
    return {
        "headline": (
            f"Caught drops worth {_money(total)}"
            if total > 0
            else "Watching prices for my next trip"
        ),
        "stats": [
            {"key": "drops_caught", "count": drops},
            {"key": "targets_hit", "count": int(summary.get("targets_hit") or 0)},
        ],
    }


def build_snapshot(
    kind: str,
    options: dict | None,
    *,
    plan: dict | None = None,
    savings: dict | None = None,
    owner_name: str | None = None,
) -> dict:
    """What a card or OG page may show. ``owner_name`` must already respect
    ``show_name`` (see :func:`owner_display_name`)."""
    opts = normalize_options(options)
    snap: dict = {
        "kind": kind,
        "title": None,
        "headline": "",
        "destination": None,
        "destinations": [],
        "days": None,
        "period": None,
        "origin": None,
        "owner_name": owner_name if opts["show_name"] else None,
        "stats": [],
    }
    if kind == "savings":
        card = savings_card(savings or {})
        snap.update(
            title="Price alerts", headline=card["headline"], stats=card["stats"]
        )
        return snap
    plan = plan or {}
    search = plan.get("search_data") or {}
    selections = plan.get("selections") or {}
    dests = _destinations(search)
    place = " / ".join(dests) if dests else None
    days = _trip_days(search, selections)
    snap.update(
        title=plan.get("name"),
        destinations=dests,
        destination=place,
        days=days,
    )
    if kind == "recap":
        snap["headline"] = f"My trip to {place}: recap" if place else "My trip: recap"
    elif place and days:
        snap["headline"] = f"{days} day{'s' if days != 1 else ''} in {place}"
    elif place:
        snap["headline"] = f"Trip to {place}"
    else:
        snap["headline"] = str(plan.get("name") or "My trip")
    snap["stats"] = _stats(kind, selections)
    if opts["dates"] != "hidden":
        snap["period"] = _month(search.get("departure_date"))
    if opts["show_origin"] and isinstance(search.get("origin"), str):
        snap["origin"] = search["origin"][:80]
    return snap
