import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class GettingAroundAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "getting-around"))

    async def run(self, request: TravelSearchRequest) -> dict:
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        prompt = (
            f"Find all public and private transportation options for getting around {request.destination} (identify the country and use the full location, e.g. 'Tokyo, Japan').\n"
            f"Trip duration: {nights} nights\n"
            f"Number of travelers: {request.num_travelers}\n"
            f"Budget: {'$' + str(int(request.budget_usd)) if request.budget_usd else 'flexible'}\n"
            f"Cover both intra-city transit AND inter-city travel within {request.destination}'s country.\n"
            f"Return 10-18 transportation options. Include intra-city first, then inter-city.\n"
            f"Every option must have: name, type, scope, description, coverage, price_info, operating_hours, tips, booking_url.\n"
            f"IMPORTANT: booking_url must be a SINGLE URL, not multiple URLs."
        )
        self._destination = request.destination
        return await self.execute(prompt)

    _MAX_ENRICH = 12

    @staticmethod
    def _clean_multi_url(url: str) -> str:
        """Extract the first URL if Haiku returned multiple joined by | or space."""
        if not url:
            return url
        for sep in (" | ", " |", "| ", "|"):
            if sep in url:
                return url.split(sep)[0].strip()
        return url

    async def _enrich_urls(self, data: dict) -> dict:
        items = data.get("results", data.get("options", []))
        if not items:
            return data

        for item in items[: self._MAX_ENRICH]:
            # First, clean up any multi-URL values from Haiku
            raw_url = item.get("booking_url", "")
            if raw_url and "|" in raw_url:
                item["booking_url"] = self._clean_multi_url(raw_url)

            name = item.get("name", "") or item.get("type", "")
            if not name:
                continue
            if item.get("booking_url") and self._is_clean_url(item["booking_url"]):
                continue

            url = await self._search_url(
                f"{name} {self._destination} official website", match_name=name
            )
            if url:
                item["booking_url"] = url
                logger.info(f"Transport URL: {name} -> {url}")

        return data
