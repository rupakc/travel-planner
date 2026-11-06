"""The one seam between the app and a language model.

``LLM_PROVIDER`` picks Gemini on Vertex AI (default; Application Default
Credentials, no API key) or Anthropic (local dev / rollback). Callers pass
Anthropic-style messages — ``{"role": "user"|"assistant", "content": ...}``
where content is a string or a list of text / base64-image blocks — and a
role: ``agent`` (specialists, routing, extraction: the cheap model) or
``chat`` (conversational answers and narrative). This module maps them per
provider, logs token usage per call (never content) and turns every provider
error into :class:`LLMError`.
"""

import base64
import contextvars
import logging
import re
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing, contextmanager
from dataclasses import dataclass, field
from typing import Literal

from .config import settings

logger = logging.getLogger(__name__)

Role = Literal["agent", "chat"]

ANTHROPIC_MODELS = {"agent": "claude-haiku-4-5-20251001", "chat": "claude-sonnet-4-6"}

# Shown wherever an AI feature pauses because the monthly spend cap tripped.
SPEND_CAP_MESSAGE = "AI limit reached for this month — try again on the 1st."
SPEND_CAP_CODE = "ai_limit"
# Billing switched off for the project (not the cap: it won't reset by itself).
BILLING_MESSAGE = (
    "AI features are unavailable right now: billing is disabled for the AI "
    "service. Please try again later."
)
BILLING_CODE = "ai_billing"
# Errors users see as-is (sections, chat deltas, route details)
USER_ERROR_CODES = {SPEND_CAP_CODE, BILLING_CODE}
# Google Search / Maps grounding exists only on Gemini (Vertex AI): the
# grounded routes answer 503 with this on the Anthropic provider.
GROUNDING_UNAVAILABLE_CODE = "grounding_unavailable"
GROUNDING_UNAVAILABLE_MESSAGE = "Live web and map results need the Gemini provider."

# Gemini 3.7 / 3.8 Flash reject thinking level MINIMAL (3.5 / 3.6 Flash and Flash-Lite accept it)
_NO_MINIMAL = re.compile(r"^gemini-3\.[78]-flash$")
# Per-request ceiling for Gemini calls (the SDK default is no timeout at all)
_GEMINI_TIMEOUT_S = 120
# The IATA fallback runs during request validation on the event-loop thread:
# keep it short and never retry, so a stalled call can't freeze the server.
_SYNC_TIMEOUT_S = 8

# Gemini counts thinking tokens against max_output_tokens: headroom keeps a
# reply sized for the old Claude budget from being cut short by reasoning.
# Only generated tokens are billed, so unused headroom costs nothing.
_THINKING_HEADROOM = {"minimal": 512, "low": 2048, "medium": 4096, "high": 8192}

# Google documents no API error for a tripped spend cap (only "usage is
# paused"), so a 403/429 whose *message* (not the help links / metadata in
# the details) names billing or a budget counts as one; a bare 429
# RESOURCE_EXHAUSTED stays a retryable quota error. A BILLING_DISABLED
# reason is reported separately. Anthropic's equivalents are a 400 "credit
# balance is too low" and the workspace usage limit ("You have reached your
# specified API usage limits. You will regain access on …"). A 400 needs the
# narrower hints ("thinking budget" is a bad request).
_SPEND_CAP_HINTS = {
    403: (
        "spend cap",
        "spending cap",
        "spend limit",
        "spending limit",
        "budget",
        "billing",
        "usage limit",
        "credit balance",
    ),
    400: (
        "credit balance",
        "spend limit",
        "spending limit",
        "spend cap",
        "usage limits",
        "regain access",
    ),
}
_SPEND_CAP_HINTS[429] = _SPEND_CAP_HINTS[403]
_SPEND_CAP_HINTS[402] = _SPEND_CAP_HINTS[403]
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504, 529}

# Once the cap is seen, fail fast for a while instead of sending every agent
# of every search into the same rejection.
_SPEND_CAP_HOLD_SECONDS = 300
_spend_cap_until = 0.0
_pause_code = SPEND_CAP_CODE

# Per-call usage records go here when a caller opened ``record_usage()``
# (the eval harness); asyncio tasks inherit the list from their creator.
_usage_sink: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "llm_usage_sink", default=None
)

_gemini = None
_anthropic_async = None
_anthropic_sync = None


@dataclass
class LLMResponse:
    text: str
    truncated: bool = False  # the reply hit the output-token cap
    usage: dict = field(default_factory=dict)


