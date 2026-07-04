import logging
from urllib.parse import urlparse

from ..schemas.request import TravelSearchRequest
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition

logger = logging.getLogger(__name__)

_SOURCE_DOMAINS = {
    "booking": "booking.com",
    "booking.com": "booking.com",
    "expedia": "expedia.com",
    "expedia.com": "expedia.com",
    "agoda": "agoda.com",
    "agoda.com": "agoda.com",
    "hotels.com": "hotels.com",
    "hostelworld": "hostelworld.com",
    "hostelworld.com": "hostelworld.com",
    "trip.com": "trip.com",
}

_DOMAIN_TO_SOURCE = {
    "booking.com": "booking.com",
    "expedia.com": "expedia.com",
    "agoda.com": "agoda.com",
    "hotels.com": "hotels.com",
    "hostelworld.com": "hostelworld.com",
    "trip.com": "trip.com",
}


def _url_to_source(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return "web"
    for domain, source_name in _DOMAIN_TO_SOURCE.items():
        if host == domain or host.endswith("." + domain):
            return source_name
    return host or "web"


def _normalize_source_key(source: str) -> str:
    return source.lower().replace(" ", "").replace("_", "").strip()


class HotelsAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "hotels"))

    async def run(
        self, request: TravelSearchRequest, filters: dict | None = None
    ) -> dict:
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        prompt = (
            f"Find hotels in {request.destination} (identify the country and use the full location, e.g. 'Tokyo, Japan').\n"
            f"Check-in: {request.departure_date}\n"
            f"Check-out: {request.return_date or 'N/A'}\n"
            f"Number of nights: {nights}\n"
            f"Number of travelers: {request.num_travelers}\n"
            f"Budget: {'$' + str(int(request.budget_usd)) + ' total' if request.budget_usd else 'flexible'}\n"
            f"Return 12 hotels across all four budget tiers (luxury, premium, mid-range, budget). Include source and source_snippet for each.\n"
            f"Traveler profile: {request.traveler_context}"
        )
        if request.multi_city_context:
            prompt += (
                f"\n{request.multi_city_context}\n"
                f"MANDATORY COVERAGE: at least 3 hotels for EACH city "
                f"({', '.join(request.destinations)}) — never skip a city — "
                "still covering multiple budget tiers per city. Order the "
                "results city by city in trip order."
            )
        if request.taste_context:
            prompt += (
                f"\n{request.taste_context}\n"
                "Weight the result mix toward this profile's preferred tier while "
                "still covering all four tiers."
            )

        if filters:
            lines = ["\n\n--- MANDATORY HOTEL FILTERS (strictly enforce these) ---"]
            if filters.get("num_beds") is not None:
                lines.append(
                    f"BEDS: Only rooms with at least {filters['num_beds']} bed(s). Mention bed count in amenities or description."
                )
            if filters.get("max_price_per_night_usd") is not None:
                lines.append(
                    f"PRICE: Maximum ${int(filters['max_price_per_night_usd'])} per night. Exclude any hotel above this nightly rate."
                )
            if filters.get("wifi_quality"):
                quality = filters["wifi_quality"]
                desc = {
                    "basic": "basic/free WiFi",
                    "good": "good/reliable WiFi suitable for video calls",
                    "excellent": "excellent high-speed WiFi",
                }
                lines.append(
                    f"WIFI: Only hotels with {desc.get(quality, quality)}. Include wifi_quality field in each result (basic/good/excellent)."
                )
            if filters.get("max_distance_from_center_km") is not None:
                lines.append(
                    f"LOCATION: Only hotels within {filters['max_distance_from_center_km']} km of the city center. Include distance_from_center_km in each result."
                )
            if filters.get("private_washroom"):
                lines.append(
                    "BATHROOM: Only hotels/rooms with a private en-suite bathroom/washroom. Exclude shared-bathroom options."
                )
            lines.append("--- END FILTERS ---")
            prompt += "\n".join(lines)

        self._destination = request.destination
        return await self.execute(prompt)

    _MAX_ENRICH = 12

    async def _enrich_urls(self, data: dict) -> dict:
        hotels = data.get("results", [])
        if not hotels:
            return data

        for hotel in hotels[: self._MAX_ENRICH]:
            name = hotel.get("name", "")
            if not name:
                continue
            source = hotel.get("source", "")
            source_key = _normalize_source_key(source)
            domain = _SOURCE_DOMAINS.get(source_key)

            # Use platform name as a search hint, not a site: restriction
            # (DuckDuckGo site: is unreliable for large booking platforms)
            hint = domain or "hotel"
            url = await self._search_url(
                f"{name} {self._destination} {hint} book",
                match_name=name,
            )

            # Fallback: try the hotel's official website
            if not url:
                url = await self._search_url(
                    f"{name} {self._destination} official website",
                    match_name=name,
                )

            if url:
                hotel["booking_url"] = url
                hotel["source"] = _url_to_source(url)
                logger.info(f"Hotel URL: {name} -> {url} (source: {hotel['source']})")

        return data
