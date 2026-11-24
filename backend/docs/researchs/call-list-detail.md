# 상담 목록·상세 리서치 — `GET /api/calls`, `GET /api/calls/{id}`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-01 상담 목록·검색(정체 `stale` 필터 제외), W-02 상담 상세 — 관련: C-03(완료), C-04·C-05(미착수), R-11 |
| 근거 | `docs/prd.md` §5.6·§6, `research.md` v0.2 §4·§5, `architecture.md` v0.3 §3·§5·§6·§7·§12·§13, `back_stack.md` v0.1, `features.md` v0.2, `api/convention.md` v0.1, `researchs/api-convention.md`, `plans/api-convention.md`, `backend/app/**`, `backend/tests/**`, `backend/.venv`, 원격 브랜치 `origin/front`(프론트 초안) |
| 검증 방법 | 문서·코드 정독, `.venv` 설치 버전 확인, 로컬 Docker/PostgreSQL 사용 가능 여부 확인 (레포 코드는 수정하지 않음) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다.

---

## 0. 요약 (핵심 발견)

1. **DB 계층이 전혀 없다.** `app/models/`·`app/repositories/`·`app/services/`는 빈 `__init__.py`뿐이고, `alembic/`에는 `.gitkeep`만 있다(`alembic.ini`·`env.py` 없음). `Settings`에 `database_url`이 없고(`app/core/config.py:10-35`), 엔진·세션·`api/deps.py`도 없다. W-01·W-02는 모델·세션·테스트 픽스처를 모두 임시로 마련해야 한다.
2. **동기 SQLAlchemy + psycopg 3**가 정해진 스택이다(`back_stack.md:53`, `:97-99`). 설치 버전: SQLAlchemy 2.0.58, psycopg 3.3.9, Alembic 1.20.1, testcontainers 4.15.0, FastAPI 0.165.0, Pydantic 2.14.4. async 드라이버(asyncpg)는 없다.
3. **이 PC에는 Docker가 없다.** `docker` 명령 없음, `C:\Program Files\Docker` 없음, WSL 배포판도 없는 상태(`wsl -l -v`가 사용법만 출력). 로컬 PostgreSQL 설치도 없다. 따라서 C-05가 전제한 testcontainers 통합 테스트를 현재 그대로는 실행할 수 없다(§5).
4. **응답 형식은 C-03에서 대부분 확정됐다.** `Page[T]`·`PageParams`(`app/schemas/common.py:96-112`), `KstDatetime`(`:31-35`), 정렬 `sort=-created_at` 허용 목록·`id` 동순위·`NULLS LAST`(`convention.md:115-118`), 다중 값 반복 파라미터·기간 `from`/`to` KST 하루 단위(`convention.md:120-123`), 상세의 `transcript`·`analysis` null·로그 `[]`(`convention.md:135`), 소프트 삭제 → 404(`architecture.md:401`).
5. **§4.1 DDL에는 키워드 검색용 `pg_trgm` GIN 인덱스와 `CREATE EXTENSION`이 없다.** 인덱스는 `architecture.md:359`에만 있다(`analysis.question_summary`, `analysis.action_summary`, `transcript.corrected_text`). 또 `CHECK` 제약(`back_stack.md:89`)과 FK `ON DELETE` 규칙도 DDL에 없다.
6. **`category` 저장 값이 문서끼리 다르다.** DDL 주석은 한글 값(`research.md:195`), API 규약은 영문 코드(`convention.md:144`). 목록 필터 구현이 저장 값에 직접 의존한다.
7. **프론트 초안(`origin/front`, 미병합)이 이미 목록·상세 응답 형태를 가정하고 있다**(`frontend/src/api/types.ts`). 상세의 로그 키는 `processing_log`, 목록·상세 모두 `is_stale` 포함, 담당자·고객사는 **정확히 일치**(선택 상자), 키워드는 요약·조치·전사 발화를 검색한다.
8. **`is_stale`은 규약상 목록 항목 필드**인데(`convention.md:149`) 이번 범위에서 `stale` 필터는 빠진다. 필드를 지금 넣을지가 열린 결정이다(§7 결정 4).
9. 한글 2글자 검색어(`환불`, `해지`)는 `pg_trgm` 트라이그램이 만들어지지 않아 GIN 인덱스를 쓰지 못한다. 데이터 규모(일 수십~백여 건, `prd.md:248`)에서는 순차 스캔으로도 PRD 2초 기준(`prd.md:247`)에 여유가 있다(§4).
10. 접근 로그는 쿼리 문자열을 남기지 않는다(`app/core/middleware.py:59`가 `scope["path"]`만 기록) → 규약의 "`q`는 로그에 남기지 않는다"(`convention.md:123`)를 이미 만족한다. 상세 조회는 `bind_call_id`(`app/core/logging.py:55`)로 `call_id`를 로그에 붙일 수 있다.

---

## 1. 현재 상태

### 1.1 코드 구조
| 위치 | 상태 | 근거 |
|---|---|---|
| `app/main.py` | `create_app(settings)` 팩토리, 라우터 등록 없음. 앱 단위 `responses`(422·500), operationId = 함수 이름 | `app/main.py:22-54` |
| `app/core/config.py` | `max_upload_mb`, `cors_origins`, `log_level`, `docs_enabled`만 있음. `extra="ignore"`, `env_file=".env"` | `config.py:10-35` |
| `app/core/errors.py` | `ErrorCode`(12개), `AppError`, 핸들러. `NOT_FOUND`=404 "대상을 찾을 수 없습니다." | `errors.py:12-24`, `:32`, `:58-70` |
| `app/core/logging.py` | `bind_call_id(request, call_id)` | `logging.py:55-58` |
| `app/core/middleware.py` | 접근 로그에 `path`·`call_id`만 기록(쿼리 문자열 없음) | `middleware.py:56-62` |
| `app/schemas/common.py` | `KstDatetime`, `ErrorResponse`, `error_responses()`, `Page[T]`, `PageParams` | `common.py:31-112` |
| `app/api/web/`, `app/api/robot/` | 빈 패키지. `api/deps.py` 없음 | — |
| `app/models/`, `app/repositories/`, `app/services/` | 빈 패키지 | — |
| `alembic/` | `.gitkeep`만. `alembic.ini` 없음 | — |
| `scripts/export_openapi.py` | `create_app(Settings(_env_file=None)).openapi()` → `docs/api/openapi.json` | `export_openapi.py:16-25` |
| `docs/api/openapi.json` | `"paths": {}` (라우트 없음) | — |
| `.env.example` | `DATABASE_URL=postgresql+psycopg://callcenter:callcenter@localhost:5432/callcenter`, `STALE_THRESHOLD_MIN=30` | `.env.example` |
| `deploy/docker-compose.dev.yml` | `postgres:16`, 사용자·DB `callcenter`, 5432 노출 | — |

