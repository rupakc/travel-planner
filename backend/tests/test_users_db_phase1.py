"""Phase 1 user-row helpers."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db import users_db
from app.db.database import get_connection


@pytest.fixture(autouse=True)
def _setup(monkeypatch, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


def _name():
    return f"p1-{uuid.uuid4().hex[:8]}"


def _pending(name, email, **kw):
    return users_db.create_pending_user(
        name, email, "pw-123456", None, None, None, **kw
    )


def _add_token(uid, expires):
    with get_connection() as c:
        c.execute(
            "INSERT INTO account_tokens (user_id, purpose, token_hash, email, created_at, expires_at)"
            " VALUES (?, 'verify_email', ?, 'e', ?, ?)",
            (uid, uuid.uuid4().hex, expires.isoformat(), expires.isoformat()),
        )


def test_username_taken_is_case_insensitive():
    n = _name()
    users_db.create_user(n, "pw")
    assert not users_db.username_available(n.upper(), datetime.now(UTC))
    with pytest.raises(users_db.UsernameTakenError):
        users_db.create_pending_user(n.upper(), f"{n}@x.io", "pw", None, None, None)


def test_expired_pending_releases_username():
    n = _name()
    u = _pending(n, f"{n}@x.io")
    now = datetime.now(UTC)
    _add_token(u["id"], now + timedelta(hours=1))
    assert not users_db.username_available(n, now)
    assert users_db.username_available(n, now + timedelta(hours=2))
    assert users_db.get_user_by_id(u["id"]) is None


def test_pending_with_same_email_is_replaced():
    n = _name()
    a = _pending(n, f"{n}@x.io")
    b = _pending(n + "b", f"{n.upper()}@x.io")
    assert users_db.get_user_by_id(a["id"]) is None
    assert b["account_status"] == "pending" and b["email"] == f"{n}@x.io"
    users_db.create_user(n + "c", "pw", email=f"{n}c@x.io")
    with pytest.raises(users_db.EmailInUseError):
        _pending(n + "d", f"{n}c@x.io")


def test_set_email_resets_verified():
    n = _name()
    u = users_db.create_user(n, "pw", email=f"{n}@x.io", email_verified=True)
    assert u["email_verified"] is True
    users_db.set_email(n, f"{n}@x.io")
    assert users_db.get_user_by_id(u["id"])["email_verified"] is True
    users_db.set_email(n, f"{n}2@x.io")
    assert users_db.get_user_by_id(u["id"])["email_verified"] is False
    assert users_db.mark_email_verified(u["id"], f"{n}2@x.io")
    assert not users_db.mark_email_verified(u["id"], "other@x.io")


def test_deactivate_bumps_token_version():
    n = _name()
    u = users_db.create_user(n, "pw")
    users_db.deactivate_user(n)
    assert users_db.get_user_by_id(u["id"])["token_version"] == 1
    users_db.admin_reset_password(n, "new")
    assert users_db.get_user_by_id(u["id"])["token_version"] == 2
    assert users_db.bump_token_version(u["id"]) == 3


def test_login_by_email_and_username():
    n = _name()
    u = users_db.create_user(n, "pw", email=f"{n}@X.io")
    assert users_db.get_user_by_login(n)["id"] == u["id"]
    assert users_db.get_user_by_login(n.upper())["id"] == u["id"]
    assert users_db.get_user_by_login(f"{n}@x.IO")["id"] == u["id"]
    assert users_db.get_user_by_email(f"{n}@x.io")["id"] == u["id"]
    assert users_db.get_user_by_login("nobody-here") is None


def test_activate_avatar_misc():
    n = _name()
    u = _pending(n, f"{n}@x.io")
    users_db.activate_user(u["id"], u["email"])
    got = users_db.get_user_by_id(u["id"])
    assert got["account_status"] == "active" and got["verified_at"]
    assert users_db.set_avatar(u["id"], "upload") == 1
    users_db.set_display_name(u["id"], "Zed")
    users_db.touch_last_login(u["id"])
    assert users_db.get_user_by_id(u["id"])["display_name"] == "Zed"
    assert users_db.count_active_admins() >= 1
    users_db.delete_user_row(u["id"])
    assert users_db.get_user_by_id(u["id"]) is None


def test_passwordless_account():
    n = _name()
    u = users_db.create_user(n, None, password_hash="!")
    assert u["password_hash"] == "!"
    assert users_db.authenticate_user(n, "anything") is None


def test_pending_without_token_holds_name_until_ttl():
    n = _name()
    u = _pending(n, f"{n}@x.io")
    now = datetime.now(UTC)
    assert not users_db.username_available(n, now)
    assert not users_db.username_available(n, now.replace(tzinfo=None))  # naive = UTC
    assert users_db.username_available(n, now + timedelta(minutes=31))
    assert users_db.get_user_by_id(u["id"]) is None


def test_create_user_refuses_case_variant_username():
    n = _name()
    users_db.create_user(n, "pw")
    with pytest.raises(users_db.UsernameTakenError):
        users_db.create_user(n.upper(), "pw")
    with pytest.raises(ValueError):
        users_db.create_user(_name())
    m = _name()
    users_db.create_user(m, "pw", email=f"{m}@x.io")
    users_db.set_email(m, f"{m.upper()}@X.IO")
    assert users_db.get_user_by_username(m)["email"] == f"{m}@x.io"


def test_delete_user_row_removes_tokens():
    n = _name()
    u = _pending(n, f"{n}@x.io")
    _add_token(u["id"], datetime.now(UTC) + timedelta(hours=1))
    users_db.delete_user_row(u["id"])
    with get_connection() as c:
        left = c.execute(
            "SELECT COUNT(*) FROM account_tokens WHERE user_id = ?", (u["id"],)
        ).fetchone()[0]
    assert left == 0
