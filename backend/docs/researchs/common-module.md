# 공통 모듈 리서치 — 설정 · 로그 · 에러 · CORS · 요청 크기 제한

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` C-02 공통 모듈 (관련: C-03 API 규약, R-01 로봇 인증, W-07 웹 업로드, R-04 등록) |
| 근거 | `docs/prd.md`, `docs/input_flow.md`, `architecture.md` v0.3, `back_stack.md` v0.1, `research.md` v0.2, `features.md` v0.2, `backend/uv.lock`, `backend/.venv` 설치 소스 |
| 검증 방법 | 설치된 라이브러리 소스를 직접 읽고, 스크래치 스크립트로 `TestClient`·실제 Uvicorn에서 동작을 확인함 (레포 코드는 수정하지 않음) |

> 이 문서는 구현 계획이 아니라 **사실 조사**다. 코드 예시는 동작 확인용 스케치이며 최종 설계는 별도 계획 문서에서 정한다.

---

## 0. 요약 (핵심 발견)

1. **설치 버전이 문서 작성 시점 가정보다 훨씬 새롭다.** FastAPI 0.165.0 / Starlette 1.10.0 / pydantic-settings 2.16.3 / structlog 26.1.0 / Uvicorn 0.54.0.
2. **FastAPI 0.165에는 요청 본문 크기 제한 기능(`FastAPI(max_body_size=...)`)이 내장돼 있다.** 그러나 `Content-Length`가 한도를 넘는 경우 응답이 **`text/plain` "Content Too Large"로 고정**되고 `X-Request-Id`·CORS 헤더가 붙지 않는다(실측). §7.2 에러 형식(`{code, message, detail}`)을 만족하지 못한다.
3. 직접 만든 순수 ASGI 미들웨어로 본문 바이트를 셀 때, 초과 시 던지는 예외가 **Starlette `HTTPException`의 하위 클래스가 아니면 FastAPI가 `400 "There was an error parsing the body"`로 바꿔 버린다**(실측, `fastapi/routing.py`). → 413 예외는 `HTTPException` 계열이어야 한다.
4. 처리되지 않은 예외(500)는 Starlette의 최외곽 `ServerErrorMiddleware`가 응답하므로 **사용자 미들웨어가 붙이는 `X-Request-Id`·CORS 헤더가 빠진다**(실측). "모든 응답에 `X-Request-Id`"(§7.2)를 지키려면 별도 처리가 필요하다.
5. pydantic-settings에서 `list[str]` 필드는 환경 변수를 **JSON으로만** 파싱한다. `CORS_ORIGINS=http://localhost:5173`(현재 `.env.example` 형식)은 그대로 두면 **기동 실패**한다(실측). 콤마 구분을 쓰려면 `NoDecode` + validator가 필요하다.
6. `BaseSettings`의 기본값이 `extra='forbid'`라서, `.env` 파일에 `Settings`가 선언하지 않은 키가 있으면 **검증 오류로 기동 실패**한다(실측). `.env.example`의 키 전부를 선언하거나 `extra='ignore'`가 필요하다.
7. structlog `contextvars` + `ProcessorFormatter` 조합으로 앱 로그·`uvicorn.access` 로그를 같은 JSON 형식과 `request_id`로 묶을 수 있다(실측). 단 **동기(def) 엔드포인트에서 바인딩한 값은 미들웨어로 되돌아오지 않는다**(스레드풀이 컨텍스트를 복사).

---

## 1. 요구사항 — 출처별 정리

### 1.1 기능 정의
| 출처 | 내용 |
|---|---|
| `features.md` §2.1 C-02 | 설정(`Settings`), structlog JSON 로그·`X-Request-Id`, 공통 예외 → 에러 응답 매핑, **CORS**(`CORS_ORIGINS`), **요청 크기 제한 미들웨어**(`MAX_UPLOAD_MB` 초과 시 413, **모든 API 공통**). P0, Phase 1, 선행 C-01 |
| `features.md` §2.1 C-03 | 응답·에러 코드·페이지네이션 형식 확정(`architecture.md` §7.2), OpenAPI 공유 방식 |
| `features.md` R-04 / W-07 | "형식 검증(**크기 제한은 C-02**)" — 엔드포인트는 크기 검사를 하지 않고 공통 모듈에 맡김 |
| `features.md` §5 | R-01~R-10 전체가 C-02(에러·로그·요청 크기 제한)·C-03을 사용. "**에러 코드·로그 형식을 1주차에 먼저 확정**" |
| `features.md` 한눈에 보기 | 주 수정 위치 중 `core/` 가 포함됨. 단 `core/security.py`는 R-01 로봇 인증 용도(§3.2) |

### 1.2 디렉터리 (`architecture.md` §3.2)
```
app/main.py           # FastAPI 앱 생성, 라우터·미들웨어 등록
app/core/config.py    # pydantic-settings (환경 변수)
app/core/logging.py   # JSON 구조화 로그, request_id
app/core/errors.py    # 공통 예외 → 에러 응답 매핑
app/core/security.py  # 로봇 API Key 검증 (R-01)
app/schemas/common    # 공통 스키마 (에러·목록 응답 모델 후보)
```
계층 규칙(§3.1): Service 계층은 HTTP 객체(Request/Response)에 의존 금지 → 서비스는 **HTTP와 무관한 도메인 예외**를 던지고, 매핑은 `core/errors.py`가 담당하는 구조가 문서와 맞는다.

### 1.3 에러 형식과 코드 (`architecture.md` §7.2)
```json
{ "code": "DUPLICATE_FILE", "message": "이미 등록된 파일입니다.", "detail": { "existing_id": 123, "status": "REGISTERED" } }
```
| 코드 | HTTP | 상황 | 발생 위치(예상) |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | 요청·GenAI JSON 스키마 불일치 | FastAPI `RequestValidationError`, R-07 |
| `DUPLICATE_FILE` | 409 | 등록 시 해시 중복, `detail`에 `existing_id`·`status` | R-04 |
| `INVALID_STATE_TRANSITION` | 409 | 허용되지 않은 상태 전이 | R-02 (R-05~08, W-03, W-05) |
| `NOT_FOUND` | 404 | 없음 또는 소프트 삭제 | 조회 전반 |
| `PAYLOAD_TOO_LARGE` | 413 | 요청 크기 `MAX_UPLOAD_MB` 초과 | **C-02 미들웨어** |
| `UNSUPPORTED_MEDIA` | 415 | 허용되지 않은 파일 형식 | R-04, W-07 |
| `UNAUTHORIZED` | 401 | 로봇 API Key 오류 | R-01 |
| `FORBIDDEN_IP` | 403 | `/api/robot/*` 비허용 IP | R-01 |
| `INBOX_UNAVAILABLE` | 503 | Drive 업로드 실패 | W-07/W-08 |

