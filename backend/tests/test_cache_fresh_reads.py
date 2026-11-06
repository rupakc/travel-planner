"""``core.cache.fresh_reads``: the view "Check now" looks through."""

import asyncio

import pytest

from app.core.cache import fresh_reads, get_cache


@pytest.fixture(autouse=True)
def _clear():
    get_cache().clear()
    yield
    get_cache().clear()


def test_outside_the_block_the_cache_is_the_shared_one():
    get_cache()["k"] = 1
    assert "k" in get_cache() and get_cache()["k"] == 1


def test_old_entries_are_misses_and_new_ones_hits_and_shared():
    get_cache()["old"] = "stale"
    with fresh_reads():
        cache = get_cache()
        assert "old" not in cache
        assert cache.get("old") is None and cache.get("old", 0) == 0
        with pytest.raises(KeyError):
            cache["old"]
        cache["old"] = "fresh"  # a live answer refreshes the shared entry
        assert "old" in cache and cache["old"] == "fresh"
        assert get_cache().get("old") == "fresh"  # later reads in the block too
    assert get_cache()["old"] == "fresh"  # and everyone else afterwards


def test_each_block_starts_fresh():
    with fresh_reads():
        get_cache()["k"] = 1
    with fresh_reads():
        assert "k" not in get_cache()
    assert "k" in get_cache()


async def test_tasks_started_inside_inherit_the_view():
    get_cache()["k"] = "stale"

    async def look():
        return "k" in get_cache()

    with fresh_reads():
        assert await asyncio.create_task(look()) is False
    assert await asyncio.create_task(look()) is True