@dataclass
class GroundedResponse:
    """A grounded answer: the model's text plus what grounded it.

    ``chunks``: ``{"kind": "web"|"maps", "uri", "title", "place_id"}`` in the
    model's order (``supports`` index into this list). ``supports``:
    ``{"text", "start", "end", "chunks"}`` — a span of ``text`` and the
    chunks backing it. ``search_queries``: the web searches the model ran."""

    text: str
    chunks: list[dict] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    supports: list[dict] = field(default_factory=list)
    truncated: bool = False
    usage: dict = field(default_factory=dict)


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        user_code: str | None = None,
        status: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        # SPEND_CAP_CODE / BILLING_CODE: the message is meant for users
        self.user_code = user_code
        self.status = status

    @property
    def spend_cap(self) -> bool:
        return self.user_code == SPEND_CAP_CODE

    @property
    def user_facing(self) -> bool:
        return self.user_code is not None

    def as_result(self) -> dict:
        """The section/route payload for a user-facing error."""
        return {"error": str(self), "error_code": self.user_code}


def provider() -> str:
    return _resolve()[0]


def provider_reason() -> str:
    return _resolve()[1]


def log_provider() -> None:
    """Resolve the provider once at startup, check its config and say which
    one (and why). Raises RuntimeError on a model/thinking-level mismatch."""
    validate_config()
    name, reason = _resolve()
    logger.info(
        f"LLM provider: {name} ({reason}), agent={model_for('agent')}, "
        f"chat={model_for('chat')}"
    )


# LLM_PROVIDER=auto is resolved once per settings combination (the ADC
# lookup can take a moment); tests that change settings get a fresh answer.
_resolved: tuple[tuple, tuple[str, str]] | None = None


def _resolve() -> tuple[str, str]:
    global _resolved
    key = (
        settings.llm_provider,
        settings.gcp_project,
        bool(settings.anthropic_api_key),
    )
    if _resolved is not None and _resolved[0] == key:
        return _resolved[1]
    choice = settings.llm_provider.strip().lower()
    if choice in ("gemini", "anthropic"):
        result = (choice, f"LLM_PROVIDER={choice}")
    elif settings.gcp_project:
        result = ("gemini", "auto: GCP_PROJECT set")
    elif settings.anthropic_api_key:
        result = ("anthropic", "auto: ANTHROPIC_API_KEY set, no GCP_PROJECT")
    elif _adc_project():
        result = ("gemini", "auto: ADC project, no ANTHROPIC_API_KEY")
    else:
        result = ("anthropic", "auto: no GCP project found")
    _resolved = (key, result)
    return result


def _adc_project() -> str | None:
    """The project Application Default Credentials resolve to, if any."""
    try:
        import google.auth

        return google.auth.default()[1]
    except Exception:
        return None


def model_for(role: Role) -> str:
    if provider() == "anthropic":
        return ANTHROPIC_MODELS[role]
    return settings.gemini_model_chat if role == "chat" else settings.gemini_model_agent


def validate_config() -> None:
    """Fail fast on settings every Gemini call would reject (400s)."""
    if provider() != "gemini":
        return
    for role, model, level, var in (
        (
            "agent",
            settings.gemini_model_agent,
            settings.gemini_thinking_agent,
            "GEMINI_THINKING_AGENT",
        ),
        (
            "chat",
            settings.gemini_model_chat,
            settings.gemini_thinking_chat,
            "GEMINI_THINKING_CHAT",
        ),
    ):
        level = level.strip().lower()
        if level not in _THINKING_HEADROOM:
            raise RuntimeError(
                f"{var}={level!r} is not a thinking level "
                f"(use one of {', '.join(_THINKING_HEADROOM)})"
            )
        if level == "minimal" and _NO_MINIMAL.match(model):
            raise RuntimeError(
                f"{var}=minimal is rejected by {model} ({role} model): use low, "
                "medium or high"
            )


def spend_cap_active() -> bool:
    """True while AI calls are paused (spend cap or billing disabled)."""
    return time.monotonic() < _spend_cap_until


def pause_error() -> "LLMError":
    message = SPEND_CAP_MESSAGE if _pause_code == SPEND_CAP_CODE else BILLING_MESSAGE
    return LLMError(message, user_code=_pause_code)


def reset_spend_cap() -> None:
    global _spend_cap_until
    _spend_cap_until = 0.0