- 목록 형식: `{ "items": [...], "page": 1, "size": 20, "total": 154 }`
- 시간: `TIMESTAMPTZ` 저장, API는 ISO 8601(+09:00) (`back_stack.md` §3.3: 서버 저장 UTC, 응답 +09:00)
- **모든 응답에 `X-Request-Id` 포함**, 로봇은 이 값과 `call_id`를 UiPath 로그에 남김 (`architecture.md` §7.2, `research.md` §3.4 "추적")
- `research.md` §5.3: 에러 포맷 `{code, message, detail}`을 프론트와 먼저 합의

### 1.4 설정 / 환경 변수 (`architecture.md` §10.3, `.env.example`)
| 이름 | 설명 | `.env.example` 값 | 비고 |
|---|---|---|---|
| `DATABASE_URL` | PostgreSQL 접속 문자열 | `postgresql+psycopg://...@localhost:5432/callcenter` | |
| `AUDIO_STORAGE_BACKEND` | `local` \| `gcs` | `local` | |
| `AUDIO_STORAGE_ROOT` / `GCS_BUCKET` | 음성 사본 위치 | `./data/audio` / (주석) | |
| `INBOX_BACKEND` | `drive` \| `local` \| `disabled` | `local` | Phase 1은 `disabled` (§10.1) |
| `DRIVE_INBOX_FOLDER_ID` / `INBOX_LOCAL_PATH` | 웹 업로드 대상 | (주석) / `./data/inbox` | |
| `GOOGLE_APPLICATION_CREDENTIALS` | 서비스 계정 키 경로 | (주석) | §3 함정 참고 |
| `ROBOT_API_KEYS` | **쉼표 구분**, 교체 중 2개 허용 | `dev-robot-key` | 리스트 |
| `MAX_UPLOAD_MB` | 업로드 최대 크기 (기본 100), 앱에서 검사 | `100` | |
| `ROBOT_ALLOWED_IPS` | `/api/robot/*` 허용 IP | `127.0.0.1` | 리스트(형식 미정) |
| `ALLOWED_EXTENSIONS` | `wav,mp3` | `wav,mp3` | 쉼표 리스트 |
| `REVIEW_CONFIDENCE_THRESHOLD` | 검토 임계값 (기본 0.7 [가정]) | `0.7` | |
| `STALE_THRESHOLD_MIN` | 정체 기준(분) (기본 30 [가정]) | `30` | |
| `CORS_ORIGINS` | 프론트 주소 | `http://localhost:5173` | 리스트(형식 미정) |

- `back_stack.md` §2.3: "환경 변수는 `Settings` 클래스 하나로 로드 (`.env` 지원)"
- 문서에 **없는** 설정: 로그 레벨, 로그 출력 형식(JSON/콘솔), 실행 환경 구분(운영에서 `/docs` 비활성 — `architecture.md` §7.1, `back_stack.md` §7)

### 1.5 로그 (`architecture.md` §12, `back_stack.md` §2.4, `research.md` §8.3)
- JSON 구조화 로그. 필드: `request_id`, `call_id`, `path`, `status`, `latency_ms`
- 요청마다 `request_id`·`call_id` 바인딩, 로봇 로그와 `X-Request-Id`로 연결
- Docker 로그 로테이션 (컨테이너 설정 영역)
- 보안(§11, `research.md` §7): DB에는 마스킹된 텍스트만, 음성 재생·다운로드 **접근 로그 기록**(W-06), 비밀값은 `.env`
- PII 원칙(`prd.md` AI-06, 설계 원칙 7): 로그에도 요청 본문·키 값을 남기지 않는 것이 원칙과 일관됨 (문서에 명시 조항은 없음)

### 1.6 CORS
- `CORS_ORIGINS` = 프론트 주소 (§10.3). 프론트가 별도 서버면 백엔드는 `CORS_ORIGINS`만 설정 (`back_stack.md` §6.1)
- 로그인 없음(`prd.md` §3.2, WEB-07) → 쿠키·인증 헤더 기반 credential 요청이 필요 없음
- 프론트가 `X-Request-Id`를 읽어야 하는지는 문서에 명시 없음 (§6 질문)

### 1.7 요청 크기 제한
| 출처 | 내용 |
|---|---|
| `back_stack.md` §6.1 | Nginx 대체: "앱에서 **`Content-Length` 확인 + 수신 중 누적 크기 검사**로 `MAX_UPLOAD_MB`(기본 100) 초과 시 413" |
| `architecture.md` §10.1 | 업로드 용량 제한 → 앱에서 `MAX_UPLOAD_MB` 초과 시 413 |
| `research.md` §3.4 | 등록 요청에 음성 파일이 포함되므로 업로드 한도(예: 100MB)를 **로봇 요청에도 동일 적용** |
| `research.md` §7 | 악성 파일 업로드 대응: 최대 용량 제한(예: 100MB) |
| `features.md` C-02 | **모든 API 공통** |
| `features.md` O-03 | VM 배포 시 "요청 크기 제한 동작 확인" |
| `features.md` W-07 | 웹 업로드는 **다중 파일** |

### 1.8 배포·실행 맥락
- Uvicorn 직접 노출(리버스 프록시 없음), `--workers 2~4` (`back_stack.md` §2.2, §6.1)
- 엔드포인트는 **동기(def) + 동기 SQLAlchemy**가 기본 (`back_stack.md` §2.2) → contextvars 전파 특성에 영향 (§3.4)
- 로봇 HTTP 호출: 타임아웃 30초, 5xx·네트워크 오류 시 2회 재시도 [가정] (`research.md` §3.4) → 5xx/413 응답 형식과 연결 끊김 처리에 민감

---

## 2. 현재 코드 상태 (브랜치 `feat/common-module`, 커밋 `793ec3f`)

| 파일 | 상태 |
|---|---|
| `app/main.py` | `create_app()`이 `FastAPI(title="Callcenter AI RPA Backend", version="0.1.0")`만 반환. 모듈 수준 `app = create_app()` |
| `app/core/__init__.py` | 빈 파일. `config.py`·`logging.py`·`errors.py`·`security.py` 없음 |
| `app/api/`, `schemas/`, `services/` 등 | 모두 빈 `__init__.py`만 존재 (`api/deps.py` 없음) |
| `tests/unit/test_app_smoke.py` | `TestClient(create_app())`로 `/openapi.json` 200·title 확인. **인자 없는 `create_app()` 호출에 의존** |
| `tests/integration/` | 비어 있음 (C-05 예정) |
| `.env.example` | §1.4 표의 값. 리스트형 값이 모두 **콤마/단일 문자열** 형식 |
| `Dockerfile.dev` | `python:3.12-slim` + uv 0.13.9, `WORKDIR /app`, `uvicorn app.main:app --reload`, `PYTHONUNBUFFERED=1` |
| `deploy/docker-compose.dev.yml` | `env_file: ../backend/.env (required: false)` + `environment`로 `DATABASE_URL`·`AUDIO_STORAGE_ROOT`·`INBOX_*` 덮어씀. `../backend`를 `/app`에 바인드 마운트 → 컨테이너 안에서도 `/app/.env`가 보임 |
| `README.md` | 로컬 실행 `cd backend && uv run uvicorn app.main:app --reload` (작업 디렉터리 = `backend/`) |
| `.pre-commit-config.yaml` | ruff check/format, mypy(app/), `.env`·키 파일 커밋 차단 |

