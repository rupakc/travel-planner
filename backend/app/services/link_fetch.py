"""Fetch a user-supplied link safely and pull readable trip text out of it.

SSRF guards (the URL comes straight from a user):

- http/https only, default web ports only, no credentials in the URL;
- the host is resolved here and EVERY answer must be a public address
  (no private, loopback, link-local, multicast, reserved, CGNAT ranges, nor
  their IPv6 / IPv4-mapped / NAT64 / 6to4 / Teredo forms);
- the request connects to that vetted IP while sending the original Host
  header and TLS SNI, so a second DNS answer can't rebind the connection;
- redirects are followed by hand (at most 3), each hop re-validated;
- the whole fetch has a 10 s ceiling and the body is read up to 2 MB;
- only HTML / XHTML / plain text (JSON for oEmbed) is accepted.

Content is parsed, never executed, and links inside it are never followed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10.0
MAX_TEXT_CHARS = 30_000

PAGE_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
JSON_TYPES = frozenset({"application/json", "text/json", "text/javascript"})

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
_ALLOWED_PORTS = {None, 80, 443}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")

Resolver = Callable[[str], Awaitable[list[str]]]


class LinkFetchError(Exception):
    """A fetch that failed in a way the traveller can act on.

    ``code`` is stable for the frontend; ``message`` is shown as-is.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_MESSAGES = {
    "invalid_url": "That doesn't look like a web link we can open — "
    "it needs to start with http:// or https://.",
    "blocked_address": "That link points somewhere private, so we can't open it.",
    "unreachable": "We couldn't reach that website. Check the link, "
    "or paste the text instead.",
    "timeout": "That page took too long to load. Try again, or paste the "
    "text of the article instead.",
    "too_many_redirects": "That link kept redirecting us. Try the final page's "
    "address, or paste the text instead.",
    "not_found": "That page doesn't exist any more (404). Check the link, "
    "or paste the text instead.",
    "paywall": "That page needs a login or subscription, so we can't read it. "
    "Paste the article text or drop a screenshot instead.",
    "http_error": "That website returned an error. Try again in a moment, "
    "or paste the text instead.",
    "unsupported_content": "That link isn't a web page we can read "
    "(it looks like a file or image). Drop a screenshot instead.",
    "unsupported_encoding": "That website sent its page in a compressed format "
    "we don't read. Paste the article text or drop a screenshot instead.",
}

_BLOCKED_SOURCES = {
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "fb.com": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "t.co": "X",
    "threads.net": "Threads",
    "threads.com": "Threads",
}


def _error(code: str) -> LinkFetchError:
    return LinkFetchError(code, _MESSAGES[code])


# ── Address checks ───────────────────────────────────────────────────────


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv4 addresses an IPv6 address smuggles (mapped, NAT64, 6to4, Teredo)."""
    found = []
    if ip.ipv4_mapped:
        found.append(ip.ipv4_mapped)
    if ip in _NAT64:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip.sixtofour:
        found.append(ip.sixtofour)
    if ip.teredo:
        found.extend(ip.teredo)
    return found


def is_public_ip(addr: str) -> bool:
    """True only for a globally routable unicast address."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        return ip not in _CGNAT
    return all(is_public_ip(str(v4)) for v4 in _embedded_ipv4(ip))


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise _error("unreachable") from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


def _validated(url: str):
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise _error("invalid_url") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _error("invalid_url")
    if parts.username or parts.password or port not in _ALLOWED_PORTS:
        raise _error("invalid_url")
    return parts


async def _vetted_ip(host: str, resolver: Resolver) -> str:
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    addrs = [host] if literal else await resolver(host)
    if not addrs:
        raise _error("unreachable")
    if not all(is_public_ip(a) for a in addrs):
        raise _error("blocked_address")
    return addrs[0]


