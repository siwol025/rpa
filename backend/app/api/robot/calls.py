"""로봇 API: 등록 `POST /api/robot/calls`. 인증은 RobotAuthMiddleware가 경로 기준으로 처리한다."""

from collections.abc import Iterator
from typing import Annotated, BinaryIO, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_robot_service
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.common import error_responses
from app.schemas.robot import (
    BIGINT_MAX,
    RobotAnalysisRequest,
    RobotCallForm,
    RobotCallRegistered,
    RobotCallStatus,
    RobotLogRequest,
    RobotQueuedRequest,
    RobotRetryTarget,
    RobotRetryTargets,
    RobotTranscriptRequest,
)
from app.services.robot_service import RobotService

router = APIRouter(
    prefix="/api/robot/calls",
    tags=["robot"],
    responses=error_responses(ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN_IP),
)

RobotServiceDep = Annotated[RobotService, Depends(get_robot_service)]
CallIdPath = Annotated[int, Path(ge=1, le=BIGINT_MAX)]


@router.post(
    "",
    status_code=201,
    responses=error_responses(
        ErrorCode.DUPLICATE_FILE, ErrorCode.PAYLOAD_TOO_LARGE, ErrorCode.UNSUPPORTED_MEDIA
    ),
)
def register_call(
    file: Annotated[UploadFile, File(description="녹취 음성 파일(wav, mp3)")],
    form: Annotated[RobotCallForm, Form()],
    request: Request,
    service: RobotServiceDep,
) -> RobotCallRegistered:
    """음성 사본을 저장하고 `REGISTERED`로 등록한다. 텍스트 변환 전에 먼저 호출한다."""
    call = service.register_call(file.file, form)
    bind_call_id(request, call.id)
    return RobotCallRegistered(call_id=call.id)


@router.patch(
    "/{call_id}/status",
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
)
def mark_call_queued(
    call_id: CallIdPath,
    body: RobotQueuedRequest,
    request: Request,
    service: RobotServiceDep,
) -> RobotCallStatus:
    """Queue에 추가한 뒤 `QUEUED`로 보고한다. `REGISTERED`·`RETRY_REQUESTED`에서만 허용한다."""
    bind_call_id(request, call_id)
    call = service.mark_queued(call_id, body.queue_item_id)
    return RobotCallStatus(call_id=call.id, status=call.status)


@router.put(
    "/{call_id}/transcript",
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
)
def put_transcript(
    call_id: CallIdPath,
    body: RobotTranscriptRequest,
    request: Request,
    service: RobotServiceDep,
) -> RobotCallStatus:
    """전사를 적재하고 `STT_DONE`으로 바꾼다. 같은 내용을 다시 보내도 같은 결과(멱등)다."""
    bind_call_id(request, call_id)
    call = service.put_transcript(call_id, body)
    return RobotCallStatus(call_id=call.id, status=call.status)


@router.put(
    "/{call_id}/analysis",
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
)
def put_analysis(
    call_id: CallIdPath,
    body: RobotAnalysisRequest,
    request: Request,
    service: RobotServiceDep,
) -> RobotCallStatus:
    """GenAI 분석 결과를 적재한다. `status`가 SUCCESS면 `STORED`, NEEDS_REVIEW면 `NEEDS_REVIEW`.

    같은 내용을 다시 보내도 같은 결과(멱등)다.
    """
    bind_call_id(request, call_id)
    call = service.put_analysis(call_id, body)
    return RobotCallStatus(call_id=call.id, status=call.status)


@router.post(
    "/{call_id}/logs",
    status_code=201,
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
)
def post_call_log(
    call_id: CallIdPath,
    body: RobotLogRequest,
    request: Request,
    service: RobotServiceDep,
) -> RobotCallStatus:
    """단계 로그를 남긴다. 처리 중인 건에 `status=FAIL`을 보내면 `FAILED`로 바뀐다."""
    bind_call_id(request, call_id)
    call = service.add_log(call_id, body)
    return RobotCallStatus(call_id=call.id, status=call.status)


@router.get("", responses=error_responses())
def list_retry_targets(
    service: RobotServiceDep,
    status: Annotated[
        Literal["RETRY_REQUESTED"], Query(description="재처리 대상만 조회할 수 있다")
    ] = "RETRY_REQUESTED",
) -> RobotRetryTargets:
    """다음 Dispatcher 주기에 다시 Queue에 넣을 재처리 요청 건 (오래 기다린 순, 최대 100건)."""
    calls = service.list_retry_targets()
    return RobotRetryTargets(
        items=[RobotRetryTarget(call_id=c.id, retry_count=c.retry_count) for c in calls]
    )


_MEDIA_TYPE_BY_EXTENSION = {".wav": "audio/wav", ".mp3": "audio/mpeg"}
_CHUNK = 64 * 1024


def _iter_and_close(stream: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := stream.read(_CHUNK):
            yield chunk
    finally:
        stream.close()


@router.get(
    "/{call_id}/audio",
    responses={
        200: {"content": {"audio/wav": {}, "audio/mpeg": {}}, "description": "음성 사본"},
        **error_responses(ErrorCode.NOT_FOUND),
    },
)
def download_audio(
    call_id: CallIdPath, request: Request, service: RobotServiceDep
) -> StreamingResponse:
    """재처리를 위해 서버의 음성 사본을 내려받는다 (원본 폴더에서 파일이 옮겨졌어도 된다)."""
    bind_call_id(request, call_id)
    stream, size, extension = service.open_audio(call_id)
    return StreamingResponse(
        _iter_and_close(stream),
        media_type=_MEDIA_TYPE_BY_EXTENSION.get(extension, "application/octet-stream"),
        headers={
            "Content-Length": str(size),
            "Content-Disposition": f'attachment; filename="call-{call_id}{extension}"',
        },
    )
