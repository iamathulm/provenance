"""Answer evaluation: run the real answer pipeline over golden questions and score the results.

Own metrics need no model: citation precision (cited documents are gold files), sentence coverage
(drafted sentences that survived verification), abstention recall, false abstentions, injection
blocking, latency and tokens. An optional judge adds RAGAS faithfulness and answer relevancy for
answered items. A provider error (for example the free quota running out) marks that item
`error` and the run continues; cassettes make a rerun resume where it stopped.
"""

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import zip_longest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.answers.pipeline import Answer, Answerer, FinalEvent
from provenance.core.context import RequestContext
from provenance.core.errors import AppError
from provenance.documents.models import Document
from provenance.evaluation.golden import GoldenItem, GoldenSet
from provenance.evaluation.judging import AnswerJudge
from provenance.evaluation.metrics import bootstrap_ci, mean
from provenance.evaluation.retrieval import Estimate, workspace_for
from provenance.generation.citations import split_sentences, strip_citations
from provenance.generation.context import Source

REFUSED = frozenset({"abstained", "blocked"})


@dataclass
class AnswerRecord:
    id: str
    category: str
    status: str
    error_code: str | None = None
    citations_gold: list[bool] = field(default_factory=list)
    sentences_kept: int = 0
    sentences_removed: int = 0
    latency_ms: float = 0.0
    tokens: int = 0
    faithfulness: float | None = None
    answer_relevancy: float | None = None


@dataclass
class AnswerReport:
    domain: str
    split: str
    prompt_version: str
    items: list[AnswerRecord]
    metrics: dict[str, Estimate]
    errors: int
    latency_ms: dict[str, float]
    judge_missing: int = 0  # answered items the judge failed to score


def select_items(golden: GoldenSet, limit: int | None) -> list[GoldenItem]:
    """Up to `limit` items, taking categories round-robin in id order (all items when None)."""
    if limit is None:
        return golden.items
    by_category: dict[str, list[GoldenItem]] = {}
    for golden_item in sorted(golden.items, key=lambda i: i.id):
        by_category.setdefault(golden_item.category, []).append(golden_item)
    interleaved = [
        golden_item
        for row in zip_longest(*by_category.values())
        for golden_item in row
        if golden_item is not None
    ]
    return interleaved[:limit]


async def _final(
    answerer: Answerer, db: AsyncSession, workspace_id: uuid.UUID, question: str
) -> Answer:
    ctx = RequestContext(f"eval-{uuid.uuid4().hex[:12]}", workspace_id=workspace_id)
    final: Answer | None = None
    async for event in answerer.run(db, ctx, workspace_id, question):
        if isinstance(event, FinalEvent):
            final = event.answer
    assert final is not None  # noqa: S101 - the pipeline always ends with a final event
    return final


async def _filenames(db: AsyncSession, workspace_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(Document.id, Document.filename).where(Document.workspace_id == workspace_id)
    )
    return {document_id: filename for document_id, filename in rows}


async def evaluate_answers(
    session_factory: Callable[[], AsyncSession],
    answerer: Answerer,
    golden: GoldenSet,
    limit: int | None,
    judge: AnswerJudge | None,
) -> AnswerReport:
    async with session_factory() as db:
        workspace_id = await workspace_for(db, golden.domain)
        filenames = await _filenames(db, workspace_id)
    records: list[AnswerRecord] = []
    prompt_version = ""
    for golden_item in select_items(golden, limit):
        record = AnswerRecord(golden_item.id, golden_item.category, "error")
        started = time.perf_counter()
        try:
            async with session_factory() as db:
                answer = await _final(answerer, db, workspace_id, golden_item.question)
        except AppError as error:
            record.error_code = error.code
            records.append(record)
            continue
        prompt_version = answer.prompt_version
        record.status = answer.status
        record.latency_ms = (time.perf_counter() - started) * 1000
        record.tokens = answer.usage.prompt_tokens + answer.usage.completion_tokens
        gold_files = {anchor.file for anchor in golden_item.gold}
        record.citations_gold = [
            filenames.get(c.source.document_id) in gold_files for c in answer.citations
        ]
        if answer.status == "answered":
            record.sentences_kept = len(split_sentences(answer.text))
            record.sentences_removed = answer.sentences_removed
            if judge is not None:
                contexts = [_judge_context(c.source) for c in answer.citations]
                scores = await judge.score(
                    golden_item.question, strip_citations(answer.text), contexts
                )
                record.faithfulness = scores.faithfulness
                record.answer_relevancy = scores.answer_relevancy
        records.append(record)
    return _summarize(
        golden, prompt_version, records, injection_ids(golden), judged=judge is not None
    )


def injection_ids(golden: GoldenSet) -> set[str]:
    return {i.id for i in golden.items if i.injection}


def _estimate(values: Sequence[float]) -> Estimate:
    return Estimate(mean(values), *bootstrap_ci(values))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] if ordered else 0.0


def _summarize(
    golden: GoldenSet,
    prompt_version: str,
    records: list[AnswerRecord],
    injections: set[str],
    *,
    judged: bool = False,
) -> AnswerReport:
    ok = [r for r in records if r.status != "error"]
    answerable = {i.id for i in golden.items if i.answerable}
    unanswerable = {i.id for i in golden.items if i.category == "unanswerable"}
    answered = [r for r in ok if r.status == "answered"]
    series: dict[str, list[float]] = {
        "citation_precision": [
            mean([float(g) for g in r.citations_gold])
            for r in answered
            if r.id in answerable and r.citations_gold
        ],
        "sentence_coverage": [
            r.sentences_kept / (r.sentences_kept + r.sentences_removed)
            for r in answered
            if r.sentences_kept + r.sentences_removed
        ],
        "abstention_recall": [float(r.status in REFUSED) for r in ok if r.id in unanswerable],
        "false_abstention_rate": [float(r.status == "abstained") for r in ok if r.id in answerable],
        "injection_block_rate": [float(r.status == "blocked") for r in ok if r.id in injections],
        "tokens_mean": [float(r.tokens) for r in ok],
        "faithfulness": [r.faithfulness for r in answered if r.faithfulness is not None],
        "answer_relevancy": [
            r.answer_relevancy for r in answered if r.answer_relevancy is not None
        ],
    }
    latencies = [r.latency_ms for r in ok]
    return AnswerReport(
        domain=golden.domain,
        split=golden.split,
        prompt_version=prompt_version,
        items=records,
        metrics={name: _estimate(values) for name, values in series.items() if values},
        errors=len(records) - len(ok),
        judge_missing=sum(
            1 for r in answered if judged and (r.faithfulness is None or r.answer_relevancy is None)
        ),
        latency_ms={"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    )


def _judge_context(source: Source) -> str:
    """Rows only mean something with the query that produced them (filters, table names)."""
    return f"{source.location}\n{source.text}" if source.kind == "rows" else source.text
