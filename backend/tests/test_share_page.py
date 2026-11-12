"""Public OG page and card.png routes."""

import io
import uuid

import pytest
from PIL import Image

from app.core.auth import create_access_token
from app.core.config import settings
from app.db import users_db
from app.db.users_db import create_user
from app.services import share_card

HOSTILE = '<script>alert("x")</script> & "q"'


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "sharing_v2_enabled", True)
    monkeypatch.setattr(users_db, "_hash", lambda pw: f"plain:{pw}")


def _setup(client, dest="Lisbon", name="Trip", display_name=None, **opts):
    uname = f"pg_{uuid.uuid4().hex[:10]}"
    create_user(
        uname,
        "correct-horse-battery",
        email=f"{uname}@example.com",
        display_name=display_name,
    )
    h = {"Authorization": f"Bearer {create_access_token({'sub': uname})}"}
    plan = client.post(
        "/api/plans",
        json={
            "name": name,
            "search_data": {
                "origin": "NYC",
                "destination": dest,
                "departure_date": "2026-04-01",
                "return_date": "2026-04-07",
            },
            "selections": {"activities": [{"name": "a"}]},
        },
        headers=h,
    ).json()
    s = client.post(
        "/api/shares",
        json={"kind": "plan", "plan_id": plan["id"], "options": opts},
        headers=h,
    ).json()
    return s["token"], h


def test_page_tags_and_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://v.example")
    tok, _ = _setup(client)
    r = client.get(f"/api/share/{tok}/page")
    assert r.status_code == 200
    assert r.headers["x-robots-tag"].startswith("noindex")
    assert r.headers["content-type"].startswith("text/html")
    t = r.text
    assert '<meta name="robots" content="noindex' in t
    assert (
        f'og:image" content="https://v.example/api/share/{tok}/card.png?size=link"' in t
    )
    assert f'og:url" content="https://v.example/share/{tok}"' in t
    assert 'twitter:card" content="summary_large_image"' in t
    assert 'og:title" content="7 days in Lisbon"' in t
    assert f'<a href="https://v.example/share/{tok}"' in t


def test_origin_fallback_is_request_origin(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    tok, _ = _setup(client)
    t = client.get(f"/api/share/{tok}/page").text
    assert f'content="http://testserver/api/share/{tok}/card.png?size=link"' in t


def test_hostile_values_escaped(client):
    tok, _ = _setup(
        client, dest=HOSTILE, name=HOSTILE, display_name=HOSTILE, show_name=True
    )
    t = client.get(f"/api/share/{tok}/page").text
    assert "<script>" not in t
    assert "&lt;script&gt;" in t
    png = client.get(f"/api/share/{tok}/card.png?size=story")
    assert png.status_code == 200
    assert Image.open(io.BytesIO(png.content)).size == (1080, 1920)


def test_month_only_even_when_exact_and_no_origin(client):
    tok, _ = _setup(client, dates="exact")
    t = client.get(f"/api/share/{tok}/page").text
    assert "April 2026" in t
    assert "2026-04-01" not in t and "2026-04-07" not in t
    assert "NYC" not in t


def test_hidden_dates_absent(client):
    tok, _ = _setup(client)
    t = client.get(f"/api/share/{tok}/page").text
    assert "2026" not in t and "April" not in t


def test_card_headers(client):
    tok, _ = _setup(client)
    r = client.get(f"/api/share/{tok}/card.png")
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers["x-robots-tag"].startswith("noindex")
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
    assert client.get(f"/api/share/{tok}/card.png?size=huge").status_code == 422


def test_unknown_and_revoked_404_without_tags(client):
    assert client.get("/api/share/nope1234/page").status_code == 404
    tok, h = _setup(client)
    client.get(f"/api/share/{tok}/card.png")
    assert [k for k in share_card._cache if k[0] == tok]
    assert client.delete(f"/api/shares/{tok}", headers=h).status_code == 204
    assert not [k for k in share_card._cache if k[0] == tok]
    for path in ("page", "card.png"):
        r = client.get(f"/api/share/{tok}/{path}")
        assert r.status_code == 404
        assert "og:" not in r.text


def test_flag_off_404(client, monkeypatch):
    tok, _ = _setup(client)
    monkeypatch.setattr(settings, "sharing_v2_enabled", False)
    assert client.get(f"/api/share/{tok}/page").status_code == 404
    assert client.get(f"/api/share/{tok}/card.png").status_code == 404
