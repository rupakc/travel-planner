def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_has_request_id(client):
    r = client.get("/health")
    assert "x-request-id" in r.headers
    assert len(r.headers["x-request-id"]) == 36  # UUID


def test_health_propagates_request_id(client):
    r = client.get("/health", headers={"X-Request-ID": "my-custom-id"})
    assert r.headers.get("x-request-id") == "my-custom-id"


def test_health_reports_serpapi_configured(client, monkeypatch):
    """The frontend reads this (no LLM call) to offer the fare calendar."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "serpapi_key", "")
    assert client.get("/health").json()["serpapi_configured"] is False
    monkeypatch.setattr(settings, "serpapi_key", "k")
    assert client.get("/health").json()["serpapi_configured"] is True


def test_health_has_no_backup_fields_outside_vm_mode(client):
    body = client.get("/health").json()
    assert "backup_ok" not in body


def test_health_reports_vm_backup_status(client, monkeypatch):
    """The uptime check content-matches "backup_ok":true."""
    import time

    from app.db import vm_backup

    state = vm_backup.BackupState(started_at=time.time())
    monkeypatch.setattr(vm_backup, "_state", state)
    r = client.get("/health")
    assert '"backup_ok":true' in r.text
    state.last_error = "ConnectionError: gcs down"
    body = client.get("/health").json()
    assert body["backup_ok"] is False
    assert body["backup"]["error"].startswith("ConnectionError")
