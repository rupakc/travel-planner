import logging
import re
from urllib.parse import urlparse

from ..schemas.request import TravelSearchRequest
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition

logger = logging.getLogger(__name__)

_SOURCE_DOMAINS = {
    "getyourguide": "getyourguide.com",
    "tripadvisor": "tripadvisor.com",
    "klook": "klook.com",
    "viator": "viator.com",
    "booking.com": "booking.com",
    "tiqets": "tiqets.com",
    "musement": "musement.com",
}

_DOMAIN_TO_SOURCE = {v: k for k, v in _SOURCE_DOMAINS.items()}


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
    return source.lower().replace(" ", "").replace(".com", "").replace("_", "")


class ActivitiesAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "activities"))

    async def run(
        self, request: TravelSearchRequest, filters: dict | None = None
    ) -> dict:
        interests_str = (
            ", ".join(request.interests) if request.interests else "general sightseeing"
        )
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        prompt = (
            f"Find the best activities and experiences in {request.destination} (identify the country and use the full location, e.g. 'Tokyo, Japan').\n"
            f"Traveler interests: {interests_str}\n"
            f"Trip duration: {nights} nights\n"
            f"Number of travelers: {request.num_travelers}\n"
            f"Return 15-20 activities sorted by similarity_score descending.\n"
            f"Include similarity_score (0.0-1.0), category, rating, review_count, source for each.\n"
            f"Write rich 2-sentence descriptions. Prefer activities with ratings 4.0+."
        )

        if filters:
            lines = ["\n\n--- MANDATORY ACTIVITY FILTERS (strictly enforce these) ---"]
            fi = filters.get("filter_interests")
            if fi:
                lines.append(
                    f"INTERESTS: Focus ONLY on these categories: {', '.join(fi)}. Every result must belong to one of these categories."
                )
            if filters.get("max_price_usd") is not None:
                lines.append(
                    f"PRICE: Maximum ${int(filters['max_price_usd'])} per person. Exclude activities above this price."
                )
            avail_from = filters.get("available_from")
            avail_to = filters.get("available_to")
            if avail_from or avail_to:
                f_str = str(avail_from) if avail_from else "any"
                t_str = str(avail_to) if avail_to else "any"
                lines.append(
                    f"AVAILABILITY: Only activities available between {f_str} and {t_str}. Include an availability_dates or available_from/available_to field in each result."
                )
            if filters.get("min_rating") is not None:
                lines.append(
                    f"RATING: Only activities rated {filters['min_rating']}+ stars. Exclude anything below this rating."
                )
            lines.append("--- END FILTERS ---")
            prompt += "\n".join(lines)

        self._destination = request.destination
        return await self.execute(prompt)

    _MAX_ENRICH = 15

    async def _enrich_urls(self, data: dict) -> dict:
        activities = data.get("results", [])
        if not activities:
            return data

        for activity in activities[: self._MAX_ENRICH]:
            raw_name = activity.get("name", "")
            if not raw_name:
                continue
            clean = re.sub(r"[^a-zA-Z0-9\s]", " ", raw_name).strip()
            short = " ".join(clean.split()[:6])
            source = activity.get("source", "")
            source_key = _normalize_source_key(source)

            url = None

            # Try source-specific search first
            domain = _SOURCE_DOMAINS.get(source_key)
            if domain:
                url = await self._search_url(
                    f"site:{domain} {short} {self._destination}",
                    match_name=raw_name,
                )

            # Fallback: general search
            if not url:
                url = await self._search_url(
                    f"{short} {self._destination} book tickets tour",
                    match_name=raw_name,
                )

            if url:
                activity["booking_url"] = url
                activity["source"] = _url_to_source(url)
                logger.info(
                    f"Activity URL: {raw_name} -> {url} (source: {activity['source']})"
                )

        return data
