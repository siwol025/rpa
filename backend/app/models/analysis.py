from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, in_check

if TYPE_CHECKING:
    from app.models.call_record import CallRecord

# 5대 유형 코드값은 BE-A05 확정 전 임시값 (research.md §4.2). 확정 시 마이그레이션으로 교체.
CATEGORIES = ("질의", "불만", "건의", "교육 내용", "기타 문의")
ACTION_STATUSES = ("OPEN", "DONE")


class Analysis(TimestampMixin, Base):
    __tablename__ = "analysis"
    __table_args__ = (
        CheckConstraint(in_check("category", CATEGORIES), name="category"),
        CheckConstraint(in_check("action_status", ACTION_STATUSES), name="action_status"),
        Index("ix_analysis_cat", "category"),
        Index(
            "ix_analysis_question_summary_trgm",
            "question_summary",
            postgresql_using="gin",
            postgresql_ops={"question_summary": "gin_trgm_ops"},
        ),
        Index(
            "ix_analysis_action_summary_trgm",
            "action_summary",
            postgresql_using="gin",
            postgresql_ops={"action_summary": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("call_record.id"), nullable=False, unique=True
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    question_summary: Mapped[str | None] = mapped_column(Text)
    action_summary: Mapped[str | None] = mapped_column(Text)
    follow_up_required: Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    action_status: Mapped[str | None] = mapped_column(String(20), server_default="OPEN")
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # GenAI 원본
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    needs_review: Mapped[bool | None] = mapped_column(Boolean, server_default="false")

    call: Mapped["CallRecord"] = relationship(back_populates="analysis")
