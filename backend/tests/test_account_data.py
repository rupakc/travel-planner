"""GET /account/export and DELETE /account (Task 33)."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime

import pytest

from app.core.auth import create_access_token
from app.db import telemetry_db, users_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import account_data
from app.services.avatar import avatar_path
from app.services.oauth import registry, secrets_box

_PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _env(client, monkeypatch):
    # bcrypt at full cost is slow; a reversible stand-in keeps the check real
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")
    monkeypatch.setattr(users_db, "_verify", lambda pw, hashed: hashed == f"plain:{pw}")
    yield
    registry.clear_overrides()


def _user(**kw):
    name = f"del_{uuid.uuid4().hex[:12]}"
    u = create_user(name, _PW, email=f"{name}@example.com", **kw)
    return u, {"Authorization": f"Bearer {create_access_token({'sub': name})}"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ms() -> int:
    # recent: the telemetry prune task drops old events
    return int(datetime.now(UTC).timestamp() * 1000)


def _cols(conn, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()  # nosec B608


def _tables(conn) -> list[str]:
    return [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    ]


def _fill(conn, table: str, values: dict) -> None:
    """Insert one row, giving every other NOT NULL column without a default a
    placeholder of its type."""
    row = dict(values)
    for c in _cols(conn, table):
        name, ctype = c["name"], (c["type"] or "").upper()
        if name in row or c["dflt_value"] is not None:
            continue
        if c["pk"] and "INT" in ctype:
            continue
        if c["notnull"] or c["pk"]:
            if "INT" in ctype or "REAL" in ctype:
                row[name] = 1
            else:  # unique-safe placeholder
                row[name] = uuid.uuid4().hex
    keys = ", ".join(row)
    marks = ", ".join("?" * len(row))
    conn.execute(
        f"INSERT INTO {table} ({keys}) VALUES ({marks})",  # nosec B608
        tuple(row.values()),
    )


# Columns with a CHECK constraint or a parsed format
_FIXED = {
    "account_tokens": {"purpose": "verify_email"},
    "oauth_tickets": {"kind": "link"},
    "user_settings": {"data": "{}"},
    "price_watches": {"kind": "hotel"},
}


def _seed_everything(u: dict) -> None:
    """A row for the user in every table that can hold one."""
    uid, name = u["id"], u["username"]
    with get_connection() as conn:
        for table, (col, key) in account_data.USER_TABLES.items():
            values = {col: uid if key == "id" else name, **_FIXED.get(table, {})}
            _fill(conn, table, values)
        for table in account_data.CHILD_TABLES:
            parent = table.removesuffix("_history") + "es"
            pid = conn.execute(
                f"SELECT id FROM {parent} WHERE user_id = ?",  # nosec B608
                (uid,),
            ).fetchone()["id"]
            _fill(conn, table, {"watch_id": pid})
        _fill(
            conn,
            "ai_usage_daily",
            {"day": "2026-11-11", "user_key": f"user:{uid}", "bucket": "search"},
        )
        _fill(
            conn,
            "invite_codes",
            {"code_hash": uuid.uuid4().hex, "code_prefix": "VOY-AAAA",
             "created_by": uid, "created_at": _now(), "expires_at": _now()},
        )  # fmt: skip
    telemetry_db.insert_events(
        [
            {
                "ts": _ms(),
                "received_at": _ms(),
                "event": "screen_view",
                "session_id": "s",
                "anon_id": "a",
                "user_id": uid,
                "platform": "web",
                "app_version": "1",
                "locale": "en",
                "props": "{}",
            }
        ]
    )
    p = avatar_path(uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"RIFF....WEBP")
    users_db.set_avatar(uid, "upload")


def _rows_mentioning(needles: list[str]) -> list[tuple[str, str]]:
    hits = []
    dbs = [get_connection]
    for opener in dbs:
        with opener() as conn:
            hits += _scan(conn, needles)
    tdb = telemetry_db.telemetry_db_path()
    conn = sqlite3.connect(str(tdb))
    conn.row_factory = sqlite3.Row
    try:
        hits += _scan(conn, needles)
    finally:
        conn.close()
    return hits


def _scan(conn, needles: list[str]) -> list[tuple[str, str]]:
    hits = []
    for table in _tables(conn):
        for c in _cols(conn, table):
            for n in needles:
                found = conn.execute(
                    f'SELECT 1 FROM "{table}" WHERE instr(CAST("{c["name"]}" AS TEXT), ?) > 0'  # nosec B608
                    " LIMIT 1",
                    (n,),
                ).fetchone()
                if found:
                    hits.append((table, c["name"]))
    return hits


# ── coverage ──────────────────────────────────────────────────────────────────


def test_every_user_table_is_covered():
    covered = (
        set(account_data.USER_TABLES)
        | set(account_data.KEEP_NULLED)
        | set(account_data.KEYED_TABLES)
        | {"users"}
    )
    with get_connection() as conn:
        for table in _tables(conn):
            names = {c["name"] for c in _cols(conn, table)}
            if names & {"username", "user_id", "created_by", "user_key"}:
                assert table in covered, f"{table} holds user rows but is not covered"
            if "watch_id" in names:
                assert table in account_data.CHILD_TABLES, table
    for table, (col, key) in account_data.USER_TABLES.items():
        assert key in ("id", "username")
        with get_connection() as conn:
            assert col in {c["name"] for c in _cols(conn, table)}, table


# ── export ────────────────────────────────────────────────────────────────────

_SECRET_KEYS = {"password_hash", "token_hash", "secret_enc", "refresh_token"}


def _keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


def test_export_round_trip(client):
    u, h = _user()
    r = client.post(
        "/api/plans",
        json={
            "name": "Lisbon",
            "search_data": {"destination": "Lisbon"},
            "selections": {},
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO devices (username, token, platform, created_at, last_seen_at)"
            " VALUES (?, ?, 'android', ?, ?)",
            (u["username"], "fcm-secret-token-abcdef123456", _now(), _now()),
        )
        conn.execute(
            """INSERT INTO user_identities (user_id, provider, subject, email,
                   secret_enc, created_at) VALUES (?, 'apple', 's1', 'a@x.com', ?, ?)""",
            (u["id"], secrets_box.seal("apple-refresh"), _now()),
        )
        conn.execute(
            """INSERT INTO refresh_tokens (id, user_id, family_id, token_hash, client,
                   token_version, created_at, expires_at, family_expires_at)
               VALUES (?, ?, 'f', 'rt-hash-zzz', 'ios', 0, ?, ?, ?)""",
            (uuid.uuid4().hex, u["id"], _now(), _now(), _now()),
        )

    r = client.get("/api/account/export", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    day = datetime.now(UTC).date().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="voyager-export-{u["username"]}-{day}.json"'
    )
    body = r.json()
    assert set(body) == {
        "format", "version", "exported_at", "account", "identities", "settings",
        "onboarding", "preferences", "plans", "recent_searches", "taste",
        "feedback", "fare_watches", "price_watches", "notifications", "devices",
        "game",
    }  # fmt: skip
    assert body["format"] == "voyager-export" and body["version"] == 1
    assert body["exported_at"].endswith("Z")
    assert body["account"]["id"] == u["id"]
    assert [p["name"] for p in body["plans"]] == ["Lisbon"]
    assert body["plans"][0]["search_data"] == {"destination": "Lisbon"}
    assert body["identities"][0]["provider"] == "apple"
    assert body["devices"][0]["token"] == "…123456"
    assert not _keys(body) & _SECRET_KEYS
    raw = r.text
    for secret in ("fcm-secret-token", "rt-hash-zzz", "plain:", "apple-refresh"):
        assert secret not in raw


def test_export_requires_auth(client):
    assert client.get("/api/account/export").status_code == 401


# ── delete ────────────────────────────────────────────────────────────────────


def _delete(client, h, body):
    return client.request("DELETE", "/api/account", json=body, headers=h)


def test_delete_wrong_password_is_403(client):
    u, h = _user()
    r = _delete(client, h, {"password": "nope-nope-nope"})
    assert r.status_code == 403
    assert r.json()["error_code"] == "password_incorrect"
    assert users_db.get_user_by_id(u["id"])


def test_delete_without_password_needs_username(client):
    u, h = _user(password_hash="!")
    r = _delete(client, h, {"confirm_username": "someone-else"})
    assert r.status_code == 400
    assert r.json()["error_code"] == "confirmation_mismatch"
    assert users_db.get_user_by_id(u["id"])
    assert _delete(client, h, {"confirm_username": u["username"]}).status_code == 204
    assert users_db.get_user_by_id(u["id"]) is None


def test_last_admin_is_409(client, monkeypatch):
    u, h = _user(is_admin=True)
    monkeypatch.setattr(account_data.users_db, "count_active_admins", lambda: 1)
    r = _delete(client, h, {"password": _PW})
    assert r.status_code == 409
    assert r.json()["error_code"] == "last_admin"
    assert users_db.get_user_by_id(u["id"])


def test_last_admin_holds_inside_the_transaction():
    """Even when the route's pre-check passed, the delete itself refuses to
    remove the only active admin."""
    with get_connection() as conn:
        admins = conn.execute(
            "SELECT id FROM users WHERE is_admin = 1 AND is_active = 1"
            " AND account_status = 'active'"
        ).fetchall()
    assert admins
    u, _ = _user(is_admin=True)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE users SET is_active = 0 WHERE id IN ({','.join('?' * len(admins))})",  # nosec B608
            [a["id"] for a in admins],
        )
    try:
        with pytest.raises(account_data.LastAdminError):
            account_data.delete_rows(users_db.get_user_by_id(u["id"]))
        assert users_db.get_user_by_id(u["id"])
    finally:
        with get_connection() as conn:
            conn.execute(
                f"UPDATE users SET is_active = 1 WHERE id IN ({','.join('?' * len(admins))})",  # nosec B608
                [a["id"] for a in admins],
            )


def test_delete_leaves_no_trace(client):
    u, h = _user()
    other, oh = _user()
    _seed_everything(u)
    _seed_everything(other)
    seeded = {t for t, _ in _rows_mentioning([u["id"], u["username"]])}
    assert seeded >= set(account_data.USER_TABLES) | {
        "telemetry_events", "ai_usage_daily", "invite_codes", "users",
    }  # fmt: skip
    with get_connection() as conn:
        children = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # nosec B608
            for t in account_data.CHILD_TABLES
        }

    r = _delete(client, h, {"password": _PW})
    assert r.status_code == 204, r.text

    assert _rows_mentioning([u["id"], u["username"]]) == []
    assert not avatar_path(u["id"]).exists()
    with get_connection() as conn:
        for t, before in children.items():  # only the deleted user's child row went
            after = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # nosec B608
            assert after == before - 1, t
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM invite_codes WHERE created_by IS NULL"
        ).fetchone()
    # the old token is dead
    assert client.get("/api/account", headers=h).status_code == 401
    # someone else's data is untouched
    assert {t for t, _ in _rows_mentioning([other["id"]])} >= set(
        t for t, (_, k) in account_data.USER_TABLES.items() if k == "id"
    )
    assert avatar_path(other["id"]).exists()
    assert client.get("/api/account", headers=oh).status_code == 200


class _FakeApple:
    id = "apple"

    def __init__(self, fail=False):
        self.revoked: list[str] = []
        self.fail = fail

    async def revoke(self, secret: str) -> None:
        self.revoked.append(secret)
        if self.fail:
            raise RuntimeError("apple is down")


@pytest.mark.parametrize("fail", [False, True])
def test_apple_identity_is_revoked(client, fail):
    fake = _FakeApple(fail=fail)
    registry.override("apple", fake)
    u, h = _user()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_identities (user_id, provider, subject, secret_enc,
                   created_at) VALUES (?, 'apple', ?, ?, ?)""",
            (u["id"], uuid.uuid4().hex, secrets_box.seal("apple-rt-123"), _now()),
        )
    assert _delete(client, h, {"password": _PW}).status_code == 204
    assert fake.revoked == ["apple-rt-123"]
    assert users_db.get_user_by_id(u["id"]) is None


