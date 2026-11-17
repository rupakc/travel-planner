"""Tripadvisor Terra ratings: on demand, hard budget, no stored content.

Terra is always stubbed with httpx.MockTransport (``tripadvisor._transport``);
the autouse guard in conftest fails any test that would reach the network."""

import logging
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.core import cache as shared_cache
from app.core import llm
from app.core import rate_limit as rl
from app.core.auth import create_access_token
from app.core.config import settings
from app.db import api_budget_db
from app.db.database import _db_path
from app.db.users_db import create_user
from app.services import alert_email, tripadvisor

KEY = "terra-test-key-0123456789"
SECRET_NAME = "Eiffel Tower Sentinel"  # a content marker searched for afterwards


def _loc(i: int, name: str | None = None) -> dict:
    return {
        "id": i,
        "geo": "Paris",
        "geo_id": 187147,
        "names": [{"language": "en", "value": name or f"Sight {i}", "primary": True}],
        "descriptions": [{"language": "en", "value": "A long description"}],
        "photos": {"total_count": 10},
        "status": {"value": "OPEN"},
        "traveler_ratings": {
            "overall": {
                "rating": 4.5,
                "count": 1000 + i,
                "icon_url": f"https://www.tripadvisor.com/img/ratings/4.5-{i}.svg",
            }
        },
        "rankings": [{"display_text": f"#{i} of 3,000 things to do in Paris"}],
        "categories": [{"id": 47, "display_name": "Sights & Landmarks"}],
        "urls": {
            "tripadvisor": {
                "main": f"https://www.tripadvisor.com/Attraction_Review-d{i}",
                "photos": f"https://www.tripadvisor.com/Attraction_Review-d{i}#photos",
                "write_review": f"https://www.tripadvisor.com/UserReview-d{i}",
            }
        },
    }


class Terra:
    """A fake Terra: records requests, answers nearby / multi-get."""

    def __init__(self, nearby_count=3, status=200, exc=None):
        self.requests: list[httpx.Request] = []
        self.nearby_count = nearby_count
        self.status = status
        self.exc = exc

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.exc:
            raise self.exc
        if self.status >= 400:
            return httpx.Response(self.status, json={"title": "err"})
        if request.url.path.endswith("/locations/nearby"):
            size = int(request.url.params["size"])
            n = min(size, self.nearby_count)
            locs = [_loc(100 + k, SECRET_NAME if k == 0 else None) for k in range(n)]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"location": loc, "distance_kilometers": 1.0} for loc in locs
                    ],
                    "pagination": {"page": 1, "size": size},
                },
            )
        if request.url.path.endswith("/locations"):
            ids = [int(x) for x in request.url.params["id"].split(",")]
            # out of order on purpose: the client keeps the cached order
            return httpx.Response(
                200,
                json={
                    "data": [
                        _loc(i, SECRET_NAME if i == 100 else None)
                        for i in reversed(ids)
                    ]
                },
            )
        return httpx.Response(404)


@pytest.fixture
def terra(monkeypatch, client):
    monkeypatch.setattr(settings, "tripadvisor_enabled", True)
    monkeypatch.setattr(settings, "tripadvisor_api_key", KEY)
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 1000)
    monkeypatch.setattr(settings, "tripadvisor_page_size", 5)
    monkeypatch.setattr(tripadvisor, "NEARBY_MIN_INTERVAL_S", 0)
    with sqlite3.connect(_db_path()) as conn:
        conn.execute("DELETE FROM api_budget")
        conn.execute("DELETE FROM tripadvisor_location_ids")
    fake = Terra()
    monkeypatch.setattr(tripadvisor, "_transport", httpx.MockTransport(fake))
    return fake


def _user(**kw):
    u = create_user(f"ta-{uuid.uuid4().hex[:8]}", "pw-123456789", **kw)
    return u, {"Authorization": f"Bearer {create_access_token({'sub': u['username']})}"}


def _used() -> int:
    return api_budget_db.status("tripadvisor", settings.tripadvisor_budget_cap)["used"]


def _set_used(n: int) -> None:
    api_budget_db.reserve("tripadvisor", n, settings.tripadvisor_budget_cap)


def _post(client, headers, destination="Paris"):
    return client.post(
        "/api/tripadvisor/attractions",
        json={"destination": destination},
        headers=headers,
    )


# ── Feature flag, auth ───────────────────────────────────────────────────────


def test_flag_off_is_404_and_hidden_in_config(client):
    assert settings.tripadvisor_enabled is False  # default
    _, h = _user()
    assert _post(client, h).status_code == 404
    assert client.get("/api/config").json()["features"]["tripadvisor"] is False


def test_flag_on_without_key_is_404(client, monkeypatch):
    monkeypatch.setattr(settings, "tripadvisor_enabled", True)
    monkeypatch.setattr(settings, "tripadvisor_api_key", "")
    _, h = _user()
    assert _post(client, h).status_code == 404
    assert client.get("/api/config").json()["features"]["tripadvisor"] is False


def test_config_reports_feature_when_on(client, terra):
    assert client.get("/api/config").json()["features"]["tripadvisor"] is True


