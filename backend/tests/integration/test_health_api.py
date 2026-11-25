"""`GET /health` — 실제 PostgreSQL로 DB 확인(SELECT 1) 정상·실패 경로."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infra.storage import LocalStorage
from app.main import create_app

pytestmark = pytest.mark.integration


def test_health_ok_with_real_db(api: TestClient, tmp_path: Path) -> None:
    api.app.state.audio_storage = LocalStorage(tmp_path / "audio")  # type: ignore[attr-defined]

    response = api.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "DISABLED"},
    }


def test_health_is_503_when_db_refuses_connection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # get_db 오버라이드 없이 실제 엔진·세션 경로. 닫힌 포트라 연결 거부로 바로 실패한다.
    refused = "postgresql+psycopg://callcenter:secret-pw@127.0.0.1:1/callcenter"
    app = create_app(Settings(_env_file=None, database_url=refused, audio_storage_root=tmp_path))

    capsys.readouterr()

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "FAIL",
        "checks": {"db": "FAIL", "audio_storage": "OK", "inbox": "DISABLED"},
    }
    assert "secret-pw" not in response.text
    logs = capsys.readouterr().out
    assert "health_check_failed" in logs  # 로그가 실제로 캡처되는지 확인
    assert "secret-pw" not in logs
    assert "127.0.0.1:1" not in logs
