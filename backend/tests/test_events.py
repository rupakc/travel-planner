"""Tests for the Local Events agent, orchestrator wiring, and route."""

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-07-20",
    "return_date": "2026-07-27",
    "interests": ["culture", "food"],
    "nationality": "American",
}


class TestEventsPrompt:
    @pytest.mark.anyio
    async def test_prompt_includes_dates_month_and_interests(self):
        from app.agents.events_agent import EventsAgent

        agent = EventsAgent.__new__(EventsAgent)
        agent.execute = AsyncMock(return_value={"results": []})
        await agent.run(TravelSearchRequest(**BASE))
        prompt = agent.execute.call_args[0][0]
        assert "Tokyo, Japan" in prompt
        assert "2026-07-20 (Monday)" in prompt
        assert "month: July" in prompt
        assert "culture, food" in prompt
        assert "disruptions" in prompt

    @pytest.mark.anyio
    async def test_one_way_trip_defaults_to_seven_days(self):
        from app.agents.events_agent import EventsAgent

        agent = EventsAgent.__new__(EventsAgent)
        agent.execute = AsyncMock(return_value={"results": []})
        await agent.run(TravelSearchRequest(**{**BASE, "return_date": None}))
        assert "2026-07-27" in agent.execute.call_args[0][0]

    @pytest.mark.anyio
    async def test_multi_city_prompt_covers_all_cities(self):
        from app.agents.events_agent import EventsAgent

        agent = EventsAgent.__new__(EventsAgent)
        agent.execute = AsyncMock(return_value={"results": []})
        await agent.run(
            TravelSearchRequest(**BASE, destinations=["Tokyo, Japan", "Kyoto, Japan"])
        )
        prompt = agent.execute.call_args[0][0]
        assert "Tokyo, Japan → Kyoto, Japan" in prompt
        assert "MULTI-CITY" in prompt


class TestAgentDefinition:
    def test_events_definition_loads(self):
        from app.agents.loader import load_agent_definition
        from app.core.config import settings

        definition = load_agent_definition(settings.agents_dir, "events")
        assert definition.name == "events"
        assert "hidden" not in definition.name
        assert "festival" in definition.system_prompt.lower()
        assert "impact" in definition.system_prompt


class TestOrchestratorWiring:
    def test_events_registered_in_both_paths(self):
        import inspect

        from app.agents import orchestrator as orch_mod

        source = inspect.getsource(orch_mod)
        assert "self.events = EventsAgent(agents_dir)" in source
        assert "self.events.run(request)" in source  # run() gather
        assert '"events": self.events' in source  # stream_run phase1_agents


class TestEventsRoute:
    def test_events_route(self, client):
        verdict = {
            "results": [
                {
                    "name": "Gion Matsuri",
                    "category": "festival",
                    "impact": "highlight",
                }
            ]
        }
        with patch(
            "app.api.routes.events.EventsAgent.run",
            new=AsyncMock(return_value=verdict),
        ):
            resp = client.post("/api/events", json=BASE)
        assert resp.status_code == 200
        assert resp.json()["results"][0]["name"] == "Gion Matsuri"

    def test_events_route_validates_request(self, client):
        resp = client.post("/api/events", json={"origin": "NYC"})
        assert resp.status_code == 422
