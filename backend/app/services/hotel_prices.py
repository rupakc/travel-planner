"""Live hotel prices from SerpAPI Google Hotels (``engine=google_hotels``).

Pure, async adapter with no database, used by hotel price watches:

- ``find_properties`` searches Google Hotels for "<name> <city>" on the
  watch's dates and returns priced ``HotelOffer`` s. Google answers either
  with a ``properties`` list or, when the query names one property, with
  that property's page (top-level fields).
- ``match_property`` picks the offer that is confidently the named hotel.
- ``price_property`` re-prices one property by its ``property_token``. Sold
  out / no rates → ``HotelPrice(available=False)``; transient failures
  raise ``SerpAPIError``.
- ``suggestions`` lists priced alternatives when nothing matched.

Prices are USD and cover the whole stay for all rooms: Google prices one
room for the adults in it, so the adults are split across ``rooms``
(rounded up) and the room price is multiplied by ``rooms``. Prices use
Google's ``extracted_lowest`` (after taxes and fees).

Results are cached in the shared TTL cache, keyed by every parameter
except the api key; errors are never cached.
"""

from __future__ import annotations

import difflib
import logging
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

import httpx

from ..core.cache import get_cache
from . import serp_flights
from .name_match import words
from .serp_flights import SERP_URL, SerpAPIError

__all__ = [
    "MATCH_THRESHOLD",
    "HotelOffer",
    "HotelPrice",
    "SerpAPIError",
    "find_is_cached",
    "find_properties",
    "match_property",
    "name_similarity",
    "price_is_cached",
    "price_property",
    "suggestions",
]

logger = logging.getLogger(__name__)

SOURCE = "google_hotels"
CURRENCY = "USD"

# Jaccard similarity of distinctive name words needed for a confident match.
# 0.6 accepts a missing/extra word on 3+ word names ("Story Rossio" vs
# "My Story Rossio Alfama" = 2/3) but rejects names sharing only one of two
# words ("Hotel da Baixa" vs "Be Poet Baixa Hotel" = 1/2, "Lisbon Light
# Hotel" vs "Lumen Hotel & The Lisbon Light Show" = 2/4).
MATCH_THRESHOLD = 0.6

# Words that never identify a property ("hotel", articles). name_match.words
# already drops words of 1-2 letters ("da", "de", "&", "by").
_GENERIC = frozenset({"the", "and", "hotel", "hotels", "des", "del", "los", "las"})
# A name word this close to a city word is the city ("Lisboa" ≈ "Lisbon").
_CITY_SIMILARITY = 0.8
# Separators between a property's own name and its add-ons
# ("Lumen Hotel & The Lisbon Light Show", "Brown's | Avenue Hotel").
_SEGMENT_SPLIT = re.compile(r"\s+[&|\-–—]\s+|\s*\|\s*|,|\(|\s+by\s+", re.IGNORECASE)
_NO_RESULTS = "hasn't returned any results"


@dataclass(frozen=True)
class HotelOffer:
    name: str
    property_token: str
    rate_per_night: float | None  # all rooms, per night
    total_rate: float | None  # all rooms, whole stay
    currency: str
    hotel_class: int | None
    overall_rating: float | None
    reviews: int | None
    link: str | None
    gps: dict | None  # {"lat": float, "lng": float}
    check_in: str
    check_out: str
    adults: int


@dataclass(frozen=True)
class HotelPrice:
    total: float | None  # all rooms, whole stay
    nightly: float | None  # all rooms, per night
    available: bool
    link: str | None
    observed: dict = field(default_factory=dict)


# ── SerpAPI call ──────────────────────────────────────────────────────────────


