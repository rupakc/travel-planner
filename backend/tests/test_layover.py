"""Tests for the Layover optimizer — agent prompt, route, and serp layover mapping."""

from unittest.mock import AsyncMock, patch

import pytest


class TestLayoverPrompt:
    @pytest.mark.anyio
    async def test_prompt_includes_all_context(self):
        from app.agents.layover_agent import LayoverAgent

        agent = LayoverAgent.__new__(LayoverAgent)
        agent.execute = AsyncMock(return_value={"feasible_to_exit": True})
        await agent.run(
            city="Doha, Qatar",
            duration_hours=6.5,
            nationality="American",
            airport="DOH",
            arrival_time="14:30",
            interests=["food", "culture"],
        )
        prompt = agent.execute.call_args[0][0]
        assert "Doha, Qatar (DOH)" in prompt
        assert "6.5 hours" in prompt
        assert "American" in prompt
        assert "14:30" in prompt
        assert "food, culture" in prompt
        assert "transit-visa" in prompt

    @pytest.mark.anyio
    async def test_optional_fields_omitted(self):
        from app.agents.layover_agent import LayoverAgent

        agent = LayoverAgent.__new__(LayoverAgent)
        agent.execute = AsyncMock(return_value={})
        await agent.run(city="Istanbul, Turkey", duration_hours=8, nationality="Indian")
        prompt = agent.execute.call_args[0][0]
        assert "Arrival time" not in prompt
        assert "interests" not in prompt.lower()

    def test_layover_definition_loads(self):
        from app.agents.loader import load_agent_definition
        from app.core.config import settings

        definition = load_agent_definition(settings.agents_dir, "layover")
        assert definition.name == "layover"
        assert "feasible_to_exit" in definition.system_prompt


class TestLayoverRoute:
    def test_layover_route(self, client):
        verdict = {
            "feasible_to_exit": True,
            "usable_city_hours": 3.5,
            "plan": [{"time_slot": "Hour 1", "activity": "Souq Waqif"}],
        }
        with patch(
            "app.api.routes.layover.LayoverAgent.run",
            new=AsyncMock(return_value=verdict),
        ):
            resp = client.post(
                "/api/layover",
                json={
                    "city": "Doha, Qatar",
                    "duration_hours": 6.5,
                    "nationality": "American",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["feasible_to_exit"] is True

    def test_layover_route_validation(self, client):
        assert (
            client.post(
                "/api/layover", json={"city": "Doha", "nationality": "American"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/layover",
                json={"city": "Doha", "duration_hours": 0, "nationality": "US"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/layover",
                json={
                    "city": "Doha",
                    "duration_hours": 5,
                    "nationality": "US",
                    "arrival_time": "3pm",
                },
            ).status_code
            == 422
        )


class TestSerpLayoverMapping:
    def test_map_leg_includes_layovers(self):
        from app.services.serp_flights import _map_leg

        flights_arr = [
            {
                "airline": "Qatar Airways",
                "flight_number": "QR 702",
                "duration": 720,
                "departure_airport": {"id": "JFK", "time": "2026-08-10 09:00"},
                "arrival_airport": {"id": "DOH", "time": "2026-08-11 05:00"},
            },
            {
                "airline": "Qatar Airways",
                "flight_number": "QR 806",
                "duration": 570,
                "departure_airport": {"id": "DOH", "time": "2026-08-11 11:30"},
                "arrival_airport": {"id": "NRT", "time": "2026-08-12 02:00"},
            },
        ]
        layovers = [
            {"name": "Hamad International Airport", "id": "DOH", "duration": 390}
        ]
        leg = _map_leg(flights_arr, layovers, "2026-08-10")
        assert leg["stops"] == 1
        assert leg["layovers"] == [
            {
                "city": "Hamad International Airport",
                "airport": "DOH",
                "duration_hours": 6.5,
            }
        ]

    def test_map_leg_nonstop_has_empty_layovers(self):
        from app.services.serp_flights import _map_leg

        flights_arr = [
            {
                "airline": "JAL",
                "duration": 810,
                "departure_airport": {"id": "JFK", "time": "2026-08-10 11:00"},
                "arrival_airport": {"id": "NRT", "time": "2026-08-11 15:30"},
            }
        ]
        leg = _map_leg(flights_arr, [], "2026-08-10")
        assert leg["stops"] == 0
        assert leg["layovers"] == []
