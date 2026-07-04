"""Tests for traveler composition — preferences persistence and agent prompts."""

from unittest.mock import AsyncMock

import pytest

from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-17",
    "nationality": "American",
}

FAMILY = {
    **BASE,
    "adults": 2,
    "children": 1,
    "seniors": 1,
    "infants": 1,
    "num_travelers": 5,
    "accessibility_needs": ["wheelchair"],
}


class TestPreferencesPersistence:
    def test_composition_roundtrip(self, client, admin_headers):
        payload = {
            "budget_category": "medium",
            "nationality": "American",
            "interests": ["food"],
            "num_travelers": 5,
            "adults": 2,
            "children": 1,
            "seniors": 1,
            "infants": 1,
            "accessibility_needs": ["wheelchair", "hearing_impairment"],
        }
        resp = client.put("/api/preferences", json=payload, headers=admin_headers)
        assert resp.status_code == 200
        saved = resp.json()
        assert saved["adults"] == 2
        assert saved["children"] == 1
        assert saved["seniors"] == 1
        assert saved["infants"] == 1
        assert saved["accessibility_needs"] == ["wheelchair", "hearing_impairment"]

        fetched = client.get("/api/preferences", headers=admin_headers).json()
        assert fetched["adults"] == 2
        assert fetched["accessibility_needs"] == ["wheelchair", "hearing_impairment"]

    def test_defaults_when_composition_omitted(self, client, admin_headers):
        resp = client.put(
            "/api/preferences",
            json={"budget_category": "low", "nationality": "Indian"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        saved = resp.json()
        assert saved["adults"] == 1
        assert saved["children"] == 0
        assert saved["accessibility_needs"] == []

    def test_rejects_negative_counts(self, client, admin_headers):
        resp = client.put(
            "/api/preferences",
            json={"budget_category": "low", "adults": -1},
            headers=admin_headers,
        )
        assert resp.status_code == 422


def _agent(cls):
    agent = cls.__new__(cls)
    agent.execute = AsyncMock(return_value={"results": []})
    return agent


class TestAgentPrompts:
    @pytest.mark.anyio
    async def test_tips_prompt_includes_group(self):
        from app.agents.tips_agent import TipsAgent

        agent = _agent(TipsAgent)
        await agent.run(TravelSearchRequest(**FAMILY))
        prompt = agent.execute.call_args[0][0]
        assert "2 adults" in prompt
        assert "1 child" in prompt
        assert "wheelchair" in prompt
        assert "Tailor tips to the traveler group" in prompt

    @pytest.mark.anyio
    async def test_getting_around_prompt_includes_group(self):
        from app.agents.getting_around_agent import GettingAroundAgent

        agent = _agent(GettingAroundAgent)
        await agent.run(TravelSearchRequest(**FAMILY))
        prompt = agent.execute.call_args[0][0]
        assert "1 senior" in prompt
        assert "stroller/wheelchair access" in prompt

    @pytest.mark.anyio
    async def test_visa_prompt_mentions_minor_documents(self):
        from app.agents.visa_agent import VisaAgent

        agent = _agent(VisaAgent)
        await agent.run(TravelSearchRequest(**FAMILY))
        prompt = agent.execute.call_args[0][0]
        assert "1 infant" in prompt
        assert "parental consent" in prompt

    @pytest.mark.anyio
    async def test_flights_prompt_notes_child_fares(self, monkeypatch):
        from app.agents import flights_agent as fa_mod
        from app.agents.flights_agent import FlightsAgent

        monkeypatch.setattr(fa_mod.settings, "serpapi_key", "")
        agent = _agent(FlightsAgent)
        await agent.run(TravelSearchRequest(**FAMILY))
        prompt = agent.execute.call_args[0][0]
        assert "young travelers" in prompt
        assert "ADULT per-person fare" in prompt

    @pytest.mark.anyio
    async def test_adults_only_flights_prompt_has_no_child_note(self, monkeypatch):
        from app.agents import flights_agent as fa_mod
        from app.agents.flights_agent import FlightsAgent

        monkeypatch.setattr(fa_mod.settings, "serpapi_key", "")
        agent = _agent(FlightsAgent)
        await agent.run(TravelSearchRequest(**BASE, adults=2, num_travelers=2))
        assert "young travelers" not in agent.execute.call_args[0][0]
