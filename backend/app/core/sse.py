"""SSE hygiene for the long AI streams (``/api/search``, ``/api/chat``).

:func:`guarded_stream` wraps an SSE generator and

- sends a ``: keepalive`` comment whenever the stream has been quiet for
  ``keepalive`` seconds (default 15), so proxies (Caddy) and phone networks
  don't drop a connection while agents think, and a vanished client is
  noticed by the next failed write;
- when the client goes away before the stream ends (the response is
  cancelled or the generator closed), cancels **every task the stream
  started**, including nested ones (agents, enrichment, deferred agents), so
  they stop spending tokens and release the global LLM semaphore.

Tasks are attributed to a stream by a context variable read by a small task
factory installed on the event loop: a task belongs to the stream whose
context created it. A task created with a fresh ``contextvars.Context()``
(``push.notify``) is detached on purpose and survives. No agent code needs
to know about any of this.

:func:`active_streams` is the number of streams open right now. The VM's
deployer reads it (``GET /internal/streams``) and waits for 0, up to ~90 s,
before it recreates Caddy, which would cut every open stream.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

KEEPALIVE = ": keepalive\n\n"
CANCEL_WAIT_SECONDS = 2.0

_scope: contextvars.ContextVar[set | None] = contextvars.ContextVar(
    "voyager_stream_scope", default=None
)


def _install_task_factory(loop: asyncio.AbstractEventLoop) -> None:
    previous = loop.get_task_factory()
    if getattr(previous, "_voyager_scoped", False):
        return

    def factory(loop, coro, **kwargs):
        if previous is None:
            task = asyncio.Task(coro, loop=loop, **kwargs)
        else:
            task = previous(loop, coro, **kwargs)
        ctx = kwargs.get("context")
        scope = ctx.get(_scope) if ctx is not None else _scope.get()
        if scope is not None:
            scope.add(task)
            task.add_done_callback(scope.discard)
        return task

    factory._voyager_scoped = True  # type: ignore[attr-defined]
    loop.set_task_factory(factory)


class _Failure:
    def __init__(self, exc: BaseException):
        self.exc = exc


_END = object()

_active = 0


def active_streams() -> int:
    """Streams currently open on this process (one uvicorn worker)."""
    return _active


async def guarded_stream(
    source: AsyncIterator[str], *, keepalive: float = 15.0
) -> AsyncIterator[str]:
    global _active
    loop = asyncio.get_running_loop()
    _install_task_factory(loop)
    scope: set[asyncio.Task] = set()
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        try:
            async for chunk in source:
                await queue.put(chunk)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 — re-raised by the reader
            await queue.put(_Failure(exc))
            return
        finally:
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except BaseException:  # noqa: BLE001
                    pass
        await queue.put(_END)

    token = _scope.set(scope)
    try:
        pump_task = loop.create_task(pump())
    finally:
        _scope.reset(token)

    finished = False
    _active += 1
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except TimeoutError:
                yield KEEPALIVE
                continue
            if item is _END:
                finished = True
                return
            if isinstance(item, _Failure):
                finished = True
                raise item.exc
            yield item
    finally:
        _active -= 1
        if not finished:
            pending = [t for t in (*scope, pump_task) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                logger.info("Client went away: cancelled %d task(s)", len(pending))
                await asyncio.wait(pending, timeout=CANCEL_WAIT_SECONDS)
