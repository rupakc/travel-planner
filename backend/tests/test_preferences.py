"""Tests for preferences endpoints."""


class TestPreferences:
    def test_get_preferences(self, client, admin_headers):
        r = client.get("/api/preferences", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "nationality" in data
        assert "interests" in data

    def test_update_preferences(self, client, admin_headers):
        r = client.put(
            "/api/preferences",
            json={
                "nationality": "German",
                "current_residence": "Munich, Germany",
                "residence_permits": ["Schengen"],
                "existing_visas": [],
                "interests": ["food", "history"],
                "num_travelers": 2,
                "budget_category": "medium",
            },
            headers=admin_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["nationality"] == "German"
        assert data["num_travelers"] == 2

    def test_preferences_require_auth(self, client):
        r = client.get("/api/preferences")
        assert r.status_code in (401, 403)