### 1.2 테스트 구조
| 위치 | 내용 |
|---|---|
| `tests/unit/conftest.py` | `_build_test_app(**overrides)`로 `.env` 영향 없이 앱 생성 + 테스트 전용 라우트(`/echo`, `/items`, `/calls/{call_id}` 등). 픽스처 `build_app`, `client` (`conftest.py:21-64`) |
| `tests/unit/test_openapi.py` | 커밋된 `openapi.json` 최신 여부(`:146-152`), operationId 고유성(`:139-143`), 422·500 문서화(`:63-67`) → **라우트를 추가하면 `openapi.json`을 재생성해 같은 PR에 넣어야 한다** |
| `tests/integration/` | 빈 `__init__.py`만 |
| `pyproject.toml` | `markers = ["integration: 실제 PostgreSQL(testcontainers)이 필요한 테스트"]`, `--strict-markers` (`pyproject.toml` `[tool.pytest.ini_options]`) |

주의: `tests/unit/conftest.py`에 이미 `GET /calls/{call_id}` 테스트 라우트가 있다(경로가 `/api/calls/...`가 아니어서 실제 라우트와 충돌하지 않음).

### 1.3 의존성 (`pyproject.toml`, `.venv` 실측)
| 패키지 | 버전 | 비고 |
|---|---|---|
| sqlalchemy | 2.0.58 | `ColumnOperators.icontains(..., autoescape=True)` 사용 가능(2.0 신규, 실측 `True`) |
| psycopg / psycopg-binary | 3.3.9 | URL 스킴 `postgresql+psycopg://`. `TIMESTAMPTZ` → aware `datetime` |
| alembic | 1.20.1 | 설정 파일 없음 |
| testcontainers | 4.15.0 (+ `docker` 7.2.0) | dev 그룹. Docker 데몬 필요 |
| pytest / httpx | 9.2.0 / 0.28.1 | |

async 드라이버·`sqlalchemy[asyncio]`는 없다. `back_stack.md:53` "동기(def) 엔드포인트 + 동기 SQLAlchemy 세션"과 일치.

### 1.4 브랜치
- 현재 `feat/call-list-detail`(main = `9a830a7`, C-02·C-03 병합 완료).
- `origin/front`: 프론트 초안(커밋 `a8e1c76`, `4f06f4e` "API 규약 v0.1에 맞춰 프론트엔드 수정"), main 미병합. `features_frontend.md`, `frontend/src/api/types.ts`, `frontend/src/mocks/handlers.ts`에 목록·상세 가정이 있다(§2.3).

---

## 2. 요구사항 정리

### 2.1 출처별 요구
| 출처 | 내용 |
|---|---|
| PRD WEB-02 (`prd.md:168`) | 상담 목록: 기간·유형·담당자·고객사·처리 상태·키워드 조건별 조회 (P0) |
| PRD WEB-03 (`prd.md:169`) | 상담 상세: 요약, 조치 이력, 화자 분리 전사 원문, 원본 음성 재생 (P0). 음성 재생은 W-06 별도 |
| PRD WEB-05 (`prd.md:171`) | 처리 상태 모니터링(폴링), 정체 건 경고 — 같은 목록 API를 폴링으로 사용 |
| PRD 성능 (`prd.md:247`) | 대시보드 조회 응답 2초 이내 |
| PRD 규모 (`prd.md:248`) | 일 수십~백여 건 [가정] → 연 수만 행 |
| W-01 (`features.md:78`) | 기간·유형·담당자·고객사·상태·키워드(`pg_trgm`), `metadata_incomplete`, (`stale`은 R-11 후), 페이지네이션·정렬, 소프트 삭제 제외. 선행 C-03·C-04·C-05 |
| W-02 (`features.md:79`) | call + transcript + analysis + processing_log 묶어 반환. 선행 C-04·C-05 |
| 진행 순서 (`features.md:161`) | 2단계에 "W-01 목록·검색(정체 필터 제외), W-02 상세" |
| API 목록 (`research.md:268-269`) | 쿼리 `from,to,category,agent,client,status,q,stale,metadata_incomplete,page,size,sort`; 상세 = call + transcript + analysis + logs |
| 권한 (`architecture.md:67`, `:379`) | 웹 API는 인증 없음(네트워크 수준 통제). 엔드포인트 단위 권한 검사 없음 |
| 계층 규칙 (`architecture.md:95-100`) | Router: 파싱·검증·직렬화, DB 직접 접근 금지 / Service: 트랜잭션 / Repository: 쿼리, **소프트 삭제 필터 기본 적용** |
| 파일 위치 (`architecture.md:113-126`) | `api/deps.py`(DB 세션·서비스 주입), `api/web/calls.py`, `schemas/call.py` 등, `services/call_service.py`(웹 조회·수정·삭제·재처리) |

