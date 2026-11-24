"""R-03 LocalStorage."""

import io
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.infra.storage import (
    AudioNotFoundError,
    InvalidKeyError,
    InvalidRangeError,
    LocalStorage,
    StorageError,
    create_audio_storage,
)

DATA = bytes(range(256)) * 40  # 10,240바이트, 위치마다 값이 달라 구간 검증이 쉽다.
UUID_KEY = re.compile(r"^[0-9a-f-]{36}\.(wav|mp3)$")


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "audio")


@pytest.fixture
def key(storage: LocalStorage) -> str:
    return storage.save(io.BytesIO(DATA), extension=".wav")


def test_save_returns_uuid_key_and_keeps_extension(storage: LocalStorage) -> None:
    wav = storage.save(io.BytesIO(b"a"), extension=".wav")
    mp3 = storage.save(io.BytesIO(b"b"), extension=".mp3")

    assert UUID_KEY.match(wav)
    assert mp3.endswith(".mp3")
    assert wav != mp3


def test_roundtrip_returns_same_bytes(storage: LocalStorage, key: str) -> None:
    with storage.open(key) as fp:
        assert fp.read() == DATA
    assert storage.size(key) == len(DATA)


def test_save_creates_missing_root_and_leaves_no_temp_files(
    storage: LocalStorage, tmp_path: Path
) -> None:
    storage.save(io.BytesIO(b"x"), extension=".wav")

    names = [p.name for p in (tmp_path / "audio").iterdir()]
    assert len(names) == 1
    assert not names[0].startswith(".tmp-")


def test_failed_save_leaves_no_partial_file(storage: LocalStorage, tmp_path: Path) -> None:
    class BrokenStream(io.RawIOBase):
        def __init__(self) -> None:
            self._sent = False

        def readable(self) -> bool:
            return True

        def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
            if self._sent:
                raise OSError("연결이 끊겼습니다")
            self._sent = True
            buffer[:3] = b"abc"
            return 3

    with pytest.raises(OSError, match="연결이 끊겼습니다"):
        storage.save(BrokenStream(), extension=".wav")  # type: ignore[arg-type]

    assert list((tmp_path / "audio").iterdir()) == []


def test_save_rejects_unsupported_extension(storage: LocalStorage) -> None:
    with pytest.raises(InvalidKeyError):
        storage.save(io.BytesIO(b"x"), extension=".exe")


@pytest.mark.parametrize(
    ("byte_range", "expected"),
    [
        ((0, 9), DATA[0:10]),
        ((100, 199), DATA[100:200]),
        ((10_000, None), DATA[10_000:]),
        ((5, 5), DATA[5:6]),
        ((10_200, 99_999), DATA[10_200:]),  # 끝이 크기를 넘으면 파일 끝으로 맞춘다
        ((0, None), DATA),
    ],
)
def test_open_with_range_returns_only_that_slice(
    storage: LocalStorage, key: str, byte_range: tuple[int, int | None], expected: bytes
) -> None:
    with storage.open(key, byte_range) as fp:
        assert fp.read() == expected


def test_range_reader_supports_chunked_reads(storage: LocalStorage, key: str) -> None:
    with storage.open(key, (10, 1033)) as fp:
        chunks = []
        while chunk := fp.read(100):
            chunks.append(chunk)

    assert b"".join(chunks) == DATA[10:1034]


@pytest.mark.parametrize("byte_range", [(len(DATA), None), (99_999, None), (-1, 5), (10, 5)])
def test_open_with_unsatisfiable_range_raises(
    storage: LocalStorage, key: str, byte_range: tuple[int, int | None]
) -> None:
    with pytest.raises(InvalidRangeError):
        storage.open(key, byte_range)


def test_open_unknown_key_raises_not_found(storage: LocalStorage) -> None:
    with pytest.raises(AudioNotFoundError):
        storage.open("00000000-0000-0000-0000-000000000000.wav")
    with pytest.raises(AudioNotFoundError):
        storage.size("00000000-0000-0000-0000-000000000000.wav")


@pytest.mark.parametrize(
    "bad_key",
    [
        "../secret.wav",
        "..\\secret.wav",
        "/etc/passwd",
        "audio/00000000-0000-0000-0000-000000000000.wav",
        "00000000-0000-0000-0000-000000000000.exe",
        "00000000-0000-0000-0000-000000000000.wav/../x",
        "not-a-uuid.wav",
        "",
    ],
)
def test_malformed_key_is_rejected_before_touching_disk(
    storage: LocalStorage, bad_key: str
) -> None:
    for call in (storage.open, storage.size, storage.delete):
        with pytest.raises(InvalidKeyError):
            call(bad_key)


def test_delete_removes_file_and_is_idempotent(storage: LocalStorage, key: str) -> None:
    storage.delete(key)
    storage.delete(key)  # 보상 처리에서 다시 불려도 안전해야 한다

    with pytest.raises(AudioNotFoundError):
        storage.open(key)


def test_range_reader_close_closes_underlying_file(storage: LocalStorage, key: str) -> None:
    reader = storage.open(key, (0, 9))
    reader.close()

    assert reader.closed


def test_check_creates_root_and_passes(tmp_path: Path) -> None:
    root = tmp_path / "new" / "audio"

    LocalStorage(root).check()

    assert root.is_dir()


def test_check_fails_when_root_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "audio"
    blocker.write_text("파일이라 폴더를 만들 수 없다")

    with pytest.raises(StorageError):
        LocalStorage(blocker).check()


def test_factory_builds_local_storage_without_touching_disk(tmp_path: Path) -> None:
    root = tmp_path / "audio"
    settings = Settings(_env_file=None, audio_storage_root=root)

    created = create_audio_storage(settings)

    assert isinstance(created, LocalStorage)
    assert not root.exists()
