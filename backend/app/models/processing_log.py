from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, in_check

if TYPE_CHECKING:
    from app.models.call_record import CallRecord

LOG_STEPS = ("REGISTER", "QUEUE", "STT", "GENAI", "STORE", "EXCEL", "CRM", "RETRY")
LOG_STATUSES = ("SUCCESS", "FAIL", "RETRY")


class ProcessingLog(Base):
    __tablename__ = "processing_log"
    __table_args__ = (
        CheckConstraint(in_check("step", LOG_STEPS), name="step"),
        CheckConstraint(in_check("status", LOG_STATUSES), name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("call_record.id"))
    step: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    orchestrator_job_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    call: Mapped["CallRecord | None"] = relationship(back_populates="logs")
