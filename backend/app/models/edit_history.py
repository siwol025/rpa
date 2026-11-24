from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.call_record import CallRecord


class EditHistory(Base):
    __tablename__ = "edit_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("call_record.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    before_val: Mapped[str | None] = mapped_column(Text)
    after_val: Mapped[str | None] = mapped_column(Text)
    editor: Mapped[str | None] = mapped_column(String(50))  # 로그인 없음 → 자유 입력
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    call: Mapped["CallRecord"] = relationship(back_populates="edits")
