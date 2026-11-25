"""R-09 재처리 대상 조회, R-10 음성 다운로드 (실제 PostgreSQL)."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.infra.storage import LocalStorage
from app.schemas.call import CallStatus
from scripts.simulate_robot import make_wav
from tests.conftest import ROBOT_IP
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

S = CallStatus
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def retry_call(db: Session, minutes_ago: int, retry_count: int = 1):  # type: ignore[no-untyped-def]
    return make_call_record(
        db,
        status=S.RETRY_REQUESTED,
        retry_count=retry_count,
        status_changed_at=NOW - timedelta(minutes=minutes_ago),
    )


# ------------------------------------------------------------------ R-09


def test_lists_only_retry_requested_calls_oldest_first(
    robot_client: TestClient, db: Session
) -> None:
    newer = retry_call(db, 10, retry_count=2)
    oldest = retry_call(db, 90, retry_count=1)
    make_call_record(db, status=S.FAILED)
    make_call_record(db, status=S.QUEUED)
    make_call_record(db, status=S.RETRY_REQUESTED, deleted_at=NOW)

    response = robot_client.get("/api/robot/calls", params={"status": "RETRY_REQUESTED"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"call_id": oldest.id, "retry_count": 1},
            {"call_id": newer.id, "retry_count": 2},
        ]
    }


def test_status_defaults_to_retry_requested(robot_client: TestClient, db: Session) -> None:
    call = retry_call(db, 5)

    response = robot_client.get("/api/robot/calls")

    assert response.json()["items"] == [{"call_id": call.id, "retry_count": 1}]


def test_empty_list_is_an_empty_array(robot_client: TestClient) -> None:
    response = robot_client.get("/api/robot/calls")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_list_is_capped_at_100(robot_client: TestClient, db: Session) -> None:
    for minutes in range(105):
        retry_call(db, minutes + 1)

    items = robot_client.get("/api/robot/calls").json()["items"]

    assert len(items) == 100


@pytest.mark.parametrize("status", ["FAILED", "QUEUED", "UNKNOWN", ""])
def test_other_status_values_are_422(robot_client: TestClient, status: str) -> None:
    response = robot_client.get("/api/robot/calls", params={"status": status})

    assert response.status_code == 422
    assert any("status" in e["loc"] for e in response.json()["detail"]["errors"])


def test_list_requires_authentication(robot_app: FastAPI) -> None:
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    assert client.get("/api/robot/calls").status_code == 401


def test_listed_call_is_queued_again_then_leaves_the_list(
    robot_client: TestClient, db: Session
) -> None:
    call = retry_call(db, 5)

    queued = robot_client.patch(
        f"/api/robot/calls/{call.id}/status", json={"status": "QUEUED", "queue_item_id": 77}
    )

    assert queued.status_code == 200
    assert robot_client.get("/api/robot/calls").json() == {"items": []}


# ------------------------------------------------------------------ R-10


@pytest.fixture
def storage(audio_root: Path) -> LocalStorage:
    return LocalStorage(audio_root)


def stored_call(db: Session, storage: LocalStorage, audio: bytes, extension: str = ".wav"):  # type: ignore[no-untyped-def]
    key = storage.save(BytesIO(audio), extension=extension)
    return make_call_record(db, object_key=key, status=S.RETRY_REQUESTED)


def test_downloads_the_stored_copy_byte_for_byte(
    robot_client: TestClient, db: Session, storage: LocalStorage
) -> None:
    audio = make_wav("download", size=300_000)  # 청크 여러 개
    call = stored_call(db, storage, audio)

    response = robot_client.get(f"/api/robot/calls/{call.id}/audio")

    assert response.status_code == 200
    assert response.content == audio
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["content-length"] == str(len(audio))
    assert response.headers["content-disposition"] == f'attachment; filename="call-{call.id}.wav"'


def test_mp3_copy_is_served_as_audio_mpeg(
    robot_client: TestClient, db: Session, storage: LocalStorage
) -> None:
    audio = b"ID3" + bytes(range(256)) * 4
    call = stored_call(db, storage, audio, ".mp3")

    response = robot_client.get(f"/api/robot/calls/{call.id}/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == audio
    assert response.headers["content-disposition"].endswith('.mp3"')


def test_original_filename_is_not_exposed_in_headers(
    robot_client: TestClient, db: Session, storage: LocalStorage
) -> None:
    call = stored_call(db, storage, make_wav("name"))

    response = robot_client.get(f"/api/robot/calls/{call.id}/audio")

    assert call.original_name not in str(response.headers)


def test_works_for_any_status_so_stuck_calls_can_be_reprocessed(
    robot_client: TestClient, db: Session, storage: LocalStorage
) -> None:
    key = storage.save(BytesIO(make_wav("stuck")), extension=".wav")
    call = make_call_record(db, object_key=key, status=S.QUEUED)

    assert robot_client.get(f"/api/robot/calls/{call.id}/audio").status_code == 200


def test_unknown_and_soft_deleted_calls_are_404(
    robot_client: TestClient, db: Session, storage: LocalStorage
) -> None:
    key = storage.save(BytesIO(make_wav("deleted")), extension=".wav")
    deleted = make_call_record(db, object_key=key, deleted_at=NOW)

    assert robot_client.get("/api/robot/calls/999999/audio").status_code == 404
    assert robot_client.get(f"/api/robot/calls/{deleted.id}/audio").status_code == 404


def test_missing_copy_in_storage_is_404_not_500(robot_client: TestClient, db: Session) -> None:
    call = make_call_record(db, object_key="0" * 32 + ".wav")  # 저장소에 없는 키

    response = robot_client.get(f"/api/robot/calls/{call.id}/audio")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_malformed_storage_key_is_404_and_does_not_escape_the_root(
    robot_client: TestClient, db: Session
) -> None:
    call = make_call_record(db, object_key="../../etc/passwd")

    response = robot_client.get(f"/api/robot/calls/{call.id}/audio")

    assert response.status_code == 404


def test_download_requires_authentication(
    robot_app: FastAPI, db: Session, storage: LocalStorage
) -> None:
    call = stored_call(db, storage, make_wav("auth"))
    client = TestClient(robot_app, client=(ROBOT_IP, 50000))

    assert client.get(f"/api/robot/calls/{call.id}/audio").status_code == 401


def test_download_is_rejected_from_a_disallowed_ip(
    robot_app: FastAPI, db: Session, storage: LocalStorage
) -> None:
    call = stored_call(db, storage, make_wav("ip"))
    client = TestClient(
        robot_app, client=("10.9.9.9", 50000), headers={"X-API-Key": "test-robot-key"}
    )

    assert client.get(f"/api/robot/calls/{call.id}/audio").status_code == 403
