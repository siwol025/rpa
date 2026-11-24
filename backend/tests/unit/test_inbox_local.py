"""LocalInboxWriter — 개발용 로컬 inbox 폴더."""

import io
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.logging import configure_logging
from app.infra.inbox import InboxUnavailableError
from app.infra.inbox.local import LocalInboxWriter

_NAME = "20261124_101500_김상담_A산업.mp3"


def _files(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in root.iterdir()}


def test_write_saves_file_with_original_name(tmp_path: Path) -> None:
    name = LocalInboxWriter(tmp_path).write(_NAME, io.BytesIO(b"ID3data"), "audio/mpeg")

    assert name == _NAME
    assert _files(tmp_path) == {_NAME: b"ID3data"}  # 임시 .part 파일이 남지 않음


def test_write_creates_missing_root(tmp_path: Path) -> None:
    root = tmp_path / "data" / "inbox"

    LocalInboxWriter(root).write(_NAME, io.BytesIO(b"x"), "audio/mpeg")

    assert (root / _NAME).read_bytes() == b"x"


def test_write_reads_stream_from_start(tmp_path: Path) -> None:
    stream = io.BytesIO(b"ID3data")
    stream.read(3)

    LocalInboxWriter(tmp_path).write(_NAME, stream, "audio/mpeg")

    assert (tmp_path / _NAME).read_bytes() == b"ID3data"


def test_write_adds_suffix_instead_of_overwriting(tmp_path: Path) -> None:
    writer = LocalInboxWriter(tmp_path)

    names = [writer.write(_NAME, io.BytesIO(data), "audio/mpeg") for data in (b"1", b"2", b"3")]

    stem = _NAME.removesuffix(".mp3")
    assert names == [_NAME, f"{stem} (1).mp3", f"{stem} (2).mp3"]
    assert _files(tmp_path) == {_NAME: b"1", f"{stem} (1).mp3": b"2", f"{stem} (2).mp3": b"3"}


def test_suffix_for_name_without_extension(tmp_path: Path) -> None:
    writer = LocalInboxWriter(tmp_path)
    writer.write("noext", io.BytesIO(b"1"), "audio/mpeg")

    assert writer.write("noext", io.BytesIO(b"2"), "audio/mpeg") == "noext (1)"


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../x.mp3", "a/b.mp3", "a\\b.mp3", "C:x.mp3", "a?.mp3", "a\x00.mp3"],
)
def test_write_rejects_unsafe_name(tmp_path: Path, name: str) -> None:
    root = tmp_path / "inbox"

    with pytest.raises(ValueError):
        LocalInboxWriter(root).write(name, io.BytesIO(b"x"), "audio/mpeg")

    assert not root.exists()  # 검사 실패 시 아무것도 만들지 않음


def test_write_io_error_becomes_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_bytes(b"")  # 디렉터리 자리에 파일이 있음

    with pytest.raises(InboxUnavailableError):
        LocalInboxWriter(root).write(_NAME, io.BytesIO(b"x"), "audio/mpeg")


def test_check_passes_for_writable_dir(tmp_path: Path) -> None:
    LocalInboxWriter(tmp_path).check()

    assert list(tmp_path.iterdir()) == []  # 파일을 만들지 않음


def test_check_fails_when_root_is_not_dir(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_bytes(b"")

    with pytest.raises(InboxUnavailableError):
        LocalInboxWriter(root).check()


class _BrokenStream(io.BytesIO):
    """첫 조각을 준 뒤 읽기에서 error를 던진다 (복사 도중 실패)."""

    def __init__(self, error: Exception) -> None:
        super().__init__(b"ID3data")
        self._error = error
        self._reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise self._error
        return super().read(3)


def test_write_removes_part_file_when_copy_fails(tmp_path: Path) -> None:
    with pytest.raises(InboxUnavailableError):
        LocalInboxWriter(tmp_path).write(_NAME, _BrokenStream(OSError("disk")), "audio/mpeg")

    assert list(tmp_path.iterdir()) == []


def test_write_removes_part_file_on_unexpected_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        LocalInboxWriter(tmp_path).write(_NAME, _BrokenStream(RuntimeError("bug")), "audio/mpeg")

    assert list(tmp_path.iterdir()) == []


def test_write_succeeds_when_file_is_moved_right_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    picked = tmp_path / "picked"
    picked.mkdir()
    root = tmp_path / "inbox"
    real_replace = os.replace

    def replace_then_pick_up(src: Any, dst: Any) -> None:
        real_replace(src, dst)
        real_replace(dst, picked / Path(dst).name)  # 로컬 Dispatcher가 곧바로 옮겨 감

    monkeypatch.setattr("app.infra.inbox.local.os.replace", replace_then_pick_up)

    name = LocalInboxWriter(root).write(_NAME, io.BytesIO(b"ID3data"), "audio/mpeg")

    assert name == _NAME
    assert (picked / _NAME).read_bytes() == b"ID3data"


def test_write_success_log_has_size_but_no_file_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 단다

    LocalInboxWriter(tmp_path).write(_NAME, io.BytesIO(b"ID3data"), "audio/mpeg")

    out = capsys.readouterr().out
    assert "inbox_written" in out
    assert '"size_bytes": 7' in out
    assert "김상담" not in out