### 2.2 C-03 규약 중 W-01·W-02에 적용되는 것
| 규칙 | 근거 | W-01·W-02 적용 |
|---|---|---|
| snake_case | `convention.md:18` | 쿼리·응답 필드 |
| 목록 200 `Page[...]`, 에러 422 | `convention.md:41` | `def list_calls(...) -> Page[CallListItem]` |
| 상세 200, 에러 404 | `convention.md:42` | `responses=error_responses(ErrorCode.NOT_FOUND)` |
| 식별자 키 | `convention.md:60` | 목록·상세 항목은 `id` |
| `page` 1~10000, `size` 1~100(기본 20), 범위 밖 페이지 → 빈 `items` + 실제 `total`, `total`은 별도 COUNT | `convention.md:109-111` | `PageParams` 그대로 사용 |
| 소프트 삭제 제외 | `convention.md:112` | 목록·상세 모두 |
| 정렬: `sort`, `-` 접두사, 허용 `call_datetime`·`created_at`·`status_changed_at`, 기본 `-created_at`, 마지막에 같은 방향 `id`, `call_datetime`은 방향과 무관하게 `NULLS LAST` | `convention.md:115-118` | `Literal` 허용 목록 → 밖이면 422 |
| 다중 값: 반복 파라미터 | `convention.md:121` | `status` (및 필요 시 `category`) |
| 기간: `from`·`to` 날짜, KST 하루 단위, `to` 포함, 기준 `call_datetime`, NULL은 기간 필터에 안 걸림, `Query(alias="from")` | `convention.md:122` | |
| `q`는 로그 금지 | `convention.md:123` | 접근 로그는 이미 path만 기록 |
| 시각 응답 초 단위 `+09:00`, 응답 모델 시각 필드는 `KstDatetime`, `model_construct()` 금지 | `convention.md:128-131` | `call_datetime`, `status_changed_at`, `created_at`, 로그 `created_at` |
| null 유지, 상세 `transcript`·`analysis` null, 로그 `[]` | `convention.md:134-135` | |
| enum 영문 상수, OpenAPI `enum` 노출 | `convention.md:139-147` | `status`, `category`, `action_status`, `source_type`, `speaker` |
| `is_stale`(서버 계산), `stale` 필터 | `convention.md:149` | 이번 범위 처리 방식 결정 필요 |
| `Decimal` 금지, `confidence`는 `float` | `convention.md:152` | `NUMERIC(4,3)` → `float` 변환 |
| 요청·응답 모델 분리, `Page[CallListItem]` | `convention.md:156-157` | 스키마 이름 `Page_CallListItem_` |
| `object_key` 응답 금지 | `convention.md:160` | |
| `openapi.json` 재생성·같은 PR | `convention.md:164` | |
| operationId = 함수 이름, 태그 `calls` | `convention.md:166-167` | `list_calls`, `get_call` |
| 에러는 `AppError`로만 | `convention.md:97` | 404는 `AppError(ErrorCode.NOT_FOUND)` |

`plans/api-convention.md:36`: "기간 필터 → KST 경계 시각 변환 함수, 정렬 파라미터 파서는 첫 사용처 W-01이 규약대로 구현" — 즉 이 두 기능은 W-01 범위다.
`plans/api-convention.md:35`: `CallStatus`·`Category` 등 도메인 enum은 C-04/R-02, W-03·R-07 몫으로 미뤄져 있다 → W-01이 먼저 필요로 한다.

### 2.3 프론트 초안의 가정 (`origin/front`, 참고용)
`frontend/src/api/types.ts` 머리말에 "[확인 필요] 목록 항목 필드(CallListItem), 상세 응답의 구조와 로그의 이름(processing_log), 상세 응답에도 is_stale이 있는지"가 미확정으로 적혀 있다.

| 타입 | 필드 |
|---|---|
| `CallBase` | `id`, `source_type`, `original_name`, `duration_sec`, `agent_name`, `client_company`, `call_datetime`, `metadata_incomplete`, `status`, `status_changed_at`, `retry_count`, `is_stale` |
| `CallListItem` | `CallBase` + `category`, `question_summary`, `action_status` (분석 없으면 null) |
| `CallDetail` | `CallBase` + `transcript: {segments} \| null`, `analysis: {category, confidence, question_summary, action_summary, follow_up_required, action_status, entities, needs_review} \| null`, `processing_log: [{step, status, message, created_at}]` |
| `CallListParams` | `from`, `to`, `category`(단일), `agent`, `client`, `status`(단일 또는 배열), `q`, `stale`, `metadata_incomplete`, `page`, `size`, `sort` |

목 서버(`frontend/src/mocks/handlers.ts`)의 동작
- `agent`·`client`·`category`: **정확히 일치**. 담당자·고객사 선택지는 통계 분류 응답의 이름에서 가져온다(`CallsPage.tsx` `useNames`, `features_frontend.md` FE-09).
- `q`: `question_summary` + `action_summary` + 전사 `segments[].text`를 이어 붙여 부분 일치.
- 정렬 기본 `-created_at`, 밖의 값 422, NULL은 뒤로.
- 모니터링 화면은 `status`를 5개 반복, `size=100`, `sort=-status_changed_at`, 5초 폴링(`calls.ts` `MONITOR_PARAMS`).
- 상세의 처리 로그는 오래된 것부터 표시 가정(`CallDetailPage.tsx:96`).

> 프론트 초안은 확정 계약이 아니다. 백엔드가 `openapi.json`을 내면 프론트가 그것에 맞춘다(`convention.md:12`). 다만 차이가 생기는 지점은 프론트에 알려야 한다.

---

## 3. 데이터 모델 (`research.md` §4.1)

### 3.1 테이블 정의 요약
`call_record` (`research.md:156-179`)
| 컬럼 | 타입 | NULL | 기본값 | 목록 | 상세 | 비고 |
|---|---|---|---|---|---|---|
| `id` | BIGSERIAL PK | N | | ✅ `id` | ✅ | |
| `source_type` | VARCHAR(20) | N | | ✅ | ✅ | `DRIVE`/`WEB` |
| `source_ref` | TEXT | Y | | — | △ | Drive 파일 ID. 노출 필요성 낮음 |
| `object_key` | TEXT | N | | ✗ | ✗ | 응답 금지(`convention.md:160`) |
| `original_name` | TEXT | N | | ✅ | ✅ | |
| `file_hash` | CHAR(64) | N | | — | △ | 화면 용도 없음 |
| `file_size` | BIGINT | Y | | — | △ | |
| `duration_sec` | INT | Y | | ✅ | ✅ | |
| `agent_name` | VARCHAR(50) | **Y** | | ✅ | ✅ | 필터 `agent` |
| `client_company` | VARCHAR(100) | Y | | ✅ | ✅ | 필터 `client` |
| `call_datetime` | TIMESTAMPTZ | **Y** | | ✅ | ✅ | 기간 필터·정렬(`NULLS LAST`) |
| `metadata_incomplete` | BOOLEAN | N | false | ✅ | ✅ | 필터 |
| `status` | VARCHAR(20) | N | 'REGISTERED' | ✅ | ✅ | 필터(다중) |
| `status_changed_at` | TIMESTAMPTZ | N | now() | ✅ | ✅ | 정렬, 정체 판단 |
| `retry_count` | INT | N | 0 | ✅ | ✅ | |
| `queue_item_id` | BIGINT | Y | | — | △ | 로봇 내부 값 |
| `deleted_at` | TIMESTAMPTZ | Y | | ✗ | ✗ | `IS NULL` 조건 |
| `created_at` | TIMESTAMPTZ | N | now() | ✅ | ✅ | 기본 정렬 |
| `updated_at` | TIMESTAMPTZ | N | now() | — | △ | |

