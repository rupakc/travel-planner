"""The LLM provider seam (core/llm.py): Gemini on Vertex AI by default,
Anthropic behind LLM_PROVIDER. The SDKs are faked at the client boundary —
no network, no credentials."""

import base64
import json
import logging
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.agents import base_agent
from app.agents.chat_agent import ChatAgent
from app.core import llm
from app.core.config import settings

# ─── Fakes ────────────────────────────────────────────────────────────────


def _gemini_reply(text, finish="STOP", prompt=100, out=50, thoughts=7):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(value=finish))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=out,
            thoughts_token_count=thoughts,
            cached_content_token_count=0,
        ),
    )


class FakeGemini:
    """Stands in for ``genai.Client``: records every call; ``replies`` are
    returned (or raised, for exceptions) in order."""

    def __init__(self, replies=(), stream_chunks=()):
        self.calls = []
        self.replies = list(replies)
        self.stream_chunks = list(stream_chunks)
        models = SimpleNamespace(
            generate_content=self._generate,
            generate_content_stream=self._stream,
        )
        self.aio = SimpleNamespace(models=models, aclose=self._aclose)
        self.models = SimpleNamespace(generate_content=self._generate_sync)
        self.stream_closed = False
        self.closed = []

    async def _aclose(self):
        self.closed.append("aio")

    def close(self):
        self.closed.append("sync")

    def _generate_sync(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)

    async def _generate(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def _stream(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self.stream_chunks

        async def gen():
            try:
                for chunk in chunks:
                    if isinstance(chunk, Exception):
                        raise chunk
                    yield chunk
            finally:
                self.stream_closed = True

        return gen()


def _api_error(code, status, message, details=()):
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    error = {"code": code, "status": status, "message": message}
    if details:
        error["details"] = list(details)
    return cls(code, {"error": error})


def _agent(name="probe", prompt="You are a probe agent."):
    agent = base_agent.BaseAgent.__new__(base_agent.BaseAgent)
    agent.definition = SimpleNamespace(name=name, system_prompt=prompt)
    return agent


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    return fake


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def _sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(base_agent.asyncio, "sleep", _sleep)
    return slept


async def _collect(gen):
    return [json.loads(e) async for e in gen]


# ─── JSON agents on Gemini ────────────────────────────────────────────────


async def test_agent_call_uses_flash_lite_json_mode_and_minimal_thinking(gemini):
    gemini.replies = [_gemini_reply('{"results": [1, 2]}')]

    result = await _agent().execute("plan Lisbon")

    assert result == {"results": [1, 2]}
    [call] = gemini.calls
    assert call["model"] == "gemini-3.5-flash-lite"
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.thinking_config.thinking_level.value == "MINIMAL"
    assert config.system_instruction.startswith("You are a probe agent.")
    assert "Return ONLY valid JSON" in config.system_instruction
    # The output budget keeps headroom for thinking on top of the agent cap
    assert config.max_output_tokens > base_agent._MAX_TOKENS
    [content] = call["contents"]
    assert content.role == "user" and content.parts[0].text == "plan Lisbon"


async def test_image_blocks_become_inline_parts(gemini):
    gemini.replies = [_gemini_reply('{"places": []}')]
    png = b"\x89PNG\r\n\x1a\nfake"

    await _agent().execute(
        [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(png).decode(),
                },
            },
            {"type": "text", "text": "read the screenshot"},
        ]
    )

    parts = gemini.calls[0]["contents"][0].parts
    assert parts[0].inline_data.data == png
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[1].text == "read the screenshot"


async def test_overload_is_retried_with_backoff(gemini, no_sleep):
    gemini.replies = [
        _api_error(503, "UNAVAILABLE", "The model is overloaded."),
        _api_error(429, "RESOURCE_EXHAUSTED", "Resource exhausted. Try later."),
        _gemini_reply('{"ok": true}'),
    ]

    assert await _agent().execute("x") == {"ok": True}
    assert len(gemini.calls) == 3
    assert no_sleep == [2, 4]  # capacity errors back off exponentially


async def test_non_capacity_error_gives_up_with_error_result(
    gemini, no_sleep, monkeypatch
):
    monkeypatch.setattr(base_agent, "_MAX_RETRIES", 2)
    gemini.replies = [_api_error(400, "INVALID_ARGUMENT", "bad request")] * 2

    result = await _agent().execute("x")

    assert "error" in result and "error_code" not in result
    assert no_sleep == [2]


