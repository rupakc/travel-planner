import logging
import re
import unicodedata
from urllib.parse import quote_plus, urlparse

from ..core.config import settings
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

# Tier 1 — deterministic platform search URLs (always valid, never expire)
_SEARCH_URL_TEMPLATES: dict[str, str] = {
    "getyourguide": "https://www.getyourguide.com/s/?q={q}&et=2",
    "viator": "https://www.viator.com/searchResults/all?text={q}",
    "klook": "https://www.klook.com/search/?query={q}",
    "tripadvisor": "https://www.tripadvisor.com/Search?q={q}",
    "tiqets": "https://www.tiqets.com/en/search/?q={q}",
    "musement": "https://www.musement.com/us/search/?q={q}",
}
_FALLBACK_URL_TEMPLATE = "https://www.google.com/search?q={q}"


def _sanitize_query(text: str) -> str:
    """Normalize unicode and strip special chars so every platform search URL works.

    Handles: accented chars (á→a, é→e, ñ→n), ampersands, colons, commas,
    brackets, and any other non-alphanumeric punctuation. Result is plain
    ASCII words separated by single spaces — safe for all search engines.
    """
    # Strip accents: NFKD decomposes é→e+combining-accent; ASCII encode drops the accent
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Replace any char that isn't a letter, digit, or space with a space
    text = re.sub(r"[^a-zA-Z0-9 ]", " ", text)
    # Collapse runs of whitespace
    return re.sub(r"\s+", " ", text).strip()


def _build_search_url(name: str, destination: str, source: str | None) -> str:
    # Sanitize both independently so neither bleeds special chars into the URL
    clean_name = _sanitize_query(name)
    clean_dest = _sanitize_query(destination)
    # Use first 6 words of the activity name — shorter queries get better results
    short_name = " ".join(clean_name.split()[:6])
    q = quote_plus(f"{short_name} {clean_dest}")
    key = _normalize_source_key(source or "")
    return _SEARCH_URL_TEMPLATES.get(key, _FALLBACK_URL_TEMPLATE).format(q=q)


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
            f"Write rich 2-sentence descriptions. Prefer activities with ratings 4.0+.\n"
            f"Traveler profile: {request.traveler_context}"
        )
        if request.multi_city_context:
            prompt += f"\n{request.multi_city_context}"
        if request.taste_context:
            prompt += (
                f"\n{request.taste_context}\n"
                "Bias activity choices and similarity scores toward this profile, "
                "but still include variety."
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

        result = await self.execute(prompt)
        destination = request.destination
        # Store destination as metadata — travels to enrich(), popped there (not serialised)
        result["_destination"] = destination
        # Tier 1: guarantee every activity has a working booking URL before returning
        for activity in result.get("results", []):
            activity["booking_url"] = _build_search_url(
                activity.get("name", ""), destination, activity.get("source")
            )
        return result

    async def enrich(self, data: dict) -> dict:
        """Override ToolAgent.enrich() — extract destination metadata then run Tier 2 resolver."""
        destination = data.pop("_destination", "")
        from ..services.activity_url_resolver import _pick_resolver, resolve_top

        resolver = _pick_resolver(settings)
        if resolver is None:
            return data
        return await resolve_top(resolver, data, destination)

    async def _enrich_urls(self, data: dict) -> dict:
        return data  # superseded by enrich() override above
