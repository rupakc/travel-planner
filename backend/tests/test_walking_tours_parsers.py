"""Tests for the walking-tour provider parsers and city helpers."""

import json

from app.services.walking_tours import (
    city_slug,
    parse_freewalkingtour,
    parse_jsonld_tours,
    parse_sandemans,
    split_city_country,
)


def _ld(data) -> str:
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def _event(
    name, url, rating=4.9, reviews=120, image="https://media.guruwalk.com/a.jpg"
):
    ev = {
        "@type": "Event",
        "name": name,
        "url": url,
        "image": image,
        "description": "d",
    }
    if rating is not None:
        ev["aggregateRating"] = {"ratingValue": rating, "reviewCount": reviews}
    return ev


def test_city_slug_basic():
    assert city_slug("Barcelona") == "barcelona"
    assert city_slug("New York") == "new-york"
    assert city_slug("Kraków") == "krakow"
    assert city_slug("Mexico City") == "mexico-city"
    assert city_slug("  São Paulo ") == "sao-paulo"


def test_split_city_country():
    assert split_city_country("Tokyo, Japan (HND)") == ("Tokyo", "Japan")
    assert split_city_country("Lisbon") == ("Lisbon", None)
    assert split_city_country("Paris, France") == ("Paris", "France")


def test_parse_jsonld_extracts_events():
    html = _ld(
        {
            "@graph": [
                {"@type": "WebPage", "name": "x"},
                {
                    "@type": "ItemList",
                    "itemListElement": [
                        _event("Tour A", "https://www.guruwalk.com/walks/1-a"),
                        _event("Tour B", "https://www.guruwalk.com/walks/2-b"),
                    ],
                },
            ]
        }
    )
    tours = parse_jsonld_tours(html, "guruwalk", "Barcelona")
    assert len(tours) == 2
    t = tours[0]
    assert t["name"] == "Tour A"
    assert t["url"] == "https://www.guruwalk.com/walks/1-a"
    assert t["image_url"] == "https://media.guruwalk.com/a.jpg"
    assert t["rating"] == 4.9
    assert t["review_count"] == 120
    assert t["price_note"] == "Free · tip-based"
    assert t["provider"] == "GuruWalk"
    assert t["provider_key"] == "guruwalk"
    assert t["id"] == "guruwalk-barcelona-0"
    assert tours[1]["id"] == "guruwalk-barcelona-1"
    assert t["reason"] is None and t["top_pick"] is False
    assert t["city"] == "Barcelona"


def test_parse_jsonld_tolerates_bad_blocks():
    html = '<script type="application/ld+json">{not json</script>' + _ld(
        [
            _event(
                "Str", "https://www.guruwalk.com/walks/1", rating="4.8", reviews="10"
            ),
            _event("NoRating", "https://www.guruwalk.com/walks/2", rating=None),
        ]
    )
    tours = parse_jsonld_tours(html, "guruwalk", "Barcelona")
    assert len(tours) == 2
    assert tours[0]["rating"] == 4.8 and isinstance(tours[0]["rating"], float)
    assert tours[0]["review_count"] == 10
    assert tours[1]["rating"] is None and tours[1]["review_count"] is None


def test_parse_jsonld_normalizes_ten_point_ratings():
    ev = _event("Ten", "https://www.freetour.com/w/1", rating=9.5)
    ev["aggregateRating"]["bestRating"] = "10"
    tours = parse_jsonld_tours(_ld([ev]), "freetour", "Rome")
    assert tours[0]["rating"] == 4.75


def test_parse_jsonld_drops_foreign_urls_and_duplicates():
    html = _ld(
        [
            _event("Evil", "https://evil.example/walks/1"),
            _event("Sneaky", "https://guruwalk.com.evil.example/walks/1"),
            _event("Ok", "https://www.guruwalk.com/walks/1"),
            _event("Dup", "https://www.guruwalk.com/walks/1"),
        ]
    )
    tours = parse_jsonld_tours(html, "guruwalk", "Barcelona")
    assert [t["name"] for t in tours] == ["Ok"]


def test_parse_jsonld_caps_at_ten():
    html = _ld([_event(f"T{i}", f"https://www.freetour.com/w/{i}") for i in range(15)])
    assert len(parse_jsonld_tours(html, "freetour", "Rome")) == 10


