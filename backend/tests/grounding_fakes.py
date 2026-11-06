"""Fake grounded Gemini replies (Search / Maps grounding metadata) for the
grounding tests: shaped like google-genai 2.34.0's response objects."""

from types import SimpleNamespace


def chunk(web=None, maps=None):
    return SimpleNamespace(web=web, maps=maps)


def web(uri, title, domain=None):
    return SimpleNamespace(uri=uri, title=title, domain=domain)


def maps(uri, title, place_id=None):
    return SimpleNamespace(uri=uri, title=title, place_id=place_id)


def support(text, chunks, start=None, end=None):
    return SimpleNamespace(
        segment=SimpleNamespace(text=text, start_index=start, end_index=end),
        grounding_chunk_indices=chunks,
    )


def grounded_reply(text, chunks=(), queries=(), supports=(), finish="STOP"):
    meta = SimpleNamespace(
        grounding_chunks=list(chunks),
        web_search_queries=list(queries),
        grounding_supports=list(supports),
    )
    return SimpleNamespace(
        text=text,
        candidates=[
            SimpleNamespace(
                finish_reason=SimpleNamespace(value=finish), grounding_metadata=meta
            )
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=40,
            candidates_token_count=30,
            thoughts_token_count=2,
            cached_content_token_count=0,
        ),
    )
