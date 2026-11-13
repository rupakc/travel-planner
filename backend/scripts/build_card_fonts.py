#!/usr/bin/env python3
"""Rebuild the share-card font subsets in ``app/assets/fonts``.

Offline, manual (needs ``pip install fonttools brotli``; never run in CI or at
runtime). Downloads the OFL-licensed Noto variable fonts from google/fonts,
pins them to Regular (wght 400, wdth 100), keeps only the glyphs the share
cards can draw and writes:

    noto-sans-latin.ttf       Latin + Latin Extended + punctuation (en es de fr,
                              digits, user place names)
    noto-sans-devanagari.ttf  whole Devanagari block (hi)
    noto-sans-bengali.ttf     whole Bengali block (bn)
    noto-sans-sc.ttf          every zh catalogue character + GB2312 level 1+2
                              hanzi (~6,763) + place-name characters (zh)
    coverage.json             code-point ranges each file covers (read at
                              runtime so cards never draw a missing glyph)
    OFL.txt                   the licence (Noto Project Authors)

Usage: python scripts/build_card_fonts.py [SRC_DIR]
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "assets" / "fonts"
sys.path.insert(0, str(ROOT))

from app.services.share_card_i18n import all_text  # noqa: E402

BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"
SOURCES = {
    "noto-sans-latin": "notosans/NotoSans[wdth,wght].ttf",
    "noto-sans-devanagari": "notosansdevanagari/NotoSansDevanagari[wdth,wght].ttf",
    "noto-sans-bengali": "notosansbengali/NotoSansBengali[wdth,wght].ttf",
    "noto-sans-sc": "notosanssc/NotoSansSC[wght].ttf",
}

PLACE_CHARS = (
    "东京都大阪巴黎伦敦纽约罗马柏林马德里巴塞罗那曼谷新加坡悉尼墨尔本迪拜开罗"
    "北上海广州深圳香港澳门台湾首尔釜山雅典阿姆斯特丹维也纳布拉格布达佩斯里斯本"
    "威尼斯米兰佛罗伦萨苏黎世日内瓦斯德哥尔摩哥本哈根奥斯陆赫尔辛基莫科圣彼得堡"
    "伊坦孟买德里加各答班罗尔斋浦果阿喀拉加满科伦坡尔代夫厘岛雅达吉隆河内胡志明市"
    "菲律宾金边仰光洛杉矶旧山芝哥华盛顿波士迈密拉维西雅图多温蒙特利墨西哥利马智"
    "宜诺艾斯布里热卢普敦内罗毕喀什卡萨布兰摩洛埃及希腊土耳其泰国日本韩国中国美国"
    "英法德意西班牙葡萄牙印度澳大亚新兰加拿大巴阿根廷秘鲁越南尼马来菲瑞士典挪威丹"
    "麦芬冰爱荷比时奥地捷克波匈牙克罗地联酋以色列约旦非肯尼亚坦桑"
)


def gb2312_hanzi() -> set[int]:
    """Every hanzi of GB2312 level 1 + 2 (rows 16-87, ~6,763 characters)."""
    out = set()
    for row in range(0xB0, 0xF8):
        for col in range(0xA1, 0xFF):
            try:
                ch = bytes([row, col]).decode("gb2312")
            except UnicodeDecodeError:
                continue
            out.add(ord(ch))
    return out


LATIN = (
    list(range(0x20, 0x250))
    + list(range(0x2000, 0x2070))
    + [0x20AC, 0x20B9, 0x2212, 0x2022, 0x2026]
)
RANGES = {
    "noto-sans-latin": LATIN,
    "noto-sans-devanagari": list(range(0x900, 0x980)) + [0x200C, 0x200D, 0x25CC],
    "noto-sans-bengali": list(range(0x980, 0xA00)) + [0x200C, 0x200D, 0x25CC],
    "noto-sans-sc": list(range(0x3000, 0x3040)) + list(range(0xFF01, 0xFF5F)),
}


def fetch(name: str, src_dir: Path) -> Path:
    path = src_dir / f"{name}-src.ttf"
    if not path.exists():
        url = f"{BASE}/{urllib.parse.quote(SOURCES[name], safe='/')}"
        print("download", url)
        urllib.request.urlretrieve(url, path)  # noqa: S310 (fixed https URL)
    return path


def build(name: str, src: Path) -> None:
    font = TTFont(src)
    axes = {"wght": 400}
    if "wdth" in {a.axisTag for a in font["fvar"].axes}:
        axes["wdth"] = 100
    font = instancer.instantiateVariableFont(font, axes)
    wanted = set(RANGES[name]) | {ord(c) for c in all_text() if ord(c) > 0x20}
    if name == "noto-sans-sc":
        wanted |= {ord(c) for c in PLACE_CHARS} | gb2312_hanzi()
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.hinting = False
    opts.notdef_outline = True
    opts.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    opts.drop_tables += ["DSIG"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=wanted)
    sub.subset(font)
    dest = OUT / f"{name}.ttf"
    font.save(dest)
    cmap = sorted(TTFont(dest).getBestCmap())
    print(f"{dest.name}: {dest.stat().st_size // 1024} KB, {len(cmap)} chars")
    COVERAGE[dest.name] = to_ranges(cmap)


def to_ranges(points: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for p in points:
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return out


COVERAGE: dict[str, list[list[int]]] = {}

if __name__ == "__main__":
    src_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/card-font-src")
    src_dir.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for key in SOURCES:
        build(key, fetch(key, src_dir))
    (OUT / "coverage.json").write_text(json.dumps(COVERAGE, indent=0) + "\n")
    lic = src_dir / "OFL.txt"
    if not lic.exists():
        urllib.request.urlretrieve(f"{BASE}/notosans/OFL.txt", lic)  # noqa: S310
    (OUT / "OFL.txt").write_bytes(lic.read_bytes())
