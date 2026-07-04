"""Tests for the Serendipity dial — schema field and prompt mapping."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas.request import TravelSearchRequest

BASE = {
    "origin": "New York, USA",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-17",
    "nationality": "American",
}


class TestSerendipityField:
    def test_defaults_to_balanced(self):
        req = TravelSearchRequest(**BASE)
        assert req.serendipity == 0.5
        assert "BALANCED" in req.serendipity_context

    def test_low_maps_to_classics(self):
        req = TravelSearchRequest(**BASE, serendipity=0.1)
        assert "CLASSICS" in req.serendipity_context

    def test_high_maps_to_hidden_gems(self):
        req = TravelSearchRequest(**BASE, serendipity=0.9)
        assert "HIDDEN GEMS" in req.serendipity_context
        assert "hidden_gem" in req.serendipity_context

    @pytest.mark.parametrize("value", [-0.1, 1.5, 2])
    def test_rejects_out_of_range(self, value):
        with pytest.raises(ValidationError):
            TravelSearchRequest(**BASE, serendipity=value)

    @pytest.mark.parametrize("value,keyword", [(0.0, "CLASSICS"), (1.0, "HIDDEN GEMS")])
    def test_boundary_values(self, value, keyword):
        req = TravelSearchRequest(**BASE, serendipity=value)
        assert keyword in req.serendipity_context


class TestPromptInjection:
    @pytest.mark.anyio
    async def test_activities_prompt_carries_dial(self):
        from app.agents.activities_agent import ActivitiesAgent

        agent = ActivitiesAgent.__new__(ActivitiesAgent)
        agent.execute = AsyncMock(return_value={"results": []})
        await agent.run(TravelSearchRequest(**BASE, serendipity=0.9))
        prompt = agent.execute.call_args[0][0]
        assert "SERENDIPITY DIAL — HIDDEN GEMS" in prompt

    @pytest.mark.anyio
    async def test_activities_prompt_classics(self):
        from app.agents.activities_agent import ActivitiesAgent

        agent = ActivitiesAgent.__new__(ActivitiesAgent)
        agent.execute = AsyncMock(return_value={"results": []})
        await agent.run(TravelSearchRequest(**BASE, serendipity=0.0))
        assert "SERENDIPITY DIAL — CLASSICS" in agent.execute.call_args[0][0]
