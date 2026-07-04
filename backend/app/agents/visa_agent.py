import logging

from ..schemas.request import TravelSearchRequest
from .base_agent import ToolAgent, _URLSearchMixin
from .loader import load_agent_definition

logger = logging.getLogger(__name__)


class VisaAgent(ToolAgent, _URLSearchMixin):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "visa"))

    async def run(self, request: TravelSearchRequest) -> dict:
        permits_str = (
            ", ".join(request.residence_permits)
            if request.residence_permits
            else "none"
        )
        visas_str = (
            ", ".join(request.existing_visas) if request.existing_visas else "none"
        )
        nights = (
            (request.return_date - request.departure_date).days
            if request.return_date
            else 7
        )
        prompt = (
            f"Determine visa requirements for:\n"
            f"Nationality: {request.nationality}\n"
            f"Destination: {request.destination} (identify the country and use the full location, e.g. 'Tokyo, Japan')\n"
            f"Intended stay: {nights} days (from {request.departure_date})\n"
            f"Residence permits held: {permits_str}\n"
            f"Existing visas held: {visas_str}\n"
            f"Travelers: {request.traveler_context}\n\n"
            f"You MUST include all three sections: requirement, vaccinations, customs.\n"
            f"Consider how any held visas or residence permits might modify entry requirements.\n"
            f"If the group includes minors, note any extra documents commonly required "
            f"(birth certificates, parental consent letters for children travelling "
            f"with one parent)."
        )
        if request.is_multi_city:
            prompt += (
                f"\nIMPORTANT: This is a multi-city trip visiting "
                f"{', '.join(request.destinations)}. If these cities span multiple "
                "countries, cover entry requirements for EVERY country visited and "
                "note each country in the requirement details."
            )
        self._destination = request.destination
        self._nationality = request.nationality
        return await self.execute(prompt)

    async def _enrich_urls(self, data: dict) -> dict:
        dest_country = (
            self._destination.split(",")[-1].strip()
            if "," in self._destination
            else self._destination
        )

        req = data.get("requirement", {})
        if isinstance(req, dict) and not (
            req.get("official_url") and self._is_clean_url(req.get("official_url", ""))
        ):
            url = await self._search_url(
                f"{dest_country} visa requirements {self._nationality} official government"
            )
            if url:
                req["official_url"] = url
                logger.info(f"Visa official URL: {dest_country} -> {url}")

        vacc = data.get("vaccinations", {})
        if isinstance(vacc, dict) and not (
            vacc.get("source_url") and self._is_clean_url(vacc.get("source_url", ""))
        ):
            url = await self._search_url(
                f"{dest_country} travel vaccination requirements CDC WHO"
            )
            if url:
                vacc["source_url"] = url
                logger.info(f"Vaccination URL: {dest_country} -> {url}")

        customs = data.get("customs", {})
        if isinstance(customs, dict) and not (
            customs.get("source_url")
            and self._is_clean_url(customs.get("source_url", ""))
        ):
            url = await self._search_url(
                f"{dest_country} customs duty free allowance import rules"
            )
            if url:
                customs["source_url"] = url
                logger.info(f"Customs URL: {dest_country} -> {url}")

        if not data.get("official_url"):
            if isinstance(req, dict) and req.get("official_url"):
                data["official_url"] = req["official_url"]

        return data
