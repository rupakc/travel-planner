"""Free walking tour providers — pure parsers and city helpers.

Turns the HTML of a provider's city page into normalized tour dicts. No I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
import urllib.parse
from collections.abc import Callable
from typing import Any

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from app.core.cache import get_cache

logger = logging.getLogger(__name__)

_TIP_NOTE = "Free · tip-based"
_PWYW_NOTE = "Pay what you wish"
_MAX_TOURS = 10

PROVIDERS: dict[str, dict[str, Any]] = {
    "guruwalk": {
        "name": "GuruWalk",
        "domain": "guruwalk.com",
        "city_url": lambda slug: f"https://www.guruwalk.com/{slug}",
        "price_note": _TIP_NOTE,
    },
    "freetour": {
        "name": "FreeTour.com",
        "domain": "freetour.com",
        "city_url": lambda slug: f"https://www.freetour.com/{slug}",
        "price_note": _TIP_NOTE,
    },
    "freewalkingtour": {
        "name": "FreeWalkingTour.com",
        "domain": "freewalkingtour.com",
        "city_url": lambda slug: f"https://freewalkingtour.com/{slug}/",
        "price_note": _PWYW_NOTE,
    },
    "sandemans": {
        "name": "SANDEMANs NewEurope",
        "domain": "neweuropetours.eu",
        "city_url": lambda slug: (
            f"https://www.neweuropetours.eu/sandemans-tours/{slug}/"
        ),
        "price_note": _TIP_NOTE,
    },
}

_CityUrl = Callable[[str], str]


def city_slug(city: str) -> str:
    ascii_city = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_city.lower()).strip("-")


def split_city_country(destination: str) -> tuple[str, str | None]:
    text = re.sub(r"\s*\([A-Za-z]{3}\)\s*$", "", destination.strip())
    city, sep, country = text.partition(",")
    return city.strip(), (country.strip() or None) if sep else None


def _host_ok(url: str, domain: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme in ("http", "https") and (
            host == domain or host.endswith(f".{domain}")
        )
    except ValueError:
        return False


def _num(value: Any, cast: Callable[[Any], Any]) -> Any:
    try:
        return cast(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rating_5(agg: dict) -> float | None:
    """Rating on a 5-point scale (FreeTour.com reports out of 10)."""
    value = _num(agg.get("ratingValue"), float)
    if value is None:
        return None
    best = _num(agg.get("bestRating"), float)
    if best and best > 5:
        value = value * 5 / best
    return round(value, 2)


def _tour(
    provider_key: str,
    slug: str,
    city: str,
    n: int,
    *,
    name: str,
    url: str,
    image_url: str | None = None,
    description: str | None = None,
    rating: float | None = None,
    review_count: int | None = None,
    duration: str | None = None,
) -> dict:
    provider = PROVIDERS[provider_key]
    return {
        "id": f"{provider_key}-{slug}-{n}",
        "name": name,
        "provider": provider["name"],
        "provider_key": provider_key,
        "url": url,
        "image_url": image_url,
        "description": description,
        "rating": rating,
        "review_count": review_count,
        "duration": duration,
        "price_note": provider["price_note"],
        "city": city,
        "reason": None,
        "top_pick": False,
    }


def _iter_events(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _iter_events(item)
    elif isinstance(node, dict):
        types = node.get("@type")
        if types == "Event" or (isinstance(types, list) and "Event" in types):
            yield node
        for value in node.values():
            if isinstance(value, (list, dict)):
                yield from _iter_events(value)


def _first_str(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url")
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_jsonld_tours(html: str, provider_key: str, city: str) -> list[dict]:
    try:
        domain = PROVIDERS[provider_key]["domain"]
        slug = city_slug(city)
        soup = BeautifulSoup(html, "html.parser")
        tours: list[dict] = []
        seen: set[str] = set()
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except ValueError:
                continue
            for ev in _iter_events(data):
                url = _first_str(ev.get("url"))
                name = _first_str(ev.get("name"))
                if not url or not name or url in seen or not _host_ok(url, domain):
                    continue
                seen.add(url)
                agg = ev.get("aggregateRating")
                agg = agg if isinstance(agg, dict) else {}
                tours.append(
                    _tour(
                        provider_key,
                        slug,
                        city,
                        len(tours),
                        name=name,
                        url=url,
                        image_url=_first_str(ev.get("image")),
                        description=_first_str(ev.get("description")),
                        rating=_rating_5(agg),
                        review_count=_num(agg.get("reviewCount"), int),
                    )
                )
                if len(tours) >= _MAX_TOURS:
                    return tours
        return tours
    except Exception:
        logger.warning("parse_jsonld_tours failed", exc_info=True)
        return []


_RATING_RE = re.compile(r"(\d\.\d)\s+(\d+)\s+reviews?", re.I)
_DURATION_RE = re.compile(r"\b(\d+h(?:\s*\d+m)?|\d+m)\b")


def parse_freewalkingtour(html: str, slug: str, city: str) -> list[dict]:
    try:
        domain = PROVIDERS["freewalkingtour"]["domain"]
        base = PROVIDERS["freewalkingtour"]["city_url"](slug)
        soup = BeautifulSoup(html, "html.parser")
        tours: list[dict] = []
        seen: set[str] = set()
        for card in soup.select("a.relative.block.h-full"):
            text = " ".join(card.get_text(" ").split())
            if _PWYW_NOTE.lower() not in text.lower():
                continue
            href = card.get("href")
            url = urllib.parse.urljoin(base, href) if isinstance(href, str) else ""
            if not url or url in seen or not _host_ok(url, domain):
                continue
            rating_m = _RATING_RE.search(text)
            dur_m = _DURATION_RE.search(text[rating_m.end() :] if rating_m else text)
            name_part = (
                text[: rating_m.start()]
                if rating_m
                else re.split(r"\bBook now\b", text)[0]
            )
            name = re.sub(_PWYW_NOTE, "", name_part, flags=re.I).strip()
            if not name:
                continue
            img = card.find("img")
            src = img.get("src") if img else None
            image_url = (
                urllib.parse.urljoin(base, src)
                if isinstance(src, str) and src
                else None
            )
            seen.add(url)
            tours.append(
                _tour(
                    "freewalkingtour",
                    slug,
                    city,
                    len(tours),
                    name=name,
                    url=url,
                    image_url=image_url,
                    rating=float(rating_m.group(1)) if rating_m else None,
                    review_count=int(rating_m.group(2)) if rating_m else None,
                    duration=dur_m.group(1) if dur_m else None,
                )
            )
            if len(tours) >= _MAX_TOURS:
                break
        return tours
    except Exception:
        logger.warning("parse_freewalkingtour failed", exc_info=True)
        return []


def parse_sandemans(html: str, slug: str, city: str) -> list[dict]:
    try:
        domain = PROVIDERS["sandemans"]["domain"]
        base = PROVIDERS["sandemans"]["city_url"](slug)
        soup = BeautifulSoup(html, "html.parser")
        tours: list[dict] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"/sandemans-tours/{slug}/" not in href:
                continue
            url = urllib.parse.urljoin(base, href)
            name = " ".join(a.get_text(" ").split())
            if (
                url == base
                or url in seen
                or not name
                or not re.search(r"\bfree\b", name, re.I)
                or not _host_ok(url, domain)
            ):
                continue
            seen.add(url)
            tours.append(_tour("sandemans", slug, city, len(tours), name=name, url=url))
            if len(tours) >= _MAX_TOURS:
                break
        return tours
    except Exception:
        logger.warning("parse_sandemans failed", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Crawler — one request per provider per city, in parallel, cached
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "VoyagerTravelPlanner/1.0 (trip-planning assistant; "
    "fetches city tour listings on behalf of a user)"
)
_FETCH_TIMEOUT = 12.0
_HEADERS = {"User-Agent": _USER_AGENT}
_DISCOVERY_PROVIDERS = ("guruwalk", "freetour")


def _ddgs_search(query: str, max_results: int) -> list:
    """Blocking DuckDuckGo search — each call gets its own DDGS instance."""
    return list(DDGS().text(query, max_results=max_results))


async def _discover_city_url(provider_key: str, city: str) -> str | None:
    """Find a provider's city page via web search when the guessed slug 404s."""
    domain = PROVIDERS[provider_key]["domain"]
    pattern = re.compile(rf"^https://www\.{re.escape(domain)}/[a-z0-9-]+/?$")
    query = f"site:{domain} {city} free walking tour"
    try:
        results = await asyncio.get_running_loop().run_in_executor(
            None, _ddgs_search, query, 5
        )
    except Exception:
        logger.warning("walking-tour discovery failed for %s", query, exc_info=True)
        return None
    for result in results:
        href = result.get("href") if isinstance(result, dict) else None
        if isinstance(href, str) and pattern.match(href):
            return href
    return None


