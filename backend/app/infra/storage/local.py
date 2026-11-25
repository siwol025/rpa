"""로컬 디스크 음성 사본 저장소. 운영은 Docker 볼륨 `/data/audio`를 가리킨다."""

import io
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, cast

from app.infra.storage.base import (
    AudioNotFoundError,
    ByteRange,
    InvalidKeyError,
    InvalidRangeError,
    StorageError,
)

ALLOWED_EXTENSIONS = (".wav", ".mp3")
_KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(wav|mp3)$"
)
_TMP_PREFIX = ".tmp-"


class _LimitedReader(io.RawIOBase):
    """파일의 `length` 바이트만 읽히게 하는 래퍼. 닫으면 원본 파일도 닫는다."""

    def __init__(self, raw: BinaryIO, length: int) -> None:
        self._raw = raw
        self._remaining = length

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        if self._remaining <= 0:
            return 0
        view = memoryview(buffer).cast("B")[: self._remaining]
        read = self._raw.readinto(view)  # type: ignore[attr-defined]
        self._remaining -= read
        return int(read)

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            super().close()


class LocalStorage:
    def __init__(self, root: Path) -> None:
        # 생성만으로는 디스크를 건드리지 않는다 (OpenAPI 내보내기·단위 테스트 부작용 방지).
        self._root = root

    def save(self, stream: BinaryIO, *, extension: str) -> str:
        if extension not in ALLOWED_EXTENSIONS:
            raise InvalidKeyError(f"허용되지 않은 확장자: {extension}")
        key = f"{uuid.uuid4()}{extension}"
        self._root.mkdir(parents=True, exist_ok=True)
        # 임시 파일에 다 쓴 뒤 한 번에 이름을 바꿔, 쓰는 도중의 파일이 읽히지 않게 한다.
        tmp = self._root / f"{_TMP_PREFIX}{uuid.uuid4().hex}"
        try:
            with tmp.open("wb") as out:
                shutil.copyfileobj(stream, out)
            os.replace(tmp, self._root / key)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return key

    def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO:
        path = self._path(key)
        try:
            fp = path.open("rb")
        except FileNotFoundError:
            raise AudioNotFoundError(key) from None
        if byte_range is None:
            return fp
        try:
            total = os.fstat(fp.fileno()).st_size
            start, end = byte_range
            if start < 0 or start >= total or (end is not None and end < start):
                raise InvalidRangeError(f"{byte_range} (size={total})")
            last = total - 1 if end is None else min(end, total - 1)
            fp.seek(start)
        except BaseException:
            fp.close()
            raise
        return cast(BinaryIO, _LimitedReader(fp, last - start + 1))

    def size(self, key: str) -> int:
        try:
            return self._path(key).stat().st_size
        except FileNotFoundError:
            raise AudioNotFoundError(key) from None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def check(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"저장소 폴더를 만들 수 없습니다: {exc.__class__.__name__}") from exc
        if not os.access(self._root, os.W_OK):
            raise StorageError("저장소 폴더에 쓸 수 없습니다")

    def _path(self, key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(key):
            raise InvalidKeyError("올바르지 않은 키")
        return self._root / key
