"""Trips API: expense log, exact decimals, honest USD estimates."""

import uuid

import pytest

from app.core.config import settings
from app.db import plans_db, trip_expenses_db, trip_snapshot_db
from app.services import trip_money


@pytest.fixture(scope="module")
def hdr(client, admin_headers):
    out = {}
    for name in ("moneya", "moneyb"):
        client.post(
            "/api/admin/users",
            json={"username": name, "password": "temp1234-kv", "is_admin": False},
            headers=admin_headers,
        )
        r = client.post(
            "/api/auth/login", json={"username": name, "password": "temp1234-kv"}
        )
        out[name] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out


@pytest.fixture
def trip(hdr):
    return plans_db.save_plan("moneya", "T", {"destination": "Lisbon"}, {})["id"]


def _post(client, hdr, trip, **kw):
    body = {
        "client_id": str(uuid.uuid4()),
        "amount": "12.50",
        "currency": "EUR",
        "category": "food",
        "spent_on": "2027-04-01",
    }
    body.update(kw)
    return client.post(f"/api/trips/{trip}/expenses", json=body, headers=hdr["moneya"])


def _get(client, hdr, trip):
    return client.get(f"/api/trips/{trip}/expenses", headers=hdr["moneya"]).json()


def test_same_client_id_twice_one_row(client, hdr, trip):
    cid = str(uuid.uuid4())
    a = _post(client, hdr, trip, client_id=cid)
    b = _post(client, hdr, trip, client_id=cid)
    assert a.status_code == 201
    assert b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    assert len(_get(client, hdr, trip)["expenses"]) == 1


def test_jpy_has_no_decimals(client, hdr, trip):
    assert _post(client, hdr, trip, currency="JPY", amount="1200").status_code == 201
    r = _post(client, hdr, trip, currency="JPY", amount="12.5")
    assert r.status_code == 422
    assert r.json()["error_code"] == "amount_invalid"


def test_kwd_three_decimals(client, hdr, trip):
    r = _post(client, hdr, trip, currency="KWD", amount="1.234")
    assert r.status_code == 201
    assert r.json()["amount"] == "1.234"
    assert _post(client, hdr, trip, currency="KWD", amount="1.2345").status_code == 422
    assert trip_money.parse_amount("1.234", "KWD") == 1234


@pytest.mark.parametrize("amount", ["0", "0.00", "-5", "abc", "", "1e3", "1000000.01"])
def test_amount_zero_or_negative_invalid(client, hdr, trip, amount):
    r = _post(client, hdr, trip, amount=amount)
    assert r.status_code == 422
    assert r.json()["error_code"] == "amount_invalid"


@pytest.mark.parametrize("cur", ["EU", "EURO", "12$", ""])
def test_currency_must_be_iso(client, hdr, trip, cur):
    r = _post(client, hdr, trip, currency=cur)
    assert r.status_code == 422
    assert r.json()["error_code"] == "currency_invalid"


def test_category_and_note_validation(client, hdr, trip):
    assert _post(client, hdr, trip, category="x").json()["error_code"] == (
        "category_invalid"
    )
    r = _post(client, hdr, trip, note="n" * 141)
    assert r.json()["error_code"] == "note_too_long"


def test_totals_exact_decimal(client, hdr, trip):
    _post(client, hdr, trip, amount="0.10")
    _post(client, hdr, trip, amount="0.20")
    assert _get(client, hdr, trip)["totals"]["by_currency"] == {"EUR": "0.30"}


def _snapshot(trip):
    trip_snapshot_db.put_snapshot(
        trip,
        {
            "forex": {
                "exchange_rates": [
                    {"from_currency": "USD", "to_currency": "EUR", "rate": 0.92}
                ]
            }
        },
    )


def test_usd_estimate_from_snapshot_rate(client, hdr, trip):
    _snapshot(trip)
    _post(client, hdr, trip, amount="92.00")
    _post(client, hdr, trip, amount="5.00", currency="USD", category="fees")
    body = _get(client, hdr, trip)
    assert body["totals"]["usd_estimate"] == "105.00"
    assert body["totals"]["by_category_usd"] == {"fees": "5.00", "food": "100.00"}
    assert body["rate"]["local"] == "EUR"
    assert body["rate"]["usd_to_local"] == 0.92
    assert body["rate"]["as_of"]
    assert trip_money.spend_summary(plans_db.get_plan(trip))["spent_usd"] == "105.00"


