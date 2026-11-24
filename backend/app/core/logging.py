"""structlog JSON 로그 설정과 요청 컨텍스트 바인딩."""

import logging
import sys

import structlog
from starlette.requests import Request

_HANDLER_NAME = "app-json"

_SHARED_PROCESSORS: list[structlog.typing.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.ExtraAdder(),
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def configure_logging(level: str) -> None:
    """루트 로거에 JSON 핸들러를 단다. 여러 번 호출해도 핸들러는 하나만 유지한다."""
    structlog.configure(
        processors=[*_SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_SHARED_PROCESSORS,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # 접근 로그는 RequestIdMiddleware가 구조화해서 남기므로 Uvicorn 접근 로그는 끈다.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def bind_call_id(request: Request, call_id: int) -> None:
    """이후 앱 로그와 요청 종료 접근 로그에 call_id를 붙인다 (동기 엔드포인트에서도 동작)."""
    request.state.call_id = call_id
    structlog.contextvars.bind_contextvars(call_id=call_id)
