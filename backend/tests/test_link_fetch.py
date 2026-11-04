"""Safe link fetching (SSRF guards) and page-content extraction.

No network: httpx.MockTransport stands in for the web and a fake resolver
stands in for DNS.
"""

import json

import httpx
import pytest

from app.services import link_fetch
from app.services.link_fetch import (
    LinkFetchError,
    extract_page,
    fetch_url,
    is_public_ip,
    read_link,
)

PUBLIC_IP = "93.184.216.34"


def _resolver(table: dict[str, list[str]]):
    calls: list[str] = []

    async def resolve(host: str) -> list[str]:
        calls.append(host)
        if host not in table:
            raise LinkFetchError("unreachable", "no such host")
        return table[host]

    resolve.calls = calls
    return resolve


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _html(body: str, head: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


# ── IP classification ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "198.18.0.1",  # benchmarking
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "ff02::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
        "2002:7f00:1::",  # 6to4 of 127.0.0.1
        "2001:db8::1",  # documentation
        "not-an-ip",
    ],
)
def test_non_public_addresses_are_rejected(addr):
    assert is_public_ip(addr) is False


@pytest.mark.parametrize("addr", ["8.8.8.8", PUBLIC_IP, "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(addr):
    assert is_public_ip(addr) is True


# ── URL / scheme validation ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "javascript:alert(1)",
        "data:text/html,hi",
        "http://",
        "https://user:pw@example.com/",
        "http://example.com:6379/",  # non-web port
        "not a url",
    ],
)
async def test_bad_urls_are_rejected_before_any_request(url):
    def handler(request):  # pragma: no cover - must never run
        raise AssertionError("no request should be made")

    resolver = _resolver({"example.com": [PUBLIC_IP]})
    with pytest.raises(LinkFetchError) as err:
        await fetch_url(url, client=_client(handler), resolver=resolver)
    assert err.value.code == "invalid_url"
    assert resolver.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://[fd00::1]/",
    ],
)
async def test_ip_literal_private_hosts_are_blocked(url):
    def handler(request):  # pragma: no cover
        raise AssertionError("no request should be made")

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(url, client=_client(handler), resolver=_resolver({}))
    assert err.value.code == "blocked_address"


@pytest.mark.parametrize(
    "answers",
    [
        ["127.0.0.1"],
        ["10.0.0.7"],
        ["::1"],
        ["::ffff:192.168.0.1"],
        [PUBLIC_IP, "127.0.0.1"],  # any private answer poisons the host
    ],
)
async def test_hostnames_resolving_to_private_addresses_are_blocked(answers):
    def handler(request):  # pragma: no cover
        raise AssertionError("no request should be made")

    resolver = _resolver({"evil.example": answers})
    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://evil.example/", client=_client(handler), resolver=resolver
        )
    assert err.value.code == "blocked_address"


# ── DNS-rebinding pin ────────────────────────────────────────────────────


async def test_connects_to_the_vetted_ip_with_original_host_and_sni():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text=_html("<p>hi</p>")
        )

    resolver = _resolver({"blog.example": [PUBLIC_IP]})
    page = await fetch_url(
        "https://blog.example/trip?x=1", client=_client(handler), resolver=resolver
    )
    assert len(seen) == 1
    req = seen[0]
    assert req.url.host == PUBLIC_IP  # connected to the pinned IP …
    assert req.url.path == "/trip" and req.url.query == b"x=1"
    assert req.headers["host"] == "blog.example"  # … while asking for the host
    assert req.extensions.get("sni_hostname") == "blog.example"
    assert "Mozilla" in req.headers["user-agent"]
    assert resolver.calls == ["blog.example"]  # resolved once, never again
    assert page.final_url == "https://blog.example/trip?x=1"


async def test_ipv6_pin_is_bracketed():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="ok")

    resolver = _resolver({"v6.example": ["2606:4700:4700::1111"]})
    await fetch_url("http://v6.example/", client=_client(handler), resolver=resolver)
    assert seen[0].url.host == "2606:4700:4700::1111"
    assert seen[0].headers["host"] == "v6.example"


