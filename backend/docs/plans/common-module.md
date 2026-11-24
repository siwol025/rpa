# 공통 모듈 상세 구현 계획 — 설정 · 로그 · 에러 · CORS · 요청 크기 제한

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` C-02 공통 모듈 |
| 근거 | `docs/researchs/common-module.md` v0.1(이하 "리서치"), `architecture.md` §3.2·§7.2·§10.3·§12, `backend/pyproject.toml`, `backend/.env.example`, `app/main.py`, `tests/unit/test_app_smoke.py`, `backend/.venv` 설치 소스 |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / pydantic 2.14.4 / pydantic-settings 2.16.3 / structlog 26.1.0 / Uvicorn 0.54.0 |
| 사전 검증 | 이 문서의 코드 스니펫을 스크래치 복사본에 그대로 넣고 아래 테스트 계획의 대표 케이스 35개를 돌려 `pytest`·`ruff check`·`mypy .` 통과를 확인함 (레포 코드는 수정하지 않음) |

---

## 1. 목표와 범위

### 1.1 목표
1. `Settings` 하나로 공통 모듈 설정을 읽는다. `.env`가 없어도(CI) 기본값으로 기동·테스트가 된다.
2. 모든 로그(앱·Uvicorn)를 한 줄 JSON으로 출력하고, 요청마다 `request_id`를 자동으로 붙인다. 요청 종료 시 §12 필드(`request_id`, `call_id`, `path`, `status`, `latency_ms`)로 접근 로그를 남긴다.
3. **모든 응답**(200, 4xx, 413, 500, CORS preflight 포함)에 `X-Request-Id` 헤더를 붙인다.
4. 모든 에러 응답을 §7.2 형식 `{"code", "message", "detail"}`으로 통일한다.
5. `CORS_ORIGINS`의 프론트 주소만 허용하고, 브라우저가 `X-Request-Id`를 읽을 수 있게 한다. 에러·500·413 응답에도 CORS 헤더가 붙는다.
6. 요청 전체 크기가 `MAX_UPLOAD_MB`를 넘으면 경로·메서드와 무관하게 413 `PAYLOAD_TOO_LARGE`(§7.2 형식)를 반환한다.

### 1.2 포함
- `app/core/config.py`, `app/core/logging.py`, `app/core/errors.py`, `app/core/middleware.py` 신규
- `app/main.py`의 `create_app()`에 설정 주입·로그 설정·예외 핸들러·미들웨어 등록
- `.env.example` 갱신 (`LOG_LEVEL` 추가, 형식 주석)
- 단위 테스트 (`tests/unit/`)
- 공용 문서 동기화: `architecture.md` §7.2 에러 코드표에 3개 코드 추가, §10.3에 `LOG_LEVEL` 추가

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| 로봇 인증(`X-API-Key`, IP 확인) 구현, `core/security.py` | R-01. 공통 모듈은 아래 1.4의 인터페이스만 제공 |
| `ROBOT_API_KEYS`·`ROBOT_ALLOWED_IPS`·`DATABASE_URL` 등 다른 설정 필드 | 각 기능(R-01, C-04, W-08 등)이 사용할 때 `Settings`에 추가 |
| 목록 응답 형식·에러 응답 Pydantic 모델(OpenAPI 문서화) | C-03 API 규약 |
| 운영 환경 `/docs` 비활성(실행 환경 구분 설정) | C-02 범위 밖. §8 확인 필요 |
| `GET /health` | §12 헬스 체크는 별도 작업 |
| 서비스 계층의 `pydantic.ValidationError` → 422 매핑 | R-07이 검증 방식을 정할 때 `AppError(ErrorCode.VALIDATION_ERROR, ...)`로 변환해 던진다. 공통 모듈은 매핑하지 않음(처리 안 되면 500) |
| 엑셀 다운로드용 `Content-Disposition` CORS 노출 | 해당 기능에서 `expose_headers`에 추가 |
| 테스트 경고 정책(`httpx2` 도입 등) | C-05 테스트 기반 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| 설정 읽기 | `app.core.config.get_settings() -> Settings` (캐시됨), `Settings` | `Depends(get_settings)`, 테스트는 `app.dependency_overrides` |
| 설정 추가 | `Settings`에 필드 추가. 콤마 리스트는 `Annotated[list[str], NoDecode]` + 기존 `_split_comma` validator의 필드 목록에 이름 추가 | `@field_validator("cors_origins", "robot_api_keys", mode="before")` |
| 도메인 에러 | `AppError(code: ErrorCode, message: str \| None = None, detail: dict[str, Any] \| None = None)` | `raise AppError(ErrorCode.DUPLICATE_FILE, detail={"existing_id": 123, "status": "REGISTERED"})` |
| 에러 코드 | `ErrorCode` (`StrEnum`) | `ErrorCode.UNAUTHORIZED`, `ErrorCode.FORBIDDEN_IP` |
| 미들웨어에서 직접 에러 응답 | `error_response(code, *, message=None, detail=None, headers=None, status_code=None) -> JSONResponse` (ASGI 앱) | `await error_response(ErrorCode.FORBIDDEN_IP)(scope, receive, send)` |
| 로거 | `structlog.stdlib.get_logger(__name__)` — `request_id`는 자동 포함 | `log.info("registered", call_id=call.id)` |
| `call_id` 바인딩 | `app.core.logging.bind_call_id(request, call_id)` — 이후 앱 로그와 요청 종료 접근 로그에 `call_id` 포함 (동기 엔드포인트에서도 동작) | 라우터에서 호출 |
| 요청 ID 값 | 헤더 이름 상수 `app.core.middleware.REQUEST_ID_HEADER`, 현재 값은 `structlog.contextvars.get_contextvars()["request_id"]` | |

R-01을 **의존성**으로 구현하면 `AppError`만 던지면 된다. **미들웨어**로 구현하면 예외 핸들러를 거치지 않으므로 `error_response(...)`를 직접 보내고, `create_app()`에서 `UnhandledErrorMiddleware`와 `BodySizeLimitMiddleware` 등록 줄 **사이**에 등록한다(요청 ID·500 처리 안쪽, 크기 검사보다 먼저 인증 — §4 참고).

---

## 2. 결정 사항

사용자 확정 4건과 리서치 §6.2의 22개 질문에 대한 결정이다.

| # (§6.2) | 질문 | 결정 | 근거 |
|---|---|---|---|
| 1 | 크기 한도 범위 | **모든 API 공통**으로 `MAX_UPLOAD_MB` 하나 | 사용자 확정. `features.md` C-02 "모든 API 공통" |
| 2 | MB 단위 | `MAX_UPLOAD_MB * 1024 * 1024` (MiB) | 사용자 확정 |
| 3 | 한도 기준 | **요청 전체 바이트**(multipart 경계·헤더 포함). 다중 파일 업로드는 "파일 합계 + 오버헤드 ≤ 한도" | 사용자 확정. 미들웨어는 파일 단위를 모름 |
| 4 | 구현 방식 | 순수 ASGI `BodySizeLimitMiddleware`. FastAPI 내장 `max_body_size`는 **사용하지 않음**(함께 쓰면 내장 limiter가 커스텀 413을 plain text로 덮어씀, 리서치 §4-1) | 사용자 확정. 리서치 §3.3 (B) |
| 5 | 추가 에러 코드 | `BAD_REQUEST`(400), `METHOD_NOT_ALLOWED`(405), `INTERNAL_ERROR`(500). 라우팅 404는 `NOT_FOUND` 재사용 | 사용자 확정 |
| 6 | `message` | **한국어 기본 메시지 표**(코드당 1개). `AppError`는 `message`를 넘기면 덮어씀. `HTTPException`의 영어 `detail`은 응답에 쓰지 않음 | 사용자 확정(한국어). 프론트가 `message`를 그대로 표시 가능 |
| 7 | `VALIDATION_ERROR` detail | `{"errors": [{"loc", "msg", "type"}, ...]}`. `input`(사용자 확정)과 함께 `ctx`·`url`도 제외 | `ctx`는 입력에서 나온 값·직렬화 불가 객체(예외 인스턴스)를 담을 수 있고, `url`은 pydantic 문서 링크라 불필요 |
| 8 | X-Request-Id 재사용 | 요청 헤더가 `[A-Za-z0-9-]{1,64}`에 **완전 일치**하면 재사용, 아니면 새로 생성 | 사용자 확정. 로그 인젝션·길이 공격 차단 |
| 9 | 생성 형식 | `str(uuid.uuid4())` (하이픈 포함 36자) | 재사용 허용 문자 집합 안에 들어가고, 로그에서 읽기 쉬움 |
| 10 | preflight에 X-Request-Id | **붙임** | 사용자 확정("모든 응답"). §4 순서로 해결 |
| 11 | CORS 상세 | `allow_origins=CORS_ORIGINS`(콤마), `allow_methods=["*"]`, `allow_headers=["*"]`, `expose_headers=["X-Request-Id"]`, `allow_credentials=False`(기본) | origin을 제한하므로 메서드·헤더는 `*`로 충분. 로그인·쿠키 없음(`prd.md` §3.2). 로봇은 CORS 무관 |
| 12 | 리스트 환경 변수 형식 | **콤마 구분**으로 통일. 이번에는 `CORS_ORIGINS`만 선언. JSON 배열 형식은 지원하지 않음 | 사용자 확정. `.env.example` 현재 형식, §10.3 "쉼표 구분". `ROBOT_ALLOWED_IPS`의 CIDR 여부는 R-01이 결정 |
| 13 | Settings 범위 | 공통 모듈이 쓰는 값(`MAX_UPLOAD_MB`, `CORS_ORIGINS`, `LOG_LEVEL`)만 선언, `extra='ignore'` | 사용자 확정 |
| 14 | 필수 값·기본값 | 모든 필드에 개발용 기본값 (`100`, `["http://localhost:5173"]`, `"INFO"`) | 사용자 확정. `.env` 없는 CI에서 `create_app()` 스모크 테스트 유지. 이후 필수 필드(예: `DATABASE_URL`)를 추가하는 기능은 기본값 또는 테스트 주입 방법을 함께 정한다 |
| 15 | 추가 설정 변수 | `LOG_LEVEL`(`DEBUG`/`INFO`/`WARNING`/`ERROR`, 기본 `INFO`)만 추가. 로그 형식 전환(콘솔용)·실행 환경 구분은 두지 않음 | 운영 디버깅에 레벨 조정은 필요, 나머지는 C-02 요구가 아님 |
| 16 | 타임스탬프 시간대 | **UTC** ISO 8601 (`...Z`) | 서버 저장 규칙(UTC, `back_stack.md` §3.3)과 동일. 로그 수집 도구와 호환 |
| 17 | 접근 로그 | 앱 미들웨어(`RequestIdMiddleware`)가 §12 필드로 구조화해 남기고 **Uvicorn 접근 로그는 끔**(`uvicorn.access` logger `disabled`) | 중복 방지, `status`·`latency_ms`가 구조화된 필드여야 함(리서치 §3.4). `/health`는 아직 없으므로 제외 규칙 없음 |
| 18 | 로그 필드 범위 | `method`, `path`(쿼리 문자열 제외), `status`, `latency_ms`, `call_id`, `request_id`. 클라이언트 IP·User-Agent·쿼리·본문·헤더 값은 남기지 않음 | PII 원칙(검색어 `q`에 이름 가능), `X-API-Key` 노출 방지 |
| 19 | 500에 CORS 헤더 | **붙임** | "모든 응답에 X-Request-Id" + 프론트가 500의 `X-Request-Id`를 읽어 문의에 쓸 수 있어야 의미가 있음. §4 순서로 해결 |
| 20 | R-01 위치 | 공통 모듈은 **두 방식 모두** 지원(`AppError`·`error_response`). 결정은 R-01 | 1.4 표 |
| 21 | UiPath 조기 413 | 공통 모듈은 `Content-Length` 초과 시 본문을 읽지 않고 즉시 413. 클라이언트 처리 여부는 §8 확인 필요 | |
| 22 | 테스트 경고 정책 | 변경 없음(경고 표시만, `filterwarnings` 추가 안 함) | C-05 범위. 경고를 오류로 바꾸면 기존 스모크 테스트가 실패 |

추가 결정 (리서치 §3·§4의 함정에서 나온 것)

| 항목 | 결정 | 근거 |
|---|---|---|
| 미들웨어 구현 | 모두 순수 ASGI. `BaseHTTPMiddleware` 사용 안 함 | 본문 카운트 불가, 스트리밍 오버헤드, contextvars 단방향(리서치 §3.2) |
| 수신 중 초과 예외 | `starlette.exceptions.HTTPException(413)` 하위 클래스 `_BodyTooLargeError` | 아니면 FastAPI가 400으로 바꿈(`fastapi/routing.py` `except HTTPException: raise`, 리서치 §3.3 (C)) |
| HTTPException 핸들러 등록 키 | `starlette.exceptions.HTTPException` | 라우팅 404/405와 FastAPI `HTTPException` 둘 다 잡힘 |
| HTTPException 상태 → 코드 | 400→`BAD_REQUEST`, 401→`UNAUTHORIZED`, 404→`NOT_FOUND`, 405→`METHOD_NOT_ALLOWED`, 413→`PAYLOAD_TOO_LARGE`. 표에 없는 4xx는 `BAD_REQUEST`, 5xx는 `INTERNAL_ERROR`. **HTTP 상태 코드는 원래 값 유지**, `exc.headers`(예: `Allow`, `WWW-Authenticate`) 유지 | 공통 예외는 `AppError`로 던지는 것이 원칙이고 `HTTPException`은 프레임워크 내부(라우팅·본문 파싱·`APIKeyHeader`)에서만 발생 |
| JSON 문법 오류 | FastAPI 동작대로 422 `VALIDATION_ERROR`(`type: "json_invalid"`) | FastAPI가 `RequestValidationError`로 변환(`fastapi/routing.py`). 400 `BAD_REQUEST`는 multipart 깨짐 등 FastAPI의 "error parsing the body" 경로. §8 확인 필요 |
| 예외 클래스 구조 | `AppError` **하나** + `ErrorCode` + 코드별 (상태, 메시지) 표. 코드별 하위 클래스는 만들지 않음 | 단일 용도 클래스 9개를 피함. 서비스 계층은 HTTP 상태를 몰라도 됨(§3.1). 필요해지면 하위 클래스 추가는 비호환 변경이 아님 |
| `detail` 키 | 항상 포함, 없으면 `null` | 클라이언트 파싱 일관성 |
| 미처리 예외 로그 | `UnhandledErrorMiddleware`가 `log.exception`으로 직접 남김(응답 후 재발생하지 않음). 응답이 이미 시작된 뒤의 예외는 재발생 → Uvicorn이 로그(JSON)를 남기고 연결 종료 | 리서치 §3.4 "미처리 예외 로그" |
| 예외 로그 형식 | `format_exc_info`(문자열 `exception` 필드) | `dict_tracebacks`는 너무 김 |
| 한글 로그 | `JSONRenderer()` 기본값(`ensure_ascii=True`, 한글은 `\uXXXX`) | Windows 콘솔(cp949) 깨짐 방지(리서치 §3.4) |
| 컨텍스트 누수 | 요청 시작 시 `clear_contextvars()` 후 `request_id` 바인딩 | Uvicorn `reset_contextvars` 기본 False(리서치 §3.4) |
| `call_id` 전달 | `request.state.call_id`(=`scope["state"]`, 공유 dict) + `bind_contextvars` 둘 다 | 동기 엔드포인트의 contextvars 변경은 미들웨어로 돌아오지 않음(리서치 §3.4) |
| 로그 핸들러 중복 | 이름(`app-json`)을 붙인 핸들러만 교체. 다른 루트 핸들러(pytest 등)는 유지 | `create_app()`이 여러 번 호출돼도(테스트) 로그가 한 줄씩만 나옴 |
| `httpx` 로그 | `WARNING`으로 올림 | 테스트·Drive 클라이언트의 INFO 로그 소음(리서치 §3.4) |
| 설정 주입 | `create_app(settings: Settings \| None = None)`. 없으면 `get_settings()` | CORS origin·크기 한도는 미들웨어 등록 시점에 필요(리서치 §3.8). 기존 인자 없는 호출 호환 |

---

## 3. 파일별 변경 목록

| 구분 | 경로 | 내용 |
|---|---|---|
| 신규 | `backend/app/core/config.py` | `Settings`, `get_settings()` |
| 신규 | `backend/app/core/logging.py` | `configure_logging(level)`, `bind_call_id(request, call_id)` |
| 신규 | `backend/app/core/errors.py` | `ErrorCode`, `AppError`, `error_response()`, `register_exception_handlers(app)` |
| 신규 | `backend/app/core/middleware.py` | `REQUEST_ID_HEADER`, `RequestIdMiddleware`, `UnhandledErrorMiddleware`, `BodySizeLimitMiddleware` |
| 수정 | `backend/app/main.py` | `create_app(settings=None)`: 로그 설정, 핸들러·미들웨어(CORS 포함) 등록 |
| 수정 | `backend/.env.example` | `LOG_LEVEL` 추가, 리스트·단위 주석 |
| 신규 | `backend/tests/unit/conftest.py` | `build_app` 팩토리 픽스처(테스트 라우트 포함), `client` 픽스처 |
| 신규 | `backend/tests/unit/test_config.py` | Settings |
| 신규 | `backend/tests/unit/test_errors.py` | 에러 응답 매핑 |
| 신규 | `backend/tests/unit/test_request_id.py` | X-Request-Id |
| 신규 | `backend/tests/unit/test_body_size_limit.py` | 413 |
| 신규 | `backend/tests/unit/test_cors.py` | CORS, 모든 응답의 공통 헤더 |
| 신규 | `backend/tests/unit/test_logging.py` | JSON 로그 |
| 유지 | `backend/tests/unit/test_app_smoke.py` | 변경 없음(인자 없는 `create_app()` 계속 통과해야 함) |
| 수정 | `backend/docs/architecture/architecture.md` | §7.2 표에 `BAD_REQUEST`(400)·`METHOD_NOT_ALLOWED`(405)·`INTERNAL_ERROR`(500) 추가, §10.3 표에 `LOG_LEVEL` 추가, `MAX_UPLOAD_MB` 설명을 "요청 전체 크기 한도(MiB), 모든 API 공통"으로 |

새 의존성 없음 (`pydantic-settings`, `structlog` 이미 포함).

---

## 4. 미들웨어 등록 순서

### 4.1 최종 스택 (바깥 → 안)
```
ServerErrorMiddleware            (Starlette 내장. 이제 사실상 도달하지 않음)
ExceptionTelemetryMiddleware     (FastAPI 내장)
AppBodyLimitMiddleware           (FastAPI 내장, max_body_size=None → 통과)
── user_middleware ──
RequestIdMiddleware              ① X-Request-Id 결정·부여, request_id 바인딩, 접근 로그
CORSMiddleware                   ② preflight 응답, CORS 헤더
UnhandledErrorMiddleware         ③ 미처리 예외 → §7.2 500 + 에러 로그
(R-01 인증 미들웨어 자리)         ※ 미들웨어 방식을 택할 경우
BodySizeLimitMiddleware          ④ Content-Length 사전 검사, 수신 누적 검사
── ──
ExceptionMiddleware              AppError / HTTPException / RequestValidationError 핸들러
AsyncExitStackMiddleware
Router
```
`add_middleware()`는 `user_middleware.insert(0, ...)`(Starlette 1.10 `applications.py`)이므로 **나중에 등록한 것이 바깥**이다. 코드에서는 ④ → ③ → ② → ① 순서로 등록한다.

### 4.2 이유 (리서치 §3.5 순서 트레이드오프의 3번째 안)
| 응답 | 생성 위치 | 거쳐 나가는 미들웨어 | X-Request-Id | CORS |
|---|---|---|---|---|
| 정상 200 | Router | ④③②① | ✓ | ✓ |
| 404/405/409/422/chunked 413 | ExceptionMiddleware | ④③②① | ✓ | ✓ |
| Content-Length 초과 413 | ④ | ③②① | ✓ | ✓ |
| 미처리 예외 500 | ③ | ②① | ✓ | ✓ |
| CORS preflight | ② | ① | ✓ | ✓ |

- ①이 CORS 바깥이어야 preflight에도 `X-Request-Id`가 붙는다.
- ③이 CORS 안쪽이어야 500에도 CORS 헤더가 붙는다. 500 처리를 ①에 합치면 CORS 바깥이 되어 CORS 헤더가 빠지므로 별도 미들웨어로 둔다.
- ④가 ①②③ 안쪽이어야 413에 두 헤더가 붙고, ④에서 생긴 예상 밖 예외도 ③이 처리한다.
- 접근 로그는 ①에 있으므로 413·500·preflight도 한 줄씩 기록된다.

---

## 5. 모듈별 코드

아래 코드는 스크래치 복사본에서 `ruff check`·`ruff format --check`·`mypy`(strict)·테스트 통과를 확인한 형태다.

### 5.1 `app/core/config.py`
```python
"""환경 변수 설정 (pydantic-settings)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """공통 모듈이 쓰는 설정. 각 기능은 필요한 필드를 여기에 추가한다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_upload_mb: int = Field(default=100, gt=0)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
```
- `env_file=".env"`는 작업 디렉터리 기준. README(`cd backend`)와 컨테이너(`/app`) 모두 맞음(리서치 §3.8).
- `NoDecode`가 없으면 `list[str]`은 JSON으로만 파싱되어 `http://localhost:5173`에서 기동 실패한다(리서치 §3.8).
- `max_upload_bytes`는 속성(`@property`)이라 환경 변수로 읽히지 않는다.
- 테스트는 `Settings(_env_file=None, ...)`로 개발자 `.env`를 차단한다(pydantic mypy 플러그인에서 통과 확인).