async def test_truncated_reply_retries_with_compact_instruction(gemini, no_sleep):
    gemini.replies = [
        _gemini_reply('{"results": [{"name": "cut', finish="MAX_TOKENS"),
        _gemini_reply('{"results": []}'),
    ]

    assert await _agent().execute("x") == {"results": []}
    first, second = (c["config"].system_instruction for c in gemini.calls)
    assert "cut off for being too long" not in first
    assert "cut off for being too long" in second


async def test_unparseable_reply_is_retried(gemini, no_sleep):
    gemini.replies = [_gemini_reply(None), _gemini_reply('{"a": 1}')]

    assert await _agent().execute("x") == {"a": 1}


# ─── Spend cap ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "status", "message"),
    [
        (403, "PERMISSION_DENIED", "Billing for this project is paused."),
        (429, "RESOURCE_EXHAUSTED", "Project spend cap reached for this budget."),
    ],
)
async def test_spend_cap_returns_friendly_error_without_retrying(
    gemini, no_sleep, code, status, message
):
    gemini.replies = [_api_error(code, status, message)]

    result = await _agent().execute("x")

    assert result == {"error": llm.SPEND_CAP_MESSAGE, "error_code": "ai_limit"}
    assert len(gemini.calls) == 1
    assert llm.spend_cap_active()


async def test_once_tripped_calls_fail_fast_without_reaching_vertex(gemini):
    gemini.replies = [_api_error(429, "RESOURCE_EXHAUSTED", "Spend cap reached.")]
    await _agent().execute("x")

    result = await _agent().execute("y")

    assert result["error_code"] == "ai_limit"
    assert len(gemini.calls) == 1


async def test_plain_quota_429_is_not_the_spend_cap(gemini, no_sleep, monkeypatch):
    monkeypatch.setattr(base_agent, "_MAX_RETRIES", 1)
    gemini.replies = [_api_error(429, "RESOURCE_EXHAUSTED", "Resource exhausted.")]

    result = await _agent().execute("x")

    assert result.get("error_code") is None
    assert not llm.spend_cap_active()


async def test_bad_request_naming_a_thinking_budget_is_not_the_cap(gemini, no_sleep):
    gemini.replies = [
        _api_error(400, "INVALID_ARGUMENT", "Thinking budget is out of range.")
    ] * base_agent._MAX_RETRIES

    result = await _agent().execute("x")

    assert result.get("error_code") is None
    assert not llm.spend_cap_active()


async def test_anthropic_credit_balance_counts_as_the_cap(monkeypatch, no_sleep):
    import anthropic
    import httpx

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError(
        "Your credit balance is too low to access the Anthropic API.",
        response=httpx.Response(400, request=request),
        body=None,
    )

    async def create(**kwargs):
        raise error

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(llm, "_anthropic_client", lambda: fake)

    assert (await _agent().execute("x"))["error_code"] == "ai_limit"


async def test_chat_reports_spend_cap_as_a_delta(gemini):
    gemini.stream_chunks = [_api_error(403, "PERMISSION_DENIED", "billing paused")]
    agent = ChatAgent(agents_dir=settings.agents_dir)

    events = await _collect(agent._regular_chat([{"role": "user", "content": "hi"}]))

    assert events == [
        {"type": "delta", "text": llm.SPEND_CAP_MESSAGE},
        {"type": "done"},
    ]


async def test_chat_stream_short_circuits_while_the_cap_holds(gemini):
    gemini.replies = [_api_error(403, "PERMISSION_DENIED", "billing paused")]
    await _agent().execute("x")
    agent = ChatAgent(agents_dir=settings.agents_dir)

    events = await _collect(
        agent.stream([{"role": "user", "content": "What should I eat in Lisbon?"}])
    )

    assert events == [
        {"type": "delta", "text": llm.SPEND_CAP_MESSAGE},
        {"type": "done"},
    ]
    assert len(gemini.calls) == 1