# ── Redirects ─────────────────────────────────────────────────────────────


async def test_redirect_to_private_address_is_blocked():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "http://internal.example/admin"}
        )

    resolver = _resolver(
        {"blog.example": [PUBLIC_IP], "internal.example": ["192.168.0.10"]}
    )
    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://blog.example/", client=_client(handler), resolver=resolver
        )
    assert err.value.code == "blocked_address"


async def test_redirect_to_ip_literal_metadata_is_blocked():
    def handler(request):
        return httpx.Response(
            301, headers={"location": "http://169.254.169.254/latest/meta-data/"}
        )

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://blog.example/",
            client=_client(handler),
            resolver=_resolver({"blog.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "blocked_address"


async def test_redirect_to_non_http_scheme_is_rejected():
    def handler(request):
        return httpx.Response(302, headers={"location": "file:///etc/passwd"})

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://blog.example/",
            client=_client(handler),
            resolver=_resolver({"blog.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "invalid_url"


async def test_relative_redirects_are_followed_and_each_hop_revetted():
    hops = []

    def handler(request):
        hops.append((request.headers["host"], request.url.path))
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        if request.url.path == "/b":
            return httpx.Response(
                302, headers={"location": "https://cdn.example/final"}
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>x</p>"
        )

    resolver = _resolver({"blog.example": [PUBLIC_IP], "cdn.example": ["8.8.4.4"]})
    page = await fetch_url(
        "https://blog.example/a", client=_client(handler), resolver=resolver
    )
    assert hops == [
        ("blog.example", "/a"),
        ("blog.example", "/b"),
        ("cdn.example", "/final"),
    ]
    assert page.final_url == "https://cdn.example/final"
    assert "cdn.example" in resolver.calls


async def test_more_than_three_redirects_fail():
    def handler(request):
        n = int(request.url.path.strip("/") or 0)
        return httpx.Response(302, headers={"location": f"/{n + 1}"})

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://blog.example/0",
            client=_client(handler),
            resolver=_resolver({"blog.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "too_many_redirects"


# ── Body limits and content types ────────────────────────────────────────


async def test_reading_stops_at_two_megabytes():
    chunk = b"a" * 65536
    produced = []

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(200):  # 12.5 MB if fully read
                produced.append(1)
                yield chunk

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, stream=Endless()
        )

    page = await fetch_url(
        "https://big.example/",
        client=_client(handler),
        resolver=_resolver({"big.example": [PUBLIC_IP]}),
    )
    assert len(page.text) <= link_fetch.MAX_BYTES
    assert page.truncated is True
    assert len(produced) < 40  # stopped early, never drained the stream


@pytest.mark.parametrize(
    "ctype", ["application/pdf", "image/png", "application/octet-stream", ""]
)
async def test_wrong_content_type_is_rejected(ctype):
    def handler(request):
        return httpx.Response(200, headers={"content-type": ctype}, content=b"%PDF")

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://x.example/file",
            client=_client(handler),
            resolver=_resolver({"x.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "unsupported_content"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (404, "not_found"),
        (410, "not_found"),
        (401, "paywall"),
        (403, "blocked_by_site"),
        (402, "paywall"),
        (500, "http_error"),
        (429, "http_error"),
    ],
)
async def test_http_errors_map_to_friendly_codes(status, code):
    def handler(request):
        return httpx.Response(status, headers={"content-type": "text/html"}, text="no")

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://x.example/",
            client=_client(handler),
            resolver=_resolver({"x.example": [PUBLIC_IP]}),
        )
    assert err.value.code == code
    assert err.value.message


async def test_timeouts_are_reported():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://x.example/",
            client=_client(handler),
            resolver=_resolver({"x.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "timeout"


# ── Extraction ────────────────────────────────────────────────────────────

BLOG = _html(
    head="""
    <title>48 Hours in Lisbon | Wander Blog</title>
    <meta property="og:site_name" content="Wander Blog">
    <meta property="og:description" content="Our favourite weekend in Lisbon.">
    <meta name="author" content="Ana Silva">
    <link rel="icon" href="/static/fav.png">
    <script type="application/ld+json">{"@context":"https://schema.org",
      "@graph":[{"@type":"ItemList","itemListElement":[
        {"@type":"ListItem","position":1,"name":"Belém Tower"},
        {"@type":"ListItem","position":2,"item":{"@type":"TouristAttraction",
          "name":"LX Factory","address":{"addressLocality":"Lisbon"}}}]}]}
    </script>
    <script>window.evil = "IGNORE ME";</script>
    <style>.x{color:red}</style>
    """,
    body="""
    <nav>Home | About | Shop</nav>
    <article>
      <h2>Day 1</h2>
      <p>Start at Time Out Market for lunch.</p>
      <ul><li>Miradouro da Senhora do Monte at sunset</li><li>Pastéis de Belém</li></ul>
    </article>
    <footer>© 2026 Wander Blog — subscribe!</footer>
    """,
)


def test_extract_page_reads_metadata_jsonld_and_main_text():
    page = extract_page(BLOG, "https://wander.example/lisbon")
    assert page["title"] == "48 Hours in Lisbon | Wander Blog"
    assert page["site_name"] == "Wander Blog"
    assert page["description"] == "Our favourite weekend in Lisbon."
    assert page["author"] == "Ana Silva"
    assert page["favicon_url"] == "https://wander.example/static/fav.png"
    text = page["text"]
    assert "Belém Tower" in text and "LX Factory" in text  # JSON-LD
    assert "## Day 1" in text
    assert "- Miradouro da Senhora do Monte at sunset" in text
    assert "Time Out Market" in text
    assert "IGNORE ME" not in text and "color:red" not in text
    assert "Home | About" not in text and "subscribe" not in text


def test_extract_page_defaults_favicon_and_site_name():
    page = extract_page(
        _html("<p>Hello</p>", "<title>T</title>"), "https://www.site.example/a/b"
    )
    assert page["site_name"] == "site.example"
    assert page["favicon_url"] == "https://www.site.example/favicon.ico"


def test_extract_page_caps_text():
    body = "".join(
        f"<p>Paragraph number {i} about a lovely place.</p>" for i in range(5000)
    )
    page = extract_page(_html(f"<main>{body}</main>"), "https://x.example/")
    assert len(page["text"]) <= link_fetch.MAX_TEXT_CHARS


def test_extract_page_handles_article_body_jsonld():
    ld = json.dumps(
        {"@type": "BlogPosting", "articleBody": "Visit Sintra and Cascais."}
    )
    page = extract_page(
        _html("<div>x</div>", f'<script type="application/ld+json">{ld}</script>'),
        "https://x.example/",
    )
    assert "Visit Sintra and Cascais." in page["text"]


# ── read_link: pages and social sources ──────────────────────────────────


async def test_read_link_returns_page_content():
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, text=BLOG
        )

    content = await read_link(
        "https://wander.example/lisbon",
        client=_client(handler),
        resolver=_resolver({"wander.example": [PUBLIC_IP]}),
    )
    assert content.title.startswith("48 Hours in Lisbon")
    assert content.site_name == "Wander Blog"
    assert "Belém Tower" in content.text


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.instagram.com/p/abc123/", "Instagram"),
        ("https://instagram.com/reel/xyz", "Instagram"),
        ("https://www.facebook.com/somebody/posts/1", "Facebook"),
        ("https://x.com/someone/status/1", "X"),
        ("https://twitter.com/someone/status/1", "X"),
        ("https://www.threads.net/@a/post/1", "Threads"),
    ],
)
async def test_blocked_social_sources_get_a_specific_message(url, platform):
    def handler(request):  # pragma: no cover
        raise AssertionError("never fetched")

    with pytest.raises(LinkFetchError) as err:
        await read_link(url, client=_client(handler), resolver=_resolver({}))
    assert err.value.code == "blocked_source"
    assert platform in err.value.message
    assert "screenshot" in err.value.message


async def test_youtube_uses_oembed_and_page_description():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/oembed":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"title": "Tokyo in 3 days", "author_name": "TravelCam"},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=_html(
                "",
                '<meta property="og:description" content="Shibuya, teamLab, Asakusa">',
            ),
        )

    resolver = _resolver({"www.youtube.com": [PUBLIC_IP]})
    content = await read_link(
        "https://youtu.be/abcDEF12345", client=_client(handler), resolver=resolver
    )
    assert content.title == "Tokyo in 3 days"
    assert content.author == "TravelCam"
    assert content.site_name == "YouTube"
    assert "Shibuya, teamLab, Asakusa" in content.text
    assert any("/oembed" in u for u in seen)


async def test_tiktok_uses_oembed_caption():
    def handler(request):
        assert request.url.path == "/oembed"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"title": "Hidden bars in Mexico City #cdmx", "author_name": "@eats"},
        )

    content = await read_link(
        "https://www.tiktok.com/@eats/video/123",
        client=_client(handler),
        resolver=_resolver({"www.tiktok.com": [PUBLIC_IP]}),
    )
    assert "Hidden bars in Mexico City" in content.text
    assert content.site_name == "TikTok"


