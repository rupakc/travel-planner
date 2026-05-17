"""Tests for plans CRUD endpoints."""

import pytest


class TestPlans:
    def test_list_plans_empty(self, client, admin_headers):
        r = client.get("/api/plans", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_plan(self, client, admin_headers):
        r = client.post(
            "/api/plans",
            json={
                "name": "Tokyo Trip",
                "search_data": {"origin": "MUC", "destination": "TYO"},
                "selections": {"flight": None, "hotel": None, "activities": []},
            },
            headers=admin_headers,
        )
        assert r.status_code in (200, 201)
        data = r.json()
        assert data["name"] == "Tokyo Trip"
        assert "id" in data
        return data["id"]

    def test_get_plan(self, client, admin_headers):
        # Create first
        r = client.post(
            "/api/plans",
            json={
                "name": "Paris Plan",
                "search_data": {},
                "selections": {},
            },
            headers=admin_headers,
        )
        plan_id = r.json()["id"]

        r = client.get(f"/api/plans/{plan_id}", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["name"] == "Paris Plan"

    def test_update_plan(self, client, admin_headers):
        r = client.post(
            "/api/plans",
            json={
                "name": "Rome Plan",
                "search_data": {},
                "selections": {},
            },
            headers=admin_headers,
        )
        plan_id = r.json()["id"]

        r = client.put(
            f"/api/plans/{plan_id}",
            json={
                "name": "Rome Plan Updated",
                "selections": {"activities": ["Colosseum"]},
            },
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Rome Plan Updated"

    def test_delete_plan(self, client, admin_headers):
        r = client.post(
            "/api/plans",
            json={
                "name": "Delete Me",
                "search_data": {},
                "selections": {},
            },
            headers=admin_headers,
        )
        plan_id = r.json()["id"]

        r = client.delete(f"/api/plans/{plan_id}", headers=admin_headers)
        assert r.status_code in (200, 204)

        r = client.get(f"/api/plans/{plan_id}", headers=admin_headers)
        assert r.status_code == 404

    def test_plans_require_auth(self, client):
        r = client.get("/api/plans")
        assert r.status_code in (401, 403)
