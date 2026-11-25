"""헬스 체크 테스트 공용 가짜: DB 세션, 음성 저장소, inbox writer, 시계."""

from typing import Any

from sqlalchemy.exc import OperationalError

from app.infra.inbox import InboxUnavailableError
from app.infra.storage import StorageError

SECRET = "secret-host-and-key-path"  # 응답·로그에 나오면 안 되는 원인 문구


class FakeSession:
    """`execute`만 흉내 낸다. fail이면 연결 실패(OperationalError)."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.statements: list[str] = []

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception(SECRET))


class FakeStorage:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def check(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def storage_error() -> StorageError:
    """LocalStorage.check()의 mkdir 실패와 같은 모양(원인 예외 체인)."""
    try:
        try:
            raise PermissionError(SECRET)
        except PermissionError as exc:
            raise StorageError("저장소 폴더를 만들 수 없습니다: PermissionError") from exc
    except StorageError as exc:
        return exc


class FakeInbox:
    """check() 호출 횟수를 센다. reason이 있으면 InboxUnavailableError, error면 그 예외."""

    def __init__(self, reason: str | None = None, error: Exception | None = None) -> None:
        self.reason = reason
        self.error = error
        self.calls = 0

    def check(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.reason is not None:
            raise InboxUnavailableError(self.reason) from OSError(SECRET)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now
