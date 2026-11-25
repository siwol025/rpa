"""웹 업로드 테스트 공용: 최소 음성 헤더와 가짜 InboxWriter."""

from typing import BinaryIO

from app.infra.inbox import InboxUnavailableError

WAV = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 20
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 20


class FakeWriter:
    """받은 (이름, 바이트, MIME)과 받은 시점의 스트림 위치를 기록한다.

    fail_at번째(0부터) 호출에서 InboxUnavailableError.
    """

    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.written: list[tuple[str, bytes, str]] = []
        self.calls = 0
        self.positions: list[int] = []

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        index = self.calls
        self.calls += 1
        if index == self.fail_at:
            raise InboxUnavailableError("http_503") from OSError("secret-key-path")
        self.positions.append(stream.tell())
        stream.seek(0)
        self.written.append((filename, stream.read(), content_type))
        return f"id-{index}"

    def check(self) -> None:
        return None
