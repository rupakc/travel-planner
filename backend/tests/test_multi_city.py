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
        assert req.city_stays is None
        assert req.flight_legs is None

    def test_city_stays_cover_exact_trip_dates(self):
        req = TravelSearchRequest(**MULTI)  # 9 days, 3 cities
        stays = req.city_stays
        assert [s["city"] for s in stays] == req.destinations
        assert stays[0]["start_date"] == req.departure_date
        assert stays[-1]["end_date"] == req.return_date
        for prev, nxt in zip(stays, stays[1:]):
            assert prev["end_date"] == nxt["start_date"]
        assert sum(s["nights"] for s in stays) == 9

    def test_flight_legs_cover_every_hop(self):
        req = TravelSearchRequest(**MULTI)
        legs = req.flight_legs
        assert len(legs) == 4  # origin→P, P→R, R→B, B→origin
        assert legs[0] == {
            "from": "New York, USA",
            "to": "Paris, France",
            "date": req.departure_date,
        }
        assert legs[1]["from"] == "Paris, France"
        assert legs[1]["to"] == "Rome, Italy"
        assert legs[-1] == {
            "from": "Barcelona, Spain",
            "to": "New York, USA",
            "date": req.return_date,
        }

    def test_flight_legs_without_return_date_skip_final_leg(self):
        req = TravelSearchRequest(**{**MULTI, "return_date": None})
        legs = req.flight_legs
        assert len(legs) == 3
        assert legs[-1]["to"] == "Barcelona, Spain"


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
    async def test_flights_prompt_covers_every_leg(self, monkeypatch):
        from app.agents import flights_agent as fa_mod
        from app.agents.flights_agent import FlightsAgent

        # Force the AI-agent path — never call the real SerpAPI in tests
        monkeypatch.setattr(fa_mod.settings, "serpapi_key", "")
        agent = _agent_with_mock_execute(FlightsAgent)
        await agent.run(TravelSearchRequest(**MULTI))
        prompt = agent.execute.call_args[0][0]
        assert "EVERY leg" in prompt
        assert "Leg 1: New York, USA → Paris, France" in prompt
        assert "Paris, France → Rome, Italy" in prompt
        assert "Rome, Italy → Barcelona, Spain" in prompt
        assert "Barcelona, Spain → New York, USA" in prompt
        assert "leg_index" in prompt

    @pytest.mark.anyio
    async def test_sim_tips_getting_around_prompts_cover_all_cities(self, monkeypatch):
        from app.agents.getting_around_agent import GettingAroundAgent
        from app.agents.sim_agent import SimAgent
        from app.agents.tips_agent import TipsAgent

        for cls in (SimAgent, TipsAgent, GettingAroundAgent):
            agent = _agent_with_mock_execute(cls)
            await agent.run(TravelSearchRequest(**MULTI))
            prompt = agent.execute.call_args[0][0]
            assert "MULTI-CITY" in prompt, cls.__name__
            assert "Barcelona, Spain" in prompt, cls.__name__
            assert "'city' field" in prompt, cls.__name__

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


class TestCityIataLookup:
    def test_resolves_known_cities(self, client):
        from app.db.database import lookup_city_iata

        codes = lookup_city_iata("Rome, Italy")
        assert codes and "FCO" in codes
        assert lookup_city_iata("Paris") is not None
        assert lookup_city_iata("LHR") == "LHR"  # bare IATA passes through

    def test_unknown_city_returns_none(self, client):
        from app.db.database import lookup_city_iata

        assert lookup_city_iata("Atlantis") is None
        assert lookup_city_iata("") is None


