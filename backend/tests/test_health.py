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


def test_internal_streams_reports_the_open_stream_count(client, monkeypatch):
    """deploy.sh (on the VM, straight to the app container) waits for this to
    reach 0 before it recreates Caddy."""
    from app.core import sse

    monkeypatch.setattr(sse, "_active", 3)
    r = client.get("/internal/streams")
    assert r.status_code == 200
    assert r.json() == {"active_streams": 3}


def test_internal_streams_is_refused_when_forwarded(client):
    """Caddy never routes /internal/*. Should a later proxy rule widen the
    match, a forwarded request still gets a plain 404."""
    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
        r = client.get("/internal/streams", headers={header: "203.0.113.9"})
        assert r.status_code == 404, header
