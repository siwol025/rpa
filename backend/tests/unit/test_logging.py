import json
import logging
import logging.config
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from uvicorn.config import LOGGING_CONFIG


def _log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def _access_logs(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [line for line in lines if line.get("logger") == "app.access"]


def test_access_log_has_request_fields(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app())

    client.get("/calls/42?q=secret", headers={"X-Request-Id": "rid-1"})

    access = _access_logs(_log_lines(capsys))
    assert len(access) == 1
    log = access[0]
    assert log["event"] == "request"
    assert log["request_id"] == "rid-1"
    assert log["method"] == "GET"
    assert log["path"] == "/calls/42"
    assert log["status"] == 200
    assert isinstance(log["latency_ms"], float)
    assert log["level"] == "info"
    assert log["timestamp"].endswith("Z")


def test_access_log_includes_call_id_bound_in_sync_endpoint(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app())

    client.get("/calls/42?q=secret", headers={"X-Request-Id": "rid-1"})

    (access,) = _access_logs(_log_lines(capsys))
    assert access["call_id"] == 42


def test_app_log_in_endpoint_has_request_and_call_id(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app())

    client.get("/calls/42?q=secret", headers={"X-Request-Id": "rid-1"})

    (app_log,) = [line for line in _log_lines(capsys) if line.get("logger") == "app.test"]
    assert app_log["event"] == "in endpoint"
    assert app_log["request_id"] == "rid-1"
    assert app_log["call_id"] == 42


def test_query_string_is_not_logged(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app())

    client.get("/calls/42?q=secret", headers={"X-Request-Id": "rid-1"})

    assert "secret" not in capsys.readouterr().out


def test_unhandled_exception_is_logged_with_traceback(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app())

    client.get("/boom", headers={"X-Request-Id": "rid-2"})

    lines = _log_lines(capsys)
    (error,) = [line for line in lines if line.get("logger") == "app.error"]
    assert error["level"] == "error"
    assert error["request_id"] == "rid-2"
    assert "RuntimeError" in error["exception"]
    (access,) = _access_logs(lines)
    assert access["status"] == 500


def test_payload_too_large_is_access_logged(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app(max_upload_mb=1))

    client.post("/echo", content=b"a" * (1024 * 1024 + 1))

    (access,) = _access_logs(_log_lines(capsys))
    assert access["status"] == 413


def test_context_does_not_leak_between_requests(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app())

    client.get("/calls/7")
    client.get("/nope")

    first, second = _access_logs(_log_lines(capsys))
    assert second["call_id"] is None
    assert first["request_id"] != second["request_id"]


def test_repeated_create_app_does_not_duplicate_handlers(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    build_app()
    client = TestClient(build_app())

    client.get("/calls/1")

    assert len(_access_logs(_log_lines(capsys))) == 1


def test_uvicorn_logs_use_same_json_format(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    # Uvicorn은 앱 import 전에 자체 dictConfig를 적용한다.
    logging.config.dictConfig(LOGGING_CONFIG)
    build_app()

    logging.getLogger("uvicorn.error").warning("x")

    (line,) = [line for line in _log_lines(capsys) if line.get("logger") == "uvicorn.error"]
    assert line["level"] == "warning"
    assert line["event"] == "x"


def test_log_level_setting_filters_info(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    client = TestClient(build_app(log_level="WARNING"))

    client.get("/calls/1")

    assert _access_logs(_log_lines(capsys)) == []


def test_access_log_status_is_500_when_stream_fails_midway(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    app = build_app()

    @app.get("/broken-stream")
    def broken_stream() -> StreamingResponse:
        def chunks() -> Iterator[bytes]:
            yield b"first"
            raise RuntimeError("mid-stream")

        return StreamingResponse(chunks())

    TestClient(app, raise_server_exceptions=False).get("/broken-stream")

    (access,) = _access_logs(_log_lines(capsys))
    assert access["status"] == 500
