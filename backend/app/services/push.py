"""Push alerts to the Android app over FCM HTTP v1.

Active when ``FCM_SERVICE_ACCOUNT_FILE`` points at a Firebase
service-account JSON key: the OAuth access token comes from a JWT signed
with that key (google-auth's signer, exchanged over httpx) and is cached
until shortly before it expires (key file read once: restart, or call
``reset()``, after rotating it). Without a key file, ``FCM_USE_ADC=true``
uses Application Default Credentials instead (on the VM: its service
account via the metadata server), with the project from ``FCM_PROJECT_ID``
or ``GOOGLE_CLOUD_PROJECT``. Never raises into callers: an alert is
already stored in-app when it is pushed, so push is best effort — tokens
FCM says are dead are pruned, everything else is logged, with tokens
masked to their last 6 characters.
"""

import asyncio
import contextvars
import datetime
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
from ..db.devices_db import masked

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
TIMEOUT_SECONDS = 10
TOKEN_LIFETIME = 3600
EXPIRY_MARGIN = 60  # refresh this long before Google's expiry
# Watch ended / on hold: worth knowing, not worth waking the phone for
QUIET_KINDS = frozenset({"watch_expired", "watch_error"})
DRAIN_SECONDS = 5  # shutdown waits this long for pushes in flight
ADC_EMAIL = "<adc>"  # cache key for the ADC token

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport
_access: dict = {}  # cached {"token", "expires_at", "email"}
# One token refresh at a time, so a burst of pushes shares one exchange (a
# lock per event loop: an asyncio.Lock can't cross loops)
_locks: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}
# Fire-and-forget pushes still running (a reference keeps them from being
# garbage-collected mid-flight)
_tasks: set[asyncio.Task] = set()


def _key_file_configured() -> bool:
    path = settings.fcm_service_account_file
    return bool(path) and os.path.isfile(path)


def _adc_project() -> str:
    return settings.fcm_project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")


def configured() -> bool:
    if _key_file_configured():
        return True
    return settings.fcm_use_adc and bool(_adc_project())


def reset() -> None:
    """Forget the cached access token and key file (tests, key rotation)."""
    global _adc_creds
    _access.clear()
    _locks.clear()
    _account.cache_clear()
    _adc_creds = None


_adc_creds = None  # google.auth credentials, created on first use


def _adc_credentials():
    import google.auth

    creds, _ = google.auth.default(scopes=[FCM_SCOPE])
    return creds


def _refresh_adc() -> tuple[str, float]:
    """Blocking: refresh the ADC token (metadata server); (token, expires_at)."""
    global _adc_creds
    from google.auth.transport.requests import Request

    if _adc_creds is None:
        _adc_creds = _adc_credentials()
    _adc_creds.refresh(Request())
    expiry = getattr(_adc_creds, "expiry", None)
    if expiry is not None:
        # google-auth expiries are naive UTC datetimes
        expires_at = expiry.replace(tzinfo=datetime.UTC).timestamp()
    else:
        expires_at = time.time() + TOKEN_LIFETIME
    return _adc_creds.token, expires_at - EXPIRY_MARGIN


async def _adc_access_token() -> str:
    if token := _cached(ADC_EMAIL):
        return token
    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        if token := _cached(ADC_EMAIL):
            return token
        token, expires_at = await loop.run_in_executor(None, _refresh_adc)
        _access.update(token=token, expires_at=expires_at, email=ADC_EMAIL)
        return token


@functools.lru_cache(maxsize=2)
def _account(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _cached(email: str) -> str | None:
    if _access.get("email") == email and _access.get("expires_at", 0) > time.time():
        return _access["token"]
    return None


async def _access_token(client: httpx.AsyncClient, account: dict) -> str:
    email = account["client_email"]
    if token := _cached(email):
        return token
    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        return _cached(email) or await _fetch_access_token(client, account)


async def _fetch_access_token(client: httpx.AsyncClient, account: dict) -> str:
    now = time.time()
    email = account["client_email"]
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


def _dead_token(r: httpx.Response) -> bool:
    """FCM says this token will never work: error code UNREGISTERED (sent
    with 404 or 400), or an INVALID_ARGUMENT whose BadRequest violation names
    ``message.token`` (a malformed token). A bare 404 (a wrong or deleted
    Firebase project) or any other error keeps the token."""
    try:
        error = r.json().get("error") or {}
        details = error.get("details") or []
    except (ValueError, AttributeError):
        return False
    for d in details:
        if not isinstance(d, dict):
            continue
        if d.get("errorCode") == "UNREGISTERED":
            return True
        if error.get("status") == "INVALID_ARGUMENT" and any(
            isinstance(v, dict) and v.get("field") == "message.token"
            for v in d.get("fieldViolations") or []
        ):
            return True
    return False


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
        logger.warning("Push to %s failed: %s", masked(token), type(exc).__name__)
        return False
    if r.status_code == 200:
        return True
    if _dead_token(r):
        devices_db.delete_token(token)
        logger.info("Push token %s is no longer valid; pruned", masked(token))
        return False
    if r.status_code == 401:
        _access.clear()  # revoked or rotated: fetch a fresh one next time
    logger.warning(
        "Push to %s failed: HTTP %d %s",
        masked(token),
        r.status_code,
        r.text[:200].replace(token, masked(token)),
    )
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
        if _key_file_configured():
            account = _account(settings.fcm_service_account_file)
            project_id = account["project_id"]
        else:
            account = None
            project_id = _adc_project()
        url = SEND_URL.format(project_id=project_id)
        # Data-only: the app always gets onMessageReceived, so it builds the
        # notification itself (channel, in-app toggle, seen-id dedupe, deep link)
        payload = {**data, "title": title, "body": body}
        message = {
            # FCM data values must be strings
            "data": {str(k): str(v) for k, v in payload.items() if v is not None},
            "android": {
                "priority": "normal" if data.get("kind") in QUIET_KINDS else "high"
            },
        }
        async with httpx.AsyncClient(
            transport=_transport, timeout=TIMEOUT_SECONDS
        ) as client:
            if account is not None:
                access = await _access_token(client, account)
            else:
                access = await _adc_access_token()
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
        if user and user.get("is_active"):
            await send_to_user(user["username"], title, body, data)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Push for notification %s crashed", data.get("notification_id")
        )


def notify(user_id: str, note: dict, link: str) -> None:
    """Push a just-created alert notification (a ``notifications`` row) in
    the background, so alert creation's latency and outcome never change.
    ``link`` is the web deep link used when the note carries none."""
    try:
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
        # A fresh context: the push is never part of the request that caused
        # it (an SSE stream cancels its own tasks when the client leaves)
        task = loop.create_task(
            _push(user_id, note["title"], note["body"], data),
            context=contextvars.Context(),
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception:  # noqa: BLE001 — never break the alert being created
        logger.exception("Push for notification %s not started", note.get("id"))


async def drain(timeout: float = DRAIN_SECONDS) -> None:
    """Shutdown: give pushes in flight ``timeout`` seconds, cancel the rest."""
    pending = set(_tasks)
    if not pending:
        return
    _, late = await asyncio.wait(pending, timeout=timeout)
    for task in late:
        task.cancel()
    if late:
        await asyncio.gather(*late, return_exceptions=True)
        logger.info("Shutdown: cancelled %d pending push(es)", len(late))