class TestFlightLegGrouping:
    def test_groups_flat_results_into_legs(self):
        from app.agents.flights_agent import FlightsAgent

        req = TravelSearchRequest(**MULTI)
        data = {
            "results": [
                {"price_usd": 300, "leg_index": 0},
                {"price_usd": 90, "leg_index": 1},
                {"price_usd": 120, "leg_index": "3"},
                {"price_usd": 999, "leg_index": 99},  # dropped — no such leg
                {"price_usd": 999, "leg_index": "bad"},  # dropped — malformed
            ]
        }
        grouped = FlightsAgent._group_legs(data, req.flight_legs)
        assert grouped["trip_type"] == "multi_city"
        assert len(grouped["legs"]) == 4
        assert grouped["legs"][0]["results"][0]["price_usd"] == 300
        assert grouped["legs"][0]["label"] == "New York, USA → Paris, France"
        assert grouped["legs"][3]["results"][0]["price_usd"] == 120
        assert grouped["legs"][3]["results"][0]["city"] == "New York, USA"
        assert grouped["legs"][2]["results"] == []

    def test_error_payload_passes_through(self):
        from app.agents.flights_agent import FlightsAgent

        req = TravelSearchRequest(**MULTI)
        data = {"error": "boom"}
        assert FlightsAgent._group_legs(data, req.flight_legs) == data


class TestSerpMultiCity:
    @pytest.mark.anyio
    async def test_searches_every_leg(self, client, monkeypatch):
        from app.services import serp_flights

        calls = []

        async def fake_call(params):
            calls.append((params["departure_id"], params["arrival_id"]))
            return {
                "best_flights": [
                    {
                        "price": 200,
                        "flights": [
                            {
                                "airline": "TestAir",
                                "flight_number": "TA1",
                                "departure_airport": {
                                    "id": params["departure_id"],
                                    "time": "2026-09-01 10:00",
                                },
                                "arrival_airport": {
                                    "id": params["arrival_id"],
                                    "time": "2026-09-01 12:00",
                                },
                                "duration": 120,
                            }
                        ],
                        "layovers": [],
                    }
                ],
                "other_flights": [],
            }

        monkeypatch.setattr(serp_flights, "_call", fake_call)
        req = TravelSearchRequest(**{**MULTI, "origin": "JFK"})
        result = await serp_flights.search_multi_city("key", req)

        assert result["trip_type"] == "multi_city"
        assert len(result["legs"]) == 4
        assert len(calls) == 4  # one SerpAPI search per leg
        first = result["legs"][0]["results"][0]
        assert first["leg_index"] == 0
        assert first["leg_from"] == "New York, United States"
        assert first["city"] == "Paris, France"
        # Flattened results keep the cheapest-flight metrics working
        assert len(result["results"]) == 4

    @pytest.mark.anyio
    async def test_all_legs_failing_raises(self, client, monkeypatch):
        from app.services import serp_flights
        from app.services.serp_flights import SerpAPIError

        async def fake_call(params):
            raise SerpAPIError("down")

        monkeypatch.setattr(serp_flights, "_call", fake_call)
        req = TravelSearchRequest(
            **{
                **MULTI,
                "origin": "JFK",
                "departure_date": "2026-10-01",
                "return_date": "2026-10-10",
            }
        )
        with pytest.raises(SerpAPIError):
            await serp_flights.search_multi_city("key", req)


class TestWeatherMultiCity:
    @pytest.mark.anyio
    async def test_days_labeled_per_city(self, monkeypatch):
        from app.agents.weather_agent import WeatherAgent

        agent = WeatherAgent.__new__(WeatherAgent)

        async def fake_meteo(coords, dep, ret):
            return {
                "days": [
                    {"date": str(dep), "is_poor": False},
                    {"date": str(ret), "is_poor": True},
                ],
                "poor_weather_day_count": 1,
                "source": "open-meteo",
            }

        agent._fetch_open_meteo = fake_meteo
        # Trip starting today so the 16-day forecast window applies
        from datetime import date, timedelta

        dep = date.today() + timedelta(days=1)
        req = TravelSearchRequest(
            **{
                **MULTI,
                "departure_date": str(dep),
                "return_date": str(dep + timedelta(days=9)),
            }
        )
        result = await agent.run(req)
        cities = {d["city"] for d in result["days"]}
        assert cities == {"Paris, France", "Rome, Italy", "Barcelona, Spain"}
        assert result["poor_weather_day_count"] == 3
        assert result["source"] == "open-meteo"


class TestOrchestratorWiring:
    def test_orchestrator_passes_destinations_to_itinerary(self):
        import inspect

        from app.agents import orchestrator as orch_mod

        source = inspect.getsource(orch_mod)
        # Every itinerary.run call site must forward request.destinations
        call_count = source.count("self.itinerary.run(")
        forwarded = source.count("destinations=request.destinations")
        assert call_count == forwarded == 3
