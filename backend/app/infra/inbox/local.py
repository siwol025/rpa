"""개발·테스트용 로컬 폴더 inbox (input_flow.md §4.4). 운영 입력 경로로 쓰지 않는다."""

import itertools
import os
import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import structlog

from app.infra.inbox.base import InboxUnavailableError

_log = structlog.stdlib.get_logger("app.inbox")

# Windows에서도 만들 수 없는 문자. 경로 구분자(/ \)와 드라이브 구분자(:)를 포함한다.
_FORBIDDEN_CHARS = frozenset('\\/:*?"<>|')


def validate_local_name(filename: str) -> None:
    """로컬 파일명으로 쓸 수 없으면 ValueError (경로 탈출·금지 문자·제어 문자)."""
    if filename in ("", ".", ".."):
        raise ValueError("파일명이 비어 있거나 경로입니다")
    if any(ch in _FORBIDDEN_CHARS or ord(ch) < 32 for ch in filename):
        raise ValueError("파일명에 사용할 수 없는 문자가 있습니다")


def _with_suffix(name: str, n: int) -> str:
    """`a.mp3` → `a (1).mp3`. 확장자가 없으면 끝에 붙인다."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return f"{name} ({n})"
    return f"{stem} ({n}).{ext}"


class LocalInboxWriter:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        # content_type은 로컬에서 쓰지 않는다(메타데이터 저장 없음). 파일명 검사는 W-07이 먼저 한다.
        validate_local_name(filename)
        tmp = self._root / f".{uuid4().hex}.part"  # .wav/.mp3가 아니라 로컬 Dispatcher가 집지 않음
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            stream.seek(0)
            with tmp.open("xb") as out:
                shutil.copyfileobj(stream, out)
                # replace 뒤에는 다른 프로세스가 파일을 옮겼을 수 있어 여기서 잰다.
                size = out.tell()
            final = self._root / filename
            for n in itertools.count(1):
                if not final.exists():
                    break
                final = self._root / _with_suffix(filename, n)
            # 존재 확인과 replace 사이 경쟁은 개발용이라 허용한다.
            os.replace(tmp, final)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            _log.warning("inbox_write_failed", backend="local", reason=type(exc).__name__)
            raise InboxUnavailableError(type(exc).__name__) from exc
        except BaseException:
            tmp.unlink(missing_ok=True)  # 버그 등 예상 밖 예외도 반쯤 쓴 파일을 남기지 않는다
            raise
        _log.info("inbox_written", backend="local", size_bytes=size)
        return final.name

    def check(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InboxUnavailableError(type(exc).__name__) from exc
        if not os.access(self._root, os.W_OK):
            raise InboxUnavailableError("not_writable")
