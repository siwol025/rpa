# 헬스 체크 상세 구현 계획 — `GET /health`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` O-02 헬스 체크 — "`GET /health` — DB, 음성 저장소, Drive `inbox/` 접근 확인" (P1, Phase 2, 선행 R-03·W-08) |
| 작업 기준 | `2bde1c6` (웹 업로드 API·문서 반영 이후) |
| 근거 | `docs/researchs/health-check.md` v0.1(이하 "리서치"), `plans/drive-inbox.md` §9.4(H1~H7), `api/convention.md` v0.1, `architecture.md` §3.2·§7.1·§12, `app/main.py`, `app/api/deps.py`, `app/core/{db,config,middleware,errors,logging}.py`, `app/infra/inbox/*`, `app/infra/storage/*`, `app/schemas/common.py`, `app/api/web/uploads.py`, `tests/conftest.py`, `tests/unit/{conftest,test_openapi,test_logging,test_uploads_api,upload_fakes}.py`, `tests/integration/conftest.py`, `scripts/export_openapi.py`, `pyproject.toml` |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / SQLAlchemy 2.0 / psycopg 3 / structlog (`uv.lock` 설치본) |
| 사전 검증 | 이 문서의 코드·테스트를 `2bde1c6` 레포 전체 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). **기존 710 통과·2 skip → 754 통과·2 skip**(신규 44: 단위 42 + 통합 2, Docker testcontainers로 통합 포함 실행, 수동 Drive 2건 skip). `ruff check`·`ruff format --check`·`mypy .`(109파일) 통과, `openapi.json` 재생성(추가만 106줄) 후 `test_committed_openapi_is_up_to_date` 통과 |

---

## 1. 목표와 범위

### 1.1 목표
1. `GET /health`가 **DB(`SELECT 1`)·음성 저장소(`AudioStorage.check()`)·inbox(`InboxWriter.check()`)**를 확인하고, 구성요소별 상태와 전체 상태를 돌려준다.
2. DB·음성 저장소는 **필수**(하나라도 실패 → 503 `FAIL`), inbox는 **선택**(실패 → 200 `DEGRADED`), inbox가 꺼져 있으면(`INBOX_BACKEND=disabled`) `DISABLED`로 표시하고 판정에서 제외한다.
3. 느릴 수 있는 inbox(Drive) 확인은 **결과를 30초 캐시**하고 동시 호출을 하나로 묶어, 헬스 체크 폭주가 Drive 호출·스레드풀 점유로 번지지 않게 한다.
4. 실패 원인은 **응답에 넣지 않고 로그에만** 남긴다(인증 없는 엔드포인트). 로그에도 분류 값만 남기고 예외 원문·`exc_info`는 남기지 않는다.
5. DB 호스트 무응답 시 무한 대기하지 않도록 엔진에 **연결 타임아웃 5초**를 준다.

