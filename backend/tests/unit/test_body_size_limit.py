import asyncio
from collections.abc import Callable, Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message

MIB = 1024 * 1024


def test_body_at_limit_is_accepted(client: TestClient) -> None:
    response = client.post("/echo", content=b"a" * MIB)

    assert response.status_code == 200
    assert response.json() == {"size": MIB}


def test_content_length_over_limit_is_payload_too_large(client: TestClient) -> None:
    response = client.post("/echo", content=b"a" * (MIB + 1))

    assert response.status_code == 413
    assert response.json() == {
        "code": "PAYLOAD_TOO_LARGE",
        "message": "요청 크기가 제한을 초과했습니다.",
        "detail": None,
    }


def test_oversized_body_checked_before_routing(client: TestClient) -> None:
    response = client.post("/nope", content=b"a" * (MIB + 1))

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def _chunks(total: int, size: int = 64 * 1024) -> Iterator[bytes]:
    sent = 0
    while sent < total:
        chunk = min(size, total - sent)
        yield b"a" * chunk
        sent += chunk


def test_chunked_body_over_limit_is_payload_too_large(client: TestClient) -> None:
    response = client.post("/echo", content=_chunks(MIB + 1))

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_chunked_json_over_limit_is_not_turned_into_bad_request(client: TestClient) -> None:
    response = client.post(
        "/items", content=_chunks(MIB + 1), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_chunked_body_at_limit_is_accepted(client: TestClient) -> None:
    response = client.post("/echo", content=_chunks(MIB))

    assert response.status_code == 200
    assert response.json() == {"size": MIB}


def test_multipart_upload_over_limit_is_payload_too_large(client: TestClient) -> None:
    response = client.post("/upload", files={"file": ("a.wav", b"a" * (MIB + 1))})

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_limit_follows_settings(build_app: Callable[..., FastAPI]) -> None:
    response = TestClient(build_app(max_upload_mb=2)).post("/echo", content=b"a" * (MIB * 3 // 2))

    assert response.status_code == 200


def test_non_ascii_digit_content_length_is_not_server_error(
    build_app: Callable[..., FastAPI],
) -> None:
    # "²"는 str.isdigit()가 True지만 int()로 변환할 수 없다.
    app = build_app()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/echo",
        "raw_path": b"/echo",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-length", "²".encode("latin-1"))],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))

    assert messages[0]["status"] != 500
