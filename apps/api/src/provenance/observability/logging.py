"""Structured JSON logging with correlation IDs and PII redaction."""

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

from provenance.core.config import Settings
from provenance.guardrails.pii import redact


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(item) for item in value]
    return value


def redact_event(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: scrub PII from every string value, at any depth."""
    return {key: _redact_value(value) for key, value in event_dict.items()}


def configure_logging(settings: Settings) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