def spend_cap_error() -> dict:
    """The section/route payload for a paused AI feature (spend cap)."""
    return {"error": SPEND_CAP_MESSAGE, "error_code": SPEND_CAP_CODE}


def user_error(result) -> dict | None:
    """``result`` if it is a user-facing AI error payload (spend cap, billing)."""
    if isinstance(result, dict) and result.get("error_code") in USER_ERROR_CODES:
        return result
    return None


@contextmanager
def record_usage() -> Iterator[list[dict]]:
    sink: list[dict] = []
    token = _usage_sink.set(sink)
    try:
        yield sink
    finally:
        _usage_sink.reset(token)


# ── Public calls ──────────────────────────────────────────────────────


async def generate(
    messages: list[dict],
    *,
    role: Role = "agent",
    system: str | None = None,
    max_tokens: int = 4096,
    json_output: bool = False,
    label: str = "",
    timeout: float | None = None,
    retries: bool = True,
) -> LLMResponse:
    """One non-streaming call. Raises LLMError."""
    _check_spend_cap()
    started = time.monotonic()
    try:
        if provider() == "anthropic":
            client = _anthropic_client()
            if timeout is not None or not retries:
                client = client.with_options(
                    **({"timeout": timeout} if timeout is not None else {}),
                    **({} if retries else {"max_retries": 0}),
                )
            resp = await client.messages.create(
                **_anthropic_kwargs(role, system, messages, max_tokens)
            )
            out = _anthropic_response(resp)
        else:
            resp = await _gemini_client().aio.models.generate_content(
                **_gemini_kwargs(
                    role, system, messages, max_tokens, json_output, timeout, retries
                )
            )
            out = _gemini_response(resp)
    except LLMError:
        raise
    except Exception as e:
        raise _wrap(e) from e
    _log_usage(label, role, out, started)
    return out


async def stream(
    messages: list[dict],
    *,
    role: Role = "chat",
    system: str | None = None,
    max_tokens: int = 4096,
    label: str = "",
) -> AsyncIterator[str]:
    """Yield text deltas as the model produces them. Raises LLMError.

    A consumer that stops early (client disconnect) closes the HTTP stream;
    the tokens seen so far are still logged, marked ``aborted``."""
    _check_spend_cap()
    started = time.monotonic()
    out = LLMResponse(text="")
    finished = False
    try:
        if provider() == "anthropic":
            async with _anthropic_client().messages.stream(
                **_anthropic_kwargs(role, system, messages, max_tokens)
            ) as s:
                async for text in s.text_stream:
                    if text:
                        out.text += text
                        yield text
                final = await s.get_final_message()
                out = _anthropic_response(final)
        else:
            chunks = await _gemini_client().aio.models.generate_content_stream(
                **_gemini_kwargs(role, system, messages, max_tokens, False, None, True)
            )
            async with aclosing(chunks):
                async for chunk in chunks:
                    text = chunk.text or ""
                    if text:
                        out.text += text
                        yield text
                    # Usage and the finish reason ride on the last chunk
                    if getattr(chunk, "usage_metadata", None):
                        out.usage = _gemini_usage(chunk)
                    out.truncated = out.truncated or _gemini_truncated(chunk)
        finished = True
    except LLMError:
        raise
    except Exception as e:
        raise _wrap(e) from e
    finally:
        if finished or out.text:
            _log_usage(label, role, out, started, aborted=not finished)


def generate_sync(
    messages: list[dict],
    *,
    role: Role = "agent",
    system: str | None = None,
    max_tokens: int = 1024,
    json_output: bool = False,
    label: str = "",
    timeout: float = _SYNC_TIMEOUT_S,
) -> LLMResponse:
    """Blocking variant for sync code paths (IATA lookup fallback): a short
    timeout and no retries, as it blocks whatever thread calls it."""
    _check_spend_cap()
    started = time.monotonic()
    try:
        if provider() == "anthropic":
            global _anthropic_sync
            if _anthropic_sync is None:
                import anthropic

                _anthropic_sync = anthropic.Anthropic(
                    api_key=settings.anthropic_api_key
                )
            resp = _anthropic_sync.with_options(
                timeout=timeout, max_retries=0
            ).messages.create(**_anthropic_kwargs(role, system, messages, max_tokens))
            out = _anthropic_response(resp)
        else:
            resp = _gemini_client().models.generate_content(
                **_gemini_kwargs(
                    role, system, messages, max_tokens, json_output, timeout, False
                )
            )
            out = _gemini_response(resp)
    except LLMError:
        raise
    except Exception as e:
        raise _wrap(e) from e
    _log_usage(label, role, out, started)
    return out


