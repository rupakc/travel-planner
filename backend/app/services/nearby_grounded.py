"""Near Me v2: places to see / eat / shop / stay around a coordinate, from
one Gemini call grounded with Google Maps.

The model answers in natural text: a heading per group (``## See`` …) and
one place per line (``Name - why``). Google attaches Maps grounding chunks to
answers in that shape (a rigid ``GROUP|name|why`` format came back with no
chunks in 7 of 8 real calls). Every item must map to a Maps grounding chunk
whose title matches its name (chunks its grounding supports cite are tried
first) and takes the chunk's title, link and place id; a place without one
is dropped, so nothing is invented or mislabelled. Pure helpers (no network); the route makes the call.

Google's Maps grounding terms: results go only to the user who asked, are
never cached or stored (only ``place_id`` could be), and each item keeps its
Maps link and the "Google Maps" attribution (docs/Trip-Planning-Features.md,
"Live web check and Near me").
"""

import re

from ..core.places import fold_place

SECTIONS = (
    ("see", "Places to see", "See", "sights, landmarks, museums, parks"),
    ("eat", "Places to eat", "Eat", "restaurants, cafés"),
    ("shop", "Places to shop", "Shop", "shops, markets"),
    ("stay", "Places to stay", "Stay", "hotels"),
)
_IDS = {sid for sid, *_ in SECTIONS}
# Maps chunk titles read "Cafe Portugal - Google Maps"
_TITLE_SUFFIX = re.compile(r"\s*[-–—|]\s*Google Maps\s*$", re.IGNORECASE)
_REVIEW_PREFIX = re.compile(r"^Review of\s+", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]+|\d{1,2}[.)])\s*")
_SEPARATORS = (" - ", " – ", " — ", ":")
# A folded name shorter than this must equal a chunk title exactly ("Bar"
# would otherwise match any "… Bar")
_MIN_PARTIAL = 6
_MAX_SUMMARY = 200


def build_prompt(
    label: str,
    lat: float,
    lng: float,
    limit: int,
    interests: list[str],
    *,
    today: str,
) -> tuple[str, str]:
    """(system, prompt) for one Maps-grounded call covering all four groups.
    The location itself goes to Maps as ``lat_lng`` (retrieval config)."""
    system = f"Today is {today}."
    groups = ", ".join(f"'## {head}' ({hint})" for _, _, head, hint in SECTIONS)
    likes = ", ".join(i for i in interests if i)[:300]
    prompt = (
        f"Recommend good places near me (I'm near {label}) in four groups, "
        f"each under its own heading line: {groups}. Under each heading list "
        f"up to {limit} places, one per line: the exact Google Maps name, then "
        "' - ' and one short sentence on why it is worth a visit."
        + (f" I enjoy: {likes}." if likes else "")
    )
    return system, prompt


def _clean(text: str) -> str:
    return re.sub(r"[*_`]+", "", text or "").strip()


def clean_title(title: str) -> str:
    """A Maps chunk title without Google's " - Google Maps" suffix, or the
    "Review of " prefix of a chunk that links to a review of the place."""
    title = _TITLE_SUFFIX.sub("", (title or "").strip()).strip()
    return _REVIEW_PREFIX.sub("", title).strip()


def _trim_summary(why: str, name: str, title: str) -> str:
    """Drop the part of a title the line split into its summary: "Isla &
    Co. - Midtown - Trendy brunch" → name "Isla & Co.", summary "Midtown -
    Trendy brunch"; the item is titled "Isla & Co. - Midtown", so the
    summary becomes "Trendy brunch"."""
    if not name or not title.lower().startswith(name.lower()):
        return why
    extra = title[len(name) :].strip(" -–—:")
    if extra and why.lower().startswith(extra.lower()):
        return why[len(extra) :].lstrip(" -–—:").strip()
    return why


