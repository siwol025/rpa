"""엑셀 보고서 API 스키마."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import Query

from app.core.errors import AppError, ErrorCode
from app.schemas.call import DATE_MAX, DATE_MIN
from app.schemas.common import KST

MAX_REPORT_DAYS = 366


def _invalid(loc: str, msg: str, type_: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"loc": ["query", loc], "msg": msg, "type": type_}]},
    )


@dataclass(frozen=True)
class ReportPeriod:
    """`Depends(ReportPeriod)`로 받는 보고서 기간(KST 날짜, 양 끝 포함).

    비우면 `to`는 오늘(KST), `from`은 `to`의 365일 전이다(최대 기간 366일).
    """

    from_: Annotated[date | None, Query(alias="from", ge=DATE_MIN, le=DATE_MAX)] = None
    to: Annotated[date | None, Query(ge=DATE_MIN, le=DATE_MAX)] = None

    def __post_init__(self) -> None:
        to = self.to or datetime.now(KST).date()
        from_ = self.from_ or to - timedelta(days=MAX_REPORT_DAYS - 1)
        object.__setattr__(self, "to", to)
        object.__setattr__(self, "from_", from_)
        if from_ > to:
            raise _invalid("from", "from은 to보다 늦을 수 없습니다", "date_range")
        if (to - from_).days + 1 > MAX_REPORT_DAYS:
            raise _invalid("to", f"보고서 기간은 최대 {MAX_REPORT_DAYS}일입니다", "period_too_long")

    @property
    def start(self) -> date:
        assert self.from_ is not None  # __post_init__에서 채운다
        return self.from_

    @property
    def end(self) -> date:
        assert self.to is not None
        return self.to