def _parse_provider(provider_key: str, html: str, slug: str, city: str) -> list[dict]:
    if provider_key == "freewalkingtour":
        return parse_freewalkingtour(html, slug, city)
    if provider_key == "sandemans":
        return parse_sandemans(html, slug, city)
    return parse_jsonld_tours(html, provider_key, city)


def _source(provider_key: str, city: str, url: str, count: int, status: str) -> dict:
    return {
        "provider": PROVIDERS[provider_key]["name"],
        "provider_key": provider_key,
        "city": city,
        "url": url,
        "count": count,
        "status": status,
    }


async def _fetch_provider(
    client: httpx.AsyncClient, provider_key: str, city: str, slug: str
) -> tuple[list[dict], dict]:
    url = PROVIDERS[provider_key]["city_url"](slug)
    cache = get_cache()
    key = f"walking_tours:{provider_key}:{slug}"
    cached = cache.get(key)
    if cached is not None:
        cached_url, tours = cached
        return list(tours), _source(provider_key, city, cached_url, len(tours), "ok")
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
        if resp.status_code != 200 and provider_key in _DISCOVERY_PROVIDERS:
            found = await _discover_city_url(provider_key, city)
            if found and found != url:
                url = found
                resp = await client.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
        if resp.status_code != 200:
            return [], _source(provider_key, city, url, 0, "none")
        tours = _parse_provider(provider_key, resp.text, slug, city)
    except Exception:
        logger.warning("walking-tour fetch failed for %s", provider_key, exc_info=True)
        return [], _source(provider_key, city, url, 0, "error")
    cache[key] = (url, tours)
    return list(tours), _source(provider_key, city, url, len(tours), "ok")


async def fetch_city_tours(
    city: str, *, client: httpx.AsyncClient | None = None
) -> tuple[list[dict], list[dict]]:
    """Fetch free walking tours for a city from all providers in parallel.

    Returns ``(tours, sources)``; ``sources`` has one entry per provider.
    """
    slug = city_slug(city)
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=True)
    try:
        results = await asyncio.gather(
            *(_fetch_provider(client, key, city, slug) for key in PROVIDERS)
        )
    finally:
        if own_client:
            await client.aclose()
    tours = [t for provider_tours, _ in results for t in provider_tours]
    return tours, [source for _, source in results]
