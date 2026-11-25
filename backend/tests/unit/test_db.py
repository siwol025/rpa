"""엔진 연결 인자 — 실제로 연결하지 않고 do_connect 이벤트에서 드라이버에 넘길 값을 확인한다."""

from typing import Any

import pytest
from sqlalchemy import Engine, event

from app.core.db import CONNECT_TIMEOUT_SEC, create_session_factory


class _StopConnectError(Exception):
    pass


def _connect_params(database_url: str) -> dict[str, Any]:
    engine = create_session_factory(database_url).kw["bind"]
    assert isinstance(engine, Engine)
    seen: dict[str, Any] = {}

    @event.listens_for(engine, "do_connect")
    def capture(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]) -> None:
        seen.update(cparams)
        raise _StopConnectError

    with pytest.raises(_StopConnectError):
        engine.connect()
    return seen


def test_engine_sets_connect_timeout() -> None:
    params = _connect_params("postgresql+psycopg://u:p@127.0.0.1:5433/db")

    assert CONNECT_TIMEOUT_SEC == 5
    assert params["connect_timeout"] == CONNECT_TIMEOUT_SEC
