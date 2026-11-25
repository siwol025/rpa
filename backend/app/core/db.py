"""DB 엔진·세션 팩토리 (동기 SQLAlchemy 2.0 + psycopg 3)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_SEC = 5


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """엔진과 세션 팩토리를 만든다. 실제 DB 연결은 첫 쿼리 때 일어난다."""
    # libpq 기본은 연결 타임아웃이 없어 DB 호스트가 응답하지 않으면 OS TCP 타임아웃까지 묶인다.
    engine = create_engine(
        database_url, pool_pre_ping=True, connect_args={"connect_timeout": CONNECT_TIMEOUT_SEC}
    )
    return sessionmaker(bind=engine, expire_on_commit=False)