인덱스: `ux_call_hash UNIQUE(file_hash) WHERE deleted_at IS NULL`, `ix_call_dt(call_datetime)`, `ix_call_status(status, status_changed_at)` (`research.md:177-179`).

`transcript` (`research.md:182-189`): `id`, `call_id` BIGINT NOT NULL **UNIQUE** FK, `segments` JSONB NOT NULL(`[{speaker, start, end, text}]`, PII 마스킹 후), `corrected_text` TEXT NULL(GenAI 교정본, STT-05 P1), `stt_engine` VARCHAR(50), `created_at`. → call과 1:0..1.

`analysis` (`research.md:192-208`): `id`, `call_id` UNIQUE FK, `category` VARCHAR(20) NOT NULL, `confidence` NUMERIC(4,3), `question_summary` TEXT, `action_summary` TEXT, `follow_up_required` BOOLEAN DEFAULT false(**NULL 허용**), `action_status` VARCHAR(20) DEFAULT 'OPEN'(**NULL 허용**), `entities` JSONB, `raw_json` JSONB NOT NULL, `prompt_version`, `needs_review` BOOLEAN DEFAULT false(NULL 허용), `created_at`, `updated_at`. 인덱스 `ix_analysis_cat(category)`. → 1:0..1.

`processing_log` (`research.md:211-219`): `id`, `call_id` FK **NULL 허용**, `step` VARCHAR(30)(`REGISTER|QUEUE|STT|GENAI|STORE|EXCEL|CRM|RETRY`), `status` VARCHAR(20)(`SUCCESS|FAIL|RETRY`), `message` TEXT, `orchestrator_job_id`, `created_at`. **`call_id` 인덱스 없음.** → 1:N.

`edit_history` (`research.md:222-230`): W-01·W-02에서 사용하지 않음(FE-18 미정).

### 3.2 DDL에 빠져 있거나 문서 간 다른 것
| 항목 | 내용 | 영향 |
|---|---|---|
| `pg_trgm` | `CREATE EXTENSION pg_trgm`과 GIN 인덱스가 DDL에 없음. `architecture.md:359`에만 대상 컬럼 명시 | 임시 모델/테스트 스키마에 직접 넣어야 함. C-04 마이그레이션에서 확장 생성 필요 |
| `CHECK` 제약 | `back_stack.md:89` "VARCHAR + CHECK"인데 DDL에 없음 | 임시 모델에 넣을지 선택 |
| `category` 값 | DDL 주석 한글(`research.md:195`) vs API 영문 코드(`convention.md:144`), 변환 위치 미정(`plans/api-convention.md:648`) | 필터 값 → DB 값 변환 필요 여부 |
| `processing_log.call_id` 인덱스 | 없음 | 상세 조회 시 로그 조회가 순차 스캔. 90일 정리(`architecture.md:367`)로 규모는 작음 → C-04에 인덱스 제안 가능 |
| analysis 불리언 NULL 허용 | `follow_up_required`·`action_status`·`needs_review` | 응답 모델이 `bool`이면 NULL에서 검증 실패 → 모델은 `bool \| None` 또는 C-04에서 NOT NULL 제안 |
| `updated_at` 자동 갱신 | "ORM에서 자동 갱신"(`back_stack.md:91`) | 조회 기능에는 영향 없음 |
| PRD `edit_history` 컬럼명 | PRD는 `before/after`(`prd.md:189`), DDL은 `before_val/after_val` | 이번 범위 밖 |

### 3.3 목록·상세 응답 매핑 (후보)
목록 항목 `CallListItem` = `call_record`의 표시용 컬럼 + `analysis`의 `category`, `question_summary`, `action_status` (LEFT JOIN, 분석 없으면 null). 프론트 초안과 같다.

상세 `CallDetail` = `call_record` 표시용 컬럼 + `transcript`(null 가능) + `analysis`(null 가능) + `processing_log`(배열, `created_at`·`id` 오름차순).

노출 제외 후보: `object_key`(규약상 금지), `raw_json`(GenAI 원본, 크기 크고 화면 용도 없음), `file_hash`·`source_ref`·`queue_item_id`·`orchestrator_job_id`(내부 값). 노출은 호환 변경이므로 나중에 추가 가능(`convention.md:22`) → 처음엔 최소로 두는 편이 안전하다.