GroundingTool = Literal["search", "maps"]


async def generate_grounded(
    prompt: str,
    *,
    tool: GroundingTool,
    system: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    language: str | None = None,
    max_tokens: int = 2048,
    label: str = "",
    timeout: float | None = None,
) -> GroundedResponse:
    """One Gemini call grounded with Google Search (``tool="search"``) or
    Google Maps (``tool="maps"``) on the agent model. Text output only:
    Google attaches grounding chunks reliably only to natural text (a rigid
    pipe format came back unattributed in real calls), so JSON mode is never
    combined with grounding; callers ask for headings / bullet lines, parse
    them and take links only from the grounding metadata. ``lat``/``lng``/``language`` bias results to the user.

    Raises LLMError: ``GROUNDING_UNAVAILABLE_CODE`` on the Anthropic
    provider, the spend-cap / billing codes like every other call. Google's
    terms bind what comes back: show it only to the user who asked, never
    store or cache it (docs/Trip-Planning-Features.md, "Live web check and
    Near me")."""
    if tool not in ("search", "maps"):
        raise ValueError(f"unknown grounding tool {tool!r}")
    if provider() != "gemini":
        raise LLMError(
            GROUNDING_UNAVAILABLE_MESSAGE, user_code=GROUNDING_UNAVAILABLE_CODE
        )
    _check_spend_cap()
    # Same global gate as the specialist agents (AGENT_MAX_CONCURRENCY), so
    # grounded calls never add to a search's burst; imported here because
    # base_agent imports this module
    from ..agents.base_agent import _get_semaphore

    started = time.monotonic()
    try:
        async with _get_semaphore():
            started = time.monotonic()
            resp = await _gemini_client().aio.models.generate_content(
                **_grounded_kwargs(
                    prompt, tool, system, lat, lng, language, max_tokens, timeout
                )
            )
        out = _grounded_response(resp)
    except LLMError:
        raise
    except Exception as e:
        raise _wrap(e) from e
    _log_usage(
        label or f"grounded_{tool}",
        "agent",
        LLMResponse(text="", truncated=out.truncated, usage=out.usage),
        started,
        extra={
            "tool": tool,
            "search_queries": len(out.search_queries),
            "grounding_chunks": len(out.chunks),
        },
    )
    return out


# ── Errors ────────────────────────────────────────────────────────────


def _check_spend_cap() -> None:
    if spend_cap_active():
        raise pause_error()


_BILLING_DISABLED = re.compile(
    r"billing (is |has been )?(disabled|not enabled)|requires billing to be enabled"
)


def _error_fields(e: Exception) -> tuple[int | None, str, str, set[str]]:
    """(HTTP status, message, status name, ErrorInfo reasons) of an SDK error —
    the parts that classify it, without the help links and metadata."""
    # google-genai: .code; anthropic: .status_code
    status = next(
        (
            v
            for v in (getattr(e, "code", None), getattr(e, "status_code", None))
            if isinstance(v, int)
        ),
        None,
    )
    message = getattr(e, "message", None)
    message = message if isinstance(message, str) else str(e)
    status_name = getattr(e, "status", None)
    status_name = status_name if isinstance(status_name, str) else ""
    reasons = set()
    details = getattr(e, "details", None)
    error = details.get("error", details) if isinstance(details, dict) else {}
    for item in (error.get("details") if isinstance(error, dict) else None) or []:
        if isinstance(item, dict) and isinstance(item.get("reason"), str):
            reasons.add(item["reason"].upper())
    return status, message, status_name, reasons


def _pause(code: str, status, status_name, reasons, message) -> LLMError:
    global _spend_cap_until, _pause_code
    _spend_cap_until = time.monotonic() + _SPEND_CAP_HOLD_SECONDS
    _pause_code = code
    logger.error(
        f"LLM {'spend cap reached' if code == SPEND_CAP_CODE else 'billing disabled'}"
        f" ({provider()} {status} {status_name} reasons={sorted(reasons)}): "
        f"{message[:300]}"
    )
    return pause_error()


def _wrap(e: Exception) -> LLMError:
    status, message, status_name, reasons = _error_fields(e)
    text = message.lower()
    if status in (400, 403) and (
        "BILLING_DISABLED" in reasons or _BILLING_DISABLED.search(text)
    ):
        return _pause(BILLING_CODE, status, status_name, reasons, message)
    if any(h in text for h in _SPEND_CAP_HINTS.get(status, ())):
        return _pause(SPEND_CAP_CODE, status, status_name, reasons, message)
    retryable = status in _RETRYABLE_STATUSES or _is_transport_error(e)
    return LLMError(str(e), retryable=retryable, status=status)


