"""Phase 3 backend seams: tables, the _notify pipeline seam, stubs."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.db import alerts_db
from app.db.database import get_connection
from app.services import alert_delivery, alert_pipeline, fare_watch, price_watch

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

COLUMNS = {
    "alert_prefs": ["user_id", "data", "updated_at"],
    "alert_savings": [
        "id", "user_id", "watch_kind", "watch_id", "notification_id",
        "from_price", "to_price", "baseline", "currency", "target_hit",
        "created_at",
    ],
    "alert_outbox": [
        "id", "user_id", "notification_id", "channel", "watch_kind",
        "due_at", "sent_at", "dropped_reason",
        "claimed_at", "attempts", "next_try_at",
    ],
    "alert_digests": ["user_id", "week", "status", "sent_at"],
    "alert_advice": ["watch_kind", "watch_id", "tip", "generated_at", "locale"],
}  # fmt: skip


def _cols(table):
    with get_connection() as conn:
        return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_alert_tables_idempotent():
    alerts_db.create_alert_tables()
    alerts_db.create_alert_tables()
    for table, cols in COLUMNS.items():
        assert _cols(table) == cols


def test_outbox_and_savings_helpers():
    alerts_db.create_alert_tables()
    assert alerts_db.enqueue("u", 1, "push", "flight", "2026-01-01T00:00:00")
    assert not alerts_db.enqueue("u", 1, "push", "flight", "2026-01-01T00:00:00")
    assert not alerts_db.enqueue("u", 2, "sms", "flight", "2026-01-01T00:00:00")
    assert len(alerts_db.claim_due("2026-02-01T00:00:00", 10)) == 1
    assert alerts_db.claim_due("2026-02-01T00:00:00", 10) == []
    row = {"user_id": "u", "watch_kind": "hotel", "watch_id": 1, "notification_id": 9}
    assert alerts_db.insert_saving(row)
    assert not alerts_db.insert_saving(row)
    assert alerts_db.digest_claim("u", "2026-W46")
    assert not alerts_db.digest_claim("u", "2026-W46")
    assert alerts_db.get_prefs("nobody")["digest_push"] is False


class _Spy:
    def __init__(self, monkeypatch, module):
        self.calls = []
        monkeypatch.setattr(
            module.push, "notify", lambda *a, **k: self.calls.append(("push", a))
        )


def _note():
    return {"kind": "fare_drop", "title": "t", "body": "b", "data": {"x": 1}}


@pytest.fixture
def users(monkeypatch):
    alerts_db.create_alert_tables()
    from app.db.notifications_db import create_notifications_table

    create_notifications_table()
    # notifications.user_id references users(id); FK is not enforced here
    return "u1"


@pytest.mark.parametrize("module", [fare_watch, price_watch])
def test_flag_off_notify_unchanged(monkeypatch, users, module):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", False)
    spy = _Spy(monkeypatch, module)
    monkeypatch.setattr(alert_pipeline, "enrich", lambda *a: pytest.fail("enrich ran"))
    monkeypatch.setattr(
        alert_pipeline, "after_insert", lambda *a: pytest.fail("after_insert ran")
    )
    row = module._notify({"id": 3, "user_id": users, "kind": "hotel"}, _note(), NOW)
    assert row["data"] == {"x": 1}
    assert len(spy.calls) == 1


@pytest.mark.parametrize("module", [fare_watch, price_watch])
@pytest.mark.parametrize("took_over", [False, True])
def test_flag_on_calls_pipeline(monkeypatch, users, module, took_over):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    spy = _Spy(monkeypatch, module)
    order = []

    def enrich(watch, kind, note):
        order.append("enrich")
        return {**note, "data": {**note["data"], "drop": {"to": 1}}}

    def after_insert(watch, kind, row, now):
        order.append("after")
        assert row["data"]["drop"] == {"to": 1}  # enriched before the insert
        return took_over

    monkeypatch.setattr(alert_pipeline, "enrich", enrich)
    monkeypatch.setattr(alert_pipeline, "after_insert", after_insert)
    row = module._notify({"id": 3, "user_id": users, "kind": "hotel"}, _note(), NOW)
    assert order == ["enrich", "after"]
    assert len(spy.calls) == (0 if took_over else 1)
    assert bool(row["data"].get("_v2")) is took_over


def test_stubs_are_inert():
    assert alert_delivery.flush(NOW) == 0
    assert asyncio.run(alert_delivery.stop_loop(None)) is None


def test_start_loop_none_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", False)
    assert alert_delivery.start_loop() is None


@pytest.mark.parametrize("module", [fare_watch, price_watch])
def test_after_insert_raising_falls_back_to_legacy(monkeypatch, users, module):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    spy = _Spy(monkeypatch, module)

    def boom(*a):
        raise RuntimeError("x")

    monkeypatch.setattr(alert_pipeline, "enrich", lambda w, k, n: n)
    monkeypatch.setattr(alert_pipeline, "after_insert", boom)
    row = module._notify({"id": 3, "user_id": users, "kind": "hotel"}, _note(), NOW)
    assert len(spy.calls) == 1
    assert "_v2" not in row["data"]


@pytest.mark.parametrize("module", [fare_watch, price_watch])
def test_enrich_raising_still_inserts_unenriched(monkeypatch, users, module):
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    spy = _Spy(monkeypatch, module)

    def boom(*a):
        raise RuntimeError("x")

    monkeypatch.setattr(alert_pipeline, "enrich", boom)
    monkeypatch.setattr(alert_pipeline, "after_insert", lambda *a: False)
    row = module._notify({"id": 3, "user_id": users, "kind": "hotel"}, _note(), NOW)
    assert row["data"] == {"x": 1}
    assert len(spy.calls) == 1