def test_apple_adapter_absent_still_deletes(client):
    registry.override("apple", None)
    u, h = _user()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_identities (user_id, provider, subject, secret_enc,
                   created_at) VALUES (?, 'apple', ?, ?, ?)""",
            (u["id"], uuid.uuid4().hex, secrets_box.seal("x"), _now()),
        )
    assert _delete(client, h, {"password": _PW}).status_code == 204
    assert users_db.get_user_by_id(u["id"]) is None


def test_delete_user_events_counts():
    uid = uuid.uuid4().hex
    telemetry_db.insert_events(
        [
            {"ts": _ms(), "received_at": _ms(), "event": "e", "session_id": "s",
             "anon_id": "a", "user_id": uid, "platform": "web",
             "app_version": "1", "locale": "en", "props": json.dumps({})}
        ]
        * 2
    )  # fmt: skip
    assert telemetry_db.delete_user_events(uid) == 2
    assert telemetry_db.delete_user_events(uid) == 0


# ── post-commit cleanup never fails the request ───────────────────────────────


def _user_with_traces():
    """A user with an Apple identity, a telemetry event and an avatar file."""
    u, h = _user()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_identities (user_id, provider, subject, secret_enc,
                   created_at) VALUES (?, 'apple', ?, ?, ?)""",
            (u["id"], uuid.uuid4().hex, secrets_box.seal("apple-rt-9"), _now()),
        )
    telemetry_db.insert_events(
        [
            {"ts": _ms(), "received_at": _ms(), "event": "e", "session_id": "s",
             "anon_id": "a", "user_id": u["id"], "platform": "web",
             "app_version": "1", "locale": "en", "props": "{}"}
        ]
    )  # fmt: skip
    p = avatar_path(u["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"RIFF....WEBP")
    return u, h


def _traces_gone(u) -> bool:
    return not avatar_path(u["id"]).exists() and not [
        t for t, _ in _rows_mentioning([u["id"]])
    ]


def test_get_provider_raising_still_cleans_up(client, monkeypatch):
    def boom(_pid):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(account_data.registry, "get_provider", boom)
    u, h = _user_with_traces()
    assert _delete(client, h, {"password": _PW}).status_code == 204
    assert _traces_gone(u)


def test_revoke_raising_still_cleans_up(client):
    fake = _FakeApple(fail=True)
    registry.override("apple", fake)
    u, h = _user_with_traces()
    assert _delete(client, h, {"password": _PW}).status_code == 204
    assert fake.revoked == ["apple-rt-9"]
    assert _traces_gone(u)


def test_local_cleanup_raising_is_not_a_500(client, monkeypatch):
    def boom(_uid):
        raise ValueError("disk on fire")

    monkeypatch.setattr(account_data.telemetry_db, "delete_user_events", boom)
    registry.override("apple", _FakeApple())
    u, h = _user_with_traces()
    assert _delete(client, h, {"password": _PW}).status_code == 204
    assert users_db.get_user_by_id(u["id"]) is None
    assert not avatar_path(u["id"]).exists()  # the next step still ran


def test_cancelled_request_still_finishes_revoke_and_cleanup():
    import asyncio

    started, release = asyncio.Event(), asyncio.Event()
    done: list[str] = []

    class SlowApple:
        id = "apple"

        async def revoke(self, secret):
            started.set()
            await release.wait()
            done.append(secret)

    registry.override("apple", SlowApple())
    u, _ = _user_with_traces()

    async def run():
        req = asyncio.create_task(account_data.delete_user(u))
        await started.wait()
        # local cleanup already ran, before the first await
        assert _traces_gone(u)
        req.cancel()  # the client went away
        with pytest.raises(asyncio.CancelledError):
            await req
        release.set()
        await asyncio.gather(*account_data._pending)

    asyncio.run(run())
    assert done == ["apple-rt-9"]
    assert users_db.get_user_by_id(u["id"]) is None