### 1.2 포함
- `app/schemas/health.py`(응답 모델), `app/services/health_service.py`(확인·판정·캐시), `app/api/health.py`(라우트 + 이 라우트 전용 의존성)
- `app/main.py`: import 1줄 + `include_router` 1줄
- `app/core/db.py`: `connect_timeout=5` (별도 커밋, A 리뷰 — §9.1 A1)
- `docs/api/openapi.json` 재생성
- 테스트: 단위(가짜 세션·저장소·writer·시계, 실제 `LocalStorage`·`LocalInboxWriter`) + 통합(실제 PostgreSQL, 연결 거부)
- 공용 문서: `convention.md`(§2.2 행, §3.6 신설 — 에러 형식의 예외, §5.3 값 집합, §7-4 태그), `architecture.md`(§3.2, §7.1, §12)

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| Docker `HEALTHCHECK`·compose `healthcheck` | 운영 `Dockerfile`·`docker-compose.yml`은 O-01(A) 소관. 명령 예시만 제공(§9.1 A3) |
| liveness 전용 경로(`/health/live`) | D7: 오케스트레이터가 없어 실익 작음. Phase 3(Cloud Run 등)에서 필요하면 추가 |
| `/health` 접근 로그 제외 | D8: 그대로 남김(`common-module.md` #17 규칙 변경 없음) |
| 음성 저장소 실제 쓰기·여유 공간 확인 | D9: `AudioStorage.check()`(R-03, A 소관)를 그대로 사용 |
| `StorageError`에 `reason` 속성 추가 | `app/infra/storage/*`는 수정하지 않는다. 로그 분류는 원인 예외 클래스 이름으로 대신(§3.3) |
| `app/infra/inbox/*` 수정 | W-08 산출물을 사용만 한다 |
| 캐시 TTL 설정 변수화 | 상수로 시작(리서치 §6.3). 필요해지면 `Settings` 필드로 |
| `.env.example`·`NO_GCE_CHECK` | 운영 `.env` 설정(O-03)으로 안내만(§9.2 O2) |
| `HEAD /health` | D13: GET만. HEAD는 405 |
| 응답에 확인 시각(`checked_at`)·버전 | 요구 없음. 필요해지면 호환 추가 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 비고 |
|---|---|---|
| 전체 판정 규칙 | `app.services.health_service.overall_status(checks) -> HealthStatus` | 순수 함수 |
| 확인 서비스 | `HealthService(session, storage, writer, inbox_cache).check() -> HealthResponse` | |
| inbox 결과 캐시 | `InboxCheckCache(ttl_sec=30.0, clock=time.monotonic).get(check)` / `app.state.inbox_health_cache` | 첫 `/health` 요청 때 만들어짐. 테스트는 미리 넣어 시계 주입 |
| DB 연결 타임아웃 | `app.core.db.CONNECT_TIMEOUT_SEC = 5` | 모든 API 공통 |
| 응답 모델 | `app.schemas.health.{HealthStatus, ComponentStatus, HealthChecks, HealthResponse}` | |

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 항목 | 실제 (`2bde1c6`) | 이 계획의 반영 |
|---|---|---|
| `/health` | 코드·테스트에 없음. 함수 이름 `get_health`·태그 `health`도 미사용 | 신규. operationId `get_health` 고유 |
| 확인 함수 | `AudioStorage.check()`(`StorageError`), `InboxWriter.check()`(`InboxUnavailableError(reason)`), `app.state.inbox_writer`가 `None`이면 disabled | 그대로 사용 |
| `StorageError` | 분류 속성 없음. `LocalStorage.check()`는 mkdir 실패 시 `from exc`(원인 `OSError` 계열), 쓰기 권한 없음은 원인 없음 | 로그 `reason` = `type(exc.__cause__ or exc).__name__` → `PermissionError`·`NotADirectoryError`·`StorageError` 등 |
| Drive `check()` 로그 | 라이브러리·인증·네트워크 오류만 `inbox_check_failed`(warning) 기록, 판정 실패(`not_folder` 등)·로컬 실패는 로그 없음 | 헬스가 모든 inbox 실패를 `health_check_failed`로 기록(Drive 오류는 2줄 — 리서치 §7 "중복 허용") |
| DB 세션 | `deps.get_db`가 `session_factory()` 컨텍스트로 yield, 세션 생성만으로는 연결 안 함 | `DbSession` 의존성 재사용 → 통합 테스트 `api` 픽스처의 `get_db` 오버라이드가 그대로 적용 |
| 엔진 | `create_engine(database_url, pool_pre_ping=True)`, `connect_args` 없음 | `connect_args={"connect_timeout": 5}` |
| `connect_args` vs URL 쿼리 | 실측: SQLAlchemy는 URL 쿼리(`?connect_timeout=10`)를 먼저 넣고 `connect_args`로 덮어쓴다 → **`connect_args`가 이김** | URL로 값을 바꿀 수 없음을 §9.4 L5에 기록 |
| 라우트 등록 | `main.py`에 `include_router` 4줄, 다른 작업도 이 부근을 수정 | 맨 끝에 1줄 추가 + import 1줄. `app.state` 초기화 줄은 추가하지 않음(캐시는 지연 생성) |
| `deps.py` | `get_db`/`DbSession`, `get_audio_storage`, `get_inbox_writer` 존재 | **변경 없음**. 헬스 전용 의존성(`get_health_service`)은 라우터 파일에 둔다 |
| 응답 상태 코드 지정 | 라우트에서 `response: Response`의 `status_code`를 바꾸면 반환 모델 그대로 해당 코드로 나감(실측) | 503을 `HTTPException`/`AppError` 없이 헬스 형식으로 |
| 앱 단위 응답 문서 | 모든 operation에 422·500(`error_responses`)이 자동으로 붙음 | `/health`도 422·500 문서화(리서치 §1 `api-convention.md:92` 감수 결정과 같음) |
| 미들웨어 | `RobotAuthMiddleware`는 `/api/robot` 경로만, `RequestIdMiddleware`는 모든 경로 | `/health`는 인증 없음, `X-Request-Id`·접근 로그 있음 |
| enum 스타일 | 응답 enum은 `StrEnum`(`CallStatus` 등) → OpenAPI `enum` 스키마 | `HealthStatus`·`ComponentStatus`도 `StrEnum` |
| mypy 범위 | `uv run mypy .`는 `tests/`까지 검사(109파일) | 테스트 가짜는 `Any`로 넘김(프로토콜 전체 구현 불필요) |
| 연결 거부 소요 시간 | Windows에서 `127.0.0.1:1` 연결 거부 → `/health` 응답까지 약 5초(실측, `connect_timeout` 이내). 리눅스 컨테이너는 즉시 | 통합 테스트 1건 약 5초(§6.1) |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| D1 | 전체 판정 | DB·음성 저장소 **필수**: 하나라도 실패 → 전체 `FAIL`, **503**. inbox 실패 → 전체 `DEGRADED`, **200**. inbox disabled(`writer is None`) → `DISABLED` 표시, **판정 제외**(H1) |
| D2 | 응답 형식 | 200·503 모두 `{"status": ..., "checks": {"db": ..., "audio_storage": ..., "inbox": ...}}`. 값은 대문자 `OK`/`DEGRADED`/`FAIL`/`DISABLED`. **원인(`reason`)은 응답에 넣지 않고 로그에만**(`exc_info` 없이, H2·H7). `convention.md`에 §3.1 에러 형식(`architecture.md` §7.2)의 **예외**로 명시 |
| D3 | inbox 캐시 | 결과를 **성공·실패 모두 TTL 30초** 캐시, `threading.Lock`으로 갱신을 하나로 직렬화(잠금 중 요청은 기다렸다가 새 결과 사용), 캐시 객체는 **`app.state`**(앱마다 하나), 시계 주입 가능 |
| H3 | 라우트 | `def`(동기). 세 확인 모두 블로킹이라 워커 스레드에서 실행 |
| D4 | DB 연결 타임아웃 | `connect_timeout=5` — 적용 위치는 §3.2 D4 비교 |

### 3.2 리서치 §11 권장안 채택
| # | 항목 | 결정 |
|---|---|---|
| D4 | DB 연결 타임아웃 위치 | **엔진 전체 `connect_args={"connect_timeout": 5}`**(`app/core/db.py`, 별도 커밋). 비교는 아래 표 |
| D5 | 상태 값 표기 | 규약 §5.3 대문자 상수(`StrEnum`) |
| D6 | 원인 노출 | 응답 미노출, 로그만(= D2) |
| D7 | liveness 분리 | `/health` 하나 |
| D8 | 접근 로그 | 그대로 남김(`RequestIdMiddleware` 변경 없음) |
| D9 | 음성 저장소 확인 깊이 | 현재 `check()`(폴더 생성 + 쓰기 권한) 그대로. `architecture.md` §12 문구를 실제 방식에 맞춤 |
| D10 | OpenAPI 포함 | **포함**, `tags=["health"]`, 규약 §7-4에 태그 추가. RPA 사전 점검·운영 도구가 계약으로 참고 가능(§9.3 R1) |
| D11 | 코드 배치 | `api/health.py` + `services/health_service.py` + `schemas/health.py`. Router는 DB에 직접 접근하지 않는다 |
| D12 | 예상 밖 예외 | 선언된 예외(`SQLAlchemyError`, `StorageError`, `InboxUnavailableError`)만 구성요소 `FAIL`로. 나머지는 500(`UnhandledErrorMiddleware`가 스택 로그) — **캐시하지 않음** |
| D13 | 메서드 | `GET`만 |

**D4 비교 — 엔진 전체 vs 헬스 쿼리 수준**

| 안 | 방법 | DB 호스트 무응답(연결 단계) | 다른 API 영향 | 코드 영향 | 평가 |
|---|---|---|---|---|---|
| (a) 엔진 전체 | `create_engine(..., connect_args={"connect_timeout": 5})` | **5초에 실패**(libpq, 2초 미만은 2초로 올림) | 모든 API·로봇 요청도 연결 단계 무한 대기 대신 5초 후 500 → 이로움 | `db.py` 1곳(C-01/C-04, A 공용 코드). alembic은 별도 엔진이라 무관 | **채택**. 별도 커밋으로 분리해 A 리뷰, 거절 시 그 커밋만 빼도 헬스는 동작 |
| (b) 헬스 쿼리 수준 | 헬스 세션에서 `SET LOCAL statement_timeout = '5s'` 후 `SELECT 1` | **막지 못함**(문장 타임아웃은 연결이 성립한 뒤에만 적용. 문제는 연결 단계) | 없음 | 헬스 서비스만 | 기각: `SELECT 1`은 잠금 대기가 없어 쿼리 단계 타임아웃의 이득이 거의 없음 |
| (c) 헬스 전용 엔진 | `create_engine(url, poolclass=NullPool, connect_args=...)`를 헬스용으로 하나 더 | 5초에 실패 | 없음(본 엔진은 여전히 무제한) | `main.py`·`app.state` 추가 필요(충돌 위험), 운영 엔진과 다른 경로를 확인하게 됨 | 기각: 실제 요청이 쓰는 풀·엔진을 확인하지 않음 |
| (d) 운영 설정 | `DATABASE_URL=...?connect_timeout=5` | 5초에 실패 | (a)와 같음 | 코드 없음, `.env`만 | 보조: 운영 `.env`에 의존해 누락되기 쉬움. (a) 채택 후에는 `connect_args`가 URL 값을 덮어씀(§2 실측) |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| 확인 순서 | DB → 음성 저장소 → inbox, **앞이 실패해도 모두 확인** | 응답에 세 구성요소 상태가 모두 있어야 진단에 쓸모 있음 |
| DB 확인 | `session.execute(text("SELECT 1"))`, `SQLAlchemyError`면 `FAIL`. 커밋 없음(세션은 `get_db`가 닫음) | 연결 거부·인증 실패·타임아웃은 `OperationalError`, 풀 대기 초과는 `sqlalchemy.exc.TimeoutError` — 모두 `SQLAlchemyError` 하위 |
| 캐시 대상 | **inbox만**. DB·저장소는 매 요청 확인 | 수 ms라 캐시하면 장애 감지만 늦어짐 |
| 캐시 시각 | 확인이 **끝난 시각**부터 TTL | Drive 확인이 10초 걸려도 다음 확인까지 30초 보장 |
| 캐시 생성 위치 | 라우터의 `_inbox_cache(app.state)`가 **첫 요청 때** 만들어 `app.state.inbox_health_cache`에 저장(모듈 잠금으로 한 번만) | `main.py` 변경을 `include_router` 1줄로 제한(다른 작업과 충돌 최소화). 모듈 전역이 아니라 앱마다라 테스트 간 상태가 섞이지 않음 |
| 헬스 전용 의존성 위치 | `get_health_service`를 `app/api/health.py`에 둠 | `deps.py` 무변경(다른 작업과 충돌 회피). 이 라우터만 씀. `deps.py`의 공용 의존성(`DbSession`, `get_audio_storage`, `get_inbox_writer`)은 import해 재사용 |
| 503 반환 방법 | 라우트가 `response.status_code = 503` 후 같은 모델 반환 | `AppError`/`HTTPException`은 §3.1 에러 형식으로 바뀜. 헬스 503은 에러 응답이 아님 → `ErrorCode` 추가 없음 |
| OpenAPI 503 | `responses={503: {"model": HealthResponse, "description": ...}}` | 503 본문도 헬스 형식임을 계약에 드러냄 |
| 응답 헤더 | `Cache-Control: no-store` | 리서치 §5.1. 모니터 도구·브라우저 캐시 방지 |
| 로그 | 로거 `app.health`, 이벤트 `health_check_failed`(warning), 필드 `component`(`db`/`audio_storage`/`inbox`)·`reason`. 성공은 로그 없음 | `request_id`는 자동 바인딩 → 운영자는 응답 `X-Request-Id`로 원인 로그를 찾음 |
| `reason` 값 | DB: 예외 클래스 이름(`OperationalError`·`TimeoutError`), 저장소: `type(exc.__cause__ or exc).__name__`, inbox: `exc.reason`(`http_404`·`DefaultCredentialsError`·`not_folder`·`PermissionError` 등) | `str(exc)` 금지: DB 메시지에 호스트·DB 이름·SQL이 있음. `exc_info` 금지(H7) |
| inbox 캐시 히트 | 로그 없음 | 같은 실패가 요청마다 반복 기록되지 않게(실제 확인했을 때만 1줄) |
| 테스트 시계 | `InboxCheckCache(clock=...)`로 주입, 앱 단위는 `app.state.inbox_health_cache`를 미리 넣음 | `time.monotonic` 기본 |
| 테스트 가짜 | `tests/unit/health_fakes.py`(`FakeSession`, `FakeStorage`, `storage_error()`, `FakeInbox`, `FakeClock`, `SECRET`). `test_*.py`가 아니라 수집되지 않음 | 서비스·라우터 테스트 공용. 기존 `upload_fakes.FakeWriter`는 `check()`가 항상 성공이라 확장 대신 새로 만듦(웹 업로드 테스트 무변경) |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준) | 내용 |
|---|---|---|
| 수정 | `app/core/db.py` | `CONNECT_TIMEOUT_SEC = 5`, `connect_args` (커밋 2) |
| 신규 | `tests/unit/test_db.py` | 연결 인자 1건 (커밋 2) |
| 신규 | `app/schemas/health.py` | `HealthStatus`, `ComponentStatus`, `HealthChecks`, `HealthResponse` |
| 신규 | `app/services/health_service.py` | `INBOX_CHECK_TTL_SEC`, `InboxCheckCache`, `overall_status`, `HealthService` |
| 신규 | `app/api/health.py` | `router`, `_inbox_cache`, `get_health_service`, `get_health` |
| 수정 | `app/main.py` | `from app.api import health`, `app.include_router(health.router)` — **2줄** |
| 재생성 | `docs/api/openapi.json` | `/health`, `HealthResponse`·`HealthChecks`·`HealthStatus`·`ComponentStatus` (추가만 106줄) |
| 신규 | `tests/unit/health_fakes.py` | 테스트 공용 가짜 |
| 신규 | `tests/unit/test_health_service.py` | 25건 |
| 신규 | `tests/unit/test_health_api.py` | 16건 |
| 신규 | `tests/integration/test_health_api.py` | 2건 |
| 수정 | `docs/api/convention.md` | §2.2 행, §3.6 신설, §5.3 값 집합 2행, §7-4 태그 |
| 수정 | `docs/architecture/architecture.md` | §3.2 구조도 3줄, §7.1 `/health` 비고, §12 헬스 체크 행 |

