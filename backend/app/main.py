"""FastAPI 애플리케이션 진입점.

라우터 등록은 각 기능(W-*, R-*)에서 추가한다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.robot import calls as robot_calls
from app.api.robot.auth import RobotAuthMiddleware
from app.api.web import calls, stats
from app.core.config import Settings, get_settings
from app.core.db import create_session_factory
from app.core.errors import ErrorCode, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    RequestIdMiddleware,
    UnhandledErrorMiddleware,
)
from app.infra.inbox import create_inbox_writer
from app.infra.storage import create_audio_storage
from app.schemas.common import error_responses


def _operation_id(route: APIRoute) -> str:
    # 프론트 타입 생성기가 함수 이름으로 쓴다. 라우트 함수 이름은 앱 전체에서 고유해야 한다.
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Callcenter AI RPA Backend",
        version="0.1.0",
        # openapi_url=None이면 /docs·/redoc·/openapi.json이 모두 꺼진다 (app.openapi()는 동작).
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        # 모든 operation의 422·500을 실제 에러 형식으로 문서화한다 (FastAPI 기본 422 대체).
        responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.INTERNAL_ERROR),
        generate_unique_id_function=_operation_id,
    )
    register_exception_handlers(app)
    app.state.settings = settings
    # 엔진 생성만으로는 DB에 연결하지 않는다 (OpenAPI 내보내기·단위 테스트는 DB 없이 동작).
    app.state.session_factory = create_session_factory(settings.database_url)
    # 키 파일·Drive 접근은 첫 업로드·헬스 체크 때 확인한다 (Drive 문제로 시작이 막히지 않음).
    app.state.inbox_writer = create_inbox_writer(settings)
    # 폴더는 첫 저장·헬스 체크 때 만든다 (시작 시 디스크를 건드리지 않는다).
    app.state.audio_storage = create_audio_storage(settings)
    app.include_router(calls.router)
    app.include_router(robot_calls.router)
    app.include_router(stats.router)

    # add_middleware는 목록 맨 앞에 끼워 넣으므로 나중에 등록한 것이 바깥에서 실행된다.
    # 실행 순서(바깥 → 안): RequestId → CORS → UnhandledError → RobotAuth → BodySizeLimit → 라우터
    # 인증 전에는 본문을 읽지 않도록 RobotAuth를 BodySizeLimit보다 바깥에 둔다.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes)
    app.add_middleware(
        RobotAuthMiddleware,
        api_keys=settings.robot_api_keys,
        allowed_ips=settings.robot_allowed_ips,
    )
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIdMiddleware)
    return app


app = create_app()
