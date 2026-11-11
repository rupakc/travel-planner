"""GET /api/config: public client config."""

from app.core.config import settings


def test_config_shape(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["public_base_url"].startswith("http")
    assert body["telemetry"] == {
        "enabled": True,
        "flush_interval_s": 15,
        "max_batch": 50,
    }
    assert body["features"] == {"telemetry": True, "accounts": True, "game": True}
    assert r.headers["cache-control"] == "max-age=300"


def test_config_uses_setting_when_set(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://voyager.example")
    body = client.get("/api/config").json()
    assert body["public_base_url"] == "https://voyager.example"


def test_config_reflects_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "telemetry_enabled", False)
    body = client.get("/api/config").json()
    assert body["telemetry"]["enabled"] is False
    assert body["features"]["telemetry"] is False


def test_config_auth_block(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example")
    monkeypatch.setattr(settings, "signup_mode", "invite")
    monkeypatch.setattr(settings, "game_enabled", False)
    monkeypatch.setattr(settings, "public_base_url", "")
    monkeypatch.setattr(settings, "app_base_url", "https://app.example/")
    body = client.get("/api/config").json()
    assert body["public_base_url"] == "https://app.example"
    assert body["auth"] == {
        "signup_mode": "invite",
        "signup_available": True,
        "password_reset_available": True,
        "min_password_length": 10,
        "verify_ttl_s": 1800,
    }
    assert body["features"]["accounts"] is True
    assert body["features"]["game"] is False


def test_config_signup_unavailable_without_email(client, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "email_log_links", False)
    monkeypatch.setattr(settings, "public_base_url", "https://voyager.example")
    auth = client.get("/api/config").json()["auth"]
    assert auth["signup_available"] is False
    assert auth["password_reset_available"] is False
