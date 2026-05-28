"""Tests for the /api/discover endpoint."""

from unittest.mock import AsyncMock, patch

_FAKE_RESULT = {
    "destinations": [
        {
            "city": "Lisbon",
            "country": "Portugal",
            "estimated_cost_usd_low": 1400,
            "estimated_cost_usd_high": 2200,
            "visa_type": "visa-free",
            "visa_verified": True,
            "weather_emoji": "☀️",
            "weather_description": "Warm and sunny, 22–26°C in April",
            "flight_duration_hours": 8.5,
            "flight_duration_label": "~8h 30m from New York",
            "match_reasons": ["Great food", "Rich history"],
            "highlights": ["Alfama", "Sintra"],
        }
    ]
}

_VALID_PAYLOAD = {
    "origin": "New York",
    "nationality": "American",
    "departure_date": "2026-08-01",
    "return_date": "2026-08-08",
    "budget_usd": 3000,
    "interests": ["food", "history"],
    "adults": 1,
    "children": 0,
    "seniors": 0,
    "infants": 0,
}


def test_discover_success(client):
    with patch("app.api.routes.discover.get_discovery_agent") as mock_factory:
        agent = mock_factory.return_value
        agent.run = AsyncMock(return_value=_FAKE_RESULT)

        r = client.post("/api/discover", json=_VALID_PAYLOAD)

    assert r.status_code == 200
    data = r.json()
    assert "destinations" in data
    assert data["destinations"][0]["city"] == "Lisbon"


def test_discover_cache_hit(client):
    """Second identical request returns cached result without calling the agent."""
    with patch("app.api.routes.discover.get_discovery_agent") as mock_factory:
        agent = mock_factory.return_value
        agent.run = AsyncMock(return_value=_FAKE_RESULT)

        # Prime the cache
        client.post("/api/discover", json=_VALID_PAYLOAD)
        # Second call
        r = client.post("/api/discover", json=_VALID_PAYLOAD)

    assert r.status_code == 200


def test_discover_agent_error_returns_500(client):
    payload = {**_VALID_PAYLOAD, "budget_usd": 9999}  # distinct cache key
    with patch("app.api.routes.discover.get_discovery_agent") as mock_factory:
        agent = mock_factory.return_value
        agent.run = AsyncMock(side_effect=RuntimeError("agent boom"))

        r = client.post("/api/discover", json=payload)

    assert r.status_code == 500
    assert "Discovery failed" in r.json()["detail"]


def test_discover_timeout_returns_504(client):
    payload = {**_VALID_PAYLOAD, "budget_usd": 8888}  # distinct cache key
    with (
        patch("app.api.routes.discover.get_discovery_agent") as mock_factory,
        patch(
            "app.api.routes.discover.asyncio.wait_for",
            side_effect=TimeoutError,
        ),
    ):
        agent = mock_factory.return_value
        agent.run = AsyncMock(return_value=_FAKE_RESULT)

        r = client.post("/api/discover", json=payload)

    assert r.status_code == 504
    assert "timed out" in r.json()["detail"].lower()


def test_discover_missing_required_fields(client):
    r = client.post("/api/discover", json={"origin": "New York"})
    assert r.status_code == 422
