"""The question-answering pipeline. One LLM call for document answers, two for table answers.

    input guard → search → route → context guard → [generate SQL → run SQL] → pack sources
      → generate (streamed) → verify citations → output guard

Everything except the two model calls is local. Each step yields a `StageEvent` (the UI shows
progress) and records a span; answer tokens stream as `TokenEvent`s as a draft; the verified,
guarded answer arrives last in a `FinalEvent`. When the workspace has nothing relevant the
pipeline abstains without calling the model at all. SQL problems degrade to a documents-only
answer with a notice; answer-model problems raise typed, actionable errors.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from provenance.answers.sql import generate_sql
from provenance.core.config import Settings
from provenance.core.context import RequestContext
from provenance.core.errors import AppError
from provenance.core.pipeline import SpanRecorder, StageOutcome
from provenance.generation.citations import (
    ABSTENTION,
    CitedSource,
    split_sentences,
    strip_citations,
    verify,
)
from provenance.generation.client import LLMClient, StreamEnd
from provenance.generation.context import Source, pack_chunks, rows_source
from provenance.generation.prompts import Prompt
from provenance.generation.providers import ChatMessage, ChatRequest, LLMFailedError, Usage
from provenance.guardrails.guards import (
    GuardrailDecision,
    check_context,
    check_input,
    check_output,
)
from provenance.observability.tracing import stage_span
from provenance.retrieval.rerank import Reranker
from provenance.retrieval.router import Route, route_query
from provenance.retrieval.search import Searcher, SearchRequest
from provenance.structured.catalog import load_catalog
from provenance.structured.engine import run_query

Status = Literal["answered", "abstained", "blocked"]
_HISTORY_TURNS = 2
_HISTORY_CHARS = 400
_TABLE_ROUTE_CHUNKS = 2


@dataclass(frozen=True)
class Exchange:
    question: str
    answer: str


@dataclass
class Answer:
    status: Status
    text: str
    question: str  # PII-redacted
    route: Route
    citations: list[CitedSource] = field(default_factory=list)
    guardrails: list[GuardrailDecision] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    sql: str | None = None
    model: str | None = None
    prompt_version: str = ""
    usage: Usage = field(default_factory=Usage)
    sentences_removed: int = 0  # drafted sentences the citation verifier dropped


@dataclass(frozen=True)
class StageEvent:
    stage: str


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class FinalEvent:
    answer: Answer


AnswerEvent = StageEvent | TokenEvent | FinalEvent


@dataclass
class AnswerDeps:
    settings: Settings
    searcher: Searcher
    llm: LLMClient
    reranker: Reranker
    recorder: SpanRecorder
    answer_prompt: Prompt
    sql_prompt: Prompt


class Answerer:
    def __init__(self, deps: AnswerDeps) -> None:
        self._deps = deps

    @asynccontextmanager
    async def _span(self, ctx: RequestContext, stage: str) -> AsyncIterator[None]:
        started = time.perf_counter()
        outcome: StageOutcome = "ok"
        error_class = None
        try:
            with stage_span(stage, ctx):
                yield
        except Exception as error:
            outcome, error_class = "error", type(error).__name__
            raise
        finally:
            duration = (time.perf_counter() - started) * 1000
            await self._deps.recorder.record(ctx, stage, outcome, duration, error_class)

    async def run(
        self,
        db: AsyncSession,
        ctx: RequestContext,
        workspace_id: uuid.UUID,
        question: str,
        history: Sequence[Exchange] = (),
    ) -> AsyncIterator[AnswerEvent]:
        settings = self._deps.settings
        version = self._deps.answer_prompt.version

        yield StageEvent("checking")
        checked = check_input(question)
        guardrails = list(checked.decisions)
        if checked.blocked_message is not None:
            yield FinalEvent(
                Answer(
                    "blocked",
                    checked.blocked_message,
                    checked.question,
                    Route("docs", ["blocked before retrieval"]),
                    guardrails=guardrails,
                    prompt_version=version,
                )
            )
            return

        yield StageEvent("searching")
        async with self._span(ctx, "answer_search"):
            result = await self._deps.searcher.search(
                db,
                ctx,
                workspace_id,
                SearchRequest(checked.question, "hybrid_rerank", settings.context_max_sources * 2),
            )
            tables = await load_catalog(db, workspace_id)
        route = route_query(checked.question, result.ranked_chunks, bool(tables))

        def abstain(reason: str) -> FinalEvent:
            return FinalEvent(
                Answer(
                    "abstained",
                    ABSTENTION,
                    checked.question,
                    route,
                    guardrails=guardrails,
                    notices=[reason],
                    degraded=sorted(ctx.degraded),
                    prompt_version=version,
                )
            )

        top = result.hits[0].rerank_score if result.hits else None
        if route.kind == "docs" and (
            not result.hits or (top is not None and top < settings.relevance_floor)
        ):
            guardrails.append(
                GuardrailDecision(
                    "off_topic",
                    "input",
                    "flag",
                    "relevance_floor",
                    "Nothing in this workspace is relevant enough to answer from.",
                )
            )
            yield abstain("No relevant passage was found in this workspace.")
            return

        quarantined = check_context([hit.chunk.text for hit in result.hits])
        guardrails += [q.decision for q in quarantined]
        excluded = {q.index for q in quarantined}
        hits = [hit for i, hit in enumerate(result.hits) if i not in excluded]
        forbidden = [result.hits[q.index].chunk.text for q in quarantined]

        notices: list[str] = []
        rows = None
        sql: str | None = None
        if route.kind in ("table", "both") and tables:
            yield StageEvent("querying tables")
            try:
                async with self._span(ctx, "answer_sql"):
                    proposed = await generate_sql(
                        self._deps.llm,
                        ctx,
                        self._deps.sql_prompt,
                        settings.sql_model,
                        checked.question,
                        tables,
                    )
                    if proposed is not None:
                        rows = await run_query(db, workspace_id, proposed, settings)
                        sql = rows.sql  # only SQL that actually ran is reported
            except AppError as error:
                ctx.degraded.add("sql")
                notices.append(f"Table lookup skipped: {error.message}")

        # SQL rows, when there are any, are the primary evidence: they become S1.
        sources: list[Source] = []
        if rows is not None and (table_source := rows_source(rows, 1)):
            sources.append(table_source)
        max_chunks = _TABLE_ROUTE_CHUNKS if sources and route.kind == "table" else None
        sources += pack_chunks(
            hits,
            max_sources=max_chunks or settings.context_max_sources,
            max_words=settings.context_max_words,
            first_number=len(sources) + 1,
        )
        if not sources:
            yield abstain("No usable passage was found in this workspace.")
            return

        yield StageEvent("writing")
        request = ChatRequest(
            "answer",
            (
                ChatMessage("system", self._deps.answer_prompt.system),
                ChatMessage(
                    "user",
                    self._deps.answer_prompt.render(
                        sources="\n\n".join(s.render() for s in sources),
                        history=_history(history),
                        question=checked.question,
                    ),
                ),
            ),
            max_tokens=settings.answer_max_tokens,
        )
        # The draft streams sentence by sentence, each one checked first, so text that echoes a
        # quarantined passage or the system prompt, or leaks personal data, is never shown.
        source_texts = [s.text for s in sources]
        forbidden.append(self._deps.answer_prompt.system)
        streamed = _GuardedStream(source_texts, forbidden)
        end = StreamEnd()
        async with self._span(ctx, "answer_generate"):
            async for delta in self._deps.llm.stream(ctx, request, settings.answer_models):
                if isinstance(delta, StreamEnd):
                    end = delta
                elif delta.text:
                    for sentence in streamed.feed(delta.text):
                        yield TokenEvent(sentence)
            for sentence in streamed.flush():
                yield TokenEvent(sentence)
        guardrails += streamed.decisions
        if not streamed.draft.strip():
            raise LLMFailedError("The model returned an empty answer. Ask again.")
        if streamed.blocked:
            yield FinalEvent(
                Answer(
                    "blocked",
                    ABSTENTION,
                    checked.question,
                    route,
                    guardrails=guardrails,
                    notices=notices,
                    degraded=sorted(ctx.degraded),
                    sql=sql,
                    model=end.model or None,
                    prompt_version=version,
                    usage=end.usage or Usage(),
                )
            )
            return

        yield StageEvent("checking citations")
        async with self._span(ctx, "answer_verify"):
            verified = await asyncio.to_thread(
                verify,
                streamed.draft,
                sources,
                question=checked.question,
                scorer=self._deps.reranker.score,
                support_min=settings.citation_support_min,
                lexical_min=settings.citation_lexical_min,
            )
            output = check_output(verified.text, source_texts, forbidden)
        guardrails += [d for d in output.decisions if d not in guardrails]
        if verified.removed_sentences and not verified.abstained:
            notices.append(
                f"{verified.removed_sentences} unsupported sentence(s) removed from the answer."
            )
        status: Status = "abstained" if verified.abstained else "answered"
        yield FinalEvent(
            Answer(
                status,
                output.answer,
                checked.question,
                route,
                citations=verified.citations,
                guardrails=guardrails,
                notices=notices,
                degraded=sorted(ctx.degraded),
                sql=sql,
                model=end.model or None,
                prompt_version=version,
                usage=end.usage or Usage(),
                sentences_removed=verified.removed_sentences,
            )
        )


class _GuardedStream:
    """Releases the draft one checked sentence at a time; stops for good once a check blocks."""

    def __init__(self, sources: list[str], forbidden: list[str]) -> None:
        self._sources = sources
        self._forbidden = forbidden
        self._pending = ""
        self._previous = ""
        self._parts: list[str] = []
        self.decisions: list[GuardrailDecision] = []
        self.blocked = False

    @property
    def draft(self) -> str:
        return "".join(self._parts)

    def feed(self, text: str) -> list[str]:
        self._parts.append(text)
        self._pending += text
        sentences = split_sentences(self._pending)
        if len(sentences) < 2:  # the last sentence may still be growing
            return []
        self._pending = sentences[-1]
        return self._release(sentences[:-1])

    def flush(self) -> list[str]:
        pending, self._pending = self._pending, ""
        return self._release([pending] if pending.strip() else [])

    def _release(self, sentences: list[str]) -> list[str]:
        released: list[str] = []
        for sentence in sentences:
            if self.blocked:
                break
            # Check with the previous sentence too, so an echo split across a boundary is caught.
            check = check_output(sentence, self._sources, self._forbidden)
            if check_output(f"{self._previous} {sentence}", self._sources, self._forbidden).blocked:
                check.blocked = True
            self._previous = sentence
            self.decisions += [d for d in check.decisions if d not in self.decisions]
            if check.blocked:
                self.blocked = True
                break
            released.append(check.answer + " ")
        return released


def _history(history: Sequence[Exchange]) -> str:
    if not history:
        return ""
    lines = ["Earlier in this conversation (for context only; cite only the sources above):"]
    for exchange in history[-_HISTORY_TURNS:]:
        lines.append(f"Q: {exchange.question}")
        answer = strip_citations(exchange.answer)  # old [Sn] ids mean other sources now
        lines.append(f"A: {answer[:_HISTORY_CHARS]}")
    return "\n".join(lines) + "\n\n"