- **변경하지 않는 파일**: `app/api/deps.py`, `app/core/{config,errors,middleware,logging}.py`, `app/infra/**`, `app/schemas/common.py`, `tests/unit/conftest.py`, `tests/conftest.py`, `tests/integration/conftest.py`, `tests/unit/upload_fakes.py`, `pyproject.toml`·`uv.lock`(새 의존성 없음), `.env.example`, `docs/features/features.md`, `docs/plans/common-module.md`.

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_openapi.py` | `test_committed_openapi_is_up_to_date`가 재생성 전까지 실패(의도). `test_every_operation_documents_422_and_500_in_error_format`·`test_operation_ids_are_unique_in_real_app`은 그대로 통과(실측) |
| 통합 테스트 전체 | `connect_timeout`은 정상 연결에 영향 없음(기존 통합 포함 710건 통과 유지, 실측) |
| `tests/unit/test_app_smoke.py` | 변경 없음 |

### 4.2 다른 작업과의 충돌 대응
같은 시기에 다른 작업이 `app/api/deps.py`, `app/main.py`, `docs/api/openapi.json`, `docs/api/convention.md`를 수정한다.

| 파일 | 이 계획의 변경 | 충돌 시 |
|---|---|---|
| `app/api/deps.py` | 없음 | — |
| `app/main.py` | import 1줄(`from app.api import health`, `app.api.robot` import 바로 위 — isort 순서) + `include_router` 1줄(마지막 `include_router` 뒤) | 양쪽 줄을 모두 남긴다. `app.state` 초기화 줄은 추가하지 않으므로 그 부근은 충돌하지 않음 |
| `docs/api/openapi.json` | 재생성 | **손으로 합치지 않는다.** 코드 병합 후 `cd backend && uv run python -m scripts.export_openapi`로 다시 생성해 커밋(`test_committed_openapi_is_up_to_date`로 확인) |
| `docs/api/convention.md` | §2.2 표 1행, §3 끝에 §3.6, §5.3 표 2행, §7-4 한 줄 | 다른 작업도 §3 끝에 절을 추가하면 번호가 겹칠 수 있음 → 병합 순서대로 번호를 다시 매긴다(본문은 독립) |

---

## 5. 모듈별 코드

### 5.1 `app/core/db.py` (수정, 커밋 2)
```python
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
```
- 정상 연결에는 영향 없음. 연결 단계 무응답만 5초로 끊는다(`OperationalError`).
- `connect_args`가 URL 쿼리의 `connect_timeout`을 덮어쓴다(§2 실측). 값 변경이 필요해지면 `Settings` 필드로 올린다.

### 5.2 `app/schemas/health.py` (신규)
```python
"""헬스 체크 응답 스키마 (O-02). 200·503 모두 이 형식이다 (§3.1 에러 형식의 예외)."""

from enum import StrEnum

from pydantic import BaseModel


class HealthStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"  # 선택 구성요소(inbox)만 실패 → 200
    FAIL = "FAIL"  # 필수 구성요소(DB·음성 저장소) 실패 → 503


class ComponentStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"
    DISABLED = "DISABLED"  # 설정으로 꺼짐(INBOX_BACKEND=disabled). 판정에서 제외


class HealthChecks(BaseModel):
    db: ComponentStatus
    audio_storage: ComponentStatus
    inbox: ComponentStatus


class HealthResponse(BaseModel):
    """전체 상태와 구성요소별 상태. 실패 원인은 응답에 없고 로그(`health_check_failed`)에만 있다."""

    status: HealthStatus
    checks: HealthChecks
```

### 5.3 `app/services/health_service.py` (신규)
```python
"""헬스 체크 (O-02): DB·음성 저장소·inbox 접근 확인과 전체 판정."""

import threading
import time
from collections.abc import Callable

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.infra.inbox import InboxUnavailableError, InboxWriter
from app.infra.storage import AudioStorage, StorageError
from app.schemas.health import ComponentStatus, HealthChecks, HealthResponse, HealthStatus

# inbox(Drive) 확인은 느릴 수 있어(소켓 타임아웃 5초 × 토큰 갱신·조회) 결과를 재사용한다.
INBOX_CHECK_TTL_SEC = 30.0

_log = structlog.stdlib.get_logger("app.health")


