"""웹 상담 API: 목록·상세 조회, 삭제(`DELETE`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import get_call_service
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.call import CallDetail, CallListItem, CallListQuery, EditorName
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


@router.delete("/{call_id}", status_code=204, responses=error_responses(ErrorCode.NOT_FOUND))
def delete_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: CallServiceDep,
    editor: Annotated[EditorName | None, Query()] = None,
) -> None:
    bind_call_id(request, call_id)
    service.delete_call(call_id, editor=editor)
