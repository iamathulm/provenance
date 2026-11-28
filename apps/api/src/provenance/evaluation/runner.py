"""Wiring for evaluation commands: the real answer pipeline against the indexed demo corpora,
with every model call recorded to (and replayed from) cassettes, and an optional RAGAS judge.

With `GROQ_API_KEY` set, unseen requests call Groq and are saved; without it, only recorded
requests can be answered. Evaluation never writes telemetry (`NullRecorder`).
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from provenance.answers.pipeline import AnswerDeps, Answerer
from provenance.core.config import REPO_ROOT, Settings
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.evaluation.judging import AnswerJudge, judge_settings
from provenance.evaluation.retrieval import NullRecorder
from provenance.generation.cassette import CassetteProvider
from provenance.generation.client import LLMClient
from provenance.generation.limiter import ModelLimits, TokenLimiter
from provenance.generation.prompts import Prompt, load_prompt
from provenance.generation.providers import GroqProvider
from provenance.retrieval.embeddings import FastEmbedder
from provenance.retrieval.index import ChunkIndex
from provenance.retrieval.rerank import FlashRanker
from provenance.retrieval.search import Searcher

ANSWER_CASSETTES = REPO_ROOT / "eval" / "cassettes" / "answers"
EVAL_MAX_WAIT_S = 90.0  # evaluation can wait out a tokens-per-minute window


@dataclass
class EvalRuntime:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    llm: LLMClient
    searcher: Searcher
    reranker: FlashRanker
    judge: AnswerJudge | None
    recording: bool

    def answerer(self, prompt: Prompt | None = None) -> Answerer:
        return Answerer(
            AnswerDeps(
                settings=self.settings,
                searcher=self.searcher,
                llm=self.llm,
                reranker=self.reranker,
                recorder=NullRecorder(),
                answer_prompt=prompt or load_prompt("answer"),
                sql_prompt=load_prompt("sql"),
            )
        )


@asynccontextmanager
async def eval_runtime(settings: Settings, *, use_judge: bool) -> AsyncIterator[EvalRuntime]:
    engine = create_engine_from_settings(settings)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    http = httpx.AsyncClient(base_url=settings.groq_base_url)
    key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
    provider = (
        CassetteProvider(
            ANSWER_CASSETTES, "record", GroqProvider(http, key, settings.llm_timeout_s)
        )
        if key
        else CassetteProvider(ANSWER_CASSETTES, "replay")
    )
    limits = ModelLimits(settings.model_requests_per_minute, settings.model_tokens_per_minute)
    embedder = FastEmbedder(settings)
    reranker = FlashRanker(settings)
    index = ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimension)
    judge: AnswerJudge | None = None
    config = judge_settings(settings) if use_judge else None
    if config is not None:
        from provenance.evaluation.ragas_judge import RagasJudge  # eval dependency group only

        judge = RagasJudge(config, embedder)
    try:
        yield EvalRuntime(
            settings=settings,
            sessions=session_factory(engine),
            llm=LLMClient(provider, TokenLimiter(limits, EVAL_MAX_WAIT_S), NullRecorder()),
            searcher=Searcher(embedder, index, reranker, NullRecorder(), settings),
            reranker=reranker,
            judge=judge,
            recording=key is not None,
        )
    finally:
        await http.aclose()
        await qdrant.close()
        await engine.dispose()


def write_report(out: Path, stem: str, data: dict[str, Any], markdown: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, content in (("json", json.dumps(data, indent=2) + "\n"), ("md", markdown)):
        (out / f"{stem}.{name}").write_text(content, encoding="utf-8", newline="\n")
