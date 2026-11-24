from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, in_check

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.edit_history import EditHistory
    from app.models.processing_log import ProcessingLog
    from app.models.transcript import Transcript

CALL_STATUSES = (
    "REGISTERED",
    "QUEUED",
    "STT_DONE",
    "STORED",
    "NEEDS_REVIEW",
    "FAILED",
    "RETRY_REQUESTED",
)
SOURCE_TYPES = ("DRIVE", "WEB")


class CallRecord(TimestampMixin, Base):
    """상담 건. 상태 전이는 CallStateMachine(R-02)에서만 수행한다."""

    __tablename__ = "call_record"
    __table_args__ = (
        CheckConstraint(in_check("status", CALL_STATUSES), name="status"),
        CheckConstraint(in_check("source_type", SOURCE_TYPES), name="source_type"),
        Index(
            "ux_call_hash",
            "file_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_call_dt", "call_datetime"),
        Index("ix_call_status", "status", "status_changed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    agent_name: Mapped[str | None] = mapped_column(String(50))
    client_company: Mapped[str | None] = mapped_column(String(100))
    call_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_incomplete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="REGISTERED")
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    queue_item_id: Mapped[int | None] = mapped_column(BigInteger)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    transcript: Mapped["Transcript | None"] = relationship(back_populates="call", uselist=False)
    analysis: Mapped["Analysis | None"] = relationship(back_populates="call", uselist=False)
    logs: Mapped[list["ProcessingLog"]] = relationship(back_populates="call")
    edits: Mapped[list["EditHistory"]] = relationship(back_populates="call")
