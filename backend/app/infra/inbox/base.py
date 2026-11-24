"""웹 업로드 파일을 입력 폴더 inbox/에 쓰는 어댑터 인터페이스 (architecture.md §8.2)."""

from typing import BinaryIO, Protocol


class InboxUnavailableError(Exception):
    """inbox/에 쓸 수 없다 (재시도 소진, 인증·권한·설정 문제, 로컬 I/O 오류).

    `reason`은 로그·헬스 체크용 짧은 분류 값이다(예: `http_404`, `RefreshError`, `trashed`).
    파일명·폴더 ID·키 경로·서비스 계정 정보는 넣지 않는다.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class InboxWriter(Protocol):
    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        """파일 하나를 inbox/에 쓰고 식별자(Drive 파일 ID / 로컬은 저장된 파일명)를 반환한다.

        stream은 seek 가능해야 하며 처음부터 끝까지 쓴다. 실패하면 InboxUnavailableError.
        """
        ...

    def check(self) -> None:
        """inbox/에 쓸 수 있는지 파일을 만들지 않고 확인한다. 불가하면 InboxUnavailableError."""
        ...