async def _call(params: dict) -> dict:
    """One SerpAPI request. Raises SerpAPIError on transport/HTTP/body errors."""
    t0 = time.monotonic()
    try:
        resp = await serp_flights.get_serp_client().get(SERP_URL, params=params)
    except httpx.TimeoutException as exc:
        raise SerpAPIError(f"SerpAPI timeout: {type(exc).__name__}") from exc
    except httpx.RequestError as exc:
        raise SerpAPIError(f"SerpAPI request error: {type(exc).__name__}") from exc
    if resp.status_code == 429:
        raise SerpAPIError("SerpAPI quota exceeded", quota_exceeded=True)
    if resp.status_code >= 400:
        # The body may echo the request (and the key), so it is not quoted.
        raise SerpAPIError(f"SerpAPI HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise SerpAPIError("SerpAPI returned a non-JSON body") from exc
    if not isinstance(data, dict):
        raise SerpAPIError("SerpAPI returned an unexpected body")
    logger.info(
        "SerpAPI google_hotels response in %.0fms", (time.monotonic() - t0) * 1000
    )
    return data


def _no_results(data: dict) -> bool:
    """True for Google's "no results" answer; raises on any other error."""
    error = data.get("error")
    if not error:
        return False
    if _NO_RESULTS in str(error):
        return True
    raise SerpAPIError(f"SerpAPI error: {str(error)[:200]}")


# ── Parsing ───────────────────────────────────────────────────────────────────


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        digits = re.sub(r"[^\d.]", "", value)
        try:
            number = float(digits)
        except ValueError:
            return None
        return number if number > 0 else None
    return None


def _rate(raw: Any) -> float | None:
    """Lowest after-tax price of a ``rate_per_night`` / ``total_rate`` block."""
    if not isinstance(raw, dict):
        return None
    for key in (
        "extracted_lowest",
        "extracted_after_taxes_fees",
        "lowest",
        "after_taxes_fees",
        "extracted_before_taxes_fees",
    ):
        value = _number(raw.get(key))
        if value is not None:
            return value
    return None


def _nights(check_in: str, check_out: str) -> int:
    return (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days


def _stay_prices(
    prop: dict, nights: int, rooms: int
) -> tuple[float | None, float | None]:
    """(nightly, total) for all rooms; one is derived from the other if missing."""
    nightly = _rate(prop.get("rate_per_night"))
    total = _rate(prop.get("total_rate"))
    if total is None and nightly is not None:
        total = nightly * nights
    if nightly is None and total is not None:
        nightly = total / nights
    if nightly is not None:
        nightly = round(nightly * rooms, 2)
    if total is not None:
        total = round(total * rooms, 2)
    return nightly, total


def _gps(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    lat, lng = raw.get("latitude"), raw.get("longitude")
    if not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lng)
    ):
        return None
    return {"lat": float(lat), "lng": float(lng)}


def _link(prop: dict, data: dict) -> str | None:
    link = prop.get("link")
    if isinstance(link, str) and link.startswith("http"):
        return link
    fallback = (data.get("search_metadata") or {}).get("google_hotels_url")
    return fallback if isinstance(fallback, str) else None


def _parse_property(
    prop: Any, data: dict, check_in: str, check_out: str, adults: int, rooms: int
) -> HotelOffer | None:
    """One property (list item or property page) → HotelOffer, or None."""
    if not isinstance(prop, dict):
        return None
    name, token = prop.get("name"), prop.get("property_token")
    if not (
        isinstance(name, str) and name.strip() and isinstance(token, str) and token
    ):
        return None
    nightly, total = _stay_prices(prop, _nights(check_in, check_out), rooms)
    hotel_class = prop.get("extracted_hotel_class")
    rating = prop.get("overall_rating")
    reviews = prop.get("reviews")
    return HotelOffer(
        name=name.strip(),
        property_token=token,
        rate_per_night=nightly,
        total_rate=total,
        currency=CURRENCY,
        hotel_class=hotel_class
        if isinstance(hotel_class, int) and not isinstance(hotel_class, bool)
        else None,
        overall_rating=round(float(rating), 2)
        if isinstance(rating, (int, float)) and not isinstance(rating, bool)
        else None,
        reviews=reviews
        if isinstance(reviews, int) and not isinstance(reviews, bool)
        else None,
        link=_link(prop, data),
        gps=_gps(prop.get("gps_coordinates")),
        check_in=check_in,
        check_out=check_out,
        adults=adults,
    )


def _properties(data: dict) -> list:
    """Both response shapes as a list of raw properties."""
    props = data.get("properties")
    if isinstance(props, list):
        return props
    if data.get("property_token") and data.get("name"):
        return [data]  # a direct property match: Google's property page
    return []


# ── Params / cache keys ───────────────────────────────────────────────────────


def _check_args(
    check_in: Any, check_out: Any, adults: int, rooms: int
) -> tuple[str, str]:
    ci, co = str(check_in), str(check_out)
    if _nights(ci, co) < 1:
        raise ValueError("check_out must be after check_in")
    if adults < 1 or rooms < 1:
        raise ValueError("adults and rooms must be at least 1")
    return ci, co


def _base_params(ci: str, co: str, adults: int, rooms: int, api_key: str) -> dict:
    return {
        "engine": "google_hotels",
        "check_in_date": ci,
        "check_out_date": co,
        "adults": str(math.ceil(adults / rooms)),  # Google prices one room
        "currency": CURRENCY,
        "hl": "en",
        "gl": "us",
        "api_key": api_key,
    }


def _find_key(q: str, ci: str, co: str, adults: int, rooms: int) -> str:
    return f"serp-hotels:find:{q.strip().lower()}:{ci}:{co}:{adults}:{rooms}"


def _price_key(token: str, ci: str, co: str, adults: int, rooms: int) -> str:
    return f"serp-hotels:price:{token}:{ci}:{co}:{adults}:{rooms}"


# ── Public API ────────────────────────────────────────────────────────────────


def find_is_cached(
    name: str, city: str, check_in: Any, check_out: Any, adults: int, rooms: int = 1
) -> bool:
    """Would ``find_properties`` with these arguments answer from the cache
    (no SerpAPI call)? Lets callers count the calls they really spend."""
    ci, co = str(check_in), str(check_out)
    q = " ".join(part.strip() for part in (name, city) if part and part.strip())
    return _find_key(q, ci, co, adults, rooms) in get_cache()


def price_is_cached(
    property_token: str, check_in: Any, check_out: Any, adults: int, rooms: int = 1
) -> bool:
    """Would ``price_property`` with these arguments answer from the cache?"""
    key = _price_key(property_token, str(check_in), str(check_out), adults, rooms)
    return key in get_cache()


async def find_properties(
    name: str,
    city: str,
    check_in: date | str,
    check_out: date | str,
    adults: int,
    api_key: str,
    rooms: int = 1,
) -> list[HotelOffer]:
    """Google Hotels properties for "<name> <city>" on these dates."""
    ci, co = _check_args(check_in, check_out, adults, rooms)
    q = " ".join(part.strip() for part in (name, city) if part and part.strip())
    key = _find_key(q, ci, co, adults, rooms)
    cache = get_cache()
    if key in cache:
        return list(cache[key])

    data = await _call({"q": q, **_base_params(ci, co, adults, rooms, api_key)})
    offers: list[HotelOffer] = []
    if not _no_results(data):
        for prop in _properties(data):
            parsed = _parse_property(prop, data, ci, co, adults, rooms)
            if parsed is not None:
                offers.append(parsed)
    cache[key] = tuple(offers)
    return offers


async def price_property(
    property_token: str,
    check_in: date | str,
    check_out: date | str,
    adults: int,
    api_key: str,
    rooms: int = 1,
    query: str = "hotel",
) -> HotelPrice:
    """Current price of one property for these dates (property-details mode).

    ``query`` only satisfies SerpAPI's required ``q``: the token selects the
    property (verified live with ``q="hotel"``).
    """
    ci, co = _check_args(check_in, check_out, adults, rooms)
    key = _price_key(property_token, ci, co, adults, rooms)
    cache = get_cache()
    if key in cache:
        cached = cache[key]  # copy: callers may mutate ``observed``
        return replace(cached, observed=dict(cached.observed))

    params = {
        "q": query,
        **_base_params(ci, co, adults, rooms, api_key),
        "property_token": property_token,
    }
    data = await _call(params)
    prop: dict = {}
    if not _no_results(data):
        prop = next(
            (
                p
                for p in _properties(data)
                if isinstance(p, dict) and p.get("property_token") == property_token
            ),
            {},
        )
    nightly, total = _stay_prices(prop, _nights(ci, co), rooms)
    available = total is not None
    price = HotelPrice(
        total=total,
        nightly=nightly,
        available=available,
        link=_link(prop, data) if prop else None,
        observed={
            "source": SOURCE,
            "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "name": prop.get("name"),
            "property_token": property_token,
            "currency": CURRENCY,
            "check_in": ci,
            "check_out": co,
            "nights": _nights(ci, co),
            "adults": adults,
            "rooms": rooms,
            "rate_per_night": prop.get("rate_per_night"),
            "total_rate": prop.get("total_rate"),
            "typical_price_range": prop.get("typical_price_range"),
        },
    )
    cache[key] = price
    return replace(price, observed=dict(price.observed))


# ── Matching ──────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    """Strip accents ("Palácio" → "Palacio") so words() keeps whole words."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _name_words(text: str, city_words: set[str]) -> set[str]:
    out = set()
    for word in words(_fold(text)) - _GENERIC:
        if any(
            difflib.SequenceMatcher(None, word, c).ratio() >= _CITY_SIMILARITY
            for c in city_words
        ):
            continue
        out.add(word)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def name_similarity(name: str, candidate: str, city: str | None = None) -> float:
    """0.0–1.0 similarity of a hotel name to a Google Hotels property name.

    Jaccard overlap of distinctive words (accents folded; "hotel", articles,
    short words and the city's words removed), against the candidate's full
    name and its leading segment (before "&", "|", " - ", "by" …), whichever
    is higher. A name with no distinctive words scores 0.
    """
    city_words = words(_fold(city)) if city else set()
    wanted = _name_words(name, city_words)
    if not wanted:
        return 0.0
    full = _name_words(candidate, city_words)
    head = _name_words(_SEGMENT_SPLIT.split(candidate or "", maxsplit=1)[0], city_words)
    return max(_jaccard(wanted, full), _jaccard(wanted, head))


def match_property(
    name: str, offers: list[HotelOffer], city: str | None = None
) -> HotelOffer | None:
    """The offer that is confidently ``name`` (score ≥ MATCH_THRESHOLD), or None.

    Best score wins; ties keep Google's order.
    """
    best, best_score = None, 0.0
    for candidate in offers:
        score = name_similarity(name, candidate.name, city)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= MATCH_THRESHOLD else None


def suggestions(
    offers: list[HotelOffer],
    n: int = 3,
    name: str | None = None,
    city: str | None = None,
) -> list[HotelOffer]:
    """Up to ``n`` priced offers (one per property), in Google's order or,
    when ``name`` is given, most similar names first."""
    seen: set[str] = set()
    priced = []
    for o in offers:
        if o.total_rate is None or o.property_token in seen:
            continue
        seen.add(o.property_token)
        priced.append(o)
    if name:
        priced.sort(key=lambda o: name_similarity(name, o.name, city), reverse=True)
    return priced[: max(n, 0)]
