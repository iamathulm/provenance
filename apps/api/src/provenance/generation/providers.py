"""LLM providers behind one streaming protocol. Groq is called directly over its OpenAI-compatible
HTTP API with httpx (no SDK); a cassette provider records and replays calls for offline tests.

Errors are typed so callers can say something actionable: a missing or rejected key
(`LLMUnavailableError`), a rate limit (`LLMRateLimitedError`, with the server's retry-after), or
anything else (`LLMFailedError`). Nothing here ever invents text on failure.
"""

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from provenance.core.errors import AppError

Purpose = Literal["answer", "sql"]

# Per-model request options. Reasoning tokens count against the free tier's tokens-per-minute,
# so answers use no reasoning at all and SQL uses the lowest effort the model allows.
MODEL_OPTIONS: Mapping[str, Mapping[str, Any]] = {
    "qwen/qwen3.8-27b": {"reasoning_effort": "none"},
    "openai/gpt-oss-120b": {"reasoning_effort": "low", "include_reasoning": False},
    "openai/gpt-oss-20b": {"reasoning_effort": "low", "include_reasoning": False},
}


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatRequest:
    purpose: Purpose
    messages: tuple[ChatMessage, ...]
    max_tokens: int
    temperature: float = 0.1
    json_schema: Mapping[str, Any] | None = None

    def body(self, model: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "max_completion_tokens": self.max_tokens,
            "temperature": self.temperature,
            # Groq does not stream structured outputs, so JSON-schema calls arrive in one piece.
            "stream": self.json_schema is None,
            **MODEL_OPTIONS.get(model, {}),
        }
        if self.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": self.purpose, "schema": dict(self.json_schema)},
            }
        return body


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class Delta:
    """A streamed piece of text; the last delta of a call carries the token usage."""

    text: str = ""
    usage: Usage | None = None


@dataclass
class Completion:
    model: str
    text: str = ""
    usage: Usage = field(default_factory=Usage)


class LLMUnavailableError(AppError):
    status_code = 503
    code = "llm_unavailable"


class LLMRateLimitedError(AppError):
    status_code = 429
    code = "llm_rate_limited"

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMFailedError(AppError):
    status_code = 502
    code = "llm_failed"


class LLMProvider(Protocol):
    name: str

    def stream(self, request: ChatRequest, model: str) -> AsyncIterator[Delta]: ...


async def complete(provider: LLMProvider, request: ChatRequest, model: str) -> Completion:
    completion = Completion(model)
    parts: list[str] = []
    async for delta in provider.stream(request, model):
        parts.append(delta.text)
        if delta.usage is not None:
            completion.usage = delta.usage
    completion.text = "".join(parts)
    return completion


NO_KEY_MESSAGE = (
    "Answers need a free Groq API key. Add GROQ_API_KEY to .env (https://console.groq.com/keys) "
    "and restart. Search and tables work without it."
)


class GroqProvider:
    name = "groq"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, timeout_s: float) -> None:
        self._client = client
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)

    async def stream(self, request: ChatRequest, model: str) -> AsyncIterator[Delta]:
        if not self._api_key:
            raise LLMUnavailableError(NO_KEY_MESSAGE)
        body = request.body(model)
        if body["stream"]:
            body["stream_options"] = {"include_usage": True}
        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            ) as response:
                if response.status_code != httpx.codes.OK:
                    await response.aread()
                    raise _http_error(response)
                if not body["stream"]:
                    await response.aread()
                    yield _parse_whole(response)
                    return
                async for line in response.aiter_lines():
                    delta = _parse_sse(line)
                    if delta is not None:
                        yield delta
        except httpx.TimeoutException as error:
            raise LLMFailedError("The language model timed out. Try again.") from error
        except httpx.TransportError as error:
            raise LLMFailedError("The language model could not be reached. Try again.") from error


def _http_error(response: httpx.Response) -> AppError:
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        retry = response.headers.get("retry-after")
        return LLMRateLimitedError(
            "The free Groq quota is busy. Wait a few seconds and ask again.",
            float(retry) if retry and retry.replace(".", "", 1).isdigit() else None,
        )
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        return LLMUnavailableError("GROQ_API_KEY was rejected. Check the key in .env.")
    return LLMFailedError(f"The language model returned HTTP {response.status_code}. Try again.")


def _usage(raw: Mapping[str, Any] | None) -> Usage | None:
    if not raw:
        return None
    return Usage(int(raw.get("prompt_tokens", 0)), int(raw.get("completion_tokens", 0)))


def _parse_whole(response: httpx.Response) -> Delta:
    try:
        payload = response.json()
        text = payload["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise LLMFailedError("The language model sent a malformed response.") from error
    return Delta(text, _usage(payload.get("usage")) or Usage())


def _parse_sse(line: str) -> Delta | None:
    if not line.startswith("data:"):
        return None
    payload = line.removeprefix("data:").strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError as error:
        raise LLMFailedError("The language model sent a malformed stream.") from error
    if "error" in chunk:
        raise LLMFailedError("The language model reported an error mid-answer. Try again.")
    choices = chunk.get("choices") or []
    text = ((choices[0].get("delta") or {}).get("content") or "") if choices else ""
    usage = _usage(chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage"))
    return Delta(text, usage) if text or usage else None