### 5.2 `app/core/logging.py`
```python
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
```
- 모듈 이름이 `logging`이지만 `app/core/logging.py` 안의 `import logging`은 절대 import라 표준 라이브러리를 가리킨다.
- `configure_logging()`은 `create_app()`에서 호출한다. Uvicorn은 앱 import **전에** 자체 dictConfig를 적용하므로(`--reload`·`--workers` 포함, 리서치 §3.4) 앱 쪽 설정이 마지막에 적용된다.
- 핸들러는 생성 시점의 `sys.stdout`을 잡는다 → 로그 테스트는 `capsys`가 켜진 **테스트 본문 안에서** 앱을 만들어야 한다(§7.2 주의).

### 5.3 `app/core/errors.py`
```python
"""공통 예외와 에러 응답 매핑 (architecture.md §7.2)."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    NOT_FOUND = "NOT_FOUND"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN_IP = "FORBIDDEN_IP"
    INBOX_UNAVAILABLE = "INBOX_UNAVAILABLE"
    BAD_REQUEST = "BAD_REQUEST"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 코드 → (HTTP 상태, 기본 메시지)
_ERROR_SPECS: dict[ErrorCode, tuple[int, str]] = {
    ErrorCode.VALIDATION_ERROR: (422, "요청 형식이 올바르지 않습니다."),
    ErrorCode.DUPLICATE_FILE: (409, "이미 등록된 파일입니다."),
    ErrorCode.INVALID_STATE_TRANSITION: (409, "현재 상태에서 허용되지 않는 요청입니다."),
    ErrorCode.NOT_FOUND: (404, "대상을 찾을 수 없습니다."),
    ErrorCode.PAYLOAD_TOO_LARGE: (413, "요청 크기가 제한을 초과했습니다."),
    ErrorCode.UNSUPPORTED_MEDIA: (415, "허용되지 않은 파일 형식입니다."),
    ErrorCode.UNAUTHORIZED: (401, "인증에 실패했습니다."),
    ErrorCode.FORBIDDEN_IP: (403, "허용되지 않은 IP입니다."),
    ErrorCode.INBOX_UNAVAILABLE: (503, "업로드 저장소를 사용할 수 없습니다."),
    ErrorCode.BAD_REQUEST: (400, "잘못된 요청입니다."),
    ErrorCode.METHOD_NOT_ALLOWED: (405, "허용되지 않은 메서드입니다."),
    ErrorCode.INTERNAL_ERROR: (500, "서버 내부 오류가 발생했습니다."),
}

# HTTPException 상태 → 코드. 표에 없는 4xx는 BAD_REQUEST, 5xx는 INTERNAL_ERROR (상태 코드는 유지).
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
}


class AppError(Exception):
    """서비스·라우터가 던지는 공통 예외. HTTP 객체에 의존하지 않는다."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or _ERROR_SPECS[code][1]
        self.detail = detail
        super().__init__(self.message)


def error_response(
    code: ErrorCode,
    *,
    message: str | None = None,
    detail: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    """§7.2 형식 에러 응답. JSONResponse는 ASGI 앱이라 미들웨어에서도 그대로 보낼 수 있다."""
    default_status, default_message = _ERROR_SPECS[code]
    return JSONResponse(
        status_code=status_code or default_status,
        content={"code": code, "message": message or default_message, "detail": detail},
        headers=headers,
    )


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.code, message=exc.message, detail=exc.detail)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    fallback = ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST
    code = _STATUS_TO_CODE.get(exc.status_code, fallback)
    return error_response(code, headers=dict(exc.headers or {}), status_code=exc.status_code)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # input(요청 값 원문)·ctx·url은 PII·크기 문제로 내보내지 않는다.
    errors = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return error_response(ErrorCode.VALIDATION_ERROR, detail={"errors": errors})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
```
- 핸들러 시그니처를 `exc: Exception`으로 두고 `assert isinstance`로 좁히는 것은 Starlette `ExceptionHandler` 타입(`Callable[[Request, Exception], ...]`)에 맞춰 mypy strict를 통과시키기 위함.
- `Exception`/`500` 키 핸들러는 등록하지 않는다. 등록하면 `ServerErrorMiddleware`(사용자 미들웨어 바깥)에서 실행되어 헤더가 빠진다(리서치 §3.1). 500은 `UnhandledErrorMiddleware`가 처리한다.
- `JSONResponse`는 `StrEnum` 값을 문자열로 직렬화한다.

