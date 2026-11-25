"""헬스 체크 API: `GET /health` (인증 없음, 모니터링용)."""

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from starlette.datastructures import State

from app.api.deps import DbSession, get_audio_storage, get_inbox_writer
from app.infra.inbox import InboxWriter
from app.infra.storage import AudioStorage
from app.schemas.health import HealthResponse, HealthStatus
from app.services.health_service import HealthService, InboxCheckCache

router = APIRouter(tags=["health"])

_cache_init_lock = threading.Lock()


def _inbox_cache(state: State) -> InboxCheckCache:
    # create_app을 건드리지 않도록 첫 요청 때 만든다. 테스트는 미리 넣어 시계를 바꿀 수 있다.
    with _cache_init_lock:
        cache: InboxCheckCache | None = getattr(state, "inbox_health_cache", None)
        if cache is None:
            cache = InboxCheckCache()
            state.inbox_health_cache = cache
        return cache


def get_health_service(
    request: Request,
    session: DbSession,
    storage: Annotated[AudioStorage, Depends(get_audio_storage)],
    writer: Annotated[InboxWriter | None, Depends(get_inbox_writer)],
) -> HealthService:
    return HealthService(session, storage, writer, _inbox_cache(request.app.state))


@router.get(
    "/health",
    responses={503: {"model": HealthResponse, "description": "필수 구성요소(DB·음성 저장소) 실패"}},
)
def get_health(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    # def(동기): DB·파일시스템·Drive 확인이 모두 블로킹이라 워커 스레드에서 돌린다.
    result = service.check()
    response.headers["Cache-Control"] = "no-store"
    if result.status == HealthStatus.FAIL:
        response.status_code = 503
    return result
