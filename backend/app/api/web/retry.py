"""웹 재처리 요청 API: `POST /api/calls/{call_id}/retry`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import DbSession, get_settings_from_app
from app.api.web.calls import BIGINT_MAX
from app.core.config import Settings
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.common import error_responses
from app.schemas.retry import RetryResult
from app.services.retry_service import RetryService

router = APIRouter(prefix="/api/calls", tags=["calls"])


def get_retry_service(
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> RetryService:
    # 정체 기준은 create_app에 넘긴 설정을 쓴다(get_settings()의 .env 값이 아니라).
    return RetryService(session, stale_threshold_min=settings.stale_threshold_min)


RetryServiceDep = Annotated[RetryService, Depends(get_retry_service)]


@router.post(
    "/{call_id}/retry",
    status_code=202,
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
)
def retry_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: RetryServiceDep,
) -> RetryResult:
    """재처리를 요청한다. 상태만 `RETRY_REQUESTED`로 바꾸고 다음 Dispatcher 주기에 반영된다."""
    bind_call_id(request, call_id)
    return service.request_retry(call_id)