def test_single_agent_route_shows_the_friendly_message(client, gemini):
    gemini.replies = [_api_error(403, "PERMISSION_DENIED", "billing paused")]

    r = client.post(
        "/api/discover",
        json={
            "origin": "Berlin",
            "nationality": "German",
            "departure_date": "2026-12-01",
            "return_date": "2026-12-09",
            "interests": ["spend-cap-probe"],
        },
    )

    assert r.status_code == 503
    assert r.json()["detail"] == llm.SPEND_CAP_MESSAGE


# ─── Chat streaming on Gemini ─────────────────────────────────────────────


async def test_chat_streams_gemini_deltas_token_by_token(gemini):
    gemini.stream_chunks = [
        _gemini_reply("Lisbon "),
        _gemini_reply("in spring "),
        _gemini_reply("is lovely.", prompt=300, out=12, thoughts=40),
    ]
    agent = ChatAgent(agents_dir=settings.agents_dir)

    with llm.record_usage() as usage:
        events = await _collect(
            agent._regular_chat(
                [
                    {"role": "user", "content": "When to visit Lisbon?"},
                    {"role": "assistant", "content": "Any month works."},
                    {"role": "user", "content": "And spring?"},
                ]
            )
        )

    assert [e.get("text") for e in events if e["type"] == "delta"] == [
        "Lisbon ",
        "in spring ",
        "is lovely.",
    ]
    assert events[-1] == {"type": "done"}
    [call] = gemini.calls
    assert call["model"] == "gemini-3.8-flash"
    assert call["config"].thinking_config.thinking_level.value == "LOW"
    assert call["config"].response_mime_type is None
    assert [c.role for c in call["contents"]] == ["user", "model", "user"]
    [record] = usage
    assert record["label"] == "chat"
    assert record["thinking_tokens"] == 40 and record["output_tokens"] == 12


async def test_narrative_uses_the_chat_model(gemini):
    gemini.replies = [_gemini_reply("Lisbon awaits.")]

    resp = await llm.generate(
        [{"role": "user", "content": "summarise"}], role="chat", max_tokens=512
    )

    assert resp.text == "Lisbon awaits."
    assert gemini.calls[0]["model"] == settings.gemini_model_chat


# ─── Usage accounting ─────────────────────────────────────────────────────


async def test_usage_is_logged_per_call_without_content(gemini, caplog):
    gemini.replies = [_gemini_reply('{"secret": "do not log me"}')]

    with caplog.at_level(logging.INFO, logger="app.core.llm"):
        with llm.record_usage() as usage:
            await _agent(name="visa").execute("my passport number is X123")

    [line] = [r.getMessage() for r in caplog.records if "llm_usage" in r.getMessage()]
    assert "label=visa" in line and "input_tokens=100" in line
    assert "thinking_tokens=7" in line and "model=gemini-3.5-flash-lite" in line
    assert "X123" not in line and "do not log me" not in line
    assert usage[0]["output_tokens"] == 50


# ─── Provider switch ──────────────────────────────────────────────────────


class FakeAnthropic:
    def __init__(self, text='{"ok": 1}', stream_texts=()):
        self.calls = []
        reply = SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=11, output_tokens=5),
        )
        outer = self

        async def create(**kwargs):
            outer.calls.append(kwargs)
            return reply

        class _Stream:
            async def __aenter__(self):
                async def texts():
                    for t in stream_texts:
                        yield t

                self.text_stream = texts()
                return self

            async def __aexit__(self, *exc):
                return False

            async def get_final_message(self):
                return reply

        def stream(**kwargs):
            outer.calls.append(kwargs)
            return _Stream()

        self.messages = SimpleNamespace(create=create, stream=stream)


