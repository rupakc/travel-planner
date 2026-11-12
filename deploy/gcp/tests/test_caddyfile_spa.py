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
