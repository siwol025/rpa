"""실제 Google Drive 수동 테스트 (E-01 이후). 기본 실행에서는 skip된다.

실행: GOOGLE_APPLICATION_CREDENTIALS=<키 경로> TEST_DRIVE_FOLDER_ID=<테스트용 폴더 ID> \\
      uv run pytest -m drive
운영 inbox/가 아닌 **테스트용 폴더**를 쓴다(Dispatcher가 집어 가지 않는 곳). 올린 파일은 남으므로
테스트 후 직접 지운다(기여자 역할은 삭제 권한이 없을 수 있다).
"""

import io
import os
from datetime import UTC, datetime
from typing import Any

import google.auth
import pytest
from googleapiclient.discovery import build

from app.infra.inbox.drive import DRIVE_SCOPES, DriveInboxWriter

pytestmark = pytest.mark.drive

_FOLDER_ID = os.environ.get("TEST_DRIVE_FOLDER_ID", "")


@pytest.fixture
def writer() -> DriveInboxWriter:
    if not _FOLDER_ID:
        pytest.skip("TEST_DRIVE_FOLDER_ID 없음 (실제 Drive 수동 테스트)")
    return DriveInboxWriter(_FOLDER_ID)


def _get(file_id: str) -> Any:
    credentials, _ = google.auth.default(scopes=DRIVE_SCOPES)
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return (
        service.files()
        .get(fileId=file_id, fields="id,name,parents,properties,mimeType", supportsAllDrives=True)
        .execute()
    )


def test_check_passes(writer: DriveInboxWriter) -> None:
    writer.check()


def test_write_creates_file_with_source_property(writer: DriveInboxWriter) -> None:
    name = f"pytest_{datetime.now(UTC):%Y%m%d_%H%M%S}_테스트_검증.mp3"

    file_id = writer.write(name, io.BytesIO(b"ID3" + b"\0" * 1024), "audio/mpeg")

    meta = _get(file_id)
    assert meta["name"] == name
    assert meta["parents"] == [_FOLDER_ID]
    assert meta["properties"] == {"source": "web"}
    assert meta["mimeType"] == "audio/mpeg"
