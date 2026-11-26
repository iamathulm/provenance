"""stored files

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26 16:03:44.949601
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_stored_files_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stored_files")),
    )
    op.create_index(
        op.f("ix_stored_files_workspace_id"), "stored_files", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stored_files_workspace_id"), table_name="stored_files")
    op.drop_table("stored_files")
