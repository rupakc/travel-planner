"""Tests for analytics ingestion endpoint."""


class TestAnalyticsEvents:
    def test_batch_accepted(self, client, admin_headers):
        r = client.post("/api/analytics/events", json={
            "events": [
                {"feature": "search_submit", "page": "search", "metadata": {"destination": "Tokyo"}, "ts": 1000},
                {"feature": "page_view", "page": "chat", "ts": 1001},
            ]
        }, headers=admin_headers)
        assert r.status_code == 204

    def test_empty_batch(self, client, admin_headers):
        r = client.post("/api/analytics/events", json={"events": []}, headers=admin_headers)
        assert r.status_code == 204

    def test_oversized_batch_rejected(self, client, admin_headers):
        r = client.post("/api/analytics/events", json={
            "events": [{"feature": "x", "page": "y"} for _ in range(51)]
        }, headers=admin_headers)
        assert r.status_code == 422

    def test_unauthenticated_rejected(self, client):
        r = client.post("/api/analytics/events", json={
            "events": [{"feature": "x", "page": "y"}]
        })
        assert r.status_code in (401, 403)

    def test_feature_too_long(self, client, admin_headers):
        r = client.post("/api/analytics/events", json={
            "events": [{"feature": "x" * 65, "page": "search"}]
        }, headers=admin_headers)
        assert r.status_code == 422