### 5.4 `app/core/middleware.py`
```python
"""순수 ASGI 미들웨어: 요청 ID·접근 로그, 미처리 예외 500, 요청 크기 제한."""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ErrorCode, error_response

REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")

_access_log = structlog.stdlib.get_logger("app.access")
_error_log = structlog.stdlib.get_logger("app.error")


class RequestIdMiddleware:
    """X-Request-Id 결정·응답 헤더 부여, request_id 컨텍스트 바인딩, 요청 종료 접근 로그."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        if incoming is not None and _REQUEST_ID_PATTERN.fullmatch(incoming):
            request_id = incoming
        else:
            request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status = 500
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _access_log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 1),
                call_id=scope.get("state", {}).get("call_id"),
            )


class UnhandledErrorMiddleware:
    """처리되지 않은 예외를 §7.2 형식 500으로 바꾼다. CORS 안쪽에 둬야 CORS 헤더가 붙는다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            if response_started:
                raise
            _error_log.exception("unhandled_exception")
            await error_response(ErrorCode.INTERNAL_ERROR)(scope, receive, send)


class _BodyTooLargeError(StarletteHTTPException):
    # Starlette HTTPException 계열이어야 FastAPI 본문 읽기에서 400으로 바뀌지 않는다.
    def __init__(self) -> None:
        super().__init__(status_code=413)


class BodySizeLimitMiddleware:
    """요청 본문이 max_bytes를 넘으면 413. Content-Length 사전 검사 + 수신 중 누적 검사."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > self.max_bytes
        ):
            await error_response(ErrorCode.PAYLOAD_TOO_LARGE)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError()
            return message

        await self.app(scope, limited_receive, send)
```
동작 메모
- `RequestIdMiddleware`의 접근 로그 `status`: 응답이 시작되지 못한 경우는 초기값 500, 응답 시작 후 예외가 올라온 경우도 500으로 덮어쓴다.
- `call_id`는 `scope["state"]`에서 읽는다. Starlette `Request.state`는 `scope["state"]` dict를 감싸므로 동기 엔드포인트에서 `request.state.call_id = ...`로 쓴 값이 보인다(리서치 §3.4 실측).
- `Content-Length` 초과는 메서드·경로와 무관하게 본문을 읽기 전에 413 (없는 경로도 404가 아니라 413). 이후 연결 처리는 Uvicorn이 한다.
- 수신 중 초과는 `_BodyTooLargeError` → FastAPI 본문 읽기에서 그대로 재발생(`except HTTPException: raise`) → `ExceptionMiddleware` → `_handle_http_exception`이 413을 `PAYLOAD_TOO_LARGE`로 매핑.
- 본문을 읽지 않는 엔드포인트(GET 등)는 누적 검사가 일어나지 않는다(읽지 않으니 영향 없음).
- **제약**: 본문을 읽지 않고 `StreamingResponse`를 돌려주는 엔드포인트에 `Content-Length` 없이(chunked) 한도를 넘는 본문이 오면, Starlette의 연결 끊김 감시(`listen_for_disconnect`)가 본문을 소비하다 응답 시작 후 `_BodyTooLargeError`가 나서 413 없이 연결이 끊긴다. 현재 해당 라우트는 없다. 스트리밍 응답 엔드포인트(예: 엑셀 다운로드)를 추가할 때 응답 시작 여부를 추적해 초과 시 `http.disconnect`를 돌려주는 방식으로 해결한다.
- `X-Request-Id`는 응답 헤더에 덮어쓴다(엔드포인트가 같은 헤더를 넣어도 1개만 남는다).
- `Content-Length`는 ASCII 숫자일 때만 사전 검사한다(`"²"` 같은 값이 `int()` 오류로 500이 되지 않게).

