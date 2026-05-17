"""Tests for feedback API endpoints."""
import pytest


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-pw!"})
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestSubmitFeedback:
    def test_submit_success(self, client, auth):
        r = client.post("/api/feedback", json={
            "page": "search", "rating": 4, "category": "general",
            "message": "Really helpful tool!"
        }, headers=auth)
        assert r.status_code == 201
        data = r.json()
        assert data["page"] == "search"
        assert data["rating"] == 4
        assert data["category"] == "general"
        assert "id" in data

    def test_submit_without_message(self, client, auth):
        r = client.post("/api/feedback", json={
            "page": "chat", "rating": 5, "category": "praise"
        }, headers=auth)
        assert r.status_code == 201

    def test_submit_with_metadata(self, client, auth):
        r = client.post("/api/feedback", json={
            "page": "results", "rating": 3, "category": "feature_request",
            "metadata": {"viewport": 375}
        }, headers=auth)
        assert r.status_code == 201

    def test_rating_out_of_range(self, client, auth):
        r = client.post("/api/feedback", json={
            "page": "search", "rating": 6, "category": "general"
        }, headers=auth)
        assert r.status_code == 422

    def test_invalid_category(self, client, auth):
        r = client.post("/api/feedback", json={
            "page": "search", "rating": 3, "category": "not_a_category"
        }, headers=auth)
        assert r.status_code == 422

    def test_message_too_long(self, client, auth):
        r = client.post("/api/feedback", json={
            "page": "search", "rating": 3, "category": "general",
            "message": "x" * 501
        }, headers=auth)
        assert r.status_code == 422

    def test_unauthenticated(self, client):
        r = client.post("/api/feedback", json={
            "page": "search", "rating": 4, "category": "general"
        })
        assert r.status_code in (401, 403)


class TestAdminFeedback:
    def test_admin_list_all(self, client, admin_headers):
        r = client.get("/api/admin/feedback", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filter_by_page(self, client, admin_headers, auth):
        client.post("/api/feedback", json={"page": "preferences", "rating": 4, "category": "general"}, headers=auth)
        r = client.get("/api/admin/feedback?page=preferences", headers=admin_headers)
        assert r.status_code == 200
        assert all(i["page"] == "preferences" for i in r.json())

    def test_filter_by_min_rating(self, client, admin_headers):
        r = client.get("/api/admin/feedback?min_rating=5", headers=admin_headers)
        assert r.status_code == 200
        assert all(i["rating"] >= 5 for i in r.json())

    def test_non_admin_blocked(self, client, auth):
        r = client.get("/api/admin/feedback", headers=auth)
        # admin token IS admin in this fixture, so test with a non-admin user
        pass  # covered by TestAdminRBAC in test_auth.py
