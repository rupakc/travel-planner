"""Every GET search route answers (regression: the nationality search SQL
was broken by an edit meant for the airport search)."""

import pytest

from app.db.database import search_nationalities


def _search_routes():
    from app.main import app

    paths = app.openapi()["paths"]
    return sorted(
        p for p, ops in paths.items() if p.endswith("/search") and "get" in ops
    )


def test_search_routes_are_found():
    assert {"/api/airports/search", "/api/nationalities/search"} <= set(
        _search_routes()
    )


@pytest.mark.parametrize("path", _search_routes())
@pytest.mark.parametrize("q", ["ind", "a", "Zürich", "%_'\""])
def test_every_get_search_route_answers(client, path, q):
    r = client.get(path, params={"q": q})
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_nationality_search_finds_matches(client):
    r = client.get("/api/nationalities/search", params={"q": "ind"})
    assert r.status_code == 200
    names = [row["nationality"] for row in r.json()]
    assert "Indian" in names
    assert set(r.json()[0]) == {"nationality", "country", "country_code"}


def test_nationality_search_ranks_prefix_first(client):
    rows = search_nationalities("ger")
    assert rows[0]["nationality"].lower().startswith("ger")
