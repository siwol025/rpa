"""공통 예외와 에러 응답 매핑 (architecture.md §7.2)."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    NOT_FOUND = "NOT_FOUND"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN_IP = "FORBIDDEN_IP"
    INBOX_UNAVAILABLE = "INBOX_UNAVAILABLE"
    BAD_REQUEST = "BAD_REQUEST"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 코드 → (HTTP 상태, 기본 메시지)
_ERROR_SPECS: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.VALIDATION_ERROR: (422, "요청 형식이 올바르지 않습니다."),
    ErrorCode.DUPLICATE_FILE: (409, "이미 등록된 파일입니다."),
    ErrorCode.INVALID_STATE_TRANSITION: (409, "현재 상태에서 허용되지 않는 요청입니다."),
    ErrorCode.NOT_FOUND: (404, "대상을 찾을 수 없습니다."),
    ErrorCode.PAYLOAD_TOO_LARGE: (413, "요청 크기가 제한을 초과했습니다."),
    ErrorCode.UNSUPPORTED_MEDIA: (415, "허용되지 않은 파일 형식입니다."),
    ErrorCode.UNAUTHORIZED: (401, "인증에 실패했습니다."),
    ErrorCode.FORBIDDEN_IP: (403, "허용되지 않은 IP입니다."),
    ErrorCode.INBOX_UNAVAILABLE: (503, "업로드 저장소를 사용할 수 없습니다."),
    ErrorCode.BAD_REQUEST: (400, "잘못된 요청입니다."),
    ErrorCode.METHOD_NOT_ALLOWED: (405, "허용되지 않은 메서드입니다."),
    ErrorCode.INTERNAL_ERROR: (500, "서버 내부 오류가 발생했습니다."),
}

# HTTPException 상태 → 코드. 표에 없는 4xx는 BAD_REQUEST, 5xx는 INTERNAL_ERROR (상태 코드는 유지).
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
}


class AppError(Exception):
    """서비스·라우터가 던지는 공통 예외. HTTP 객체에 의존하지 않는다."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or _ERROR_SPECS[code][1]
        self.detail = detail
        super().__init__(self.message)


def error_response(
    code: ErrorCode,
    *,
    message: str | None = None,
    detail: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    """§7.2 형식 에러 응답. JSONResponse는 ASGI 앱이라 미들웨어에서도 그대로 보낼 수 있다."""
    default_status, default_message = _ERROR_SPECS[code]
    return JSONResponse(
        status_code=status_code or default_status,
        content={"code": code, "message": message or default_message, "detail": detail},
        headers=headers,
    )


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.code, message=exc.message, detail=exc.detail)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    fallback = ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST
    code = _STATUS_TO_CODE.get(exc.status_code, fallback)
    return error_response(code, headers=dict(exc.headers or {}), status_code=exc.status_code)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # input(요청 값 원문)·ctx·url은 PII·크기 문제로 내보내지 않는다.
    errors = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return error_response(ErrorCode.VALIDATION_ERROR, detail={"errors": errors})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
