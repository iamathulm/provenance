from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from provenance.observability import tracing
from tests.conversations.conftest import RUNBOOK
from tests.conversations.test_conversations_api import ask, use_llm
from tests.ingest.harness import Harness

QUESTION = "battery fault: when to land and swap the pack? I'm jane.doe@example.com"
_EXPORTER = InMemorySpanExporter()
tracing.tracer_provider().add_span_processor(SimpleSpanProcessor(_EXPORTER))


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


@pytest.fixture
async def answered(
    app: FastAPI, client: AsyncClient, harness: Harness, spans: InMemorySpanExporter
) -> str:
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    spans.clear()  # only this scenario's spans are inspected
    await harness.upload("runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()
    base = f"/v1/workspaces/{harness.workspace_id}"
    use_llm(app, harness, "Land within 90 seconds and swap the pack [S1].")
    await client.post(f"{base}/search", json={"query": "swap the pack"})
    created = (await client.post(f"{base}/conversations", json={})).json()
    await ask(client, f"{base}/conversations/{created['id']}", QUESTION)
    return (await client.get("/metrics")).text


async def test_metrics_endpoint_counts_stages_and_calls(client: AsyncClient, answered: str) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'provenance_stage_duration_seconds_count{outcome="ok",stage="retrieve"}' in answered
    assert 'provenance_llm_calls_total{model="m-1",purpose="answer",status="ok"}' in answered
    assert 'provenance_answers_total{status="answered"}' in answered


async def test_metrics_and_spans_carry_no_text(answered: str, spans: InMemorySpanExporter) -> None:
    attributes = " ".join(
        str(value) for span in spans.get_finished_spans() for value in span.attributes.values()
    )

    for secret in ("jane.doe", "example.com", "swap the pack", "battery fault"):
        assert secret not in answered
        assert secret not in attributes


@pytest.mark.usefixtures("answered")
async def test_spans_per_stage_without_exporter(spans: InMemorySpanExporter) -> None:
    names = {span.name for span in spans.get_finished_spans()}

    assert {
        "embed_query",
        "retrieve",
        "authorize",
        "rerank",
        "answer_generate",
        "answer_verify",
    } <= names
    assert tracing.exporting() is False


async def test_exported_span_events_never_carry_error_text(spans: InMemorySpanExporter) -> None:
    from provenance.core.context import RequestContext

    secret = "Could not convert string 'jane.doe@example.com'"
    with (
        pytest.raises(ValueError, match="jane"),
        tracing.stage_span("answer_sql", RequestContext("c1")),
    ):
        raise ValueError(secret)

    (span,) = [s for s in spans.get_finished_spans() if s.name == "answer_sql"]
    exported = " ".join(
        [str(v) for v in span.attributes.values()]
        + [str(v) for event in span.events for v in event.attributes.values()]
        + [span.status.description or ""]
    )
    assert "jane.doe" not in exported
    assert span.attributes["error.type"] == "ValueError"
