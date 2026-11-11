import asyncio
import importlib

import pytest
from fastapi import APIRouter
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
    @app_main.app.get("/api/_seam_err")
    def boom():
        raise ApiError(409, "username_taken", "x", bucket="s")

    r = TestClient(app_main.app).get("/api/_seam_err")
    assert r.status_code == 409
    assert r.json() == {"detail": "x", "error_code": "username_taken", "bucket": "s"}


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


def test_hooks_stubs_return_none():
    from app.game import hooks

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