### 2.1 `pyproject.toml` 도구 설정 중 영향 있는 것
- 의존성에 `pydantic-settings`, `structlog` 이미 포함 → **새 의존성 추가 없이 구현 가능**
- mypy: `strict = true`, `warn_unreachable = true`, `plugins = ["pydantic.mypy"]`, 대상 `app/`만
- Ruff: `E,W,F,I,UP,B,SIM,N,C4,RUF`, line-length 100, `RUF001~003` 무시(한글)
- pytest: `testpaths=["tests"]`, `--strict-markers`, 마커 `integration` 등록됨

### 2.2 설치 버전 (`uv.lock` = `.venv` 일치 확인)
| 패키지 | 버전 | 비고 |
|---|---|---|
| fastapi | **0.165.0** | 내장 `max_body_size`, `form_limits`, OpenTelemetry 미들웨어 내장 |
| starlette | **1.10.0** | `RequestBodyLimitMiddleware` 내장, TestClient가 httpx 사용 시 `StarletteDeprecationWarning`("install `httpx2`") 출력 |
| pydantic | 2.14.4 | |
| pydantic-settings | 2.16.3 | `NoDecode`/`ForceDecode`, `enable_decoding`, `env_file_depth` |
| pydantic-core | 2.50.5 | |
| structlog | 26.1.0 | |
| uvicorn | 0.54.0 | `reset_contextvars` 옵션(기본 False) |
| httpx | 0.28.1 | |
| python-multipart | 0.0.34 | |
| python-dotenv | 1.2.4 | |
| anyio | 4.16.0 | |

---

## 3. 라이브러리 API 스펙 분석 (설치 버전 기준)

### 3.1 미들웨어 스택 구조 (FastAPI 0.165 `build_middleware_stack`)

`fastapi/applications.py` 실제 순서 (바깥 → 안):
```
ServerErrorMiddleware(handler=exception_handlers[500 or Exception])   # 최외곽, 미처리 예외 → 500
ExceptionTelemetryMiddleware
AppBodyLimitMiddleware(max_body_size=app.max_body_size)                # None이면 통과
  ... user_middleware (add_middleware 로 등록한 것) ...
ExceptionMiddleware(handlers=그 외 exception_handlers)                 # HTTPException·커스텀 예외 처리
AsyncExitStackMiddleware
Router
```
- `add_middleware()`는 `user_middleware.insert(0, ...)` → **나중에 등록한 미들웨어가 더 바깥**에서 실행된다.
- `exception_handlers`에서 키가 `500` 또는 `Exception`인 핸들러만 `ServerErrorMiddleware`로 가고, 나머지는 `ExceptionMiddleware`(사용자 미들웨어보다 **안쪽**)에서 처리된다.
- 결과적으로:
  - `HTTPException`·`RequestValidationError`·커스텀 예외 핸들러의 응답 → 사용자 미들웨어를 **통과**해 나감 → `X-Request-Id`·CORS 헤더가 붙음 (실측 ✅)
  - `Exception`/500 핸들러의 응답 → 사용자 미들웨어 **바깥**에서 생성 → 헤더가 **안 붙음** (실측 ❌)
- FastAPI는 기본으로 `HTTPException`, `RequestValidationError` 핸들러를 `setdefault`로 등록 → 사용자가 같은 키로 등록하면 대체된다. 기본 응답은 `{"detail": ...}` 형식이라 §7.2와 다르다.
- Starlette의 라우팅 404/405는 **Starlette `HTTPException`**을 던진다. FastAPI의 `HTTPException`은 그 하위 클래스이므로, 핸들러는 `starlette.exceptions.HTTPException`에 등록해야 둘 다 잡힌다 (실측: 404 `/nope`, 405 `GET /json` 모두 커스텀 형식).

### 3.2 `BaseHTTPMiddleware` vs 순수 ASGI 미들웨어

| 항목 | `BaseHTTPMiddleware` (`starlette/middleware/base.py`) | 순수 ASGI (`async __call__(scope, receive, send)`) |
|---|---|---|
| 응답 처리 | 하위 앱을 **별도 task**에서 실행, 메시지를 anyio 메모리 스트림으로 받아 `_StreamingResponse`로 재조립 | 메시지를 그대로 전달, 필요한 메시지만 수정 |
| 스트리밍·Range(206) | 동작은 하나 청크마다 스트림 경유 오버헤드. `pathsend`·`early_hint`는 별도 분기 | 영향 없음 (`http.response.start` 헤더만 손대면 됨) |
| 요청 본문 | `receive`를 감쌀 수 없음 → **수신 중 바이트 카운트 불가**. `request.body()`를 읽으면 본문 전체를 메모리에 캐시 | `receive`를 감싸 바이트 카운트 가능 → 크기 제한에 필수 |
| contextvars | `dispatch`에서 설정한 값은 하위로 전파되지만, **하위(엔드포인트)에서 설정한 값은 돌아오지 않음** (별도 task) | 같은 task → async 엔드포인트에서 설정한 값이 미들웨어에서 보임 (실측) |
| 예외 | 하위 예외를 `call_next`에서 재발생 | `try/except`로 직접 처리 |

→ 요청 크기 제한은 **반드시 순수 ASGI**. 요청 ID·접근 로그도 음성 Range 스트리밍(W-06)·음성 다운로드(R-10)를 고려하면 순수 ASGI가 유리하다.

### 3.3 요청 크기 제한 — 세 가지 방식 실측 비교

실험 조건: 한도 100바이트, CORS(`allow_origins=["http://localhost:5173"]`, `expose_headers=["X-Request-Id"]`) + 요청 ID 미들웨어 + 커스텀 `HTTPException` 핸들러.

**(A) FastAPI 내장 `FastAPI(max_body_size=N)`**

동작 원리: `starlette/middleware/body_limit.py`의 `RequestBodyLimitResponder`
- `receive_with_limit`: `Content-Length > max`이면 첫 `receive`에서 즉시 `_RequestBodyTooLarge`(= `HTTPException(413)`), 아니면 누적 바이트 초과 시 같은 예외
- `send_with_limit`: **`Content-Length > max`인 요청이면 앱이 어떤 응답을 보내든 `http.response.start` 시점에 `PlainTextResponse("Content Too Large", 413)`로 갈아 끼움**
- `AppBodyLimitMiddleware`가 사용자 미들웨어 **바깥**에 위치

| 요청 | 결과 |
|---|---|
| `Content-Length` 초과 (JSON) | `413 text/plain "Content Too Large"`, `X-Request-Id` 없음, CORS 헤더 없음 ❌ |
| `Content-Length` 초과 (multipart) | 위와 동일 ❌ |
| 없는 경로 + `Content-Length` 초과 | 위와 동일 (404가 아니라 413) |
| chunked(헤더 없음) 초과 | `_RequestBodyTooLarge`가 `ExceptionMiddleware`의 `HTTPException` 핸들러로 감 → 커스텀 JSON 413 + 헤더 ✅ (단 `code`는 핸들러가 413을 `PAYLOAD_TOO_LARGE`로 매핑해야 함) |