### 5.5 `app/main.py` (CORS 설정 포함)
```python
"""FastAPI 애플리케이션 진입점.

라우터 등록은 각 기능(W-*, R-*)에서 추가한다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    RequestIdMiddleware,
    UnhandledErrorMiddleware,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Callcenter AI RPA Backend", version="0.1.0")
    register_exception_handlers(app)

    # add_middleware는 목록 맨 앞에 끼워 넣으므로 나중에 등록한 것이 바깥에서 실행된다.
    # 실행 순서(바깥 → 안): RequestId → CORS → UnhandledError → BodySizeLimit → 라우터
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIdMiddleware)
    return app


app = create_app()
```
- `FastAPI(max_body_size=...)`는 지정하지 않는다(결정 4).
- 모듈 수준 `app = create_app()`은 유지(Uvicorn `app.main:app`, Dockerfile.dev).

---

## 6. `.env.example` 변경

```diff
 # --- 업로드 / 처리 기준 ---
+# 요청 전체 크기 한도(MiB, 1024²바이트). 모든 API 공통, 초과 시 413 PAYLOAD_TOO_LARGE
 MAX_UPLOAD_MB=100
 ALLOWED_EXTENSIONS=wav,mp3
 REVIEW_CONFIDENCE_THRESHOLD=0.7
 STALE_THRESHOLD_MIN=30

 # --- 웹 ---
+# 쉼표 구분 (예: http://localhost:5173,http://10.0.0.5:5173)
 CORS_ORIGINS=http://localhost:5173
+
+# --- 로그 ---
+# DEBUG | INFO | WARNING | ERROR
+LOG_LEVEL=INFO
```
기존 키·값은 그대로 둔다(`extra='ignore'`로 미선언 키는 무시). 테스트 T6이 이 파일을 실제로 읽어 호환을 확인한다.

