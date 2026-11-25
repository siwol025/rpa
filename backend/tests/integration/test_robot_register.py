"""R-04 `POST /api/robot/calls` 등록 (실제 PostgreSQL)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CallRecord, ProcessingLog
from app.schemas.call import CallStatus
from app.services.robot_service import RobotService
from tests.conftest import ROBOT_IP
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

URL = "/api/robot/calls"
WAV = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + bytes(range(64)) * 8
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes(range(64)) * 8


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def register(
    client: TestClient, content: bytes = WAV, *, name: str = "a.wav", **fields: Any
) -> Any:
    form: dict[str, Any] = {
        "file_hash": sha256(content),
        "original_name": name,
        "source_type": "DRIVE",
        "source_ref": "drive-file-1",
        "call_datetime": "2026-11-23T14:30:05+09:00",
        "agent_name": "홍길동",
        "client_company": "테스트고객사",
    }
    form.update(fields)
    form = {key: value for key, value in form.items() if value is not None}
    return client.post(URL, data=form, files={"file": (name, content, "application/octet-stream")})


def stored_files(audio_root: Path) -> list[Path]:
    return sorted(audio_root.iterdir()) if audio_root.exists() else []


def call_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(CallRecord)) or 0


def test_register_creates_registered_call_with_copy_and_log(
    robot_client: TestClient, db: Session, audio_root: Path
) -> None:
    response = register(robot_client)

    assert response.status_code == 201
    call = db.get(CallRecord, response.json()["call_id"])
    assert call is not None
    assert call.status == CallStatus.REGISTERED
    assert call.file_hash == sha256(WAV)
    assert call.file_size == len(WAV)
    assert call.source_type == "DRIVE"
    assert call.source_ref == "drive-file-1"
    assert call.original_name == "a.wav"
    assert call.agent_name == "홍길동"
    assert call.client_company == "테스트고객사"
    assert call.metadata_incomplete is False
    (copy,) = stored_files(audio_root)
    assert copy.name == call.object_key
    assert copy.suffix == ".wav"
    assert copy.read_bytes() == WAV
    log = db.scalars(select(ProcessingLog).where(ProcessingLog.call_id == call.id)).one()
    assert (log.step, log.status) == ("REGISTER", "SUCCESS")


def test_response_has_only_call_id_and_request_id_header(robot_client: TestClient) -> None:
    response = register(robot_client)

    assert set(response.json()) == {"call_id"}
    assert "X-Request-Id" in response.headers


@pytest.mark.parametrize("prefix", ["fffb", "fffa", "fff3", "ffe3", "ffe2"])
def test_mp3_without_id3_tag_is_accepted(
    robot_client: TestClient, db: Session, audio_root: Path, prefix: str
) -> None:
    # filetype은 FF FA·FF E3·FF E2로 시작하는 MP3를 알아보지 못해 웹 업로드와 판정이 달랐다.
    audio = bytes.fromhex(prefix + "9000") + bytes(range(64)) * 8

    response = register(robot_client, audio, name="c.mp3")

    assert response.status_code == 201
    assert next(audio_root.iterdir()).suffix == ".mp3"


def test_aac_adts_frame_is_not_mistaken_for_mp3(robot_client: TestClient) -> None:
    response = register(robot_client, bytes.fromhex("fff15080") + bytes(300), name="d.mp3")

    assert response.status_code == 415


def test_mp3_is_accepted_and_stored_with_mp3_extension(
    robot_client: TestClient, audio_root: Path
) -> None:
    response = register(robot_client, MP3, name="b.mp3")

    assert response.status_code == 201
    (copy,) = stored_files(audio_root)
    assert copy.suffix == ".mp3"


def test_format_is_decided_by_signature_not_by_file_name(
    robot_client: TestClient, audio_root: Path
) -> None:
    ok = register(robot_client, WAV, name="recording.txt")
    fake = register(robot_client, b"not audio at all" * 50, name="fake.wav")

    assert ok.status_code == 201
    assert fake.status_code == 415
    assert fake.json()["code"] == "UNSUPPORTED_MEDIA"
    assert len(stored_files(audio_root)) == 1


def test_empty_file_is_rejected(robot_client: TestClient, db: Session) -> None:
    response = register(robot_client, b"", file_hash=sha256(b""))

    assert response.status_code == 415
    assert call_count(db) == 0


@pytest.mark.parametrize(
    ("overrides", "incomplete"),
    [
        ({}, False),
        ({"agent_name": None}, True),
        ({"call_datetime": None}, True),
        ({"agent_name": None, "call_datetime": None}, True),
        ({"client_company": None}, False),  # 고객사 누락은 보정 대상이 아니다
        ({"agent_name": "", "call_datetime": ""}, True),  # 빈 값은 없음으로 본다
        ({"agent_name": "   "}, True),
    ],
)
def test_metadata_incomplete_flag(
    robot_client: TestClient, db: Session, overrides: dict[str, Any], incomplete: bool
) -> None:
    response = register(robot_client, **overrides)

    assert response.status_code == 201
    call = db.get(CallRecord, response.json()["call_id"])
    assert call is not None
    assert call.metadata_incomplete is incomplete


def test_missing_metadata_is_stored_as_null_and_processing_continues(
    robot_client: TestClient, db: Session
) -> None:
    response = register(
        robot_client, agent_name="", call_datetime="", client_company="", source_ref=None
    )

    call = db.get(CallRecord, response.json()["call_id"])
    assert call is not None
    assert (call.agent_name, call.call_datetime, call.client_company) == (None, None, None)
    assert call.status == CallStatus.REGISTERED


def test_naive_call_datetime_is_read_as_kst(robot_client: TestClient, db: Session) -> None:
    response = register(robot_client, call_datetime="2026-11-23T14:30:05")

    call = db.get(CallRecord, response.json()["call_id"])
    assert call is not None
    assert call.call_datetime == datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)


def test_uppercase_hash_is_accepted_and_stored_lowercase(
    robot_client: TestClient, db: Session
) -> None:
    response = register(robot_client, file_hash=sha256(WAV).upper())

    assert response.status_code == 201
    call = db.get(CallRecord, response.json()["call_id"])
    assert call is not None
    assert call.file_hash == sha256(WAV)


# ------------------------------------------------------------------ 해시 검증


def test_hash_mismatch_is_422_and_leaves_no_copy_or_row(
    robot_client: TestClient, db: Session, audio_root: Path
) -> None:
    response = register(robot_client, file_hash=sha256(b"another file"))

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["detail"]["errors"][0]["type"] == "hash_mismatch"
    assert body["detail"]["errors"][0]["loc"] == ["body", "file_hash"]
    assert stored_files(audio_root) == []
    assert call_count(db) == 0


# ------------------------------------------------------------------ 중복


@pytest.mark.parametrize("status", list(CallStatus))
def test_duplicate_hash_is_409_with_existing_id_and_status(
    robot_client: TestClient, db: Session, audio_root: Path, status: CallStatus
) -> None:
    existing = make_call_record(db, file_hash=sha256(WAV), status=status)

    response = register(robot_client)

    assert response.status_code == 409
    assert response.json() == {
        "code": "DUPLICATE_FILE",
        "message": "이미 등록된 파일입니다.",
        "detail": {"existing_id": existing.id, "status": status},
    }
    assert stored_files(audio_root) == []  # 중복이면 사본을 만들지 않는다
    assert call_count(db) == 1


def test_soft_deleted_call_does_not_block_reregistration(
    robot_client: TestClient, db: Session
) -> None:
    make_call_record(db, file_hash=sha256(WAV), deleted_at=datetime.now(UTC))

    response = register(robot_client)

    assert response.status_code == 201
    assert call_count(db) == 2


def test_concurrent_duplicate_caught_by_unique_index_is_409_and_copy_removed(
    robot_client: TestClient,
    db: Session,
    audio_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 사전 조회를 지난 뒤 다른 요청이 먼저 등록한 상황 (해시 유니크 인덱스가 마지막 방어선).
    existing = make_call_record(db, file_hash=sha256(WAV), status=CallStatus.QUEUED)
    original = RobotService._find_by_hash
    calls = {"n": 0}

    def find_by_hash(self: RobotService, file_hash: str) -> CallRecord | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else original(self, file_hash)

    monkeypatch.setattr(RobotService, "_find_by_hash", find_by_hash)

    response = register(robot_client)

    assert response.status_code == 409
    assert response.json()["detail"] == {"existing_id": existing.id, "status": "QUEUED"}
    assert stored_files(audio_root) == []
    assert call_count(db) == 1


# ------------------------------------------------------------------ 보상 처리


def test_copy_is_deleted_when_db_registration_fails(
    robot_app: FastAPI,
    db: Session,
    audio_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("DB 장애")

    monkeypatch.setattr(RobotService, "_create_record", boom)
    client = TestClient(
        robot_app,
        client=(ROBOT_IP, 50000),
        headers={"X-API-Key": "test-robot-key"},
        raise_server_exceptions=False,
    )

    response = register(client)

    assert response.status_code == 500
    assert stored_files(audio_root) == []


# ------------------------------------------------------------------ 입력 검증


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"file_hash": "abc"}, "file_hash"),
        ({"file_hash": "z" * 64}, "file_hash"),
        ({"file_hash": None}, "file_hash"),
        ({"original_name": None}, "original_name"),
        ({"source_type": "UNKNOWN"}, "source_type"),
        ({"source_type": None}, "source_type"),
        ({"agent_name": "가" * 51}, "agent_name"),
        ({"client_company": "가" * 101}, "client_company"),
        ({"call_datetime": "어제 오후"}, "call_datetime"),
    ],
)
def test_invalid_form_is_422_without_echoing_input(
    robot_client: TestClient,
    db: Session,
    audio_root: Path,
    overrides: dict[str, Any],
    field: str,
) -> None:
    response = register(robot_client, **overrides)

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert any(field in error["loc"] for error in errors)
    for value in overrides.values():
        if isinstance(value, str) and len(value) > 3:
            assert value not in response.text
    assert stored_files(audio_root) == []
    assert call_count(db) == 0


def test_missing_file_is_422(robot_client: TestClient) -> None:
    response = robot_client.post(
        URL,
        data={"file_hash": sha256(WAV), "original_name": "a.wav", "source_type": "DRIVE"},
    )

    assert response.status_code == 422
    assert any("file" in error["loc"] for error in response.json()["detail"]["errors"])


# ------------------------------------------------------------------ 접근 통제


def test_unauthenticated_request_does_not_store_anything(
    robot_app: FastAPI, db: Session, audio_root: Path
) -> None:
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    response = register(client)

    assert response.status_code == 401
    assert stored_files(audio_root) == []
    assert call_count(db) == 0
