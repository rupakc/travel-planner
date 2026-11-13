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
from datetime import UTC, date, datetime

KINDS = ("plan", "recap", "savings", "quiz", "status")
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
# Keys that match the date regex by accident but carry no date.
_DATE_KEY_EXEMPT_RE = re.compile(r"^(time_of_day|duration)", re.IGNORECASE)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}.*)?$")
_ISO_ANY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_URL_DATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{8}|check[_-]?(?:in|out)|[?&#;](?:date|dep|ret|depart|"
    r"return|from|to|arrive)[a-z_]*=",
    re.IGNORECASE,
)
# Owner-private free text: never part of a new-style share, in any date mode
# (the sharer wrote these for themselves; they may name people, addresses or
# booking references).
_PRIVATE_KEYS = frozenset({"itinerary_notes", "itinerary_edits", "notes"})
_ORIGIN_KEYS = frozenset({"origin", "leg_from", "origin_airport", "origin_city"})
_RETURN_KEYS = frozenset({"return", "inbound", "return_flight", "return_leg"})
_RETURN_DEST_KEYS = frozenset({"destination", "to", "leg_to", "arrival_airport"})
_FLIGHTISH_KEYS = frozenset({"outbound", "return", "inbound", "leg_from", "airline"})
_DROP = object()


def _is_url(key, value: str) -> bool:
    return str(key).lower().endswith("url") or value.strip().lower().startswith(
        ("http://", "https://")
    )


def _scrub_str(key, value: str, mode: str, key_hit: bool):
    if _is_url(key, value):
        # Booking links embed travel dates (flt=JFK.NRT.2026-05-01, checkin=).
        if mode != "exact" and _URL_DATE_RE.search(value):
            return _DROP
        return value
    if mode == "exact":
        return value
    if _ISO_ANY_RE.search(value):
        if mode == "hidden":
            return _DROP
        if _ISO_RE.match(value.strip()):
            return _month(value) or _DROP
        return _ISO_ANY_RE.sub(lambda m: m.group(0)[:7], value)
    return _DROP if key_hit else value


def _scrub_value(key, value, mode: str, key_hit: bool, ctx: dict):
    if isinstance(value, str):
        return _scrub_str(key, value, mode, key_hit)
    if isinstance(value, dict):
        if key_hit and mode == "hidden":
            return {}
        return _scrub(value, mode, ctx, parent_key=str(key))
    if isinstance(value, list):
        out = [_scrub_value(key, v, mode, False, ctx) for v in value]
        return [v for v in out if v is not _DROP]
    if mode == "exact":
        return value
    return _DROP if key_hit else value


def _origin_key(key: str, parent_key: str, ctx: dict) -> bool:
    if ctx.get("show_origin"):
        return False
    k = str(key).lower()
    if k in _ORIGIN_KEYS:
        return True
    return k in _RETURN_DEST_KEYS and parent_key.lower() in _RETURN_KEYS


def _scrub(obj: dict, mode: str, ctx: dict, parent_key: str = "") -> dict:
    flightish = bool(_FLIGHTISH_KEYS & {str(k).lower() for k in obj})
    origin = ctx.get("origin")
    out = {}
    for key, value in obj.items():
        k = str(key).lower()
        if k in _PRIVATE_KEYS or _origin_key(k, parent_key, ctx):
            continue
        if (
            not ctx.get("show_origin")
            and flightish
            and k.endswith("url")
            and isinstance(value, str)
        ):
            continue  # flight links carry the origin airport code
        if (
            origin
            and isinstance(value, str)
            and k in ("leg_to", "destination", "to")
            and value.strip().casefold() == origin
        ):
            continue
        exempt = bool(_DATE_KEY_EXEMPT_RE.match(k))
        hit = bool(_DATE_KEY_RE.search(k)) and not exempt
        if hit and mode == "hidden":
            continue
        cleaned = _scrub_value(key, value, mode, hit, ctx)
        if cleaned is not _DROP:
            out[key] = cleaned
    return out


def scrub_selections(
    selections: dict,
    mode: str,
    *,
    show_origin: bool = True,
    origin: str | None = None,
) -> dict:
    """Selections made safe for a public new-style share.

    Always: owner-private free text (``itinerary_notes``, ``itinerary_edits``,
    any ``notes``) is removed. Without ``show_origin``: origin keys, a return
    leg's destination and flight links are removed in every date mode.
    ``hidden``/``month``: keys that look like dates or times go (not
    ``time_of_day`` or ``duration*``), URLs carrying dates go, and ISO dates
    inside any string are dropped (hidden) or cut to ``YYYY-MM`` (month);
    ``exact`` leaves dates alone."""
    ctx = {
        "show_origin": show_origin,
        "origin": origin.strip().casefold() if isinstance(origin, str) else None,
    }
    return _scrub(selections, mode if mode in ("hidden", "month") else "exact", ctx)


