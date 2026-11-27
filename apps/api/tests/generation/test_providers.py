import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from provenance.generation.cassette import CassetteProvider
from provenance.generation.providers import (
    ChatMessage,
    ChatRequest,
    GroqProvider,
    LLMFailedError,
    LLMRateLimitedError,
    LLMUnavailableError,
    Usage,
    complete,
)

REQUEST = ChatRequest("answer", (ChatMessage("user", "When is GA?"),), max_tokens=50)
MODEL = "qwen/qwen3.8-27b"


def sse(*chunks: dict[str, object]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def provider(
    handler: Callable[[httpx.Request], httpx.Response], key: str | None = "k"
) -> GroqProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://groq.test")
    return GroqProvider(client, key, timeout_s=5)


async def test_streams_text_and_usage_with_model_options() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        body = sse(
            {"choices": [{"delta": {"content": "3 February"}}]},
            {"choices": [{"delta": {"content": " 2027 [S1]."}}]},
            {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 7}},
        )
        return httpx.Response(200, content=body)

    completion = await complete(provider(handler), REQUEST, MODEL)

    assert completion.text == "3 February 2027 [S1]."
    assert completion.usage == Usage(40, 7)
    assert sent[0]["reasoning_effort"] == "none"
    assert sent[0]["stream"] is True


@pytest.mark.parametrize(
    ("response", "error", "code"),
    [
        (
            httpx.Response(429, headers={"retry-after": "7"}),
            LLMRateLimitedError,
            "llm_rate_limited",
        ),
        (httpx.Response(401), LLMUnavailableError, "llm_unavailable"),
        (httpx.Response(500), LLMFailedError, "llm_failed"),
        (
            httpx.Response(200, content=b'data: {"error": {"message": "x"}}\n\n'),
            LLMFailedError,
            "llm_failed",
        ),
    ],
)
async def test_provider_failures_are_typed(
    response: httpx.Response, error: type[Exception], code: str
) -> None:
    with pytest.raises(error) as raised:
        await complete(provider(lambda _: response), REQUEST, MODEL)

    assert raised.value.code == code  # type: ignore[attr-defined]
    if isinstance(raised.value, LLMRateLimitedError):
        assert raised.value.retry_after_s == 7


async def test_network_errors_and_missing_key_are_actionable() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(LLMFailedError, match="could not be reached"):
        await complete(provider(unreachable), REQUEST, MODEL)
    with pytest.raises(LLMUnavailableError, match="GROQ_API_KEY"):
        await complete(provider(unreachable, key=None), REQUEST, MODEL)


async def test_cassettes_record_then_replay_offline(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=sse(
                {"choices": [{"delta": {"content": "Land within 90 seconds [S1]."}}]},
                {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 6}},
            ),
        )

    recorded = await complete(
        CassetteProvider(tmp_path, "record", provider(handler)), REQUEST, MODEL
    )
    replayed = await complete(CassetteProvider(tmp_path, "replay"), REQUEST, MODEL)
    changed = ChatRequest("answer", (ChatMessage("user", "Different?"),), max_tokens=50)

    assert calls == 1
    assert replayed.text == recorded.text == "Land within 90 seconds [S1]."
    assert replayed.usage == Usage(9, 6)
    with pytest.raises(LLMUnavailableError, match="No recorded answer"):
        await complete(CassetteProvider(tmp_path, "replay"), changed, MODEL)


def test_json_schema_requests_structured_output() -> None:
    request = ChatRequest("sql", REQUEST.messages, 100, json_schema={"type": "object"})

    body = request.body("openai/gpt-oss-20b")

    assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}  # type: ignore[index]
    assert body["include_reasoning"] is False