def _is_transport_error(e: Exception) -> bool:
    import httpx

    if isinstance(e, httpx.TransportError | TimeoutError):
        return True
    # google-genai uses aiohttp for async calls whenever it is installed
    try:
        import aiohttp

        if isinstance(e, aiohttp.ClientError):
            return True
    except ImportError:
        pass
    try:
        import anthropic

        return isinstance(e, anthropic.APIConnectionError)
    except ImportError:  # pragma: no cover
        return False


async def aclose() -> None:
    """Close the shared clients (app shutdown)."""
    global _gemini, _anthropic_async
    if _gemini is not None:
        try:
            await _gemini.aio.aclose()
            _gemini.close()
        except Exception as e:  # pragma: no cover - best effort at shutdown
            logger.warning(f"Closing the Gemini client failed: {e}")
        _gemini = None
    if _anthropic_async is not None:
        try:
            await _anthropic_async.close()
        except Exception as e:  # pragma: no cover
            logger.warning(f"Closing the Anthropic client failed: {e}")
        _anthropic_async = None


# ── Gemini (Vertex AI) ────────────────────────────────────────────────


def _gemini_client():
    global _gemini
    if _gemini is None:
        _gemini = _new_gemini_client()
    return _gemini


def _new_gemini_client():
    from google import genai
    from google.genai import types

    # Vertex AI with ADC (the VM's service account; `gcloud auth
    # application-default login` locally). SDK retries cover 429/5xx bursts
    # like the Anthropic client's max_retries did; the timeout bounds every
    # call (the SDK default is none).
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project or None,
        location=settings.gcp_location or "global",
        http_options=types.HttpOptions(
            timeout=_GEMINI_TIMEOUT_S * 1000,  # milliseconds
            retry_options=types.HttpRetryOptions(
                attempts=3, http_status_codes=[429, 500, 502, 503, 504]
            ),
        ),
    )


def _thinking_level(role: Role) -> str:
    level = (
        settings.gemini_thinking_chat
        if role == "chat"
        else settings.gemini_thinking_agent
    ).lower()
    return level if level in _THINKING_HEADROOM else "low"


def _gemini_kwargs(role, system, messages, max_tokens, json_output, timeout, retries):
    from google.genai import types

    level = _thinking_level(role)
    http_options = None
    if timeout is not None or not retries:
        http_options = types.HttpOptions(
            timeout=int((timeout or _GEMINI_TIMEOUT_S) * 1000),
            retry_options=None if retries else types.HttpRetryOptions(attempts=1),
        )
    config = types.GenerateContentConfig(
        system_instruction=system or None,
        max_output_tokens=max_tokens + _THINKING_HEADROOM[level],
        response_mime_type="application/json" if json_output else None,
        thinking_config=types.ThinkingConfig(thinking_level=level.upper()),
        http_options=http_options,
    )
    return {
        "model": model_for(role),
        "contents": _gemini_contents(messages),
        "config": config,
    }


def _grounded_kwargs(prompt, tool, system, lat, lng, language, max_tokens, timeout):
    from google.genai import types

    kwargs = _gemini_kwargs(
        "agent",
        system,
        [{"role": "user", "content": prompt}],
        max_tokens,
        False,
        timeout,
        True,
    )
    config = kwargs["config"]
    config.tools = [
        types.Tool(google_search=types.GoogleSearch())
        if tool == "search"
        else types.Tool(google_maps=types.GoogleMaps())
    ]
    located = lat is not None and lng is not None
    if located or language:
        config.tool_config = types.ToolConfig(
            retrieval_config=types.RetrievalConfig(
                lat_lng=types.LatLng(latitude=lat, longitude=lng) if located else None,
                language_code=language or None,
            )
        )
    return kwargs