---

## 7. 로그 필드 정의

모든 로그는 stdout 한 줄 JSON. 공통 필드는 `merge_contextvars`·`add_log_level`·`add_logger_name`·`TimeStamper`가 넣는다.

| 필드 | 타입 | 포함 로그 | 설명 |
|---|---|---|---|
| `event` | str | 전체 | 이벤트 이름. 접근 로그 `"request"`, 미처리 예외 `"unhandled_exception"` |
| `level` | str | 전체 | `debug`/`info`/`warning`/`error` |
| `logger` | str | 전체 | 로거 이름. 접근 로그 `app.access`, 미처리 예외 `app.error`, 앱 코드 `__name__`, Uvicorn `uvicorn.error` |
| `timestamp` | str | 전체 | UTC ISO 8601, `Z` 접미사 |
| `request_id` | str | 요청 처리 중 남긴 모든 로그 | `X-Request-Id`와 같은 값 |
| `call_id` | int \| null | 접근 로그(항상), 앱 로그(`bind_call_id` 이후) | 없으면 접근 로그에서 `null` |
| `method` | str | 접근 로그 | HTTP 메서드 |
| `path` | str | 접근 로그 | 경로만(쿼리 문자열 제외) |
| `status` | int | 접근 로그 | 응답 상태 코드 |
| `latency_ms` | float | 접근 로그 | 소수 1자리. BackgroundTasks 실행 시간을 포함한다 |
| `exception` | str | `log.exception` 사용 시 | 트레이스백 문자열 |