def _stamp(value, mode: str):
    """Timestamps reveal when the trip was planned: null when dates are hidden,
    ``YYYY-MM`` for month, as saved for exact."""
    if mode == "exact":
        return value
    return _month(value) if mode == "month" else None


def public_import_source(value) -> dict | None:
    """The "Inspired by" link of an imported trip: title and an http(s) URL."""
    if not isinstance(value, dict):
        return None
    url = value.get("url")
    if not (isinstance(url, str) and url.lower().startswith(("http://", "https://"))):
        url = None
    title = value.get("title") if isinstance(value.get("title"), str) else None
    return {"url": url, "title": title}


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
        "created_at": _stamp(plan.get("created_at"), opts["dates"]),
        "updated_at": _stamp(plan.get("updated_at"), opts["dates"]),
        "search_data": public,
        "selections": scrub_selections(
            plan.get("selections") or {},
            opts["dates"],
            show_origin=opts["show_origin"],
            origin=search.get("origin"),
        ),
    }
    imp = public_import_source(search.get("import_source"))
    if imp:
        public["import_source"] = imp
    return out


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


HEADLINE_MAX = 120


def clip_headline(text: str, limit: int = HEADLINE_MAX) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def savings_card(summary: dict) -> dict:
    total = float(summary.get("total_usd") or 0)
    drops = int(summary.get("drops_caught") or 0)
    return {
        "headline": (
            f"Caught drops worth {_money(total)}"
            if total > 0
            else "Watching prices for my next trip"
        ),
        "hl": {"total_usd": total},
        "stats": [
            s
            for s in (
                {"key": "drops_caught", "count": drops},
                {"key": "targets_hit", "count": int(summary.get("targets_hit") or 0)},
            )
            if s["count"] > 0
        ],
    }


QUIZ_PACK_LABELS = {
    "flags": "Flags",
    "capitals": "Capitals",
    "landmarks": "Landmarks",
    "cuisine": "Cuisine",
}


def quiz_card(session: dict) -> dict:
    """Pack and correct-out-of-total only: never time, points or answers."""
    total = len(session.get("questions") or [])
    correct = max(0, min(int(session.get("correct") or 0), total))
    if session.get("mode") == "daily":
        label = "Daily quiz"
    else:
        label = QUIZ_PACK_LABELS.get(session.get("pack"))
        label = f"{label} quiz" if label else "Quiz"
    return {
        "hl": {
            "mode": session.get("mode"),
            "pack": session.get("pack"),
            "correct": correct,
            "total": total,
        },
        "headline": f"{label}: {correct}/{total}" if total else label,
        "stats": [{"key": "correct", "count": correct}] if correct else [],
    }


def status_card(plan: dict, today: date) -> dict:
    """ "Day N in Place" from server data; no dates, origin or other trip detail."""
    from .trip_phase import day_index, trip_dates

    search = plan.get("search_data") or {}
    dests = _destinations(search)
    place = " / ".join(dests) if dests else None
    start, end = trip_dates(plan)
    day = day_index(start, end, today)
    if day and place:
        head = f"Day {day} in {place}"
    elif place:
        head = f"On a trip in {place}"
    else:
        head = "On a trip"
    return {
        "headline": clip_headline(head),
        "destination": place,
        "hl": {"day": day or None},
    }


def build_snapshot(
    kind: str,
    options: dict | None,
    *,
    plan: dict | None = None,
    savings: dict | None = None,
    quiz: dict | None = None,
    today: date | None = None,
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
        # Structured headline inputs so the card can re-word the headline in
        # another language (never shown by the API; the card renderer only).
        "hl": {},
    }
    if kind == "savings":
        card = savings_card(savings or {})
        snap.update(
            title="Price alerts",
            headline=card["headline"],
            stats=card["stats"],
            hl=card["hl"],
        )
        return snap
    if kind == "quiz":
        card = quiz_card(quiz or {})
        snap.update(
            title="Quiz",
            headline=card["headline"],
            stats=card["stats"],
            hl=card["hl"],
        )
        return snap
    if kind == "status":
        card = status_card(plan or {}, today or datetime.now(UTC).date())
        snap.update(
            title="Trip status",
            headline=card["headline"],
            destination=card["destination"],
            hl=card["hl"],
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
    snap["headline"] = clip_headline(snap["headline"])
    snap["stats"] = _stats(kind, selections)
    if opts["dates"] != "hidden":
        snap["period"] = _month(search.get("departure_date"))
    if opts["show_origin"] and isinstance(search.get("origin"), str):
        snap["origin"] = search["origin"][:80]
    return snap
