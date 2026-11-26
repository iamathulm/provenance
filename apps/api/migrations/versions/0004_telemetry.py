"""telemetry

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26 16:05:20.447641
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_logs")),
    )
    op.create_index(
        op.f("ix_request_logs_correlation_id"), "request_logs", ["correlation_id"], unique=False
    )
    op.create_table(
        "stage_spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("error_class", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_spans")),
    )
    op.create_index(
        op.f("ix_stage_spans_correlation_id"), "stage_spans", ["correlation_id"], unique=False
    )
    op.create_index(
        op.f("ix_stage_spans_workspace_id"), "stage_spans", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stage_spans_workspace_id"), table_name="stage_spans")
    op.drop_index(op.f("ix_stage_spans_correlation_id"), table_name="stage_spans")
    op.drop_table("stage_spans")
    op.drop_index(op.f("ix_request_logs_correlation_id"), table_name="request_logs")
    op.drop_table("request_logs")
