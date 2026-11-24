"""FastAPI 애플리케이션 진입점.

라우터 등록은 각 기능(W-*, R-*)에서 추가한다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    RequestIdMiddleware,
    UnhandledErrorMiddleware,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Callcenter AI RPA Backend", version="0.1.0")
    register_exception_handlers(app)

    # add_middleware는 목록 맨 앞에 끼워 넣으므로 나중에 등록한 것이 바깥에서 실행된다.
    # 실행 순서(바깥 → 안): RequestId → CORS → UnhandledError → BodySizeLimit → 라우터
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes)
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
