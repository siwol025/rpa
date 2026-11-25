"""공통 테스트 픽스처.

- `postgres_url`: 테스트 DB. `TEST_DATABASE_URL` 환경 변수 → testcontainers `postgres:16`
  → 둘 다 불가하면 skip. `TEST_DATABASE_URL`은 **테스트 전용 DB**여야 한다(시작 시 모든
  테이블을 지우고 Alembic 으로 다시 만든다).
- `db`: 테스트마다 트랜잭션을 열고 끝나면 롤백한다. 테스트 코드가 `commit()` 해도 격리된다.
- `client`: FastAPI TestClient.
- `api`: 웹 API용. 개발자 .env 없이 만든 앱이 `db`를 쓴다.
- `robot_client`: 로봇 API용. 인증 헤더·허용 IP가 설정되고 `db`·임시 음성 저장소를 쓴다.

DB 가 필요한 테스트는 `db` 픽스처를 쓰고 `@pytest.mark.integration` 을 붙인다.
Docker 없이 돌리려면 `pytest -m "not integration"`.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.api.deps import get_db
from app.core.config import Settings
from app.main import create_app

ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic"


def create_schema(database_url: str) -> None:
    """마이그레이션으로 테스트 스키마를 만든다 (`downgrade base` → `upgrade head`).

    alembic.ini를 읽지 않는다: ini의 로깅 설정(fileConfig)이 앱 로거를 꺼 버리기 때문이다.
    alembic/env.py는 접속 정보를 DATABASE_URL 환경 변수에서만 읽는다.
    """
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", database_url)
        command.downgrade(config, "base")
        command.upgrade(config, "head")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer("postgres:16", driver="psycopg")
        container.start()
    except Exception as exc:  # Docker 없음·데몬 꺼짐·이미지 받기 실패
        pytest.skip(
            f"PostgreSQL 사용 불가(TEST_DATABASE_URL 없음, Docker 실패): {type(exc).__name__}"
        )
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def engine(postgres_url: str) -> Iterator[Engine]:
    create_schema(postgres_url)
    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """테스트 종료 시 롤백되는 세션. 코드 안의 commit() 은 SAVEPOINT 해제로만 동작한다."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    # get_db 의존성이 생기면(C-02) app.dependency_overrides 로 `db` 픽스처를 주입한다.
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def api(db: Session) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


ROBOT_KEY = "test-robot-key"
ROBOT_IP = "127.0.0.1"


@pytest.fixture
def audio_root(tmp_path: Path) -> Path:
    return tmp_path / "audio"


@pytest.fixture
def robot_app(db: Session, audio_root: Path) -> FastAPI:
    app = create_app(
        Settings(
            _env_file=None,
            robot_api_keys=[ROBOT_KEY],
            robot_allowed_ips=[ROBOT_IP],
            audio_storage_root=audio_root,
        )
    )
    # 요청이 테스트의 db 세션을 그대로 쓴다. 서비스의 commit()도 테스트 끝에 롤백된다.
    app.dependency_overrides[get_db] = lambda: db
    return app


@pytest.fixture
def robot_client(robot_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(
        robot_app, client=(ROBOT_IP, 50000), headers={"X-API-Key": ROBOT_KEY}
    ) as test_client:
        yield test_client