def test_extract_page_prefers_the_biggest_content_block_over_a_teaser():
    places = "".join(
        f"<h3>{n}</h3><p>{n} is one of the best places in Lisbon to visit.</p>"
        for n in ("Belém Tower", "Alfama", "LX Factory", "Time Out Market", "Sintra")
    )
    html = _html(
        '<article class="related"><h2>The Best Hotels in Lisbon</h2>'
        "<p>Read our hotel guide.</p></article>"
        f'<div class="entry-content">{places}</div>'
    )
    text = extract_page(html, "https://x.example/")["text"]
    for n in ("Belém Tower", "Alfama", "LX Factory", "Time Out Market", "Sintra"):
        assert n in text


# ── Decompression bombs (C-1) ────────────────────────────────────────────

import gzip  # noqa: E402
import threading  # noqa: E402
import tracemalloc  # noqa: E402
import zlib  # noqa: E402

BOMB_SIZE = 64 * 1024 * 1024  # 64 MB of zeros, a few dozen KB on the wire


def _zeros_gzip() -> bytes:
    return gzip.compress(b"\0" * BOMB_SIZE, compresslevel=9)


def _zeros_zlib(raw: bool = False) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15 if raw else 15)
    return c.compress(b"\0" * BOMB_SIZE) + c.flush()


