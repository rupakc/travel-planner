"""Avatars: validate and resize uploads to a 256 px WebP, store one file per
user under ``$DATA_DIR/avatars``, and best-effort import of a provider photo."""

import asyncio
import io
import logging
import os
import threading
import uuid
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from ..core.config import settings
from ..core.errors import ApiError
from ..core.urls import public_url
from ..db import users_db

logger = logging.getLogger(__name__)

# Pillow's own bomb guard at open (a warning, promoted to an error below)
Image.MAX_IMAGE_PIXELS = 40_000_000

MAX_BYTES = 2 * 1024 * 1024
SIZE = 256
# Most pixels we ever decode (after JPEG's draft scaling): 16 MP is 64 MB as
# RGBA, plenty for a 256 px avatar and safe on the 1 GB VM.
MAX_PIXELS = 16_000_000
# One decode at a time across uploads and provider imports. Acquired inside
# the worker thread (process_upload runs via asyncio.to_thread), so the event
# loop never waits on it.
_DECODE_SLOT = threading.BoundedSemaphore(1)
_REDUCE_MODES = {"L", "LA", "RGB", "RGBA"}
_ORIENT = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
PROVIDER_HOSTS = {
    "lh3.googleusercontent.com",
    "avatars.githubusercontent.com",
    "platform-lookaside.fbsbx.com",
    "graph.facebook.com",
}
_MAX_REDIRECTS = 3
_TIMEOUT = 5.0


def avatar_path(user_id: str) -> Path:
    return Path(settings.data_dir) / "avatars" / f"{user_id}.webp"


def _too_large() -> ApiError:
    return ApiError(
        413, "avatar_too_large", "That image is too big — use one under 2 MB."
    )


def _unreadable() -> ApiError:
    return ApiError(
        422, "avatar_unreadable", "We couldn't read that image — try another."
    )


def process_upload(data: bytes, content_type: str) -> bytes:
    if len(data) > MAX_BYTES:
        raise _too_large()
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_TYPES:
        raise _bad_type()
    with _DECODE_SLOT:
        return _decode(data)


def _bad_type() -> ApiError:
    return ApiError(415, "avatar_type", "Use a JPEG, PNG, WebP or GIF image.")


def _decode(data: bytes) -> bytes:
    """Decode to a 256 px WebP without ever holding a large full-size copy:
    JPEG decodes at reduced scale (draft), the size is checked from the
    header before any pixel is decoded, and the image is shrunk (reduce)
    before the orientation fix, colour conversion and crop."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in ALLOWED_FORMATS:
                raise _bad_type()
            img.seek(0)
            if img.format == "JPEG":
                img.draft(img.mode, (SIZE * 2, SIZE * 2))
            if img.width * img.height > MAX_PIXELS:
                raise _unreadable()
            has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
            img.load()
            # read after load: PNG keeps its eXIf chunk after the pixel data
            orientation = img.getexif().get(0x0112)
            if img.mode not in _REDUCE_MODES:
                img = img.convert("RGBA" if has_alpha else "RGB")
            factor = min(img.size) // (SIZE * 2)
            if factor > 1:
                img = img.reduce(factor)
            if orientation in _ORIENT:
                img = img.transpose(_ORIENT[orientation])
            img = img.convert("RGBA" if has_alpha else "RGB")
            side = min(img.size)
            left, top = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize(
                (SIZE, SIZE), Image.LANCZOS
            )
            out = io.BytesIO()
            img.save(out, "WEBP", quality=82)
            return out.getvalue()
    except ApiError:
        raise
    except UnidentifiedImageError:
        raise _bad_type()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _unreadable()
    except Exception:  # truncated, corrupt, anything Pillow chokes on
        raise _unreadable()


def save_avatar(user_id: str, webp: bytes, source: str) -> str:
    path = avatar_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{user_id}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(webp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    rev = users_db.set_avatar(user_id, source)
    return public_url(f"/api/avatars/{user_id}.webp?v={rev}")


def remove_avatar(user_id: str) -> None:
    avatar_path(user_id).unlink(missing_ok=True)
    users_db.set_avatar(user_id, None)


def _allowed_url(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and (p.hostname or "") in PROVIDER_HOSTS


async def _fetch(url: str) -> tuple[bytes, str] | None:
    async with httpx.AsyncClient(follow_redirects=False, timeout=_TIMEOUT) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            if not _allowed_url(url):
                return None
            async with client.stream("GET", url) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        return None
                    url = urljoin(url, loc)
                    continue
                if resp.status_code != 200:
                    return None
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                    return None
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_BYTES:
                        return None
                return bytes(buf), resp.headers.get("content-type", "")
    return None


async def import_provider_photo(user_id: str, url: str) -> bool:
    """Best effort: store the provider's profile photo; False on any failure."""
    try:
        if not _allowed_url(url):
            return False
        fetched = await asyncio.wait_for(_fetch(url), timeout=_TIMEOUT * 2)
        if not fetched:
            return False
        data, ctype = fetched
        webp = await asyncio.to_thread(process_upload, data, ctype)
        await asyncio.to_thread(save_avatar, user_id, webp, "provider")
        return True
    except Exception as exc:
        logger.info("avatar import failed: %s", type(exc).__name__)
        return False