→ 가장 흔한 경우(브라우저·UiPath 모두 `Content-Length`를 보냄)에 §7.2 형식·`X-Request-Id`를 만족하지 못한다. 프론트는 CORS 헤더가 없어 응답 자체를 읽을 수 없다. 라우터/경로별 `max_body_size`도 같은 `RequestBodyLimitMiddleware`를 쓰므로 `send_with_limit` 교체 동작은 같다.

**(B) 순수 ASGI 커스텀 미들웨어 + 초과 시 `HTTPException` 하위 예외**

```python
# 동작 확인용 스케치 (최종 설계 아님)
class PayloadTooLarge(starlette.exceptions.HTTPException):  # ← HTTPException 계열이어야 함
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="요청 크기가 제한을 초과했습니다.")

class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None: ...
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cl = Headers(scope=scope).get("content-length")
        if cl is not None and cl.isdigit() and int(cl) > self.max_bytes:
            # 본문을 읽기 전에 즉시 §7.2 형식 413 응답
            return await error_response("PAYLOAD_TOO_LARGE", 413, ...)(scope, receive, send)
        total = 0
        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise PayloadTooLarge()
            return message
        await self.app(scope, limited_receive, send)
```
| 요청 | 결과 |
|---|---|
| `Content-Length` 초과 | `413 {"code":"PAYLOAD_TOO_LARGE",...}` + `X-Request-Id` + CORS ✅ |
| chunked JSON 초과 | 동일 ✅ (`ExceptionMiddleware` → 핸들러) |
| chunked multipart 초과 | 동일 ✅ |
| 실제 Uvicorn(httptools)에서 10KB / 5MB / 50MB multipart, 10MB chunked | httpx 클라이언트가 모두 413 JSON을 정상 수신 ✅ |

**(C) (B)와 같으나 초과 예외가 `HTTPException`이 아닌 커스텀 예외(`AppError`)**

| 요청 | 결과 |
|---|---|
| `Content-Length` 초과 | 413 ✅ (사전 검사 경로는 예외를 쓰지 않으므로) |
| chunked 초과 (JSON·multipart) | **`400 "There was an error parsing the body"`** ❌ |

원인 — `fastapi/routing.py` 본문 읽기 부분:
```python
except HTTPException:
    raise                       # HTTPException 계열만 그대로 통과
except Exception as e:
    if MAX_BODY_SIZE_SCOPE_KEY in request.scope and (error := get_body_limit_error(e)):
        raise error from e      # 내장 limiter 예외만 예외 처리
    raise HTTPException(status_code=400, detail="There was an error parsing the body") from e
```
→ 커스텀 미들웨어에서 `receive` 중에 던지는 예외는 **`HTTPException` 하위 클래스**여야 한다. 도메인 예외 계층(`AppError`)과 통일하고 싶다면 다중 상속(`class PayloadTooLarge(AppError, HTTPException)`) 또는 핸들러에서 `isinstance` 분기로 처리할 수 있다 (다중 상속은 실측하지 않음).

**기타 사실**
- `Content-Length` 사전 거절 시 서버는 본문을 다 받지 않고 응답한다. Uvicorn은 이후 연결을 닫는다. httpx는 정상 수신했지만, **UiPath HTTP Request 액티비티가 본문 전송 중 연결 종료를 어떻게 처리하는지는 미확인** (클라이언트에 따라 "connection reset"으로 보일 수 있음).
- 한도 계산 단위: `MAX_UPLOAD_MB * 1024 * 1024`(MiB) vs `* 1_000_000`(MB)은 문서에 정의 없음.
- 한도는 **요청 전체 바이트**(multipart 경계·헤더 포함) 기준이다. 파일 하나의 크기가 아니다. W-07 다중 파일 업로드에서는 "파일 합계 + 오버헤드 ≤ 한도"가 된다.
- multipart 파서 자체 제한(Starlette `request.form()` 기본): `max_files=1000`, `max_fields=1000`, 텍스트 필드 `max_part_size=1MB`, 파일은 1MB 초과 시 임시 파일로 스풀(`SpooledTemporaryFile`). FastAPI 0.165는 `form_limits`로 조정 가능. 크기 제한과는 별개.
- GET 등 본문을 읽지 않는 경로는 누적 카운트가 동작하지 않는다(읽지 않으니 문제도 없음). `Content-Length` 사전 검사는 메서드·경로와 무관하게 동작한다.
- 미들웨어 위치는 요청 ID 미들웨어 **안쪽**이어야 413에도 `X-Request-Id`가 붙는다.

### 3.4 structlog 26.1 — JSON 로그, contextvars, 표준 logging 통합

**구성 (실측 동작 확인)**
```python
shared = [
    structlog.contextvars.merge_contextvars,      # request_id 등 컨텍스트 병합
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.ExtraAdder(),
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]
structlog.configure(
    processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
formatter = structlog.stdlib.ProcessorFormatter(
    foreign_pre_chain=shared,                     # 표준 logging(uvicorn 등) 레코드에도 같은 처리
    processors=[
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        structlog.processors.dict_tracebacks,     # 예외를 JSON 구조로
        structlog.processors.JSONRenderer(),
    ],
)
handler = logging.StreamHandler(sys.stdout); handler.setFormatter(formatter)
logging.getLogger().handlers = [handler]
for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    lg = logging.getLogger(name); lg.handlers.clear(); lg.propagate = True
```
실측 출력 예:
```json
{"event": "in sync endpoint", "request_id": "rid-1", "path": "/sync", "call_id": 42, "level": "info", "logger": "app", "timestamp": "...Z"}
{"event": "127.0.0.1:1 - \"GET /sync HTTP/1.1\" 200", "request_id": "rid-1", ..., "logger": "uvicorn.access"}
```