def _streaming(body: bytes, encoding: str, ctype: str = "text/html"):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(0, len(body), 65536):
                yield body[i : i + 65536]

    seen = {}

    def handler(request):
        seen["accept-encoding"] = request.headers.get("accept-encoding")
        return httpx.Response(
            200,
            headers={"content-type": ctype, "content-encoding": encoding},
            stream=Stream(),
        )

    return handler, seen


async def _fetch_bomb(body, encoding):
    handler, seen = _streaming(body, encoding)
    tracemalloc.start()
    try:
        page = await fetch_url(
            "https://bomb.example/",
            client=_client(handler),
            resolver=_resolver({"bomb.example": [PUBLIC_IP]}),
        )
        error = None
    except LinkFetchError as exc:
        page, error = None, exc
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return page, error, peak, seen


@pytest.mark.parametrize(
    ("make", "encoding"),
    [
        (_zeros_gzip, "gzip"),
        (_zeros_zlib, "deflate"),
        (lambda: _zeros_zlib(True), "deflate"),
    ],
)
async def test_gzip_and_deflate_bombs_stop_at_the_cap_with_bounded_memory(
    make, encoding
):
    page, error, peak, seen = await _fetch_bomb(make(), encoding)
    assert error is None
    assert page.truncated is True
    assert len(page.text) <= link_fetch.MAX_BYTES
    assert peak < 24 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB"
    assert seen["accept-encoding"] == "gzip, deflate"


