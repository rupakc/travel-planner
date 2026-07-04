"""Tests for shareable trip cards — token lifecycle and public sanitized access."""

SEARCH_DATA = {
    "origin": "New York, USA",
    "destination": "Tokyo, Japan",
    "departure_date": "2026-08-10",
    "return_date": "2026-08-17",
    "interests": ["food"],
    "nationality": "American",
    "residence_permits": ["Schengen"],
    "existing_visas": ["UK"],
    "accessibility_needs": ["wheelchair"],
    "num_travelers": 2,
}

SELECTIONS = {
    "hotel": {"name": "Park Hyatt", "star_rating": 5.0},
    "activities": [],
    "events": [{"name": "Sumida Fireworks", "category": "festival"}],
}


def _create_plan(client, admin_headers, name="Share me"):
    resp = client.post(
        "/api/plans",
        json={"name": name, "search_data": SEARCH_DATA, "selections": SELECTIONS},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    return resp.json()["id"]


class TestShareLifecycle:
    def test_share_revoke_roundtrip(self, client, admin_headers):
        plan_id = _create_plan(client, admin_headers)

        resp = client.post(f"/api/plans/{plan_id}/share", headers=admin_headers)
        assert resp.status_code == 200
        token = resp.json()["share_token"]
        assert len(token) >= 16

        # Sharing again returns the SAME stable token
        again = client.post(f"/api/plans/{plan_id}/share", headers=admin_headers)
        assert again.json()["share_token"] == token

        # Public access works with NO auth headers
        public = client.get(f"/api/share/{token}")
        assert public.status_code == 200
        body = public.json()
        assert body["name"] == "Share me"
        assert body["selections"]["hotel"]["name"] == "Park Hyatt"
        assert body["selections"]["events"][0]["name"] == "Sumida Fireworks"

        # Revoke kills the link
        revoke = client.delete(f"/api/plans/{plan_id}/share", headers=admin_headers)
        assert revoke.status_code == 200
        assert client.get(f"/api/share/{token}").status_code == 404

        client.delete(f"/api/plans/{plan_id}", headers=admin_headers)

    def test_share_requires_auth_and_ownership(self, client, admin_headers):
        plan_id = _create_plan(client, admin_headers)
        assert client.post(f"/api/plans/{plan_id}/share").status_code in (401, 403)
        assert (
            client.post("/api/plans/999999/share", headers=admin_headers).status_code
            == 404
        )
        client.delete(f"/api/plans/{plan_id}", headers=admin_headers)

    def test_unknown_token_404(self, client):
        assert client.get("/api/share/not-a-real-token").status_code == 404


class TestSanitization:
    def test_public_view_drops_personal_fields(self, client, admin_headers):
        plan_id = _create_plan(client, admin_headers, name="Sanitized")
        token = client.post(
            f"/api/plans/{plan_id}/share", headers=admin_headers
        ).json()["share_token"]

        body = client.get(f"/api/share/{token}").json()
        sd = body["search_data"]
        assert "nationality" not in sd
        assert "residence_permits" not in sd
        assert "existing_visas" not in sd
        assert "accessibility_needs" not in sd
        assert "username" not in body
        assert "id" not in body
        assert "share_token" not in body
        # Non-personal trip facts survive
        assert sd["destination"] == "Tokyo, Japan"
        assert sd["num_travelers"] == 2

        client.delete(f"/api/plans/{plan_id}", headers=admin_headers)
