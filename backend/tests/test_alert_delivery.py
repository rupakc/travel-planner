"""Task 6: quiet hours, caps, grouping, the outbox flush."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db import alerts_db, notifications_db, user_settings_db
from app.db.database import get_connection
from app.db.users_db import create_user
from app.services import alert_delivery as ad
from app.services import alert_email, push

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
CASES = json.loads(
    (Path(__file__).parent / "fixtures/alerts/quiet_hours_cases.json").read_text()
)


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    alerts_db.create_alert_tables()
    with get_connection() as conn:
        conn.execute("DELETE FROM alert_outbox")
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")


@pytest.fixture
def user():
    return create_user(f"dl-{uuid.uuid4().hex[:8]}", "pw-123456789")


@pytest.fixture
def sent(monkeypatch):
    pushes, emails = [], []

    async def fake_push(username, title, body, data):
        pushes.append((username, title, body, data))
        return 1

    async def fake_email(kind, watch, row, now):
        emails.append(row["id"])
        return True

    monkeypatch.setattr(ad, "_load_watch", lambda kind, note: {"id": 1})
    monkeypatch.setattr(push, "send_to_user", fake_push)
    monkeypatch.setattr(alert_email, "deliver_one", fake_email)
    return pushes, emails


def _note(user, kind="hotel_drop", target=False, wid=1, title="Drop"):
    return notifications_db.add_notification(
        user["id"],
        kind,
        title,
        "body",
        {"watch_id": wid, "watch_kind": "hotel", "drop": {"target_hit": target}},
        now=NOW,
    )


def _watch(user, email=False):
    return {"id": 1, "user_id": user["id"], "email_enabled": email, "kind": "hotel"}


def _run(coro):
    return asyncio.run(coro)


def _outbox(user):
    with get_connection() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM alert_outbox WHERE user_id = ? ORDER BY id",
                (user["id"],),
            )
        ]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_quiet_hours_golden(case):
    inp, exp = case["input"], case["expected"]
    now = datetime.fromisoformat(inp["now_utc"].replace("Z", "+00:00"))
    prefs = {**alerts_db.DEFAULT_PREFS, "quiet_hours": inp["quiet_hours"]}
    d = ad.plan({"kind": "hotel_drop"}, "hotel", prefs, inp["timezone"], {}, None, now)
    due = d.due_at
    assert ("held" if d.reason == "quiet" else "now") == exp["deliver"]
    assert due.strftime("%Y-%m-%dT%H:%M:%SZ") == exp["due_utc"]


def test_cap_per_category_local_day(user, sent):
    alerts_db.put_prefs(user["id"], {**alerts_db.DEFAULT_PREFS, "group_window_min": 0})
    w = _watch(user)
    for _ in range(3):
        ad.dispatch(w, "hotel", _note(user), NOW)
        (ad.flush(NOW))
    fourth = _note(user)
    ad.dispatch(w, "hotel", fourth, NOW)
    rows = [r for r in _outbox(user) if r["notification_id"] == fourth["id"]]
    assert rows[0]["dropped_reason"] == "cap"
    flight = _note(user, kind="fare_drop")
    ad.dispatch({**w, "kind": "flight"}, "flight", flight, NOW)
    rows = [r for r in _outbox(user) if r["notification_id"] == flight["id"]]
    assert rows[0]["dropped_reason"] is None


def test_targets_only_holds_non_target(user):
    alerts_db.put_prefs(
        user["id"], {**alerts_db.DEFAULT_PREFS, "instant": "targets_only"}
    )
    n = _note(user)
    ad.dispatch(_watch(user), "hotel", n, NOW)
    assert _outbox(user)[0]["dropped_reason"] == "targets_only"
    t = _note(user, kind="hotel_target", target=True)
    ad.dispatch(_watch(user), "hotel", t, NOW)
    assert _outbox(user)[-1]["dropped_reason"] is None


def test_group_window_coalesces_three_into_one_push(user, sent):
    pushes, _ = sent
    alerts_db.put_prefs(
        user["id"],
        {
            **alerts_db.DEFAULT_PREFS,
            "daily_cap": {"hotel": 10, "flight": 3, "activity": 3, "trip": 3},
        },
    )
    w = _watch(user)
    ad.dispatch(w, "hotel", _note(user, title="first"), NOW)
    assert (ad.flush(NOW)) == 1
    for i in range(3):
        ad.dispatch(w, "hotel", _note(user, title=f"n{i}"), NOW + timedelta(minutes=1))
    assert (ad.flush(NOW + timedelta(minutes=2))) == 0
    assert (ad.flush(NOW + timedelta(minutes=16))) == 3
    assert len(pushes) == 2
    _, title, _, data = pushes[1]
    assert title == "3 prices dropped" and data["group_count"] == "3"
    assert data["kind"] == "hotel_drop"


def test_flush_claims_each_item_once(user, sent):
    pushes, _ = sent
    ad.dispatch(_watch(user), "hotel", _note(user), NOW)

    async def both():
        return await asyncio.gather(
            asyncio.to_thread(ad.flush, NOW), asyncio.to_thread(ad.flush, NOW)
        )

    assert sorted(_run(both())) == [0, 1]
    assert len(pushes) == 1


def test_stale_outbox_item_dropped_not_sent(user, sent):
    pushes, _ = sent
    n = _note(user)
    ad.dispatch(_watch(user), "hotel", n, NOW)
    assert ad.flush(NOW + timedelta(hours=13)) == 0
    assert pushes == []
    rows = [r for r in _outbox(user) if r["notification_id"] == n["id"]]
    assert rows[0]["dropped_reason"] == "stale" and rows[0]["sent_at"] is None


def test_in_app_row_always_written(user):
    alerts_db.put_prefs(
        user["id"], {**alerts_db.DEFAULT_PREFS, "instant": "targets_only"}
    )
    n = _note(user)
    ad.dispatch(_watch(user), "hotel", n, NOW)
    page = notifications_db.list_notifications(
        user["id"], unread_only=False, limit=10, offset=0
    )
    assert [x["id"] for x in page["items"]] == [n["id"]]


def test_email_respects_quiet_hours_never_grouped(user, sent):
    pushes, emails = sent
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Kolkata"})
    w = _watch(user, email=True)
    # prior push 1 minute ago: push is group-held, email is not
    ad.dispatch(w, "hotel", _note(user), NOW)
    (ad.flush(NOW))
    n2 = _note(user)
    ad.dispatch(w, "hotel", n2, NOW + timedelta(minutes=1))
    (ad.flush(NOW + timedelta(minutes=1)))
    assert n2["id"] in emails and len(pushes) == 1
    # quiet: 23:30 IST = 18:00Z, both held to 01:30Z
    late = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)
    n3 = _note(user)
    ad.dispatch(w, "hotel", n3, late)
    assert {r["due_at"] for r in _outbox(user) if r["notification_id"] == n3["id"]} == {
        "2026-11-13T01:30:00Z"
    }


def test_expired_note_legacy_path(user, sent):
    pushes, _ = sent
    alerts_db.put_prefs(
        user["id"], {**alerts_db.DEFAULT_PREFS, "instant": "targets_only"}
    )
    user_settings_db.patch_settings(user["id"], {"timezone": "Asia/Kolkata"})
    n = _note(user, kind="watch_expired")
    late = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)
    ad.dispatch(_watch(user), "hotel", n, late)
    assert (ad.flush(late)) == 1
    assert len(pushes) == 1


def test_validate_prefs():
    assert ad.validate_prefs({"timezone": "X", "digest_push": True}) == {
        "digest_push": True
    }
    for bad in (
        {"digest_day": 8},
        {"instant": "x"},
        {"daily_cap": {"hotel": 0}},
        {"daily_cap": {"boat": 1}},
        {"group_window_min": 121},
        {"quiet_hours": {"start": "25:00"}},
        {"digest_weekly": "yes"},
        {"nope": 1},
    ):
        with pytest.raises(ad.ApiError) as e:
            ad.validate_prefs(bad)
        assert e.value.status == 422 and e.value.code == "alert_prefs_invalid"


def test_expired_never_grouped_nor_capped(user, sent):
    pushes, _ = sent
    w = _watch(user)
    alerts_db.put_prefs(user["id"], {**alerts_db.DEFAULT_PREFS, "group_window_min": 0})
    for _ in range(3):
        ad.dispatch(w, "hotel", _note(user, kind="watch_expired"), NOW)
    ad.flush(NOW)
    assert len(pushes) == 3 and all(p[3]["kind"] == "watch_expired" for p in pushes)
    assert "group_count" not in pushes[0][3]
    # expired rows do not use up the hotel cap
    n = _note(user)
    ad.dispatch(w, "hotel", n, NOW)
    assert [r for r in _outbox(user) if r["notification_id"] == n["id"]][0][
        "dropped_reason"
    ] is None
    ad.flush(NOW)  # leave no due item behind for other tests


def test_enrich_row_data_carries_price_drops_category():
    from app.services import alert_pipeline

    note = {"kind": "hotel_expired", "title": "t", "body": "b", "data": {"watch_id": 1}}
    out = alert_pipeline.enrich({"id": 1}, "hotel", note)
    assert out["data"]["category"] == "price_drops" and out["data"]["plan_id"] is None


def test_push_payload_carries_category_single_and_grouped(user):
    rows = [_note(user, wid=i, title=f"D{i}") for i in (1, 2)]
    for batch in (rows[:1], rows):
        data = ad._push_payload(batch)[2]
        assert data["category"] == "price_drops" and data["plan_id"] == ""


# ── claim + ack ──────────────────────────────────────────────────────────────


def _queue(user):
    ad.dispatch(_watch(user), "hotel", _note(user), NOW)
    return _outbox(user)


def test_send_fails_once_then_delivered_once(user, monkeypatch):
    calls = []

    async def flaky(username, title, body, data):
        calls.append(data["dedupe_key"])
        return 0 if len(calls) == 1 else 1

    monkeypatch.setattr(push, "send_to_user", flaky)
    monkeypatch.setattr(push, "configured", lambda: True)
    from app.db import devices_db

    monkeypatch.setattr(devices_db, "devices_for", lambda u: [("t", "android")])
    row = _queue(user)[0]
    assert ad.flush(NOW) == 0  # failed: lease released, retry scheduled
    r = _outbox(user)[0]
    assert r["sent_at"] is None and r["claimed_at"] is None and r["attempts"] == 1
    assert ad.flush(NOW + timedelta(seconds=30)) == 0  # backoff holds it
    assert ad.flush(NOW + timedelta(minutes=2)) == 1
    assert ad.flush(NOW + timedelta(minutes=10)) == 0  # acked: no duplicate
    assert len(calls) == 2 and calls[0] == calls[1]  # same key on the retry
    assert _outbox(user)[0]["sent_at"] and row["id"]


def test_crash_between_claim_and_ack_redelivers_after_lease(user, sent):
    pushes, _ = sent
    _queue(user)
    claimed = alerts_db.claim_due(ad._iso(NOW), 10)  # crash: never acked
    assert len(claimed) == 1
    assert alerts_db.claim_due(ad._iso(NOW), 10) == []  # lease held
    assert ad.flush(NOW + timedelta(seconds=10)) == 0
    later = NOW + timedelta(seconds=ad.settings.alert_outbox_lease_s + 5)
    assert ad.flush(later) == 1
    assert len(pushes) == 1 and _outbox(user)[0]["attempts"] == 2


def test_attempts_bounded_then_dropped(user, monkeypatch):
    async def bad(*a):
        return 0

    monkeypatch.setattr(push, "send_to_user", bad)
    monkeypatch.setattr(push, "configured", lambda: True)
    from app.db import devices_db

    monkeypatch.setattr(devices_db, "devices_for", lambda u: [("t", "android")])
    monkeypatch.setattr(ad.settings, "alert_outbox_max_attempts", 3)
    _queue(user)
    t = NOW
    for _ in range(6):
        t += timedelta(hours=1)
        ad.flush(t)
    r = _outbox(user)[0]
    assert r["dropped_reason"] == "max_attempts" and r["attempts"] == 3
    assert r["sent_at"] is None


def test_claimed_counts_toward_cap_only_while_leased(user):
    _queue(user)
    alerts_db.claim_due(ad._iso(NOW), 10)
    start = ad._iso(NOW - timedelta(hours=12))
    assert alerts_db.sent_today(user["id"], "hotel", start, "push") == 1


@pytest.mark.parametrize(
    "devices,fcm,apns_on,expected",
    [
        ([("t", "ios")], True, False, True),  # nothing deliverable: ack, no retry
        ([("t", "ios")], False, True, False),  # APNs failure retries
        ([("t", "android")], True, False, False),  # FCM failure retries
        ([("t", "android")], False, True, True),  # FCM off, no Android route
        ([], True, True, True),
    ],
)
def test_send_push_per_route_deliverable(
    user, monkeypatch, devices, fcm, apns_on, expected
):
    from app.db import devices_db
    from app.services import apns

    async def none(*a):
        return 0

    monkeypatch.setattr(push, "send_to_user", none)
    monkeypatch.setattr(push, "configured", lambda: fcm)
    monkeypatch.setattr(apns, "configured", lambda: apns_on)
    monkeypatch.setattr(ad.settings, "notifications_v2_enabled", True)
    monkeypatch.setattr(devices_db, "devices_for", lambda u: devices)
    ok = asyncio.run(ad._send_push(user["id"], [_note(user)]))
    assert ok is expected


def test_dedupe_key_is_notification_id(user, monkeypatch):
    seen = {}

    async def grab(username, title, body, data):
        seen.update(data)
        return 1

    monkeypatch.setattr(push, "send_to_user", grab)
    n = _note(user)
    assert asyncio.run(ad._send_push(user["id"], [n]))
    assert seen["dedupe_key"] == seen["notification_id"] == str(n["id"])