# ── Bounded decompression ────────────────────────────────────────────────
#
# httpx's own decoders inflate a whole chunk before anything can check its
# size, so a 2 KB brotli or nested-gzip "bomb" could expand to gigabytes.
# We ask for gzip/deflate only, read RAW bytes, and inflate them ourselves
# with zlib's ``max_length`` so output never exceeds MAX_BYTES.


class _BoundedDecoder:
    def __init__(self, content_encoding: str) -> None:
        codings = [c.strip().lower() for c in content_encoding.split(",") if c.strip()]
        codings = [c for c in codings if c != "identity"]
        if not codings:
            self._kind = None
        elif len(codings) == 1 and codings[0] in ("gzip", "x-gzip"):
            self._kind = "gzip"
        elif len(codings) == 1 and codings[0] == "deflate":
            self._kind = "deflate"
        else:  # br, zstd, compress, stacked encodings, anything unknown
            raise _error("unsupported_encoding")
        self._z = None
        self._head = b""

    def _start(self, data: bytes):
        if self._kind == "gzip":
            return zlib.decompressobj(16 + zlib.MAX_WBITS)
        # "deflate" is zlib-wrapped per the RFC, but many servers send raw
        is_zlib = (
            len(data) >= 2
            and data[0] & 0x0F == 8
            and (data[0] << 8 | data[1]) % 31 == 0
        )
        return zlib.decompressobj(zlib.MAX_WBITS if is_zlib else -zlib.MAX_WBITS)

    def feed(self, chunk: bytes, room: int) -> bytes:
        """At most ``room`` decoded bytes from ``chunk``."""
        if self._kind is None:
            return chunk[:room]
        if self._z is None:
            self._head += chunk
            if len(self._head) < 2:
                return b""
            chunk, self._head = self._head, b""
            self._z = self._start(chunk)
        out = bytearray()
        data = chunk
        try:
            while data and room - len(out) > 0:
                out += self._z.decompress(data, room - len(out))
                data = self._z.unconsumed_tail
        except zlib.error as exc:
            raise _error("unsupported_encoding") from exc
        return bytes(out)


async def _raw_chunks(resp: httpx.Response):
    """The body's undecoded bytes. A response built in memory (tests, cached
    content) has no stream left to read; real network responses always do."""
    if resp.is_stream_consumed:
        yield resp.content
        return
    async for chunk in resp.aiter_raw():
        yield chunk


# ── Fetching ──────────────────────────────────────────────────────────────


@dataclass
class FetchedPage:
    final_url: str
    content_type: str
    text: str
    truncated: bool = False


def _pinned(parts, ip: str) -> tuple[str, dict, dict]:
    """(URL aimed at the vetted IP, headers, request extensions)."""
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_host}:{parts.port}" if parts.port else ip_host
    target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = parts.hostname + (f":{parts.port}" if parts.port else "")
    headers = {
        "Host": host_header,
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,"
        "application/json;q=0.8,*/*;q=0.1",
        "Accept-Language": "en;q=1.0, *;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    }
    extensions = {"sni_hostname": parts.hostname} if parts.scheme == "https" else {}
    return target, headers, extensions


async def _fetch(
    url: str, client: httpx.AsyncClient, resolver: Resolver, accept: frozenset[str]
) -> FetchedPage:
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        parts = _validated(current)
        ip = await _vetted_ip(parts.hostname, resolver)
        target, headers, extensions = _pinned(parts, ip)
        async with client.stream(
            "GET", target, headers=headers, extensions=extensions
        ) as resp:
            if resp.status_code in _REDIRECT_STATUSES:
                location = resp.headers.get("location")
                if not location:
                    raise _error("http_error")
                current = urljoin(current, location)
                continue
            if resp.status_code in (404, 410):
                raise _error("not_found")
            if resp.status_code in (401, 402, 403):
                raise _error("paywall")
            if resp.status_code >= 400:
                raise _error("http_error")
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in accept:
                raise _error("unsupported_content")
            decoder = _BoundedDecoder(resp.headers.get("content-encoding", ""))
            body = bytearray()
            raw_total = 0
            truncated = False
            async for chunk in _raw_chunks(resp):
                raw_total += len(chunk)
                body += decoder.feed(chunk, MAX_BYTES - len(body))
                if len(body) >= MAX_BYTES or raw_total >= MAX_BYTES:
                    truncated = True
                    break
            encoding = resp.charset_encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return FetchedPage(current, ctype, text, truncated)
    raise _error("too_many_redirects")


async def fetch_url(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
    accept: frozenset[str] = PAGE_TYPES,
) -> FetchedPage:
    """GET ``url`` under the SSRF guards above. Raises LinkFetchError."""
    resolver = resolver or system_resolver
    _validated(url)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
        )
    try:
        return await asyncio.wait_for(
            _fetch(url, client, resolver, accept), TIMEOUT_SECONDS
        )
    except LinkFetchError:
        raise
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise _error("timeout") from exc
    except httpx.HTTPError as exc:
        raise _error("unreachable") from exc
    finally:
        if own_client:
            await client.aclose()


