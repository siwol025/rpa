"""HealthService·InboxCheckCache·overall_status — 가짜 의존 대상으로 판정·캐시·로그를 확인한다."""

import json
import threading
import time
from typing import Any

import pytest

from app.core.logging import configure_logging
from app.infra.storage import StorageError
from app.schemas.health import ComponentStatus, HealthChecks, HealthStatus
from app.services.health_service import (
    INBOX_CHECK_TTL_SEC,
    HealthService,
    InboxCheckCache,
    overall_status,
)
from tests.unit.health_fakes import (
    SECRET,
    FakeClock,
    FakeInbox,
    FakeSession,
    FakeStorage,
    storage_error,
)

OK = ComponentStatus.OK
FAIL = ComponentStatus.FAIL
DISABLED = ComponentStatus.DISABLED


def _service(
    session: Any = None,
    storage: Any = None,
    writer: Any = None,
    cache: InboxCheckCache | None = None,
) -> HealthService:
    fake_session: Any = session or FakeSession()
    fake_storage: Any = storage or FakeStorage()
    return HealthService(fake_session, fake_storage, writer, cache or InboxCheckCache())


def _health_logs(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [line for line in lines if line.get("logger") == "app.health"]


# ---------------------------------------------------------------- 전체 판정


@pytest.mark.parametrize(
    ("db", "audio_storage", "inbox", "expected"),
    [
        (OK, OK, OK, HealthStatus.OK),
        (OK, OK, DISABLED, HealthStatus.OK),
        (OK, OK, FAIL, HealthStatus.DEGRADED),
        (FAIL, OK, OK, HealthStatus.FAIL),
        (OK, FAIL, OK, HealthStatus.FAIL),
        (FAIL, OK, FAIL, HealthStatus.FAIL),
        (OK, FAIL, DISABLED, HealthStatus.FAIL),
    ],
)
def test_overall_status(
    db: ComponentStatus,
    audio_storage: ComponentStatus,
    inbox: ComponentStatus,
    expected: HealthStatus,
) -> None:
    checks = HealthChecks(db=db, audio_storage=audio_storage, inbox=inbox)

    assert overall_status(checks) == expected


# ---------------------------------------------------------------- 구성요소 확인


def test_all_ok() -> None:
    session = FakeSession()

    result = _service(session=session, writer=FakeInbox()).check()

    assert result.model_dump() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "OK"},
    }
    assert session.statements == ["SELECT 1"]


def test_disabled_inbox_is_not_checked() -> None:
    result = _service(writer=None).check()

    assert result.status == HealthStatus.OK
    assert result.checks.inbox == DISABLED


def test_db_failure_is_fail() -> None:
    result = _service(session=FakeSession(fail=True), writer=FakeInbox()).check()

    assert result.status == HealthStatus.FAIL
    assert result.checks.db == FAIL
    assert result.checks.audio_storage == OK


def test_audio_storage_failure_is_fail() -> None:
    result = _service(storage=FakeStorage(storage_error())).check()

    assert result.status == HealthStatus.FAIL
    assert result.checks.audio_storage == FAIL


def test_inbox_failure_is_degraded() -> None:
    result = _service(writer=FakeInbox(reason="http_404")).check()

    assert result.status == HealthStatus.DEGRADED
    assert result.checks.inbox == FAIL


def test_every_component_is_checked_even_after_failure() -> None:
    storage = FakeStorage()
    writer = FakeInbox()

    result = _service(session=FakeSession(fail=True), storage=storage, writer=writer).check()

    assert result.checks.model_dump() == {"db": "FAIL", "audio_storage": "OK", "inbox": "OK"}
    assert (storage.calls, writer.calls) == (1, 1)


@pytest.mark.parametrize(
    "error",
    [RuntimeError("bug"), ValueError("bug")],
)
def test_unexpected_errors_are_not_swallowed(error: Exception) -> None:
    with pytest.raises(type(error)):
        _service(storage=FakeStorage(error)).check()
    with pytest.raises(type(error)):
        _service(writer=FakeInbox(error=error)).check()


# ---------------------------------------------------------------- 로그


