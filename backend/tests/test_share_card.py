"""Share card renderer: PNG validity, sizes, determinism, cache, palette."""

import io
import json
from pathlib import Path

from PIL import Image

from app.services import share_card, share_public

TOKENS = Path(__file__).resolve().parents[2] / "frontend" / "design" / "tokens.json"


def _snap(**kw):
    plan = {
        "name": "Trip",
        "search_data": {
            "destination": "Lisbon",
            "departure_date": "2026-04-01",
            "return_date": "2026-04-07",
        },
        "selections": {"activities": [{"name": "a"}], "hotels": [{"name": "h"}]},
    }
    return share_public.build_snapshot("plan", kw.get("opts"), plan=plan)


def test_png_sizes():
    for size, dims in (("link", (1200, 630)), ("story", (1080, 1920))):
        img = Image.open(io.BytesIO(share_card.render(_snap(), size)))
        assert img.format == "PNG" and img.size == dims


def test_deterministic():
    assert share_card.render(_snap()) == share_card.render(_snap())


def test_hidden_dates_not_in_snapshot():
    snap = _snap()
    assert snap["period"] is None
    assert "2026" not in json.dumps(snap)
    exact = _snap(opts={"dates": "exact"})
    assert exact["period"] == "2026-04"
    assert "2026-04-01" not in json.dumps(exact)


def test_hostile_and_non_latin_headline_renders():
    snap = _snap()
    snap["headline"] = "<script>alert(1)</script> " + "x" * 500
    snap["owner_name"] = "東京"
    assert Image.open(io.BytesIO(share_card.render(snap, "story"))).size == (1080, 1920)
    snap["headline"] = "東京 7 days"
    assert share_card.safe_headline(snap) == "7 days away"


def test_cache_and_invalidate():
    share_card.invalidate("t1")
    a = share_card.get_card("t1", _snap(), "link")
    assert share_card.get_card("t1", _snap(), "link") is a
    share_card.invalidate("t1")
    assert not [k for k in share_card._cache if k[0] == "t1"]


def test_palette_matches_tokens():
    pal = json.loads(TOKENS.read_text())["palette"]
    teal, bg = pal["teal"], share_card.PALETTE
    assert bg["bg"] == teal["700"]
    assert bg["bg_dark"] == teal["800"]
    assert bg["muted"] == teal["100"]
    assert bg["chip"] == teal["900"]
    assert bg["chip_text"] == teal["50"]
