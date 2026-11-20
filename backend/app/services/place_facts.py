"""Place facts for the Results page: the ``facts`` section (docs/Place-Facts.md).

One section per search, covering every destination (each city of a
multi-city trip), its state/region and its country, in five groups:
``historical``, ``fun``, ``popular``, ``unbelievable`` and ``little_known``.

* **Places come from our own place data.** ``resolve_place`` gives the city's
  GeoNames id (the crawler's join key), its first-level division and its
  country; nothing is resolved by a model.
* **Crawler first.** When the crawler answers ``GET /v1/facts``, its facts are
  streamed at once (Phase 0), each with its own source (name, link, as-of,
  licence, attribution) and ``origin``/``source`` ``"crawler"``.
* **AI fills only empty groups.** The ``place_facts`` agent adds facts from
  model knowledge for groups the crawler left empty; every such fact is
  ``origin: "ai"``, ``verified: false`` and carries **no** source or link (a
  model never gets to invent one). If the agent fails, the crawler facts stay.
* **Licence rules** (``docs/Crawler-Data.md``): only open / api_terms facts
  whose record says ``llm_ok`` (not share-alike, not a Wikipedia hook, not an
  AI-blocked source, not in conflict) are given to the model, wrapped as
  untrusted reference data. Share-alike hooks are shown as written, as a
  quote with their attribution, never merged into our wording.

Pure helpers except :func:`crawler_facts_for`, which calls the crawler client
(never raises, ``None`` when the crawler is off or did not answer).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass

from ..core.places import fold_place
from . import crawler_client
from .crawler_facts import country_for_place, country_name, reference_block

logger = logging.getLogger(__name__)

FACT_TYPES = crawler_client.FACT_TYPES
SECTION = "facts"
# Crawler facts kept per group and place; AI facts per empty group and place
CRAWLER_PER_GROUP = 4
AI_PER_GROUP = 3
AI_PER_GROUP_MULTI = 2
MAX_DESTINATIONS = 4
MAX_TEXT = 280
_MERGEABLE = {"open", "api_terms"}
_CONFIDENCE_RANK = {"corroborated": 0, "structured": 1, "extracted": 2}
_URL_RE = re.compile(r"^https?://\S+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_LINKISH = re.compile(r"https?://|www\.", re.IGNORECASE)


@dataclass(frozen=True)
class Scope:
    """One place the section covers."""

    key: str  # "city:2950159", "place:bali", "region:DE.16", "country:DE"
    scope: str  # city | place | region | country
    name: str
    country: str | None  # ISO 3166-1 alpha-2
    destination: str  # the typed destination this place belongs to
    geonames_id: int | None = None

    def public(self) -> dict:
        return {
            "key": self.key,
            "scope": self.scope,
            "name": self.name,
            "country": self.country,
            "country_name": country_name(self.country) if self.country else None,
            "destination": self.destination,
            "geonames_id": self.geonames_id,
        }


# ── places ───────────────────────────────────────────────────────────────


def _admin1_name(country: str, admin1: str | None) -> str | None:
    if not country or not admin1:
        return None
    try:
        from ..db.database import get_connection

        with get_connection() as conn:
            row = conn.execute(
                "SELECT name FROM admin1 WHERE code = ?", (f"{country}.{admin1}",)
            ).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception as e:  # never break the section over a lookup
        logger.debug("admin1 lookup %s.%s failed: %s", country, admin1, e)
        return None


def _typed_name(text: str) -> str:
    head = (text or "").split(",")[0].strip()
    # "BER — Berlin, Germany" → "Berlin"
    if "—" in head:
        head = head.split("—")[-1].strip()
    return head or (text or "").strip()


def _same_place(region: str, city: str) -> bool:
    """ "State of Berlin" for Berlin, "Tokyo" for Tokyo: one place, one entry."""
    r, c = fold_place(region), fold_place(city)
    return bool(c) and (r == c or f" {c} " in f" {r} ")


def destinations_of(request) -> list[str]:
    places = [p for p in (request.destinations or []) if p and p.strip()]
    if not places:
        places = [request.destination]
    out: list[str] = []
    for p in places:
        if p not in out:
            out.append(p)
    return out[:MAX_DESTINATIONS]


def scopes_for(request) -> list[Scope]:
    """City (or destination), region and country of every destination, in
    trip order, without repeats (two cities in one country share it)."""
    from ..db.places_db import resolve_place

    out: list[Scope] = []
    seen: set[str] = set()

    def add(s: Scope) -> None:
        if s.key not in seen and s.name:
            seen.add(s.key)
            out.append(s)

    for dest in destinations_of(request):
        try:
            place = resolve_place(dest)
        except Exception as e:
            logger.debug("resolve_place(%r) failed: %s", dest, e)
            place = None
        cc = (
            place.country_code.upper()
            if place and place.country_code
            else country_for_place(dest)
        )
        region = None
        city_name = ""
        if place and place.division:
            region = _admin1_name(cc, place.admin1) or place.name
        elif place and place.geonameid:
            add(
                Scope(
                    key=f"city:{place.geonameid}",
                    scope="city",
                    name=place.name,
                    country=cc,
                    destination=dest,
                    geonames_id=place.geonameid,
                )
            )
            region = _admin1_name(cc, place.admin1)
            city_name = place.name
        else:
            name = place.name if place else _typed_name(dest)
            if name and (not cc or fold_place(name) != fold_place(country_name(cc))):
                add(
                    Scope(
                        key=f"place:{fold_place(name)}",
                        scope="place",
                        name=name,
                        country=cc,
                        destination=dest,
                    )
                )
            city_name = name
        if region and cc and not _same_place(region, city_name):
            code = place.admin1 if place and place.admin1 else fold_place(region)
            add(
                Scope(
                    key=f"region:{cc}.{code}",
                    scope="region",
                    name=region,
                    country=cc,
                    destination=dest,
                )
            )
        if cc:
            add(
                Scope(
                    key=f"country:{cc}",
                    scope="country",
                    name=country_name(cc),
                    country=cc,
                    destination=dest,
                )
            )
    return out


# ── crawler facts ────────────────────────────────────────────────────────


def _url(value) -> str | None:
    return value if isinstance(value, str) and _URL_RE.match(value) else None


def _day(value) -> str | None:
    return value[:10] if isinstance(value, str) and _DATE_RE.match(value) else None


def _str(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _citation(item: dict) -> dict:
    src = item.get("source") if isinstance(item.get("source"), dict) else {}
    lic = item.get("licence") if isinstance(item.get("licence"), dict) else {}
    return {
        "source_id": _str(src.get("source_id")),
        "name": _str(src.get("name")) or _str(src.get("publisher")),
        "publisher": _str(src.get("publisher")),
        "url": _url(src.get("url")) or _url(item.get("source_url")),
        "as_of": _day(item.get("as_of")) or _day(item.get("updated_at")),
        "licence": _str(lic.get("class")),
        "attribution": _str(lic.get("attribution")),
        "licence_url": _url(lic.get("url")),
        "conflict": bool(item.get("conflict")),
    }


def _text_for(item: dict, locale: str) -> tuple[str | None, bool]:
    """The fact's text for ``locale`` and whether it is a machine
    translation: the text in the reader's language, else the ingest-time
    English translation, else English text; other languages are skipped."""
    lang = (_str(item.get("lang")) or "").lower().split("-")[0]
    text = _str(item.get("text"))
    text_en = _str(item.get("text_en"))
    if text and lang == locale:
        return text, False
    if text_en and lang != "en":
        return text_en, True
    if text and lang == "en":
        return text, False
    return None, False


def crawler_fact(item: dict, locale: str = "en") -> dict | None:
    """One ``/v1/facts`` item as a section fact, or None when it is unusable
    (unknown group, no text in a language we show, no source name)."""
    if not isinstance(item, dict):
        return None
    ftype = item.get("fact_type")
    if ftype not in FACT_TYPES:
        return None
    text, translated = _text_for(item, locale or "en")
    if not text:
        return None
    citation = _citation(item)
    if not citation["name"]:
        return None
    hook = item.get("text_origin") == "source_hook"
    llm_ok = (
        item.get("llm_ok") is True
        and not hook
        and not item.get("ai_bot_blocked")
        and citation["licence"] in _MERGEABLE
        and not citation["conflict"]
    )
    fid = _str(str(item.get("id"))) if item.get("id") is not None else None
    if not fid:
        fid = hashlib.sha1(f"{ftype}|{text}".encode()).hexdigest()[:12]
    return {
        "id": f"c:{fid}",
        "fact_type": ftype,
        "text": text[:MAX_TEXT],
        "origin": "crawler",
        "source": "crawler",
        "citation": citation,
        "date_ref": _str(item.get("date_ref")),
        "quote": hook,
        "machine_translated": translated,
        "confidence": _str(item.get("confidence")),
        "llm_ok": llm_ok,
    }


def _place(item: dict) -> dict:
    return item.get("place") if isinstance(item.get("place"), dict) else {}


def _is_country_level(item: dict) -> bool:
    p = _place(item)
    if p.get("admin_level") == "country":
        return True
    # A Factbook fact names only the country
    return not p.get("geonames_id") and not p.get("wikidata_qid") and not p.get("name")


def _names_region(item: dict, region: str) -> bool:
    p = _place(item)
    if p.get("admin_level") not in ("admin1", None):
        return False
    name = fold_place(p.get("name") or "")
    want = fold_place(region)
    if not name or not want:
        return False
    return name == want or name.startswith(want + " ") or want.startswith(name + " ")


def _sort_key(f: dict) -> tuple:
    return (
        _CONFIDENCE_RANK.get(f.get("confidence") or "", 3),
        f.get("machine_translated", False),
        f.get("quote", False),
        f["id"],
    )


def empty_groups() -> dict[str, list]:
    return {t: [] for t in FACT_TYPES}


def _group(facts: list[dict]) -> dict[str, list]:
    groups = empty_groups()
    seen: set[str] = set()
    for f in sorted(facts, key=_sort_key):
        k = fold_place(f["text"])
        if k in seen or f["id"] in seen:
            continue
        seen.update((k, f["id"]))
        if len(groups[f["fact_type"]]) < CRAWLER_PER_GROUP:
            groups[f["fact_type"]].append(f)
    return groups


async def crawler_facts_for(
    scopes: list[Scope], locale: str = "en"
) -> dict[str, dict[str, list]] | None:
    """``{scope key: {fact_type: [fact]}}`` from the crawler, or None when
    it is off or answered for none of the places. Never raises."""
    if not crawler_client.configured() or not scopes:
        return None
    cities = [s for s in scopes if s.geonames_id]
    countries = sorted({s.country for s in scopes if s.country})
    try:
        got = await asyncio.gather(
            *(crawler_client.place_facts(geonames_id=s.geonames_id) for s in cities),
            *(
                crawler_client.place_facts(country=cc, limit=100, pages=2)
                for cc in countries
            ),
        )
    except Exception as e:  # the client never raises; belt and braces
        logger.warning("place_facts crawler fetch failed: %s", type(e).__name__)
        return None
    if all(g is None for g in got):
        return None
    by_city = dict(zip([s.key for s in cities], got[: len(cities)]))
    by_country = dict(zip(countries, got[len(cities) :]))
    city_ids = {s.geonames_id for s in cities}
    out: dict[str, dict[str, list]] = {}
    for s in scopes:
        raw: list[dict] = []
        if s.scope == "city":
            raw = list(by_city.get(s.key) or [])
            raw += [
                i
                for i in by_country.get(s.country) or []
                if _place(i).get("geonames_id") == s.geonames_id
            ]
        elif s.scope == "country":
            raw = [i for i in by_country.get(s.country) or [] if _is_country_level(i)]
        elif s.scope in ("region", "place"):
            raw = [
                i
                for i in by_country.get(s.country) or []
                if _place(i).get("geonames_id") not in city_ids
                and not _is_country_level(i)
                and _names_region(i, s.name)
            ]
        facts = [f for f in (crawler_fact(i, locale) for i in raw) if f]
        out[s.key] = _group(facts)
    return out


# ── the section ──────────────────────────────────────────────────────────


def build_section(
    scopes: list[Scope], crawler: dict[str, dict[str, list]] | None
) -> dict:
    places = []
    for s in scopes:
        groups = empty_groups()
        for t, facts in ((crawler or {}).get(s.key) or {}).items():
            if t in groups:
                groups[t] = list(facts)
        places.append({**s.public(), "groups": groups})
    return {"places": places, "fact_types": list(FACT_TYPES), "counts": _counts(places)}


def _counts(places: list[dict]) -> dict:
    crawler = ai = 0
    for p in places:
        for facts in p["groups"].values():
            for f in facts:
                if f.get("origin") == "crawler":
                    crawler += 1
                else:
                    ai += 1
    return {"crawler": crawler, "ai": ai}


def has_facts(section: dict | None) -> bool:
    return bool(
        isinstance(section, dict)
        and any(
            facts
            for p in section.get("places") or []
            for facts in (p.get("groups") or {}).values()
        )
    )


def gaps(section: dict) -> dict[str, list[str]]:
    """``{place key: [fact types with no facts]}``, places with no gap left
    out."""
    out: dict[str, list[str]] = {}
    for p in section.get("places") or []:
        missing = [t for t in FACT_TYPES if not (p.get("groups") or {}).get(t)]
        if missing:
            out[p["key"]] = missing
    return out


def reference_prompt(section: dict) -> str:
    """The crawler facts the model may see (open licence, ``llm_ok``, no hook,
    no conflict), as untrusted reference data, so it does not repeat them."""
    lines = []
    for p in section.get("places") or []:
        for facts in (p.get("groups") or {}).values():
            for f in facts:
                if f.get("origin") == "crawler" and f.get("llm_ok"):
                    lines.append((f["citation"], f"{p['name']}: {f['text']}"))
    return reference_block(lines, "facts we already show — do not repeat them")


def _clean_ai_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if len(text) < 12 or _LINKISH.search(text):
        return None
    if len(text) > MAX_TEXT:
        text = text[: MAX_TEXT - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def merge_ai(section: dict, ai: dict, *, per_group: int = AI_PER_GROUP) -> dict:
    """Add the model's facts to the groups the crawler left empty. Anything
    else the model sends (sources, links, groups that already have facts,
    unknown places) is dropped. Returns a new section."""
    places = []
    holes = gaps(section)
    by_key: dict[str, list] = {}
    for entry in (ai or {}).get("places") or []:
        if isinstance(entry, dict) and isinstance(entry.get("key"), str):
            by_key.setdefault(entry["key"], []).extend(
                f for f in entry.get("facts") or [] if isinstance(f, dict)
            )
    for p in section.get("places") or []:
        groups = {t: list(v) for t, v in (p.get("groups") or {}).items()}
        open_types = set(holes.get(p["key"], []))
        seen = {fold_place(f["text"]) for v in groups.values() for f in v}
        for raw in by_key.get(p["key"], []):
            ftype = raw.get("fact_type")
            if ftype not in open_types:
                continue
            text = _clean_ai_text(raw.get("text"))
            if not text or fold_place(text) in seen:
                continue
            if len([f for f in groups[ftype] if f["origin"] == "ai"]) >= per_group:
                continue
            seen.add(fold_place(text))
            digest = hashlib.sha1(f"{p['key']}|{ftype}|{text}".encode()).hexdigest()
            groups[ftype].append(
                {
                    "id": f"a:{digest[:12]}",
                    "fact_type": ftype,
                    "text": text,
                    "origin": "ai",
                    "source": "ai",
                    "verified": False,
                    "citation": None,
                }
            )
        places.append({**p, "groups": groups})
    return {**section, "places": places, "counts": _counts(places)}


def public(section: dict) -> dict:
    """The section as sent to clients: the internal ``llm_ok`` flag
    removed."""
    if not isinstance(section, dict) or section.get("error"):
        return section
    places = []
    for p in section.get("places") or []:
        groups = {
            t: [{k: v for k, v in f.items() if k != "llm_ok"} for f in facts]
            for t, facts in (p.get("groups") or {}).items()
        }
        places.append({**p, "groups": groups})
    return {**section, "places": places}
