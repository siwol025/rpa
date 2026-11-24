"""웹 상담 조회 API: `GET /api/calls`, `GET /api/calls/{call_id}`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import get_call_service
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.call import CallDetail, CallListItem, CallListQuery
from app.schemas.common import Page, PageParams, error_responses
from app.services.call_service import CallService

BIGINT_MAX = 9_223_372_036_854_775_807

router = APIRouter(prefix="/api/calls", tags=["calls"])

CallServiceDep = Annotated[CallService, Depends(get_call_service)]


@router.get("")
def list_calls(
    query: Annotated[CallListQuery, Depends()],
    page: Annotated[PageParams, Depends()],
    service: CallServiceDep,
) -> Page[CallListItem]:
    return service.list_calls(query, page)


@router.get("/{call_id}", responses=error_responses(ErrorCode.NOT_FOUND))
def get_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: CallServiceDep,
) -> CallDetail:
    bind_call_id(request, call_id)
    return service.get_call(call_id)
