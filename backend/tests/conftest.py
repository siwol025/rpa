"""공통 테스트 픽스처.

- `postgres_url`: 세션당 PostgreSQL 16 컨테이너 1개를 띄우고 Alembic 으로 최신 스키마를 적용한다.
- `db`: 테스트마다 트랜잭션을 열고 끝나면 롤백한다. 테스트 코드가 `commit()` 해도 격리된다.
- `client`: FastAPI TestClient.

DB 가 필요한 테스트는 `db` 픽스처를 쓰고 `@pytest.mark.integration` 을 붙인다.
Docker 없이 돌리려면 `pytest -m "not integration"`.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        # alembic/env.py 는 DATABASE_URL 환경 변수만 읽는다.
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        finally:
            if previous is None:
                del os.environ["DATABASE_URL"]
            else:
                os.environ["DATABASE_URL"] = previous
        yield url


@pytest.fixture(scope="session")
def engine(postgres_url: str) -> Iterator[Engine]:
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
