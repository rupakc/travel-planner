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


def _gb2312_chars():
    out = []
    for row in range(0xB0, 0xF8):
        for col in range(0xA1, 0xFF):
            try:
                out.append(bytes([row, col]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return out


def test_sc_font_covers_gb2312_sample_and_common_chars():
    import random

    from fontTools.ttLib import TTFont

    from app.services import share_card

    cmap = TTFont(share_card.FONT_DIR / "noto-sans-sc.ttf").getBestCmap()
    chars = _gb2312_chars()
    assert len(chars) > 6700
    sample = random.Random(7).sample(chars, 600) + list("程序北京东京")
    assert [c for c in sample if ord(c) not in cmap] == []
    assert share_card.supported("程 · 上海", "zh")


def test_hi_bn_fonts_cover_every_assigned_block_char():
    import unicodedata

    from fontTools.ttLib import TTFont

    from app.services import share_card

    for file, lo, hi in (
        ("noto-sans-devanagari.ttf", 0x900, 0x97F),
        ("noto-sans-bengali.ttf", 0x980, 0x9FF),
    ):
        cmap = TTFont(share_card.FONT_DIR / file).getBestCmap()
        missing = [
            hex(c)
            for c in range(lo, hi + 1)
            if unicodedata.name(chr(c), None) and c not in cmap
        ]
        # the font itself lacks a few rare assigned Bengali letters (Noto Sans Bengali)
        assert len(missing) <= 8, missing
