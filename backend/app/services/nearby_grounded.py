"""Near Me v2: places to see / eat / shop / stay around a coordinate, from
one Gemini call grounded with Google Maps.

The model answers in lines ``GROUP|Place name|why``; every item must match a
Maps grounding chunk, whose title, link and place id it takes — a place the
model names without a Maps chunk is dropped, so nothing is invented. Pure
helpers (no network); the route makes the call.

Google's Maps grounding terms: results go only to the user who asked, are
never cached or stored (only ``place_id`` could be), and each item keeps its
Maps link and the "Google Maps" attribution (docs/Trip-Planning-Features.md,
"Live web check and Near me").
"""

import re

from ..core.places import fold_place

SECTIONS = (
    ("see", "Places to see", "sights, landmarks, museums, parks and viewpoints"),
    ("eat", "Places to eat", "restaurants, cafés, bakeries and food markets"),
    ("shop", "Places to shop", "shops, markets, malls and local crafts"),
    ("stay", "Places to stay", "hotels, guesthouses and other places to stay"),
)
_IDS = {sid for sid, _, _ in SECTIONS}
_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?P<group>[A-Za-z]+)\s*\|\s*(?P<name>[^|]*?)\s*"
    r"(?:\|\s*(?P<why>.*?)\s*)?$"
)
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
    """(system, prompt) for one Maps-grounded call covering all four groups."""
    system = (
        f"Today is {today}. You recommend real places near a traveller using "
        "Google Maps. Only name places that Google Maps returns, spelled "
        "exactly as on Google Maps."
    )
    groups = "\n".join(f"{sid.upper()}: {hint}" for sid, _, hint in SECTIONS)
    likes = ", ".join(i for i in interests if i)[:300]
    prompt = (
        f"The traveller is at latitude {lat:.5f}, longitude {lng:.5f}, near "
        f"{label}. Find places near them in these groups:\n{groups}\n\n"
        f"List up to {limit} places per group, the best-rated close by first."
        + (f" They enjoy: {likes}." if likes else "")
        + "\n\nAnswer only with lines in this exact format, one place per "
        "line, no other text:\nGROUP|Exact place name as on Google Maps|One "
        "short sentence on why it is worth a visit\nGROUP is one of SEE, EAT, "
        "SHOP, STAY."
    )
    return system, prompt


def _clean(text: str) -> str:
    return re.sub(r"[*_`]+", "", text or "").strip()


def _place_id(raw) -> str | None:
    """ "places/ChIJ…" → "ChIJ…" (the id the Places API and Maps URLs use)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip().removeprefix("places/") or None


def _maps_chunks(chunks: list[dict]) -> list[dict]:
    """Maps chunks with a link, once per link, in the model's order."""
    out, seen = [], set()
    for c in chunks:
        uri = c.get("uri")
        if c.get("kind") != "maps" or not isinstance(uri, str):
            continue
        if not uri.startswith(("https://", "http://")) or uri in seen:
            continue
        seen.add(uri)
        out.append(c)
    return out


def _match(name: str, candidates: list[dict], used: set[str]) -> dict | None:
    """The chunk this name refers to: an exact (folded) title first, else the
    closest title containing it or contained in it."""
    folded = fold_place(name)
    if not folded:
        return None
    free = [c for c in candidates if c["uri"] not in used]
    for c in free:
        if fold_place(c["title"]) == folded:
            return c
    if len(folded) < _MIN_PARTIAL:
        return None
    best, best_gap = None, None
    for c in free:
        title = fold_place(c["title"])
        if len(title) < _MIN_PARTIAL or not (folded in title or title in folded):
            continue
        gap = abs(len(title) - len(folded))
        if best_gap is None or gap < best_gap:
            best, best_gap = c, gap
    return best


def parse_sections(
    text: str, chunks: list[dict], limit: int
) -> tuple[list[dict], list[dict]]:
    """(sections, sources) from the grounded answer: four sections in a
    fixed order (each possibly empty, at most ``limit`` items), and every
    Maps chunk with a link as ``{"title", "uri"}``."""
    candidates = _maps_chunks(chunks)
    items: dict[str, list[dict]] = {sid: [] for sid in _IDS}
    used: set[str] = set()
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        group = m["group"].lower()
        name = _clean(m["name"])
        if group not in _IDS or not name or len(items[group]) >= limit:
            continue
        chunk = _match(name, candidates, used)
        if chunk is None:
            continue
        used.add(chunk["uri"])
        items[group].append(
            {
                "name": chunk["title"] or name,
                "summary": _clean(m["why"] or "")[:_MAX_SUMMARY],
                "maps_uri": chunk["uri"],
                "place_id": _place_id(chunk.get("place_id")),
                "category": group,
            }
        )
    sections = [
        {"id": sid, "title": title, "items": items[sid]} for sid, title, _ in SECTIONS
    ]
    sources = [{"title": c["title"], "uri": c["uri"]} for c in candidates]
    return sections, sources
