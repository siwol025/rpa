"""웹 상담 조회 API: `GET /api/calls`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_call_service
from app.schemas.call import CallListItem, CallListQuery
from app.schemas.common import Page, PageParams
from app.services.call_service import CallService

router = APIRouter(prefix="/api/calls", tags=["calls"])

CallServiceDep = Annotated[CallService, Depends(get_call_service)]


@router.get("")
def list_calls(
    query: Annotated[CallListQuery, Depends()],
    page: Annotated[PageParams, Depends()],
    service: CallServiceDep,
) -> Page[CallListItem]:
    return service.list_calls(query, page)
