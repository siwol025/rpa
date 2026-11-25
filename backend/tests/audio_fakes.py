"""음성 재생 테스트(단위·통합) 공용 가짜·데이터. `test_*.py`가 아니라 수집되지 않는다."""

import io
from typing import Any, BinaryIO

DATA = bytes(range(256)) * 40  # 10,240바이트. 위치마다 값이 달라 구간 검증이 쉽다
SIZE = len(DATA)


class FakeSession:
    """`scalar()`만 흉내 낸다. 조회 조건은 통합 테스트가 확인한다."""

    def __init__(self, key: str | None, events: list[str] | None = None) -> None:
        self.key = key
        self.events = events if events is not None else []

    def scalar(self, statement: Any) -> str | None:
        self.events.append("query")
        return self.key


class ReadRecorder(io.RawIOBase):
    """읽을 때마다 events에 "read"를 남기는 래퍼."""

    def __init__(self, inner: BinaryIO, events: list[str]) -> None:
        self._inner = inner
        self._events = events

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        self._events.append("read")
        return int(self._inner.readinto(buffer))  # type: ignore[attr-defined]

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            super().close()
