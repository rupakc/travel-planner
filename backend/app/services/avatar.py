"""Avatars: validate and resize uploads to a 256 px WebP, store one file per
user under ``$DATA_DIR/avatars``, and best-effort import of a provider photo."""

import asyncio
import io
import logging
import os
import uuid
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..core.config import settings
from ..core.errors import ApiError
from ..core.urls import public_url
from ..db import users_db

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 40_000_000

MAX_BYTES = 2 * 1024 * 1024
SIZE = 256
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
    bad_type = ApiError(415, "avatar_type", "Use a JPEG, PNG, WebP or GIF image.")
    if ctype not in ALLOWED_TYPES:
        raise bad_type
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in ALLOWED_FORMATS:
                raise bad_type
            img.seek(0)
            img = ImageOps.exif_transpose(img)
            img.load()
            has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
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
        raise bad_type
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
