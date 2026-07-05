"""Failed search runs must never be cached (regression: one transient failure
was replayed verbatim from cache for 30 minutes on every retry)."""

import json

from app.api.routes.search import _is_cacheable_run


def _ev(payload):
    return f"data: {json.dumps(payload)}\n\n"


def test_clean_complete_run_is_cacheable():
    events = [
        _ev({"type": "flights", "data": {"results": [1]}}),
        _ev({"type": "hotels", "data": {"results": [1]}}),
        _ev({"type": "done"}),
    ]
    assert _is_cacheable_run(events)


def test_run_with_any_errored_section_is_not_cacheable():
    events = [
        _ev({"type": "flights", "data": {"results": [1]}}),
        _ev({"type": "hotels", "data": {"error": "rate limited"}}),
        _ev({"type": "done"}),
    ]
    assert not _is_cacheable_run(events)


def test_incomplete_run_is_not_cacheable():
    events = [_ev({"type": "flights", "data": {"results": [1]}})]
    assert not _is_cacheable_run(events)