남기지 않는 것: 요청·응답 본문, 쿼리 문자열, 헤더 값(`X-API-Key` 등), 클라이언트 IP, User-Agent.

예시
```json
{"event": "request", "method": "GET", "path": "/api/calls/42", "status": 200, "latency_ms": 3.4, "call_id": 42, "request_id": "0b6f...", "level": "info", "logger": "app.access", "timestamp": "2026-11-24T01:23:45.678901Z"}
```

---

## 8. 확인 필요

| # | 항목 | 확인 대상 | 영향 |
|---|---|---|---|
| 1 | **UiPath HTTP Request 액티비티가 본문 전송 중 받은 조기 413(서버가 본문을 다 읽지 않고 응답 후 연결 종료)을 응답으로 읽는지**, 아니면 연결 오류로 보고 재시도하는지 | RPA 파트 (E-04 합의 항목 후보) | 읽지 못하면 로봇이 413을 네트워크 오류로 처리해 2회 재시도할 수 있음(`research.md` §3.4 [가정]). 공통 모듈 구현은 바꾸지 않고 로봇 쪽 처리 규칙으로 해결 |
| 2 | 추가 에러 코드 3개(`BAD_REQUEST`·`METHOD_NOT_ALLOWED`·`INTERNAL_ERROR`)와 한국어 기본 메시지 표, `VALIDATION_ERROR`의 `detail.errors[]` 형식 | 프론트, C-03 API 규약 리뷰 | `architecture.md` §7.2 갱신과 함께 공유 |
| 3 | 잘못된 JSON 본문은 FastAPI 동작대로 **422 `VALIDATION_ERROR`(`type: json_invalid`)**로 두고, 400 `BAD_REQUEST`는 multipart 깨짐 등 "본문 파싱 실패"에만 쓰는 것으로 충분한지 | 사용자 | 400으로 바꾸려면 `_handle_validation_error`에서 `json_invalid` 분기 추가 |
| 4 | `LOG_LEVEL` 환경 변수 신설 | 사용자 / 공용 문서 | `architecture.md` §10.3·`.env.example` 반영 |
| 5 | 운영 환경 `/docs` 비활성(`architecture.md` §7.1)을 위한 실행 환경 설정 | 배포(O-*) 작업 시 | 이번 범위 밖. `create_app()`에 인자 추가로 대응 가능 |
| 6 | 실제 Uvicorn 기동 시 로그가 모두 JSON이고 `uvicorn.access` 중복이 없는지 | 구현 후 수동 확인(§9.2) | 단위 테스트로는 Uvicorn dictConfig 이후 동작을 재현하지 않음 |
| 7 | **validator 에러 메시지에 입력값을 넣지 않는다.** `VALIDATION_ERROR`의 `detail.errors[].msg`는 그대로 응답에 나가므로, 커스텀 validator가 `ValueError(f"... {value}")`처럼 입력값을 메시지에 넣으면 전화번호 등이 노출된다 | C-03 API 규약에 규칙으로 추가 | 코드 변경 없음 |
| 8 | 미처리 예외 로그(`exception`)의 트레이스백에 예외 메시지 원문이 남는다(예: DB `IntegrityError`의 파라미터 값) | DB 연동(C-04) 시 | 필요하면 로그 처리기에서 마스킹 |

---

## 9. 테스트 계획 (TDD 순서)

### 9.1 원칙
- 공개 인터페이스로만 검증: HTTP 요청/응답(`TestClient`), `Settings(...)` 생성, 로그는 stdout JSON 출력.
- 설정은 항상 `Settings(_env_file=None, ...)`로 만들어 개발자 `.env`의 영향을 막는다(`test_app_smoke.py`는 예외 — 인자 없는 `create_app()` 호환 확인용).
- `uv run mypy .`가 `tests/`도 검사하므로(현재 17파일) 테스트 함수·픽스처에 타입을 붙인다.
- 크기 테스트는 `max_upload_mb=1`(1 MiB = 1,048,576바이트)로 앱을 만든다.
- chunked 전송은 httpx `content=`에 제너레이터를 넘긴다(`Transfer-Encoding: chunked`, `Content-Length` 없음).
- 미처리 500 테스트는 `TestClient` 기본값(`raise_server_exceptions=True`)으로 둔다. 예외가 테스트로 재발생하지 않는 것 자체가 `UnhandledErrorMiddleware`가 삼켰다는 검증이다.

### 9.2 공용 픽스처 — `tests/unit/conftest.py`
```python
from collections.abc import Callable, Iterator
from typing import Annotated, Any

import pytest
import structlog
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import bind_call_id
from app.main import create_app


class Item(BaseModel):
    name: str
    count: int


def _build_test_app(**overrides: Any) -> FastAPI:
    """개발자 .env 영향 없이 앱을 만들고 테스트용 라우트를 붙인다."""
    app = create_app(Settings(_env_file=None, **overrides))

    @app.post("/echo")  # 본문 원문 길이 반환 (크기 제한)
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/items")  # JSON 본문 검증 (422, 405)
    def create_item(item: Item) -> Item:
        return item

    @app.post("/upload")  # multipart (400, 413)
    def upload(file: Annotated[UploadFile, File()]) -> dict[str, str]:
        return {"name": file.filename or ""}

    @app.get("/app-error")
    def raise_app_error() -> None:
        raise AppError(
            ErrorCode.DUPLICATE_FILE, detail={"existing_id": 123, "status": "REGISTERED"}
        )

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom-secret")

    @app.get("/calls/{call_id}")  # 동기 엔드포인트에서 call_id 바인딩 + 앱 로그
    def get_call(call_id: int, request: Request) -> dict[str, int]:
        bind_call_id(request, call_id)
        structlog.stdlib.get_logger("app.test").info("in endpoint")
        return {"call_id": call_id}

    return app


@pytest.fixture
def build_app() -> Callable[..., FastAPI]:
    return _build_test_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_build_test_app(max_upload_mb=1)) as test_client:
        yield test_client
```
필요한 테스트 라우트(예: `AppError(message=...)`, `HTTPException(401, headers=...)`, `HTTPException(429)`)는 위 목록에 추가하거나 각 테스트에서 `build_app()` 결과에 붙인다. 로그 테스트는 `capsys`가 활성화된 테스트 본문에서 `build_app()`을 호출해야 출력이 잡힌다(핸들러가 생성 시점의 `sys.stdout`을 잡음).

