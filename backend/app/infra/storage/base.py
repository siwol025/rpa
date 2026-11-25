"""서버 음성 사본 저장소 인터페이스 (architecture.md §8, R-03).

로봇이 등록한 녹취의 사본을 보관하고 웹 재생(W-06)·로봇 재처리 다운로드(R-10)에 쓴다.
키는 서버가 만든 UUID 기반 문자열이라 원본 파일명이 저장소에 노출되지 않는다.
"""

from typing import BinaryIO, Protocol

# (시작 바이트, 끝 바이트). 끝은 포함(HTTP Range와 같음)이고 None이면 파일 끝까지.
ByteRange = tuple[int, int | None]


class StorageError(Exception):
    """저장소 오류의 공통 부모."""


class InvalidKeyError(StorageError):
    """저장소가 만든 형식이 아닌 키. 경로 탈출(`../`)을 막기 위해 파일 접근 전에 거절한다."""


class AudioNotFoundError(StorageError):
    """키에 해당하는 음성 사본이 없다."""


class InvalidRangeError(StorageError):
    """요청 범위가 파일 크기를 벗어난다 (HTTP 416에 대응)."""


class AudioStorage(Protocol):
    def save(self, stream: BinaryIO, *, extension: str) -> str:
        """스트림을 처음부터 끝까지 저장하고 키를 반환한다.

        extension: `.wav` 또는 `.mp3`. 저장이 끝나기 전에는 다른 호출자에게 보이지 않고,
        중간에 실패하면 부분 파일을 남기지 않는다.
        """
        ...

    def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO:
        """읽기용 스트림을 연다. 호출자가 닫는다.

        byte_range가 있으면 그 구간만 읽힌다 (끝이 파일 크기를 넘으면 파일 끝으로 맞춘다).
        없는 키는 AudioNotFoundError, 시작이 파일 크기 이상이면 InvalidRangeError.
        """
        ...

    def size(self, key: str) -> int:
        """파일 크기(바이트). Content-Range·Content-Length 계산용."""
        ...

    def delete(self, key: str) -> None:
        """사본을 지운다. 이미 없으면 아무것도 하지 않는다 (보상 처리에서 재호출해도 안전)."""
        ...

    def check(self) -> None:
        """저장소에 쓸 수 있는지 확인한다 (헬스 체크, O-02). 불가하면 StorageError."""
        ...