def _grounded_response(resp) -> GroundedResponse:
    cands = getattr(resp, "candidates", None) or []
    meta = getattr(cands[0], "grounding_metadata", None) if cands else None
    chunks = []
    for c in getattr(meta, "grounding_chunks", None) or []:
        maps, web = getattr(c, "maps", None), getattr(c, "web", None)
        src, kind = (maps, "maps") if maps is not None else (web, "web")
        if src is None:  # image / retrieved-context chunks: kept for indices
            kind = None
        chunks.append(
            {
                "kind": kind,
                "uri": getattr(src, "uri", None) or None,
                "title": (getattr(src, "title", None) or "").strip(),
                "place_id": getattr(src, "place_id", None) if kind == "maps" else None,
            }
        )
    supports = []
    for s in getattr(meta, "grounding_supports", None) or []:
        seg = getattr(s, "segment", None)
        supports.append(
            {
                "text": getattr(seg, "text", None) or "",
                "start": getattr(seg, "start_index", None),
                "end": getattr(seg, "end_index", None),
                "chunks": [
                    i
                    for i in getattr(s, "grounding_chunk_indices", None) or []
                    if isinstance(i, int)
                ],
            }
        )
    queries = [
        q
        for q in getattr(meta, "web_search_queries", None) or []
        if isinstance(q, str) and q.strip()
    ]
    return GroundedResponse(
        text=resp.text or "",
        chunks=chunks,
        search_queries=queries,
        supports=supports,
        truncated=_gemini_truncated(resp),
        usage=_gemini_usage(resp),
    )


def _gemini_contents(messages: list[dict]) -> list:
    from google.genai import types

    contents = []
    for msg in messages:
        content = msg.get("content")
        blocks = (
            [{"type": "text", "text": content}] if isinstance(content, str) else content
        )
        parts = []
        for block in blocks or []:
            if block.get("type") == "image":
                src = block.get("source") or {}
                parts.append(
                    types.Part.from_bytes(
                        data=base64.b64decode(src.get("data", "")),
                        mime_type=src.get("media_type", "image/jpeg"),
                    )
                )
            elif block.get("text"):
                parts.append(types.Part.from_text(text=block["text"]))
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append(types.Content(role=role, parts=parts))
    return contents


def _gemini_truncated(resp) -> bool:
    for cand in getattr(resp, "candidates", None) or []:
        reason = getattr(cand, "finish_reason", None)
        if str(getattr(reason, "value", reason)) == "MAX_TOKENS":
            return True
    return False


def _gemini_usage(resp) -> dict:
    meta = getattr(resp, "usage_metadata", None)
    return {
        "input_tokens": getattr(meta, "prompt_token_count", None) or 0,
        "output_tokens": getattr(meta, "candidates_token_count", None) or 0,
        "thinking_tokens": getattr(meta, "thoughts_token_count", None) or 0,
        "cached_tokens": getattr(meta, "cached_content_token_count", None) or 0,
    }


def _gemini_response(resp) -> LLMResponse:
    # .text is None when a safety filter blocked the reply (Gemini 3.5+
    # default the filters to OFF on Vertex): treated as an empty answer.
    return LLMResponse(
        text=resp.text or "",
        truncated=_gemini_truncated(resp),
        usage=_gemini_usage(resp),
    )


# ── Anthropic ─────────────────────────────────────────────────────────


def _anthropic_client():
    global _anthropic_async
    if _anthropic_async is None:
        import anthropic

        # SDK-level retries handle 429/529 with Retry-After awareness
        _anthropic_async = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key, max_retries=3
        )
    return _anthropic_async


def _anthropic_kwargs(role, system, messages, max_tokens) -> dict:
    kwargs = {"model": model_for(role), "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    return kwargs


def _anthropic_response(resp) -> LLMResponse:
    usage = getattr(resp, "usage", None)
    return LLMResponse(
        text=resp.content[0].text if getattr(resp, "content", None) else "",
        truncated=getattr(resp, "stop_reason", None) == "max_tokens",
        usage={
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "thinking_tokens": 0,
            "cached_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        },
    )


# ── Usage accounting ──────────────────────────────────────────────────


def _log_usage(
    label: str,
    role: Role,
    out: LLMResponse,
    started: float,
    aborted: bool = False,
    extra: dict | None = None,
) -> None:
    record = {
        "label": label or role,
        "provider": provider(),
        "model": model_for(role),
        **{
            k: out.usage.get(k, 0)
            for k in (
                "input_tokens",
                "output_tokens",
                "thinking_tokens",
                "cached_tokens",
            )
        },
        "latency_ms": int((time.monotonic() - started) * 1000),
        "truncated": out.truncated,
        "aborted": aborted,
        **(extra or {}),
    }
    logger.info("llm_usage " + " ".join(f"{k}={v}" for k, v in record.items()))
    sink = _usage_sink.get()
    if sink is not None:
        sink.append(record)