def _card(href, text, img="/_ipx/x/img.webp"):
    return f'<a href="{href}" class="relative block h-full"><img src="{img}" alt="">{text}</a>'


FWT_HTML = (
    "<html><body>"
    + _card(
        "/barcelona/barcelona-historic-centre-spain/",
        "Pay what you wish Welcome to Barcelona: Old Town and Modernism "
        "4.9 116 reviews 2h 30m Book now",
    )
    + _card(
        "/barcelona/private-gaudi/",
        "From 150 EUR Private Gaudi 5.0 12 reviews 3h Book now",
    )
    + _card(
        "/barcelona/gothic-quarter/",
        "Pay what you wish Gothic Quarter Walk 4.7 80 reviews 2h Book now",
    )
    + "</body></html>"
)


def test_parse_freewalkingtour_cards():
    tours = parse_freewalkingtour(FWT_HTML, "barcelona", "Barcelona")
    assert len(tours) == 2
    t = tours[0]
    assert t["name"] == "Welcome to Barcelona: Old Town and Modernism"
    assert t["rating"] == 4.9
    assert t["review_count"] == 116
    assert t["duration"] == "2h 30m"
    assert (
        t["url"]
        == "https://freewalkingtour.com/barcelona/barcelona-historic-centre-spain/"
    )
    assert t["image_url"] == "https://freewalkingtour.com/_ipx/x/img.webp"
    assert t["price_note"] == "Pay what you wish"
    assert t["provider_key"] == "freewalkingtour"
    assert t["id"] == "freewalkingtour-barcelona-0"
    assert tours[1]["name"] == "Gothic Quarter Walk"
    assert tours[1]["duration"] == "2h"


SANDEMANS_HTML = """
<html><body>
<a href="https://www.neweuropetours.eu/sandemans-tours/barcelona/free-tour-of-barcelona/">Free Tour of Barcelona</a>
<a href="https://www.neweuropetours.eu/sandemans-tours/barcelona/barcelona-gaudi-modernism-tour/">Barcelona Gaudí &amp; Modernism Free Tour</a>
<a href="https://www.neweuropetours.eu/sandemans-tours/barcelona/3-hour-barcelona-private-city-tour/">3-hour Barcelona Private City Tour</a>
<a href="/sandemans-tours/barcelona/free-tour-of-barcelona/">Free Tour of Barcelona</a>
<a href="https://evil.example/sandemans-tours/barcelona/free-tour/">Free Tour Evil</a>
</body></html>
"""


def test_parse_sandemans_keeps_free_only():
    tours = parse_sandemans(SANDEMANS_HTML, "barcelona", "Barcelona")
    assert [t["name"] for t in tours] == [
        "Free Tour of Barcelona",
        "Barcelona Gaudí & Modernism Free Tour",
    ]
    assert tours[0]["url"] == (
        "https://www.neweuropetours.eu/sandemans-tours/barcelona/free-tour-of-barcelona/"
    )
    assert tours[0]["provider"] == "SANDEMANs NewEurope"
    assert tours[0]["price_note"] == "Free · tip-based"
    assert tours[0]["rating"] is None and tours[0]["duration"] is None


def test_parsers_return_empty_on_garbage():
    for garbage in ("", "<html>nothing</html>"):
        assert parse_jsonld_tours(garbage, "guruwalk", "X") == []
        assert parse_freewalkingtour(garbage, "x", "X") == []
        assert parse_sandemans(garbage, "x", "X") == []


def test_parse_freewalkingtour_strips_language_badge_prefix():
    # Live cards render a "+1" extra-languages badge before the title.
    html = (
        "<html><body>"
        + _card(
            "/krakow/old-town-krakow/",
            "Pay what you wish +1 Welcome to Kraków! Old Town & Wawel Hill "
            "Guided Walking Tour 4.9 2039 reviews 2h 30m Book now",
        )
        + "</body></html>"
    )
    tours = parse_freewalkingtour(html, "krakow", "Kraków")
    assert [t["name"] for t in tours] == [
        "Welcome to Kraków! Old Town & Wawel Hill Guided Walking Tour"
    ]
