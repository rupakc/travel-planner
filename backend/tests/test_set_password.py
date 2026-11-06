"""Tests for the operator password tool (python -m app.set_password)."""

import uuid

import pytest

from app import set_password
from app.db.users_db import authenticate_user, create_user, get_user_by_username


@pytest.fixture(autouse=True)
def _app_tables(client):
    """The session app client creates the users table."""


def _prompts(monkeypatch, *answers):
    """Feed getpass the given answers in order."""
    it = iter(answers)
    monkeypatch.setattr(set_password.getpass, "getpass", lambda prompt="": next(it))


def _name(prefix="pw"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_resets_an_existing_users_password(monkeypatch):
    user = _name()
    create_user(user, "oldpassword1", is_admin=True)
    _prompts(monkeypatch, "brand-new-pass-1", "brand-new-pass-1")

    assert set_password.main([user]) == 0

    assert authenticate_user(user, "brand-new-pass-1")
    assert authenticate_user(user, "oldpassword1") is None
    # the operator chose it: no forced change on next login
    assert get_user_by_username(user)["is_first_login"] is False


def test_reset_reactivates_a_deactivated_account(monkeypatch):
    from app.db.users_db import deactivate_user

    user = _name()
    create_user(user, "oldpassword1")
    deactivate_user(user)
    _prompts(monkeypatch, "brand-new-pass-1", "brand-new-pass-1")

    assert set_password.main([user]) == 0
    assert get_user_by_username(user)["is_active"] is True


def test_creates_an_admin_with_create_and_admin(monkeypatch):
    user = _name("adm")
    _prompts(monkeypatch, "admin-pass-1234", "admin-pass-1234")

    assert set_password.main([user, "--create", "--admin"]) == 0

    created = get_user_by_username(user)
    assert created["is_admin"] is True
    assert created["is_first_login"] is False
    assert authenticate_user(user, "admin-pass-1234")


def test_unknown_user_without_create_changes_nothing(monkeypatch, capsys):
    user = _name()
    _prompts(monkeypatch, "brand-new-pass-1", "brand-new-pass-1")

    assert set_password.main([user]) == 1
    assert get_user_by_username(user) is None
    assert "--create" in capsys.readouterr().err


def test_create_refuses_an_existing_user(monkeypatch):
    user = _name()
    create_user(user, "oldpassword1")
    _prompts(monkeypatch, "brand-new-pass-1", "brand-new-pass-1")

    assert set_password.main([user, "--create"]) == 1
    assert authenticate_user(user, "oldpassword1")


@pytest.mark.parametrize(
    ("first", "second"),
    [("short", "short"), ("brand-new-pass-1", "different-pass-1")],
)
def test_rejects_short_or_mismatched_passwords(monkeypatch, first, second):
    user = _name()
    create_user(user, "oldpassword1")
    _prompts(monkeypatch, first, second)

    assert set_password.main([user]) == 1
    assert authenticate_user(user, "oldpassword1")


def test_never_prints_the_password(monkeypatch, capsys):
    user = _name()
    create_user(user, "oldpassword1")
    _prompts(monkeypatch, "secret-value-987", "secret-value-987")

    set_password.main([user])

    out = capsys.readouterr()
    assert "secret-value-987" not in out.out + out.err