`transcript`에 `corrected_text`·`stt_engine`을 포함할지, `analysis`에 `prompt_version`을 포함할지는 화면 요구가 없다(프론트 초안은 `segments`만 사용). `segments` 항목 구조는 E-03(A 담당, GenAI·STT 파트 합의) 미확정 → 응답 모델을 엄격한 `Segment` 모델로 할지, `list[dict]`로 둘지 선택 필요(§7 #7).

---

## 4. 키워드 검색 (`pg_trgm`)

### 4.1 대상 컬럼
| 출처 | 대상 |
|---|---|
| `research.md:241` | `question_summary`, `action_summary`, `corrected_text` 부분 일치 |
| `architecture.md:359` | GIN: `analysis(question_summary)`, `analysis(action_summary)`, `transcript(corrected_text)` |
| 프론트 목 (`handlers.ts`) | `question_summary`, `action_summary`, `segments[].text` |

차이: 문서는 `corrected_text`, 프론트는 `segments` 텍스트. `corrected_text`는 GenAI 교정본이며 STT-05(P1, `prd.md:129`) — 교정 단계가 없으면 NULL로 남아 전사 검색이 되지 않는다. `segments`는 JSONB라 trgm 인덱스를 바로 걸 수 없다.

선택지
| 안 | 방법 | 장점 | 단점 |
|---|---|---|---|
| A | 3개 컬럼(`question_summary`, `action_summary`, `corrected_text`) ILIKE | 문서와 일치, 인덱스 대상과 같음 | `corrected_text`가 NULL이면 전사 미검색 |
| B | A + `segments::text` ILIKE | 전사 원문까지 검색 | JSON 키(`speaker`, `AGENT`, `text`)까지 검색됨(`q=text` 같은 오탐), 인덱스 불가(표현식 인덱스는 가능하나 C-04 범위) |
| C | A + 전사 적재(R-06) 때 `segments` 텍스트를 이어 붙인 컬럼(예: `full_text`)을 저장 | 정확, 인덱스 가능 | 스키마 변경 → A(C-04·R-06)와 합의 필요 |
| D | 요약 2개만 | 가장 단순·빠름 | 전사 검색 불가, 문서와 다름 |

### 4.2 매칭 방식
| 방식 | 의미 | 평가 |
|---|---|---|
| `ILIKE '%q%'` | 부분 일치. `gin_trgm_ops` 인덱스가 LIKE/ILIKE를 지원 | 사용자가 기대하는 "포함 검색", 결과가 결정적 → **권장** |
| `similarity()` / `%` 연산자 | 유사도(기본 임계 0.3) | 짧은 검색어·긴 본문 사이 유사도가 낮아 누락이 많음, 결과 설명이 어려움. 정렬 기준(관련도)과도 규약이 안 맞음 |
| `word_similarity()` / `<%` | 단어 단위 유사도 | 오타 허용이 필요할 때 검토. 현재 요구 없음 |

SQLAlchemy 2.0: `column.icontains(q, autoescape=True)` → `lower(col) LIKE lower('%' || q || '%') ESCAPE '/'`로 렌더링되며 `%`·`_`를 자동 이스케이프한다. PostgreSQL 방언에서는 `ilike`로 나간다. 검색어의 `%`·`_`를 그대로 넘기면 와일드카드로 동작하므로 이스케이프는 필요하다.

### 4.3 인덱스·성능 고려
- `pg_trgm`은 문자열을 3글자 조각(트라이그램)으로 나눈다. `LIKE '%환불%'`처럼 **검색어가 2글자 이하**면 추출되는 트라이그램이 없어 GIN 인덱스가 전체 스캔으로 떨어진다(PostgreSQL 문서 pgtrgm "Index Support"). 한국어 검색어는 2음절이 흔하다.
- 한글을 "글자"로 인식하는지는 DB의 `LC_CTYPE`에 따른다. `C` 로캘에서는 비ASCII 문자가 단어 문자로 인식되지 않아 트라이그램이 만들어지지 않을 수 있다(인덱스 효과 없음, 결과 정확성은 ILIKE 재검사로 유지) **[확인 필요]**. 공식 `postgres:16` 이미지는 기본 `en_US.utf8`로 초기화된다.
- 3개 컬럼을 OR로 묶고 두 테이블을 LEFT JOIN 하면 플래너가 BitmapOr로 GIN을 쓰기 어렵다. 규모(연 수만 행)에서는 순차 스캔 + ILIKE로도 수십 ms 수준이라 PRD 2초(`prd.md:247`)에 여유가 있다 **[가정: 실측 전]**.
- 결론: 인덱스는 C-04(A) 마이그레이션 대상이며, W-01은 인덱스 유무와 관계없이 같은 쿼리(ILIKE)로 동작한다. W-01의 임시 테스트 스키마에서는 `CREATE EXTENSION pg_trgm`만 하고 인덱스는 넣어도 되고 안 넣어도 결과가 같다.

### 4.4 입력 규칙 후보
- 앞뒤 공백 제거, 빈 문자열이면 필터 없음.
- 최대 길이(예: 100자) 초과 시 422 — 긴 문자열 LIKE 남용 방지. 최소 길이는 두지 않음(1글자 검색도 허용, 규모상 문제 없음).
- 공백으로 나뉜 여러 단어: 전체를 하나의 부분 문자열로 볼지(AND 분할 없음) — 프론트 목과 같고 단순.
- 검색어는 로그·에러 `detail`에 넣지 않는다(`convention.md:98`, `:123`).

### 4.5 쿼리 스케치 (설명용)
```python
stmt = (
    select(CallRecord, Analysis.category, Analysis.question_summary, Analysis.action_status)
    .outerjoin(Analysis, Analysis.call_id == CallRecord.id)
    .where(CallRecord.deleted_at.is_(None))
)
if q:
    stmt = stmt.outerjoin(Transcript, Transcript.call_id == CallRecord.id).where(
        or_(
            Analysis.question_summary.icontains(q, autoescape=True),
            Analysis.action_summary.icontains(q, autoescape=True),
            Transcript.corrected_text.icontains(q, autoescape=True),
        )
    )
total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
```
- `transcript`·`analysis`는 `call_id` UNIQUE라 JOIN으로 행이 늘지 않는다 → `COUNT` 정확, `DISTINCT` 불필요.
- `category` 필터는 `Analysis.category.in_(...)` → 분석 없는 건은 자연스럽게 제외.

---

## 5. 테스트 전략

### 5.1 실행 환경 확인 결과 (2026-11-24, 이 개발 PC)
| 항목 | 결과 |
|---|---|
| `docker version` | `docker: command not found` |
| Docker Desktop | `C:\Program Files\Docker` 없음 |
| WSL | `wsl -l -v`가 사용법만 출력 → 설치된 배포판 없음으로 보임 |
| 로컬 PostgreSQL | `C:\Program Files\PostgreSQL` 없음, `psql` 없음 |
| testcontainers 패키지 | 설치됨(4.15.0) — 데몬이 없어 실행 불가 |

### 5.2 선택지
| 안 | 방법 | pg_trgm·TIMESTAMPTZ 동작 | 비용·위험 |
|---|---|---|---|
| A. Docker Desktop 설치 + testcontainers | C-05 설계 그대로 | 운영과 동일(`postgres:16`) | WSL2·관리자 권한 필요. C-05와 바로 호환 |
| B. 로컬 PostgreSQL 16 설치 + `TEST_DATABASE_URL` | 테스트 픽스처가 환경 변수 URL에 연결 | 동일(설치 시 로캘 `Korean_Korea.949`/UTF8 인코딩 확인 필요) | Windows 설치 프로그램. pg_trgm은 contrib로 기본 포함 |
| C. `pgserver`(pip, PostgreSQL 바이너리 내장) | dev 의존성 추가 후 임시 디렉터리에 서버 기동 | PyPI에 `pgserver 0.1.4` cp312 `win_amd64` 휠 존재(확인). **pg_trgm 포함 여부·동작은 미검증**(스크래치 실행 권한이 없어 확인 못 함) | 비공식 패키지, 유지보수 불확실. C-05 방식과 다름 |
| D. SQLite | 인메모리 | `pg_trgm` 없음, ILIKE는 `lower() LIKE`로 흉내, TIMESTAMPTZ는 naive 저장, JSONB 없음, partial unique index 차이 | 실제 동작과 달라 **목록·검색 검증 목적에 부적합** |
| E. DB 없이 리포지토리 목(mock) | 서비스·라우터만 단위 테스트 | 쿼리 자체는 검증 안 됨 | 필터·정렬·KST 경계·NULLS LAST가 핵심 로직이라 효용 낮음 |

### 5.3 C-05와 충돌을 줄이는 픽스처 형태 (후보)
- 위치: `tests/integration/conftest.py`(현재 비어 있음). 마커 `integration` 사용(이미 등록됨).
- DB 결정 순서: `TEST_DATABASE_URL` 환경 변수가 있으면 그 DB 사용 → 없으면 testcontainers `PostgresContainer("postgres:16", driver="psycopg")` → 둘 다 불가하면 `pytest.skip`. A·B 어느 환경에서도 같은 테스트가 돈다.
- 스키마 생성을 함수 하나로 감싼다: 지금은 `CREATE EXTENSION IF NOT EXISTS pg_trgm` + `Base.metadata.create_all(engine)`, C-04 이후에는 `alembic upgrade head`로 교체 → 교체 지점이 한 곳.
- 격리: 테스트마다 연결 단위 트랜잭션을 열고 끝에 롤백(SQLAlchemy 2.0 `Session(bind=connection, join_transaction_mode="create_savepoint")`)하거나, 테스트마다 `TRUNCATE ... RESTART IDENTITY CASCADE`. 조회 전용 기능이라 어느 쪽이든 충분.
- 앱 연결: `app.dependency_overrides[get_session]`으로 테스트 세션 주입. `create_app(Settings(_env_file=None, database_url=...))` 패턴(`tests/unit/conftest.py:21-23`)과 맞춘다.
- 테스트 데이터: C-05 팩토리가 없으므로 최소한의 헬퍼(`make_call(session, **overrides)`) → C-05 팩토리로 교체. 헬퍼 이름·기본값을 C-05 담당과 맞추면 교체가 쉽다.
- 시각: 테스트 데이터는 aware 값만 사용(`datetime(2026, 11, 23, 23, 59, tzinfo=KST)` 등). KST 경계(`to` 당일 23:59:59 포함, 다음날 00:00 제외), `call_datetime` NULL 제외, NULLS LAST, `id` 동순위 정렬이 핵심 테스트 케이스.

### 5.4 단위 테스트로 가능한 부분
DB 없이 검증 가능한 것: 쿼리 파라미터 검증(422: `sort` 허용 목록 밖, `size>100`, `page=0`, 잘못된 enum, 날짜 형식), `from`/`to` → KST 경계 시각 변환 함수, 정렬 파서, 응답 모델 직렬화(`+09:00`, `confidence` float), OpenAPI 스키마(`Page_CallListItem_`, `from` 별칭, `NOT_FOUND` 문서화). 라우터 단위 테스트는 세션 의존성을 `dependency_overrides`로 가짜로 바꿔 두면 DB 없이도 422 경로를 확인할 수 있다(FastAPI는 쿼리 검증과 의존성 해결을 같은 단계에서 하므로, 실제 세션 의존성이 연결을 시도하지 않도록 바꿔 두는 편이 안전).

---

## 6. 파라미터·응답 설계 상세

### 6.1 `GET /api/calls` 쿼리
| 파라미터 | 타입(후보) | 규칙 | 근거 |
|---|---|---|---|
| `from`, `to` | `date \| None`, `Query(alias="from")` | KST `from 00:00 ≤ call_datetime < (to+1) 00:00`. 하나만 와도 동작 | `convention.md:122` |
| `category` | `list[Category] \| None` 또는 `Category \| None` | 반복 파라미터, 영문 코드 | `convention.md:121`, `:144` |
| `agent` | `str \| None` | 정확히 일치(후보) | 프론트 선택 상자 |
| `client` | `str \| None` | 정확히 일치(후보) | 〃 |
| `status` | `list[CallStatus] \| None` | 반복 파라미터 | `convention.md:121` |
| `q` | `str \| None` (`max_length`) | §4.4 | |
| `metadata_incomplete` | `bool \| None` | `true`/`false` 모두 허용 | `features.md:78` |
| `stale` | — | **이번 범위 제외**(R-11 이후) | 지시 범위 |
| `page`, `size` | `PageParams` | `Depends(PageParams)` | `common.py:103-112` |
| `sort` | `Literal["call_datetime", "-call_datetime", "created_at", "-created_at", "status_changed_at", "-status_changed_at"]`, 기본 `"-created_at"` | `id` 같은 방향 보조 정렬, `call_datetime` NULLS LAST | `convention.md:115-118` |

- FastAPI에서 `list[...]` 쿼리는 `Annotated[list[CallStatus] | None, Query()] = None`으로 선언해야 반복 파라미터로 인식된다(`researchs/api-convention.md:177` 실측).
- 필터 묶음은 `PageParams`처럼 `@dataclass` + `Depends()` 의존성으로 두면 라우터 시그니처가 짧고 서비스에 그대로 넘기기 좋다. 단 dataclass 필드에 `Query(alias="from")`를 쓸 때 OpenAPI 이름이 `from`으로 나오는지 구현 시 확인 필요.
- `from > to`: 규약에 규정 없음. 선택지 (a) 422 `VALIDATION_ERROR`(`detail.errors[].loc = ["query","from"]`) (b) 빈 결과. 통계·엑셀도 같은 규칙을 써야 하므로 한쪽으로 정해 규약에 추가하는 것이 좋다(§7 #8).
- 알 수 없는 쿼리 파라미터(예: 지금 `stale=true`를 보내는 경우)는 FastAPI가 무시한다 → 프론트가 `stale`을 보내도 에러가 나지 않고 필터가 적용되지 않는다. 프론트에 알려야 할 사항.

### 6.2 KST 경계 변환
```python
def kst_day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=KST)   # KST = app.schemas.common.KST
# from → kst_day_start(from_), to → kst_day_start(to + timedelta(days=1)) (미만)
```
psycopg 3는 aware `datetime`을 `timestamptz`로 정확히 바인딩한다. `KST` 상수는 이미 `app/schemas/common.py:12`에 있다.

### 6.3 정렬
```python
col = {"call_datetime": CallRecord.call_datetime, ...}[field]
order = [col.desc() if desc else col.asc()]
if field == "call_datetime":
    order[0] = order[0].nulls_last()
order.append(CallRecord.id.desc() if desc else CallRecord.id.asc())
```

### 6.4 `GET /api/calls/{id}`
- 경로 파라미터 이름: 규약 표는 `{id}`(`convention.md:42`). 함수 인자는 `call_id: int`로 받고 경로를 `/api/calls/{call_id}`로 두면 OpenAPI 경로 문자열이 `{call_id}`가 된다. 문서 표기와 맞추려면 경로를 `{id}`로 두고 `Path(alias=...)` 또는 인자명 `id`(파이썬 내장 이름 가림, Ruff `A002`는 현재 미선택) 중 선택. 프론트는 경로 문자열에 의존하지 않으므로 영향은 OpenAPI 표기뿐.
- 정수가 아닌 ID → 422 `VALIDATION_ERROR`(`loc: ["path", ...]`). 0·음수는 404로 둬도 무방(존재하지 않음).
- 없음 또는 `deleted_at IS NOT NULL` → `AppError(ErrorCode.NOT_FOUND)` → 404 `{code: "NOT_FOUND", message: "대상을 찾을 수 없습니다.", detail: null}` (`architecture.md:401`, `errors.py:32`). 삭제 여부를 구별해 알려 주지 않는다(같은 404).
- 하위 데이터 로드: call 1건 + transcript(0..1) + analysis(0..1) + logs(N). `selectinload`/`joinedload` 또는 쿼리 4개 모두 가능. 규모상 차이 없음.
- 로그 정렬: `created_at ASC, id ASC`(처리 순서대로). 프론트 초안도 오래된 것부터 가정.
- `bind_call_id(request, call_id)`로 접근 로그에 `call_id`를 남길 수 있다(`logging.py:55`). 404 건도 남길지 선택(남겨도 무방).
- `processing_log.call_id`가 NULL 허용이므로 call에 연결된 로그만 조회(`WHERE call_id = :id`).

### 6.5 계층 배치 (`architecture.md` §3 기준 후보)
| 파일 | 내용 |
|---|---|
| `app/core/config.py` | `database_url: str` 추가(`.env.example`에 이미 있음). 기본값을 둘지(개발용 URL) 필수로 할지 선택 — 필수로 하면 `scripts/export_openapi.py`·단위 테스트의 `Settings(_env_file=None)`이 실패하므로 기본값 또는 지연 연결이 필요 |
| `app/core/db.py` 또는 `app/db.py` | `create_engine`, `sessionmaker` (위치는 문서에 없음. `architecture.md:114`는 세션 주입만 `api/deps.py`) |
| `app/api/deps.py` | `get_session()` 의존성(요청당 세션, 종료 시 close) |
| `app/models/` | ORM 모델(§7 결정 1) |
| `app/schemas/call.py` | `CallStatus`, `Category`, `ActionStatus`, `SourceType` enum(StrEnum), `CallListQuery`, `CallListItem`, `CallDetail`, `TranscriptOut`, `AnalysisOut`, `ProcessingLogOut` |
| `app/repositories/call_repository.py` | 목록·건수·단건 조회, `deleted_at IS NULL` 기본 적용(`architecture.md:99`) |
| `app/services/call_service.py` | 목록·상세 유스케이스, 404 판단 |
| `app/api/web/calls.py` | `APIRouter(prefix="/api/calls", tags=["calls"])`, `list_calls`, `get_call` |
| `app/main.py` | `app.include_router(...)` |
| `docs/api/openapi.json` | 재생성 |

- 엔진 생성 시점: `create_app()`에서 엔진을 만들면 `export_openapi`·단위 테스트가 DB 없이도 동작해야 한다. SQLAlchemy `create_engine`은 연결을 지연하므로 생성만으로는 DB 접속이 일어나지 않는다. 그래도 `app.state`에 두고 `get_session`이 거기서 꺼내는 방식이 테스트 오버라이드에 유리하다.
- 상태 enum(`CallStatus`)을 만들면 `DuplicateFileDetail.status: str`를 `CallStatus`로 바꾸는 일이 생긴다(`plans/api-convention.md:96`, `:654` — A 담당 C-04/R-02 시점으로 넘겨져 있음). W-01에서 enum을 먼저 만들면 이 변경을 같이 할지, 그대로 둘지 정해야 한다(`openapi.json` 변경 동반).

---

## 7. 미결 사항 (선택지와 권장안)

**[핵심]** 표시는 다른 담당(A·프론트)에 영향을 주거나 되돌리기 어려운 결정이다.

| # | 항목 | 선택지 | 권장안 | 이유 |
|---|---|---|---|---|
| 1 | **[핵심]** 임시 모델의 위치·소유 | (a) `app/models/`에 §4.1 DDL 그대로 ORM 작성, C-04는 이 모델로 Alembic 초기 마이그레이션 작성(모델 공동 소유) (b) 테스트 전용 위치(`tests/`)에만 모델 두고 앱 코드는 Core `text()` 쿼리 (c) C-04 선행 대기 | **(a)**, 파일은 C-04가 만들 것으로 예상되는 이름에 맞추고(`app/models/base.py`, `app/models/call.py` 등) A 리뷰 | 리포지토리가 ORM 모델을 써야 하므로 (b)는 C-04 후 쿼리 재작성이 필요. (a)는 DDL과 1:1이면 C-04가 그대로 채택하거나 차이만 고치면 됨. 같은 파일을 두 브랜치가 새로 만들면 충돌하므로 **어느 쪽이 먼저 병합할지·파일 이름**을 A와 먼저 맞추는 것이 핵심 |
| 2 | **[핵심]** 테스트 DB 환경 | §5.2 A~E | **픽스처는 "`TEST_DATABASE_URL` → testcontainers → skip" 순서**, 개발 PC에는 **Docker Desktop 설치(A)** 또는 **로컬 PostgreSQL 16(B)** 중 하나 마련 | SQLite·목으로는 pg_trgm·KST 경계·NULLS LAST를 검증할 수 없음. 환경 변수 경로를 두면 Docker 없는 PC에서도 실행 가능하고, C-05(testcontainers)와도 그대로 호환 |
| 3 | **[핵심]** 키워드 검색 대상 | §4.1 A/B/C/D | **A(3개 컬럼 ILIKE, `icontains(autoescape=True)`)** + `corrected_text`가 비는 경우 대비책(C: 전사 텍스트 컬럼)은 A·GenAI 파트와 별도 합의 | 문서·인덱스 계획과 일치. `segments::text` 검색은 JSON 키 오탐. 전사 교정(STT-05)이 P1이라 `corrected_text`가 비면 전사 검색이 안 되는 점을 프론트에 알려야 함 |
| 4 | **[핵심]** `is_stale`·상세 응답 키 | (a) `is_stale` 생략, R-11 후 `stale` 필터와 함께 추가(호환 변경) (b) 지금 `STALE_THRESHOLD_MIN` 설정으로 간단 계산해 포함 (c) 항상 `false` | **(a)** + 상세의 로그 키는 **`processing_log`**(features·프론트 초안과 일치) | 정체 판단은 R-11(A) 소유라 지금 계산하면 로직이 두 곳에 생김. 필드 추가는 호환 변경(`convention.md:22`). (c)는 잘못된 정보. 단 프론트 초안 타입은 `is_stale`을 필수로 가정 → 프론트에 "R-11 이후 추가" 공지 필요 |
| 5 | `category` 저장 값 | DB 한글 / DB 영문 코드 | **DB도 영문 코드 + CHECK**, 한글→코드 변환은 적재(R-07) 시 | 필터·응답에 변환 계층이 필요 없음. 단 R-07·C-04(A) 결정 사항 → 임시 모델은 영문 코드로 두고 A와 확인 |
| 6 | 담당자·고객사 필터 | 정확히 일치 / 부분 일치(ILIKE) | **정확히 일치** | 프론트가 선택 상자(통계 분류 이름)로 보냄. 부분 일치는 키워드 검색과 역할이 겹침. 바꿔도 파라미터 형태는 같음 |
| 7 | 응답 필드 범위 | 최소(§3.3 ✅) / 전체 컬럼 | **최소** — `object_key`·`raw_json`·`file_hash`·`source_ref`·`queue_item_id`·`orchestrator_job_id` 제외. `segments`는 `Segment{speaker, start, end, text}` 모델 vs `list[dict]` 중 E-03 확정 전이면 `list[dict[str, Any]]` | 필드 추가는 호환, 삭제는 비호환. E-03 미확정 상태에서 엄격 모델은 적재 데이터와 어긋나면 500 위험 |
| 8 | `from > to` | 422 / 빈 결과 | **422 `VALIDATION_ERROR`**, 규약 §4.3에 한 줄 추가 | 사용자 실수를 드러냄. 통계·엑셀도 같은 규칙 |
| 9 | `category` 다중 값 | 단일 / 반복 파라미터(다중) | **반복 파라미터(다중)** | 규약의 다중 값 규칙과 일관, 단일 값 요청도 그대로 동작(프론트 영향 없음) |
| 10 | `q` 길이 | 제한 없음 / 최대 N | **최대 100자**, 공백 제거 후 빈 값은 무시 | 남용 방지, 422 `msg`에 입력값이 안 들어감(Pydantic `string_too_long`) |
| 11 | analysis 불리언 NULL | 응답 `bool \| None` / C-04에 NOT NULL 제안 | **C-04에 NOT NULL 제안**, 임시 모델은 NOT NULL + 기본값 | DDL이 DEFAULT만 있고 NULL 허용이라 응답 타입이 애매해짐 |
| 12 | `processing_log(call_id)` 인덱스 | 없음 / 추가 | **C-04에 추가 제안** | 상세마다 조회. 규모상 급하지 않음 |
| 13 | `CallStatus` enum 도입 시 `DuplicateFileDetail.status` | 같이 변경 / 그대로 | **그대로 두고 A(R-04)가 변경** | 범위 최소화, `plans/api-convention.md:654`의 넘김과 일치 |
| 14 | `database_url` 기본값 | 개발 URL 기본값 / 필수 | **`.env.example`과 같은 개발 URL 기본값** | `Settings(_env_file=None)`을 쓰는 기존 테스트·스크립트가 깨지지 않음. 운영은 `.env`로 덮음 |

---

## 8. 핵심 결정 후보

1. **임시 모델을 어디에 누가 두는가** (§7 #1, #5)
   - 선택지: (a) `app/models/`에 §4.1 DDL대로 작성하고 C-04는 이 모델로 마이그레이션만 작성 (b) 테스트 전용 모델 + 앱은 Core 쿼리 (c) C-04 완료까지 대기
   - 권장: **(a)**. 파일 이름·병합 순서를 A와 먼저 합의하고, `category`는 영문 코드로 저장하는 것을 함께 확인한다.
2. **테스트 DB를 어떻게 띄우는가** (§5, §7 #2)
   - 선택지: Docker Desktop + testcontainers / 로컬 PostgreSQL 16 + `TEST_DATABASE_URL` / `pgserver`(미검증) / SQLite(부적합)
   - 권장: **픽스처는 `TEST_DATABASE_URL` 우선, 없으면 testcontainers, 둘 다 없으면 skip**. 개발 PC에는 Docker Desktop 또는 PostgreSQL 16 중 하나를 설치한다(현재 둘 다 없음).
3. **키워드 검색 대상** (§4, §7 #3)
   - 선택지: 요약 2개 + `corrected_text` / + `segments::text` / + 전사 텍스트 컬럼 신설 / 요약 2개만
   - 권장: **요약 2개 + `corrected_text`를 ILIKE(`icontains(autoescape=True)`)로 검색**. `corrected_text`가 비는 경우는 A·GenAI 파트와 별도로 정한다.
4. **`is_stale`을 지금 응답에 넣는가** (§7 #4)
   - 선택지: 생략 후 R-11 때 추가 / 설정값으로 지금 계산 / 항상 false
   - 권장: **생략 후 R-11 때 `stale` 필터와 함께 추가**하고 프론트에 알린다. 상세의 로그 키는 `processing_log`로 한다.
