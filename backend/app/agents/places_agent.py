"""Places-to-see agent — Serper Google data + Claude synthesis."""

from __future__ import annotations

import asyncio
import logging
import urllib.parse

from ..core.cache import get_cache
from ..core.config import settings
from ..schemas.request import TravelSearchRequest
from ..services.places_url_resolver import SerperPlacesResolver, resolve_top_places
from ..services.serper_places import SerperPlacesClient
from .base_agent import ToolAgent
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


def _build_tripadvisor_url(name: str, destination: str) -> str:
    q = urllib.parse.quote_plus(f"{name} {destination}")
    return f"https://www.tripadvisor.com/Search?q={q}"


class PlacesAgent(ToolAgent):
    def __init__(self, agents_dir: str) -> None:
        super().__init__(load_agent_definition(agents_dir, "places"))

    async def run(self, request: TravelSearchRequest) -> dict:
        destination = request.destination
        cities = request.destinations if request.is_multi_city else [destination]

        # Fetch from Serper per city in parallel (cached 30 min each)
        async def fetch_city(city: str) -> tuple[str, list[dict], list[dict]]:
            cache_key = f"serper:places_ctx:{city}"
            cached = get_cache().get(cache_key)
            if cached:
                return city, cached[0], cached[1]
            client = SerperPlacesClient(settings.serper_key)
            fetched = await asyncio.gather(
                client.fetch_places(city),
                client.fetch_guides(city),
                return_exceptions=True,
            )
            p_data = fetched[0] if not isinstance(fetched[0], Exception) else []
            g_data = fetched[1] if not isinstance(fetched[1], Exception) else []
            if p_data or g_data:
                get_cache()[cache_key] = (p_data, g_data)
            return city, p_data, g_data

        places_data: list[dict] = []
        guides_data: list[dict] = []
        city_context_blocks: list[str] = []
        if settings.serper_key:
            per_city = await asyncio.gather(*[fetch_city(c) for c in cities])
            for city, p_data, g_data in per_city:
                places_data.extend(p_data)
                guides_data.extend(g_data)
                if len(cities) > 1:
                    city_context_blocks.append(
                        f"### {city}\n"
                        + SerperPlacesClient.format_context(p_data, g_data)
                    )

        # Build prompt with injected Google context
        google_context = (
            "\n\n".join(city_context_blocks)
            if city_context_blocks
            else SerperPlacesClient.format_context(places_data, guides_data)
        )
        interests_str = (
            ", ".join(request.interests) if request.interests else "general sightseeing"
        )
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date and request.departure_date
            else 7
        )
        prompt = (
            f"Find the best places to see in {destination}.\n"
            f"Traveler interests: {interests_str}. Trip duration: {nights} nights.\n"
            f"Traveler profile: {request.traveler_context}\n\n"
            f"=== GOOGLE SEARCH DATA ===\n{google_context}\n=========================\n\n"
            "Synthesise the Google data above with your knowledge. Return 8–12 must-see places. "
            "JSON only."
        )
        if request.multi_city_context:
            prompt += (
                f"\n{request.multi_city_context}\n"
                f"MANDATORY COVERAGE: return 4-6 must-see places for EACH of "
                f"the {len(cities)} cities ({', '.join(cities)}) — never skip a "
                "city. Group them city by city in trip order."
            )
        if request.serendipity_context:
            prompt += f"\n{request.serendipity_context}"

        # Claude synthesises Serper + internal knowledge → structured JSON
        result = await self.execute(prompt)
        if result.get("error"):
            return result

        # Tier 1: match Serper /places official website to result items
        places_websites: dict[str, str] = {
            p.get("title", "").lower(): p.get("website", "")
            for p in places_data
            if p.get("website")
        }
        for place in result.get("results", []):
            name_lower = place.get("name", "").lower()
            official_url = next(
                (
                    url
                    for title, url in places_websites.items()
                    if title in name_lower or name_lower in title
                ),
                None,
            )
            if official_url:
                place["info_url"] = official_url
                place["source"] = "official"
            else:
                place["info_url"] = _build_tripadvisor_url(
                    place.get("name", ""), destination
                )
                place["source"] = "tripadvisor"

        result["_destination"] = destination
        return result

    async def enrich(self, data: dict) -> dict:
        destination = data.pop("_destination", "")
        if not destination or not settings.serper_key:
            return data
        resolver = SerperPlacesResolver(settings.serper_key)
        return await resolve_top_places(resolver, data, destination)
