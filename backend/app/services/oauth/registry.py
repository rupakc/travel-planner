"""Provider lookup. Provider modules merge independently, so imports are lazy."""

from __future__ import annotations

import importlib

from app.services.oauth.base import OAuthProvider

PROVIDER_ORDER = ("apple", "google", "facebook", "github")

_overrides: dict[str, OAuthProvider | None] = {}


def get_provider(provider_id: str) -> OAuthProvider | None:
    if provider_id in _overrides:
        return _overrides[provider_id]
    if provider_id not in PROVIDER_ORDER:
        return None
    try:
        module = importlib.import_module(f"app.services.oauth.{provider_id}")
    except ImportError:
        return None
    return getattr(module, "PROVIDER", None)


def override(provider_id: str, provider: OAuthProvider | None) -> None:
    """Test hook; pass None to make the provider look absent."""
    _overrides[provider_id] = provider


def clear_overrides() -> None:
    _overrides.clear()
