from .base_agent import BaseAgent
from .loader import load_agent_definition


class LayoverAgent(BaseAgent):
    """Turns a long layover into a mini-plan with transit-visa feasibility."""

    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "layover"))

    async def run(
        self,
        city: str,
        duration_hours: float,
        nationality: str,
        airport: str | None = None,
        arrival_time: str | None = None,
        interests: list[str] | None = None,
    ) -> dict:
        prompt = (
            f"Layover city: {city}"
            + (f" ({airport})" if airport else "")
            + "\n"
            + f"Layover duration: {duration_hours} hours\n"
            f"Traveler nationality: {nationality}\n"
        )
        if arrival_time:
            prompt += f"Arrival time at layover airport: {arrival_time}\n"
        if interests:
            prompt += f"Traveler interests: {', '.join(interests)}\n"
        prompt += (
            "Decide whether leaving the airport is realistic, cover transit-visa "
            "requirements for this nationality, and return the JSON plan."
        )
        return await self.execute(prompt)
