import asyncio
import importlib

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app import main as app_main
from app.core import ai_quota
from app.core.config import settings
from app.core.errors import ApiError
from app.core.session_payload import user_payload
from app.core.urls import public_url

USER_KEYS = {
    "id", "username", "display_name", "email", "email_verified", "is_admin",
    "requires_password_change", "account_verified", "has_password",
    "signup_method", "avatar_url",
}  # fmt: skip


def test_api_error_envelope():
    app = FastAPI()
    app.add_exception_handler(ApiError, app_main._api_error_handler)

    @app.get("/boom")
    def boom():
        raise ApiError(
            409, "username_taken", "x", headers={"Retry-After": "5"}, bucket="s"
        )

    r = TestClient(app).get("/boom")
    assert r.status_code == 409
    assert r.json() == {"detail": "x", "error_code": "username_taken", "bucket": "s"}
    assert r.headers["retry-after"] == "5"


def test_public_url_prefers_public_base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://a.example/")
    assert public_url("/verify") == "https://a.example/verify"
    monkeypatch.setattr(settings, "public_base_url", "")
    monkeypatch.setattr(settings, "app_base_url", "https://b.example/")
    assert public_url("/verify") == "https://b.example/verify"


def test_user_payload_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "public_base_url", "https://a.example")
    user = {
        "id": "u1", "username": "jane", "email": "j@x.io", "password_hash": "!",
        "avatar_source": "upload", "avatar_rev": 3,
    }  # fmt: skip
    p = user_payload(user)
    assert set(p) == USER_KEYS
    assert p["display_name"] == "jane"
    assert p["avatar_url"] is None
    assert p["has_password"] is False
    assert p["account_verified"] is True  # legacy rows count as admin-made
    (tmp_path / "avatars").mkdir()
    (tmp_path / "avatars" / "u1.webp").write_bytes(b"x")
    assert (
        user_payload(user)["avatar_url"] == "https://a.example/api/avatars/u1.webp?v=3"
    )
    p2 = user_payload({**user, "password_hash": "h", "signup_method": "password"})
    assert user_payload({**user, "password_hash": None})["has_password"] is False
    assert (
        user_payload({k: v for k, v in user.items() if k != "password_hash"})[
            "has_password"
        ]
        is False
    )
    assert p2["has_password"] is True and p2["account_verified"] is False


@pytest.mark.parametrize(
    "name",
    "signup sessions oauth account avatars account_data game quota admin_invites".split(),
)
def test_stub_routers_importable(name):
    mod = importlib.import_module(f"app.api.routes.{name}")
    assert isinstance(mod.router, APIRouter)


def test_account_stub_answers_404_or_405():
    r = TestClient(app_main.app).get("/api/account")
    assert r.status_code in (404, 405)


def test_limited_includes_quota_dependency():
    deps = app_main._limited("search")
    assert len(deps) == 3
    assert asyncio.run(deps[2].dependency()) is None
    assert callable(ai_quota.daily_quota("search"))


def test_hooks_return_none_when_game_disabled(monkeypatch):
    from app.core.config import settings
    from app.game import hooks

    monkeypatch.setattr(settings, "game_enabled", False)
    assert hooks.on_email_verified("u") is None
    assert hooks.on_onboarding_complete("u") is None


def test_account_maintenance_loop_survives_errors():
    from app.services import account_maintenance as am

    calls = []

    def purge(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"x": 1}

    async def run():
        t = asyncio.create_task(am.account_maintenance(purge, interval=0.01))
        await asyncio.sleep(0.1)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(run())
    assert len(calls) >= 2


def test_phase1_setting_defaults():
    from app.core.config import Settings

    expected = {
        "signup_mode": "open", "email_log_links": False,
        "account_token_ttl_minutes": 30, "pending_purge_days": 7,
        "refresh_token_days": 60, "refresh_family_max_days": 365,
        "mobile_access_token_minutes": 60,
        "google_client_id": "", "google_client_secret": "",
        "google_native_client_ids": [], "github_client_id": "",
        "github_client_secret": "", "facebook_app_id": "",
        "facebook_app_secret": "", "facebook_graph_version": "v24.0",
        "facebook_email_trusted": False, "apple_services_id": "",
        "apple_team_id": "", "apple_key_id": "", "apple_private_key": "",
        "apple_native_client_ids": [],
        "oauth_mobile_redirects": ["voyager://auth/callback"],
        "ai_daily_quota_enabled": True, "ai_daily_quota_search": 20,
        "ai_daily_quota_chat": 100, "ai_daily_quota_compare": 40,
        "ai_daily_quota_discover": 20, "ai_daily_quota_light_ai": 200,
        "ai_daily_quota_import": 20, "game_enabled": True, "game_rules_path": "",
        "rate_limit_auth_email": 10, "rate_limit_email_address": 3,
        "rate_limit_signup": 5, "rate_limit_oauth": 30,
        "rate_limit_refresh": 60, "rate_limit_account": 30,
    }  # fmt: skip
    for name, default in expected.items():
        assert Settings.model_fields[name].default == default, name


def test_lifespan_starts_and_cancels_maintenance(monkeypatch):
    started = []
    cancelled = []

    async def fake(*a, **k):
        started.append(1)
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(1)
            raise

    monkeypatch.setattr(app_main, "account_maintenance", fake)
    with TestClient(app_main.app):
        assert started == [1]
    assert cancelled == [1]
