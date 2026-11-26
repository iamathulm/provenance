"""Original uploaded files, stored in Postgres so the cloud deployment keeps them durably."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column

from provenance.db.base import Base, TimestampMixin


class StoredFile(TimestampMixin, Base):
    __tablename__ = "stored_files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
