"""workspaces

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-26 16:00:45.828697
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("profile", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_workspaces_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("owner_id", "name", name=op.f("uq_workspaces_owner_id_name")),
    )
    op.create_index(op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.drop_table("workspaces")
