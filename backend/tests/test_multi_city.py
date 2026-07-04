"""Tests for multi-city routing — schema helpers and agent prompt context."""

from unittest.mock import AsyncMock

import pytest

from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Paris, France",
    "departure_date": "2026-09-01",
    "return_date": "2026-09-10",
    "nationality": "American",
}

MULTI = {**BASE, "destinations": ["Paris, France", "Rome, Italy", "Barcelona, Spain"]}


class TestSchemaHelpers:
    def test_single_city_defaults(self):
        req = TravelSearchRequest(**BASE)
        assert req.is_multi_city is False
        assert req.destination_label == "Paris, France"
        assert req.multi_city_context is None

    def test_multi_city_properties(self):
        req = TravelSearchRequest(**MULTI)
        assert req.is_multi_city is True
        assert req.destination_label == "Paris, France → Rome, Italy → Barcelona, Spain"
        assert "MULTI-CITY" in req.multi_city_context
        assert "Rome, Italy" in req.multi_city_context

    def test_single_entry_destinations_is_not_multi_city(self):
        req = TravelSearchRequest(**BASE, destinations=["Paris, France"])
        assert req.is_multi_city is False
        assert req.multi_city_context is None


def _agent_with_mock_execute(cls):
    agent = cls.__new__(cls)
    agent.execute = AsyncMock(return_value={"results": []})
    return agent


class TestAgentPrompts:
    @pytest.mark.anyio
    async def test_hotels_prompt_mentions_all_cities(self):
        from app.agents.hotels_agent import HotelsAgent

        agent = _agent_with_mock_execute(HotelsAgent)
        await agent.run(TravelSearchRequest(**MULTI))
        prompt = agent.execute.call_args[0][0]
        assert "MULTI-CITY" in prompt
        assert "Barcelona, Spain" in prompt
        assert "'city' field" in prompt

    @pytest.mark.anyio
    async def test_visa_prompt_covers_every_country(self):
        from app.agents.visa_agent import VisaAgent

        agent = _agent_with_mock_execute(VisaAgent)
        await agent.run(TravelSearchRequest(**MULTI))
        prompt = agent.execute.call_args[0][0]
        assert "multi-city" in prompt
        assert "EVERY country" in prompt
        assert "Rome, Italy" in prompt

    @pytest.mark.anyio
    async def test_flights_prompt_prefers_open_jaw(self, monkeypatch):
        from app.agents import flights_agent as fa_mod
        from app.agents.flights_agent import FlightsAgent

        # Force the AI-agent path — never call the real SerpAPI in tests
        monkeypatch.setattr(fa_mod.settings, "serpapi_key", "")
        agent = _agent_with_mock_execute(FlightsAgent)
        await agent.run(TravelSearchRequest(**MULTI))
        prompt = agent.execute.call_args[0][0]
        assert "OPEN-JAW" in prompt
        assert "Barcelona, Spain → New York, USA" in prompt

    @pytest.mark.anyio
    async def test_itinerary_prompt_allocates_cities(self):
        from app.agents.itinerary_agent import ItineraryAgent

        agent = _agent_with_mock_execute(ItineraryAgent)
        req = TravelSearchRequest(**MULTI)
        await agent.run(req, destinations=req.destinations)
        prompt = agent.execute.call_args[0][0]
        assert "MULTI-CITY" in prompt
        assert "OPTIMIZE CITY ORDER" in prompt
        assert "travel day" in prompt

    @pytest.mark.anyio
    async def test_single_city_prompts_have_no_multi_city_noise(self):
        from app.agents.hotels_agent import HotelsAgent

        agent = _agent_with_mock_execute(HotelsAgent)
        await agent.run(TravelSearchRequest(**BASE))
        assert "MULTI-CITY" not in agent.execute.call_args[0][0]


class TestOrchestratorWiring:
    def test_orchestrator_passes_destinations_to_itinerary(self):
        import inspect

        from app.agents import orchestrator as orch_mod

        source = inspect.getsource(orch_mod)
        # Every itinerary.run call site must forward request.destinations
        call_count = source.count("self.itinerary.run(")
        forwarded = source.count("destinations=request.destinations")
        assert call_count == forwarded == 3
