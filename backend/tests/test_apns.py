"""APNs sender and platform routing. No network: httpx.MockTransport."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import settings
from app.db import devices_db
from app.db.users_db import create_user
from app.services import apns, push

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key()
    return pem, pub


class FakeApple:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.answers: dict[str, httpx.Response] = {}

    def __call__(self, request):
        self.requests.append(request)
        token = request.url.path.rsplit("/", 1)[1]
        return self.answers.get(token, httpx.Response(200))


@pytest.fixture
def apple(monkeypatch, keypair, client):
    monkeypatch.setattr(settings, "apns_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apns_key_id", "KEY1234567")
    monkeypatch.setattr(settings, "apns_key_p8", keypair[0])
    monkeypatch.setattr(settings, "apns_key_file", "")
    monkeypatch.setattr(settings, "apns_sandbox", False)
    fake = FakeApple()
    monkeypatch.setattr(apns, "_transport", httpx.MockTransport(fake))
    apns.reset()
    yield fake
    apns.reset()


def _user(platforms):
    u = create_user(f"apns-{uuid.uuid4().hex[:8]}", "pw-123456789")
    toks = []
    for p in platforms:
        t = f"{p}-{uuid.uuid4().hex}"
        devices_db.upsert_device(u["username"], t, p, "en", now=NOW)
        toks.append(t)
    return u, toks


def run(coro):
    return asyncio.run(coro)


def test_inert_when_unconfigured(monkeypatch, client):
    monkeypatch.setattr(settings, "apns_team_id", "")
    assert apns.configured() is False
    u, _ = _user(["ios"])
    assert run(apns.send_to_user(u["username"], "t", "b", {})) == 0


def test_provider_token_claims_and_cache(apple, keypair):
    tok = apns.provider_token(now=1000.0)
    hdr = jwt.get_unverified_header(tok)
    assert hdr["alg"] == "ES256" and hdr["kid"] == "KEY1234567"
    claims = jwt.decode(
        tok, keypair[1], algorithms=["ES256"], options={"verify_iat": False}
    )
    assert claims == {"iss": "TEAM123456", "iat": 1000}
    assert apns.provider_token(now=1000.0 + 49 * 60) == tok
    assert apns.provider_token(now=1000.0 + 51 * 60) != tok


def test_send_request_shape(apple):
    u, (t,) = _user(["ios"])
    n = run(
        apns.send_to_user(
            u["username"],
            "Hi",
            "There",
            {"link": "/x", "category": "c", "notification_id": 7},
        )
    )
    assert n == 1
    r = apple.requests[0]
    assert str(r.url) == f"https://api.push.apple.com/3/device/{t}"
    assert r.headers["apns-topic"] == settings.apns_bundle_id
    assert r.headers["apns-push-type"] == "alert"
    assert r.headers["apns-priority"] == "10"
    assert r.headers["authorization"].startswith("bearer ")
    body = json.loads(r.content)
    assert body["aps"] == {
        "alert": {"title": "Hi", "body": "There"},
        "sound": "default",
    }
    assert body["link"] == "/x" and body["category"] == "c"
    assert body["notification_id"] == "7"


def test_sandbox_host_and_quiet_priority(apple, monkeypatch):
    monkeypatch.setattr(settings, "apns_sandbox", True)
    u, _ = _user(["ios"])
    run(apns.send_to_user(u["username"], "t", "b", {"kind": "watch_expired"}))
    r = apple.requests[0]
    assert r.url.host == "api.sandbox.push.apple.com"
    assert r.headers["apns-priority"] == "5"


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(410, json={"reason": "Unregistered"}),
        httpx.Response(400, json={"reason": "BadDeviceToken"}),
    ],
)
def test_dead_tokens_pruned(apple, resp):
    u, (t,) = _user(["ios"])
    apple.answers[t] = resp
    assert run(apns.send_to_user(u["username"], "t", "b", {})) == 0
    assert devices_db.devices_for(u["username"]) == []


def test_other_failure_keeps_token_and_never_logs_full_token(apple, caplog):
    u, (t,) = _user(["ios"])
    apple.answers[t] = httpx.Response(500, json={"reason": "InternalServerError"})
    with caplog.at_level("INFO"):
        assert run(apns.send_to_user(u["username"], "t", "b", {})) == 0
    assert devices_db.devices_for(u["username"]) == [(t, "ios")]
    assert t not in caplog.text


def test_network_error_swallowed(apple, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(apns, "_transport", httpx.MockTransport(boom))
    u, _ = _user(["ios"])
    assert run(apns.send_to_user(u["username"], "t", "b", {})) == 0


def test_devices_for(client):
    u, (a, i) = _user(["android", "ios"])
    assert devices_db.devices_for(u["username"]) == [(a, "android"), (i, "ios")]
    assert devices_db.tokens_for(u["username"]) == [a, i]


def test_routing_flag_on_splits_by_platform(apple, monkeypatch):
    monkeypatch.setattr(settings, "notifications_v2_enabled", True)
    sent_fcm = []

    async def fake_fcm(username, title, body, data, tokens=None):
        sent_fcm.append(tokens)
        return len(tokens)

    monkeypatch.setattr(push, "_send_fcm", fake_fcm)
    u, (a, i) = _user(["android", "ios"])
    n = run(push.send_to_user(u["username"], "t", "b", {}))
    assert n == 2 and sent_fcm == [[a]]
    assert apple.requests[0].url.path.endswith(i)


def test_routing_flag_on_fcm_unconfigured_does_not_block_apns(apple, monkeypatch):
    monkeypatch.setattr(settings, "notifications_v2_enabled", True)
    monkeypatch.setattr(settings, "fcm_service_account_file", "")
    monkeypatch.setattr(settings, "fcm_use_adc", False)
    u, _ = _user(["android", "ios"])
    assert run(push.send_to_user(u["username"], "t", "b", {})) == 1


def test_routing_flag_on_apns_unconfigured_does_not_block_fcm(monkeypatch, client):
    monkeypatch.setattr(settings, "notifications_v2_enabled", True)
    monkeypatch.setattr(settings, "apns_team_id", "")
    got = []

    async def fake_fcm(username, title, body, data, tokens=None):
        got.append(tokens)
        return 1

    monkeypatch.setattr(push, "_send_fcm", fake_fcm)
    u, (a, _i) = _user(["android", "ios"])
    assert run(push.send_to_user(u["username"], "t", "b", {})) == 1
    assert got == [[a]]


def test_flag_off_is_fcm_path_for_all_tokens(apple, monkeypatch):
    monkeypatch.setattr(settings, "notifications_v2_enabled", False)
    got = []

    async def fake_fcm(username, title, body, data, tokens=None):
        got.append(tokens)
        return 0

    monkeypatch.setattr(push, "_send_fcm", fake_fcm)
    u, _ = _user(["android", "ios"])
    run(push.send_to_user(u["username"], "t", "b", {}))
    assert got == [None] and apple.requests == []


def test_register_ios_device(client):
    from app.core.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"username": "ios-reg"}
    try:
        r = client.post("/api/devices", json={"token": "abc123456", "platform": "ios"})
        assert r.status_code == 200 and r.json()["platform"] == "ios"
        assert (
            client.post(
                "/api/devices", json={"token": "x", "platform": "web"}
            ).status_code
            == 422
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
