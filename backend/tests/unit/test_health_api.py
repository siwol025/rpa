"""`GET /health` 라우터 — 가짜 의존 대상과 실제 로컬 어댑터로 상태 코드·본문·헤더를 확인한다."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.logging import configure_logging
from app.services.health_service import INBOX_CHECK_TTL_SEC, InboxCheckCache
from tests.unit.health_fakes import (
    SECRET,
    FakeClock,
    FakeInbox,
    FakeSession,
    FakeStorage,
    storage_error,
)

_URL = "/health"


def _app(
    build_app: Callable[..., FastAPI],
    *,
    session: FakeSession | None = None,
    storage: Any = None,
    writer: Any = None,
    **overrides: Any,
) -> FastAPI:
    app = build_app(**overrides)
    fake_session = session or FakeSession()
    app.dependency_overrides[get_db] = lambda: fake_session
    app.state.audio_storage = storage or FakeStorage()
    app.state.inbox_writer = writer
    return app


def _get(app: FastAPI) -> Any:
    return TestClient(app).get(_URL)


def test_all_ok_is_200(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, writer=FakeInbox()))

    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "OK"},
    }


def test_headers(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app))

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-Id"]


def test_disabled_inbox_is_200_ok(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, writer=None))

    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "DISABLED"},
    }


def test_db_failure_is_503_in_health_format(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, session=FakeSession(fail=True), writer=FakeInbox()))

    assert response.status_code == 503
    assert response.json() == {
        "status": "FAIL",
        "checks": {"db": "FAIL", "audio_storage": "OK", "inbox": "OK"},
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_audio_storage_failure_is_503(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, storage=FakeStorage(storage_error())))

    assert response.status_code == 503
    assert response.json() == {
        "status": "FAIL",
        "checks": {"db": "OK", "audio_storage": "FAIL", "inbox": "DISABLED"},
    }


def test_inbox_failure_is_200_degraded(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, writer=FakeInbox(reason="http_404")))

    assert response.status_code == 200
    assert response.json() == {
        "status": "DEGRADED",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "FAIL"},
    }


def test_response_has_no_reason(build_app: Callable[..., FastAPI]) -> None:
    app = _app(
        build_app,
        session=FakeSession(fail=True),
        storage=FakeStorage(storage_error()),
        writer=FakeInbox(reason="http_404"),
    )

    body = _get(app).text

    for hidden in (SECRET, "http_404", "OperationalError", "PermissionError", "reason"):
        assert hidden not in body


def test_failure_log_has_request_id_and_no_cause(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    app = _app(build_app, session=FakeSession(fail=True))
    capsys.readouterr()

    TestClient(app).get(_URL, headers={"X-Request-Id": "rid-health"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    (failed,) = [line for line in lines if line.get("event") == "health_check_failed"]
    assert failed["request_id"] == "rid-health"
    assert (failed["component"], failed["reason"]) == ("db", "OperationalError")
    assert SECRET not in json.dumps(lines)
    assert "Traceback" not in json.dumps(lines)


def test_no_robot_auth_required(build_app: Callable[..., FastAPI]) -> None:
    # 로봇 키가 비어 있으면 /api/robot/*는 모두 401이지만 /health는 영향이 없다.
    app = _app(build_app, robot_api_keys=[], robot_allowed_ips=[])

    assert _get(app).status_code == 200


def test_unexpected_error_is_500_in_error_format(build_app: Callable[..., FastAPI]) -> None:
    app = _app(build_app, storage=FakeStorage(RuntimeError("boom-secret")))

    response = TestClient(app, raise_server_exceptions=False).get(_URL)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "boom-secret" not in response.text


# ---------------------------------------------------------------- inbox 캐시 (앱 단위)


def test_inbox_check_is_cached_across_requests(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeInbox(reason="http_403")
    client = TestClient(_app(build_app, writer=writer))

    statuses = [client.get(_URL).json()["status"] for _ in range(3)]

    assert statuses == ["DEGRADED"] * 3
    assert writer.calls == 1


def test_injected_clock_expires_cache(build_app: Callable[..., FastAPI]) -> None:
    clock = FakeClock()
    writer = FakeInbox()
    app = _app(build_app, writer=writer)
    app.state.inbox_health_cache = InboxCheckCache(clock=clock)
    client = TestClient(app)

    client.get(_URL)
    clock.now += INBOX_CHECK_TTL_SEC
    client.get(_URL)

    assert writer.calls == 2


def test_cache_is_per_app(build_app: Callable[..., FastAPI]) -> None:
    first = FakeInbox()
    second = FakeInbox()

    _get(_app(build_app, writer=first))
    _get(_app(build_app, writer=second))

    assert (first.calls, second.calls) == (1, 1)


# ---------------------------------------------------------------- 실제 로컬 어댑터


def test_local_adapters_are_ok_and_create_folders(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    audio = tmp_path / "audio"
    inbox = tmp_path / "inbox"
    app = build_app(audio_storage_root=audio, inbox_backend="local", inbox_local_path=inbox)
    fake_session = FakeSession()
    app.dependency_overrides[get_db] = lambda: fake_session

    response = TestClient(app).get(_URL)

    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "OK"},
    }
    assert audio.is_dir()
    assert inbox.is_dir()


def test_local_storage_on_file_path_is_503(
    build_app: Callable[..., FastAPI], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"x")
    app = build_app(audio_storage_root=blocker / "audio")
    fake_session = FakeSession()
    app.dependency_overrides[get_db] = lambda: fake_session
    configure_logging("INFO")
    capsys.readouterr()

    response = TestClient(app).get(_URL)

    assert response.status_code == 503
    assert response.json()["checks"]["audio_storage"] == "FAIL"
    assert str(tmp_path.name) not in capsys.readouterr().out


# ---------------------------------------------------------------- OpenAPI


def test_openapi_health(build_app: Callable[..., FastAPI]) -> None:
    spec = build_app().openapi()
    operation = spec["paths"]["/health"]["get"]
    schemas = spec["components"]["schemas"]

    assert operation["operationId"] == "get_health"
    assert operation["tags"] == ["health"]
    assert set(operation["responses"]) == {"200", "422", "500", "503"}
    for status in ("200", "503"):
        ref = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/HealthResponse")
    assert schemas["HealthStatus"]["enum"] == ["OK", "DEGRADED", "FAIL"]
    assert schemas["ComponentStatus"]["enum"] == ["OK", "FAIL", "DISABLED"]
    assert set(schemas["HealthChecks"]["required"]) == {"db", "audio_storage", "inbox"}
