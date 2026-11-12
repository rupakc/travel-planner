"""Deal hunter: XP, badges, the savings ledger and the pipeline seam (Task 5)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import alerts_db, notifications_db, user_settings_db, users_db
from app.db.database import get_connection
from app.game import alert_hooks, engine
from app.services import alert_delivery, alert_moments, alert_pipeline

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def uid(client):
    alerts_db.create_alert_tables()
    return users_db.create_user(f"d{uuid.uuid4().hex[:10]}", "pw-long-enough-1")["id"]


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "price_alerts_v2_enabled", True)
    monkeypatch.setattr(alert_delivery, "dispatch", lambda *a: calls.append(a))
    return calls


def _note(kind, price, prev):
    return {"kind": kind, "title": "t", "body": "b",
            "data": {"price": price, "previous_price": prev}}  # fmt: skip


def _fire(uid, wid, kind, price, prev, baseline, sent_calls=None):
    """A watch alert through enrich -> insert -> after_insert, as _notify does."""
    watch = {"id": wid, "user_id": uid, "baseline_price": baseline}
    note = alert_pipeline.enrich(watch, "flight", _note(kind, price, prev))
    row = notifications_db.add_notification(
        uid, note["kind"], note["title"], note["body"], note["data"], now=NOW
    )
    assert alert_pipeline.after_insert(watch, "flight", row, NOW) is True
    return notifications_db.list_notifications(uid, limit=50)["items"][0]


def _xp_rules(uid):
    with get_connection() as c:
        return sorted(r["rule"] for r in c.execute(
            "SELECT rule FROM xp_ledger WHERE user_id=?", (uid,)))  # fmt: skip


def test_drop_awards_and_stores_game_and_v2(uid, sent):
    stored = _fire(uid, 1, "fare_drop", 412, 455, 455)
    assert stored["data"]["drop"]["amount"] == 43.0
    assert stored["data"]["game"]["awards"] == [{"rule": "deal_drop", "points": 15}]
    assert [b["id"] for b in stored["data"]["game"]["badges"]] == ["deal_hunter"]
    assert stored["data"]["_v2"] is True
    assert len(sent) == 1


def test_target_hit_awards_bullseye_once(uid, sent):
    first = _fire(uid, 1, "fare_target", 300, 455, 455)
    rules = [a["rule"] for a in first["data"]["game"]["awards"]]
    assert "deal_target" in rules and "deal_drop" in rules
    assert "bullseye" in [b["id"] for b in first["data"]["game"]["badges"]]
    again = alert_hooks.on_drop(uid, "flight", 1, first["id"], first["data"]["drop"])
    assert again["awards"] == []  # same notification: idempotent
    second = _fire(uid, 1, "fare_target", 250, 300, 455)
    assert "bullseye" not in [b["id"] for b in second["data"]["game"]["badges"]]


def test_crossing_200_awards_saver_50_and_200(uid):
    d = alert_hooks.on_savings(uid, 40.0)
    assert d["awards"] == []
    d = alert_hooks.on_savings(uid, 230.0)
    assert [a["rule"] for a in d["awards"]] == ["deal_saved_50", "deal_saved_200"]
    assert {b["id"] for b in d["badges"]} == {"saver_50", "saver_200"}
    assert alert_hooks.on_savings(uid, 260.0)["awards"] == []  # once each
    assert d["xp"] == 150


def test_savings_milestone_through_pipeline(uid, sent):
    stored = _fire(uid, 1, "fare_drop", 200, 455, 455)  # caught 255
    rules = [a["rule"] for a in stored["data"]["game"]["awards"]]
    assert "deal_saved_50" in rules and "deal_saved_200" in rules
    assert alert_moments.summary(uid)["total_usd"] == 255.0


def test_hide_game_still_records_savings(uid, sent):
    user_settings_db.patch_settings(uid, {"hide_game": True})
    _fire(uid, 1, "fare_drop", 400, 455, 455)
    assert alert_moments.summary(uid)["total_usd"] == 55.0
    assert "deal_drop" in _xp_rules(uid)


def test_game_disabled_still_records_savings(uid, sent, monkeypatch):
    monkeypatch.setattr(settings, "game_enabled", False)
    stored = _fire(uid, 1, "fare_drop", 400, 455, 455)
    assert stored["data"]["game"] is None
    assert alert_moments.summary(uid)["total_usd"] == 55.0
    assert _xp_rules(uid) == []


def test_non_drop_note_gets_no_drop_or_game(uid, sent):
    watch = {"id": 1, "user_id": uid}
    note = {"kind": "watch_expired", "title": "t", "body": "", "data": {}}
    out = alert_pipeline.enrich(watch, "flight", note)
    assert "drop" not in out["data"] and out["data"]["category"] == "price_drops"
    row = notifications_db.add_notification(uid, "watch_expired", "t", "", {}, now=NOW)
    assert alert_pipeline.after_insert(watch, "flight", row, NOW) is True
    data = notifications_db.list_notifications(uid)["items"][0]["data"]
    assert "game" not in data and "drop" not in data and data["_v2"] is True
    assert alerts_db.savings_rows(uid) == []


def test_dispatch_failure_leaves_no_v2_flag(uid, monkeypatch):
    def boom(*a):
        raise RuntimeError("x")

    monkeypatch.setattr(alert_delivery, "dispatch", boom)
    watch = {"id": 1, "user_id": uid, "baseline_price": 455.0}
    note = alert_pipeline.enrich(watch, "flight", _note("fare_drop", 412, 455))
    row = notifications_db.add_notification(
        uid, note["kind"], "t", "", note["data"], now=NOW
    )
    with pytest.raises(RuntimeError):
        alert_pipeline.after_insert(watch, "flight", row, NOW)
    data = notifications_db.list_notifications(uid)["items"][0]["data"]
    assert "_v2" not in data and data["game"]["awards"]


def test_deal_hunter_tiers():
    cat = {b["id"]: b for b in engine.catalog()["badges"]}
    assert [
        cat[k]["target"]
        for k in ("deal_hunter", "deal_hunter_silver", "deal_hunter_gold")
    ] == [1, 5, 20]
    assert cat["bullseye"]["icon"] == "target"
    assert cat["saver_1000"]["icon"] == "piggy-bank"
    rules = {r["id"]: r for r in engine.catalog()["rules"]}
    assert (rules["deal_drop"]["points"], rules["deal_drop"]["daily_cap"]) == (15, 5)
    assert (rules["deal_target"]["points"], rules["deal_target"]["daily_cap"]) == (
        30,
        3,
    )
    assert rules["deal_saved_200"]["once"] and rules["deal_saved_1000"]["points"] == 250


def test_summary_route(client, uid):
    name = users_db.get_user_by_id(uid)["username"]
    h = {"Authorization": f"Bearer {create_access_token({'sub': name})}"}
    r = client.get("/api/alerts/summary", headers=h)
    assert r.status_code == 200 and r.json()["total_usd"] == 0
    assert r.json()["milestones"] == [50, 200, 1000]
    assert client.get("/api/alerts/summary").status_code in (401, 403)
