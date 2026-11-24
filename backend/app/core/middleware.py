"""순수 ASGI 미들웨어: 요청 ID·접근 로그, 미처리 예외 500, 요청 크기 제한."""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ErrorCode, error_response

REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")

_access_log = structlog.stdlib.get_logger("app.access")
_error_log = structlog.stdlib.get_logger("app.error")


class RequestIdMiddleware:
    """X-Request-Id 결정·응답 헤더 부여, request_id 컨텍스트 바인딩, 요청 종료 접근 로그."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        if incoming is not None and _REQUEST_ID_PATTERN.fullmatch(incoming):
            request_id = incoming
        else:
            request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status = 500
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            status = 500  # 응답 시작 후 예외: 클라이언트는 중단된 응답을 받는다.
            raise
        finally:
            _access_log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 1),
                call_id=scope.get("state", {}).get("call_id"),
            )


class UnhandledErrorMiddleware:
    """처리되지 않은 예외를 §7.2 형식 500으로 바꾼다. CORS 안쪽에 둬야 CORS 헤더가 붙는다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            if response_started:
                raise
            _error_log.exception("unhandled_exception")
            await error_response(ErrorCode.INTERNAL_ERROR)(scope, receive, send)


class _BodyTooLargeError(StarletteHTTPException):
    # Starlette HTTPException 계열이어야 FastAPI 본문 읽기에서 400으로 바뀌지 않는다.
    def __init__(self) -> None:
        super().__init__(status_code=413)


class BodySizeLimitMiddleware:
    """요청 본문이 max_bytes를 넘으면 413. Content-Length 사전 검사 + 수신 중 누적 검사."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if (
            content_length is not None
            and content_length.isascii()
            and content_length.isdigit()
            and int(content_length) > self.max_bytes
        ):
            await error_response(ErrorCode.PAYLOAD_TOO_LARGE)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError()
            return message

        await self.app(scope, limited_receive, send)
