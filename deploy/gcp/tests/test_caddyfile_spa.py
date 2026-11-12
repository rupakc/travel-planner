"""The offline service worker (/sw.js) needs no Caddyfile change: the CSP
already allows a same-origin worker, /sw.js is not caught by the immutable
/assets/* handle, and the SPA handle serves it with Cache-Control no-cache (so
a deploy's new worker is picked up). Plain text checks: no Caddy binary."""

import re
from pathlib import Path

CADDYFILE = Path(__file__).resolve().parent.parent / "Caddyfile"
TEXT = CADDYFILE.read_text()


def _block(opener: str) -> str:
    """The body of the `{ ... }` block that starts at `opener`."""
    start = TEXT.index(opener)
    i = TEXT.index("{", start)
    depth = 0
    for j in range(i, len(TEXT)):
        if TEXT[j] == "{":
            depth += 1
        elif TEXT[j] == "}":
            depth -= 1
            if depth == 0:
                return TEXT[i + 1 : j]
    raise AssertionError(f"unclosed block {opener!r}")


def test_csp_allows_same_origin_worker():
    csp = re.search(r'Content-Security-Policy "([^"]+)"', TEXT)
    assert csp, "no CSP header"
    directives = [d.strip() for d in csp.group(1).split(";")]
    assert "script-src 'self'" in directives
    assert "worker-src 'self' blob:" in directives


def test_sw_js_is_not_an_immutable_asset():
    matcher = _block("@asset {")
    paths = re.findall(r"^\s*path\s+(.+)$", matcher, re.M)
    assert paths == ["/assets/*"]
    for pattern in paths[0].split():
        prefix = pattern.rstrip("*")
        assert not "/sw.js".startswith(prefix), pattern
        assert not "/sw-assets.json".startswith(prefix), pattern
    assert "immutable" in _block("handle @asset {")


def test_spa_handle_is_no_cache():
    # the catch-all `handle {` (no matcher) serves index.html, sw.js and the
    # rest of the public files
    m = re.search(r"^\s*handle \{", TEXT, re.M)
    assert m, "no catch-all handle"
    body = _block(m.group(0).strip())
    assert 'header Cache-Control "no-cache"' in body
    assert "try_files {path} /index.html" in body


# --- crawler route for public share pages ---------------------------------


def _crawler_regex() -> re.Pattern:
    m = re.search(r"header_regexp\s+ua\s+User-Agent\s+(\S+)", _block("@crawler {"))
    assert m, "no User-Agent matcher"
    # Caddy uses Go RE2; the (?i) prefix works the same in Python
    return re.compile(m.group(1))


def test_crawler_handle_precedes_spa_handle():
    crawler = TEXT.index("handle @crawler {")
    spa = re.search(r"^\s*handle \{", TEXT, re.M).start()
    assert crawler < spa
    assert crawler < TEXT.index("handle @asset {")


def test_crawler_path_matches_only_share_tokens():
    body = _block("@crawler {")
    pat = re.search(r"path_regexp\s+share\s+(\S+)", body).group(1)
    rx = re.compile(pat)
    assert rx.match("/share/abcDEF12_-xyz").group(1) == "abcDEF12_-xyz"
    for bad in (
        "/share/short",
        "/share/",
        "/share/abcdefgh/x",
        "/share/" + "a" * 65,
        "/api/share/abcdefgh",
        "/share/abc def12",
    ):
        assert not rx.match(bad), bad


def test_crawler_ua_positives_and_negatives():
    rx = _crawler_regex()
    for ua in (
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Twitterbot/1.0",
        "WhatsApp/2.23.20 A",
        "LinkedInBot/1.0",
        "Slackbot-LinkExpanding 1.0",
        "Mozilla/5.0 (compatible; Discordbot/2.0)",
        "TelegramBot (like TwitterBot)",
        "Mozilla/5.0 (compatible; Googlebot/2.1)",
        "Mozilla/5.0 (compatible; bingbot/2.0)",
        "Mozilla/5.0 (Macintosh) Applebot/0.1",
        "Mozilla/5.0 (compatible; redditbot/1.0)",
        "Mastodon/4.2 (http.rb)",
        "Mozilla/5.0 (iPhone) iMessage",
    ):
        assert rx.search(ua), ua
    for ua in (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile Safari/604.1",
        "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "",
    ):
        assert not rx.search(ua), ua


def test_crawler_handle_proxies_like_backend_and_falls_back_to_spa():
    crawler = _block("handle @crawler {")
    backend = _block("handle @backend {")
    assert "rewrite * /api/share/{re.share.1}/page" in crawler
    for setting in (
        "flush_interval -1",
        "lb_try_duration 30s",
        "lb_try_interval 250ms",
        "header_up X-Real-IP {remote_host}",
        "reverse_proxy app:8001",
    ):
        assert setting in crawler and setting in backend, setting
    assert "handle_response @apperr" in crawler
    assert "status 4xx 5xx" in crawler
    fb = _block("handle_response @apperr {")
    assert "rewrite * /index.html" in fb and "file_server" in fb
    assert "root * /edge/current/srv" in fb


def test_csp_unchanged_by_crawler_route():
    assert TEXT.count("Content-Security-Policy") == 1
