"""웹 음성 재생 API: `GET /api/calls/{call_id}/audio` (HTTP Range)."""

from collections.abc import Iterator
from typing import Annotated, Any, BinaryIO

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_audio_storage, get_db
from app.api.web.calls import BIGINT_MAX
from app.core.errors import ErrorCode, error_response
from app.core.http_range import RangeNotSatisfiableError
from app.core.logging import bind_call_id
from app.infra.storage import AudioStorage
from app.schemas.common import error_responses
from app.services.audio_service import AudioService

CHUNK_SIZE = 64 * 1024  # Starlette FileResponse와 같은 크기

router = APIRouter(prefix="/api/calls", tags=["calls"])


def get_audio_service(
    # scope="function": 엔드포인트 함수가 끝나면 세션을 닫는다. 기본(request)이면 음성 전송이
    # 끝날 때까지(브라우저 재생 속도로 수 분) DB 연결을 붙잡는다.
    session: Annotated[Session, Depends(get_db, scope="function")],
    storage: Annotated[AudioStorage, Depends(get_audio_storage)],
) -> AudioService:
    return AudioService(session, storage)


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]

_BINARY = {"schema": {"type": "string", "format": "binary"}}
_AUDIO_CONTENT = {"audio/wav": _BINARY, "audio/mpeg": _BINARY}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "전체 음성 (Range 없음·무시)", "content": _AUDIO_CONTENT},
    206: {"description": "요청 구간 (단일 바이트 범위)", "content": _AUDIO_CONTENT},
    **error_responses(ErrorCode.NOT_FOUND, ErrorCode.RANGE_NOT_SATISFIABLE),
}


def _iter_chunks(stream: BinaryIO) -> Iterator[bytes]:
    # 제너레이터 안에서 닫아야 전송 중 클라이언트가 끊어도 파일 핸들이 남지 않는다.
    with stream:
        while chunk := stream.read(CHUNK_SIZE):
            yield chunk


@router.get(
    "/{call_id}/audio",
    response_class=StreamingResponse,
    response_model=None,
    responses=_RESPONSES,
)
def get_call_audio(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: AudioServiceDep,
) -> Response:
    bind_call_id(request, call_id)
    # 검증자(ETag·Last-Modified)를 발급하지 않으므로 If-Range는 일치할 수 없다 → Range 무시.
    range_header = None if "if-range" in request.headers else request.headers.get("range")
    try:
        audio = service.open_audio(call_id, range_header)
    except RangeNotSatisfiableError as exc:
        # AppError는 응답 헤더를 실을 수 없어 Content-Range가 필요한 416은 여기서 만든다.
        return error_response(
            ErrorCode.RANGE_NOT_SATISFIABLE, headers={"Content-Range": f"bytes */{exc.size}"}
        )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(audio.length),
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'inline; filename="call-{call_id}{audio.extension}"',
        "X-Content-Type-Options": "nosniff",
    }
    if audio.byte_range is not None:
        start, end = audio.byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{audio.size}"
    return StreamingResponse(
        _iter_chunks(audio.stream),
        status_code=200 if audio.byte_range is None else 206,
        media_type=audio.media_type,
        headers=headers,
    )
