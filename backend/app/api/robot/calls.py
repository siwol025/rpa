"""로봇 API: 등록 `POST /api/robot/calls`. 인증은 RobotAuthMiddleware가 경로 기준으로 처리한다."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile

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
