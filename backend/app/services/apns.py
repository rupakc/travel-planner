"""Push to the iOS app over APNs (token-based provider auth, HTTP/2).

Active when the team id, key id, a .p8 key (``APNS_KEY_P8`` inline or
``APNS_KEY_FILE``) are all set; inert otherwise. The ES256 provider token is
cached ~50 minutes (Apple wants 20-60). Never raises into callers; tokens
Apple says are dead are pruned; tokens are only ever logged masked.
"""

import asyncio
import logging
import time

import httpx
import jwt

from ..core.config import settings
from ..db import devices_db
from ..db.devices_db import masked

logger = logging.getLogger(__name__)

HOST = "https://api.push.apple.com"
SANDBOX_HOST = "https://api.sandbox.push.apple.com"
TIMEOUT_SECONDS = 10
TOKEN_TTL = 50 * 60
QUIET_KINDS = frozenset({"watch_expired", "watch_error"})
DEAD_REASONS = frozenset({"BadDeviceToken", "Unregistered"})

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport
_provider: dict = {}  # cached {"token", "issued_at", "key"}


def _key() -> str:
    if settings.apns_key_p8:
        return settings.apns_key_p8.replace("\\n", "\n")
    if settings.apns_key_file:
        try:
            with open(settings.apns_key_file, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""
    return ""


def configured() -> bool:
    return bool(settings.apns_team_id and settings.apns_key_id and _key())


def reset() -> None:
    _provider.clear()


def provider_token(now: float | None = None) -> str:
    now = time.time() if now is None else now
    key = _key()
    if (
        _provider.get("key") == (key, settings.apns_key_id, settings.apns_team_id)
        and now - _provider["issued_at"] < TOKEN_TTL
    ):
        return _provider["token"]
    token = jwt.encode(
        {"iss": settings.apns_team_id, "iat": int(now)},
        key,
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )
    _provider.update(
        token=token,
        issued_at=now,
        key=(key, settings.apns_key_id, settings.apns_team_id),
    )
    return token


def _payload(title: str, body: str, data: dict) -> dict:
    extra = {str(k): str(v) for k, v in data.items() if v is not None}
    return {
        "aps": {"alert": {"title": title, "body": body}, "sound": "default"},
        **extra,
    }


async def _send_one(client: httpx.AsyncClient, auth: str, token: str, payload, prio):
    host = SANDBOX_HOST if settings.apns_sandbox else HOST
    try:
        r = await client.post(
            f"{host}/3/device/{token}",
            json=payload,
            headers={
                "authorization": f"bearer {auth}",
                "apns-topic": settings.apns_bundle_id,
                "apns-push-type": "alert",
                "apns-priority": prio,
            },
        )
    except httpx.HTTPError as exc:
        logger.warning("APNs push to %s failed: %s", masked(token), type(exc).__name__)
        return False
    if r.status_code == 200:
        return True
    try:
        reason = (r.json() or {}).get("reason", "")
    except (ValueError, AttributeError):
        reason = ""
    if r.status_code == 410 or reason in DEAD_REASONS:
        devices_db.delete_token(token)
        logger.info("APNs token %s is no longer valid; pruned", masked(token))
        return False
    if r.status_code == 403:
        _provider.clear()  # bad/expired provider token: mint a new one next time
    logger.warning(
        "APNs push to %s failed: HTTP %d %s", masked(token), r.status_code, reason
    )
    return False


async def send_tokens(
    tokens: list[str], title: str, body: str, data: dict[str, str]
) -> int:
    """Push to the given iOS tokens concurrently; returns how many Apple
    accepted. Never raises."""
    if not tokens or not configured():
        return 0
    try:
        auth = provider_token()
        payload = _payload(title, body, data)
        prio = "5" if data.get("kind") in QUIET_KINDS else "10"
        async with httpx.AsyncClient(
            transport=_transport, timeout=TIMEOUT_SECONDS, http2=_transport is None
        ) as client:
            sent = await asyncio.gather(
                *(_send_one(client, auth, t, payload, prio) for t in tokens)
            )
        return sum(sent)
    except Exception as exc:  # noqa: BLE001 — push never breaks the caller
        logger.warning("APNs push failed: %s", type(exc).__name__)
        return 0


async def send_to_user(
    username: str, title: str, body: str, data: dict[str, str]
) -> int:
    """Push to every iOS device of ``username``."""
    try:
        tokens = [t for t, p in devices_db.devices_for(username) if p == "ios"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("APNs lookup failed: %s", type(exc).__name__)
        return 0
    return await send_tokens(tokens, title, body, data)
