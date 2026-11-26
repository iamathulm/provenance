"""Private workspaces: every document, chunk, chat and metric belongs to exactly one."""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from provenance.db.base import Base, TimestampMixin


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    profile: Mapped[str] = mapped_column(String(40))