**확인된 사실·함정**
| 항목 | 내용 |
|---|---|
| Uvicorn 로그 설정 | Uvicorn은 기동 시 `LOGGING_CONFIG`(dictConfig)로 `uvicorn`(propagate False), `uvicorn.access`(propagate False) 핸들러를 직접 붙인다. 앱 쪽에서 핸들러를 비우고 propagate를 켜야 JSON으로 통일됨. 설정 시점이 Uvicorn의 dictConfig **이후**여야 함(앱 import/`create_app()` 시점은 이후임). `--reload`·`--workers`에서는 워커 프로세스마다 앱을 import하므로 각자 설정됨 |
| Uvicorn 접근 로그 | `httptools_impl.py`/`h11_impl.py`에서 `http.response.start`를 보낼 때 기록 → 앱 task 안이므로 contextvars의 `request_id`가 포함됨. 다만 메시지가 문자열이라 `status`·`latency_ms` 필드가 구조화되지 않음 → §12 필드를 맞추려면 앱 미들웨어에서 별도 접근 로그를 남기고 Uvicorn 접근 로그는 끄는(`--no-access-log` 또는 레벨 조정) 선택지가 있음 |
| contextvars 누수 | Uvicorn 0.54 소스 주석: asyncio가 task 간 contextvars를 누수할 수 있음(cpython#140947), `reset_contextvars` 옵션은 기본 False → 요청 시작 시 `clear_contextvars()` 권장 |
| 동기 엔드포인트 | `def` 엔드포인트는 스레드풀에서 **복사된 컨텍스트**로 실행 → 엔드포인트 안 `bind_contextvars(call_id=...)`는 그 안의 로그에는 붙지만 **미들웨어의 요청 종료 로그에는 안 보임** (실측). async 엔드포인트는 보임. 프로젝트 기본이 동기 엔드포인트이므로, 접근 로그에 `call_id`를 넣으려면 `request.state`(=`scope["state"]`) 같은 공유 가변 객체를 쓰는 방식이 필요 (실측: `scope["state"]`에 쓴 값은 미들웨어에서 보임) |
| 요청 후 정리 | 요청 처리 후 컨텍스트는 남지 않음 (실측: 요청 후 `get_contextvars()` = `{}`) |
| 한글 출력 | `JSONRenderer(ensure_ascii=False)` 사용 시 Windows 콘솔(cp949)에서 한글이 깨짐(실측). Docker(Linux, UTF-8)에선 문제없음. 기본값 `ensure_ascii=True`면 `\uXXXX`로 안전 |
| 예외 로그 | `dict_tracebacks`는 프레임 목록을 JSON으로 출력 → 길다. `format_exc_info`(문자열)도 선택지 |
| 미처리 예외 로그 | 미처리 예외를 사용자 미들웨어에서 잡아 응답하고 재발생하지 않으면 `ServerErrorMiddleware`·Uvicorn이 로그를 남기지 않으므로 **직접 `log.exception(...)`** 해야 함 |
| httpx 로그 | 테스트·Drive 클라이언트의 `httpx` INFO 로그도 루트로 들어옴 (실측) → 레벨 조정 대상 |

### 3.5 X-Request-Id

| 항목 | 확인 내용 |
|---|---|
| 응답 헤더 추가 | 순수 ASGI에서 `http.response.start` 메시지에 `MutableHeaders(scope=message).append("X-Request-Id", rid)` (실측 동작) |
| 클라이언트 값 재사용 | 요청 헤더 값을 그대로 쓰면 로그 인젝션·과도한 길이 위험 → 형식 검증(길이·문자 집합) 후 재사용 또는 항상 서버 생성. 문서는 "로봇이 응답의 `X-Request-Id`를 기록"만 정의 → **재사용 여부 미정** |
| 생성 형식 | `uuid.uuid4().hex`(32자) 또는 `str(uuid.uuid4())`(36자) 등. 문서에 정의 없음 |
| 커버리지 (설계 B 구성에서 실측) | 200, 404, 405, 413(CL·chunked), 422, 커스텀 도메인 예외 → 헤더 있음. **CORS preflight(OPTIONS)** → CORS가 바깥이면 헤더 없음. **미처리 500** → 별도 처리 없으면 헤더 없음 |
| 미처리 500에 헤더 붙이기 | 요청 ID 미들웨어(또는 그 안쪽 미들웨어)에서 `except Exception` → 응답 미시작이면 §7.2 형식 500 응답을 직접 전송 + 로그. 실측 시 `X-Request-Id`·CORS 헤더 모두 붙음(이 미들웨어가 CORS 안쪽일 때) |
| 다른 방법 | `request.state.request_id`로 핸들러에서 읽어 헤더를 직접 넣는 방식도 가능하나, 500 핸들러는 `ServerErrorMiddleware`에서 돌므로 CORS 헤더는 여전히 빠짐 |

**배치 순서 트레이드오프 (바깥 → 안)**
| 배치 | preflight에 `X-Request-Id` | 500 응답에 CORS 헤더 |
|---|---|---|
| CORS → 요청 ID(+500 처리) → 크기 제한 | ✗ | ✓ |
| 요청 ID(+500 처리) → CORS → 크기 제한 | ✓ | ✗ (500 응답이 CORS 바깥에서 생성) |
| 요청 ID → CORS → 500 처리 전용 미들웨어 → 크기 제한 | ✓ | ✓ (미들웨어 1개 추가) |

### 3.6 예외 핸들러 매핑

| 예외 | 기본 동작(FastAPI 0.165) | §7.2에 맞추려면 |
|---|---|---|
| `RequestValidationError` | 422 `{"detail": errors()}` | 422 `VALIDATION_ERROR`, `detail`에 오류 목록. `errors()`에는 `input`(요청 값 원문)·`ctx`·`url`이 포함됨 → 요청 본문 일부가 응답에 되돌아감. 필드 정제 여부 결정 필요 |
| JSON 문법 오류 | FastAPI가 `RequestValidationError(type="json_invalid")`로 변환 | 위와 동일 경로 |
| Starlette/FastAPI `HTTPException` | `{"detail": ...}` | 상태 코드 → 코드 매핑 필요. 404→`NOT_FOUND`, 401→`UNAUTHORIZED`, 403→?, 405·400 등은 §7.2에 코드 없음 |
| 본문 파싱 실패(멀티파트 깨짐 등) | `HTTPException(400, "There was an error parsing the body")` | §7.2에 400 코드 없음 |
| 커스텀 도메인 예외 | — | `exception_handlers`에 기반 클래스 등록 → MRO로 하위 클래스 모두 처리 (`starlette/_exception_handler.py` `_lookup_exception_handler`) |
| `pydantic.ValidationError` (서비스에서 수동 검증 시) | 처리 안 됨 → **500** | R-07이 GenAI JSON을 요청 스키마가 아닌 서비스에서 검증한다면 매핑 필요 |
| 미처리 `Exception` | `ServerErrorMiddleware` → 500 plain text, 헤더 없음 | §3.5 참고. `code` 값(`INTERNAL_ERROR` 등)이 §7.2에 없음 |
| `fastapi.security.APIKeyHeader(auto_error=True)` 키 누락 | `HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "APIKey"})` | R-01이 이 클래스를 쓰면 401→`UNAUTHORIZED` 매핑으로 흡수됨 |

- 핸들러는 `async def`/`def` 모두 가능(`def`는 스레드풀 실행).
- `HTTPException(headers=...)`의 헤더는 응답에 유지해야 함 (기본 핸들러는 유지함).
- 응답 시작 후 예외: `ExceptionMiddleware`는 `RuntimeError("Caught handled exception, but response already started.")`, 스트리밍 중 예외는 형식 응답 불가 → 로그만 가능.
- 상태 코드 204/304는 본문 금지(`is_body_allowed_for_status_code`).

### 3.7 CORSMiddleware (Starlette 1.10)

| 항목 | 내용 |
|---|---|
| 기본값 | `allow_methods=("GET",)`, `allow_headers=()`, `allow_credentials=False`, `expose_headers=()`, `max_age=600` |
| `expose_headers` | 단순 응답에 `Access-Control-Expose-Headers` 추가. **`X-Request-Id`를 넣지 않으면 브라우저 JS에서 읽을 수 없음** (실측: `expose_headers=["X-Request-Id"]` 설정 시 헤더 노출됨) |
| 메서드 | 프론트가 `PATCH`·`DELETE`·`POST`를 쓰므로 `allow_methods` 지정 필요 (`"*"`면 `DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT, QUERY`) |
| 헤더 | `Content-Type: application/json`은 safelisted 값이 아니므로 preflight 발생 → `allow_headers`에 필요 헤더 지정 또는 `"*"`. 프론트가 `X-Request-Id`를 보낼 계획이면 허용 필요 |
| credentials | 로그인·쿠키 없음 → `False`로 충분. `True` + `allow_origins=["*"]` 조합은 Starlette가 Origin을 반사하는 방식으로 처리하지만 불필요 |
| preflight | CORS 미들웨어가 직접 200 `OK`(text/plain) 응답 → 안쪽 미들웨어·라우터를 거치지 않음 |
| 비허용 Origin | preflight는 400, 단순 요청은 CORS 헤더 없이 응답(브라우저가 차단) |
| 로봇 | UiPath HTTP 요청은 브라우저가 아니므로 CORS 영향 없음 |

### 3.8 pydantic-settings 2.16 — `Settings`

**리스트 환경 변수 파싱 (실측)**
| `CORS_ORIGINS` 값 | `list[str]` (기본) | `Annotated[list[str], NoDecode]` + 콤마 split validator |
|---|---|---|
| `http://a,http://b` | **SettingsError (기동 실패)** | `['http://a','http://b']` |
| `["http://a","http://b"]` | `['http://a','http://b']` | `['["http://a"', '"http://b"]']` (깨짐) |
| `http://a` (현재 `.env.example`) | **SettingsError** | `['http://a']` |
| `` (빈 값) | **SettingsError** | `[]` |

원인: `pydantic_settings/sources/base.py` `decode_complex_value` → 복합 타입은 `json.loads(value)`. `NoDecode` 메타데이터가 있거나 `enable_decoding=False`면 원문 문자열을 validator로 넘긴다.
```python
from typing import Annotated
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
```
같은 패턴이 `ROBOT_API_KEYS`(문서상 "쉼표 구분"), `ALLOWED_EXTENSIONS`(`wav,mp3`), `ROBOT_ALLOWED_IPS`에 적용된다.

**기타 사실**
| 항목 | 내용 |
|---|---|
| 기본 설정 | `extra='forbid'`, `case_sensitive=False`, `env_file=None`, `validate_default=True`, `env_file_depth=0` |
| `extra='forbid'` | `.env`에 선언되지 않은 키가 있으면 `ValidationError: Extra inputs are not permitted` (실측). OS 환경 변수의 미선언 키는 무시됨(실측) → **`.env`를 쓰는 로컬에서만 실패**하는 비대칭 |
| `env_file` 경로 | 상대 경로는 **현재 작업 디렉터리 기준**. README는 `backend/`에서 실행, 컨테이너는 `/app`(=backend 바인드 마운트) → 둘 다 `.env` 발견. 레포 루트에서 실행하면 못 찾음 (`env_file_depth`로 상위 탐색 가능) |
| 우선순위 | 생성자 인자 > OS 환경 변수 > `.env` > 기본값. dev compose의 `environment:` 값이 `.env`보다 우선 |
| 타입 오류 | `MAX_UPLOAD_MB=abc` → 기동 시 `ValidationError` (실측) → 잘못된 설정은 기동 단계에서 실패 |
| Windows | `os.environ`이 대소문자 무시 → `case_sensitive=True`여도 자동으로 무시 처리(소스 주석) |
| `.env`는 `os.environ`에 반영 안 됨 | pydantic-settings는 `.env`를 읽어 필드만 채운다. **`GOOGLE_APPLICATION_CREDENTIALS`처럼 라이브러리(google-auth)가 `os.environ`을 직접 읽는 값은 `.env`에만 있으면 라이브러리가 못 본다** → 경로를 Settings에서 읽어 명시적으로 넘기는 방식 필요 (W-08 관련) |
| Docker secret | `secrets_dir`(예: `/run/secrets`) 지원 → 서비스 계정 키·API Key 주입에 사용 가능 |
| 캐싱 | 관례적으로 `@lru_cache def get_settings() -> Settings`. 테스트는 `get_settings.cache_clear()` 또는 `Settings(_env_file=None, ...)`로 직접 생성해 주입 |
| 시크릿 노출 | `ROBOT_API_KEYS`·`DATABASE_URL`(비밀번호 포함)을 로그·`repr`에 노출하지 않으려면 `SecretStr` 고려 (mypy strict에서 `.get_secret_value()` 필요) |

**`create_app()`과 설정 주입**
- CORS origin·크기 한도는 **미들웨어 등록 시점**(앱 생성 시)에 필요 → FastAPI `Depends`로는 주입 불가. `create_app(settings: Settings | None = None)`처럼 앱 생성 인자로 받거나 `get_settings()`를 호출하는 형태가 된다.
- 현재 스모크 테스트는 `create_app()`을 인자 없이 호출 → 필수 필드(기본값 없는 `DATABASE_URL` 등)를 두면 `.env`가 없는 CI/깨끗한 환경에서 **스모크 테스트가 깨진다**.
- 모듈 수준 `app = create_app()`이 import 시 Settings를 읽으므로, 테스트에서 `from app.main import app`만 해도 `.env`가 로드된다 (개발자 `.env`가 테스트에 섞일 수 있음).

### 3.9 테스트 도구 관련
- Starlette 1.10 `TestClient`는 httpx 사용 시 `StarletteDeprecationWarning`("install `httpx2`")을 출력한다(실측). `pytest`는 경고로만 표시(현재 `filterwarnings` 설정 없음). 경고를 오류로 바꾸는 설정을 추가하면 기존 스모크 테스트가 실패한다.
- `TestClient(app, raise_server_exceptions=False)`가 아니면 미처리 예외가 테스트로 재발생 → 500 응답 형식 테스트 시 필요. 단 미처리 예외를 미들웨어가 삼키는 구조면 기본값으로도 500 응답을 받는다.
- httpx에 제너레이터를 `content=`로 주면 `Transfer-Encoding: chunked`로 전송 → chunked 크기 초과 테스트 가능(실측).

---

## 4. 설계 시 고려사항 · 함정 (정리)

1. **내장 `max_body_size`만으로는 §7.2 형식·`X-Request-Id`·CORS를 만족할 수 없다** (`Content-Length` 초과 시 plain text 고정). 순수 ASGI 커스텀 미들웨어가 필요하고, 내장 기능과 **함께 쓰면** 내장 `send_with_limit`가 커스텀 413을 다시 plain text로 바꾼다 (내장 limiter가 바깥이므로). 둘 중 하나만 쓰는 것이 안전하다.
2. 커스텀 미들웨어의 수신 중 초과 예외는 **`HTTPException` 하위 클래스**여야 한다 (아니면 400으로 변환).
3. 크기 제한 미들웨어는 요청 ID 미들웨어 **안쪽**, CORS 미들웨어 **안쪽**에 둬야 413에 두 헤더가 붙는다.
4. 미처리 예외 500에는 기본적으로 `X-Request-Id`·CORS 헤더가 없다 → 미들웨어 단에서 잡아 응답하고 **직접 로그**를 남겨야 한다 (재발생하지 않으면 다른 곳에서 로그가 안 남음).
5. `BaseHTTPMiddleware`는 쓰지 않는 편이 낫다 (본문 카운트 불가, Range/스트리밍 오버헤드, contextvars 단방향).
6. 동기 엔드포인트에서 `bind_contextvars(call_id=...)`한 값은 미들웨어 접근 로그에 안 보인다 → 접근 로그에 `call_id`를 넣으려면 `request.state` 등 공유 객체 경유가 필요.
7. 요청 시작 시 `clear_contextvars()`로 이전 요청 값 누수를 막는다.
8. Uvicorn 로거의 핸들러·propagate를 재설정해야 로그가 JSON으로 통일된다. Uvicorn 접근 로그를 유지하면 앱 접근 로그와 **중복**된다.
9. 리스트 환경 변수는 `NoDecode` + 콤마 split이 필요하다 (현재 `.env.example` 형식 유지 시). JSON 형식과 동시에 지원하려면 validator에서 `[`로 시작하는지 분기.
10. `extra='forbid'` 기본값 때문에 `.env.example`의 모든 키를 선언하거나 `extra='ignore'`로 바꿔야 한다. 각 기능(R-03, W-08 등)이 나중에 설정을 추가할 때 충돌 지점이 된다.
11. `GOOGLE_APPLICATION_CREDENTIALS` 등 라이브러리가 OS 환경 변수를 직접 읽는 값은 `.env`만으로 전달되지 않는다.
12. `RequestValidationError.errors()`의 `input` 필드는 요청 값을 되돌려준다 → GenAI 결과(마스킹 텍스트)나 큰 값이 에러 응답·로그에 그대로 실릴 수 있다.
13. 로그에 요청 본문, `X-API-Key` 값, 쿼리 `q`(키워드 검색어에 이름 등이 들어갈 수 있음)를 남기지 않도록 필드를 제한하는 것이 PII 원칙과 일관된다.
14. `Content-Length` 사전 거절 시 서버가 연결을 끊는다 → UiPath 클라이언트가 413 본문을 받는지 확인 필요(RPA 파트와 테스트). 받지 못하면 로봇은 네트워크 오류로 보고 **2회 재시도**할 수 있다(`research.md` §3.4 [가정]).
15. 운영 `/docs` 비활성(`architecture.md` §7.1)은 `FastAPI(docs_url=None, redoc_url=None, openapi_url=...)`로 앱 생성 시 결정되므로 이를 제어할 설정 값이 필요하다(현재 없음).
16. mypy strict: structlog 로거 타입(`structlog.stdlib.BoundLogger`), ASGI 타입(`starlette.types.ASGIApp/Scope/Receive/Send/Message`), validator 반환형 `object`/`Any` 처리 필요.

---

## 5. 로봇 연동 기능(A 영역)과의 인터페이스

A 영역 코드는 여기서 설계하지 않는다. 공통 모듈이 제공해야 할 **접점**만 정리한다.

| 사용하는 기능 | 공통 모듈에 기대하는 것 | 비고 |
|---|---|---|
| R-01 로봇 인증 | `UNAUTHORIZED`(401), `FORBIDDEN_IP`(403)를 던질 수 있는 공통 예외 (또는 `HTTPException` 상태 코드 매핑), `Settings.robot_api_keys: list[str]`, `Settings.robot_allowed_ips: list[str]` | 인증을 **미들웨어**(`features.md` R-01 "미들웨어")로 할지 **의존성**(`architecture.md` §3.1 Router "인증 의존성")으로 할지 문서가 엇갈림. 미들웨어라면 예외 핸들러를 거치지 않으므로(사용자 미들웨어는 `ExceptionMiddleware` 바깥) **공통 에러 응답 생성 함수**를 직접 호출할 수 있어야 함. 의존성이라면 예외만 던지면 됨 |
| R-01 IP 확인 | 클라이언트 IP는 `scope["client"]`. Uvicorn `proxy_headers` 기본 True·`forwarded_allow_ips` 기본 `127.0.0.1,::1` → 프록시 없으면 실제 접속 IP | 로봇 IP 형식(단일 IP / CIDR) 미정 |
| R-02 상태 머신 | `INVALID_STATE_TRANSITION`(409) 예외 | 서비스 계층이 던짐 → HTTP 비의존 예외여야 함(§3.1) |
| R-04 등록 | `DUPLICATE_FILE`(409, `detail={"existing_id", "status"}`), `UNSUPPORTED_MEDIA`(415), 크기 제한은 미들웨어가 처리 | `detail`은 임의 dict를 담을 수 있어야 함 |
| R-04~R-10 조회 | `NOT_FOUND`(404) | |
| R-06·R-07 적재 | `VALIDATION_ERROR`(422). 요청 스키마 검증이면 `RequestValidationError` 경로, 서비스 수동 검증이면 `pydantic.ValidationError` 또는 공통 예외 경로 | 둘 다 같은 형식이 되도록 |
| R-04~R-08 로그 | `request_id`가 자동으로 붙는 로거, `call_id` 바인딩 방법 | 동기 엔드포인트 특성(§3.4) 고려 |
| R-10 음성 다운로드 | 미들웨어가 스트리밍 응답을 버퍼링하지 않을 것 | 순수 ASGI면 충족 |
| R-12 시뮬레이션 테스트 | 테스트에서 설정을 주입할 수 있는 `create_app` 형태, 에러 응답 `code`로 단언 가능 | C-05 테스트 기반과 연계 |
| 로봇(UiPath) | 모든 응답(에러 포함)의 `X-Request-Id`, 일관된 `code` | 로봇은 `code`·HTTP 상태로 분기(409 `DUPLICATE_FILE` + `detail.status`) |

`features.md` §5가 요구하는 "에러 코드·로그 형식 1주차 확정" 항목:
- 에러 코드 전체 목록(§6의 추가 코드 포함)과 예외 클래스 이름·생성 인자
- 로그 필드 이름(`request_id`, `call_id`, `path`, `status`, `latency_ms` + 추가 필드)과 로거 획득 방법
- `X-Request-Id` 생성·재사용 규칙

---

## 6. 문서 간 모순 · 미정 사항 · 결정 필요 질문

### 6.1 문서 간 모순·불일치
| # | 내용 | 출처 |
|---|---|---|
| 1 | `MAX_UPLOAD_MB`는 "**업로드** 최대 크기"(§10.3)인데 C-02는 "**모든 API 공통 요청 크기** 제한". JSON API에도 100MB를 허용할지, 업로드 경로만 크게 둘지 | `architecture.md` §10.3 vs `features.md` C-02 |
| 2 | R-01 인증 방식: "미들웨어" vs Router 계층 "인증 의존성" | `features.md` R-01 vs `architecture.md` §3.1 |
| 3 | `core/`는 B 주 수정 위치로 적혀 있으나 `core/security.py`는 R-01(A) 용도 | `features.md` 한눈에 보기 vs `architecture.md` §3.2 |
| 4 | 정체 기준 상태 목록: `research.md` §3.3은 `QUEUED`·`STT_DONE`만, `architecture.md` §12는 `RETRY_REQUESTED`까지 (공통 모듈과는 `STALE_THRESHOLD_MIN` 설정만 관련) | — |
| 5 | §7.2 에러 코드표에 **500·400·405·403(IP 외)** 등 일반 상황 코드가 없음. 그러나 "모든 응답에 X-Request-Id"는 이 경우도 포함 | `architecture.md` §7.2 |

### 6.2 결정이 필요한 질문
1. **요청 크기 한도 범위**: 모든 경로에 `MAX_UPLOAD_MB` 하나를 적용하나, 아니면 업로드 경로(`/api/uploads`, `POST /api/robot/calls`)와 나머지(JSON)를 다르게 두나? (C-02 문구는 "모든 API 공통")
2. **MB 단위**: `MAX_UPLOAD_MB * 1024 * 1024`(MiB)인가 `* 1_000_000`인가?
3. **한도 기준**: 요청 전체 바이트(멀티파트 오버헤드 포함)인가, 파일당 크기인가? W-07 다중 파일 업로드에서 "파일 합계 100MB"가 의도인지
4. **구현 방식**: FastAPI 내장 `max_body_size` 사용(§7.2 형식 포기, plain text 413) vs 커스텀 순수 ASGI 미들웨어(§7.2 형식 유지)
5. **추가 에러 코드**: 500(`INTERNAL_ERROR`?), 400 본문 파싱 실패(`BAD_REQUEST`?), 405(`METHOD_NOT_ALLOWED`?), 라우팅 404(`NOT_FOUND` 재사용?) 등의 코드명. C-03 API 규약과 함께 확정 필요
6. **`message` 언어·문구**: 한국어 고정 메시지 테이블을 둘지, 예외마다 메시지를 받을지
7. **`VALIDATION_ERROR`의 `detail` 형식**: FastAPI `errors()` 원본을 그대로 줄지, `loc`·`msg`·`type`만 남길지 (`input` 제거 여부 — PII·크기)
8. **X-Request-Id 재사용**: 클라이언트가 보낸 값을 (검증 후) 재사용할지, 항상 서버가 생성할지. 재사용 시 허용 형식·최대 길이
9. **X-Request-Id 형식**: UUID4 hex(32자) vs 하이픈 포함(36자) 등
10. **preflight(OPTIONS) 응답에도 `X-Request-Id`가 필요한가**: 필요하면 미들웨어 순서·구성이 바뀜(§3.5 표)
11. **CORS 상세**: `CORS_ORIGINS` 형식(콤마 vs JSON), `allow_methods`·`allow_headers` 범위, `expose_headers`에 `X-Request-Id`(+ 엑셀 다운로드 파일명용 `Content-Disposition`) 포함 여부, `allow_credentials=False` 확정 여부
12. **리스트 환경 변수 형식 통일**: `ROBOT_API_KEYS`(문서상 쉼표), `ALLOWED_EXTENSIONS`, `ROBOT_ALLOWED_IPS`, `CORS_ORIGINS`를 모두 콤마 구분으로 할지. `ROBOT_ALLOWED_IPS`에 CIDR 허용 여부
13. **Settings 범위**: C-02에서 §10.3의 **모든** 변수를 선언할지(각 기능이 필드만 사용), 아니면 공통 모듈 관련 필드만 선언하고 `extra='ignore'`로 둘지
14. **필수 값과 기본값**: `DATABASE_URL` 등을 필수(기본값 없음)로 둘 때 스모크 테스트·CI(`.env` 없음)를 어떻게 통과시킬지
15. **추가 설정 변수**: `LOG_LEVEL`, 로그 형식(JSON/개발용 콘솔), 실행 환경(`APP_ENV` 등 — 운영 `/docs` 비활성용)을 새로 둘지. 두면 `architecture.md` §10.3·`.env.example` 갱신 필요
16. **로그 타임스탬프 시간대**: UTC(서버 저장 규칙과 동일) vs KST(+09:00, API 응답 규칙과 동일)
17. **접근 로그**: 앱 미들웨어 접근 로그(§12 필드 구조화)로 대체하고 Uvicorn 접근 로그를 끌지, 둘 다 둘지. 헬스 체크(`/health`) 요청을 로그에서 제외할지
18. **로그에 남길 필드 범위**: 메서드, 클라이언트 IP, 쿼리 문자열(검색어 `q`의 PII 가능성), User-Agent 포함 여부
19. **미처리 예외 500 응답에 CORS 헤더가 필요한가**: 프론트가 500 응답 본문·`X-Request-Id`를 읽어 사용자에게 보여줄 계획인지
20. **R-01 인증 위치(미들웨어/의존성)**: 공통 모듈이 "미들웨어에서 직접 쓸 수 있는 에러 응답 생성 함수"까지 제공해야 하는지가 여기에 달림
21. **UiPath 클라이언트의 조기 413 처리**: 본문 전송 중 서버가 413을 보내고 연결을 닫을 때 로봇이 응답을 읽는지 (RPA 파트와 확인, E-04 합의 항목에 추가 후보)
22. **테스트 경고 정책**: Starlette `TestClient`의 httpx deprecation 경고를 무시할지, `httpx2` 도입을 검토할지 (C-05 테스트 기반과 연계)

---

## 7. 참고 — 확인에 사용한 소스 위치 (`backend/.venv/Lib/site-packages/`)
| 주제 | 파일 |
|---|---|
| 미들웨어 스택·기본 예외 핸들러 | `fastapi/applications.py` (`build_middleware_stack`, `exception_handlers.setdefault`) |
| 본문 읽기 예외 → 400 변환 | `fastapi/routing.py` (본문 읽기 `try/except`) |
| FastAPI 본문 한도 | `fastapi/_body_limit.py`, `starlette/middleware/body_limit.py`, `starlette/applications.py` |
| 예외 처리 순서 | `starlette/middleware/exceptions.py`, `starlette/_exception_handler.py`, `starlette/middleware/errors.py` |
| BaseHTTPMiddleware | `starlette/middleware/base.py` |
| CORS | `starlette/middleware/cors.py` |
| multipart 제한 | `starlette/formparsers.py`, `starlette/requests.py` |
| 기본 에러 응답 형식 | `fastapi/exception_handlers.py` |
| APIKeyHeader 401 | `fastapi/security/api_key.py` |
| Settings 파싱 | `pydantic_settings/main.py`(기본 설정), `pydantic_settings/sources/base.py`(`decode_complex_value`), `pydantic_settings/sources/types.py`(`NoDecode`) |
| structlog | `structlog/contextvars.py`, `structlog/stdlib.py`(`ProcessorFormatter`), `structlog/processors.py` |
| Uvicorn 로깅·contextvars | `uvicorn/config.py`(`LOGGING_CONFIG`, `reset_contextvars`), `uvicorn/protocols/http/httptools_impl.py`(접근 로그 시점) |
