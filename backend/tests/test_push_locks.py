import asyncio
import gc

from app.services import push


def test_push_locks_do_not_outlive_their_loop():
    push.reset()

    async def use():
        push._locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())

    loop = asyncio.new_event_loop()
    loop.run_until_complete(use())
    assert len(push._locks) == 1
    loop.close()
    del loop
    gc.collect()
    assert len(push._locks) == 0
