"""Tests for the Trip Stress-Test agent and route."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.stress_test_agent import StressTestAgent
from app.schemas.request import TravelSearchRequest

_DEP = date.today() + timedelta(days=30)
_RET = _DEP + timedelta(days=5)


def _request(**overrides) -> TravelSearchRequest:
    data = {
        "origin": "New York",
        "destination": "Tokyo, Japan",
        "departure_date": _DEP.isoformat(),
        "return_date": _RET.isoformat(),
        "nationality": "American",
        "budget_usd": 3000,
        "num_travelers": 2,
    }
    data.update(overrides)
    return TravelSearchRequest(**data)


def _itinerary() -> dict:
    return {
        "days": [
            {
                "day_number": 1,
                "date": _DEP.isoformat(),
                "theme": "Arrival",
                "slots": [
                    {
                        "time_of_day": "morning",
                        "activity": "Arrive at Tokyo",
                        "location": "Narita",
                        "duration_hours": 3.0,
                        "estimated_cost_usd": 30.0,
                    }
                ],
            }
        ],
        "total_estimated_cost_usd": 900.0,
    }


class TestBuildPrompt:
    def test_includes_trip_facts_and_weekdays(self):
        prompt = StressTestAgent.build_prompt(
            _request(), _itinerary(), None, None, None
        )
        assert "New York" in prompt
        assert "Tokyo" in prompt
        assert _DEP.strftime("%A") in prompt
        assert "Stated budget: $3000" in prompt
        assert "Day 1" in prompt
        assert "Arrive at Tokyo" in prompt

    def test_includes_flight_visa_weather_context(self):
        flights = {
            "results": [
                {
                    "price_usd": 1200.0,
                    "outbound": {
                        "airline": "JAL",
                        "departure_date": _DEP.isoformat(),
                        "departure_time": "11:00",
                        "arrival_time": "23:40",
                        "stops": 0,
                    },
                }
            ]
        }
        visa = {"requirement": {"visa_type": "visa-free", "max_stay_days": 90}}
        weather = {
            "days": [
                {"date": _DEP.isoformat(), "description": "Heavy rain", "is_poor": True}
            ]
        }
        prompt = StressTestAgent.build_prompt(
            _request(), _itinerary(), flights, visa, weather
        )
        assert "23:40" in prompt
        assert "visa-free" in prompt
        assert "Heavy rain" in prompt

    def test_multi_city_destination_label(self):
        req = _request(destinations=["Paris", "Rome"])
        prompt = StressTestAgent.build_prompt(req, _itinerary(), None, None, None)
        assert "Paris → Rome" in prompt

    def test_handles_malformed_slots_and_dates(self):
        itinerary = {
            "days": [
                {"day_number": 1, "date": "not-a-date", "slots": [{}]},
                {"day_number": 2, "slots": None},
            ]
        }
        prompt = StressTestAgent.build_prompt(_request(), itinerary, {}, {}, {})
        assert "Day 1" in prompt


class TestRunGuards:
    @pytest.mark.anyio
    async def test_no_itinerary_returns_error(self):
        from app.core.config import settings

        agent = StressTestAgent(settings.agents_dir)
        result = await agent.run(_request(), itinerary=None)
        assert "error" in result
        result = await agent.run(_request(), itinerary={"days": []})
        assert "error" in result


class TestStressTestRoute:
    def test_route_returns_agent_verdict(self, client):
        verdict = {
            "overall": "amber",
            "summary": "One timing risk.",
            "score": 78,
            "findings": [
                {
                    "severity": "high",
                    "category": "timing",
                    "day_number": 1,
                    "issue": "Late arrival",
                    "suggestion": "Shift Day 1 morning",
                }
            ],
        }
        with patch.object(
            StressTestAgent, "execute", new=AsyncMock(return_value=verdict)
        ):
            r = client.post(
                "/api/stress-test",
                json={
                    "origin": "New York",
                    "destination": "Tokyo",
                    "departure_date": _DEP.isoformat(),
                    "return_date": _RET.isoformat(),
                    "nationality": "American",
                    "itinerary": _itinerary(),
                },
            )
        assert r.status_code == 200
        assert r.json()["overall"] == "amber"
        assert r.json()["findings"][0]["category"] == "timing"

    def test_route_rejects_missing_itinerary(self, client):
        r = client.post(
            "/api/stress-test",
            json={
                "origin": "New York",
                "destination": "Tokyo",
                "departure_date": _DEP.isoformat(),
                "nationality": "American",
            },
        )
        assert r.status_code == 422
