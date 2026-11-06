"""SSE hygiene shared by /search and /chat: a keepalive comment whenever the
stream has been quiet for the interval, and every task the stream started
(agents, enrichment, nested tasks) cancelled when the client goes away."""

import asyncio
import contextvars

import pytest

from app.core.sse import guarded_stream


async def test_passes_chunks_through_and_ends():
    async def src():
        yield "data: 1\n\n"
        yield "data: 2\n\n"

    out = [c async for c in guarded_stream(src(), keepalive=5)]
    assert out == ["data: 1\n\n", "data: 2\n\n"]


async def test_quiet_periods_get_keepalive_comments():
    async def src():
        yield "data: a\n\n"
        await asyncio.sleep(0.25)
        yield "data: b\n\n"

    out = [c async for c in guarded_stream(src(), keepalive=0.1)]
    assert out[0] == "data: a\n\n" and out[-1] == "data: b\n\n"
    assert out.count(": keepalive\n\n") >= 1
    assert set(out[1:-1]) == {": keepalive\n\n"}


async def test_errors_from_the_source_propagate():
    async def src():
        yield "data: a\n\n"
        raise ValueError("boom")

    gen = guarded_stream(src(), keepalive=5)
    assert await gen.__anext__() == "data: a\n\n"
    with pytest.raises(ValueError, match="boom"):
        await gen.__anext__()


async def test_disconnect_cancels_every_task_the_stream_started():
    started = asyncio.Event()
    cancelled: list[str] = []

    async def agent(name):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(name)
            raise

    async def nested():
        inner = asyncio.create_task(agent("nested-child"))
        await inner

    async def src():
        tasks = [asyncio.create_task(agent(f"a{i}")) for i in range(3)]
        tasks.append(asyncio.create_task(nested()))
        started.set()
        yield "data: first\n\n"
        await asyncio.gather(*tasks)
        yield "data: never\n\n"

    gen = guarded_stream(src(), keepalive=5)
    assert await gen.__anext__() == "data: first\n\n"
    await started.wait()
    await asyncio.sleep(0)  # let the nested task start its child
    await gen.aclose()  # what Starlette does when the client disconnects
    assert sorted(cancelled) == ["a0", "a1", "a2", "nested-child"]


async def test_cancellation_of_the_consumer_also_cancels_the_agents():
    cancelled = []

    async def agent():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(1)
            raise

    async def src():
        t = asyncio.create_task(agent())
        yield "data: x\n\n"
        await t

    async def consume():
        async for _ in guarded_stream(src(), keepalive=5):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == [1]


async def test_tasks_outside_the_stream_are_left_alone():
    outside = asyncio.create_task(asyncio.sleep(60))

    async def src():
        yield "data: x\n\n"
        await asyncio.sleep(60)

    gen = guarded_stream(src(), keepalive=5)
    await gen.__anext__()
    await gen.aclose()
    assert not outside.cancelled()
    outside.cancel()


async def test_detached_tasks_survive_a_disconnect():
    """A task created with a fresh context (push.notify does this) is not
    part of the stream: an alert push must not die with the request."""
    done = asyncio.Event()

    async def push():
        await asyncio.sleep(0.05)
        done.set()

    async def src():
        loop = asyncio.get_running_loop()
        loop.create_task(push(), context=contextvars.Context())
        yield "data: x\n\n"
        await asyncio.sleep(60)

    gen = guarded_stream(src(), keepalive=5)
    await gen.__anext__()
    await gen.aclose()
    await asyncio.wait_for(done.wait(), 1)


async def test_tasks_finishing_normally_are_not_cancelled_after_the_end():
    survivors = []

    async def background():
        await asyncio.sleep(0.05)
        survivors.append(1)

    async def src():
        asyncio.create_task(background())
        yield "data: x\n\n"

    out = [c async for c in guarded_stream(src(), keepalive=5)]
    assert out == ["data: x\n\n"]
    await asyncio.sleep(0.1)
    assert survivors == [1]


# ── Wired into the routes ───────────────────────────────────────────────────


def test_search_route_streams_keepalives_while_agents_think(client, monkeypatch):
    import asyncio as _asyncio
    import json as _json

    from app.api.routes import search as search_route
    from app.core.config import settings

    class SlowOrchestrator:
        async def stream_run(self, request):
            yield 'data: {"type": "visa", "data": {}}\n\n'
            await _asyncio.sleep(0.3)
            yield _json.dumps({"type": "done"}).join(["data: ", "\n\n"])

    monkeypatch.setattr(settings, "sse_keepalive_seconds", 0.1)
    monkeypatch.setattr(search_route, "get_orchestrator", SlowOrchestrator)
    body = {
        "origin": "Berlin",
        "destination": "Keepalive City",
        "departure_date": "2027-03-01",
        "return_date": "2027-03-05",
        "nationality": "German",
    }
    r = client.post("/api/search", json=body)
    assert r.status_code == 200
    assert ": keepalive\n\n" in r.text
    assert r.text.rstrip().endswith('{"type": "done"}')
