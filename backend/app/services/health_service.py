"""헬스 체크 (O-02): DB·음성 저장소·inbox 접근 확인과 전체 판정."""

import threading
import time
from collections.abc import Callable

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.infra.inbox import InboxUnavailableError, InboxWriter
from app.infra.storage import AudioStorage, StorageError
from app.schemas.health import ComponentStatus, HealthChecks, HealthResponse, HealthStatus

# inbox(Drive) 확인은 느릴 수 있어(소켓 타임아웃 5초 × 토큰 갱신·조회) 결과를 재사용한다.
INBOX_CHECK_TTL_SEC = 30.0

_log = structlog.stdlib.get_logger("app.health")


class InboxCheckCache:
    """inbox 확인 결과를 TTL 동안 재사용한다. 성공·실패 모두 캐시한다.

    만료 시 한 스레드만 확인하고, 그동안 다른 요청은 잠금에서 기다렸다가 새 결과를 쓴다.
    앱마다 하나(`app.state.inbox_health_cache`)라 테스트 간 상태가 섞이지 않는다.
    """

    def __init__(
        self,
        ttl_sec: float = INBOX_CHECK_TTL_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._result: ComponentStatus | None = None
        self._checked_at = 0.0

    def get(self, check: Callable[[], ComponentStatus]) -> ComponentStatus:
        with self._lock:
            if self._result is None or self._clock() - self._checked_at >= self._ttl:
                # check()가 예상 밖 예외(버그)를 던지면 캐시하지 않고 그대로 올린다.
                self._result = check()
                self._checked_at = self._clock()
            return self._result


def overall_status(checks: HealthChecks) -> HealthStatus:
    """DB·음성 저장소는 필수(실패 → FAIL), inbox는 선택(실패 → DEGRADED, DISABLED는 제외)."""
    if ComponentStatus.FAIL in (checks.db, checks.audio_storage):
        return HealthStatus.FAIL
    if checks.inbox == ComponentStatus.FAIL:
        return HealthStatus.DEGRADED
    return HealthStatus.OK


def _failed(component: str, reason: str) -> ComponentStatus:
    # 원인 예외(str·exc_info)에는 DB 호스트·SQL·키 경로가 있을 수 있어 분류 값만 남긴다.
    _log.warning("health_check_failed", component=component, reason=reason)
    return ComponentStatus.FAIL


class HealthService:
    def __init__(
        self,
        session: Session,
        storage: AudioStorage,
        writer: InboxWriter | None,
        inbox_cache: InboxCheckCache,
    ) -> None:
        self._session = session
        self._storage = storage
        self._writer = writer
        self._inbox_cache = inbox_cache

    def check(self) -> HealthResponse:
        checks = HealthChecks(
            db=self._check_db(),
            audio_storage=self._check_audio_storage(),
            inbox=self._check_inbox(),
        )
        return HealthResponse(status=overall_status(checks), checks=checks)

    def _check_db(self) -> ComponentStatus:
        try:
            self._session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            return _failed("db", type(exc).__name__)
        return ComponentStatus.OK

    def _check_audio_storage(self) -> ComponentStatus:
        try:
            self._storage.check()
        except StorageError as exc:
            # StorageError에는 분류 속성이 없어 원인 예외(OSError 계열) 클래스 이름을 쓴다.
            return _failed("audio_storage", type(exc.__cause__ or exc).__name__)
        return ComponentStatus.OK

    def _check_inbox(self) -> ComponentStatus:
        writer = self._writer
        if writer is None:  # INBOX_BACKEND=disabled: 실패가 아니다
            return ComponentStatus.DISABLED

        def check() -> ComponentStatus:
            try:
                writer.check()
            except InboxUnavailableError as exc:
                return _failed("inbox", exc.reason)
            return ComponentStatus.OK

        return self._inbox_cache.get(check)
