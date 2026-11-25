"""통계 추이·분류·요약 API 스키마."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BaseModel

from app.schemas.call import DATE_MAX, DATE_MIN, CallListQuery

# 쿼리 파라미터 선택 값은 `sort`처럼 소문자 허용 목록(Literal)으로 둔다.
Granularity = Literal["day", "week", "month"]
BreakdownBy = Literal["agent", "client"]


# ---------------------------------------------------------------- 요청


@dataclass(frozen=True)
class StatsPeriod:
    """`Depends(StatsPeriod)`로 받는 통계 기간. 규칙은 목록(`CallListQuery`)과 같다."""

    from_: Annotated[date | None, Query(alias="from", ge=DATE_MIN, le=DATE_MAX)] = None
    to: Annotated[date | None, Query(ge=DATE_MIN, le=DATE_MAX)] = None

    def __post_init__(self) -> None:
        self.call_filter()  # from > to 이면 목록과 같은 422(date_range)

    def call_filter(self) -> CallListQuery:
        """목록 필터로 변환한다. 삭제 제외·KST 경계 조건(`filter_conditions`)을 그대로 쓰기 위함."""
        return CallListQuery(from_=self.from_, to=self.to)


# ---------------------------------------------------------------- 응답


class TrendPoint(BaseModel):
    period: date  # 구간 시작일(KST). 주는 월요일, 월은 1일
    count: int


class TrendResponse(BaseModel):
    granularity: Granularity
    items: list[TrendPoint]


class CategoryCounts(BaseModel):
    """유형 코드별 건수. 5개 키가 항상 있다(0 포함). 분석 전인 건은 어느 키에도 없다."""

    INQUIRY: int
    COMPLAINT: int
    SUGGESTION: int
    EDUCATION: int
    ETC: int


class BreakdownItem(BaseModel):
    name: str | None  # 담당자·고객사가 없거나 빈 값이면 null (한 행으로 묶어 맨 뒤)
    count: int
    by_category: CategoryCounts


class BreakdownResponse(BaseModel):
    by: BreakdownBy
    items: list[BreakdownItem]


class StatsSummary(BaseModel):
    """통계 요약. `total`·`by_category`만 기간을 적용하고, 처리 대기 건수는 기간과 무관한 전체."""

    total: int
    by_category: CategoryCounts
    action_open: int  # 분석 조치 상태 OPEN
    needs_review: int  # 상태 NEEDS_REVIEW
    metadata_incomplete: int
    failed: int  # 상태 FAILED
    stale: int  # 정체 감지 기준(STALE_THRESHOLD_MIN)

    @classmethod
    def empty(cls) -> "StatsSummary":
        zero = CategoryCounts(INQUIRY=0, COMPLAINT=0, SUGGESTION=0, EDUCATION=0, ETC=0)
        return cls(
            total=0,
            by_category=zero,
            action_open=0,
            needs_review=0,
            metadata_incomplete=0,
            failed=0,
            stale=0,
        )
