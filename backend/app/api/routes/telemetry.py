"""Product telemetry ingestion (``POST /api/telemetry``).

Anonymous-friendly and never an AI route. Every event passes the closed
registry in ``app.telemetry.registry``; anything invalid is dropped silently,
so a well-formed batch always answers 204.
"""

import asyncio
import json
import time
import zlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...core.auth import get_optional_user
from ...core.config import settings
from ...db import telemetry_db
from ...telemetry.registry import clean_client, clean_event, valid_id

router = APIRouter()

MAX_BODY_BYTES = 64 * 1024
MAX_DECOMPRESSED_BYTES = 256 * 1024
MAX_EVENTS = 100


def _too_big() -> HTTPException:
    return HTTPException(status_code=413, detail="Telemetry batch too large")


def _bad() -> HTTPException:
    return HTTPException(status_code=422, detail="Malformed telemetry batch")


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_big()
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            raise _too_big()
    raw = bytes(raw)
    encoding = request.headers.get("content-encoding", "").strip().lower()
    if encoding in ("", "identity"):
        return raw
    if encoding != "gzip":
        raise _bad()
    d = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(raw, MAX_DECOMPRESSED_BYTES + 1)
    except zlib.error:
        raise _bad() from None
    if len(out) > MAX_DECOMPRESSED_BYTES:
        raise _too_big()
    return out


@router.post("/telemetry", status_code=204)
async def ingest_telemetry(
    request: Request, user: dict | None = Depends(get_optional_user)
) -> Response:
    if not settings.telemetry_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    body = await _read_body(request)
    try:
        data = json.loads(body)
    except ValueError:
        raise _bad() from None
    if not isinstance(data, dict):
        raise _bad()
    events = data.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise _bad()
    client = clean_client(data.get("client"))
    if client is None:
        raise _bad()

    received_at = int(time.time() * 1000)
    user_id = str(user["id"]) if user and user.get("id") is not None else None
    rows = []
    for raw in events:
        ev = clean_event(raw)
        if ev is None:
            continue
        screen = raw.get("screen")
        rows.append(
            {
                **client,
                "ts": ev["ts"],
                "received_at": received_at,
                "event": ev["event"],
                "user_id": user_id,
                "screen": screen if valid_id(screen) else None,
                "props": json.dumps(ev["props"], separators=(",", ":")),
            }
        )
    if rows:
        await asyncio.to_thread(telemetry_db.insert_events, rows)
    return Response(status_code=204)
