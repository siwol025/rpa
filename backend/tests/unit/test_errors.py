from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Response

from app.core.errors import AppError, ErrorCode


def test_unknown_route_returns_not_found_error_body_with_request_id(client: TestClient) -> None:
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }
    assert response.headers.get("X-Request-Id")


def assert_error(response: Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert isinstance(body["message"], str)
    assert body["message"]
    assert "detail" in body
    return body


def test_app_error_maps_to_code_status_and_detail(client: TestClient) -> None:
    body = assert_error(client.get("/app-error"), 409, "DUPLICATE_FILE")

    assert body["message"] == "이미 등록된 파일입니다."
    assert body["detail"] == {"existing_id": 123, "status": "REGISTERED"}


def test_app_error_message_override(build_app: Callable[..., FastAPI]) -> None:
    app = build_app()

    @app.get("/custom-message")
    def raise_with_message() -> None:
        raise AppError(ErrorCode.NOT_FOUND, message="상담 건을 찾을 수 없습니다.")

    body = assert_error(TestClient(app).get("/custom-message"), 404, "NOT_FOUND")

    assert body["message"] == "상담 건을 찾을 수 없습니다."


def test_method_not_allowed_keeps_allow_header(client: TestClient) -> None:
    response = client.get("/items")

    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert response.headers["Allow"] == "POST"


def test_validation_error_hides_input_ctx_and_url(client: TestClient) -> None:
    response = client.post("/items", json={"name": "홍길동", "count": "many"})

    body = assert_error(response, 422, "VALIDATION_ERROR")
    assert body["detail"]["errors"] == [
        {"loc": ["body", "count"], "msg": body["detail"]["errors"][0]["msg"], "type": "int_parsing"}
    ]
    assert isinstance(body["detail"]["errors"][0]["msg"], str)
    for hidden in ("many", "input", "ctx", "url"):
        assert hidden not in response.text


def test_malformed_json_is_validation_error(client: TestClient) -> None:
    response = client.post("/items", content=b"{bad", headers={"Content-Type": "application/json"})

    body = assert_error(response, 422, "VALIDATION_ERROR")
    assert body["detail"]["errors"][0]["type"] == "json_invalid"


def test_broken_multipart_body_is_bad_request(client: TestClient) -> None:
    response = client.post(
        "/upload",
        content=b"garbage",
        headers={"Content-Type": "multipart/form-data; boundary=xyz"},
    )

    body = assert_error(response, 400, "BAD_REQUEST")
    assert body["message"] == "잘못된 요청입니다."


def test_http_exception_401_keeps_headers(build_app: Callable[..., FastAPI]) -> None:
    app = build_app()

    @app.get("/auth")
    def unauthorized() -> None:
        raise HTTPException(401, headers={"WWW-Authenticate": "APIKey"})

    response = TestClient(app).get("/auth")

    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == "APIKey"


def test_unmapped_4xx_keeps_status_with_bad_request_code(
    build_app: Callable[..., FastAPI],
) -> None:
    app = build_app()

    @app.get("/limited")
    def too_many() -> None:
        raise HTTPException(429)

    assert_error(TestClient(app).get("/limited"), 429, "BAD_REQUEST")


def test_unhandled_exception_becomes_internal_error(client: TestClient) -> None:
    response = client.get("/boom")

    body = assert_error(response, 500, "INTERNAL_ERROR")
    assert body["message"] == "서버 내부 오류가 발생했습니다."
    assert "boom-secret" not in response.text
    assert response.headers.get("X-Request-Id")