def _place_id(raw) -> str | None:
    """ "places/ChIJ…" → "ChIJ…" (the id the Places API and Maps URLs use)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip().removeprefix("places/") or None


def _heading(line: str) -> str | None:
    """The section id a heading line names ("## See", "**Eat:**", "Shop",
    "Places to stay"), else None."""
    text = _clean(line.strip().lstrip("#").strip()).rstrip(":").strip().lower()
    text = text.removeprefix("places to ").strip()
    return text if text in _IDS else None


def _split(line: str) -> tuple[str, str]:
    """(name, why) of an item line: split on the first separator."""
    body = _clean(_BULLET.sub("", line, count=1))
    cuts = [(body.find(s), s) for s in _SEPARATORS if body.find(s) > 0]
    if not cuts:
        return body.strip(), ""
    at, sep = min(cuts)
    return body[:at].strip(), body[at + len(sep) :].strip()


def _maps_chunks(chunks: list[dict]) -> dict[int, dict]:
    """Maps chunks with a link, by their index in ``chunks`` (supports refer
    to that index), once per link, titles cleaned."""
    out: dict[int, dict] = {}
    seen: set[str] = set()
    for i, c in enumerate(chunks):
        uri = c.get("uri")
        if c.get("kind") != "maps" or not isinstance(uri, str):
            continue
        if not uri.startswith(("https://", "http://")) or uri in seen:
            continue
        seen.add(uri)
        out[i] = {**c, "title": clean_title(c.get("title") or "")}
    return out


def _title_match(folded: str, candidates: list[dict]) -> dict | None:
    """An exact (folded) title first, else the closest title containing the
    name or contained in it as whole words, the shorter at least 6
    characters and half the longer ("Time Out Market" ↔ "Time Out Market
    Lisboa"; never "Lisbon" ↔ "Lisbon Cathedral Cloister Ruins")."""
    for c in candidates:
        if fold_place(c["title"]) == folded:
            return c
    if len(folded) < _MIN_PARTIAL:
        return None
    best, best_gap = None, None
    for c in candidates:
        title = fold_place(c["title"])
        short, long_ = sorted((title, folded), key=len)
        if (
            len(short) < _MIN_PARTIAL
            or len(short) * 2 < len(long_)
            or f" {short} " not in f" {long_} "
        ):
            continue
        gap = abs(len(title) - len(folded))
        if best_gap is None or gap < best_gap:
            best, best_gap = c, gap
    return best


def _match(
    name: str,
    line: str,
    maps: dict[int, dict],
    supports: list[dict],
    used: set[str],
) -> dict | None:
    """The chunk an item line refers to, or None (the line is dropped).

    A chunk is only ever taken when its cleaned title matches the line's
    name (``_title_match``: folded exact, or containment either way for
    names of 6+ characters). Supports only set the order: chunks a support
    covering this line cites are tried first, then every other chunk. A
    support's chunk is never taken on the support alone — real answers
    cite neighbouring places' chunks ("Carmo Convent" backed by the Time Out
    Market chunk), and a wrong name and link on a card is worse than none."""
    folded = fold_place(name)
    if not folded:
        return None
    flat = fold_place(_clean(line))
    for s in supports:
        seg = fold_place(_clean(s.get("text") or ""))
        if not seg or not (seg == folded or seg in flat or folded in seg):
            continue
        backing = [
            maps[i]
            for i in s.get("chunks") or []
            if i in maps and maps[i]["uri"] not in used
        ]
        hit = _title_match(folded, backing)
        if hit is not None:
            return hit
    free = [c for c in maps.values() if c["uri"] not in used]
    return _title_match(folded, free)


def maps_chunk_count(chunks: list[dict]) -> int:
    return len(_maps_chunks(chunks))


def parse_sections(
    text: str, chunks: list[dict], limit: int, supports: list[dict] | None = None
) -> tuple[list[dict], list[dict]]:
    """(sections, sources) from the grounded answer: four sections in a
    fixed order (each possibly empty, at most ``limit`` items), and every
    Maps chunk with a link as ``{"title", "uri"}``."""
    maps = _maps_chunks(chunks)
    supports = supports or []
    items: dict[str, list[dict]] = {sid: [] for sid in _IDS}
    used: set[str] = set()
    places: set[str] = set()
    section = None
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        heading = _heading(line)
        if heading:
            section = heading
            continue
        if section is None or len(items[section]) >= limit:
            continue
        name, why = _split(line)
        if not name:
            continue
        chunk = _match(name, line, maps, supports, used)
        if chunk is None:
            continue
        used.add(chunk["uri"])
        # one card per place: a review chunk (or a second chunk) of a place
        # already listed is skipped
        place = _place_id(chunk.get("place_id")) or fold_place(chunk["title"])
        if place in places:
            continue
        places.add(place)
        title = chunk["title"] or name
        items[section].append(
            {
                "name": title,
                "summary": _trim_summary(why, name, title)[:_MAX_SUMMARY],
                "maps_uri": chunk["uri"],
                "place_id": _place_id(chunk.get("place_id")),
                "category": section,
            }
        )
    sections = [
        {"id": sid, "title": title, "items": items[sid]} for sid, title, *_ in SECTIONS
    ]
    sources = [{"title": c["title"], "uri": c["uri"]} for c in maps.values()]
    return sections, sources
