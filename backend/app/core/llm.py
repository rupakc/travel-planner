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
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from .config import settings

logger = logging.getLogger(__name__)

Role = Literal["agent", "chat"]

ANTHROPIC_MODELS = {"agent": "claude-haiku-4-5-20251001", "chat": "claude-sonnet-4-6"}

# Shown wherever an AI feature pauses because the monthly spend cap tripped.
SPEND_CAP_MESSAGE = "AI limit reached for this month — try again on the 1st."
SPEND_CAP_CODE = "ai_limit"

# Gemini counts thinking tokens against max_output_tokens: headroom keeps a
# reply sized for the old Claude budget from being cut short by reasoning.
# Only generated tokens are billed, so unused headroom costs nothing.
_THINKING_HEADROOM = {"minimal": 512, "low": 2048, "medium": 4096, "high": 8192}

# Google documents no API error for a tripped spend cap (only "usage is
# paused"), so a 403/429 whose text names billing or a budget counts as one;
# a bare 429 RESOURCE_EXHAUSTED stays a retryable quota error. Anthropic's
# equivalents are "credit balance is too low" and the workspace spend limit.
_SPEND_CAP_STATUSES = {400, 402, 403, 429}
_SPEND_CAP_HINTS = (
    "spend cap",
    "spending cap",
    "spend limit",
    "spending limit",
    "budget",
    "billing",
    "usage limit",
    "credit balance",
)
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504, 529}

# Once the cap is seen, fail fast for a while instead of sending every agent
# of every search into the same rejection.
_SPEND_CAP_HOLD_SECONDS = 300
_spend_cap_until = 0.0

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


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        spend_cap: bool = False,
        status: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.spend_cap = spend_cap
        self.status = status


def provider() -> str:
    return "anthropic" if settings.llm_provider.lower() == "anthropic" else "gemini"


def model_for(role: Role) -> str:
    if provider() == "anthropic":
        return ANTHROPIC_MODELS[role]
    return settings.gemini_model_chat if role == "chat" else settings.gemini_model_agent


def spend_cap_active() -> bool:
    return time.monotonic() < _spend_cap_until


def reset_spend_cap() -> None:
    global _spend_cap_until
    _spend_cap_until = 0.0


def spend_cap_error() -> dict:
    """The section/route payload for a paused AI feature."""
    return {"error": SPEND_CAP_MESSAGE, "error_code": SPEND_CAP_CODE}


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
    """Yield text deltas as the model produces them. Raises LLMError."""
    _check_spend_cap()
    started = time.monotonic()
    out = LLMResponse(text="")
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
            async for chunk in chunks:
                text = chunk.text or ""
                if text:
                    out.text += text
                    yield text
                # Usage and the finish reason ride on the last chunk
                if getattr(chunk, "usage_metadata", None):
                    out.usage = _gemini_usage(chunk)
                out.truncated = out.truncated or _gemini_truncated(chunk)
    except LLMError:
        raise
    except Exception as e:
        raise _wrap(e) from e
    _log_usage(label, role, out, started)


def generate_sync(
    messages: list[dict],
    *,
    role: Role = "agent",
    system: str | None = None,
    max_tokens: int = 1024,
    json_output: bool = False,
    label: str = "",
) -> LLMResponse:
    """Blocking variant for sync code paths (IATA lookup fallback)."""
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
            resp = _anthropic_sync.messages.create(
                **_anthropic_kwargs(role, system, messages, max_tokens)
            )
            out = _anthropic_response(resp)
        else:
            resp = _gemini_client().models.generate_content(
                **_gemini_kwargs(
                    role, system, messages, max_tokens, json_output, None, True
                )
            )
            out = _gemini_response(resp)
    except LLMError:
        raise
    except Exception as e:
        raise _wrap(e) from e
    _log_usage(label, role, out, started)
    return out


# ── Errors ────────────────────────────────────────────────────────────


def _check_spend_cap() -> None:
    if spend_cap_active():
        raise LLMError(SPEND_CAP_MESSAGE, spend_cap=True)


def _wrap(e: Exception) -> LLMError:
    global _spend_cap_until
    status = getattr(e, "code", None) or getattr(e, "status_code", None)
    status = status if isinstance(status, int) else None
    text = str(e).lower()
    if status in _SPEND_CAP_STATUSES and any(h in text for h in _SPEND_CAP_HINTS):
        _spend_cap_until = time.monotonic() + _SPEND_CAP_HOLD_SECONDS
        logger.error(f"LLM spend cap reached ({provider()} {status}): {e}")
        return LLMError(SPEND_CAP_MESSAGE, spend_cap=True, status=status)
    retryable = status in _RETRYABLE_STATUSES or _is_transport_error(e)
    return LLMError(str(e), retryable=retryable, status=status)


def _is_transport_error(e: Exception) -> bool:
    import httpx

    if isinstance(e, httpx.TransportError | TimeoutError):
        return True
    try:
        import anthropic

        return isinstance(e, anthropic.APIConnectionError)
    except ImportError:  # pragma: no cover
        return False


# ── Gemini (Vertex AI) ────────────────────────────────────────────────


def _gemini_client():
    global _gemini
    if _gemini is None:
        from google import genai
        from google.genai import types

        # Vertex AI with ADC (the VM's service account; `gcloud auth
        # application-default login` locally). SDK retries cover 429/5xx
        # bursts like the Anthropic client's max_retries did.
        _gemini = genai.Client(
            vertexai=True,
            project=settings.gcp_project or None,
            location=settings.gcp_location or "global",
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=3, http_status_codes=[429, 500, 502, 503, 504]
                )
            ),
        )
    return _gemini


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
            timeout=int(timeout * 1000) if timeout is not None else None,
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


def _log_usage(label: str, role: Role, out: LLMResponse, started: float) -> None:
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
    }
    logger.info("llm_usage " + " ".join(f"{k}={v}" for k, v in record.items()))
    sink = _usage_sink.get()
    if sink is not None:
        sink.append(record)
