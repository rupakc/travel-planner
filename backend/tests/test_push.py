"""FCM push sender: disabled without a service account, OAuth token cached,
one send per device, dead tokens pruned, every failure swallowed; and the
fire-and-forget hook where fare / price alerts are created.

No network: the OAuth exchange and FCM go through an httpx.MockTransport.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.db import devices_db, notifications_db
from app.db.users_db import create_user
from app.services import fare_watch, price_watch, push

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
TOKEN_URI = "https://oauth2.example.test/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/tp-test/messages:send"


@pytest.fixture(scope="module")
def account_file(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    path = tmp_path_factory.mktemp("fcm") / "sa.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "tp-test",
                "private_key_id": "k1",
                "private_key": pem,
                "client_email": "push@tp-test.iam.gserviceaccount.com",
                "token_uri": TOKEN_URI,
            }
        )
    )
    return str(path)


class FakeGoogle:
    """OAuth token endpoint + FCM send endpoint; ``fcm`` maps a device token
    to the (status, json) FCM answers for it (default 200)."""

    def __init__(self):
        self.token_calls = 0
        self.sends: list[dict] = []
        self.fcm: dict[str, tuple[int, dict]] = {}
        self.token_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            self.token_calls += 1
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            assert form["grant_type"].startswith("urn")
            assert form["assertion"].count(".") == 2  # a signed JWT
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "nope"})
            return httpx.Response(
                200, json={"access_token": "ya29.test", "expires_in": 3600}
            )
        assert str(request.url) == SEND_URL
        assert request.headers["authorization"] == "Bearer ya29.test"
        msg = json.loads(request.content)["message"]
        self.sends.append(msg)
        status, body = self.fcm.get(msg["token"], (200, {"name": "projects/x/m/1"}))
        return httpx.Response(status, json=body)


@pytest.fixture
def google(monkeypatch, account_file, client):
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    monkeypatch.setattr(settings, "fcm_service_account_file", account_file)
    fake = FakeGoogle()
    monkeypatch.setattr(push, "_transport", httpx.MockTransport(fake))
    push.reset()
    yield fake
    push.reset()


def _user_with_devices(n=2):
    u = create_user(f"push-{uuid.uuid4().hex[:8]}", "pw-123456789")
    tokens = [f"tok-{uuid.uuid4().hex}" for _ in range(n)]
    for t in tokens:
        devices_db.upsert_device(u["username"], t, "android", "en-GB", now=NOW)
    return u, tokens


# ── Configuration ─────────────────────────────────────────────────────────────


def test_disabled_by_default(monkeypatch, client):
    monkeypatch.setattr(settings, "fcm_service_account_file", "")
    assert push.configured() is False
    assert client.get("/health").json()["push_configured"] is False


def test_health_reports_push_configured(google, client):
    assert push.configured() is True
    assert client.get("/health").json()["push_configured"] is True


def test_missing_file_is_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "fcm_service_account_file", str(tmp_path / "x"))
    assert push.configured() is False


@pytest.mark.asyncio
async def test_disabled_sends_nothing(monkeypatch):
    monkeypatch.setattr(settings, "fcm_service_account_file", "")
    called = []
    monkeypatch.setattr(push, "_transport", httpx.MockTransport(called.append))
    u, _ = _user_with_devices(1)
    assert await push.send_to_user(u["username"], "t", "b", {}) == 0
    assert called == []


# ── Sending ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sends_to_every_device_with_string_data(google):
    u, tokens = _user_with_devices(2)
    sent = await push.send_to_user(
        u["username"], "Fare drop", "BER → LIS $454", {"kind": "fare_drop", "n": 7}
    )
    assert sent == 2
    assert sorted(m["token"] for m in google.sends) == sorted(tokens)
    msg = google.sends[0]
    assert msg["notification"] == {"title": "Fare drop", "body": "BER → LIS $454"}
    assert msg["data"] == {"kind": "fare_drop", "n": "7"}
    assert msg["android"]["priority"] == "high"


@pytest.mark.asyncio
async def test_access_token_is_cached(google):
    u, _ = _user_with_devices(1)
    await push.send_to_user(u["username"], "a", "b", {})
    await push.send_to_user(u["username"], "a", "b", {})
    assert google.token_calls == 1
    assert len(google.sends) == 2


@pytest.mark.asyncio
async def test_no_devices_no_calls(google):
    u = create_user(f"push-{uuid.uuid4().hex[:8]}", "pw-123456789")
    assert await push.send_to_user(u["username"], "a", "b", {}) == 0
    assert google.token_calls == 0


@pytest.mark.asyncio
async def test_unregistered_tokens_are_pruned(google):
    u, (dead, gone, live) = _user_with_devices(3)
    google.fcm[dead] = (
        404,
        {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}},
    )
    google.fcm[gone] = (
        400,
        {
            "error": {
                "status": "INVALID_ARGUMENT",
                "details": [{"errorCode": "UNREGISTERED"}],
            }
        },
    )
    assert await push.send_to_user(u["username"], "a", "b", {}) == 1
    assert devices_db.tokens_for(u["username"]) == [live]


@pytest.mark.asyncio
async def test_other_failures_keep_the_token_and_never_raise(google, caplog):
    u, (flaky,) = _user_with_devices(1)
    google.fcm[flaky] = (500, {"error": {"status": "INTERNAL"}})
    assert await push.send_to_user(u["username"], "a", "b", {}) == 0
    assert devices_db.tokens_for(u["username"]) == [flaky]


@pytest.mark.asyncio
async def test_token_exchange_failure_never_raises(google):
    google.token_status = 401
    u, tokens = _user_with_devices(1)
    assert await push.send_to_user(u["username"], "a", "b", {}) == 0
    assert google.sends == []
    assert devices_db.tokens_for(u["username"]) == tokens


@pytest.mark.asyncio
async def test_network_error_never_raises(monkeypatch, google):
    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(push, "_transport", httpx.MockTransport(boom))
    u, _ = _user_with_devices(1)
    assert await push.send_to_user(u["username"], "a", "b", {}) == 0


# ── Alert hook ────────────────────────────────────────────────────────────────


async def _drain():
    while push._tasks:
        await asyncio.gather(*list(push._tasks))


@pytest.mark.asyncio
async def test_fare_alert_pushes_in_the_background(google, monkeypatch):
    sender = AsyncMock(return_value=1)
    monkeypatch.setattr(push, "send_to_user", sender)
    u, _ = _user_with_devices(1)
    watch = {"id": 41, "user_id": u["id"]}
    note = {
        "kind": "fare_drop",
        "title": "Berlin → Lisbon dropped to $454",
        "body": "For 1–8 Dec",
        "data": {"watch_id": 41, "links": {"alerts": "/alerts?watch=41"}},
    }
    row = fare_watch._notify(watch, note, NOW)
    assert notifications_db.list_notifications(u["id"])["items"][0]["id"] == row["id"]
    await _drain()
    sender.assert_awaited_once_with(
        u["username"],
        "Berlin → Lisbon dropped to $454",
        "For 1–8 Dec",
        {
            "kind": "fare_drop",
            "notification_id": str(row["id"]),
            "link": "/alerts?watch=41",
            "watch_id": "41",
        },
    )


@pytest.mark.asyncio
async def test_fare_note_without_links_uses_the_alerts_page(google, monkeypatch):
    sender = AsyncMock(return_value=1)
    monkeypatch.setattr(push, "send_to_user", sender)
    u, _ = _user_with_devices(1)
    note = {"kind": "watch_expired", "title": "t", "body": "b", "data": {}}
    fare_watch._notify({"id": 7, "user_id": u["id"]}, note, NOW)
    await _drain()
    assert sender.await_args.args[3]["link"] == "/alerts?watch=7"


@pytest.mark.asyncio
async def test_price_alert_pushes_with_its_deep_link(google, monkeypatch):
    sender = AsyncMock(return_value=1)
    monkeypatch.setattr(push, "send_to_user", sender)
    u, _ = _user_with_devices(1)
    watch = {"id": 9, "kind": "hotel", "user_id": u["id"]}
    note = {
        "kind": "hotel_drop",
        "title": "Hotel dropped",
        "body": "b",
        "data": {"watch_id": 9, "watch_kind": "hotel"},
    }
    row = price_watch._notify(watch, note, NOW)
    await _drain()
    data = sender.await_args.args[3]
    assert data == {
        "kind": "hotel_drop",
        "notification_id": str(row["id"]),
        "link": "/alerts?kind=hotel&watch=9",
        "watch_id": "9",
        "watch_kind": "hotel",
    }


@pytest.mark.asyncio
async def test_hook_is_inert_when_push_is_off(monkeypatch):
    monkeypatch.setattr(settings, "fcm_service_account_file", "")
    sender = AsyncMock()
    monkeypatch.setattr(push, "send_to_user", sender)
    u, _ = _user_with_devices(1)
    note = {"kind": "fare_drop", "title": "t", "body": "b", "data": {}}
    assert fare_watch._notify({"id": 1, "user_id": u["id"]}, note, NOW)["id"]
    assert push._tasks == set()
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failing_push_never_breaks_alert_creation(google, monkeypatch):
    monkeypatch.setattr(push, "send_to_user", AsyncMock(side_effect=RuntimeError))
    u, _ = _user_with_devices(1)
    note = {"kind": "fare_drop", "title": "t", "body": "b", "data": {}}
    row = fare_watch._notify({"id": 1, "user_id": u["id"]}, note, NOW)
    await _drain()
    assert row["kind"] == "fare_drop"


def test_hook_without_a_running_loop_is_a_no_op(google):
    u, _ = _user_with_devices(1)
    note = {"kind": "fare_drop", "title": "t", "body": "b", "data": {}}
    assert fare_watch._notify({"id": 1, "user_id": u["id"]}, note, NOW)["id"]
