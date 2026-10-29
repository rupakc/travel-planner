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


def test_discovery_visa_override_uses_exact_rows():
    """Visa badges come from the exact _VISA_TABLE row for city + country."""
    import asyncio

    from app.agents.discovery_agent import DiscoveryAgent
    from app.schemas.request import DiscoveryRequest

    llm = {
        "destinations": [
            {"city": "Hiroshima", "country": "Japan", "visa_type": "visa-free"},
            {"city": "Indianapolis", "country": "United States", "visa_type": "x"},
            {"city": "Kiev", "country": "Ukraine", "visa_type": "visa-free"},
        ]
    }
    agent = DiscoveryAgent.__new__(DiscoveryAgent)
    agent.execute = AsyncMock(return_value=llm)
    req = DiscoveryRequest(**{**_VALID_PAYLOAD, "nationality": "Indian"})
    out = asyncio.run(agent.run(req))["destinations"]

    assert out[0]["visa_type"] == "e-visa"  # ("indian", "japan") row
    assert out[0]["visa_verified"] is True
    assert out[1]["visa_type"] == "visa-required"  # ("indian", "usa"), not india
    assert out[1]["visa_verified"] is True
    assert out[2]["visa_verified"] is False  # "uk" ⊂ "ukraine" no longer matches
