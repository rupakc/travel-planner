"""Tests for auth endpoints and RBAC."""

import uuid


def _uid(prefix: str) -> str:
    """Return a test-run-unique username so tests don't collide across runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestLogin:
    def test_admin_login_success(self, client):
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-admin-pw!"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["is_admin"] is True
        assert data["user"]["requires_password_change"] is False

    def test_wrong_password(self, client):
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert r.status_code == 401

    def test_unknown_user(self, client):
        r = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
        assert r.status_code == 401

    def test_missing_fields(self, client):
        r = client.post("/api/auth/login", json={"username": "admin"})
        assert r.status_code == 422


class TestMe:
    def test_me_returns_user(self, client, admin_headers):
        r = client.get("/api/auth/me", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["username"] == "admin"
        assert r.json()["is_admin"] is True

    def test_me_without_token(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code in (401, 403)

    def test_me_with_bad_token(self, client):
        r = client.get(
            "/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert r.status_code in (401, 403)


class TestCreateAndChangePassword:
    def test_full_flow(self, client, admin_headers):
        username = _uid("flowuser")
        # Create user
        r = client.post(
            "/api/admin/users",
            json={"username": username, "password": "temp1234", "is_admin": False},
            headers=admin_headers,
        )
        assert r.status_code == 201
        assert r.json()["username"] == username

        # Login — requires_password_change should be True
        r = client.post(
            "/api/auth/login", json={"username": username, "password": "temp1234"}
        )
        assert r.status_code == 200
        assert r.json()["user"]["requires_password_change"] is True
        token = r.json()["access_token"]

        # Change password
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "temp1234", "new_password": "newpass99"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        _ = r.json()["access_token"]  # token issued; value not needed here

        # Login with new password — requires_password_change should be False
        r = client.post(
            "/api/auth/login", json={"username": username, "password": "newpass99"}
        )
        assert r.status_code == 200
        assert r.json()["user"]["requires_password_change"] is False

    def test_change_password_wrong_current(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"username": "cptest", "password": "temp5678", "is_admin": False},
            headers=admin_headers,
        )
        r = client.post(
            "/api/auth/login", json={"username": "cptest", "password": "temp5678"}
        )
        token = r.json()["access_token"]

        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "newpass99"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400

    def test_change_password_too_short(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"username": "shortpw", "password": "temp5678", "is_admin": False},
            headers=admin_headers,
        )
        r = client.post(
            "/api/auth/login", json={"username": "shortpw", "password": "temp5678"}
        )
        token = r.json()["access_token"]

        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "temp5678", "new_password": "abc"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400
        assert "8 characters" in r.json()["detail"]


class TestAdminResetPassword:
    def test_admin_can_reset_regular_user_password(self, client, admin_headers):
        username = _uid("resetme")
        client.post(
            "/api/admin/users",
            json={"username": username, "password": "original1", "is_admin": False},
            headers=admin_headers,
        )
        # First login to clear is_first_login flag
        r = client.post(
            "/api/auth/login", json={"username": username, "password": "original1"}
        )
        token = r.json()["access_token"]
        client.post(
            "/api/auth/change-password",
            json={"current_password": "original1", "new_password": "changed99"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Admin resets the password
        r = client.post(
            f"/api/admin/users/{username}/reset-password",
            json={"new_password": "newreset1"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "password_reset"

        # Login with new password should work and requires_password_change must be True
        r = client.post(
            "/api/auth/login", json={"username": username, "password": "newreset1"}
        )
        assert r.status_code == 200
        assert r.json()["user"]["requires_password_change"] is True

        # Old password no longer works
        r = client.post(
            "/api/auth/login", json={"username": username, "password": "changed99"}
        )
        assert r.status_code == 401

    def test_admin_can_reset_another_admin_password(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"username": "admin2", "password": "adminpass1", "is_admin": True},
            headers=admin_headers,
        )
        r = client.post(
            "/api/admin/users/admin2/reset-password",
            json={"new_password": "newapass1"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["username"] == "admin2"

        r = client.post(
            "/api/auth/login", json={"username": "admin2", "password": "newapass1"}
        )
        assert r.status_code == 200
        assert r.json()["user"]["requires_password_change"] is True

    def test_cannot_reset_nonexistent_user(self, client, admin_headers):
        r = client.post(
            "/api/admin/users/doesnotexist/reset-password",
            json={"new_password": "somepass1"},
            headers=admin_headers,
        )
        assert r.status_code == 404

    def test_cannot_reset_inactive_user_password(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={
                "username": "inactive_reset",
                "password": "pass1234",
                "is_admin": False,
            },
            headers=admin_headers,
        )
        client.delete("/api/admin/users/inactive_reset", headers=admin_headers)

        r = client.post(
            "/api/admin/users/inactive_reset/reset-password",
            json={"new_password": "newpass99"},
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert "inactive" in r.json()["detail"].lower()

    def test_reset_password_too_short_rejected(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"username": "shortpw2", "password": "pass1234", "is_admin": False},
            headers=admin_headers,
        )
        r = client.post(
            "/api/admin/users/shortpw2/reset-password",
            json={"new_password": "abc"},
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert "8 characters" in r.json()["detail"]

    def test_non_admin_cannot_reset_password(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={
                "username": "noreset_user",
                "password": "pass1234",
                "is_admin": False,
            },
            headers=admin_headers,
        )
        r = client.post(
            "/api/auth/login", json={"username": "noreset_user", "password": "pass1234"}
        )
        token = r.json()["access_token"]

        r = client.post(
            "/api/admin/users/admin/reset-password",
            json={"new_password": "hackattempt"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


class TestAdminRBAC:
    def test_non_admin_cannot_list_users(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"username": "regularuser", "password": "pass1234", "is_admin": False},
            headers=admin_headers,
        )
        r = client.post(
            "/api/auth/login", json={"username": "regularuser", "password": "pass1234"}
        )
        token = r.json()["access_token"]

        r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_admin_can_list_users(self, client, admin_headers):
        r = client.get("/api/admin/users", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1

    def test_deactivate_and_reactivate(self, client, admin_headers):
        client.post(
            "/api/admin/users",
            json={"username": "deactme", "password": "pass1234", "is_admin": False},
            headers=admin_headers,
        )

        # Deactivate
        r = client.delete("/api/admin/users/deactme", headers=admin_headers)
        assert r.status_code == 204

        # Login should fail
        r = client.post(
            "/api/auth/login", json={"username": "deactme", "password": "pass1234"}
        )
        assert r.status_code == 401

        # Reactivate
        r = client.post("/api/admin/users/deactme/reactivate", headers=admin_headers)
        assert r.status_code == 200

        # Login should work again
        r = client.post(
            "/api/auth/login", json={"username": "deactme", "password": "pass1234"}
        )
        assert r.status_code == 200