# ── Extraction ────────────────────────────────────────────────────────────

_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "button",
    "select",
)
_TEXT_TAGS = ("h1", "h2", "h3", "h4", "p", "li", "blockquote", "figcaption", "dt", "dd")
_LD_PLACE_TYPES = {
    "Place",
    "TouristAttraction",
    "TouristDestination",
    "LandmarksOrHistoricalBuildings",
    "Restaurant",
    "FoodEstablishment",
    "BarOrPub",
    "CafeOrCoffeeShop",
    "Museum",
    "Park",
    "LodgingBusiness",
    "Hotel",
    "City",
}


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _meta(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        if tag and _clean(tag.get("content")):
            return _clean(tag.get("content"))
    return ""


def _ld_types(node: dict) -> set[str]:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t} if isinstance(t, str) else set()


def _ld_place_line(node: dict) -> str:
    name = _clean(node.get("name") if isinstance(node.get("name"), str) else "")
    if not name:
        return ""
    address = node.get("address")
    locality = ""
    if isinstance(address, dict):
        locality = _clean(address.get("addressLocality") or "")
    elif isinstance(address, str):
        locality = _clean(address)
    desc = node.get("description")
    line = f"- {name}" + (f" ({locality})" if locality else "")
    if isinstance(desc, str) and _clean(desc):
        line += f": {_clean(desc)[:200]}"
    return line


