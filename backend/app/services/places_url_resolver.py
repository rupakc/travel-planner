"""Serper URL resolver for places — Phase 2 background URL enrichment."""

from __future__ import annotations

import asyncio
import logging
import urllib.parse

import httpx

from ..core.cache import get_cache

_SERPER_URL = "https://google.serper.dev/search"
_TRUSTED_DOMAINS = frozenset(
    {
        "tripadvisor.com",
        "timeout.com",
        "lonelyplanet.com",
        "atlasobscura.com",
        "visitacity.com",
        "viator.com",
    }
)
_TOP_N = 5
_TIMEOUT = 10.0

logger = logging.getLogger(__name__)


def _is_trusted(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lstrip("www.")
        return any(host == d or host.endswith(f".{d}") for d in _TRUSTED_DOMAINS)
    except Exception:
        return False


def _build_query(name: str, destination: str) -> str:
    short = " ".join(name.split()[:5])
    return f"{short} {destination} visit"


def _url_to_source(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lstrip("www.")
        for d in _TRUSTED_DOMAINS:
            if host == d or host.endswith(f".{d}"):
                return d.replace(".com", "")
    except Exception:
        pass
    return "web"


class SerperPlacesResolver:
    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def resolve(self, name: str, destination: str) -> str | None:
        cache_key = f"serper:place:{name}:{destination}"
        cached = get_cache().get(cache_key)
        if cached is not None:
            return cached or None
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _SERPER_URL,
                    headers={
                        "X-API-KEY": self._key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "q": _build_query(name, destination),
                        "gl": "us",
                        "hl": "en",
                        "num": 10,
                    },
                )
                resp.raise_for_status()
                for item in resp.json().get("organic", []):
                    url = item.get("link", "")
                    if _is_trusted(url):
                        get_cache()[cache_key] = url
                        return url
        except Exception as exc:
            logger.warning("SerperPlacesResolver failed for %s: %s", name, exc)
        get_cache()[cache_key] = ""
        return None


async def resolve_top_places(
    resolver: SerperPlacesResolver,
    data: dict,
    destination: str,
) -> dict:
    results = data.get("results", [])
    top = results[:_TOP_N]
    seen_urls: set[str] = set()

    async def resolve_one(idx: int, place: dict) -> tuple[int, str | None]:
        name = place.get("name", "")
        if len(name) < 4:
            return idx, None
        url = await resolver.resolve(name, destination)
        return idx, url

    resolved = await asyncio.gather(*(resolve_one(i, p) for i, p in enumerate(top)))
    for idx, url in resolved:
        if url and url not in seen_urls:
            seen_urls.add(url)
            results[idx]["info_url"] = url
            results[idx]["source"] = _url_to_source(url)
    return data
