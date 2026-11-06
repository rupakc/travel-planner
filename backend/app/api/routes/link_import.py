"""POST /api/import/extract — plan a trip from a link, pasted text or
screenshots. Returns an ImportPreview for the traveller to review; planning
then runs as a normal search with ``must_include``."""

import base64
import binascii
import hashlib
import io
import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from ...agents.link_import_agent import LinkImportAgent
from ...core import llm
from ...core.auth import get_current_user
from ...core.cache import get_cache
from ...core.config import settings
from ...schemas.link_import import (
    MAX_IMAGES,
    ImportPreview,
    ImportRequest,
    ResolvedPlace,
    ResolvePlaceRequest,
)
from ...services.link_fetch import LinkFetchError, read_link
from ...services.link_import import build_preview, resolve_one_place

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Anthropic's per-image limit applies to the base64 text, so check that too
# (kept on Gemini, whose inline request limit is far larger)
MAX_IMAGE_BASE64 = 5 * 1024 * 1024
_MIN_SOURCE_CHARS = 40

_agent: LinkImportAgent | None = None


def get_import_agent() -> LinkImportAgent:
    global _agent
    if _agent is None:
        _agent = LinkImportAgent(settings.agents_dir)
    return _agent


def _fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in (
        b"heic",
        b"heix",
        b"hevc",
        b"heim",
        b"heis",
        b"mif1",
        b"msf1",
    ):
        return "image/heic"
    return None


def _gif_to_png(data: bytes) -> bytes | None:
    """First frame of a GIF as PNG, or None when Pillow isn't installed."""
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(io.BytesIO(data)) as img:
        out = io.BytesIO()
        img.convert("RGBA").save(out, format="PNG")
        return out.getvalue()


def _checked_images(body: ImportRequest) -> list[dict]:
    images = body.images or []
    if len(images) > MAX_IMAGES:
        raise _fail(
            422,
            "too_many_images",
            f"Up to {MAX_IMAGES} screenshots at a time — remove a few and try again.",
        )
    checked = []
    for i, image in enumerate(images, start=1):
        if len(image.data_base64) > MAX_IMAGE_BASE64:
            raise _fail(
                422,
                "image_too_large",
                f"Screenshot {i} is too big to read. Crop it, or save it as a "
                "smaller PNG or JPEG.",
            )
        try:
            data = base64.b64decode(image.data_base64, validate=True)
        except (binascii.Error, ValueError):
            data = b""
        media_type = _sniff(data)
        declared = image.media_type.lower()
        if media_type == "image/heic" or declared in ("image/heic", "image/heif"):
            raise _fail(
                422,
                "heic_unsupported",
                "iPhone HEIC photos can't be read yet. Take a screenshot instead "
                "(screenshots are PNG), or export the photo as JPEG.",
            )
        if media_type is None:
            raise _fail(
                422,
                "unsupported_image",
                f"Screenshot {i} isn't an image we can read. Use PNG, JPEG or WebP.",
            )
        if len(data) > MAX_IMAGE_BYTES:
            raise _fail(
                422,
                "image_too_large",
                f"Screenshot {i} is over 5 MB. Crop it, or save it as a "
                "smaller PNG or JPEG.",
            )
        if media_type == "image/gif" and llm.provider() == "gemini":
            # Vertex AI reads PNG, JPEG and WebP but not GIF
            try:
                png = _gif_to_png(data)
            except Exception:
                png = None
            if png is None:
                raise _fail(
                    422,
                    "gif_unsupported",
                    f"Screenshot {i} is a GIF, which we can't read. Save it as "
                    "PNG or JPEG and try again.",
                )
            media_type, data = "image/png", png
        checked.append(
            {"media_type": media_type, "data_base64": base64.b64encode(data).decode()}
        )
    return checked


def _cache_key(body: ImportRequest) -> str:
    raw = json.dumps(body.model_dump(), sort_keys=True).encode()
    return "import:" + hashlib.sha256(raw).hexdigest()


@router.post("/import/extract", response_model=ImportPreview)
async def extract_trip(
    body: ImportRequest, user: dict = Depends(get_current_user)
) -> dict:
    kind = body.kind
    images = _checked_images(body) if kind == "images" else None

    cache = get_cache()
    key = _cache_key(body)
    if key in cache:
        return cache[key]

    agent = get_import_agent()
    source: dict = {"kind": kind}
    if kind == "url":
        try:
            content = await read_link(body.url)
        except LinkFetchError as exc:
            raise _fail(422, exc.code, exc.message) from exc
        source.update(
            url=body.url.strip(),
            title=content.title or None,
            site_name=content.site_name or None,
            favicon_url=content.favicon_url or None,
            author=content.author or None,
        )
        text = content.as_source_text()
        if len(content.text.strip()) + len(content.description) < _MIN_SOURCE_CHARS:
            raise _fail(
                422,
                "empty_page",
                "We couldn't read any text on that page. Paste the part of the "
                "article with the places, or drop a screenshot instead.",
            )
        result = await agent.run(text=text, source_kind="url")
    elif kind == "text":
        result = await agent.run(text=body.text.strip(), source_kind="text")
    else:
        result = await agent.run(images=images, source_kind="images")

    if paused := llm.user_error(result):
        raise _fail(503, paused["error_code"], paused["error"])
    if result.get("error"):
        logger.warning("Link import extraction failed: %s", result["error"])
        raise _fail(
            502,
            "extract_failed",
            "Our trip reader is busy right now. Give it a few seconds and try again.",
        )

    preview = await build_preview(result, source)
    if not preview["places"] and not preview["unresolved"]:
        raise _fail(
            422,
            "no_places",
            "We couldn't spot any places — try pasting the part of the article "
            "with the list.",
        )
    cache[key] = preview
    return preview


@router.post("/import/resolve-place", response_model=ResolvedPlace)
async def resolve_place_for_import(
    body: ResolvePlaceRequest, user: dict = Depends(get_current_user)
) -> dict:
    """Place one "Couldn't place" spot in the town the traveller typed."""
    resolved = await resolve_one_place(body.model_dump())
    if resolved is None:
        raise _fail(
            422,
            "city_not_found",
            f"We couldn't find a town called “{body.city}”. Check the spelling, "
            "or add the country (e.g. “Porto, Portugal”).",
        )
    return resolved