async def test_stacked_gzip_bomb_is_refused():
    body = gzip.compress(_zeros_gzip())
    page, error, peak, _ = await _fetch_bomb(body, "gzip, gzip")
    assert page is None and error.code == "unsupported_encoding"
    assert "compress" in error.message.lower() or "encod" in error.message.lower()
    assert peak < 24 * 1024 * 1024


@pytest.mark.parametrize("encoding", ["br", "zstd", "compress", "x-weird"])
async def test_other_encodings_are_refused_without_decoding(encoding):
    import brotli

    body = (
        brotli.compress(b"\0" * BOMB_SIZE)
        if encoding == "br"
        else b"\x28\xb5\x2f\xfd" * 100
    )
    page, error, peak, _ = await _fetch_bomb(body, encoding)
    assert page is None and error.code == "unsupported_encoding"
    assert peak < 24 * 1024 * 1024


async def test_compressed_page_still_reads_normally():
    html = _html("<article><p>Belém Tower and LX Factory</p></article>").encode()
    handler, _ = _streaming(gzip.compress(html), "gzip")
    page = await fetch_url(
        "https://ok.example/",
        client=_client(handler),
        resolver=_resolver({"ok.example": [PUBLIC_IP]}),
    )
    assert "Belém Tower" in page.text and page.truncated is False


async def test_raw_bytes_are_capped_even_for_identity():
    produced = []

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(500):
                produced.append(1)
                yield b"<p>" + b"a" * 65530 + b"</p>"

    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, stream=Endless()
        )

    page = await fetch_url(
        "https://big.example/",
        client=_client(handler),
        resolver=_resolver({"big.example": [PUBLIC_IP]}),
    )
    assert page.truncated and len(produced) < 40


async def test_page_parsing_runs_off_the_event_loop(monkeypatch):
    threads = []
    real = link_fetch.extract_page

    def spy(html, url):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(html, url)

    monkeypatch.setattr(link_fetch, "extract_page", spy)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, text=BLOG)

    await read_link(
        "https://wander.example/lisbon",
        client=_client(handler),
        resolver=_resolver({"wander.example": [PUBLIC_IP]}),
    )
    assert threads == [False]


# ── Review minors ────────────────────────────────────────────────────────


@pytest.mark.parametrize("addr", ["fec0::1", "3fff::1"])
def test_site_local_and_new_documentation_ranges_are_rejected(addr):
    assert is_public_ip(addr) is False


async def test_each_hop_asks_for_a_fresh_connection():
    seen = []

    def handler(request):
        seen.append(request.headers.get("connection"))
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://cdn.example/b"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="ok")

    await fetch_url(
        "https://blog.example/a",
        client=_client(handler),
        resolver=_resolver({"blog.example": [PUBLIC_IP], "cdn.example": [PUBLIC_IP]}),
    )
    assert seen == ["close", "close"]


async def test_a_redirect_to_a_blocked_platform_gets_its_specific_message():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "https://www.instagram.com/p/x/"}
        )

    with pytest.raises(LinkFetchError) as err:
        await read_link(
            "https://bit.example/abc",
            client=_client(handler),
            resolver=_resolver({"bit.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "blocked_source" and "Instagram" in err.value.message


def test_t_co_is_followed_not_blocked():
    assert link_fetch.blocked_source("https://t.co/abc") is None


async def test_403_is_a_site_that_blocks_apps_not_a_paywall():
    def handler(request):
        return httpx.Response(403, headers={"content-type": "text/html"}, text="no")

    with pytest.raises(LinkFetchError) as err:
        await fetch_url(
            "https://x.example/",
            client=_client(handler),
            resolver=_resolver({"x.example": [PUBLIC_IP]}),
        )
    assert err.value.code == "blocked_by_site"
    assert "subscription" not in err.value.message


async def test_a_custom_port_gets_a_message_that_fits():
    with pytest.raises(LinkFetchError) as err:
        await fetch_url("http://x.example:8080/", resolver=_resolver({}))
    assert err.value.code == "invalid_url"
    assert (
        "port" in err.value.message.lower() or "normal web" in err.value.message.lower()
    )
