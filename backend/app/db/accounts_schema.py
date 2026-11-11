"""Phase 1 schema: account columns on ``users`` plus the session, identity,
quota and game tables. Idempotent and purely additive (safe on production)."""

import logging
from datetime import datetime, timedelta

from ..core.config import settings
from .database import get_connection

logger = logging.getLogger(__name__)

_USER_COLUMNS = {
    "email_verified": "INTEGER NOT NULL DEFAULT 0",
    "account_status": "TEXT NOT NULL DEFAULT 'active'",
    "signup_method": "TEXT NOT NULL DEFAULT 'admin'",
    "verified_at": "TEXT",
    "token_version": "INTEGER NOT NULL DEFAULT 0",
    "display_name": "TEXT",
    "avatar_source": "TEXT",
    "avatar_rev": "INTEGER NOT NULL DEFAULT 0",
    "locale": "TEXT",
    "last_login_at": "TEXT",
    "invite_id": "INTEGER",
}

_TABLES = """
CREATE INDEX IF NOT EXISTS idx_users_lower_username ON users(lower(username));
CREATE INDEX IF NOT EXISTS idx_users_lower_email ON users(lower(email));

CREATE TABLE IF NOT EXISTS account_tokens (
    id         INTEGER PRIMARY KEY,
    user_id    TEXT NOT NULL,
    purpose    TEXT NOT NULL CHECK(purpose IN ('verify_email','reset_password')),
    token_hash TEXT NOT NULL UNIQUE,
    email      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_account_tokens_user ON account_tokens(user_id, purpose);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    family_id         TEXT NOT NULL,
    token_hash        TEXT NOT NULL UNIQUE,
    client            TEXT NOT NULL,
    device_name       TEXT,
    token_version     INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    last_used_at      TEXT,
    expires_at        TEXT NOT NULL,
    family_expires_at TEXT NOT NULL,
    rotated_at        TEXT,
    revoked_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family ON refresh_tokens(family_id);

CREATE TABLE IF NOT EXISTS user_identities (
    id             INTEGER PRIMARY KEY,
    user_id        TEXT NOT NULL,
    provider       TEXT NOT NULL,
    subject        TEXT NOT NULL,
    email          TEXT,
    email_verified INTEGER NOT NULL DEFAULT 0,
    display_name   TEXT,
    picture_url    TEXT,
    secret_enc     TEXT,
    created_at     TEXT NOT NULL,
    last_used_at   TEXT,
    UNIQUE(provider, subject)
);
CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);

CREATE TABLE IF NOT EXISTS oauth_tickets (
    hash             TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK(kind IN ('state','handoff','signup','link')),
    provider         TEXT,
    user_id          TEXT,
    data             TEXT NOT NULL DEFAULT '{}',
    binding_hash     TEXT,
    client_challenge TEXT,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    used_at          TEXT
);

CREATE TABLE IF NOT EXISTS invite_codes (
    id          INTEGER PRIMARY KEY,
    code_hash   TEXT NOT NULL UNIQUE,
    code_prefix TEXT NOT NULL,
    note        TEXT,
    max_uses    INTEGER NOT NULL,
    uses        INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id    TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_onboarding (
    user_id       TEXT PRIMARY KEY,
    step          INTEGER NOT NULL DEFAULT 0,
    done          INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    traveller_type TEXT,
    completed_at  TEXT,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_usage_daily (
    day      TEXT,
    user_key TEXT,
    bucket   TEXT,
    used     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(day, user_key, bucket)
);

CREATE TABLE IF NOT EXISTS xp_ledger (
    id         INTEGER PRIMARY KEY,
    user_id    TEXT NOT NULL,
    rule       TEXT NOT NULL,
    points     INTEGER NOT NULL,
    idem_key   TEXT NOT NULL UNIQUE,
    meta       TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xp_ledger_user_time ON xp_ledger(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_xp_ledger_user_rule ON xp_ledger(user_id, rule, created_at);

CREATE TABLE IF NOT EXISTS user_badges (
    user_id    TEXT,
    badge_id   TEXT,
    progress   INTEGER NOT NULL,
    target     INTEGER NOT NULL,
    earned_at  TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, badge_id)
);

CREATE TABLE IF NOT EXISTS user_streaks (
    user_id    TEXT,
    kind       TEXT,
    current    INTEGER NOT NULL,
    longest    INTEGER NOT NULL,
    last_day   TEXT,
    freezes    INTEGER NOT NULL,
    freeze_week TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, kind)
);
"""


def create_account_tables() -> None:
    """Add the Phase 1 columns and tables. Needs ``users`` to exist."""
    with get_connection() as conn:
        have = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        for col, decl in _USER_COLUMNS.items():
            if col not in have:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
        conn.executescript(_TABLES)


def purge_expired(now: datetime) -> dict[str, int]:
    """Delete stale rows; returns the number removed per table."""
    days = int(getattr(settings, "pending_purge_days", 7))
    iso = lambda dt: dt.isoformat()  # noqa: E731
    out: dict[str, int] = {}
    with get_connection() as conn:
        pend = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM users WHERE account_status = 'pending' AND created_at < ?",
                (iso(now - timedelta(days=days)),),
            )
        ]
        tok = 0
        for uid in pend:
            tok += conn.execute(
                "DELETE FROM account_tokens WHERE user_id = ?", (uid,)
            ).rowcount
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        out["users"] = len(pend)
        tok += conn.execute(
            "DELETE FROM account_tokens WHERE expires_at < ?",
            (iso(now - timedelta(days=1)),),
        ).rowcount
        out["account_tokens"] = tok
        out["oauth_tickets"] = conn.execute(
            "DELETE FROM oauth_tickets WHERE expires_at < ?", (iso(now),)
        ).rowcount
        cut = iso(now - timedelta(days=7))
        out["refresh_tokens"] = conn.execute(
            "DELETE FROM refresh_tokens WHERE expires_at < ? OR revoked_at < ?",
            (cut, cut),
        ).rowcount
        out["ai_usage_daily"] = conn.execute(
            "DELETE FROM ai_usage_daily WHERE day < ?",
            ((now - timedelta(days=8)).date().isoformat(),),
        ).rowcount
    return out
