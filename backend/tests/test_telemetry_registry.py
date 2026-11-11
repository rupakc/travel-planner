"""Closed telemetry event registry and validation."""

import time
import uuid
from pathlib import Path

from app.telemetry.registry import EVENTS, PROP_TYPES, clean_client, clean_event


def test_pii_id_props_are_dropped():
    out = clean_event(
        {"event": "ui_tap", "props": {"tid": "jane@x.com", "route": "/results"}}
    )
    assert out["props"] == {"route": "/results"}
    out = clean_event(
        {"event": "ui_tap", "props": {"tid": "hello world", "route": "/results"}}
    )
    assert out["props"] == {"route": "/results"}


def test_unknown_event_is_none():
    assert clean_event({"event": "nope"}) is None
    assert clean_event({}) is None


def test_unknown_props_and_bad_enums_dropped():
    out = clean_event(
        {
            "event": "search_submit",
            "props": {"mode": "bogus", "travelers": 2, "extra": 1},
        }
    )
    assert out["props"] == {"travelers": 2}


def test_type_checks():
    out = clean_event(
        {"event": "perf", "props": {"metric": "lcp", "value": 1.5, "route": "x" * 65}}
    )
    assert out["props"] == {"metric": "lcp", "value": 1.5}
    out = clean_event(
        {"event": "ui_toggle", "props": {"on": "yes", "tid": "a", "route": "/r"}}
    )
    assert out["props"] == {"tid": "a", "route": "/r"}
    # bool is not an int
    assert clean_event({"event": "screen_time", "props": {"ms": True}})["props"] == {}
    assert clean_event({"event": "screen_time", "props": {"ms": 12}})["props"] == {
        "ms": 12
    }


def test_huge_integers_are_dropped_not_fatal():
    huge = 10**400
    assert clean_event({"event": "screen_time", "props": {"ms": huge}})["props"] == {}
    assert clean_event({"event": "perf", "props": {"value": huge}})["props"] == {}
    inf = float("inf")
    assert clean_event({"event": "perf", "props": {"value": inf}})["props"] == {}
    for bad_ts in (huge, -huge):
        out = clean_event({"event": "app_open", "ts": bad_ts})
        assert abs(out["ts"] - int(time.time() * 1000)) < 5000


def test_ts_window():
    now = int(time.time() * 1000)
    assert clean_event({"event": "app_open", "ts": now - 1000})["ts"] == now - 1000
    far = clean_event({"event": "app_open", "ts": now - 30 * 86_400_000})["ts"]
    assert abs(far - now) < 5000
    assert abs(clean_event({"event": "app_open"})["ts"] - now) < 5000


def test_clean_client():
    ok = {
        "anon_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "platform": "web",
        "app_version": "1.2.3",
        "locale": "en-US",
    }
    assert clean_client(ok) == ok
    assert clean_client({**ok, "anon_id": "nope"}) is None
    assert clean_client({**ok, "platform": "palm"}) is None
    assert clean_client({**ok, "locale": "x" * 17}) is None
    assert clean_client({**ok, "app_version": "has space"}) is None


def test_registry_shape():
    for props in EVENTS.values():
        for t in props.values():
            assert t in PROP_TYPES or t.startswith("enum:")


def test_every_event_documented():
    doc = Path(__file__).resolve().parents[2] / "docs" / "Telemetry.md"
    text = doc.read_text()
    assert all(name in text for name in EVENTS)


def test_ui_change_event_keeps_only_tid_and_route():
    ev = clean_event(
        {
            "event": "ui_change",
            "props": {"tid": "search.dest", "route": "/", "value": "Paris"},
        }
    )
    assert ev is not None
    assert ev["props"] == {"tid": "search.dest", "route": "/"}


PHASE1_EVENTS = (
    "auth_start",
    "auth_result",
    "signup_step",
    "email_verify",
    "password_reset",
    "account_action",
    "quota_block",
    "game_award",
    "badge_earned",
    "level_up",
    "game_view",
)


def test_phase1_events_registered():
    assert all(name in EVENTS for name in PHASE1_EVENTS)


def test_auth_result_drops_email_shaped_code():
    out = clean_event(
        {
            "event": "auth_result",
            "props": {
                "method": "google",
                "mode": "signin",
                "result": "ok",
                "code": "jane@x.com",
            },
        }
    )
    assert out["props"] == {"method": "google", "mode": "signin", "result": "ok"}


def test_phase1_enums_and_ints():
    out = clean_event(
        {"event": "game_award", "props": {"rule": "first_search", "points": 10}}
    )
    assert out["props"] == {"rule": "first_search", "points": 10}
    out = clean_event({"event": "quota_block", "props": {"bucket": "x", "reason": "unverified"}})
    assert out["props"] == {"reason": "unverified"}
    out = clean_event({"event": "level_up", "props": {"level": "3"}})
    assert out["props"] == {}


def test_phase1_enum_accept_and_reject():
    cases = [
        ("signup_step", {"step": "check_email"}, {"step": "check_email"}),
        ("signup_step", {"step": "bogus"}, {}),
        ("email_verify", {"result": "email_changed"}, {"result": "email_changed"}),
        ("email_verify", {"result": "ok2"}, {}),
        ("account_action", {"action": "signout_all"}, {"action": "signout_all"}),
        ("account_action", {"action": "hack"}, {}),
    ]
    for name, props, want in cases:
        assert clean_event({"event": name, "props": props})["props"] == want
