"""Phase 1 schema: idempotent, additive migration and purge."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.db import accounts_schema, users_db
from app.db.database import get_connection

NEW_COLS = {
    "email_verified", "account_status", "signup_method", "verified_at",
    "token_version", "display_name", "avatar_source", "avatar_rev", "locale",
    "last_login_at", "invite_id",
}  # fmt: skip


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return tmp_path


def _cols():
    with get_connection() as conn:
        return {r["name"] for r in conn.execute("PRAGMA table_info(users)")}


def test_create_account_tables_idempotent(fresh_db):
    conn = sqlite3.connect(str(fresh_db / "airports.db"))
    conn.executescript(
        """CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
           email TEXT UNIQUE, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
           is_first_login INTEGER NOT NULL DEFAULT 1, is_active INTEGER NOT NULL DEFAULT 1,
           created_at TEXT, updated_at TEXT);
           INSERT INTO users (id, username, password_hash) VALUES ('u1', 'old', 'x');"""
    )
    conn.commit()
    conn.close()
    accounts_schema.create_account_tables()
    accounts_schema.create_account_tables()
    assert NEW_COLS <= _cols()
    with get_connection() as c:
        row = c.execute("SELECT * FROM users WHERE id = 'u1'").fetchone()
        tables = {
            r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert row["signup_method"] == "admin"
    assert row["token_version"] == 0
    assert row["account_status"] == "active"
    assert {"account_tokens", "refresh_tokens", "user_identities", "oauth_tickets",
            "invite_codes", "user_settings", "user_onboarding", "ai_usage_daily",
            "xp_ledger", "user_badges", "user_streaks"} <= tables  # fmt: skip


def _token(uid, expires, purpose="verify_email"):
    with get_connection() as c:
        c.execute(
            "INSERT INTO account_tokens (user_id, purpose, token_hash, email, created_at, expires_at)"
            " VALUES (?, ?, ?, 'a@b.c', ?, ?)",
            (uid, purpose, f"h-{uid}-{expires}", expires, expires),
        )


def test_purge_expired_counts(fresh_db, monkeypatch):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    users_db.create_users_table()
    now = datetime.now(UTC)
    old = users_db.create_user("old1", "p", email="o@x.io", account_status="pending")
    new = users_db.create_user("new1", "p", email="n@x.io", account_status="pending")
    with get_connection() as c:
        c.execute("UPDATE users SET created_at = ? WHERE id = ?",
                  ((now - timedelta(days=8)).isoformat(), old["id"]))  # fmt: skip
        c.execute("UPDATE users SET created_at = ? WHERE id = ?",
                  ((now - timedelta(days=6)).isoformat(), new["id"]))  # fmt: skip
        c.execute("INSERT INTO ai_usage_daily VALUES (?, 'u', 'b', 1)",
                  ((now - timedelta(days=9)).date().isoformat(),))  # fmt: skip
        c.execute("INSERT INTO ai_usage_daily VALUES (?, 'u', 'b', 1)",
                  (now.date().isoformat(),))  # fmt: skip
        c.execute(
            "INSERT INTO oauth_tickets (hash, kind, created_at, expires_at)"
            " VALUES ('t', 'state', ?, ?)",
            (now.isoformat(), (now - timedelta(minutes=1)).isoformat()),
        )
    _token(old["id"], (now + timedelta(days=1)).isoformat())
    _token(new["id"], (now + timedelta(days=1)).isoformat())
    out = accounts_schema.purge_expired(now)
    assert out["users"] == 1
    assert out["account_tokens"] == 1
    assert out["oauth_tickets"] == 1
    assert out["ai_usage_daily"] == 1
    assert users_db.get_user_by_id(old["id"]) is None
    assert users_db.get_user_by_id(new["id"]) is not None
