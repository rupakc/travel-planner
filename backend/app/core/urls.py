"""Absolute URLs for emails and avatars."""

from .config import settings


def public_base_url() -> str:
    base = settings.public_base_url.strip() or settings.app_base_url.strip()
    return base.rstrip("/")


def public_url(path: str) -> str:
    return f"{public_base_url()}{path}"


def request_public_url(path: str, request=None) -> str:
    """Like :func:`public_url`, but with no ``PUBLIC_BASE_URL`` configured the
    request's own origin is used (never a relative or localhost-default URL)."""
    base = settings.public_base_url.strip()
    if not base and request is not None:
        base = str(request.base_url)
    return f"{(base or public_base_url()).rstrip('/')}{path}"
