"""Unit tests for SerpAPI Google Flights service."""

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.schemas.request import TravelSearchRequest
from app.services.serp_flights import (
    SerpAPIError,
    _build_params,
    _pick_diverse_outbounds,
    _post_filter_arrival,
    search,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def mock_iata_lookup(monkeypatch):
    """Prevent IATA resolution from hitting the airports DB in unit tests."""
    monkeypatch.setattr("app.db.database.lookup_iata", lambda code: None)


@pytest.fixture(autouse=True)
def clear_serp_cache():
    """Clear the shared TTL cache before each test to prevent cross-test pollution."""
    from app.core.cache import get_cache

    get_cache().clear()
    yield
    get_cache().clear()


def _make_request(
    origin="LHR",
    destination="JFK",
    dep="2026-09-01",
    ret=None,
    travelers=1,
) -> TravelSearchRequest:
    return TravelSearchRequest(
        origin=origin,
        destination=destination,
        departure_date=date.fromisoformat(dep),
        return_date=date.fromisoformat(ret) if ret else None,
        nationality="British",
        num_travelers=travelers,
    )


def _make_serp_flight(
    price=800, dep_time="2026-09-01 08:00", arr_time="2026-09-01 11:00"
):
    return {
        "flights": [
            {
                "airline": "British Airways",
                "flight_number": "BA001",
                "departure_airport": {
                    "id": "LHR",
                    "name": "Heathrow",
                    "time": dep_time,
                },
                "arrival_airport": {"id": "JFK", "name": "JFK", "time": arr_time},
                "duration": 420,
                "often_delayed_by_over_30_min": False,
            }
        ],
        "layovers": [],
        "total_duration": 420,
        "price": price,
        "type": "One way",
        "departure_token": f"token_{price}",
        "carbon_emissions": {"this_flight": 350000},
    }


def _make_serp_response(flights=None):
    return {"best_flights": flights or [_make_serp_flight()], "other_flights": []}


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBuildParams:
    def test_one_way_type(self):
        req = _make_request()
        params = _build_params(API_KEY, req, None)
        assert params["type"] == "2"
        assert "return_date" not in params

    def test_round_trip_type(self):
        req = _make_request(ret="2026-09-08")
        params = _build_params(API_KEY, req, None)
        assert params["type"] == "1"
        assert params["return_date"] == "2026-09-08"

    def test_iata_used_when_available(self):
        req = _make_request(origin="LHR", destination="JFK")
        # validator sets origin_iata="LHR" for 3-letter codes
        assert req.origin_iata == "LHR"
        params = _build_params(API_KEY, req, None)
        assert params["departure_id"] == "LHR"
        assert params["arrival_id"] == "JFK"

    def test_filter_stops_mapping(self):
        req = _make_request()
        params = _build_params(API_KEY, req, {"max_stops": 0})
        assert params["stops"] == "1"  # nonstop only

        params = _build_params(API_KEY, req, {"max_stops": 1})
        assert params["stops"] == "2"  # ≤1 stop

        params = _build_params(API_KEY, req, {"max_stops": 2})
        assert params["stops"] == "3"  # ≤2 stops

    def test_filter_max_price(self):
        req = _make_request()
        params = _build_params(API_KEY, req, {"max_price_usd": 500.99})
        assert params["max_price"] == "500"

    def test_filter_departure_times(self):
        req = _make_request()
        params = _build_params(
            API_KEY,
            req,
            {"departure_time_earliest": "08:00", "departure_time_latest": "18:00"},
        )
        assert params["outbound_times"] == "8,18"


class TestPickDiverseOutbounds:
    def test_returns_up_to_three(self):
        # items[0] = cheapest (mid-day), items[1] = earliest, items[2] = latest
        # → all three are distinct so we get exactly 3 unique picks
        items = [
            _make_serp_flight(price=400, dep_time="2026-09-01 10:00"),  # cheapest
            _make_serp_flight(price=700, dep_time="2026-09-01 06:00"),  # earliest
            _make_serp_flight(price=600, dep_time="2026-09-01 20:00"),  # latest
            _make_serp_flight(price=500, dep_time="2026-09-01 14:00"),  # extra
        ]
        for i, item in enumerate(items):
            item["departure_token"] = f"tok{i}"
        result = _pick_diverse_outbounds(items, n=3)
        assert len(result) == 3
        tokens = {r["departure_token"] for r in result}
        assert len(tokens) == 3  # no duplicates

    def test_single_item(self):
        item = _make_serp_flight()
        result = _pick_diverse_outbounds([item])
        assert len(result) == 1


class TestPostFilterArrival:
    def test_filters_outside_window(self):
        results = [
            {"outbound": {"arrival_time": "07:00"}, "price_usd": 300},
            {"outbound": {"arrival_time": "12:00"}, "price_usd": 400},
            {"outbound": {"arrival_time": "20:00"}, "price_usd": 500},
        ]
        filtered = _post_filter_arrival(
            results,
            {"arrival_time_earliest": "09:00", "arrival_time_latest": "18:00"},
        )
        assert len(filtered) == 1
        assert filtered[0]["outbound"]["arrival_time"] == "12:00"

    def test_no_filters_returns_all(self):
        results = [{"outbound": {"arrival_time": "07:00"}}]
        assert _post_filter_arrival(results, None) == results


class TestSearchOneway:
    @pytest.mark.asyncio
    async def test_oneway_search_maps_correctly(self):
        serp_data = _make_serp_response([_make_serp_flight(price=450)])
        mock_resp = httpx.Response(200, json=serp_data)

        with patch("app.services.serp_flights._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            req = _make_request()
            result = await search(API_KEY, req)

        assert "results" in result
        assert len(result["results"]) == 1
        r = result["results"][0]
        assert r["price_usd"] == 450.0
        assert r["source"] == "google_flights"
        assert r["trip_type"] == "one_way"
        assert r["outbound"]["airline"] == "British Airways"
        assert r["outbound"]["origin"] == "LHR"
        assert r["return"] is None
        assert "google.com/flights" in r["booking_url"]

    @pytest.mark.asyncio
    async def test_serp_error_raises_exception(self):
        mock_resp = httpx.Response(429, text="Quota exceeded")

        with patch("app.services.serp_flights._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            req = _make_request()
            with pytest.raises(SerpAPIError) as exc_info:
                await search(API_KEY, req)
            assert exc_info.value.quota_exceeded is True

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self):
        serp_data = {"best_flights": [], "other_flights": []}
        mock_resp = httpx.Response(200, json=serp_data)

        with patch("app.services.serp_flights._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_client

            req = _make_request()
            result = await search(API_KEY, req)

        assert result == {"results": []}


class TestSearchRoundtrip:
    @pytest.mark.asyncio
    async def test_roundtrip_makes_multiple_calls(self):
        outbound_item = _make_serp_flight(price=400, dep_time="2026-09-01 08:00")
        outbound_item["departure_token"] = "out_token"

        return_item = {
            "flights": [
                {
                    "airline": "American Airlines",
                    "flight_number": "AA100",
                    "departure_airport": {"id": "JFK", "time": "2026-09-08 14:00"},
                    "arrival_airport": {"id": "LHR", "time": "2026-09-09 02:00"},
                    "duration": 480,
                    "often_delayed_by_over_30_min": False,
                }
            ],
            "layovers": [],
            "price": 850,
            "departure_token": "ret_token",
            "carbon_emissions": {},
        }

        call_count = 0

        async def mock_get(url, params=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200, json={"best_flights": [outbound_item], "other_flights": []}
                )
            return httpx.Response(
                200, json={"best_flights": [return_item], "other_flights": []}
            )

        with patch("app.services.serp_flights._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            req = _make_request(ret="2026-09-08")
            result = await search(API_KEY, req)

        # Call 1 (outbound) + at least 1 return call
        assert call_count >= 2
        assert len(result["results"]) >= 1
        r = result["results"][0]
        assert r["trip_type"] == "round_trip"
        assert r["outbound"]["airline"] == "British Airways"
        assert r["return"]["airline"] == "American Airlines"
        assert r["price_usd"] == 850.0
