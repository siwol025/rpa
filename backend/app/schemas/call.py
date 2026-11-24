"""상담 목록·상세 API 스키마 (W-01, W-02)."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.core.errors import AppError, ErrorCode
from app.schemas.common import KstDatetime

# ---------------------------------------------------------------- enum (convention.md §5.3)
# 값은 모델의 CHECK 상수(app/models/*.py)와 같아야 한다 (tests/unit/test_call_enums.py).


class CallStatus(StrEnum):
    REGISTERED = "REGISTERED"
    QUEUED = "QUEUED"
    STT_DONE = "STT_DONE"
    STORED = "STORED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    RETRY_REQUESTED = "RETRY_REQUESTED"


class SourceType(StrEnum):
    DRIVE = "DRIVE"
    WEB = "WEB"


class Category(StrEnum):
    INQUIRY = "INQUIRY"
    COMPLAINT = "COMPLAINT"
    SUGGESTION = "SUGGESTION"
    EDUCATION = "EDUCATION"
    ETC = "ETC"


class ActionStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"


class LogStep(StrEnum):
    REGISTER = "REGISTER"
    QUEUE = "QUEUE"
    STT = "STT"
    GENAI = "GENAI"
    STORE = "STORE"
    EXCEL = "EXCEL"
    CRM = "CRM"
    RETRY = "RETRY"


class LogStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    RETRY = "RETRY"


# DB `analysis.category` 저장 값(현재 한글, app/models/analysis.py CATEGORIES) ↔ API 코드.
# 저장 값이 코드로 바뀌면 이 표만 고친다.
CATEGORY_DB_VALUES: dict[Category, str] = {
    Category.INQUIRY: "질의",
    Category.COMPLAINT: "불만",
    Category.SUGGESTION: "건의",
    Category.EDUCATION: "교육 내용",
    Category.ETC: "기타 문의",
}
_CATEGORY_BY_DB_VALUE = {value: code for code, value in CATEGORY_DB_VALUES.items()}


def _category_from_db(value: object) -> object:
    # DB 값이면 코드로 바꾸고, 그 밖의 값은 enum 검증에 맡긴다.
    return _CATEGORY_BY_DB_VALUE.get(value, value) if isinstance(value, str) else value


CategoryOut = Annotated[Category, BeforeValidator(_category_from_db)]

Q_MAX_LENGTH = 100
DATE_MIN = date(2000, 1, 1)
DATE_MAX = date(2100, 12, 31)

CallSort = Literal[
    "call_datetime",
    "-call_datetime",
    "created_at",
    "-created_at",
    "status_changed_at",
    "-status_changed_at",
]


# ---------------------------------------------------------------- 요청


@dataclass(frozen=True)
class CallListQuery:
    """`Depends(CallListQuery)`로 받는 목록 필터·정렬 쿼리. 페이지는 `PageParams`."""

    from_: Annotated[date | None, Query(alias="from", ge=DATE_MIN, le=DATE_MAX)] = None
    to: Annotated[date | None, Query(ge=DATE_MIN, le=DATE_MAX)] = None
    category: Annotated[list[Category] | None, Query()] = None
    agent: Annotated[str | None, Query()] = None
    client: Annotated[str | None, Query()] = None
    status: Annotated[list[CallStatus] | None, Query()] = None
    q: Annotated[str | None, Query(max_length=Q_MAX_LENGTH)] = None
    metadata_incomplete: Annotated[bool | None, Query()] = None
    sort: Annotated[CallSort, Query()] = "-created_at"

    def __post_init__(self) -> None:
        if self.from_ and self.to and self.from_ > self.to:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                detail={
                    "errors": [
                        {
                            "loc": ["query", "from"],
                            "msg": "from은 to보다 늦을 수 없습니다",
                            "type": "date_range",
                        }
                    ]
                },
            )

    @property
    def keyword(self) -> str | None:
        """앞뒤 공백을 뺀 검색어. 비면 None(필터 없음)."""
        stripped = (self.q or "").strip()
        return stripped or None


# ---------------------------------------------------------------- 응답


class CallBase(BaseModel):
    """목록·상세 공통 필드. `object_key`·`file_hash` 등 내부 값은 넣지 않는다."""

    id: int
    source_type: SourceType
    original_name: str
    duration_sec: int | None
    agent_name: str | None
    client_company: str | None
    call_datetime: KstDatetime | None
    metadata_incomplete: bool
    status: CallStatus
    status_changed_at: KstDatetime
    retry_count: int
    created_at: KstDatetime


class CallListItem(CallBase):
    # 분석 전이면 null
    category: CategoryOut | None
    question_summary: str | None
    action_status: ActionStatus | None


class Speaker(StrEnum):
    AGENT = "AGENT"
    CUSTOMER = "CUSTOMER"
    UNKNOWN = "UNKNOWN"


class SegmentOut(BaseModel):
    # STT 결과(stt/schema/call_schema.json)의 transcript.segments 항목.
    speaker: Speaker
    start_sec: float
    end_sec: float
    text: str


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    segments: list[SegmentOut]


class EntityOut(BaseModel):
    # STT 결과(stt/schema/call_schema.json)의 entities 항목.
    # type 값(PRODUCT·ORG·DATE·AMOUNT·REF_NO·OTHER)이 늘어도 500이 나지 않게 문자열로 둔다.
    type: str
    value: str


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: CategoryOut
    confidence: float | None  # DB NUMERIC(4,3) → Decimal → float
    question_summary: str | None
    action_summary: str | None
    # 아래 셋은 DB에서 NULL 허용(DEFAULT만 있음)이라 null일 수 있다.
    follow_up_required: bool | None
    action_status: ActionStatus | None
    entities: list[EntityOut] | None
    needs_review: bool | None


class ProcessingLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: LogStep
    status: LogStatus
    message: str | None
    created_at: KstDatetime


class CallDetail(CallBase):
    transcript: TranscriptOut | None
    analysis: AnalysisOut | None
    processing_log: list[ProcessingLogOut]
