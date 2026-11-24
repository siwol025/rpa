from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORIGIN = "http://localhost:5173"
MIB = 1024 * 1024


def _chunks(total: int, size: int = 64 * 1024) -> Iterator[bytes]:
    sent = 0
    while sent < total:
        chunk = min(size, total - sent)
        yield b"a" * chunk
        sent += chunk


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "status"),
    [
        ("GET", "/calls/1", {}, 200),
        ("GET", "/nope", {}, 404),
        ("GET", "/items", {}, 405),
        ("GET", "/app-error", {}, 409),
        ("POST", "/items", {"json": {"name": "x", "count": "many"}}, 422),
        ("POST", "/echo", {"content": b"a" * (MIB + 1)}, 413),
        ("POST", "/echo", {"content": "chunked"}, 413),
        ("GET", "/boom", {}, 500),
    ],
    ids=["ok", "not-found", "method", "app-error", "validation", "cl-413", "chunked-413", "500"],
)
def test_every_response_has_request_id_and_cors_headers(
    client: TestClient, method: str, path: str, kwargs: dict[str, Any], status: int
) -> None:
    if kwargs.get("content") == "chunked":
        kwargs = {"content": _chunks(MIB + 1)}

    response = client.request(method, path, headers={"Origin": ORIGIN}, **kwargs)

    assert response.status_code == status
    assert response.headers.get("X-Request-Id")
    assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN


def test_preflight_from_allowed_origin(client: TestClient) -> None:
    response = client.options(
        "/items",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert response.headers.get("X-Request-Id")


def test_request_id_exposed_without_credentials(client: TestClient) -> None:
    response = client.get("/calls/1", headers={"Origin": ORIGIN})

    assert "X-Request-Id" in response.headers["Access-Control-Expose-Headers"]
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_disallowed_origin_gets_no_cors_header(client: TestClient) -> None:
    response = client.get("/calls/1", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert response.headers.get("X-Request-Id")


def test_preflight_from_disallowed_origin_rejected(client: TestClient) -> None:
    response = client.options(
        "/items",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 400
    assert response.headers.get("X-Request-Id")


def test_allowed_origins_follow_settings(build_app: Callable[..., FastAPI]) -> None:
    client = TestClient(build_app(cors_origins=["http://other:3000"]))

    response = client.get("/calls/1", headers={"Origin": "http://other:3000"})

    assert response.headers["Access-Control-Allow-Origin"] == "http://other:3000"
