"""실제 PostgreSQL 통합 테스트 픽스처 (임시 — C-05 테스트 기반으로 대체 예정).

DB 선택 순서: `TEST_DATABASE_URL` 환경 변수 → testcontainers `postgres:16` → 둘 다 불가하면 skip.
`TEST_DATABASE_URL`은 **테스트 전용 DB**여야 한다(시작 시 모든 테이블을 지우고 다시 만든다).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from alembic import command
from app.api.deps import get_db
from app.core.config import Settings
from app.main import create_app

_ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


def create_schema(database_url: str) -> None:
    """마이그레이션으로 테스트 스키마를 만든다 (`downgrade base` → `upgrade head`).

    alembic.ini를 읽지 않는다: ini의 로깅 설정(fileConfig)이 앱 로거를 꺼 버리기 때문이다.
    alembic/env.py는 접속 정보를 DATABASE_URL 환경 변수에서만 읽는다.
    """
    config = Config()
    config.set_main_option("script_location", str(_ALEMBIC_DIR))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", database_url)
        command.downgrade(config, "base")
        command.upgrade(config, "head")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
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
def engine(database_url: str) -> Iterator[Engine]:
    create_schema(database_url)
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """테스트마다 바깥 트랜잭션을 열고 끝에 롤백한다 (데이터가 남지 않음)."""
    with engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def api(db_session: Session) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client
