import uuid
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.db import alerts_db, notify_db, user_settings_db
from app.db.database import get_connection
from app.db.plans_db import save_plan
from app.db.users_db import create_user
from app.services import notify_text
from app.services import weather_push as wp
from app.services.weather_client import Forecast, OpenMeteoClient, parse

LANGS = ("en", "es", "de", "fr", "hi", "zh", "bn")
NOW = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)  # 08:00 in a UTC destination
DAY = "2026-11-13"


class FakeClient:
    def __init__(self, fc):
        self.fc = fc
        self.calls = 0

    def forecast(self, lat, lng):
        self.calls += 1
        return self.fc


def rainy(hour=10):
    return Forecast(precip_prob={f"{DAY}T{hour:02d}:00": 80.0})


@pytest.fixture(autouse=True)
def _setup(client, monkeypatch):
    alerts_db.create_alert_tables()
    notify_db.create_notify_tables()
    monkeypatch.setattr("app.db.users_db._hash", lambda pw: "unused")
    wp._calls.clear()


@pytest.fixture
def user():
    u = create_user(f"wp-{uuid.uuid4().hex[:8]}", "pw-123456789")
    user_settings_db.patch_settings(u["id"], {"timezone": "UTC"})
    return u


def make_plan(u, start="2026-11-12", end="2026-11-16", slots=None, phase=None):
    p = save_plan(
        u["username"],
        "Trip",
        {"destination": "Tokyo", "departure_date": start, "return_date": end},
        {
            "itinerary_slots": slots
            if slots is not None
            else [
                {"day_number": 2, "start_time": "10:00", "activity": "Walk in the park"}
            ]
        },
    )
    return p


def rows(u):
    with get_connection() as c:
        return [
            dict(r)
            for r in c.execute("SELECT * FROM notify_log WHERE user_id = ?", (u["id"],))
        ]


def test_evaluate_cases():
    k = f"{DAY}T10:00"
    assert wp.evaluate(Forecast(precip_prob={k: 60.0}), DAY, 10) == "rain"
    assert wp.evaluate(Forecast(precip_prob={k: 59.0}), DAY, 10) is None
    assert wp.evaluate(Forecast(precip_mm={k: 1.2}), DAY, 10) == "rain"
    assert wp.evaluate(Forecast(apparent_c={k: 35.0}), DAY, 10) == "heat"
    assert wp.evaluate(Forecast(apparent_c={k: 0.0}), DAY, 10) == "cold"
    assert wp.evaluate(Forecast(apparent_c={k: 20.0}), DAY, 10) is None
    assert wp.evaluate(Forecast(apparent_c={k: 40.0}), DAY, 11) is None


def test_outdoor_heuristic_and_hour():
    assert wp.is_outdoor({"activity": "Hike to the waterfall"})
    assert not wp.is_outdoor({"activity": "Tokyo National Museum"})
    assert not wp.is_outdoor({"activity": "Museum garden", "outdoor": False})
    assert wp.is_outdoor({"activity": "Ramen", "outdoor": True})
    assert wp.slot_hour({"start_time": "09:30"}) == 9
    assert wp.slot_hour({"time_of_day": "afternoon"}) == 14
    assert wp.slot_hour({"time_of_day": "night"}) is None


def test_sends_once_and_dedupes(user):
    p = make_plan(user)
    fake = FakeClient(rainy())
    wp.run_due(NOW, fake)
    wp.run_due(NOW, fake)  # same slot, condition and day
    r = rows(user)
    assert len(r) == 1 and r[0]["kind"] == "weather_rain"
    assert r[0]["category"] == "weather" and r[0]["plan_id"] == p["id"]


def test_one_call_per_city(user):
    u2 = create_user(f"wp-{uuid.uuid4().hex[:8]}", "pw-123456789")
    make_plan(user)
    make_plan(u2)
    fake = FakeClient(rainy())
    wp.run_due(NOW, fake)
    assert fake.calls == 1


def test_call_budget(user, monkeypatch):
    monkeypatch.setattr(settings, "weather_push_max_calls_per_hour", 0)
    make_plan(user)
    fake = FakeClient(rainy())
    wp.run_due(NOW, fake)
    assert fake.calls == 0 and rows(user) == []


def test_not_on_the_road_or_indoor_or_far(user):
    make_plan(user, start="2026-11-20", end="2026-11-25")  # not started
    make_plan(
        user, slots=[{"day_number": 2, "start_time": "10:00", "activity": "Museum"}]
    )
    make_plan(
        user, slots=[{"day_number": 2, "start_time": "16:00", "activity": "Park"}]
    )
    fake = FakeClient(rainy(16))
    wp.run_due(NOW, fake)  # 16:00 is beyond the 3 h window
    assert rows(user) == []


def test_toggle_off(user):
    from app.services import notify_settings

    make_plan(user)
    notify_db.put_data(user["id"], {"categories": {"weather": False}})
    assert notify_settings.stored(user["id"])["categories"]["weather"] is False
    wp.run_due(NOW, FakeClient(rainy()))
    assert rows(user) == []


def test_quiet_hours_holds_push(user):
    make_plan(user)
    alerts_db.put_prefs(
        user["id"],
        {"quiet_hours": {"enabled": True, "start": "22:00", "end": "09:00"}},
    )
    wp.run_due(NOW, FakeClient(rainy()))
    r = rows(user)[0]
    assert r["status"] == "pending" and r["due_at"] == "2026-11-13T09:00:00Z"


def test_templates_in_all_languages():
    for lang in LANGS:
        for k in ("weather_rain", "weather_heat", "weather_cold"):
            out = notify_text.render(k, lang, slot="X", time="10:00")
            assert "10:00" in out and "{" not in out


def test_open_meteo_parse_and_cache():
    payload = {
        "utc_offset_seconds": 3600,
        "hourly": {
            "time": [f"{DAY}T10:00"],
            "precipitation_probability": [70],
            "precipitation": [0.2],
            "apparent_temperature": [12.5],
        },
    }
    fc = parse(payload)
    assert fc.utc_offset_s == 3600 and fc.precip_prob[f"{DAY}T10:00"] == 70.0

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class Http:
        n = 0

        def get(self, *a, **k):
            Http.n += 1
            return Resp()

    c = OpenMeteoClient(http=Http())
    c.forecast(35.68, 139.69)
    c.forecast(35.71, 139.72)  # same rounded cell
    assert Http.n == 1
