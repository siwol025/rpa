"""로봇 API: 등록 `POST /api/robot/calls`. 인증은 RobotAuthMiddleware가 경로 기준으로 처리한다."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.deps import get_robot_service
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.common import error_responses
from app.schemas.robot import RobotCallForm, RobotCallRegistered
from app.services.robot_service import RobotService

router = APIRouter(
    prefix="/api/robot/calls",
    tags=["robot"],
    responses=error_responses(ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN_IP),
)

RobotServiceDep = Annotated[RobotService, Depends(get_robot_service)]


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