async def test_anthropic_provider_keeps_the_claude_path(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    fake = FakeAnthropic(stream_texts=["Hi ", "there"])
    monkeypatch.setattr(llm, "_anthropic_client", lambda: fake)

    assert await _agent().execute("x") == {"ok": 1}
    events = await _collect(
        ChatAgent(agents_dir=settings.agents_dir)._regular_chat(
            [{"role": "user", "content": "hi"}]
        )
    )

    agent_call, chat_call = fake.calls
    assert agent_call["model"] == "claude-haiku-4-5-20251001"
    assert agent_call["system"].startswith("You are a probe agent.")
    assert chat_call["model"] == "claude-sonnet-4-6"
    assert [e["text"] for e in events if e["type"] == "delta"] == ["Hi ", "there"]


def test_provider_defaults_to_auto():
    from app.core.config import Settings

    assert Settings.model_fields["llm_provider"].default == "auto"


@pytest.mark.parametrize(
    ("choice", "project", "key", "adc", "expected"),
    [
        # prod: GCP_PROJECT set → Gemini, even with an Anthropic key around
        ("auto", "voyager-prod-ohzkl", "sk-ant-x", None, "gemini"),
        # the existing local .env: Anthropic key, no GCP settings
        ("auto", "", "sk-ant-x", "some-adc-project", "anthropic"),
        # no key, ADC resolves a project
        ("auto", "", "", "some-adc-project", "gemini"),
        # nothing configured at all
        ("auto", "", "", None, "anthropic"),
        # explicit choices win
        ("gemini", "", "sk-ant-x", None, "gemini"),
        ("ANTHROPIC", "voyager-prod-ohzkl", "", None, "anthropic"),
    ],
)
def test_auto_provider_resolution(monkeypatch, choice, project, key, adc, expected):
    monkeypatch.setattr(settings, "llm_provider", choice)
    monkeypatch.setattr(settings, "gcp_project", project)
    monkeypatch.setattr(settings, "anthropic_api_key", key)
    monkeypatch.setattr(llm, "_adc_project", lambda: adc)

    assert llm.provider() == expected
    assert llm.model_for("agent") == (
        "gemini-3.5-flash-lite" if expected == "gemini" else "claude-haiku-4-5-20251001"
    )


def test_adc_lookup_runs_only_when_needed(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "gcp_project", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(llm, "_adc_project", lambda: calls.append(1) or "p")

    assert llm.provider() == "gemini"
    assert llm.provider() == "gemini"
    assert calls == [1]  # cached for the same settings

    monkeypatch.setattr(settings, "gcp_project", "voyager-prod-ohzkl")
    assert llm.provider_reason() == "auto: GCP_PROJECT set"
    assert calls == [1]


def test_resolved_provider_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "gcp_project", "voyager-prod-ohzkl")

    with caplog.at_level(logging.INFO, logger="app.core.llm"):
        llm.log_provider()

    assert "LLM provider: gemini (auto: GCP_PROJECT set)" in caplog.text


def test_health_agents_uses_the_configured_provider(client, gemini):
    from app.core.cache import get_cache

    get_cache().pop("health:agents", None)
    gemini.replies = [_gemini_reply("OK")]

    body = client.get("/health/agents").json()
    get_cache().pop("health:agents", None)

    assert body["llm"] == "ok" and body["llm_provider"] == "gemini"
    assert body["llm_provider_reason"] == "LLM_PROVIDER=gemini"
    assert gemini.calls[0]["model"] == "gemini-3.5-flash-lite"


# ─── Error classification details ─────────────────────────────────────────


async def test_billing_words_in_help_links_are_not_the_cap(
    gemini, no_sleep, monkeypatch
):
    monkeypatch.setattr(base_agent, "_MAX_RETRIES", 1)
    gemini.replies = [
        _api_error(
            403,
            "PERMISSION_DENIED",
            "Permission 'aiplatform.endpoints.predict' denied on resource.",
            details=[
                {
                    "@type": "type.googleapis.com/google.rpc.Help",
                    "links": [{"url": "https://console.cloud.google.com/billing"}],
                },
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "IAM_PERMISSION_DENIED",
                },
            ],
        )
    ]

    result = await _agent().execute("x")

    assert result.get("error_code") is None
    assert not llm.spend_cap_active()


async def test_billing_disabled_has_its_own_message(gemini, no_sleep):
    gemini.replies = [
        _api_error(
            403,
            "PERMISSION_DENIED",
            "This API method requires billing to be enabled.",
            details=[
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "BILLING_DISABLED",
                }
            ],
        )
    ]

    result = await _agent().execute("x")

    assert result == {"error": llm.BILLING_MESSAGE, "error_code": "ai_billing"}
    assert len(gemini.calls) == 1
    events = await _collect(
        ChatAgent(agents_dir=settings.agents_dir).stream(
            [{"role": "user", "content": "What should I eat in Lisbon?"}]
        )
    )
    assert events[0] == {"type": "delta", "text": llm.BILLING_MESSAGE}