def _walk_ld(node, lines: list[str], author: list[str], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(node, list):
        for item in node:
            _walk_ld(item, lines, author, depth + 1)
        return
    if not isinstance(node, dict):
        return
    types = _ld_types(node)
    if "@graph" in node:
        _walk_ld(node["@graph"], lines, author, depth + 1)
    body = node.get("articleBody")
    if isinstance(body, str) and _clean(body):
        lines.append(_clean(body))
    if isinstance(node.get("author"), dict) and node["author"].get("name"):
        author.append(_clean(str(node["author"]["name"])))
    elif isinstance(node.get("author"), list):
        for a in node["author"]:
            if isinstance(a, dict) and a.get("name"):
                author.append(_clean(str(a["name"])))
    if "ItemList" in types:
        for el in node.get("itemListElement") or []:
            if not isinstance(el, dict):
                continue
            inner = el.get("item") if isinstance(el.get("item"), dict) else el
            line = _ld_place_line(inner) or _ld_place_line(el)
            if line:
                lines.append(line)
    elif types & _LD_PLACE_TYPES:
        line = _ld_place_line(node)
        if line:
            lines.append(line)
    for key in ("mainEntity", "about", "hasPart", "itinerary", "containsPlace"):
        if key in node:
            _walk_ld(node[key], lines, author, depth + 1)


_CONTENT_CLASS = re.compile(
    r"entry-content|post-content|post-body|article-body|article-content|"
    r"story-body|blog-post|single-post|main-content",
    re.IGNORECASE,
)


def _text_len(el) -> int:
    return len(_clean(el.get_text(" ")))


def _content_root(soup: BeautifulSoup):
    """The element holding the article: the biggest of <article>, <main> and
    the usual blog content containers — a teaser <article> in a sidebar must
    not win — or the whole body when none holds most of the page's text."""
    body = soup.body or soup
    candidates = [
        *soup.find_all("article"),
        *soup.find_all("main"),
        *soup.find_all(attrs={"role": "main"}),
        *soup.find_all(attrs={"itemprop": "articleBody"}),
        *soup.find_all(class_=_CONTENT_CLASS),
    ]
    if not candidates:
        return body
    best = max(candidates, key=_text_len)
    best_len, body_len = _text_len(best), _text_len(body)
    if best_len < 1500 and body_len > 3 * best_len:
        return body
    return best


def _main_text(soup: BeautifulSoup) -> str:
    root = _content_root(soup)
    lines: list[str] = []
    for el in root.find_all(_TEXT_TAGS):
        # Only the innermost text block counts (a <li> holding a <p> once)
        if el.find(_TEXT_TAGS):
            continue
        text = _clean(el.get_text(" "))
        if not text:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            line = f"## {text}"
        elif el.name == "li":
            line = f"- {text}"
        else:
            line = text
        if not lines or lines[-1] != line:
            lines.append(line)
    if not lines:
        text = _clean(root.get_text(" "))
        if text:
            lines.append(text)
    return "\n".join(lines)


def extract_page(html: str, base_url: str) -> dict:
    """Title, site name, description, author, favicon and readable text of a
    page. ``text`` keeps headings ("## …") and list items ("- …"), because
    itineraries are usually lists; it is capped at MAX_TEXT_CHARS."""
    soup = BeautifulSoup(html, "html.parser")

    ld_lines: list[str] = []
    ld_author: list[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            _walk_ld(
                json.loads(tag.string or tag.get_text() or ""), ld_lines, ld_author
            )
        except (ValueError, TypeError):
            continue

    title = _meta(soup, "og:title", "twitter:title") or _clean(
        soup.title.get_text() if soup.title else ""
    )
    description = _meta(soup, "og:description", "twitter:description", "description")
    site_name = _meta(soup, "og:site_name", "application-name")
    author = _meta(soup, "author", "article:author") or (
        ld_author[0] if ld_author else ""
    )

    host = urlsplit(base_url).hostname or ""
    icon = soup.find(
        "link",
        rel=lambda r: r and "icon" in (r if isinstance(r, list) else r.split()),
    )
    favicon = (
        urljoin(base_url, icon["href"])
        if icon and icon.get("href")
        else urljoin(base_url, "/favicon.ico")
    )
    if not favicon.startswith(("http://", "https://")):
        favicon = ""

    for tag in soup(_DROP_TAGS):
        tag.decompose()
    main = _main_text(soup)

    sections = []
    if ld_lines:
        sections.append("\n".join(dict.fromkeys(ld_lines)))
    if main:
        sections.append(main)
    text = "\n\n".join(sections)[:MAX_TEXT_CHARS]

    return {
        "title": title[:300],
        "site_name": site_name[:120] or re.sub(r"^www\.", "", host),
        "description": description[:1000],
        "author": author[:120],
        "favicon_url": favicon,
        "text": text,
    }


# ── Reading a link (pages, YouTube, TikTok, blocked platforms) ───────────


@dataclass
class LinkContent:
    url: str
    final_url: str
    title: str
    site_name: str
    description: str
    author: str
    favicon_url: str
    text: str
    truncated: bool = False

    def as_source_text(self) -> str:
        """Everything the extraction agent should read, labelled."""
        parts = []
        if self.title:
            parts.append(f"TITLE: {self.title}")
        if self.author:
            parts.append(f"BY: {self.author}")
        if self.description:
            parts.append(f"DESCRIPTION: {self.description}")
        if self.text:
            parts.append(self.text)
        return "\n\n".join(parts)[:MAX_TEXT_CHARS]


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _platform(host: str) -> str | None:
    for domain in ("youtube.com", "youtu.be", "youtube-nocookie.com"):
        if _host_matches(host, domain):
            return "youtube"
    if _host_matches(host, "tiktok.com"):
        return "tiktok"
    return None


def blocked_source(url: str) -> str | None:
    """The platform name when ``url`` is on a site that blocks apps."""
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        return None
    for domain, name in _BLOCKED_SOURCES.items():
        if _host_matches(host, domain):
            return name
    return None


def _youtube_watch_url(url: str) -> str:
    """youtu.be/<id> and /shorts/<id> → the canonical watch page."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    video_id = ""
    if host == "youtu.be":
        video_id = parts.path.strip("/").split("/")[0]
    elif parts.path.startswith(("/shorts/", "/live/", "/embed/")):
        video_id = parts.path.split("/")[2] if len(parts.path.split("/")) > 2 else ""
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id or ""):
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


async def _oembed(
    endpoint: str, url: str, client: httpx.AsyncClient | None, resolver: Resolver
) -> dict:
    page = await fetch_url(
        f"{endpoint}?format=json&url={quote(url, safe='')}",
        client=client,
        resolver=resolver,
        accept=JSON_TYPES,
    )
    try:
        data = json.loads(page.text)
    except ValueError as exc:
        raise _error("http_error") from exc
    return data if isinstance(data, dict) else {}


async def _read_video(
    url: str, platform: str, client: httpx.AsyncClient | None, resolver: Resolver
) -> LinkContent:
    if platform == "youtube":
        endpoint, site, favicon = (
            "https://www.youtube.com/oembed",
            "YouTube",
            "https://www.youtube.com/favicon.ico",
        )
    else:
        endpoint, site, favicon = (
            "https://www.tiktok.com/oembed",
            "TikTok",
            "https://www.tiktok.com/favicon.ico",
        )
    data = await _oembed(endpoint, url, client, resolver)
    title = _clean(str(data.get("title") or ""))
    author = _clean(str(data.get("author_name") or ""))
    description = ""
    if platform == "youtube":
        # oEmbed has no description; the watch page's metadata usually does
        try:
            page = await fetch_url(
                _youtube_watch_url(url), client=client, resolver=resolver
            )
            info = await asyncio.to_thread(extract_page, page.text, page.final_url)
            description = info["description"]
        except LinkFetchError:
            description = ""
    text = "\n".join(p for p in (title, description) if p)
    return LinkContent(
        url=url,
        final_url=url,
        title=title,
        site_name=site,
        description=description,
        author=author,
        favicon_url=favicon,
        text=text,
    )


async def read_link(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
) -> LinkContent:
    """Fetch ``url`` safely and return its readable content.

    Raises LinkFetchError — ``blocked_source`` for Instagram, Facebook, X and
    Threads, which don't let apps read posts."""
    resolver = resolver or system_resolver
    url = url.strip()
    platform_name = blocked_source(url)
    if platform_name:
        raise LinkFetchError(
            "blocked_source",
            f"{platform_name} doesn't let apps read posts. Paste the caption "
            "or drop a screenshot instead.",
        )
    parts = _validated(url)
    platform = _platform(parts.hostname.lower())
    if platform:
        return await _read_video(url, platform, client, resolver)

    page = await fetch_url(url, client=client, resolver=resolver)
    if page.content_type == "text/plain":
        info = {
            "title": "",
            "site_name": re.sub(r"^www\.", "", urlsplit(page.final_url).hostname or ""),
            "description": "",
            "author": "",
            "favicon_url": "",
            "text": page.text[:MAX_TEXT_CHARS],
        }
    else:
        # bs4 on a 2 MB page takes a while: keep it off the event loop
        info = await asyncio.to_thread(extract_page, page.text, page.final_url)
    return LinkContent(
        url=url, final_url=page.final_url, truncated=page.truncated, **info
    )
