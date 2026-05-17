"""Tests for users_db CRUD operations."""
import pytest
from app.db.users_db import (
    create_user, get_user_by_username, authenticate_user,
    change_password, deactivate_user, reactivate_user, get_all_users,
)


@pytest.fixture
def new_user(admin_headers, client):
    import uuid
    username = f"dbtest_{uuid.uuid4().hex[:8]}"
    client.post("/api/admin/users", json={
        "username": username, "password": "initpass1", "is_admin": False
    }, headers=admin_headers)
    return username


def test_create_and_get_user():
    import uuid
    uname = f"unit_{uuid.uuid4().hex[:6]}"
    u = create_user(uname, "password123")
    assert u["username"] == uname
    assert u["is_first_login"] is True
    assert u["is_active"] is True
    assert u["is_admin"] is False

    fetched = get_user_by_username(uname)
    assert fetched is not None
    assert fetched["username"] == uname


def test_password_hash_not_stored_plaintext():
    import uuid
    uname = f"hashtest_{uuid.uuid4().hex[:6]}"
    create_user(uname, "myplainpassword")
    u = get_user_by_username(uname)
    assert "myplainpassword" not in u["password_hash"]


def test_authenticate_valid():
    import uuid
    uname = f"authtest_{uuid.uuid4().hex[:6]}"
    create_user(uname, "correctpw")
    assert authenticate_user(uname, "correctpw") is not None


def test_authenticate_wrong_password():
    import uuid
    uname = f"authtest2_{uuid.uuid4().hex[:6]}"
    create_user(uname, "correctpw")
    assert authenticate_user(uname, "wrongpw") is None


def test_authenticate_unknown_user():
    assert authenticate_user("ghost_user_xyz", "anything") is None


def test_change_password_updates_first_login():
    import uuid
    uname = f"chpw_{uuid.uuid4().hex[:6]}"
    create_user(uname, "oldpass")
    assert get_user_by_username(uname)["is_first_login"] is True

    change_password(uname, "newpass99")
    u = get_user_by_username(uname)
    assert u["is_first_login"] is False
    assert authenticate_user(uname, "newpass99") is not None
    assert authenticate_user(uname, "oldpass") is None


def test_deactivate_blocks_auth():
    import uuid
    uname = f"deact_{uuid.uuid4().hex[:6]}"
    create_user(uname, "pass1234")
    deactivate_user(uname)
    assert authenticate_user(uname, "pass1234") is None


def test_reactivate_restores_auth():
    import uuid
    uname = f"react_{uuid.uuid4().hex[:6]}"
    create_user(uname, "pass1234")
    deactivate_user(uname)
    reactivate_user(uname)
    assert authenticate_user(uname, "pass1234") is not None


def test_get_all_users_includes_created():
    import uuid
    uname = f"listtest_{uuid.uuid4().hex[:6]}"
    create_user(uname, "pass1234")
    users = get_all_users()
    assert any(u["username"] == uname for u in users)