def test_unknown_currency_listed_unconverted(client, hdr, trip):
    _snapshot(trip)
    _post(client, hdr, trip, amount="9.20")
    _post(client, hdr, trip, amount="40", currency="GBP")
    t = _get(client, hdr, trip)["totals"]
    assert t["unconverted"] == ["GBP"]
    assert t["usd_estimate"] == "10.00"
    assert t["by_currency"] == {"EUR": "9.20", "GBP": "40.00"}


def test_no_rate_means_no_estimate(client, hdr, trip):
    _post(client, hdr, trip)
    body = _get(client, hdr, trip)
    assert body["rate"] is None
    assert body["totals"]["usd_estimate"] is None
    assert body["totals"]["unconverted"] == ["EUR"]


def test_usd_rate_rules():
    ok = {
        "forex": {
            "exchange_rates": [
                {"from_currency": "USD", "to_currency": "JPY", "rate": 150}
            ]
        },
        "as_of": "x",
    }
    assert trip_money.usd_rate(ok) == {
        "local": "JPY",
        "usd_to_local": 150,
        "as_of": "x",
    }
    for bad in (
        None,
        {},
        {
            "forex": {
                "exchange_rates": [
                    {"from_currency": "USD", "to_currency": "JPY", "rate": None},
                    {"from_currency": "USD", "to_currency": "JPY", "rate": 0},
                    {"from_currency": "EUR", "to_currency": "JPY", "rate": 160},
                ]
            }
        },
    ):
        assert trip_money.usd_rate(bad) is None


def test_expense_limit(client, hdr, trip, monkeypatch):
    monkeypatch.setattr(settings, "trip_max_expenses", 2)
    assert _post(client, hdr, trip).status_code == 201
    cid = str(uuid.uuid4())
    assert _post(client, hdr, trip, client_id=cid).status_code == 201
    r = _post(client, hdr, trip)
    assert r.status_code == 409
    assert r.json()["error_code"] == "expense_limit"
    # a retry of an existing client_id still answers 200 at the limit
    assert _post(client, hdr, trip, client_id=cid).status_code == 200


def test_patch_and_delete(client, hdr, trip):
    eid = _post(client, hdr, trip).json()["id"]
    url = f"/api/trips/{trip}/expenses/{eid}"
    r = client.patch(
        url, json={"amount": "20.00", "note": "dinner"}, headers=hdr["moneya"]
    )
    assert r.status_code == 200
    assert (r.json()["amount"], r.json()["note"]) == ("20.00", "dinner")
    r = client.patch(url, json={"currency": "JPY"}, headers=hdr["moneya"])
    assert r.status_code == 422  # 20.00 has decimals JPY forbids
    r = client.patch(
        url, json={"currency": "JPY", "amount": "2000"}, headers=hdr["moneya"]
    )
    assert r.json()["amount"] == "2000"
    assert client.delete(url, headers=hdr["moneya"]).status_code == 204
    r = client.delete(url, headers=hdr["moneya"])
    assert (r.status_code, r.json()["error_code"]) == (404, "expense_not_found")
    r = client.patch(url, json={"note": "x"}, headers=hdr["moneya"])
    assert r.status_code == 404


def test_other_users_expense_404(client, hdr, trip):
    eid = _post(client, hdr, trip).json()["id"]
    base = f"/api/trips/{trip}/expenses"
    other = hdr["moneyb"]
    assert client.get(base, headers=other).status_code == 404
    body = {
        "client_id": str(uuid.uuid4()),
        "amount": "1",
        "currency": "EUR",
        "category": "food",
        "spent_on": "2027-04-01",
    }
    assert client.post(base, json=body, headers=other).status_code == 404
    assert (
        client.patch(f"{base}/{eid}", json={"note": "x"}, headers=other).status_code
        == 404
    )
    assert client.delete(f"{base}/{eid}", headers=other).status_code == 404
    assert len(_get(client, hdr, trip)["expenses"]) == 1


def test_patch_race_with_delete_is_404_not_500(client, hdr, trip, monkeypatch):
    eid = _post(client, hdr, trip).json()["id"]
    monkeypatch.setattr(trip_expenses_db, "update", lambda *a, **k: None)
    r = client.patch(
        f"/api/trips/{trip}/expenses/{eid}", json={"note": "x"}, headers=hdr["moneya"]
    )
    assert (r.status_code, r.json()["error_code"]) == (404, "expense_not_found")
