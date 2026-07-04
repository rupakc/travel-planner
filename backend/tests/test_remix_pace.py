"""Tests for the Trip Remix `pace` field and its itinerary prompt injection."""

from unittest.mock import AsyncMock, patch

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


class TestPaceField:
    def test_defaults_to_balanced(self):
        req = TravelSearchRequest(**BASE)
        assert req.pace == "balanced"

    @pytest.mark.parametrize("pace", ["relaxed", "balanced", "packed"])
    def test_accepts_valid_paces(self, pace):
        req = TravelSearchRequest(**BASE, pace=pace)
        assert req.pace == pace

    def test_rejects_invalid_pace(self):
        with pytest.raises(ValidationError):
            TravelSearchRequest(**BASE, pace="frantic")


class TestItineraryPromptPacing:
    @pytest.mark.anyio
    async def test_pace_guidance_reaches_prompt(self):
        from app.agents.itinerary_agent import ItineraryAgent

        agent = ItineraryAgent.__new__(ItineraryAgent)
        agent.execute = AsyncMock(return_value={"days": []})

        req = TravelSearchRequest(**BASE, pace="relaxed")
        await agent.run(req)

        prompt = agent.execute.call_args[0][0]
        assert "RELAXED pace" in prompt

        req_packed = TravelSearchRequest(**BASE, pace="packed")
        await agent.run(req_packed)
        assert "PACKED pace" in agent.execute.call_args[0][0]


class TestSearchRouteAcceptsPace:
    def test_sync_search_validates_pace(self, client):
        with patch("app.api.routes.search.get_orchestrator") as mock_get_orchestrator:
            orch = mock_get_orchestrator.return_value
            orch.run = AsyncMock(return_value={"flights": {"results": []}})
            resp = client.post("/api/search/sync", json={**BASE, "pace": "packed"})
        assert resp.status_code == 200

    def test_sync_search_rejects_bad_pace(self, client):
        resp = client.post("/api/search/sync", json={**BASE, "pace": "warp-speed"})
        assert resp.status_code == 422
