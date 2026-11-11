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
    assert body["features"] == {"telemetry": True}
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
