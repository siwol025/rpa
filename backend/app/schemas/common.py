"""API 공통 스키마: 에러 응답, 목록(페이지), 시간(KST) 직렬화."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Query
from pydantic import AfterValidator, BaseModel, PlainSerializer

from app.core.errors import ErrorCode, error_status

KST = timezone(timedelta(hours=9))

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
PAGE_MAX = 10_000


# ---------------------------------------------------------------- 시간


def _assume_kst(value: datetime) -> datetime:
    # 오프셋 없는 입력은 KST로 본다. 오프셋이 있으면 그대로 둔다.
    return value.replace(tzinfo=KST) if value.tzinfo is None else value


def _to_kst(value: datetime) -> datetime:
    return value.astimezone(KST).replace(microsecond=0)


KstDatetime = Annotated[
    datetime,
    AfterValidator(_assume_kst),
    PlainSerializer(_to_kst, return_type=datetime, when_used="json"),
]
"""요청·응답 모델의 시각 필드 타입. JSON 출력은 항상 초 단위 ISO 8601 `+09:00`."""


# ---------------------------------------------------------------- 에러


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: dict[str, Any] | None


class ValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorDetail(BaseModel):
    errors: list[ValidationErrorItem]


class ValidationErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: ValidationErrorDetail


class DuplicateFileDetail(BaseModel):
    existing_id: int
    status: str


class DuplicateFileErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: DuplicateFileDetail


_DEDICATED_MODELS: dict[ErrorCode, type[BaseModel]] = {
    ErrorCode.VALIDATION_ERROR: ValidationErrorResponse,
    ErrorCode.DUPLICATE_FILE: DuplicateFileErrorResponse,
}


def error_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """라우터·데코레이터 `responses=` 값. 같은 HTTP 상태의 코드는 한 항목으로 묶는다."""
    grouped: dict[int, list[ErrorCode]] = {}
    for code in dict.fromkeys(codes):
        grouped.setdefault(error_status(code), []).append(code)
    responses: dict[int | str, dict[str, Any]] = {}
    for status, group in grouped.items():
        model = _DEDICATED_MODELS.get(group[0], ErrorResponse) if len(group) == 1 else ErrorResponse
        responses[status] = {"model": model, "description": ", ".join(group)}
    return responses


# ---------------------------------------------------------------- 목록


class Page[T](BaseModel):
    items: list[T]
    page: int
    size: int
    total: int


@dataclass(frozen=True)
class PageParams:
    """`Depends(PageParams)`로 받는 `page`·`size` 쿼리."""

    page: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 1
    size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = PAGE_SIZE_DEFAULT

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