class InboxCheckCache:
    """inbox 확인 결과를 TTL 동안 재사용한다. 성공·실패 모두 캐시한다.

    만료 시 한 스레드만 확인하고, 그동안 다른 요청은 잠금에서 기다렸다가 새 결과를 쓴다.
    앱마다 하나(`app.state.inbox_health_cache`)라 테스트 간 상태가 섞이지 않는다.
    """

    def __init__(
        self,
        ttl_sec: float = INBOX_CHECK_TTL_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._result: ComponentStatus | None = None
        self._checked_at = 0.0

    def get(self, check: Callable[[], ComponentStatus]) -> ComponentStatus:
        with self._lock:
            if self._result is None or self._clock() - self._checked_at >= self._ttl:
                # check()가 예상 밖 예외(버그)를 던지면 캐시하지 않고 그대로 올린다.
                self._result = check()
                self._checked_at = self._clock()
            return self._result


def overall_status(checks: HealthChecks) -> HealthStatus:
    """DB·음성 저장소는 필수(실패 → FAIL), inbox는 선택(실패 → DEGRADED, DISABLED는 제외)."""
    if ComponentStatus.FAIL in (checks.db, checks.audio_storage):
        return HealthStatus.FAIL
    if checks.inbox == ComponentStatus.FAIL:
        return HealthStatus.DEGRADED
    return HealthStatus.OK


def _failed(component: str, reason: str) -> ComponentStatus:
    # 원인 예외(str·exc_info)에는 DB 호스트·SQL·키 경로가 있을 수 있어 분류 값만 남긴다.
    _log.warning("health_check_failed", component=component, reason=reason)
    return ComponentStatus.FAIL


class HealthService:
    def __init__(
        self,
        session: Session,
        storage: AudioStorage,
        writer: InboxWriter | None,
        inbox_cache: InboxCheckCache,
    ) -> None:
        self._session = session
        self._storage = storage
        self._writer = writer
        self._inbox_cache = inbox_cache

    def check(self) -> HealthResponse:
        checks = HealthChecks(
            db=self._check_db(),
            audio_storage=self._check_audio_storage(),
            inbox=self._check_inbox(),
        )
        return HealthResponse(status=overall_status(checks), checks=checks)

    def _check_db(self) -> ComponentStatus:
        try:
            self._session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            return _failed("db", type(exc).__name__)
        return ComponentStatus.OK

    def _check_audio_storage(self) -> ComponentStatus:
        try:
            self._storage.check()
        except StorageError as exc:
            # StorageError에는 분류 속성이 없어 원인 예외(OSError 계열) 클래스 이름을 쓴다.
            return _failed("audio_storage", type(exc.__cause__ or exc).__name__)
        return ComponentStatus.OK

    def _check_inbox(self) -> ComponentStatus:
        writer = self._writer
        if writer is None:  # INBOX_BACKEND=disabled: 실패가 아니다
            return ComponentStatus.DISABLED

        def check() -> ComponentStatus:
            try:
                writer.check()
            except InboxUnavailableError as exc:
                return _failed("inbox", exc.reason)
            return ComponentStatus.OK

        return self._inbox_cache.get(check)
```
- `_check_inbox`의 내부 함수 `check`는 캐시 미스일 때만 불린다 → 실패 로그도 실제 확인했을 때만 1줄.
- `except`는 선언된 예외만 잡는다(D12). `Exception`을 잡으면 버그가 `FAIL`로 숨는다.
- 잠금을 쥔 채 `writer.check()`를 부른다(최악 10초 남짓). 그동안 들어온 헬스 요청은 잠금에서 기다린다 — 의도한 동작(D3). DB·저장소 확인은 잠금 밖.

### 5.4 `app/api/health.py` (신규)
```python
"""헬스 체크 API: `GET /health` (인증 없음, 모니터링용)."""

import threading
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from starlette.datastructures import State

from app.api.deps import DbSession, get_audio_storage, get_inbox_writer
from app.infra.inbox import InboxWriter
from app.infra.storage import AudioStorage
from app.schemas.health import HealthResponse, HealthStatus
from app.services.health_service import HealthService, InboxCheckCache

router = APIRouter(tags=["health"])

_cache_init_lock = threading.Lock()


def _inbox_cache(state: State) -> InboxCheckCache:
    # create_app을 건드리지 않도록 첫 요청 때 만든다. 테스트는 미리 넣어 시계를 바꿀 수 있다.
    with _cache_init_lock:
        cache: InboxCheckCache | None = getattr(state, "inbox_health_cache", None)
        if cache is None:
            cache = InboxCheckCache()
            state.inbox_health_cache = cache
        return cache


def get_health_service(
    request: Request,
    session: DbSession,
    storage: Annotated[AudioStorage, Depends(get_audio_storage)],
    writer: Annotated[InboxWriter | None, Depends(get_inbox_writer)],
) -> HealthService:
    return HealthService(session, storage, writer, _inbox_cache(request.app.state))


@router.get(
    "/health",
    responses={503: {"model": HealthResponse, "description": "필수 구성요소(DB·음성 저장소) 실패"}},
)
def get_health(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    # def(동기): DB·파일시스템·Drive 확인이 모두 블로킹이라 워커 스레드에서 돌린다.
    result = service.check()
    response.headers["Cache-Control"] = "no-store"
    if result.status == HealthStatus.FAIL:
        response.status_code = 503
    return result
```
- `async def`로 바꾸지 않는다(H3). 의존성 `get_health_service`·`get_db`도 동기라 스레드풀에서 실행된다.
- 라우터에 `prefix`가 없다(경로가 `/health` 하나). 로봇 인증 미들웨어는 `/api/robot` 경로만 보므로 별도 처리 불필요.

### 5.5 `app/main.py` (수정)
```python
from app.api import health
from app.api.robot import calls as robot_calls
...
    app.include_router(uploads.router)
    app.include_router(health.router)
```

### 5.6 `docs/api/openapi.json` (재생성)
```bash
cd backend && uv run python -m scripts.export_openapi
```
생성 결과 요점(실측, 기존 대비 추가만 106줄)
- `paths./health.get`: `operationId` `get_health`, 태그 `health`, 응답 `200`·`503`(둘 다 `HealthResponse`), `422`(`ValidationErrorResponse`), `500`(`ErrorResponse`)
- 추가 스키마: `HealthResponse`(설명 = 클래스 docstring), `HealthChecks`(`db`·`audio_storage`·`inbox` 필수), `HealthStatus`(`OK`,`DEGRADED`,`FAIL`), `ComponentStatus`(`OK`,`FAIL`,`DISABLED`)
- 재생성은 구현 마지막에 한 번 하고, diff가 위 추가뿐인지 확인한다.

### 5.7 공용 문서 보완 (중립 표현)

`docs/api/convention.md`

① §2.2 표 — `POST /api/robot/calls/{id}/logs` 행 뒤에 추가
```markdown
| GET | `/health` | 200 (`OK`·`DEGRADED`) / 503 (`FAIL`), 본문은 둘 다 헬스 형식(§3.6) | 500 |
```

② §3.5 뒤에 신설
~~~markdown
### 3.6 헬스 체크 (`GET /health`) — 에러 형식의 예외
- 503도 §3.1 에러 형식이 아니라 200과 같은 **헬스 형식**으로 돌려준다(어느 구성요소가 문제인지 보이도록). 헬스용 `ErrorCode`는 없다.
  ```json
  { "status": "FAIL", "checks": { "db": "FAIL", "audio_storage": "OK", "inbox": "OK" } }
  ```
- `status`: `OK`(200), `DEGRADED`(200, 선택 구성요소 `inbox`만 실패), `FAIL`(503, 필수 구성요소 `db`·`audio_storage` 중 하나 이상 실패).
- `checks`의 값: `OK`, `FAIL`, `DISABLED`(`INBOX_BACKEND=disabled`, 전체 판정에서 제외).
- 실패 원인은 응답에 넣지 않는다. 원인은 로그(`app.health` 로거 `health_check_failed`, 필드 `component`·`reason`)에 있으며 응답의 `X-Request-Id`로 찾는다.
- `inbox` 확인 결과는 서버 프로세스마다 30초 동안 재사용된다(성공·실패 모두). `db`·`audio_storage`는 요청마다 확인한다.
- 인증이 없다(로봇 API Key·IP 검사 대상 아님). 응답에 `Cache-Control: no-store`.
- 예상하지 못한 서버 오류는 §3.1 형식의 500 `INTERNAL_ERROR`다.
~~~

③ §5.3 값 집합 표 끝에 추가
```markdown
| 헬스 `status` | `OK`, `DEGRADED`, `FAIL` |
| 헬스 `checks.*` | `OK`, `FAIL`, `DISABLED` |
```

④ §7-4
```markdown
4. 라우터에 `tags`를 붙인다: 웹 `calls`·`uploads`·`stats`·`reports`, 로봇 `robot`, 운영 `health`.
```

`docs/architecture/architecture.md`
| 위치 | 현재 | 변경 |
|---|---|---|
| §3.2 `api/` | `deps.py`, `web/`, `robot/` | `│   │   ├── health.py            # GET /health (헬스 체크)` 추가(`deps.py` 다음 줄) |
| §3.2 `schemas/` | `# Pydantic: call, transcript, analysis(GenAI JSON), stats, common` | `…, stats, health, common` |
| §3.2 `services/` | `upload_service.py` 등 | `│   │   ├── health_service.py    # DB·음성 저장소·inbox 확인, 판정, inbox 결과 캐시` 추가(`upload_service.py` 다음 줄) |
| §7.1 `/health` 행 비고 | `DB·음성 저장소·Drive inbox/ 접근 확인` | `DB·음성 저장소(필수, 실패 시 503)·Drive inbox/(선택, 실패 시 200 DEGRADED) 접근 확인. 503도 헬스 형식(convention.md §3.6)` |
| §12 헬스 체크 행 | `GET /health → DB SELECT 1, 음성 저장소 쓰기, Drive inbox/ 폴더 메타데이터 조회 가능 여부` | `` `GET /health` → DB `SELECT 1`(연결 타임아웃 5초), 음성 저장소 폴더 생성·쓰기 권한(`AudioStorage.check()`), Drive `inbox/` 폴더 메타데이터 조회(`InboxWriter.check()`, 결과 30초 캐시). DB·음성 저장소 실패 → 503 `FAIL`, inbox 실패 → 200 `DEGRADED`, `INBOX_BACKEND=disabled`면 `DISABLED`(판정 제외). 원인은 응답이 아니라 로그 `health_check_failed`에만 `` |

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 서비스 테스트는 가짜(`FakeSession`·`FakeStorage`·`FakeInbox`·`FakeClock`)로 판정·캐시·로그를 확인한다. mypy가 `tests/`도 검사하므로 가짜는 `Any`로 넘긴다(프로토콜 전체를 구현하지 않음).
- 라우터 테스트는 `build_app(**overrides)`로 앱을 만들고 `app.dependency_overrides[get_db]`(가짜 세션), `app.state.audio_storage`, `app.state.inbox_writer`를 바꾼다. 시계는 `app.state.inbox_health_cache = InboxCheckCache(clock=FakeClock())`로 주입한다.
- 실제 어댑터 경로는 `build_app(audio_storage_root=tmp_path/..., inbox_backend="local", inbox_local_path=tmp_path/...)`로 확인한다. 읽기 전용 폴더는 Windows·root에서 재현이 불안정하므로 "파일 아래 경로"(mkdir 실패)로 저장소 실패를 만든다.
- 원인 비노출은 원인 예외에 `SECRET` 문구를 넣고 응답·로그에 없음을 단언한다(ASCII 문구 — JSON 로그는 한글을 `\uXXXX`로 냄).
- 동시성은 `threading.Event`로 첫 확인이 잠금을 쥔 상태를 만든 뒤 나머지 스레드를 시작해 **결정적으로** 확인한다(sleep 없음).
- DB 확인은 통합 테스트로 실제 PostgreSQL(testcontainers, `api` 픽스처)과 연결 거부(닫힌 포트, 실제 엔진 경로)를 확인한다. 연결 거부 테스트는 Docker가 필요 없지만 실제 네트워크·드라이버를 쓰므로 `integration` 마커에 둔다(Windows 약 5초).
- `connect_timeout`은 실제 무응답 호스트 대신 SQLAlchemy `do_connect` 이벤트로 드라이버에 넘길 인자를 확인한다(빠르고 결정적). 무응답 동작은 수동 확인(§6.5).

### 6.2 케이스 목록 (구현 순서)

**1단계 — DB 연결 타임아웃 (`test_db.py`)** → `db.py` (커밋 2)
| # | 테스트 | 기대 |
|---|---|---|
| 1 | `test_engine_sets_connect_timeout` | `do_connect`의 `cparams["connect_timeout"] == 5` (D4) |

**2단계 — 판정·확인 (`test_health_service.py`)** → `schemas/health.py`, `overall_status`, `HealthService`
| # | 테스트 | 기대 |
|---|---|---|
| 2 | `test_overall_status` ×7 | OK/OK/OK→OK, OK/OK/DISABLED→OK, OK/OK/FAIL→DEGRADED, FAIL/OK/OK→FAIL, OK/FAIL/OK→FAIL, FAIL/OK/FAIL→FAIL, OK/FAIL/DISABLED→FAIL (D1) |
| 3 | `test_all_ok` | 본문 전체 일치, 실행 문장 `["SELECT 1"]` |
| 4 | `test_disabled_inbox_is_not_checked` | `writer=None` → `inbox=DISABLED`, 전체 OK (H1) |
| 5 | `test_db_failure_is_fail` | `OperationalError` → `db=FAIL`, 전체 FAIL |
| 6 | `test_audio_storage_failure_is_fail` | `StorageError` → `audio_storage=FAIL`, 전체 FAIL |
| 7 | `test_inbox_failure_is_degraded` | `InboxUnavailableError("http_404")` → `inbox=FAIL`, 전체 DEGRADED (D1) |
| 8 | `test_every_component_is_checked_even_after_failure` | DB 실패여도 저장소·inbox 각 1회 확인 |
| 9 | `test_unexpected_errors_are_not_swallowed` ×2 | 저장소·inbox의 `RuntimeError`/`ValueError`는 그대로 올라감 (D12) |

**3단계 — 로그 (`test_health_service.py`)**
| # | 테스트 | 기대 |
|---|---|---|
| 10 | `test_failures_are_logged_with_reason_only` | `health_check_failed` 3줄(`db`/`OperationalError`, `audio_storage`/`PermissionError`, `inbox`/`http_404`), level warning, `SECRET`·`exception`·`Traceback` 없음 (D2, H7) |
| 11 | `test_storage_error_without_cause_uses_class_name` | 원인 없는 `StorageError` → `reason == "StorageError"` |
| 12 | `test_success_is_not_logged` | 정상이면 `app.health` 로그 없음 |

**4단계 — inbox 캐시 (`test_health_service.py`)** → `InboxCheckCache`
| # | 테스트 | 기대 |
|---|---|---|
| 13 | `test_inbox_result_is_reused_within_ttl` | TTL-0.1초 경과 → `check()` 1회 (D3) |
| 14 | `test_inbox_is_checked_again_after_ttl` | TTL 경과 → 2회 |
| 15 | `test_inbox_failure_is_cached_and_logged_once` | 실패도 캐시, 로그 1줄 (D3, H5) |
| 16 | `test_inbox_recovery_is_seen_after_ttl` | DEGRADED → (복구, TTL 경과) → OK |
| 17 | `test_unexpected_error_is_not_cached` | 버그 예외 후 다음 호출에서 다시 확인 (D12) |
| 18 | `test_db_and_storage_are_not_cached` | 두 번 호출 → DB 2회·저장소 2회 |
| 19 | `test_concurrent_requests_check_inbox_once` | 첫 확인이 잠금을 쥔 동안 7개 스레드 진입 → `check()` 1회, 8개 모두 같은 결과 (D3) |

**5단계 — 라우터 (`test_health_api.py`)** → `api/health.py`, `main.py`
| # | 테스트 | 기대 |
|---|---|---|
| 20 | `test_all_ok_is_200` | 200, 본문 전체 일치 |
| 21 | `test_headers` | `Cache-Control: no-store`, `X-Request-Id` |
| 22 | `test_disabled_inbox_is_200_ok` | 기본 disabled → 200, `inbox=DISABLED` |
| 23 | `test_db_failure_is_503_in_health_format` | 503, 본문이 헬스 형식(에러 형식 아님), `no-store` (D2) |
| 24 | `test_audio_storage_failure_is_503` | 503, `audio_storage=FAIL` |
| 25 | `test_inbox_failure_is_200_degraded` | 200 `DEGRADED` (D1) |
| 26 | `test_response_has_no_reason` | 본문에 `SECRET`·`http_404`·예외 클래스 이름·`reason` 없음 (D2) |
| 27 | `test_failure_log_has_request_id_and_no_cause` | `health_check_failed`에 요청의 `request_id`, 원인 문구·`Traceback` 없음 |
| 28 | `test_no_robot_auth_required` | 로봇 키·IP 비어 있어도 200 |
| 29 | `test_unexpected_error_is_500_in_error_format` | 저장소 `RuntimeError` → 500 `INTERNAL_ERROR`, 원문 없음 (D12) |
| 30 | `test_inbox_check_is_cached_across_requests` | 요청 3번 → `check()` 1회, 모두 DEGRADED |
| 31 | `test_injected_clock_expires_cache` | `app.state.inbox_health_cache`에 가짜 시계 → TTL 경과 후 2회 |
| 32 | `test_cache_is_per_app` | 앱 두 개 → 각 writer 1회(캐시 공유 없음) |
| 33 | `test_local_adapters_are_ok_and_create_folders` | 실제 `LocalStorage`·`LocalInboxWriter` → 200 OK, 두 폴더 생성 |
| 34 | `test_local_storage_on_file_path_is_503` | 파일 아래 경로 → 503 `audio_storage=FAIL`, 로그에 경로 없음 |
| 35 | `test_openapi_health` | operationId `get_health`, 태그 `health`, 응답 `{200,422,500,503}`, 200·503 `$ref` `HealthResponse`, enum 값 순서, `HealthChecks` 필수 3개 (D10) |

**6단계 — 통합 (`tests/integration/test_health_api.py`)**
| # | 테스트 | 기대 |
|---|---|---|
| 36 | `test_health_ok_with_real_db` | 실제 PostgreSQL(`api` 픽스처) → 200, `db=OK` |
| 37 | `test_health_is_503_when_db_refuses_connection` | `get_db` 오버라이드 없이 `127.0.0.1:1` → 503 `db=FAIL`, 응답에 비밀번호 없음 |

**7단계 — OpenAPI 재생성** → `test_committed_openapi_is_up_to_date` 통과

### 6.3 케이스 수
신규 44건: `test_db` 1, `test_health_service` 25, `test_health_api` 16, 통합 2.

### 6.4 테스트 코드

#### `tests/unit/test_db.py` (신규, 커밋 2)
```python
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
```

#### `tests/unit/health_fakes.py` (신규)
```python
"""헬스 체크 테스트 공용 가짜: DB 세션, 음성 저장소, inbox writer, 시계."""

from typing import Any

from sqlalchemy.exc import OperationalError

from app.infra.inbox import InboxUnavailableError
from app.infra.storage import StorageError

SECRET = "secret-host-and-key-path"  # 응답·로그에 나오면 안 되는 원인 문구


class FakeSession:
    """`execute`만 흉내 낸다. fail이면 연결 실패(OperationalError)."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.statements: list[str] = []

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception(SECRET))


class FakeStorage:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def check(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def storage_error() -> StorageError:
    """LocalStorage.check()의 mkdir 실패와 같은 모양(원인 예외 체인)."""
    try:
        try:
            raise PermissionError(SECRET)
        except PermissionError as exc:
            raise StorageError("저장소 폴더를 만들 수 없습니다: PermissionError") from exc
    except StorageError as exc:
        return exc


class FakeInbox:
    """check() 호출 횟수를 센다. reason이 있으면 InboxUnavailableError, error면 그 예외."""

    def __init__(self, reason: str | None = None, error: Exception | None = None) -> None:
        self.reason = reason
        self.error = error
        self.calls = 0

    def check(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.reason is not None:
            raise InboxUnavailableError(self.reason) from OSError(SECRET)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now
```

#### `tests/unit/test_health_service.py` (신규)
```python
"""HealthService·InboxCheckCache·overall_status — 가짜 의존 대상으로 판정·캐시·로그를 확인한다."""

import json
import threading
from typing import Any

import pytest

from app.core.logging import configure_logging
from app.infra.storage import StorageError
from app.schemas.health import ComponentStatus, HealthChecks, HealthStatus
from app.services.health_service import (
    INBOX_CHECK_TTL_SEC,
    HealthService,
    InboxCheckCache,
    overall_status,
)
from tests.unit.health_fakes import (
    SECRET,
    FakeClock,
    FakeInbox,
    FakeSession,
    FakeStorage,
    storage_error,
)

OK = ComponentStatus.OK
FAIL = ComponentStatus.FAIL
DISABLED = ComponentStatus.DISABLED


def _service(
    session: Any = None,
    storage: Any = None,
    writer: Any = None,
    cache: InboxCheckCache | None = None,
) -> HealthService:
    fake_session: Any = session or FakeSession()
    fake_storage: Any = storage or FakeStorage()
    return HealthService(fake_session, fake_storage, writer, cache or InboxCheckCache())


def _health_logs(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [line for line in lines if line.get("logger") == "app.health"]


# ---------------------------------------------------------------- 전체 판정


@pytest.mark.parametrize(
    ("db", "audio_storage", "inbox", "expected"),
    [
        (OK, OK, OK, HealthStatus.OK),
        (OK, OK, DISABLED, HealthStatus.OK),
        (OK, OK, FAIL, HealthStatus.DEGRADED),
        (FAIL, OK, OK, HealthStatus.FAIL),
        (OK, FAIL, OK, HealthStatus.FAIL),
        (FAIL, OK, FAIL, HealthStatus.FAIL),
        (OK, FAIL, DISABLED, HealthStatus.FAIL),
    ],
)
def test_overall_status(
    db: ComponentStatus,
    audio_storage: ComponentStatus,
    inbox: ComponentStatus,
    expected: HealthStatus,
) -> None:
    checks = HealthChecks(db=db, audio_storage=audio_storage, inbox=inbox)

    assert overall_status(checks) == expected


# ---------------------------------------------------------------- 구성요소 확인


def test_all_ok() -> None:
    session = FakeSession()

    result = _service(session=session, writer=FakeInbox()).check()

    assert result.model_dump() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "OK"},
    }
    assert session.statements == ["SELECT 1"]


def test_disabled_inbox_is_not_checked() -> None:
    result = _service(writer=None).check()

    assert result.status == HealthStatus.OK
    assert result.checks.inbox == DISABLED


def test_db_failure_is_fail() -> None:
    result = _service(session=FakeSession(fail=True), writer=FakeInbox()).check()

    assert result.status == HealthStatus.FAIL
    assert result.checks.db == FAIL
    assert result.checks.audio_storage == OK


def test_audio_storage_failure_is_fail() -> None:
    result = _service(storage=FakeStorage(storage_error())).check()

    assert result.status == HealthStatus.FAIL
    assert result.checks.audio_storage == FAIL


def test_inbox_failure_is_degraded() -> None:
    result = _service(writer=FakeInbox(reason="http_404")).check()

    assert result.status == HealthStatus.DEGRADED
    assert result.checks.inbox == FAIL


def test_every_component_is_checked_even_after_failure() -> None:
    storage = FakeStorage()
    writer = FakeInbox()

    result = _service(session=FakeSession(fail=True), storage=storage, writer=writer).check()

    assert result.checks.model_dump() == {"db": "FAIL", "audio_storage": "OK", "inbox": "OK"}
    assert (storage.calls, writer.calls) == (1, 1)


@pytest.mark.parametrize(
    "error",
    [RuntimeError("bug"), ValueError("bug")],
)
def test_unexpected_errors_are_not_swallowed(error: Exception) -> None:
    with pytest.raises(type(error)):
        _service(storage=FakeStorage(error)).check()
    with pytest.raises(type(error)):
        _service(writer=FakeInbox(error=error)).check()


# ---------------------------------------------------------------- 로그


def test_failures_are_logged_with_reason_only(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    _service(
        session=FakeSession(fail=True),
        storage=FakeStorage(storage_error()),
        writer=FakeInbox(reason="http_404"),
    ).check()

    logs = _health_logs(capsys)
    assert [(log["event"], log["component"], log["reason"]) for log in logs] == [
        ("health_check_failed", "db", "OperationalError"),
        ("health_check_failed", "audio_storage", "PermissionError"),
        ("health_check_failed", "inbox", "http_404"),
    ]
    assert all(log["level"] == "warning" for log in logs)
    dumped = json.dumps(logs)
    assert SECRET not in dumped
    assert "exception" not in dumped
    assert "Traceback" not in dumped


def test_storage_error_without_cause_uses_class_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    _service(storage=FakeStorage(StorageError("저장소 폴더에 쓸 수 없습니다"))).check()

    (log,) = _health_logs(capsys)
    assert log["reason"] == "StorageError"


def test_success_is_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    _service(writer=FakeInbox()).check()

    assert _health_logs(capsys) == []


# ---------------------------------------------------------------- inbox 캐시


def test_inbox_result_is_reused_within_ttl() -> None:
    clock = FakeClock()
    cache = InboxCheckCache(clock=clock)
    writer = FakeInbox()
    service = _service(writer=writer, cache=cache)

    service.check()
    clock.now += INBOX_CHECK_TTL_SEC - 0.1
    service.check()

    assert writer.calls == 1


def test_inbox_is_checked_again_after_ttl() -> None:
    clock = FakeClock()
    cache = InboxCheckCache(clock=clock)
    writer = FakeInbox()
    service = _service(writer=writer, cache=cache)

    service.check()
    clock.now += INBOX_CHECK_TTL_SEC
    service.check()

    assert writer.calls == 2


def test_inbox_failure_is_cached_and_logged_once(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    capsys.readouterr()
    clock = FakeClock()
    writer = FakeInbox(reason="DefaultCredentialsError")
    service = _service(writer=writer, cache=InboxCheckCache(clock=clock))

    first = service.check()
    clock.now += 10
    second = service.check()

    assert first.checks.inbox == second.checks.inbox == FAIL
    assert writer.calls == 1
    assert len(_health_logs(capsys)) == 1


def test_inbox_recovery_is_seen_after_ttl() -> None:
    clock = FakeClock()
    writer = FakeInbox(reason="http_503")
    service = _service(writer=writer, cache=InboxCheckCache(clock=clock))

    assert service.check().status == HealthStatus.DEGRADED
    writer.reason = None
    clock.now += INBOX_CHECK_TTL_SEC
    assert service.check().status == HealthStatus.OK


def test_unexpected_error_is_not_cached() -> None:
    writer = FakeInbox(error=RuntimeError("bug"))
    service = _service(writer=writer, cache=InboxCheckCache(clock=FakeClock()))

    with pytest.raises(RuntimeError):
        service.check()
    writer.error = None
    assert service.check().checks.inbox == OK
    assert writer.calls == 2


def test_db_and_storage_are_not_cached() -> None:
    session = FakeSession()
    storage = FakeStorage()
    service = _service(session=session, storage=storage, cache=InboxCheckCache(clock=FakeClock()))

    service.check()
    service.check()

    assert len(session.statements) == 2
    assert storage.calls == 2


def test_concurrent_requests_check_inbox_once() -> None:
    cache = InboxCheckCache()
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_check() -> ComponentStatus:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return OK

    results: list[ComponentStatus] = []
    threads = [threading.Thread(target=lambda: results.append(cache.get(slow_check)))]
    threads[0].start()
    assert started.wait(timeout=5)
    # 첫 확인이 잠금을 쥔 동안 들어온 요청들
    threads += [
        threading.Thread(target=lambda: results.append(cache.get(slow_check))) for _ in range(7)
    ]
    for thread in threads[1:]:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(timeout=5)

    assert calls == 1
    assert results == [OK] * 8
```

#### `tests/unit/test_health_api.py` (신규)
```python
"""`GET /health` 라우터 — 가짜 의존 대상과 실제 로컬 어댑터로 상태 코드·본문·헤더를 확인한다."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.logging import configure_logging
from app.services.health_service import INBOX_CHECK_TTL_SEC, InboxCheckCache
from tests.unit.health_fakes import (
    SECRET,
    FakeClock,
    FakeInbox,
    FakeSession,
    FakeStorage,
    storage_error,
)

_URL = "/health"


def _app(
    build_app: Callable[..., FastAPI],
    *,
    session: FakeSession | None = None,
    storage: Any = None,
    writer: Any = None,
    **overrides: Any,
) -> FastAPI:
    app = build_app(**overrides)
    fake_session = session or FakeSession()
    app.dependency_overrides[get_db] = lambda: fake_session
    app.state.audio_storage = storage or FakeStorage()
    app.state.inbox_writer = writer
    return app


def _get(app: FastAPI) -> Any:
    return TestClient(app).get(_URL)


def test_all_ok_is_200(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, writer=FakeInbox()))

    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "OK"},
    }


def test_headers(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app))

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-Id"]


def test_disabled_inbox_is_200_ok(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, writer=None))

    assert response.status_code == 200
    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "DISABLED"},
    }


def test_db_failure_is_503_in_health_format(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, session=FakeSession(fail=True), writer=FakeInbox()))

    assert response.status_code == 503
    assert response.json() == {
        "status": "FAIL",
        "checks": {"db": "FAIL", "audio_storage": "OK", "inbox": "OK"},
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_audio_storage_failure_is_503(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, storage=FakeStorage(storage_error())))

    assert response.status_code == 503
    assert response.json() == {
        "status": "FAIL",
        "checks": {"db": "OK", "audio_storage": "FAIL", "inbox": "DISABLED"},
    }


def test_inbox_failure_is_200_degraded(build_app: Callable[..., FastAPI]) -> None:
    response = _get(_app(build_app, writer=FakeInbox(reason="http_404")))

    assert response.status_code == 200
    assert response.json() == {
        "status": "DEGRADED",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "FAIL"},
    }


def test_response_has_no_reason(build_app: Callable[..., FastAPI]) -> None:
    app = _app(
        build_app,
        session=FakeSession(fail=True),
        storage=FakeStorage(storage_error()),
        writer=FakeInbox(reason="http_404"),
    )

    body = _get(app).text

    for hidden in (SECRET, "http_404", "OperationalError", "PermissionError", "reason"):
        assert hidden not in body


def test_failure_log_has_request_id_and_no_cause(
    build_app: Callable[..., FastAPI], capsys: pytest.CaptureFixture[str]
) -> None:
    app = _app(build_app, session=FakeSession(fail=True))
    capsys.readouterr()

    TestClient(app).get(_URL, headers={"X-Request-Id": "rid-health"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    (failed,) = [line for line in lines if line.get("event") == "health_check_failed"]
    assert failed["request_id"] == "rid-health"
    assert (failed["component"], failed["reason"]) == ("db", "OperationalError")
    assert SECRET not in json.dumps(lines)
    assert "Traceback" not in json.dumps(lines)


def test_no_robot_auth_required(build_app: Callable[..., FastAPI]) -> None:
    # 로봇 키가 비어 있으면 /api/robot/*는 모두 401이지만 /health는 영향이 없다.
    app = _app(build_app, robot_api_keys=[], robot_allowed_ips=[])

    assert _get(app).status_code == 200


def test_unexpected_error_is_500_in_error_format(build_app: Callable[..., FastAPI]) -> None:
    app = _app(build_app, storage=FakeStorage(RuntimeError("boom-secret")))

    response = TestClient(app, raise_server_exceptions=False).get(_URL)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "boom-secret" not in response.text


# ---------------------------------------------------------------- inbox 캐시 (앱 단위)


def test_inbox_check_is_cached_across_requests(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeInbox(reason="http_403")
    client = TestClient(_app(build_app, writer=writer))

    statuses = [client.get(_URL).json()["status"] for _ in range(3)]

    assert statuses == ["DEGRADED"] * 3
    assert writer.calls == 1


def test_injected_clock_expires_cache(build_app: Callable[..., FastAPI]) -> None:
    clock = FakeClock()
    writer = FakeInbox()
    app = _app(build_app, writer=writer)
    app.state.inbox_health_cache = InboxCheckCache(clock=clock)
    client = TestClient(app)

    client.get(_URL)
    clock.now += INBOX_CHECK_TTL_SEC
    client.get(_URL)

    assert writer.calls == 2


def test_cache_is_per_app(build_app: Callable[..., FastAPI]) -> None:
    first = FakeInbox()
    second = FakeInbox()

    _get(_app(build_app, writer=first))
    _get(_app(build_app, writer=second))

    assert (first.calls, second.calls) == (1, 1)


# ---------------------------------------------------------------- 실제 로컬 어댑터


def test_local_adapters_are_ok_and_create_folders(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    audio = tmp_path / "audio"
    inbox = tmp_path / "inbox"
    app = build_app(audio_storage_root=audio, inbox_backend="local", inbox_local_path=inbox)
    fake_session = FakeSession()
    app.dependency_overrides[get_db] = lambda: fake_session

    response = TestClient(app).get(_URL)

    assert response.json() == {
        "status": "OK",
        "checks": {"db": "OK", "audio_storage": "OK", "inbox": "OK"},
    }
    assert audio.is_dir()
    assert inbox.is_dir()


def test_local_storage_on_file_path_is_503(
    build_app: Callable[..., FastAPI], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"x")
    app = build_app(audio_storage_root=blocker / "audio")
    fake_session = FakeSession()
    app.dependency_overrides[get_db] = lambda: fake_session
    configure_logging("INFO")
    capsys.readouterr()

    response = TestClient(app).get(_URL)

    assert response.status_code == 503
    assert response.json()["checks"]["audio_storage"] == "FAIL"
    assert str(tmp_path.name) not in capsys.readouterr().out


# ---------------------------------------------------------------- OpenAPI


def test_openapi_health(build_app: Callable[..., FastAPI]) -> None:
    spec = build_app().openapi()
    operation = spec["paths"]["/health"]["get"]
    schemas = spec["components"]["schemas"]

    assert operation["operationId"] == "get_health"
    assert operation["tags"] == ["health"]
    assert set(operation["responses"]) == {"200", "422", "500", "503"}
    for status in ("200", "503"):
        ref = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/HealthResponse")
    assert schemas["HealthStatus"]["enum"] == ["OK", "DEGRADED", "FAIL"]
    assert schemas["ComponentStatus"]["enum"] == ["OK", "FAIL", "DISABLED"]
    assert set(schemas["HealthChecks"]["required"]) == {"db", "audio_storage", "inbox"}
```

#### `tests/integration/test_health_api.py` (신규)
```python
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


def test_health_is_503_when_db_refuses_connection(tmp_path: Path) -> None:
    # get_db 오버라이드 없이 실제 엔진·세션 경로. 닫힌 포트라 연결 거부로 바로 실패한다.
    refused = "postgresql+psycopg://callcenter:secret-pw@127.0.0.1:1/callcenter"
    app = create_app(Settings(_env_file=None, database_url=refused, audio_storage_root=tmp_path))

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "FAIL",
        "checks": {"db": "FAIL", "audio_storage": "OK", "inbox": "DISABLED"},
    }
    assert "secret-pw" not in response.text
```

### 6.5 수동 확인
| # | 항목 | 방법 |
|---|---|---|
| M1 | 개발 서버 | `docker compose -f deploy/docker-compose.dev.yml up` 후 `curl -i localhost:8000/health` → 200, `inbox` 값은 `.env`의 `INBOX_BACKEND`에 따름 |
| M2 | DB 중단 | `docker compose ... stop db` → 503 `db=FAIL`, 로그 `health_check_failed` `component=db` |
| M3 | 연결 타임아웃 | `DATABASE_URL`을 라우팅되지 않는 주소(예: `10.255.255.1`)로 두고 `/health` → 약 5초 후 503(무응답 환경 의존, 자동 테스트 안 함) |
| M4 | 실제 Drive (E-01 이후) | 정상 폴더 OK, 서비스 계정 권한 제거 시 200 `DEGRADED` + 로그 `reason=http_404/http_403`, 30초 안 재호출 시 Drive 호출 없음(`inbox_check_failed` 로그 1줄) |

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 0 | 작업 트리 확인(리서치·계획 문서 외 미커밋 변경 없음) | `git status` |
| 1 | #1 작성(Red) → `db.py`(Green) → **커밋 2** | `uv run pytest tests/unit/test_db.py` |
| 2 | `health_fakes.py`, #2~9 → `schemas/health.py`, `overall_status`, `HealthService`(캐시 없이 `writer.check()` 직접) | `uv run pytest tests/unit/test_health_service.py` |
| 3 | #10~12 → `_failed` 로그 | 같은 파일 |
| 4 | #13~19 → `InboxCheckCache`, `_check_inbox`가 캐시 사용 | 같은 파일 |
| 5 | #20~35 → `api/health.py`, `main.py` 2줄 | `uv run pytest tests/unit` (이 시점에 `test_committed_openapi_is_up_to_date`만 실패) |
| 6 | #36~37 | `uv run pytest tests/integration/test_health_api.py` (Docker 필요) |
| 7 | `openapi.json` 재생성, diff가 §5.6 추가뿐인지 확인 → **커밋 3** | `uv run pytest` 전부 통과 |
| 8 | 공용 문서(§5.7) → **커밋 4** | 리뷰 |
| 9 | 전체 검증(§8) | |

---

## 8. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (Docker 있으면 통합 포함, drive는 항상 skip)
uv run pytest -m "not integration"   # 단위만
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
- 기대(사전 검증 시점, `2bde1c6` 기준): 710 통과·2 skip → **754 통과·2 skip**(신규 44). Docker가 없으면 통합 테스트는 skip.
- Windows Git Bash에서 Docker CLI가 PATH에 없으면 `export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"`.

---

## 9. 확인 필요

### 9.1 A (C-01/C-04 공용 코드, R-03, O-01)
| # | 항목 | 내용 |
|---|---|---|
| A1 | **`connect_timeout=5` (D4)** | `app/core/db.py`(공용)에 엔진 전체 연결 타임아웃 추가. 로봇 API·웹 API 모두 DB 무응답 시 5초 후 500이 된다(지금은 OS TCP 타임아웃까지 대기). alembic은 별도 엔진이라 무관. 별도 커밋이라 거절 시 그 커밋만 빼면 되고, 대신 운영 `DATABASE_URL`에 `?connect_timeout=5`를 붙이는 안(§3.2 D4 (d)) |
| A2 | 음성 저장소 확인 깊이 (D9) | `check()`는 폴더 생성 + 쓰기 권한만 본다 → 디스크 가득 참은 못 잡음. 실제 쓰기·여유 공간 확인이 필요한지, `StorageError`에 분류 속성(`reason`)을 둘 의향이 있는지 |
| A3 | Docker healthcheck (O-01) | 운영 `Dockerfile`/compose에 넣을지. `python:3.12-slim`에 `curl`이 없으므로 예: `HEALTHCHECK --interval=30s --timeout=20s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=15)"]` — 503이면 종료 코드 1, 200 `DEGRADED`는 healthy. non-root 실행 여부(저장소 `os.access` 판정 신뢰성) |
| A4 | `main.py` 변경 | import 1줄 + `include_router` 1줄만. 캐시는 첫 요청 때 `app.state.inbox_health_cache`에 생김(시작 시 초기화 없음) |

### 9.2 운영 (O-03)·E-01
| # | 항목 | 내용 |
|---|---|---|
| O1 | **모니터의 판정 기준** | HTTP 코드만 보는 모니터는 Drive 장애(200 `DEGRADED`)를 놓친다. 본문 `status`까지 보는지, Drive 장애 알림이 필요한지 |
| O2 | `NO_GCE_CHECK=true` | 비 GCP VM 운영 `.env`에 권장(H5: 자격 증명이 없을 때 매 확인 약 3초 지연). 캐시로 빈도는 30초당 1회로 줄지만 그 1회가 느림 |
| O3 | Drive 스코프(E1) | `drive.file`로 기존 `inbox/`에 `files.get`이 안 되면 헬스가 계속 `DEGRADED`(`reason=http_404`) — 헬스 버그가 아니라 E1 미해결 신호 |
| O4 | 워커 수 × TTL | Uvicorn 워커마다 캐시가 따로라 Drive 호출은 최대 워커 수 × 2회/분(할당량 대비 무시 수준 예상) |
| O5 | 접근 로그 양 | 30초 주기 모니터 1개당 하루 2,880줄(`app.access`). 많으면 성공 요청 제외 규칙을 별도로 논의(D8) |

### 9.3 RPA (④)
| # | 항목 | 내용 |
|---|---|---|
| R1 | 사전 점검 호출 | Dispatcher가 처리 전에 `/health`를 부를 계획이 있는지. 부른다면 로봇 흐름은 Drive와 무관하므로 `status != "FAIL"`(= HTTP 200)을 "진행 가능"으로 보면 된다. 계약은 `openapi.json`의 `get_health` |

### 9.4 알려진 제한
| # | 항목 | 내용 |
|---|---|---|
| L1 | 풀 고갈 | DB 풀이 고갈되면 헬스의 세션 체크아웃도 `pool_timeout` 기본 30초를 기다린 뒤 `FAIL`(`reason=TimeoutError`). 풀 고갈 자체가 장애 신호라 그대로 둠 |
| L2 | 캐시 중 대기 | inbox 캐시 만료 순간 Drive 확인(최악 10초 남짓) 동안 다른 헬스 요청은 잠금에서 기다린다. 스레드 수는 동시 헬스 요청 수만큼만 점유 |
| L3 | 워커별 결과 차이 | 다중 워커에서 inbox 결과가 워커마다 최대 30초 다를 수 있다(요청이 어느 워커로 가느냐에 따라 OK/DEGRADED가 번갈아 보일 수 있음) |
| L4 | Drive 오류 로그 2줄 | Drive 라이브러리·인증 오류는 어댑터(`inbox_check_failed`)와 헬스(`health_check_failed`)가 각각 남긴다(리서치 §7 중복 허용) |
| L5 | 연결 타임아웃 변경 | `connect_args`가 URL의 `connect_timeout`을 덮어써 값 조정은 코드 변경이 필요하다 |
| L6 | 422 문서화 | 파라미터가 없는데도 앱 단위 설정으로 422가 문서에 붙는다(기존 감수 결정) |

---

## 10. 구현 시 주의
1. 라우트·의존성은 `def`로 둔다. `async def`에서 `writer.check()`·`SELECT 1`을 부르면 이벤트 루프가 막힌다(H3).
2. 503은 `response.status_code = 503`으로 내고 `AppError`/`HTTPException`을 쓰지 않는다(쓰면 §3.1 에러 형식이 된다).
3. 응답에 `reason`·예외 메시지를 넣지 않는다. 로그는 `_failed(component, reason)` 한 곳에서만, `exc_info`·`_log.exception`·`str(exc)` 금지(H7).
4. `except`는 `SQLAlchemyError`·`StorageError`·`InboxUnavailableError`만. 버그는 500으로 올라가야 하고 캐시되면 안 된다(D12).
5. 캐시를 모듈 전역 변수로 두지 않는다(테스트마다 새 앱 → 상태 누출). `app.state.inbox_health_cache`에 둔다. 모듈 전역은 생성 잠금(`_cache_init_lock`)뿐이다.
6. `deps.py`를 수정하지 않는다(다른 작업과 충돌). 헬스 전용 의존성은 `app/api/health.py`에 둔다.
7. `main.py`는 import 1줄 + `include_router` 1줄만. `create_app`에 `app.state` 줄을 추가하지 않는다.
8. `openapi.json`은 충돌 시 손으로 합치지 말고 재생성한다(§4.2).
9. 라우트 함수 이름 `get_health`는 앱 전체에서 고유해야 한다(operationId).

---

## 11. 커밋 분할안

작업 단위 ID(O-02 등)는 커밋 메시지에 넣지 않는다.

| 순서 | 커밋 메시지 | 포함 파일 |
|---|---|---|
| 1 | `docs: 헬스 체크 리서치·구현 계획 추가` | `docs/researchs/health-check.md`, `docs/plans/health-check.md` |
| 2 | `feat: DB 연결 타임아웃(5초) 추가 — 호스트 무응답 시 무한 대기 방지` | `app/core/db.py`, `tests/unit/test_db.py` |
| 3 | `feat: 헬스 체크 API(GET /health) 추가 — DB·음성 저장소·inbox 확인, inbox 결과 캐시` | `app/schemas/health.py`, `app/services/health_service.py`, `app/api/health.py`, `app/main.py`, `docs/api/openapi.json`, `tests/unit/{health_fakes,test_health_service,test_health_api}.py`, `tests/integration/test_health_api.py` |
| 4 | `docs: 헬스 체크 응답 형식·판정 규칙을 규약·아키텍처 문서에 반영` | `docs/api/convention.md`, `docs/architecture/architecture.md` |

- 2번은 공용 코드(`db.py`) 변경이라 따로 둔다. A 리뷰(§9.1 A1)에서 거절되면 2번만 빼도 3·4번은 그대로 동작한다(§12 문구의 "연결 타임아웃 5초"만 지움).
- 4번을 3번에 합칠지는 리뷰에서 정한다(규약 문구가 API 동작과 같은 PR에 들어가면 된다).