def test_failures_are_logged_with_reason_only(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    _service(
        session=FakeSession(fail=True),
        storage=FakeStorage(storage_error()),
        writer=FakeInbox(reason="http_404"),
    ).check()

    logs = _health_logs(capsys)
    assert [(log["event"], log["component"], log["reason"]) for log in logs] == [
        ("health_check_failed", "db", "OperationalError"),
        ("health_check_failed", "audio_storage", "PermissionError"),
        ("health_check_failed", "inbox", "http_404"),
    ]
    assert all(log["level"] == "warning" for log in logs)
    dumped = json.dumps(logs)
    assert SECRET not in dumped
    assert "exception" not in dumped
    assert "Traceback" not in dumped


def test_storage_error_without_cause_uses_class_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    _service(storage=FakeStorage(StorageError("저장소 폴더에 쓸 수 없습니다"))).check()

    (log,) = _health_logs(capsys)
    assert log["reason"] == "StorageError"


def test_success_is_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    _service(writer=FakeInbox()).check()

    assert _health_logs(capsys) == []


# ---------------------------------------------------------------- inbox 캐시


def test_inbox_result_is_reused_within_ttl() -> None:
    clock = FakeClock()
    cache = InboxCheckCache(clock=clock)
    writer = FakeInbox()
    service = _service(writer=writer, cache=cache)

    service.check()
    clock.now += INBOX_CHECK_TTL_SEC - 0.1
    service.check()

    assert writer.calls == 1


def test_inbox_is_checked_again_after_ttl() -> None:
    clock = FakeClock()
    cache = InboxCheckCache(clock=clock)
    writer = FakeInbox()
    service = _service(writer=writer, cache=cache)

    service.check()
    clock.now += INBOX_CHECK_TTL_SEC
    service.check()

    assert writer.calls == 2


def test_inbox_failure_is_cached_and_logged_once(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    capsys.readouterr()
    clock = FakeClock()
    writer = FakeInbox(reason="DefaultCredentialsError")
    service = _service(writer=writer, cache=InboxCheckCache(clock=clock))

    first = service.check()
    clock.now += 10
    second = service.check()

    assert first.checks.inbox == second.checks.inbox == FAIL
    assert writer.calls == 1
    assert len(_health_logs(capsys)) == 1


def test_inbox_recovery_is_seen_after_ttl() -> None:
    clock = FakeClock()
    writer = FakeInbox(reason="http_503")
    service = _service(writer=writer, cache=InboxCheckCache(clock=clock))

    assert service.check().status == HealthStatus.DEGRADED
    writer.reason = None
    clock.now += INBOX_CHECK_TTL_SEC
    assert service.check().status == HealthStatus.OK


def test_unexpected_error_is_not_cached() -> None:
    writer = FakeInbox(error=RuntimeError("bug"))
    service = _service(writer=writer, cache=InboxCheckCache(clock=FakeClock()))

    with pytest.raises(RuntimeError):
        service.check()
    writer.error = None
    assert service.check().checks.inbox == OK
    assert writer.calls == 2


def test_db_and_storage_are_not_cached() -> None:
    session = FakeSession()
    storage = FakeStorage()
    service = _service(session=session, storage=storage, cache=InboxCheckCache(clock=FakeClock()))

    service.check()
    service.check()

    assert len(session.statements) == 2
    assert storage.calls == 2


def test_concurrent_requests_check_inbox_once() -> None:
    cache = InboxCheckCache()
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_check() -> ComponentStatus:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return OK

    results: list[ComponentStatus] = []
    entered = threading.Semaphore(0)

    def waiter() -> None:
        entered.release()
        results.append(cache.get(slow_check))

    threads = [threading.Thread(target=lambda: results.append(cache.get(slow_check)))]
    threads[0].start()
    assert started.wait(timeout=5)
    # 첫 확인이 잠금을 쥔 동안 들어온 요청들.
    # 모두 get 직전까지 온 뒤 잠금 대기에 들어갈 시간을 준다.
    threads += [threading.Thread(target=waiter) for _ in range(7)]
    for thread in threads[1:]:
        thread.start()
    for _ in range(7):
        assert entered.acquire(timeout=5)
    time.sleep(0.2)
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert calls == 1
    assert results == [OK] * 8
