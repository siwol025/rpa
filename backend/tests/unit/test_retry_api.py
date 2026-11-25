"""재처리 요청 라우터 단위 테스트: 서비스를 가짜로 바꿔 DB 없이 경로 검증·응답·OpenAPI를 본다."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web.calls import BIGINT_MAX
from app.api.web.retry import get_retry_service
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.schemas.call import CallStatus
from app.schemas.retry import RetryResult
from app.services.state_machine import InvalidTransition

S = CallStatus


class FakeRetryService:
    def __init__(self) -> None:
        self.requested: list[int] = []

    def request_retry(self, call_id: int) -> RetryResult:
        self.requested.append(call_id)
        if call_id == 404:
            raise AppError(ErrorCode.NOT_FOUND)
        if call_id == 409:
            raise InvalidTransition(S.QUEUED, S.RETRY_REQUESTED)
        return RetryResult(call_id=call_id, status=S.RETRY_REQUESTED, retry_count=1)


@pytest.fixture
def fake() -> FakeRetryService:
    return FakeRetryService()


@pytest.fixture
def api(build_app: Callable[..., FastAPI], fake: FakeRetryService) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_retry_service] = lambda: fake
    with TestClient(app) as client:
        yield client


def test_retry_returns_202_with_result(api: TestClient, fake: FakeRetryService) -> None:
    response = api.post("/api/calls/7/retry")

    assert response.status_code == 202
    assert response.json() == {"call_id": 7, "status": "RETRY_REQUESTED", "retry_count": 1}
    assert fake.requested == [7]


def test_retry_ignores_request_body(api: TestClient, fake: FakeRetryService) -> None:
    response = api.post("/api/calls/7/retry", json={"reason": "무시됨"})

    assert response.status_code == 202
    assert fake.requested == [7]


def test_retry_not_found_is_404(api: TestClient) -> None:
    response = api.post("/api/calls/404/retry")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }


def test_retry_invalid_transition_is_409_with_statuses(api: TestClient) -> None:
    response = api.post("/api/calls/409/retry")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"] == {"current_status": "QUEUED", "requested_status": "RETRY_REQUESTED"}


@pytest.mark.parametrize("call_id", ["0", "-1", str(BIGINT_MAX + 1), "abc"])
def test_retry_rejects_invalid_path_id(
    api: TestClient, fake: FakeRetryService, call_id: str
) -> None:
    response = api.post(f"/api/calls/{call_id}/retry")

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["loc"] == ["path", "call_id"]
    assert fake.requested == []


def test_retry_get_is_405(api: TestClient) -> None:
    assert api.get("/api/calls/7/retry").status_code == 405


# ---------------------------------------------------------------- OpenAPI


@pytest.fixture
def operation() -> dict[str, Any]:
    spec = create_app(Settings(_env_file=None)).openapi()
    op: dict[str, Any] = spec["paths"]["/api/calls/{call_id}/retry"]["post"]
    return op


def test_openapi_documents_retry_operation(operation: dict[str, Any]) -> None:
    responses = operation["responses"]

    assert operation["operationId"] == "retry_call"
    assert operation["tags"] == ["calls"]
    assert "requestBody" not in operation
    assert set(responses) == {"202", "404", "409", "422", "500"}
    schema_ref = responses["202"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/RetryResult"
    assert responses["409"]["description"] == "INVALID_STATE_TRANSITION"


def test_openapi_retry_result_schema() -> None:
    schema = create_app(Settings(_env_file=None)).openapi()["components"]["schemas"]["RetryResult"]

    assert set(schema["required"]) == {"call_id", "status", "retry_count"}
    assert schema["properties"]["status"]["$ref"] == "#/components/schemas/CallStatus"
