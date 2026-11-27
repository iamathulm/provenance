"""Scripted LLM provider for pipeline tests: canned replies per purpose, every request recorded."""

from collections.abc import AsyncIterator, Callable

from provenance.generation.providers import ChatRequest, Delta, LLMRateLimitedError, Usage

Reply = str | Exception


class ScriptedProvider:
    name = "scripted"

    def __init__(self, **replies: Reply | Callable[[ChatRequest], Reply]) -> None:
        self.replies = replies
        self.requests: list[tuple[str, ChatRequest]] = []

    async def stream(self, request: ChatRequest, model: str) -> AsyncIterator[Delta]:
        self.requests.append((model, request))
        reply = self.replies[request.purpose]
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        for word in reply.split(" "):
            yield Delta(word + " ")
        yield Delta(usage=Usage(100, len(reply.split())))

    def prompts(self, purpose: str) -> list[str]:
        return [r.messages[-1].content for _, r in self.requests if r.purpose == purpose]


def rate_limited_once() -> Callable[[ChatRequest], Reply]:
    calls = 0

    def reply(_: ChatRequest) -> Reply:
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMRateLimitedError("busy", 30)
        return "Land within 90 seconds and swap the pack [S1]."

    return reply
