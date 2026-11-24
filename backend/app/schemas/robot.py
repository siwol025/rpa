"""로봇(UiPath) API 요청·응답 모델. 규약은 docs/api/convention.md."""

import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.call import CallStatus, Category, SourceType, Speaker
from app.schemas.common import KstDatetime

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _blank_to_none(value: Any) -> Any:
    """multipart는 값이 없는 필드를 빈 문자열로 보낼 수 있다. 빈 값은 '없음'으로 본다."""
    if isinstance(value, str) and not value.strip():
        return None
    return value.strip() if isinstance(value, str) else value


# 길이 제한은 str 쪽에만 건다 (`str | None` 전체에 걸면 None이 된 뒤 제한이 적용돼 500).
OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]
OptionalName50 = Annotated[
    Annotated[str, Field(max_length=50)] | None, BeforeValidator(_blank_to_none)
]
OptionalName100 = Annotated[
    Annotated[str, Field(max_length=100)] | None, BeforeValidator(_blank_to_none)
]


class RobotCallForm(BaseModel):
    """`POST /api/robot/calls`의 multipart 폼 필드 (파일은 `file`로 따로 받는다).

    담당자·통화 일시·고객사는 파일명에서 못 뽑았으면 비워 보낸다. 담당자나 통화 일시가
    비면 서버가 `metadata_incomplete=true`로 등록하고 웹에서 보정한다.
    """

    file_hash: str = Field(
        description="파일 내용의 SHA-256(16진수 64자). 서버가 다시 계산해 비교한다."
    )
    original_name: Annotated[str, Field(min_length=1, max_length=255)]
    source_type: SourceType
    source_ref: OptionalText = Field(default=None, description="Drive 파일 ID 등 출처 식별자")
    call_datetime: Annotated[KstDatetime | None, BeforeValidator(_blank_to_none)] = None
    agent_name: OptionalName50 = None
    client_company: OptionalName100 = None

    @field_validator("file_hash")
    @classmethod
    def _normalize_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_HEX.fullmatch(normalized):
            raise ValueError("file_hash는 SHA-256 16진수 64자여야 합니다")
        return normalized

    @field_validator("original_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("original_name이 비어 있습니다")
        return stripped


class RobotCallRegistered(BaseModel):
    call_id: int


BIGINT_MAX = 9_223_372_036_854_775_807


class RobotQueuedRequest(BaseModel):
    """`PATCH /api/robot/calls/{id}/status` 본문. 로봇이 보낼 수 있는 전이는 QUEUED뿐이다."""

    status: Literal["QUEUED"]
    queue_item_id: int = Field(ge=1, le=BIGINT_MAX, description="Orchestrator Queue Item ID")


class RobotCallStatus(BaseModel):
    """상태를 바꾸는 동작의 결과 (`{call_id, status}`)."""

    call_id: int
    status: CallStatus


class SegmentIn(BaseModel):
    """전사 구간 한 줄 (`stt/schema/call_schema.json`의 `transcript.segments` 항목)."""

    speaker: Speaker
    start_sec: float = Field(ge=0, allow_inf_nan=False, description="구간 시작(초)")
    end_sec: float = Field(ge=0, allow_inf_nan=False, description="구간 끝(초)")
    text: str

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "SegmentIn":
        if self.end_sec < self.start_sec:
            raise ValueError("end_sec는 start_sec보다 작을 수 없습니다")
        return self


class RobotTranscriptRequest(BaseModel):
    """`PUT /api/robot/calls/{id}/transcript` 본문. PII 마스킹이 끝난 전사만 보낸다."""

    segments: list[SegmentIn]
    full_text: str | None = Field(
        default=None,
        description="마스킹 후 '[상담원] … / [고객] …' 전체 텍스트. 키워드 검색에 쓰인다.",
    )
    stt_engine: Annotated[str, Field(max_length=50)] | None = None


class AnalysisType(StrEnum):
    """GenAI 결과의 `type` 값 (`stt/schema/call_schema.json`). 코드 확정(BE-A05) 전 상태다."""

    INQUIRY = "INQUIRY"
    COMPLAINT = "COMPLAINT"
    SUGGESTION = "SUGGESTION"
    TRAINING = "TRAINING"
    OTHER = "OTHER"


# GenAI 코드 → 웹 API 코드 (docs/api/convention.md §5.3). DB에는 이 코드의 한글 값이 저장된다.
CATEGORY_BY_ANALYSIS_TYPE: dict[AnalysisType, Category] = {
    AnalysisType.INQUIRY: Category.INQUIRY,
    AnalysisType.COMPLAINT: Category.COMPLAINT,
    AnalysisType.SUGGESTION: Category.SUGGESTION,
    AnalysisType.TRAINING: Category.EDUCATION,
    AnalysisType.OTHER: Category.ETC,
}


class EntityIn(BaseModel):
    type: str
    value: Annotated[str, Field(min_length=1)]


class ProcessingIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt_version: Annotated[str, Field(max_length=20)] | None = None


class RobotAnalysisRequest(BaseModel):
    """`PUT /api/robot/calls/{id}/analysis` 본문: GenAI 결과 JSON을 그대로 보낸다.

    서버가 쓰는 필드만 검증하고, 그 밖의 필드(summary·sentiment·keywords 등)는 허용해
    `analysis.raw_json`에 원본으로 보존한다. 실패 건(`FAILED`)은 로그 API로 보고한다.
    """

    model_config = ConfigDict(extra="allow")

    # 형식이 바뀐 결과를 현재 매핑대로 잘못 저장하지 않도록 지원하는 버전만 받는다.
    schema_version: Literal["1.0"]
    status: Literal["SUCCESS", "NEEDS_REVIEW"]
    type: AnalysisType
    type_confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    customer_question: str | None = None
    agent_action: str | None = None
    follow_up_required: bool | None = None
    entities: list[EntityIn] = Field(default_factory=list)
    processing: ProcessingIn | None = None
