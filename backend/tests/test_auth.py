"""Tests for auth endpoints and RBAC."""
import pytest


class TestLogin:
    def test_admin_login_success(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-pw!"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["is_admin"] is True
        assert data["user"]["requires_password_change"] is False

    def test_wrong_password(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
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
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert r.status_code in (401, 403)


class TestCreateAndChangePassword:
    def test_full_flow(self, client, admin_headers):
        # Create user
        r = client.post("/api/admin/users", json={
            "username": "flowuser", "password": "temp1234", "is_admin": False
        }, headers=admin_headers)
        assert r.status_code == 201
        assert r.json()["username"] == "flowuser"

        # Login — requires_password_change should be True
        r = client.post("/api/auth/login", json={"username": "flowuser", "password": "temp1234"})
        assert r.status_code == 200
        assert r.json()["user"]["requires_password_change"] is True
        token = r.json()["access_token"]

        # Change password
        r = client.post("/api/auth/change-password", json={
            "current_password": "temp1234", "new_password": "newpass99"
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        new_token = r.json()["access_token"]

        # Login with new password — requires_password_change should be False
        r = client.post("/api/auth/login", json={"username": "flowuser", "password": "newpass99"})
        assert r.status_code == 200
        assert r.json()["user"]["requires_password_change"] is False

    def test_change_password_wrong_current(self, client, admin_headers):
        client.post("/api/admin/users", json={
            "username": "cptest", "password": "temp5678", "is_admin": False
        }, headers=admin_headers)
        r = client.post("/api/auth/login", json={"username": "cptest", "password": "temp5678"})
        token = r.json()["access_token"]

        r = client.post("/api/auth/change-password", json={
            "current_password": "wrong", "new_password": "newpass99"
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400

    def test_change_password_too_short(self, client, admin_headers):
        client.post("/api/admin/users", json={
            "username": "shortpw", "password": "temp5678", "is_admin": False
        }, headers=admin_headers)
        r = client.post("/api/auth/login", json={"username": "shortpw", "password": "temp5678"})
        token = r.json()["access_token"]

        r = client.post("/api/auth/change-password", json={
            "current_password": "temp5678", "new_password": "abc"
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400


class TestAdminRBAC:
    def test_non_admin_cannot_list_users(self, client, admin_headers):
        client.post("/api/admin/users", json={
            "username": "regularuser", "password": "pass1234", "is_admin": False
        }, headers=admin_headers)
        r = client.post("/api/auth/login", json={"username": "regularuser", "password": "pass1234"})
        token = r.json()["access_token"]

        r = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_admin_can_list_users(self, client, admin_headers):
        r = client.get("/api/admin/users", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1

    def test_deactivate_and_reactivate(self, client, admin_headers):
        client.post("/api/admin/users", json={
            "username": "deactme", "password": "pass1234", "is_admin": False
        }, headers=admin_headers)

        # Deactivate
        r = client.delete("/api/admin/users/deactme", headers=admin_headers)
        assert r.status_code == 204

        # Login should fail
        r = client.post("/api/auth/login", json={"username": "deactme", "password": "pass1234"})
        assert r.status_code == 401

        # Reactivate
        r = client.post("/api/admin/users/deactme/reactivate", headers=admin_headers)
        assert r.status_code == 200

        # Login should work again
        r = client.post("/api/auth/login", json={"username": "deactme", "password": "pass1234"})
        assert r.status_code == 200
