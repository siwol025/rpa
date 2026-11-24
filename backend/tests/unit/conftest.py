from collections.abc import Callable, Iterator
from typing import Annotated, Any

import pytest
import structlog
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import bind_call_id
from app.main import create_app


class Item(BaseModel):
    name: str
    count: int


def _build_test_app(**overrides: Any) -> FastAPI:
    """개발자 .env 영향 없이 앱을 만들고 테스트용 라우트를 붙인다."""
    app = create_app(Settings(_env_file=None, **overrides))

    @app.post("/echo")  # 본문 원문 길이 반환 (크기 제한)
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/items")  # JSON 본문 검증 (422, 405)
    def create_item(item: Item) -> Item:
        return item

    @app.post("/upload")  # multipart (400, 413)
    def upload(file: Annotated[UploadFile, File()]) -> dict[str, str]:
        return {"name": file.filename or ""}

    @app.get("/app-error")
    def raise_app_error() -> None:
        raise AppError(
            ErrorCode.DUPLICATE_FILE, detail={"existing_id": 123, "status": "REGISTERED"}
        )

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom-secret")

    @app.get("/calls/{call_id}")  # 동기 엔드포인트에서 call_id 바인딩 + 앱 로그
    def get_call(call_id: int, request: Request) -> dict[str, int]:
        bind_call_id(request, call_id)
        structlog.stdlib.get_logger("app.test").info("in endpoint")
        return {"call_id": call_id}

    return app


@pytest.fixture
def build_app() -> Callable[..., FastAPI]:
    return _build_test_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_build_test_app(max_upload_mb=1)) as test_client:
        yield test_client