공통 단언 헬퍼(각 파일 또는 conftest): `assert_error(resp, status, code)` — 상태 코드, `content-type: application/json`, `body["code"] == code`, `message`가 비어 있지 않은 문자열, `"detail"` 키 존재.

### 9.3 케이스 목록 (구현 순서)

**단계 1 — Tracer bullet** (`test_errors.py`) · 구현: `Settings` 최소형, `create_app(settings)`, `register_exception_handlers`(HTTPException), `RequestIdMiddleware`(헤더 부여만)

| ID | 입력 | 기대 결과 |
|---|---|---|
| T1 | `GET /nope` | 404, `{"code":"NOT_FOUND","message":"대상을 찾을 수 없습니다.","detail":null}`, 응답에 `X-Request-Id` 헤더 존재 |

**단계 2 — Settings** (`test_config.py`) · 구현: `config.py` 완성

| ID | 입력 | 기대 결과 |
|---|---|---|
| T2 | `Settings(_env_file=None)` (관련 환경 변수 없음) | `max_upload_mb == 100`, `max_upload_bytes == 104_857_600`, `cors_origins == ["http://localhost:5173"]`, `log_level == "INFO"` |
| T3 | env `CORS_ORIGINS="http://a:1, http://b:2 ,"` | `["http://a:1", "http://b:2"]` (공백 제거, 빈 항목 제외) |
| T4 | env `CORS_ORIGINS=""` | `[]` |
| T5 | `tmp_path/.env`에 `UNKNOWN_KEY=x`, `MAX_UPLOAD_MB=5` → `Settings(_env_file=그 경로)` | 오류 없음, `max_upload_mb == 5` |
| T6 | `Settings(_env_file=<backend>/.env.example)` | 오류 없음(미선언 키 다수 무시), `max_upload_mb == 100`, `cors_origins == ["http://localhost:5173"]`, `log_level == "INFO"` |
| T7 | env `MAX_UPLOAD_MB` = `"0"` / `"abc"` (parametrize 2) | `pydantic.ValidationError` |
| T8 | env `LOG_LEVEL="verbose"` | `pydantic.ValidationError` |
| T9 | 기존 `test_app_smoke.py` | 변경 없이 통과 |

**단계 3 — X-Request-Id** (`test_request_id.py`) · 구현: 재사용 규칙

| ID | 입력 | 기대 결과 |
|---|---|---|
| T10 | `GET /calls/1` (헤더 없음) | `X-Request-Id`가 UUID4 (`uuid.UUID(v, version=4)` 성공, 36자) |
| T11 | `X-Request-Id: robot-123-abc` | 응답 헤더 값 동일 |
| T12 | `X-Request-Id: "a"*64` | 그대로 재사용 (경계값) |
| T13 | `X-Request-Id`: `"a"*65`, `"has space"`, `"a_b"`, `"a.b"`, `""` (parametrize 5) | 입력값과 다른 새 UUID4 |
| T14 | 헤더 없이 2회 요청 | 두 응답의 `X-Request-Id`가 서로 다름 |

**단계 4 — 에러 매핑** (`test_errors.py`) · 구현: `AppError`, 전체 핸들러, `UnhandledErrorMiddleware`

| ID | 입력 | 기대 결과 |
|---|---|---|
| T15 | `GET /app-error` | 409, `code=DUPLICATE_FILE`, `message="이미 등록된 파일입니다."`, `detail={"existing_id":123,"status":"REGISTERED"}` |
| T16 | `AppError(ErrorCode.NOT_FOUND, message="상담 건을 찾을 수 없습니다.")`를 던지는 라우트 | 404, `message`가 넘긴 값 |
| T17 | `GET /items` (POST 전용) | 405, `code=METHOD_NOT_ALLOWED`, `Allow: POST` 헤더 유지 |
| T18 | `POST /items` JSON `{"name":"홍길동","count":"many"}` | 422, `code=VALIDATION_ERROR`, `detail.errors == [{"loc":["body","count"],"msg":<문자열>,"type":"int_parsing"}]`, 응답 본문에 `"many"`·`input`·`ctx`·`url` 없음 |
| T19 | `POST /items` 본문 `b"{bad"`, `Content-Type: application/json` | 422, `code=VALIDATION_ERROR`, `detail.errors[0].type == "json_invalid"` |
| T20 | `POST /upload` 본문 `b"garbage"`, `Content-Type: multipart/form-data; boundary=xyz` | 400, `code=BAD_REQUEST`, `message="잘못된 요청입니다."` |
| T21 | `HTTPException(401, headers={"WWW-Authenticate":"APIKey"})`를 던지는 라우트 | 401, `code=UNAUTHORIZED`, `WWW-Authenticate` 헤더 유지 |
| T22 | `HTTPException(429)`를 던지는 라우트 | 429(상태 유지), `code=BAD_REQUEST` (표에 없는 4xx 대체) |
| T23 | `GET /boom` (`RuntimeError("boom-secret")`) | 예외가 테스트로 올라오지 않음, 500, `code=INTERNAL_ERROR`, `message="서버 내부 오류가 발생했습니다."`, 본문에 `boom-secret` 없음, `X-Request-Id` 존재 |

**단계 5 — 요청 크기 제한** (`test_body_size_limit.py`) · 구현: `BodySizeLimitMiddleware`, `main.py` 등록 · `client`(1 MiB)

| ID | 입력 | 기대 결과 |
|---|---|---|
| T24 | `POST /echo` 본문 1,048,576바이트(Content-Length) | 200, `{"size":1048576}` (한도와 같으면 허용) |
| T25 | `POST /echo` 본문 1,048,577바이트(Content-Length) | 413, `{"code":"PAYLOAD_TOO_LARGE","message":"요청 크기가 제한을 초과했습니다.","detail":null}` |
| T26 | `POST /nope` 본문 1,048,577바이트 | 404가 아니라 413 `PAYLOAD_TOO_LARGE` (라우팅 전 검사) |
| T27 | `POST /echo` chunked 1,048,577바이트(64 KiB 조각) | 413 `PAYLOAD_TOO_LARGE` |
| T28 | `POST /items` chunked 1,048,577바이트, `Content-Type: application/json` | 400이 아니라 413 `PAYLOAD_TOO_LARGE` (FastAPI 본문 파싱 경로) |
| T29 | `POST /echo` chunked 정확히 1,048,576바이트 | 200, `{"size":1048576}` |
| T30 | `POST /upload` multipart `files={"file": ("a.wav", b"a"*(MiB+1))}` | 413 `PAYLOAD_TOO_LARGE` |
| T31 | `build_app(max_upload_mb=2)`로 만든 앱에 1.5 MiB `POST /echo` | 200 (설정 값이 한도에 반영됨) |

