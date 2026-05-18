import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class SimAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "sim"))

    async def run(self, request: TravelSearchRequest) -> dict:
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        prompt = (
            f"Recommend SIM card and eSIM options for traveling to {request.destination} (identify the country and use the full location, e.g. 'Tokyo, Japan').\n"
            f"Trip duration: {nights} days\n"
            f"Number of travelers: {request.num_travelers}\n"
            f"Return 6-10 options including both local SIM and international eSIM options sorted by price_usd ascending.\n"
            f"Always include 2-3 global eSIM fallback options (Airalo, Holafly, Nomad, etc.).\n"
            f"IMPORTANT: For every plan, include a network_quality object with speed (e.g. '5G', '4G LTE'), "
            f"coverage_rating ('excellent'/'good'/'moderate'/'limited'), and coverage_description "
            f"(one sentence about real-world coverage at {request.destination}). "
            f"For global eSIMs, assess the partner network quality at {request.destination}."
        )
        self._destination = request.destination
        return await self.execute(prompt)

    async def _enrich_urls(self, data: dict) -> dict:
        items = data.get("results", data.get("plans", []))
        if not items:
            return data

        seen_providers = set()
        for item in items:
            provider = item.get("provider", "") or item.get("name", "")
            if not provider or provider in seen_providers:
                continue
            seen_providers.add(provider)
            if item.get("url") and self._is_clean_url(item["url"]):
                continue
            url = await self._search_url(
                f"{provider} eSIM SIM card {self._destination} buy", match_name=provider
            )
            if url:
                for it in items:
                    p = it.get("provider", "") or it.get("name", "")
                    if p == provider and not (
                        it.get("url") and self._is_clean_url(it["url"])
                    ):
                        it["url"] = url
                logger.info(f"SIM URL: {provider} -> {url}")

        return data
