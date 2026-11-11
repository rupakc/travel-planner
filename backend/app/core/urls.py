"""Absolute URLs for emails and avatars."""

from .config import settings


def public_base_url() -> str:
    base = settings.public_base_url.strip() or settings.app_base_url.strip()
    return base.rstrip("/")


def public_url(path: str) -> str:
    return f"{public_base_url()}{path}"