def test_requires_sign_in(client, terra):
    assert _post(client, {}).status_code == 401
    assert terra.requests == []


def test_unknown_destination_is_422_without_a_call(client, terra):
    _, h = _user()
    r = _post(client, h, "Qwxzzv Nowhereville")
    assert r.status_code == 422
    assert r.json()["error_code"] == "unknown_destination"
    assert terra.requests == []


# ── Calls, attribution, budget math ──────────────────────────────────────────


def test_first_view_uses_nearby_and_refunds_unreturned_units(client, terra):
    _, h = _user()
    r = _post(client, h)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "noindex" in r.headers["x-robots-tag"]
    body = r.json()
    assert body["status"] == "ok"
    assert body["attribution"]["name"] == "Tripadvisor"
    assert body["attribution"]["logo_url"].startswith("https://")
    assert [i["id"] for i in body["items"]] == [100, 101, 102]
    first = body["items"][0]
    assert first["name"] == SECRET_NAME
    assert first["web_url"].startswith("https://www.tripadvisor.com/")
    assert first["rating"] == 4.5 and first["num_reviews"] == 1100
    assert first["rating_image_url"].startswith("https://www.tripadvisor.com/")
    (req,) = terra.requests
    assert req.url.path == "/api/locations/nearby"
    assert req.headers["x-api-key"] == KEY
    assert req.url.params["version"] == "1"
    assert req.url.params["size"] == "5"
    assert req.url.params["category"] == "ATTRACTION"
    # 5 reserved, 3 returned → 3 billed
    assert _used() == 3
    # The key never reaches the client
    assert KEY not in r.text


def test_repeat_view_uses_cached_ids_only(client, terra):
    _, h = _user()
    _post(client, h)
    r = _post(client, h)
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == [100, 101, 102]  # cached order
    assert len(terra.requests) == 2
    second = terra.requests[1]
    assert second.url.path == "/api/locations"
    assert second.url.params["id"] == "100,101,102"
    assert _used() == 6


def test_reservation_shrinks_the_request_to_the_remaining_budget(
    client, terra, monkeypatch
):
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 7)
    _set_used(5)
    terra.nearby_count = 20
    _, h = _user()
    body = _post(client, h).json()
    assert terra.requests[0].url.params["size"] == "2"
    assert len(body["items"]) == 2
    assert _used() == 7


def test_paused_at_cap_makes_no_call(client, terra, monkeypatch):
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 4)
    _set_used(4)
    _, h = _user()
    r = _post(client, h)
    assert r.status_code == 200
    assert r.json() == {
        "status": "paused",
        "items": [],
        "attribution": tripadvisor.attribution(),
    }
    assert terra.requests == []
    assert _used() == 4


def test_terra_error_is_not_billed(client, terra):
    terra.status = 500
    _, h = _user()
    r = _post(client, h)
    assert r.status_code == 502
    assert r.json()["error_code"] == "tripadvisor_unavailable"
    assert _used() == 0


def test_rate_limited_by_terra_is_not_billed(client, terra):
    terra.status = 429
    _, h = _user()
    assert _post(client, h).status_code == 502
    assert _used() == 0


def test_connection_never_opened_is_refunded(client, terra):
    terra.exc = httpx.ConnectError("down")
    _, h = _user()
    assert _post(client, h).status_code == 502
    assert _used() == 0


def test_timeout_after_sending_keeps_the_reservation(client, terra):
    terra.exc = httpx.ReadTimeout("slow")
    _, h = _user()
    assert _post(client, h).status_code == 502
    assert _used() == 5  # may have been billed: never undercount


def test_concurrent_reservations_never_exceed_the_cap(client, terra):
    cap = 37
    barrier = threading.Barrier(16)

    def grab(_):
        barrier.wait()
        got = 0
        for _ in range(10):
            got += api_budget_db.reserve("tripadvisor", 3, cap)
        return got

    with ThreadPoolExecutor(16) as pool:
        total = sum(pool.map(grab, range(16)))
    assert total == cap
    assert api_budget_db.status("tripadvisor", cap)["used"] == cap


def test_budget_survives_restart(client, terra):
    _set_used(42)
    api_budget_db.create_api_budget_tables()  # startup again: nothing reset
    assert _used() == 42


def test_warns_once_at_80_percent_and_once_at_cap(client, terra, monkeypatch, caplog):
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 10)
    _set_used(5)
    terra.nearby_count = 20
    _, h = _user()
    with caplog.at_level(logging.WARNING, logger="app.services.tripadvisor"):
        _post(client, h)  # 5 → 10: both thresholds crossed
        with sqlite3.connect(_db_path()) as conn:
            conn.execute("DELETE FROM tripadvisor_location_ids")
        _post(client, h)  # paused: no new warnings
    lines = [
        r.getMessage() for r in caplog.records if "tripadvisor_budget" in r.getMessage()
    ]
    assert lines == [
        "tripadvisor_budget level=warn used=10 cap=10",
        "tripadvisor_budget level=exhausted used=10 cap=10",
    ]


