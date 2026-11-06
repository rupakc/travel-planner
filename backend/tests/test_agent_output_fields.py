"""Prompt contracts for UI-rendered fields some models drop.

Gemini 3.5 Flash-Lite omitted `tourist_pass` (getting around) and
`accessibility_notes` (flights) unless the prompt names them with an explicit
null rule. These tests pin that wording (no network) and prove null values
survive parsing, URL enrichment and verification.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.agents.base_agent import BaseAgent
from app.agents.loader import load_agent_definition
from app.schemas.request import TravelSearchRequest
from app.services.verification import attach_verification

AGENTS_DIR = str(Path(__file__).resolve().parents[2] / ".agents")

BASE = {
    "origin": "New York, USA",
    "destination": "Vienna, Austria",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-17",
    "nationality": "American",
}
ACCESSIBLE = {**BASE, "accessibility_needs": ["wheelchair"]}
MULTI = {
    **BASE,
    "destination": "Paris, France",
    "destinations": ["Paris, France", "Rome, Italy"],
    "destination_nights": [3, 4],
}


def _agent(cls):
    agent = cls.__new__(cls)
    agent.execute = AsyncMock(return_value={"results": []})
    return agent


@pytest.fixture
def no_serpapi(monkeypatch):
    from app.agents import flights_agent as fa_mod

    monkeypatch.setattr(fa_mod.settings, "serpapi_key", "")


class TestAgentDefinitions:
    def test_getting_around_schema_requires_tourist_pass(self):
        prompt = load_agent_definition(AGENTS_DIR, "getting-around").system_prompt
        assert "`tourist_pass` is ALWAYS present" in prompt
        assert "Use `null` when no such pass applies" in prompt
        assert "never omit the key" in prompt
        assert "`operating_hours`, `tips`, `booking_url` and `tourist_pass`" in prompt

    def test_flights_schema_documents_accessibility_notes(self):
        prompt = load_agent_definition(AGENTS_DIR, "flights").system_prompt
        assert '"accessibility_notes": null' in prompt
        assert "`accessibility_notes` is ALWAYS present" in prompt
        assert "it is REQUIRED" in prompt
        assert "Never omit the key" in prompt

    def test_flights_example_json_is_valid(self):
        prompt = load_agent_definition(AGENTS_DIR, "flights").system_prompt
        block = prompt.split("```json", 1)[1].split("```", 1)[0]
        example = json.loads(block)
        assert example["results"][0]["accessibility_notes"] is None


class TestRuntimePrompts:
    @pytest.mark.anyio
    async def test_getting_around_prompt_requires_tourist_pass(self):
        from app.agents.getting_around_agent import GettingAroundAgent

        agent = _agent(GettingAroundAgent)
        await agent.run(TravelSearchRequest(**BASE))
        prompt = agent.execute.call_args[0][0]
        assert "booking_url, tourist_pass" in prompt
        assert "tourist_pass: ALWAYS include the key" in prompt
        assert "or null when none applies" in prompt

    @pytest.mark.anyio
    async def test_flights_prompt_requires_notes_with_accessibility_needs(
        self, no_serpapi
    ):
        from app.agents.flights_agent import FlightsAgent

        agent = _agent(FlightsAgent)
        await agent.run(TravelSearchRequest(**ACCESSIBLE))
        prompt = agent.execute.call_args[0][0]
        assert "ACCESSIBILITY (wheelchair)" in prompt
        assert "every result MUST include accessibility_notes" in prompt
        assert "Never null, never omitted" in prompt

    @pytest.mark.anyio
    async def test_flights_prompt_asks_for_null_without_needs(self, no_serpapi):
        from app.agents.flights_agent import FlightsAgent

        agent = _agent(FlightsAgent)
        await agent.run(TravelSearchRequest(**BASE))
        prompt = agent.execute.call_args[0][0]
        assert "include the key accessibility_notes, set to null" in prompt
        assert "MUST include accessibility_notes" not in prompt

    @pytest.mark.anyio
    async def test_multi_city_flights_prompt_carries_clause(self, no_serpapi):
        from app.agents.flights_agent import FlightsAgent

        agent = _agent(FlightsAgent)
        await agent.run(
            TravelSearchRequest(**{**MULTI, "accessibility_needs": ["wheelchair"]})
        )
        prompt = agent.execute.call_args[0][0]
        assert "MULTI-CITY" in prompt
        assert "every result MUST include accessibility_notes" in prompt

    @pytest.mark.anyio
    async def test_leg_fill_prompt_carries_clause(self):
        from app.agents.flights_agent import FlightsAgent

        agent = _agent(FlightsAgent)
        agent.execute = AsyncMock(return_value={"results": []})
        await agent._ai_fill_legs(
            TravelSearchRequest(**{**MULTI, "accessibility_needs": ["wheelchair"]}),
            [{"leg_index": 0, "from": "New York", "to": "Paris", "date": "2026-08-10"}],
        )
        prompt = agent.execute.call_args[0][0]
        assert "every result MUST include accessibility_notes" in prompt

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "module,cls_name,phrase",
        [
            ("activities_agent", "ActivitiesAgent", "aim for 18 or more"),
            ("tips_agent", "TipsAgent", "aim for 22 or more"),
            ("getting_around_agent", "GettingAroundAgent", "aim for 14 or more"),
            ("flights_agent", "FlightsAgent", "aim for 10 or more"),
        ],
    )
    async def test_count_nudges(self, no_serpapi, module, cls_name, phrase):
        import importlib

        cls = getattr(importlib.import_module(f"app.agents.{module}"), cls_name)
        agent = _agent(cls)
        await agent.run(TravelSearchRequest(**BASE))
        assert phrase in agent.execute.call_args[0][0]


class TestNullTolerance:
    def _parse(self, payload: dict) -> dict:
        agent = BaseAgent.__new__(BaseAgent)
        return agent._parse_json("```json\n" + json.dumps(payload) + "\n```")

    def test_parse_keeps_null_tourist_pass(self):
        data = self._parse(
            {
                "options": [
                    {"name": "Taxi", "type": "taxi", "tourist_pass": None},
                    {
                        "name": "U-Bahn",
                        "type": "metro",
                        "tourist_pass": "Vienna City Card",
                    },
                ]
            }
        )
        assert "tourist_pass" in data["options"][0]
        assert data["options"][0]["tourist_pass"] is None
        assert data["options"][1]["tourist_pass"] == "Vienna City Card"

    def test_parse_keeps_null_accessibility_notes(self):
        data = self._parse(
            {"results": [{"price_usd": 900.0, "accessibility_notes": None}]}
        )
        assert data["results"][0]["accessibility_notes"] is None

    def test_verification_tolerates_nulls(self):
        req = TravelSearchRequest(**ACCESSIBLE)
        flights = {
            "results": [
                {
                    "price_usd": 900.0,
                    "trip_type": "round_trip",
                    "booking_url": None,
                    "source": "web",
                    "outbound": {"airline": "Austrian", "flight_number": "OS88"},
                    "accessibility_notes": None,
                }
            ]
        }
        ga = {"options": [{"name": "Taxi", "type": "taxi", "tourist_pass": None}]}
        out_f = attach_verification("flights", flights, req)
        out_g = attach_verification("getting_around", ga, req)
        assert out_f["verification"]["level"]
        assert out_g["verification"]["level"]
        assert out_f["results"][0]["accessibility_notes"] is None
        assert out_g["options"][0]["tourist_pass"] is None

    @pytest.mark.anyio
    async def test_getting_around_enrichment_tolerates_null_pass(self):
        from app.agents.getting_around_agent import GettingAroundAgent

        agent = GettingAroundAgent.__new__(GettingAroundAgent)
        agent._destination = "Vienna, Austria"
        agent._search_url = AsyncMock(return_value=None)
        data = {
            "options": [
                {
                    "name": "Taxi",
                    "type": "taxi",
                    "booking_url": None,
                    "tourist_pass": None,
                }
            ]
        }
        out = await agent._enrich_urls(data)
        assert out["options"][0]["tourist_pass"] is None
