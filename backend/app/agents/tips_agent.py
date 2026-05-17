import logging
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition
from ..schemas.request import TravelSearchRequest

logger = logging.getLogger(__name__)


class TipsAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "tips"))

    async def run(self, request: TravelSearchRequest) -> dict:
        prompt = (
            f"Provide essential travel tips for visiting {request.destination} (identify the country and use the full location, e.g. 'Tokyo, Japan').\n"
            f"Traveler nationality: {request.nationality}\n"
            f"Travel dates: {request.departure_date} to {request.return_date or 'N/A'}\n"
            f"Return 18-25 tips covering safety, culture, money, health, transport, scam, tourist_trap, food, legal.\n"
            f"Sort by severity: danger first, then warning, then info.\n"
            f"Include at least 4-5 tips about tourist traps and scams.\n"
            f"Every tip MUST have a real source_url (government advisory, tourism board, WHO, CDC)."
        )
        self._destination = request.destination
        self._nationality = request.nationality
        return await self.execute(prompt)

    async def _enrich_urls(self, data: dict) -> dict:
        tips = data.get("results", data.get("tips", []))
        if not tips:
            return data

        dest_country = self._destination.split(",")[-1].strip() if "," in self._destination else self._destination

        categories_seen = set()
        category_urls = {}

        for tip in tips:
            cat = tip.get("category", "safety")
            if cat not in categories_seen:
                categories_seen.add(cat)

        search_map = {
            "safety": f"{dest_country} travel safety advisory {self._nationality}",
            "health": f"{dest_country} travel health vaccination advice CDC WHO",
            "money": f"{dest_country} currency exchange money tips tourists",
            "culture": f"{dest_country} culture customs etiquette tourists guide",
            "transport": f"{dest_country} public transport tourist guide",
            "scam": f"{dest_country} tourist scams warnings avoid",
            "tourist_trap": f"{dest_country} tourist traps avoid tips",
            "food": f"{dest_country} food safety hygiene tourists",
            "legal": f"{dest_country} laws rules tourists know",
        }

        for cat in categories_seen:
            query = search_map.get(cat, f"{dest_country} travel tips {cat}")
            url = await self._search_url(query)
            if url:
                category_urls[cat] = url
                logger.info(f"Tips URL [{cat}]: {dest_country} -> {url}")

        for tip in tips:
            if tip.get("source_url") and self._is_clean_url(tip["source_url"]):
                continue
            cat = tip.get("category", "safety")
            if cat in category_urls:
                tip["source_url"] = category_urls[cat]

        return data
