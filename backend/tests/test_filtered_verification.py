"""Filtered search endpoints attach a final (non-pending) verification."""

from unittest.mock import AsyncMock, patch

import pytest

_PAYLOAD = {
    "origin": "NYC",
    "destination": "Tokyo",
    "departure_date": "2026-11-01",
    "return_date": "2026-11-08",
    "interests": ["food"],
    "nationality": "American",
    "budget_usd": 3000,
    "num_travelers": 1,
}


def _mock_agent(cls_path: str, run_result: dict, enrich_result: dict):
    patcher = patch(cls_path)
    factory = patcher.start()
    agent = factory.return_value
    agent.run = AsyncMock(return_value=run_result)
    agent.enrich = AsyncMock(return_value=enrich_result)
    return patcher, agent


@pytest.mark.parametrize(
    ("path", "cls_path", "enriched", "level", "counts"),
    [
        (
            "/api/hotels/filtered",
            "app.api.routes.hotels.HotelsAgent",
            {"results": [{"name": "A", "link_verified": True}]},
            "verified",
            (1, 1),
        ),
        (
            "/api/activities/filtered",
            "app.api.routes.activities.ActivitiesAgent",
            {
                "results": [
                    {"name": "A", "link_checked": True, "link_verified": True},
                    {"name": "B", "link_checked": True},
                ]
            },
            "partial",
            (1, 2),
        ),
        (
            "/api/flights/filtered",
            "app.api.routes.flights.FlightsAgent",
            {"results": [{"airline": "JAL", "live_fare": True}]},
            "verified",
            (1, 1),
        ),
    ],
)
def test_filtered_route_attaches_verification(
    client, path, cls_path, enriched, level, counts
):
    patcher, _agent = _mock_agent(cls_path, {"results": []}, enriched)
    try:
        r = client.post(path, json=_PAYLOAD)
    finally:
        patcher.stop()
    assert r.status_code == 200, r.text
    v = r.json()["verification"]
    assert v["pending"] is False
    assert v["level"] == level
    assert (v["items_verified"], v["items_total"]) == counts


@pytest.mark.parametrize(
    ("path", "cls_path"),
    [
        ("/api/hotels/filtered", "app.api.routes.hotels.HotelsAgent"),
        ("/api/activities/filtered", "app.api.routes.activities.ActivitiesAgent"),
        ("/api/flights/filtered", "app.api.routes.flights.FlightsAgent"),
    ],
)
def test_filtered_route_error_has_no_verification(client, path, cls_path):
    patcher, agent = _mock_agent(cls_path, {"error": "boom"}, {})
    try:
        r = client.post(path, json=_PAYLOAD)
    finally:
        patcher.stop()
    assert r.status_code == 200
    body = r.json()
    assert body["error"] == "boom"
    assert "verification" not in body
    agent.enrich.assert_not_called()
