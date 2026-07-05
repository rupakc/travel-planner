"""Robustness of the shared agent execution path (regression: a burst of 12
concurrent large-output calls made every LLM-backed section fail in prod
while SerpAPI flights and Open-Meteo weather survived)."""

import pytest

from app.agents import base_agent
from app.schemas.request import TravelSearchRequest


def test_output_cap_covers_multi_city_responses():
    assert base_agent._MAX_TOKENS >= 16384


def test_semaphore_limits_concurrent_agent_calls():
    sem = base_agent._get_semaphore()
    assert 1 <= sem._value <= 12


@pytest.mark.anyio
async def test_execute_backs_off_and_reports_error(monkeypatch):
    class FakeMessages:
        async def create(self, **kwargs):
            raise anthropic_error

    class FakeClient:
        messages = FakeMessages()

    import anthropic

    anthropic_error = anthropic.APIConnectionError(request=None)
    monkeypatch.setattr(base_agent, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(base_agent, "_MAX_RETRIES", 2)

    async def no_sleep(_):
        pass

    monkeypatch.setattr(base_agent.asyncio, "sleep", no_sleep)

    agent = base_agent.BaseAgent.__new__(base_agent.BaseAgent)

    class Defn:
        name = "probe"
        system_prompt = "test"

    agent.definition = Defn()
    result = await agent.execute("hello")
    assert "error" in result


def test_multi_city_stops_resolve_bare_iata(client):
    req = TravelSearchRequest(
        origin="BER",
        destination="SFO",
        destinations=["AMS", "JFK", "SFO"],
        departure_date="2026-09-10",
        return_date="2026-09-20",
        nationality="German",
    )
    assert req.destinations[0].startswith("Amsterdam")
    assert req.destinations[1].startswith("New York")
    assert req.destinations[2].startswith("San Francisco")
    assert req.destination.startswith("San Francisco")
