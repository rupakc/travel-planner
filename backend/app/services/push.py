"""Push alerts to the Android app over FCM HTTP v1.

Active only when ``FCM_SERVICE_ACCOUNT_FILE`` points at a Firebase
service-account JSON key. The OAuth access token comes from a JWT signed
with that key (google-auth's signer, exchanged over httpx) and is cached
until shortly before it expires. Never raises into callers: an alert is
already stored in-app when it is pushed, so push is best effort — dead
tokens (404 / UNREGISTERED) are pruned, everything else is logged.
"""

import asyncio
import functools
import json
import logging
import os
import time

import httpx
from google.auth import crypt
from google.auth import jwt as google_jwt

from ..core.config import settings
from ..db import devices_db

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
TIMEOUT_SECONDS = 10
TOKEN_LIFETIME = 3600
EXPIRY_MARGIN = 60  # refresh this long before Google's expiry

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport
_access: dict = {}  # cached {"token", "expires_at", "email"}
# Fire-and-forget pushes still running (a reference keeps them from being
# garbage-collected mid-flight)
_tasks: set[asyncio.Task] = set()


def configured() -> bool:
    path = settings.fcm_service_account_file
    return bool(path) and os.path.isfile(path)


def reset() -> None:
    """Forget the cached access token and key file (tests, key rotation)."""
    _access.clear()
    _account.cache_clear()


@functools.lru_cache(maxsize=2)
def _account(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def _access_token(client: httpx.AsyncClient, account: dict) -> str:
    now = time.time()
    email = account["client_email"]
    if _access.get("email") == email and _access.get("expires_at", 0) > now:
        return _access["token"]
    token_uri = account.get("token_uri") or DEFAULT_TOKEN_URI
    signer = crypt.RSASigner.from_service_account_info(account)
    assertion = google_jwt.encode(
        signer,
        {
            "iss": email,
            "scope": FCM_SCOPE,
            "aud": token_uri,
            "iat": int(now),
            "exp": int(now) + TOKEN_LIFETIME,
        },
    ).decode()
    r = await client.post(
        token_uri,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )
    r.raise_for_status()
    body = r.json()
    lifetime = int(body.get("expires_in") or TOKEN_LIFETIME)
    _access.update(
        token=body["access_token"],
        expires_at=now + lifetime - EXPIRY_MARGIN,
        email=email,
    )
    return _access["token"]


def _unregistered(r: httpx.Response) -> bool:
    if r.status_code == 404:
        return True
    try:
        details = r.json().get("error", {}).get("details") or []
    except ValueError:
        return False
    return any(d.get("errorCode") == "UNREGISTERED" for d in details)


async def _send_one(
    client: httpx.AsyncClient, url: str, access: str, token: str, message: dict
) -> bool:
    try:
        r = await client.post(
            url,
            json={"message": {**message, "token": token}},
            headers={"Authorization": f"Bearer {access}"},
        )
    except httpx.HTTPError as exc:
        logger.warning("Push send failed: %s", type(exc).__name__)
        return False
    if r.status_code == 200:
        return True
    if _unregistered(r):
        devices_db.delete_token(token)
        logger.info("Push token unregistered; pruned …%s", token[-6:])
        return False
    if r.status_code == 401:
        _access.clear()  # revoked or rotated: fetch a fresh one next time
    logger.warning("Push send failed: HTTP %d %s", r.status_code, r.text[:200])
    return False


async def send_to_user(
    username: str, title: str, body: str, data: dict[str, str]
) -> int:
    """Push one notification to every device of ``username``, concurrently.
    Returns how many FCM accepted; never raises."""
    if not configured():
        return 0
    try:
        tokens = devices_db.tokens_for(username)
        if not tokens:
            return 0
        account = _account(settings.fcm_service_account_file)
        url = SEND_URL.format(project_id=account["project_id"])
        message = {
            "notification": {"title": title, "body": body},
            # FCM data values must be strings
            "data": {str(k): str(v) for k, v in data.items() if v is not None},
            "android": {"priority": "high"},
        }
        async with httpx.AsyncClient(
            transport=_transport, timeout=TIMEOUT_SECONDS
        ) as client:
            access = await _access_token(client, account)
            sent = await asyncio.gather(
                *(_send_one(client, url, access, t, message) for t in tokens)
            )
        return sum(sent)
    except Exception as exc:  # noqa: BLE001 — push never breaks the caller
        logger.warning("Push to %s failed: %s: %s", username, type(exc).__name__, exc)
        return 0


async def _push(user_id: str, title: str, body: str, data: dict[str, str]) -> None:
    try:
        from ..db.users_db import get_user_by_id

        user = get_user_by_id(user_id)
        if user:
            await send_to_user(user["username"], title, body, data)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Push for notification %s crashed", data.get("notification_id")
        )


def notify(user_id: str, note: dict, link: str) -> None:
    """Push a just-created alert notification (a ``notifications`` row) in
    the background, so alert creation's latency and outcome never change.
    ``link`` is the web deep link used when the note carries none."""
    if not configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (sync caller): nothing to push from
        return
    extra = note.get("data") or {}
    data = {
        "kind": note["kind"],
        "notification_id": str(note["id"]),
        "link": (extra.get("links") or {}).get("alerts") or link,
    }
    for key in ("watch_id", "watch_kind"):
        if extra.get(key) is not None:
            data[key] = str(extra[key])
    task = loop.create_task(_push(user_id, note["title"], note["body"], data))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
