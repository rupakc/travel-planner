"""Tests for the per-user recent searches endpoints."""

import uuid

import pytest

from app.db.recent_searches_db import MAX_RECENT_SEARCHES


def _search(**overrides) -> dict:
    data = {
        "origin": "New York, USA (JFK)",
        "destination": "Tokyo, Japan (HND)",
        "departure_date": "2027-04-01",
        "return_date": "2027-04-08",
        "stops": [],
        "nationality": "American",
        "residence_permits": [],
        "existing_visas": [],
        "interests": ["food", "history"],
        "budget_usd": 3000,
        "adults": 2,
        "children": 0,
        "seniors": 0,
        "infants": 0,
        "accessibility_needs": [],
        "serendipity": 0.5,
    }
    data.update(overrides)
    return data


@pytest.fixture
def user_headers(client, admin_headers):
    """A fresh user per test so recent-search lists never leak between tests."""
    username = f"recent_{uuid.uuid4().hex[:6]}"
    r = client.post(
        "/api/admin/users",
        json={"username": username, "password": "init-pw-123"},
        headers=admin_headers,
    )
    assert r.status_code in (200, 201), r.text
    r = client.post(
        "/api/auth/login", json={"username": username, "password": "init-pw-123"}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestRecentSearches:
    def test_requires_auth(self, client):
        assert client.get("/api/recent-searches").status_code in (401, 403)
        assert client.post("/api/recent-searches", json=_search()).status_code in (
            401,
            403,
        )

    def test_empty_for_new_user(self, client, user_headers):
        r = client.get("/api/recent-searches", headers=user_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_save_then_list_round_trips_search(self, client, user_headers):
        stops = [{"city": "Seoul, South Korea", "nights": 2}]
        r = client.post(
            "/api/recent-searches", json=_search(stops=stops), headers=user_headers
        )
        assert r.status_code == 200
        saved = r.json()
        assert saved["id"]
        assert saved["last_used_at"]
        assert saved["search"]["destination"] == "Tokyo, Japan (HND)"
        assert saved["search"]["stops"] == stops

        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert [e["id"] for e in listed] == [saved["id"]]
        assert listed[0]["search"]["interests"] == ["food", "history"]

    def test_most_recent_first(self, client, user_headers):
        for city in ("Paris, France", "Rome, Italy", "Lisbon, Portugal"):
            client.post(
                "/api/recent-searches",
                json=_search(destination=city),
                headers=user_headers,
            )
        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert [e["search"]["destination"] for e in listed] == [
            "Lisbon, Portugal",
            "Rome, Italy",
            "Paris, France",
        ]

    def test_exact_repeat_is_merged_and_moved_to_top(self, client, user_headers):
        first = client.post(
            "/api/recent-searches", json=_search(), headers=user_headers
        ).json()
        client.post(
            "/api/recent-searches",
            json=_search(destination="Paris, France"),
            headers=user_headers,
        )
        # Same search, interests in a different order — still the same search
        again = client.post(
            "/api/recent-searches",
            json=_search(interests=["history", "food"]),
            headers=user_headers,
        ).json()
        assert again["id"] == first["id"]

        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert len(listed) == 2
        assert listed[0]["id"] == first["id"]

    def test_changed_dates_are_a_different_search(self, client, user_headers):
        client.post("/api/recent-searches", json=_search(), headers=user_headers)
        client.post(
            "/api/recent-searches",
            json=_search(departure_date="2027-05-01", return_date="2027-05-08"),
            headers=user_headers,
        )
        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert len(listed) == 2

    def test_keeps_only_the_newest_entries(self, client, user_headers):
        total = MAX_RECENT_SEARCHES + 3
        for i in range(total):
            client.post(
                "/api/recent-searches",
                json=_search(destination=f"City {i}"),
                headers=user_headers,
            )
        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert len(listed) == MAX_RECENT_SEARCHES
        assert listed[0]["search"]["destination"] == f"City {total - 1}"
        assert (
            listed[-1]["search"]["destination"] == f"City {total - MAX_RECENT_SEARCHES}"
        )

    def test_repeat_at_the_cap_moves_to_top_without_evicting(
        self, client, user_headers
    ):
        for i in range(MAX_RECENT_SEARCHES):
            client.post(
                "/api/recent-searches",
                json=_search(destination=f"City {i}"),
                headers=user_headers,
            )
        # Re-run the oldest one: nothing new, so nothing should drop off
        client.post(
            "/api/recent-searches",
            json=_search(destination="City 0"),
            headers=user_headers,
        )
        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert len(listed) == MAX_RECENT_SEARCHES
        assert listed[0]["search"]["destination"] == "City 0"
        assert {e["search"]["destination"] for e in listed} == {
            f"City {i}" for i in range(MAX_RECENT_SEARCHES)
        }

    def test_one_day_trip_is_allowed(self, client, user_headers):
        r = client.post(
            "/api/recent-searches",
            json=_search(departure_date="2027-04-01", return_date="2027-04-01"),
            headers=user_headers,
        )
        assert r.status_code == 200

    def test_delete_removes_entry(self, client, user_headers):
        saved = client.post(
            "/api/recent-searches", json=_search(), headers=user_headers
        ).json()
        r = client.delete(f"/api/recent-searches/{saved['id']}", headers=user_headers)
        assert r.status_code == 204
        assert client.get("/api/recent-searches", headers=user_headers).json() == []

    def test_cannot_delete_another_users_entry(
        self, client, user_headers, admin_headers
    ):
        saved = client.post(
            "/api/recent-searches", json=_search(), headers=user_headers
        ).json()
        r = client.delete(f"/api/recent-searches/{saved['id']}", headers=admin_headers)
        assert r.status_code == 404
        listed = client.get("/api/recent-searches", headers=user_headers).json()
        assert len(listed) == 1

    def test_lists_are_per_user(self, client, user_headers, admin_headers):
        saved = client.post(
            "/api/recent-searches", json=_search(), headers=user_headers
        ).json()
        admins = client.get("/api/recent-searches", headers=admin_headers).json()
        assert saved["id"] not in {e["id"] for e in admins}

    @pytest.mark.parametrize(
        "bad",
        [
            {"destination": ""},
            {"origin": ""},
            {"departure_date": "not-a-date"},
            {"interests": ["x"] * 51},
            {"stops": [{"city": "A", "nights": 1}] * 4},
            {"adults": 99},
            {"serendipity": 2},
            {"interests": ["x" * 101]},
            {"existing_visas": ["x" * 101]},
            {"departure_date": "2027-04-08", "return_date": "2027-04-01"},
        ],
    )
    def test_rejects_invalid_payloads(self, client, user_headers, bad):
        r = client.post(
            "/api/recent-searches", json=_search(**bad), headers=user_headers
        )
        assert r.status_code == 422

    def test_optional_fields_take_defaults(self, client, user_headers):
        r = client.post(
            "/api/recent-searches",
            json={
                "origin": "London, UK",
                "destination": "Lisbon, Portugal",
                "departure_date": "2027-03-10",
            },
            headers=user_headers,
        )
        assert r.status_code == 200, r.text
        search = r.json()["search"]
        assert search["nationality"] == ""
        assert search["return_date"] is None
        assert search["interests"] == []
        assert search["adults"] == 1
