from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.call_record import CallRecord


class Transcript(Base):
    __tablename__ = "transcript"
    __table_args__ = (
        Index(
            "ix_transcript_corrected_text_trgm",
            "corrected_text",
            postgresql_using="gin",
            postgresql_ops={"corrected_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("call_record.id"), nullable=False, unique=True
    )
    # [{speaker: "AGENT|CUSTOMER", start, end, text}] (PII 마스킹 후)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    corrected_text: Mapped[str | None] = mapped_column(Text)
    stt_engine: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    call: Mapped["CallRecord"] = relationship(back_populates="transcript")