def test_warning_fires_at_800_of_1000(client, terra, caplog):
    _set_used(797)
    _, h = _user()
    with caplog.at_level(logging.WARNING, logger="app.services.tripadvisor"):
        _post(client, h)  # +3 → 800
        _post(client, h)  # +3 → 803: no repeat
    lines = [
        r.getMessage() for r in caplog.records if "tripadvisor_budget" in r.getMessage()
    ]
    assert lines == ["tripadvisor_budget level=warn used=800 cap=1000"]


def test_raising_the_cap_rearms_and_unpauses(client, terra, monkeypatch):
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 3)
    _set_used(3)
    assert tripadvisor.budget_status()["paused"] is True
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 100)
    assert tripadvisor.budget_status()["paused"] is False
    _, h = _user()
    assert _post(client, h).json()["status"] == "ok"


def test_owner_is_emailed_when_smtp_is_configured(client, terra, monkeypatch):
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 5)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@example.test")
    monkeypatch.setattr(settings, "admin_email", "owner@example.test")
    sent = []
    monkeypatch.setattr(alert_email, "send_message", lambda msg: sent.append(msg))
    terra.nearby_count = 20
    _, h = _user()
    _post(client, h)
    subjects = sorted(m["Subject"] for m in sent)
    assert subjects == [
        "Tripadvisor API budget at 80%",
        "Tripadvisor ratings paused: API budget reached",
    ]
    assert all(m["To"] == "owner@example.test" for m in sent)


def test_no_email_without_smtp(client, terra, monkeypatch):
    monkeypatch.setattr(settings, "tripadvisor_budget_cap", 5)
    monkeypatch.setattr(settings, "admin_email", "owner@example.test")
    sent = []
    monkeypatch.setattr(alert_email, "send_message", lambda msg: sent.append(msg))
    terra.nearby_count = 20
    _, h = _user()
    _post(client, h)
    assert sent == []


# ── Terms: nothing but IDs is stored; no AI ──────────────────────────────────


def test_only_location_ids_are_persisted(client, terra):
    _, h = _user()
    _post(client, h)
    _post(client, h)
    with sqlite3.connect(_db_path()) as conn:
        rows = conn.execute(
            "SELECT place_key, location_ids FROM tripadvisor_location_ids"
        ).fetchall()
        assert len(rows) == 1 and rows[0][1] == "[100, 101, 102]"
        assert set(
            r[1] for r in conn.execute("PRAGMA table_info(tripadvisor_location_ids)")
        ) == {
            "place_key",
            "location_ids",
            "created_at",
        }
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):  # noqa: S608
                for value in row:
                    if isinstance(value, str):
                        assert SECRET_NAME not in value, table
                        assert "tripadvisor.com/" not in value, table
    # Not in the shared response cache either
    for value in list(shared_cache.get_cache().values()):
        assert SECRET_NAME not in repr(value)


def test_no_llm_call_ever_sees_tripadvisor_content(client, terra, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Tripadvisor content must never reach an LLM")

    for name in ("generate", "stream", "generate_sync", "generate_grounded"):
        monkeypatch.setattr(llm, name, boom)
    _, h = _user()
    assert _post(client, h).status_code == 200
    assert _post(client, h).status_code == 200


def test_content_is_not_logged(client, terra, caplog):
    _, h = _user()
    with caplog.at_level(logging.DEBUG):
        _post(client, h)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET_NAME not in text
    assert KEY not in text


def test_key_is_redacted_from_log_lines(monkeypatch):
    from app.core.logging_config import RedactSecrets

    monkeypatch.setattr(settings, "tripadvisor_api_key", KEY)
    record = logging.LogRecord(
        "x", logging.ERROR, __file__, 1, "header %s", (KEY,), None
    )
    RedactSecrets().filter(record)
    assert KEY not in record.getMessage()
    assert "[redacted]" in record.getMessage()


def test_items_without_a_tripadvisor_link_are_dropped():
    loc = _loc(1)
    loc["urls"] = {"tripadvisor": {"main": "http://evil.example/x"}}
    assert tripadvisor.display_item(loc) is None
    assert tripadvisor.display_item(_loc(2))["web_url"].startswith(
        "https://www.tripadvisor.com/"
    )


# ── Rate limit, health, admin ────────────────────────────────────────────────


def test_own_rate_limit_bucket(client, terra, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_tripadvisor", 2)
    _, h = _user()
    assert _post(client, h).status_code == 200
    assert _post(client, h).status_code == 200
    r = _post(client, h)
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    rl.limiter.prune(0)


def test_health_reports_budget(client, terra, monkeypatch):
    _set_used(12)
    body = client.get("/health").json()
    assert body["tripadvisor"] == {
        "configured": True,
        "enabled": True,
        "used": 12,
        "cap": 1000,
        "paused": False,
    }
    assert body["tripadvisor_budget_ok"] is True
    _set_used(800)
    assert client.get("/health").json()["tripadvisor_budget_ok"] is False


def test_admin_budget_endpoint(client, terra, admin_headers):
    _, h = _user()
    assert client.get("/api/admin/tripadvisor/budget", headers=h).status_code == 403
    r = client.get("/api/admin/tripadvisor/budget", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["used"] == 0 and r.json()["cap"] == 1000
    assert KEY not in r.text
