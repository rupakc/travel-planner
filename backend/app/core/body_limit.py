"""Refuse oversized request bodies on chosen paths before the app reads them.

Pure ASGI, so it sees the body as it streams: a declared Content-Length over
the limit is refused at once, and a body without one (chunked) is counted as
it arrives and refused once it passes the limit. Accepted bodies are replayed
to the app unchanged.
"""

import json


class BodySizeLimit:
    def __init__(self, app, *, prefix: str, max_bytes: int, message: str) -> None:
        self.app = app
        self.prefix = prefix
        self.max_bytes = max_bytes
        self.message = message

    async def _refuse(self, send) -> None:
        body = json.dumps({"detail": self.message}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        try:
            declared = int(headers.get(b"content-length", b"0") or 0)
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            return await self._refuse(send)

        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                return await self._refuse(send)
            chunks.append(chunk)
            if not message.get("more_body"):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
