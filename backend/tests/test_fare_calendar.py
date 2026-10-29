"""Fare calendar (±3 days) and Google Flights price_insights passthrough.

No network: SerpAPI `_call` (or the HTTP client) is always mocked.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.cache import get_cache
from app.core.config import settings
from app.schemas.request import TravelSearchRequest
from app.services import serp_flights
from app.services.serp_flights import SerpAPIError, search, search_calendar

API_KEY = "test-key"
TODAY = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr("app.db.database.lookup_iata", lambda code: None)
    monkeypatch.setattr(serp_flights, "_today", lambda: TODAY)
    get_cache().clear()
    yield
    get_cache().clear()


def _req(dep="2026-10-20", ret="2026-10-27", travelers=2, **extra):
    return TravelSearchRequest(
        origin="JFK",
        destination="NRT",
        departure_date=date.fromisoformat(dep),
        return_date=date.fromisoformat(ret) if ret else None,
        nationality="American",
        num_travelers=travelers,
        **extra,
    )


def _serp(prices, insights=None):
    data = {
        "best_flights": [{"price": p, "flights": [], "layovers": []} for p in prices],
        "other_flights": [],
    }
    if insights is not None:
        data["price_insights"] = insights
    return data


INSIGHTS = {
    "lowest_price": 512,
    "price_level": "low",
    "typical_price_range": [600, 820],
    "price_history": [[1727740800, 650], [1727827200, 512]],
}


# ── price_insights passthrough ────────────────────────────────────────────────


def _flight(price):
    return {
        "flights": [
            {
                "airline": "JAL",
                "flight_number": "JL5",
                "departure_airport": {"id": "JFK", "time": "2026-10-20 10:00"},
                "arrival_airport": {"id": "NRT", "time": "2026-10-21 14:00"},
                "duration": 840,
            }
        ],
        "layovers": [],
        "price": price,
        "departure_token": f"tok{price}",
    }


def _mock_client(responses):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[httpx.Response(200, json=r) for r in responses])
    return patch("app.services.serp_flights._get_client", return_value=client)


@pytest.mark.asyncio
async def test_one_way_search_includes_price_insights():
    data = {"best_flights": [_flight(512)], "other_flights": []}
    data["price_insights"] = {**INSIGHTS, "junk": "x"}
    with _mock_client([data]):
        result = await search(API_KEY, _req(ret=None))
    assert result["price_insights"] == INSIGHTS


@pytest.mark.asyncio
async def test_round_trip_takes_insights_from_outbound_call():
    outbound = {"best_flights": [_flight(700)], "other_flights": []}
    outbound["price_insights"] = INSIGHTS
    returns = {"best_flights": [_flight(900)], "other_flights": []}
    returns["price_insights"] = {"price_level": "high"}
    with _mock_client([outbound, returns]):
        result = await search(API_KEY, _req())
    assert result["price_insights"] == INSIGHTS


@pytest.mark.asyncio
async def test_missing_or_bad_insights_are_omitted():
    data = {"best_flights": [_flight(512)], "other_flights": []}
    with _mock_client([data]):
        result = await search(API_KEY, _req(ret=None))
    assert "price_insights" not in result

    get_cache().clear()
    data["price_insights"] = {"price_level": "astronomical", "lowest_price": "cheap"}
    with _mock_client([data]):
        result = await search(API_KEY, _req(ret=None))
    assert "price_insights" not in result


def test_model_cannot_supply_price_insights():
    from app.agents.flights_agent import strip_live_fare
    from app.services.verification import verify_section

    data = {"results": [{"price_usd": 400}], "price_insights": INSIGHTS}
    out = strip_live_fare(data)
    assert "price_insights" not in out
    assert verify_section("flights", out, _req())["level"] == "unverified"


def test_price_insights_do_not_change_verification():
    from app.services.verification import verify_section

    live = {"results": [{"price_usd": 400, "live_fare": True}]}
    with_insights = {**live, "price_insights": INSIGHTS}
    assert verify_section("flights", with_insights, _req()) == verify_section(
        "flights", live, _req()
    )


# ── search_calendar ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_shifts_both_dates_and_takes_cheapest():
    calls = []

    async def fake_call(params):
        calls.append(params)
        day = int(params["outbound_date"][-2:])
        return _serp([day * 10 + 5, day * 10])

    with patch.object(serp_flights, "_call", side_effect=fake_call):
        out = await search_calendar(API_KEY, _req())

    assert out["currency"] == "USD"
    assert out["source"] == "google_flights"
    assert [d["departure_date"] for d in out["dates"]] == [
        f"2026-10-{d}" for d in range(17, 24)
    ]
    assert [d["return_date"] for d in out["dates"]] == [
        f"2026-10-{d}" for d in range(24, 31)
    ]
    assert [d["cheapest_usd"] for d in out["dates"]] == [
        d * 10.0 for d in range(17, 24)
    ]
    assert [d["is_selected"] for d in out["dates"]] == [False] * 3 + [True] + [
        False
    ] * 3
    # One outbound call per date, no departure_token (return-leg) calls
    assert len(calls) == 7
    assert all("departure_token" not in p for p in calls)
    assert all(p["adults"] == "2" and p["type"] == "1" for p in calls)


@pytest.mark.asyncio
async def test_one_way_window_has_no_return_dates():
    with patch.object(serp_flights, "_call", AsyncMock(return_value=_serp([300]))):
        out = await search_calendar(API_KEY, _req(ret=None))
    assert len(out["dates"]) == 7
    assert all(d["return_date"] is None for d in out["dates"])


@pytest.mark.asyncio
async def test_dates_before_tomorrow_are_skipped():
    mock = AsyncMock(return_value=_serp([300]))
    with patch.object(serp_flights, "_call", mock):
        out = await search_calendar(API_KEY, _req(dep="2026-10-03", ret="2026-10-05"))
    # 2026-09-30, 10-01 (today) skipped; 10-02 (tomorrow) onward kept
    assert [d["departure_date"] for d in out["dates"]] == [
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-05",
        "2026-10-06",
    ]
    assert mock.await_count == 5


@pytest.mark.asyncio
async def test_failed_date_is_null_not_error():
    async def fake_call(params):
        if params["outbound_date"] == "2026-10-18":
            raise SerpAPIError("boom")
        if params["outbound_date"] == "2026-10-19":
            return _serp([])
        return _serp([400])

    with patch.object(serp_flights, "_call", side_effect=fake_call):
        out = await search_calendar(API_KEY, _req())
    prices = {d["departure_date"]: d["cheapest_usd"] for d in out["dates"]}
    assert prices["2026-10-18"] is None
    assert prices["2026-10-19"] is None
    assert prices["2026-10-20"] == 400.0


@pytest.mark.asyncio
async def test_per_date_cache_hit_skips_calls():
    mock = AsyncMock(return_value=_serp([400]))
    with patch.object(serp_flights, "_call", mock):
        await search_calendar(API_KEY, _req())
        assert mock.await_count == 7
        assert get_cache()["serp-cal:JFK:NRT:2026-10-17:2026-10-24:2"] == 400.0
        again = await search_calendar(API_KEY, _req())
    assert mock.await_count == 7
    assert [d["cheapest_usd"] for d in again["dates"]] == [400.0] * 7


@pytest.mark.asyncio
async def test_failures_are_not_cached():
    failing = AsyncMock(side_effect=SerpAPIError("down"))
    with patch.object(serp_flights, "_call", failing):
        await search_calendar(API_KEY, _req())
    ok = AsyncMock(return_value=_serp([400]))
    with patch.object(serp_flights, "_call", ok):
        out = await search_calendar(API_KEY, _req())
    assert ok.await_count == 7
    assert all(d["cheapest_usd"] == 400.0 for d in out["dates"])


@pytest.mark.asyncio
async def test_selected_date_reuses_cached_main_search():
    req = _req()
    get_cache()[f"serp:JFK:NRT:2026-10-20:2026-10-27:{hash(())}"] = {
        "results": [{"price_usd": 777.0}, {"price_usd": 650.0}]
    }
    mock = AsyncMock(return_value=_serp([400]))
    with patch.object(serp_flights, "_call", mock):
        out = await search_calendar(API_KEY, req)
    assert mock.await_count == 6
    selected = next(d for d in out["dates"] if d["is_selected"])
    assert selected["cheapest_usd"] == 650.0


@pytest.mark.asyncio
async def test_concurrency_is_limited_to_four():
    import asyncio

    active = peak = 0

    async def fake_call(params):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _serp([400])

    with patch.object(serp_flights, "_call", side_effect=fake_call):
        await search_calendar(API_KEY, _req())
    assert peak == 4


@pytest.mark.asyncio
async def test_concurrent_calendars_share_in_flight_lookups():
    """Two overlapping requests (StrictMode double mount, two tabs) make one
    SerpAPI call per date between them."""
    import asyncio

    calls = []

    async def fake_call(params):
        calls.append(params["outbound_date"])
        await asyncio.sleep(0.01)
        return _serp([400])

    with patch.object(serp_flights, "_call", side_effect=fake_call):
        a, b = await asyncio.gather(
            search_calendar(API_KEY, _req()), search_calendar(API_KEY, _req())
        )
    assert len(calls) <= 7
    assert sorted(calls) == sorted(set(calls))
    assert a == b
    assert all(d["cheapest_usd"] == 400.0 for d in a["dates"])
    assert serp_flights._calendar_inflight == {}


@pytest.mark.asyncio
async def test_selected_date_prefers_cached_lowest_price_insight():
    get_cache()[f"serp:JFK:NRT:2026-10-20:2026-10-27:{hash(())}"] = {
        "results": [{"price_usd": 777.0}, {"price_usd": 650.0}],
        "price_insights": {"lowest_price": 598, "price_level": "typical"},
    }
    mock = AsyncMock(return_value=_serp([400]))
    with patch.object(serp_flights, "_call", mock):
        out = await search_calendar(API_KEY, _req())
    assert mock.await_count == 6
    selected = next(d for d in out["dates"] if d["is_selected"])
    assert selected["cheapest_usd"] == 598.0


@pytest.mark.asyncio
async def test_any_error_for_one_date_is_null():
    async def fake_call(params):
        if params["outbound_date"] == "2026-10-18":
            raise ValueError("Expecting value: line 1 column 1")  # non-JSON 200
        if params["outbound_date"] == "2026-10-19":
            return {"best_flights": "garbage"}
        return _serp([400])

    with patch.object(serp_flights, "_call", side_effect=fake_call):
        out = await search_calendar(API_KEY, _req())
    prices = {d["departure_date"]: d["cheapest_usd"] for d in out["dates"]}
    assert prices["2026-10-18"] is None
    assert prices["2026-10-19"] is None
    assert prices["2026-10-20"] == 400.0
    assert len(out["dates"]) == 7


@pytest.mark.asyncio
async def test_window_crosses_the_year_boundary():
    mock = AsyncMock(return_value=_serp([400]))
    with patch.object(serp_flights, "_call", mock):
        out = await search_calendar(API_KEY, _req(dep="2026-12-30", ret="2027-01-03"))
    assert [(d["departure_date"], d["return_date"]) for d in out["dates"]] == [
        ("2026-12-27", "2026-12-31"),
        ("2026-12-28", "2027-01-01"),
        ("2026-12-29", "2027-01-02"),
        ("2026-12-30", "2027-01-03"),
        ("2026-12-31", "2027-01-04"),
        ("2027-01-01", "2027-01-05"),
        ("2027-01-02", "2027-01-06"),
    ]


# ── Route ─────────────────────────────────────────────────────────────────────

_BODY = {
    "origin": "JFK",
    "destination": "NRT",
    "departure_date": "2026-10-20",
    "return_date": "2026-10-27",
    "nationality": "American",
}


def test_route_requires_auth(client):
    r = client.post("/api/flights/fare-calendar", json=_BODY)
    assert r.status_code == 401


def test_route_503_without_serpapi_key(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "")
    r = client.post("/api/flights/fare-calendar", json=_BODY, headers=admin_headers)
    assert r.status_code == 503
    assert r.json() == {
        "detail": "Fare calendar needs live flight data, which isn't configured."
    }


def test_route_422_for_multi_city(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "k")
    body = {**_BODY, "destinations": ["Osaka", "NRT"]}
    with patch("app.api.routes.flights.search_calendar") as cal:
        r = client.post("/api/flights/fare-calendar", json=body, headers=admin_headers)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    cal.assert_not_called()


def test_route_returns_calendar(client, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "serpapi_key", "k")
    with patch.object(serp_flights, "_call", AsyncMock(return_value=_serp([480]))):
        r = client.post("/api/flights/fare-calendar", json=_BODY, headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "USD" and body["source"] == "google_flights"
    assert len(body["dates"]) == 7
    assert set(body["dates"][0]) == {
        "departure_date",
        "return_date",
        "cheapest_usd",
        "is_selected",
    }