**단계 6 — CORS와 모든 응답의 공통 헤더** (`test_cors.py`) · 구현: `CORSMiddleware` 등록·순서 확정

| ID | 입력 | 기대 결과 |
|---|---|---|
| T32 | `Origin: http://localhost:5173`과 함께 parametrize 8건: `GET /calls/1`(200), `GET /nope`(404), `GET /items`(405), `GET /app-error`(409), `POST /items` 잘못된 값(422), `POST /echo` CL 초과(413), `POST /echo` chunked 초과(413), `GET /boom`(500) | 각 기대 상태, 모두 `X-Request-Id` 존재 + `Access-Control-Allow-Origin: http://localhost:5173` |
| T33 | `OPTIONS /items` + `Origin: http://localhost:5173`, `Access-Control-Request-Method: PATCH`, `Access-Control-Request-Headers: content-type,x-request-id` | 200, `Access-Control-Allow-Origin` 일치, `Access-Control-Allow-Methods`에 `PATCH` 포함, `X-Request-Id` 존재 |
| T34 | `GET /calls/1` + 허용 Origin | `Access-Control-Expose-Headers`에 `X-Request-Id` 포함, `Access-Control-Allow-Credentials` 헤더 없음 |
| T35 | `GET /calls/1` + `Origin: http://evil.example` | 200, `Access-Control-Allow-Origin` 없음, `X-Request-Id`는 존재 |
| T36 | 비허용 Origin으로 preflight | 400, `X-Request-Id` 존재 |
| T37 | `build_app(cors_origins=["http://other:3000"])`, `Origin: http://other:3000` | `Access-Control-Allow-Origin: http://other:3000` (설정 반영) |

**단계 7 — 로그** (`test_logging.py`) · 구현: `configure_logging`, 접근 로그, `bind_call_id` · 모두 `capsys` 사용, 본문에서 `build_app()` 호출, stdout을 줄 단위 `json.loads`

| ID | 입력 | 기대 결과 |
|---|---|---|
| T38 | `GET /calls/42?q=secret`, `X-Request-Id: rid-1` | `logger == "app.access"` 줄이 정확히 1개: `request_id=="rid-1"`, `method=="GET"`, `path=="/calls/42"`, `status==200`, `latency_ms`는 float, `level=="info"`, `timestamp`가 `Z`로 끝남 |
| T39 | T38과 같은 요청 | 접근 로그 `call_id == 42` (동기 엔드포인트의 `bind_call_id`가 미들웨어 로그에 반영) |
| T40 | T38과 같은 요청 | 엔드포인트 앱 로그(`logger=="app.test"`, `event=="in endpoint"`)에 `request_id=="rid-1"`, `call_id==42` |
| T41 | T38과 같은 요청 | 전체 출력에 `secret` 없음(쿼리 미기록) |
| T42 | `GET /boom`, `X-Request-Id: rid-2` | `logger=="app.error"` 줄 1개: `level=="error"`, `request_id=="rid-2"`, `exception`에 `RuntimeError` 포함. 접근 로그 `status==500` |
| T43 | `POST /echo` 1 MiB 초과(`build_app(max_upload_mb=1)`) | 접근 로그 `status==413` |
| T44 | `GET /calls/7` 후 `GET /nope` | 두 번째 접근 로그 `call_id is None`, 두 `request_id`가 다름 (컨텍스트 누수 없음) |
| T45 | `build_app()` 2회 호출 후 요청 1건 | 접근 로그가 정확히 1줄 (핸들러 중복 없음) |
| T46 | `build_app()` 후 `logging.getLogger("uvicorn.error").warning("x")` | 같은 JSON 형식 줄, `logger=="uvicorn.error"`, `level=="warning"` |
| T47 | `build_app(log_level="WARNING")` 후 `GET /calls/1` | 접근 로그(INFO) 출력 없음 |

### 9.4 케이스 수
| 단계 | 케이스 ID | 수 (parametrize 펼친 수) |
|---|---|---|
| 1 | T1 | 1 |
| 2 | T2–T9 | 8 (9) |
| 3 | T10–T14 | 5 (9) |
| 4 | T15–T23 | 9 |
| 5 | T24–T31 | 8 |
| 6 | T32–T37 | 6 (13) |
| 7 | T38–T47 | 10 |
| 합계 | | **47개 케이스** (pytest 실행 기준 약 59건, 기존 스모크 포함) |

T38–T41은 같은 요청을 쓰므로 하나의 테스트 함수로 묶어도 된다(동작 단위가 달라 ID만 분리).

### 9.5 검증 명령
```bash
cd backend
uv run pytest                 # 전체 (tests/unit)
uv run ruff check .
uv run ruff format --check .
uv run mypy .                 # 명령줄 대상 "."이 pyproject의 files=["app"]를 대체 → tests/ 포함 strict 검사
```
- pre-commit의 mypy 훅은 `app/`만 검사하지만 위 명령은 `tests/`까지 검사한다. 둘 다 통과해야 한다.
- Starlette `TestClient`의 `StarletteDeprecationWarning`(httpx) 경고 1건은 정상(결정 22).

수동 확인 (확인 필요 #6)
```bash
cd backend
uv run uvicorn app.main:app --port 8000
curl -i http://127.0.0.1:8000/nope                                  # 404 JSON + X-Request-Id
curl -i -X POST --data-binary @<100MiB 초과 파일> http://127.0.0.1:8000/nope   # 413 JSON
```
- 콘솔 출력이 기동 로그 포함 모두 JSON이고, 요청당 `app.access` 한 줄만 있으며 Uvicorn 기본 접근 로그(`"GET /nope HTTP/1.1" 404`)가 없는지 확인.

---

## 10. 구현 시 주의
1. `Exception`/`500` 키로 예외 핸들러를 등록하지 않는다(헤더 누락, §5.3).
2. `FastAPI(max_body_size=...)`를 함께 쓰지 않는다(커스텀 413이 plain text로 바뀜).
3. 수신 중 초과 예외를 `AppError`로 바꾸지 않는다(400으로 변환됨).
4. 미들웨어 등록 순서를 바꾸면 §4.2 표가 깨진다. 새 미들웨어는 §4.1의 위치 규칙을 따른다.
5. 테스트에서 `from app.main import app`(모듈 수준 앱)을 쓰지 않는다 — 개발자 `.env`를 읽는다.
