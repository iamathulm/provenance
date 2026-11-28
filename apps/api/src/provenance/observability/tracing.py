"""OpenTelemetry spans for every pipeline stage; exported only when an OTLP endpoint is set.

Spans always exist (cheap, in-process), so traces are one environment variable away:
`OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` sends them to any OTLP collector. Attributes
are identifiers only (correlation id, workspace id, stage), never text.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from provenance.core.config import Settings
from provenance.core.context import RequestContext

SERVICE_NAME = "provenance-api"
_PROVIDER = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
_TRACER = _PROVIDER.get_tracer("provenance")
_exporting = False


def tracer_provider() -> TracerProvider:
    return _PROVIDER


def exporting() -> bool:
    return _exporting


def configure_tracing(settings: Settings) -> None:
    """Attach the OTLP exporter once, if configured. Safe to call for every app instance."""
    global _exporting
    if _exporting or not settings.otel_exporter_otlp_endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
    _PROVIDER.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(_PROVIDER)
    _exporting = True


@contextmanager
def stage_span(name: str, ctx: RequestContext) -> Iterator[None]:
    attributes = {"provenance.stage": name, "provenance.correlation_id": ctx.correlation_id}
    if ctx.workspace_id is not None:
        attributes["provenance.workspace_id"] = str(ctx.workspace_id)
    # Exception messages can quote user text (e.g. a SQL error echoing a literal), so spans keep
    # only the error class: no exception events, no message in the status.
    with _TRACER.start_as_current_span(
        name, attributes=attributes, record_exception=False, set_status_on_exception=False
    ) as span:
        try:
            yield
        except Exception as error:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
