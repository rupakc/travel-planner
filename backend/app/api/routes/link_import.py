"""POST /api/import/extract — plan a trip from a link, pasted text or
screenshots. Returns an ImportPreview for the traveller to review; planning
then runs as a normal search with ``must_include``."""

import base64
import binascii
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from ...agents.link_import_agent import LinkImportAgent
from ...core.auth import get_current_user
from ...core.cache import get_cache
from ...core.config import settings
from ...schemas.link_import import MAX_IMAGES, ImportPreview, ImportRequest
from ...services.link_fetch import LinkFetchError, read_link
from ...services.link_import import build_preview

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_IMAGE_BYTES = 5 * 1024 * 1024
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
                f"Screenshot {i} isn't an image we can read. Use PNG, JPEG, "
                "WebP or GIF.",
            )
        if len(data) > MAX_IMAGE_BYTES:
            raise _fail(
                422,
                "image_too_large",
                f"Screenshot {i} is over 5 MB. Crop it, or save it as a "
                "smaller PNG or JPEG.",
            )
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
