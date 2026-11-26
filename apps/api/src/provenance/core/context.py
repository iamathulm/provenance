"""Per-request context shared across layers."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


@dataclass(slots=True)
class RequestContext:
    """Identity and state carried through a pipeline run."""

    correlation_id: str
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    degraded: set[str] = field(default_factory=set)