async def test_anthropic_usage_limits_count_as_the_cap(monkeypatch, no_sleep):
    import anthropic
    import httpx

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError(
        "You have reached your specified API usage limits. You will regain "
        "access on 2026-12-01 at 00:00 UTC.",
        response=httpx.Response(400, request=request),
        body=None,
    )

    async def create(**kwargs):
        raise error

    monkeypatch.setattr(
        llm,
        "_anthropic_client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )

    assert (await _agent().execute("x"))["error_code"] == "ai_limit"


def test_aiohttp_transport_errors_are_retryable():
    aiohttp = pytest.importorskip("aiohttp")

    assert llm._wrap(aiohttp.ClientConnectionError("reset")).retryable
    assert llm._wrap(TimeoutError()).retryable


# ─── Timeouts, sync calls, stream cleanup, shutdown ───────────────────────


def test_client_has_a_default_timeout(monkeypatch):
    from google import genai

    seen = {}
    monkeypatch.setattr(genai, "Client", lambda **kw: seen.update(kw) or "client")

    assert llm._new_gemini_client() == "client"
    assert seen["vertexai"] is True
    assert seen["http_options"].timeout == 120_000
    assert seen["http_options"].retry_options.attempts == 3


def test_generate_sync_is_short_and_never_retries(gemini):
    gemini.replies = [_gemini_reply('{"city": "Lisbon", "country": "Portugal"}')]

    resp = llm.generate_sync([{"role": "user", "content": "LIS?"}], json_output=True)

    assert resp.text.startswith('{"city"')
    options = gemini.calls[0]["config"].http_options
    assert options.timeout == llm._SYNC_TIMEOUT_S * 1000
    assert options.retry_options.attempts == 1


async def test_aborted_stream_is_closed_and_its_usage_logged(gemini):
    gemini.stream_chunks = [_gemini_reply("one "), _gemini_reply("two ")]

    with llm.record_usage() as usage:
        gen = llm.stream([{"role": "user", "content": "hi"}], label="chat")
        assert await gen.__anext__() == "one "
        await gen.aclose()  # the client disconnected

    assert gemini.stream_closed
    [record] = usage
    assert record["aborted"] is True and record["label"] == "chat"


async def test_finished_stream_is_not_marked_aborted(gemini):
    gemini.stream_chunks = [_gemini_reply("done")]

    with llm.record_usage() as usage:
        assert [t async for t in llm.stream([{"role": "user", "content": "hi"}])] == [
            "done"
        ]

    assert usage[0]["aborted"] is False


async def test_aclose_closes_the_shared_client(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini", fake)

    await llm.aclose()

    assert fake.closed == ["aio", "sync"]
    assert llm._gemini is None


# ─── Thinking level vs model ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("agent_model", "agent_level", "chat_model", "chat_level", "error"),
    [
        ("gemini-3.5-flash-lite", "minimal", "gemini-3.8-flash", "low", None),
        # 3.5 / 3.6 Flash accept MINIMAL; only 3.7 / 3.8 Flash reject it
        ("gemini-3.5-flash", "minimal", "gemini-3.8-flash", "low", None),
        (
            "gemini-3.7-flash",
            "minimal",
            "gemini-3.8-flash",
            "low",
            "GEMINI_THINKING_AGENT=minimal",
        ),
        (
            "gemini-3.5-flash-lite",
            "low",
            "gemini-3.8-flash",
            "minimal",
            "GEMINI_THINKING_CHAT=minimal",
        ),
        (
            "gemini-3.8-flash",
            "minimal",
            "gemini-3.8-flash",
            "low",
            "GEMINI_THINKING_AGENT=minimal",
        ),
        (
            "gemini-3.5-flash-lite",
            "extreme",
            "gemini-3.8-flash",
            "low",
            "not a thinking level",
        ),
    ],
)
def test_thinking_level_is_validated_at_startup(
    monkeypatch, agent_model, agent_level, chat_model, chat_level, error
):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_model_agent", agent_model)
    monkeypatch.setattr(settings, "gemini_thinking_agent", agent_level)
    monkeypatch.setattr(settings, "gemini_model_chat", chat_model)
    monkeypatch.setattr(settings, "gemini_thinking_chat", chat_level)

    if error is None:
        llm.log_provider()
    else:
        with pytest.raises(RuntimeError, match=error):
            llm.log_provider()


def test_anthropic_skips_gemini_validation(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "gemini_thinking_chat", "minimal")

    llm.validate_config()
