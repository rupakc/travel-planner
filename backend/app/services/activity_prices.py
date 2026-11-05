"""Observed activity prices from Google search results (GetYourGuide / Viator).

GetYourGuide and Viator block automated clients (HTTP 403, even on
robots.txt), so their pages are never fetched. The only source is SerpAPI
``engine=google``: organic results whose link is on getyourguide.com or
viator.com and whose ``rich_snippet`` carries a price, e.g.
``rich_snippet.top.detected_extensions = {"price": 11.63, "currency": "$",
"rating": 4.3, "reviews": 59566}`` with ``extensions: ["Starting from $11.63"]``.
Such a price is a per-person "from" price, as Google shows it.

Pure and async, no database. Public API:

- ``find_listings(name, city, api_key)``: GetYourGuide query, then Viator only
  when GetYourGuide has no confident activity-page match.
- ``match_listing(name, listings, city="")``: a confident match or ``None``.
- ``price_listing(listing, query, api_key)``: re-run the stored query and
  find the same listing again.
- ``suggestions(listings, n=3)``.
- ``search_listings(query, api_key)`` / ``is_cached(query)``: one stored
  query's listings, and whether re-running it is free.

Currency: prices keep the currency Google shows ("$" with ``gl=us`` is USD,
"€" is EUR, "A$" is AUD …). The app has no exchange-rate source to convert
with (the forex agent asks the AI over web search per trip; there are no
static rate tables), so non-USD prices are **not converted**: they keep their
ISO code (or the raw symbol when unknown) and ``is_usd=False``. Callers must
not compare them with USD prices.

Errors: HTTP / network failures raise ``SerpAPIError`` (from
``serp_flights``; ``quota_exceeded`` on 429) and are never cached. A SerpAPI
"no results" answer is an empty result, and is cached.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from ..core.cache import get_cache
from . import serp_flights
from .name_match import STOP_WORDS, distinctive_words, min_matches, words
from .serp_flights import SerpAPIError

logger = logging.getLogger(__name__)

_SERP_URL = "https://serpapi.com/search"
_HL, _GL = "en", "us"
_CACHE_PREFIX = "activity_prices:google"  # shared cache: TTL 30 min (settings)

PROVIDERS = {"getyourguide.com": "getyourguide", "viator.com": "viator"}
_QUERY_SUFFIX = {"getyourguide": "getyourguide", "viator": "viator"}

# ── Thresholds ────────────────────────────────────────────────────────────────
# Matching a traveller's activity name to a listing title (accent-folded,
# city and stop words removed from the name):
# - the name's distinctive words found in the title must reach
#   ``name_match.min_matches`` (1-2 words: all; more: half, floor 2) AND
#   cover at least MATCH_MIN_COVERAGE of them;
# - for activity pages, the matched words must also make up at least
#   MATCH_MIN_PRECISION of the title's own distinctive words (format words
#   like "ticket", "entry", "skip", "small group" ignored), so a tour that
#   merely passes the place ("Belém Tuk Tuk Tour: Jerónimos, MAAT & Tower")
#   is not taken for it. Category pages are only used when no activity page
#   matches, and are flagged (``is_category``).
MATCH_MIN_COVERAGE = 0.6
MATCH_MIN_PRECISION = 0.5
# Re-check fallback when the stored URL is gone: same provider, same page
# kind, and the Jaccard similarity of the two titles' words at least this.
RECHECK_MIN_TITLE_SIMILARITY = 0.8

# Generic tour vocabulary: never enough to identify an activity. A name's
# other capitalised words (places, proper nouns) must all be in a listing's
# title, and these count only GENERIC_TOUR_WEIGHT towards coverage.
GENERIC_TOUR_WORDS = frozenset(
    {
        "tour",
        "tours",
        "walking",
        "walk",
        "small",
        "group",
        "guided",
        "guide",
        "ticket",
        "tickets",
        "entry",
        "skip",
        "line",
        "private",
        "day",
        "trip",
        "from",
        "with",
        "experience",
        "admission",
        "audio",
    }
)
GENERIC_TOUR_WEIGHT = 0.25

# Words that describe the product format, not what is visited.
_FORMAT_WORDS = frozenset(
    {
        "ticket",
        "entry",
        "entrance",
        "admission",
        "skip",
        "line",
        "fast",
        "track",
        "audio",
        "audioguide",
        "guided",
        "private",
        "small",
        "group",
        "walking",
        "walk",
        "pass",
        "combo",
        "visit",
        "views",
        "view",
        "day",
        "half",
        "full",
        "hour",
        "hours",
        "pickup",
        "transfer",
        "optional",
        "including",
        "included",
        "experience",
        "2025",
        "2026",
        "2027",
    }
)

_CURRENCIES = {
    "US$": "USD",
    "USD": "USD",
    "$": "USD",  # results are requested with gl=us
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "A$": "AUD",
    "AU$": "AUD",
    "AUD": "AUD",
    "C$": "CAD",
    "CA$": "CAD",
    "CAD": "CAD",
    "NZ$": "NZD",
    "HK$": "HKD",
    "S$": "SGD",
    "R$": "BRL",
    "MX$": "MXN",
    "¥": "JPY",
    "₹": "INR",
    "CHF": "CHF",
}
_CUR_RE = "|".join(re.escape(c) for c in sorted(_CURRENCIES, key=len, reverse=True))
_AMOUNT_RE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
_FROM_PRICE = re.compile(
    rf"(?i)\bfrom\s*:?\s*(?P<cur>{_CUR_RE})\s?(?P<amt>{_AMOUNT_RE})"
)
_BARE_PRICE = re.compile(rf"^\s*(?P<cur>{_CUR_RE})\s?(?P<amt>{_AMOUNT_RE})\s*$")
_NOT_PER_PERSON = re.compile(
    r"(?i)^\s*(?:per|/|a)\s*(?:group|vehicle|car|boat|booking)"
)
_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}-[a-z]{2}$", re.IGNORECASE)


# ── Data ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActivityListing:
    provider: str  # "getyourguide" | "viator"
    url: str  # normalised (see normalise_url)
    title: str
    price_from: float  # per person, as shown by Google
    currency: str  # ISO code, or the raw symbol when unknown
    is_usd: bool
    rating: float | None
    reviews: int | None
    snippet: str
    page_kind: str  # "activity" | "category"
    query: str  # the Google query that found it (re-run by price_listing)
    position: int | None = None

    @property
    def is_category(self) -> bool:
        return self.page_kind == "category"

    @property
    def source(self) -> str:
        return f"{self.provider}_via_google"


@dataclass(frozen=True)
class ActivityPrice:
    price_from: float | None
    currency: str | None
    is_usd: bool
    available: bool
    url: str
    observed: str  # ISO-8601 UTC time the Google results were fetched
    source: str  # "getyourguide_via_google" | "viator_via_google"
    matched_by: str | None = None  # "url" | "title"
    reason: str | None = None  # unavailable: "not_found" | "no_price"
    title: str = ""
    position: int | None = None


# ── URLs ──────────────────────────────────────────────────────────────────────


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def provider_of(url: str) -> str | None:
    host = _host(url) if isinstance(url, str) else ""
    for domain, provider in PROVIDERS.items():
        if host == domain or host.endswith("." + domain):
            return provider
    return None


def normalise_url(url: str) -> str:
    """https + host + path; query, fragment, trailing slash and a leading
    locale segment ("en-au", "en-CA") dropped. Provider hosts become
    ``www.<domain>``. Path case is kept (Viator paths are case-sensitive)."""
    try:
        parts = urlparse(url.strip())
    except (ValueError, AttributeError):
        return ""
    host = (parts.hostname or "").lower()
    provider = provider_of(url)
    if provider:
        host = "www." + next(d for d, p in PROVIDERS.items() if p == provider)
        segments = [s for s in parts.path.split("/") if s]
        if segments and _LOCALE_SEGMENT.match(segments[0]):
            segments = segments[1:]
        path = "/" + "/".join(segments)
    else:
        path = parts.path.rstrip("/") or "/"
    return f"https://{host}{path}".rstrip("/")


def page_kind(url: str) -> str | None:
    """ "activity" (a bookable product page), "category" (an attraction,
    category or place listing whose price is the cheapest of many), or None
    (supplier pages, blogs, home, other hosts)."""
    provider = provider_of(url)
    if not provider:
        return None
    segments = [s for s in urlparse(normalise_url(url)).path.split("/") if s]
    if not segments:
        return None
    last = segments[-1]
    if provider == "getyourguide":
        if re.search(r"-t\d+$", last):
            return "activity"
        if re.search(r"-(?:tc|l)\d+$", last):
            return "category"
        return None
    if "blog" in (s.lower() for s in segments):
        return None
    if segments[0] == "tours" and re.match(r"^d\d+-\w+$", last):
        return "activity"
    if any(re.match(r"^d\d+(?:-\w+)?$", s) for s in segments):
        return "category"
    return None


# ── Prices ────────────────────────────────────────────────────────────────────


def _currency(symbol: str) -> tuple[str, bool]:
    code = _CURRENCIES.get(symbol.strip()) or _CURRENCIES.get(symbol.strip().upper())
    if code:
        return code, code == "USD"
    return symbol.strip(), False


def _amount(text: str) -> float | None:
    if "," in text and "." not in text and re.fullmatch(r"\d+,\d{1,2}", text):
        text = text.replace(",", ".")  # European decimal comma: "11,50"
    try:
        value = float(text.replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _price_in_text(text: str, pattern: re.Pattern) -> tuple[float, str] | None:
    for m in pattern.finditer(text or ""):
        if _NOT_PER_PERSON.match(text[m.end() :]):
            continue
        amount = _amount(m.group("amt"))
        if amount is not None:
            return amount, _currency(m.group("cur"))[0]
    return None


def parse_price(item: dict, use_snippet: bool = True) -> tuple[float, str] | None:
    """(price, currency code) of one organic result, or None.

    Order: ``rich_snippet.{top,bottom}.detected_extensions.price`` with its
    currency symbol; then "Starting from $X" / "From US$X" / "from €X" (or a
    bare "$X") in the rich-snippet extensions; then, if ``use_snippet``,
    "from $X" in the snippet text. Per-group / per-vehicle prices are ignored.
    Listing pages must not use the snippet: its prices belong to single
    products shown on the page, not to the page.
    """
    rich = item.get("rich_snippet") if isinstance(item, dict) else None
    blocks = [rich.get(k) for k in ("top", "bottom")] if isinstance(rich, dict) else []
    blocks = [b for b in blocks if isinstance(b, dict)]
    for block in blocks:
        det = block.get("detected_extensions")
        if isinstance(det, dict):
            price, cur = det.get("price"), det.get("currency")
            if (
                isinstance(price, int | float)
                and not isinstance(price, bool)
                and price > 0
                and isinstance(cur, str)
                and cur.strip()
            ):
                return float(price), _currency(cur)[0]
    for block in blocks:
        for ext in block.get("extensions") or []:
            if isinstance(ext, str):
                found = _price_in_text(ext, _FROM_PRICE) or _price_in_text(
                    ext, _BARE_PRICE
                )
                if found:
                    return found
    snippet = item.get("snippet") if isinstance(item, dict) else None
    if use_snippet and isinstance(snippet, str):
        return _price_in_text(snippet, _FROM_PRICE)
    return None


def _num(value, kind):
    if isinstance(value, int | float) and not isinstance(value, bool):
        return kind(value)
    return None


def _rich_value(item: dict, key: str):
    rich = item.get("rich_snippet")
    if isinstance(rich, dict):
        for k in ("top", "bottom"):
            det = (
                (rich.get(k) or {}).get("detected_extensions")
                if isinstance(rich.get(k), dict)
                else None
            )
            if isinstance(det, dict) and key in det:
                return det[key]
    return None


def _to_listing(item, query: str) -> ActivityListing | None:
    if not isinstance(item, dict) or not isinstance(item.get("link"), str):
        return None
    link = item["link"]
    provider, kind = provider_of(link), page_kind(link)
    if not provider or not kind:
        return None
    price = parse_price(item, use_snippet=kind == "activity")
    if not price:
        return None
    amount, currency = price
    return ActivityListing(
        provider=provider,
        url=normalise_url(link),
        title=str(item.get("title") or ""),
        price_from=amount,
        currency=currency,
        is_usd=currency == "USD",
        rating=_num(_rich_value(item, "rating"), float),
        reviews=_num(_rich_value(item, "reviews"), int),
        snippet=str(item.get("snippet") or ""),
        page_kind=kind,
        query=query,
        position=_num(item.get("position"), int),
    )


def _activity_first(listings: Iterable[ActivityListing]) -> list[ActivityListing]:
    seen: set[str] = set()
    unique = []
    for listing in listings:
        if listing.url not in seen:
            seen.add(listing.url)
            unique.append(listing)
    return sorted(unique, key=lambda x: x.is_category)  # stable: search order kept


def parse_listings(data: dict, query: str) -> list[ActivityListing]:
    """Priced GetYourGuide/Viator listings of one SerpAPI response, activity
    pages first, search order kept, one per normalised URL."""
    results = data.get("organic_results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    return _activity_first(x for x in (_to_listing(i, query) for i in results) if x)


# ── Matching ──────────────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    """Strip accents so "Belém" and "Belem" are the same word."""
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c))


def _required_words(name: str, name_words: set[str]) -> set[str]:
    """The name's place / proper-noun words, which a listing must contain:
    its capitalised words that aren't generic tour vocabulary (all its
    non-generic words when the name has no capitals at all)."""
    folded = _fold(name)
    capitalised = {
        w.lower() for w in re.findall(r"[A-Za-z0-9]+", folded) if w[:1].isupper()
    }
    specific = name_words - GENERIC_TOUR_WORDS
    return specific & capitalised if capitalised else specific


def _weight(word: str) -> float:
    return GENERIC_TOUR_WEIGHT if word in GENERIC_TOUR_WORDS else 1.0


def _score(
    name: str, listing: ActivityListing, city: str
) -> tuple[float, float] | None:
    """(coverage, precision) when the listing confidently matches ``name``.

    Every place / proper-noun word of the name (``_required_words``) must be
    in the title; coverage weighs generic tour vocabulary at
    ``GENERIC_TOUR_WEIGHT``, so "small group walking tour" can't carry a
    match on its own.
    """
    name_words = distinctive_words(_fold(name), exclude=[_fold(city)] if city else [])
    if not name_words:
        return None
    title_words = words(_fold(listing.title))
    hits = name_words & title_words
    if not _required_words(name, name_words) <= title_words:
        return None
    coverage = sum(_weight(w) for w in hits) / sum(_weight(w) for w in name_words)
    if len(hits) < min_matches(name_words) or coverage < MATCH_MIN_COVERAGE:
        return None
    city_words = words(_fold(city)) if city else set()
    title_own = (title_words - STOP_WORDS - city_words - _FORMAT_WORDS) | hits
    precision = len(hits) / len(title_own)
    if not listing.is_category and precision < MATCH_MIN_PRECISION:
        return None
    return coverage, precision


def match_listing(
    name: str, listings: Iterable[ActivityListing], city: str = ""
) -> ActivityListing | None:
    """The best confident match: activity pages beat category pages (a
    category page is returned only when no activity page matches, and is
    flagged by ``is_category``); then higher coverage, tighter title, more
    reviews, earlier position."""
    scored = []
    for index, listing in enumerate(listings):
        score = _score(name, listing, city)
        if score:
            coverage, precision = score
            scored.append(
                (
                    (
                        listing.is_category,
                        -coverage,
                        -precision,
                        -(listing.reviews or 0),
                        index,
                    ),
                    listing,
                )
            )
    return min(scored, key=lambda s: s[0])[1] if scored else None


def suggestions(
    listings: Iterable[ActivityListing], n: int = 3
) -> list[ActivityListing]:
    """Up to ``n`` priced listings to offer instead: activity pages first."""
    return _activity_first(listings)[: max(n, 0)]


def _title_similarity(a: str, b: str) -> float:
    def bag(text: str) -> set[str]:
        return words(_fold(text).replace("...", " ").replace("…", " ")) - STOP_WORDS

    wa, wb = bag(a), bag(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


# ── SerpAPI ───────────────────────────────────────────────────────────────────


def _cache_key(query: str) -> str:
    return f"{_CACHE_PREFIX}:{_HL}:{_GL}:{' '.join(query.lower().split())}"


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "***") if api_key else text


async def _search(query: str, api_key: str) -> dict:
    """{"results": organic_results, "fetched_at": iso} for ``query``; cached
    (shared 30-minute cache, api_key not in the key)."""
    cache = get_cache()
    key = _cache_key(query)
    cached = cache.get(key)
    if cached is not None:
        return cached
    params = {
        "engine": "google",
        "q": query,
        "num": 10,
        "hl": _HL,
        "gl": _GL,
        "api_key": api_key,
    }
    try:
        resp = await serp_flights._get_client().get(_SERP_URL, params=params)
    except httpx.TimeoutException as exc:
        raise SerpAPIError(_redact(f"SerpAPI timeout: {exc}", api_key)) from None
    except httpx.RequestError as exc:
        raise SerpAPIError(_redact(f"SerpAPI request error: {exc}", api_key)) from None
    if resp.status_code == 429:
        raise SerpAPIError("SerpAPI quota exceeded", quota_exceeded=True)
    if resp.status_code >= 400:
        raise SerpAPIError(
            _redact(f"SerpAPI HTTP {resp.status_code}: {resp.text[:200]}", api_key)
        )
    try:
        data = resp.json()
    except ValueError:
        raise SerpAPIError("SerpAPI returned invalid JSON") from None
    results = data.get("organic_results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        # SerpAPI answers "no results" with 200 + {"error": "..."}
        results = []
    entry = {
        "results": results,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    cache[key] = entry
    logger.info("Activity prices: %d Google results for %r", len(results), query)
    return entry


def is_cached(query: str) -> bool:
    """True when ``query``'s Google results are in the shared cache, so
    searching it again spends no SerpAPI call."""
    return get_cache().get(_cache_key(query)) is not None


async def search_listings(query: str, api_key: str) -> list[ActivityListing]:
    """Priced listings for one exact query (as ``parse_listings``); cached.
    Raises ``SerpAPIError``."""
    entry = await _search(query, api_key)
    return parse_listings({"organic_results": entry["results"]}, query)


def build_query(name: str, city: str, provider: str) -> str:
    return " ".join(f"{name} {city} {_QUERY_SUFFIX[provider]}".split())


async def find_listings(name: str, city: str, api_key: str) -> list[ActivityListing]:
    """Priced GetYourGuide/Viator listings for an activity, activity pages first.

    Queries "<name> <city> getyourguide"; the Viator query runs only when that
    gives no confident activity-page match. Raises ``SerpAPIError``.
    """
    query = build_query(name, city, "getyourguide")
    listings = parse_listings(
        {"organic_results": (await _search(query, api_key))["results"]}, query
    )
    best = match_listing(name, listings, city)
    if best is None or best.is_category:
        query = build_query(name, city, "viator")
        viator = parse_listings(
            {"organic_results": (await _search(query, api_key))["results"]}, query
        )
        listings = _activity_first([*listings, *viator])
    return listings


async def price_listing(
    listing: ActivityListing, query: str, api_key: str
) -> ActivityPrice:
    """Re-run ``query`` and price the same listing.

    Found by normalised URL → its price (``available=False, reason="no_price"``
    when it is shown without one). Absent → a same-provider, same-kind result
    whose title is near-identical (``RECHECK_MIN_TITLE_SIMILARITY``) is taken
    (``matched_by="title"``); otherwise ``available=False, reason="not_found"``.
    Raises ``SerpAPIError``.
    """
    entry = await _search(query, api_key)
    observed = entry["fetched_at"]
    target = normalise_url(listing.url)
    base = {"observed": observed, "source": listing.source}

    for item in entry["results"]:
        if (
            isinstance(item, dict)
            and isinstance(item.get("link"), str)
            and normalise_url(item["link"]) == target
        ):
            found = _to_listing(item, query)
            if found:
                return _priced(found, "url", observed)
            return ActivityPrice(
                price_from=None,
                currency=None,
                is_usd=False,
                available=False,
                url=listing.url,
                reason="no_price",
                title=str(item.get("title") or listing.title),
                position=_num(item.get("position"), int),
                **base,
            )

    candidates = [
        (sim, x)
        for x in parse_listings({"organic_results": entry["results"]}, query)
        if x.provider == listing.provider
        and x.page_kind == listing.page_kind
        and (sim := _title_similarity(listing.title, x.title))
        >= RECHECK_MIN_TITLE_SIMILARITY
    ]
    if candidates:
        return _priced(max(candidates, key=lambda c: c[0])[1], "title", observed)
    return ActivityPrice(
        price_from=None,
        currency=None,
        is_usd=False,
        available=False,
        url=listing.url,
        reason="not_found",
        title=listing.title,
        **base,
    )


def _priced(found: ActivityListing, matched_by: str, observed: str) -> ActivityPrice:
    return ActivityPrice(
        price_from=found.price_from,
        currency=found.currency,
        is_usd=found.is_usd,
        available=True,
        url=found.url,
        observed=observed,
        source=found.source,
        matched_by=matched_by,
        title=found.title,
        position=found.position,
    )
