"""Activity booking URL resolver — Tier 2 upgrade via Serper / SerpAPI.

Upgrades Tier 1 platform search URLs to direct listing URLs for top activities.
All resolver calls run in parallel; results are TTL-cached to protect quota.

Evidence flags set here (and only here):
- ``link_checked``: the activity was one of the top-N actually searched.
- ``link_verified``: the chosen trusted result's title contains the
  activity's distinctive name words (``services.name_match``). A trusted URL
  whose title does not name the activity still upgrades the link, unflagged.
"""

import asyncio
import logging
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx

from ..core.cache import get_cache
from .name_match import name_matches_title

logger = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"
_SERPAPI_URL = "https://serpapi.com/search"

_TRUSTED_DOMAINS = frozenset(
    {
        "getyourguide.com",
        "viator.com",
        "klook.com",
        "tripadvisor.com",
        "tiqets.com",
        "musement.com",
    }
)
_TOP_N = 5
_MIN_NAME_LEN = 10

# Module-level shared client — own connection pool, not coupled to serp_flights
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _is_trusted(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
        return any(host == d or host.endswith("." + d) for d in _TRUSTED_DOMAINS)
    except Exception:
        return False


def _build_query(name: str, destination: str) -> str:
    short = " ".join(name.split()[:6])
    return f"{short} {destination} book tour"


# ── Protocol ───────────────────────────────────────────────────────────────────


@runtime_checkable
class ActivityURLResolver(Protocol):
    async def resolve(
        self, name: str, destination: str
    ) -> tuple[str, str] | None: ...  # (link, result title)


# ── Implementations ────────────────────────────────────────────────────────────


class SerperActivityResolver:
    """Resolves activity URLs via the Serper Google Search API (google.serper.dev).

    POST https://google.serper.dev/search
    Auth: X-API-KEY header
    Response: {"organic": [{"link": "...", "title": "..."}, ...]}
    tbs=qdr:y restricts to results indexed in the past year (freshness).
    """

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def resolve(self, name: str, destination: str) -> tuple[str, str] | None:
        try:
            resp = await _get_client().post(
                _SERPER_URL,
                json={
                    "q": _build_query(name, destination),
                    "gl": "us",
                    "hl": "en",
                    "num": 10,
                    "tbs": "qdr:y",
                },
                headers={"X-API-KEY": self._key, "Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("Serper returned HTTP %d for %r", resp.status_code, name)
                return None
            for item in resp.json().get("organic", []):
                link = item.get("link", "")
                if _is_trusted(link):
                    return link, str(item.get("title") or "")
        except (httpx.RequestError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("Serper resolve failed for %r: %s", name, exc)
        return None


class SerpAPIActivityResolver:
    """Resolves activity URLs via SerpAPI engine=google (fallback).

    Uses the same SerpAPI key as the flights integration.
    Note: response field is organic_results (not organic like Serper).
    """

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def resolve(self, name: str, destination: str) -> tuple[str, str] | None:
        try:
            resp = await _get_client().get(
                _SERPAPI_URL,
                params={
                    "engine": "google",
                    "q": _build_query(name, destination),
                    "api_key": self._key,
                    "num": 10,
                    "tbs": "qdr:y",
                },
            )
            if resp.status_code != 200:
                return None
            for item in resp.json().get("organic_results", []):
                link = item.get("link", "")
                if _is_trusted(link):
                    return link, str(item.get("title") or "")
        except (httpx.RequestError, httpx.TimeoutException, ValueError) as exc:
            logger.warning("SerpAPI activity resolve failed for %r: %s", name, exc)
        return None


# ── Factory ────────────────────────────────────────────────────────────────────


def _pick_resolver(settings) -> ActivityURLResolver | None:  # type: ignore[type-arg]
    """Priority: Serper (separate budget) > SerpAPI (shares flight quota) > None."""
    if getattr(settings, "serper_key", ""):
        return SerperActivityResolver(settings.serper_key)
    if getattr(settings, "serpapi_key", ""):
        return SerpAPIActivityResolver(settings.serpapi_key)
    return None


# ── Public API ─────────────────────────────────────────────────────────────────


async def resolve_top(
    resolver: ActivityURLResolver,
    data: dict,
    destination: str,
) -> dict:
    """Upgrade Tier 1 URLs to direct listing URLs for the top N activities.

    Runs all resolver calls in parallel. Results are TTL-cached (30 min).
    A URL is only assigned to one activity (deduplication via used_urls).
    """
    activities = data.get("results", [])
    cache = get_cache()

    ranked = sorted(
        [
            (i, a)
            for i, a in enumerate(activities)
            if a.get("similarity_score") is not None
            and len(a.get("name", "")) >= _MIN_NAME_LEN
        ],
        key=lambda x: (-(x[1].get("similarity_score") or 0), x[0]),
    )[:_TOP_N]

    if not ranked:
        return data

    used_urls: set[str] = set()

    async def resolve_one(
        idx: int, activity: dict
    ) -> tuple[int, tuple[str, str] | None]:
        name = activity.get("name", "")
        cache_key = f"serper:activity:{name}:{destination}"
        cached = cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, tuple):
                return idx, cached
            return idx, ((cached, "") if cached else None)
        hit = await resolver.resolve(name, destination)
        hit = tuple(hit) if hit else None
        cache[cache_key] = hit or ""
        return idx, hit

    # Only the top-N actually searched count towards the section's totals
    for i, _a in ranked:
        activities[i]["link_checked"] = True

    results = await asyncio.gather(
        *[resolve_one(i, a) for i, a in ranked],
        return_exceptions=True,
    )

    # Dedup in post-processing (parallel tasks can't share used_urls state)
    for res in results:
        if isinstance(res, Exception):
            logger.warning("resolve_one raised: %s", res)
            continue
        idx, hit = res
        if not hit:
            continue
        url, title = hit
        if url and url not in used_urls:
            activity = activities[idx]
            activity["booking_url"] = url
            # Evidence only when the result is really about this activity
            if name_matches_title(activity.get("name", ""), title):
                activity["link_verified"] = True
            used_urls.add(url)
            logger.info(
                "Tier 2 activity URL [%d] %r → %s",
                idx,
                activity.get("name", ""),
                url,
            )

    return data
