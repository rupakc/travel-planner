"""Serper API client for fetching structured Google places and search data."""

from __future__ import annotations

import logging

import httpx

_SERPER_PLACES_URL = "https://google.serper.dev/places"
_SERPER_SEARCH_URL = "https://google.serper.dev/search"
_TIMEOUT = 10.0

logger = logging.getLogger(__name__)


class SerperPlacesClient:
    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def fetch_places(self, destination: str) -> list[dict]:
        """Fetch structured Google Maps place data (name, rating, category, website)."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _SERPER_PLACES_URL,
                    headers={
                        "X-API-KEY": self._key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "q": f"top places to visit {destination}",
                        "gl": "us",
                        "hl": "en",
                    },
                )
                resp.raise_for_status()
                return resp.json().get("places", [])
        except Exception as exc:
            logger.warning("Serper /places failed for %s: %s", destination, exc)
            return []

    async def fetch_guides(self, destination: str) -> list[dict]:
        """Fetch editorial Google search results (Timeout, Lonely Planet, TripAdvisor articles)."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _SERPER_SEARCH_URL,
                    headers={
                        "X-API-KEY": self._key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "q": f"best places to see {destination} must visit attractions landmarks",
                        "gl": "us",
                        "hl": "en",
                        "num": 10,
                    },
                )
                resp.raise_for_status()
                return resp.json().get("organic", [])
        except Exception as exc:
            logger.warning("Serper /search failed for %s: %s", destination, exc)
            return []

    @staticmethod
    def format_context(places: list[dict], guides: list[dict]) -> str:
        """Format Serper results as a context block for prompt injection."""
        lines: list[str] = []

        if places:
            lines.append("GOOGLE MAPS PLACES (structured data from Google):")
            for p in places[:15]:
                rating_str = (
                    f" | Rating: {p['rating']} ({p.get('ratingCount', 0):,} reviews)"
                    if p.get("rating")
                    else ""
                )
                website_str = f" | Website: {p['website']}" if p.get("website") else ""
                addr_str = f" | {p['address']}" if p.get("address") else ""
                lines.append(
                    f"  - {p.get('title', '')} [{p.get('category', '')}]"
                    f"{rating_str}{addr_str}{website_str}"
                )

        if guides:
            lines.append("\nGOOGLE SEARCH RESULTS (editorial travel guides):")
            for g in guides[:8]:
                lines.append(f"  - {g.get('title', '')} | {g.get('link', '')}")
                if g.get("snippet"):
                    lines.append(f"    {g['snippet']}")

        return (
            "\n".join(lines)
            if lines
            else "(No Google data available — use your internal knowledge)"
        )
