# 상담 목록·상세 상세 구현 계획 — `GET /api/calls`, `GET /api/calls/{call_id}`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-01 상담 목록·검색(정체 `stale` 필터 제외), W-02 상담 상세 |
| 작업 브랜치 | `cyj` (기준 `main` `cb46e02`, C-04 DB 스키마 병합 이후) |
| 근거 | `docs/researchs/call-list-detail.md` v0.1(이하 "리서치"), C-04 결과물(`app/models/*.py`, `alembic/env.py`, `alembic/versions/2026_11_24_1153-8c600ef00817_init_schema.py`), `research.md` §4.1, `architecture.md` v0.3 §3·§6·§7, `back_stack.md` §3.3·§3.4, `api/convention.md` v0.1, `plans/api-convention.md`, `plans/common-module.md`, `app/**`, `scripts/export_openapi.py`, `tests/**` |
| 기준 버전 | FastAPI 0.165.0 / pydantic 2.14.4 / SQLAlchemy 2.0.58 / psycopg 3.3.9 / Alembic 1.20.1 / testcontainers 4.15.0 |
| 사전 검증 | 이 문서의 코드·테스트를 `cb46e02` 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). ① Docker 없는 상태: `pytest` 기존 100 + 신규 단위 45 = **145 통과, 통합 18 skip**, `ruff check`·`ruff format --check`·`mypy .`(55파일) 통과 ② 통합: 검증용 임시 PostgreSQL 16.2(`pgserver`, 레포에 추가하지 않음)에 `TEST_DATABASE_URL`로 연결. 이 서버에는 `pg_trgm`이 없어 `alembic upgrade head`가 마이그레이션의 `CREATE EXTENSION pg_trgm`에서 멈춘다 — 그 직전까지(`downgrade base`, `env.py`의 `DATABASE_URL` 읽기·접속) 동작 확인. 쿼리 로직은 스키마 생성만 `create_all`(trgm 인덱스 제외)로 바꾼 변형으로 **163 전부 통과**. → `alembic upgrade head` 전체와 trgm 인덱스는 Docker(`postgres:16`)에서 확인 필요(§9 E1) |

---

## 1. 목표와 범위

### 1.1 목표
1. 웹 대시보드가 쓰는 상담 목록 `GET /api/calls`(기간·유형·담당자·고객사·상태·키워드·`metadata_incomplete` 필터, 페이지·정렬)와 상세 `GET /api/calls/{call_id}`(call + transcript + analysis + processing_log)를 규약(`convention.md`)대로 제공한다.
2. C-04가 만든 ORM 모델·마이그레이션을 **수정 없이** 사용한다. 아직 없는 DB 접근 계층(설정 `database_url`, 엔진·세션, `get_db` 의존성)만 추가한다.
3. 실제 PostgreSQL에서 필터·정렬·KST 경계·키워드 이스케이프를 검증하는 통합 테스트 기반을 C-05와 겹치지 않게 최소한으로 둔다(나중에 C-05로 교체). 테스트 스키마는 `alembic upgrade head`로 만든다.

### 1.2 포함
- 설정 `database_url`, `app/core/db.py`(세션 팩토리), `app/api/deps.py`(`get_db`, `get_call_service`)
- `app/schemas/call.py`(API enum, 유형 코드↔DB 값 표, 요청·응답 모델), `app/repositories/call_repository.py`, `app/services/call_service.py`, `app/api/web/calls.py`, `app/main.py` 라우터 등록
- `docs/api/openapi.json` 재생성
- 테스트: 단위(항상 실행) + 통합(`integration` 마커, DB 없으면 skip)
- 공용 문서 보완: `convention.md` §4.3·§5.3, `architecture.md` §3.2 트리 1줄, `README.md` 통합 테스트 안내

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| `app/models/*`, `alembic/*` 변경 | C-04(A) 소유. 필요한 변경은 §9.1에 요청으로 올림 |
| `stale` 필터, 응답의 `is_stale` | R-11(정체 감지) 이후 함께 추가(사용자 결정). 필드 추가는 호환 변경 |
| C-05 테스트 기반(공식 픽스처·팩토리) | C-05. 이번 픽스처·헬퍼는 임시이며 교체 지점을 `tests/integration/` 두 파일로 모은다 |
| `DuplicateFileDetail.status: str` → `CallStatus` | R-04(리서치 §7 #13). 이번에 `CallStatus`를 만들지만 기존 에러 모델은 건드리지 않는다 |
| 응답 `segments` 항목 엄격 모델 | E-03 확정 후 |
| 음성 재생(W-06), 수정(W-03·W-12), 삭제(W-04), 재처리(W-05) | 각 기능 |
| 앱 종료 시 엔진 `dispose()`(lifespan) | 프로세스 종료로 충분. 필요해지면 O-02(헬스 체크) 등에서 추가 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| DB 세션 | `app.api.deps.get_db` / `DbSession` (`Annotated[Session, Depends(get_db)]`) | 다른 서비스 주입 함수의 인자 |
| 세션 팩토리 | `app.state.session_factory` (`create_app`에서 생성) | `get_db`가 꺼내 씀. 테스트는 `dependency_overrides[get_db]` |
| 설정 | `Settings.database_url` (`DATABASE_URL`) | 앱 엔진. `alembic/env.py`는 같은 환경 변수를 직접 읽음 |
| API enum | `app.schemas.call.{CallStatus, SourceType, Category, ActionStatus, LogStep, LogStatus}` | R-02 상태 머신, R-04·R-07 적재, W-03 수정 |
| 유형 코드 ↔ DB 값 | `app.schemas.call.CATEGORY_DB_VALUES`, `CategoryOut` | W-03(유형 수정)·W-09·W-10(유형별 통계)·W-11(엑셀) |
| 목록 필터 | `app.schemas.call.CallListQuery` | W-11 엑셀이 같은 필터를 쓸 경우 |
| KST 하루 시작 | `app.repositories.call_repository.kst_day_start(date)` | W-09·W-11이 같은 기간 규칙을 쓸 때 `schemas/common.py`로 옮겨 공용화 |
| 테스트 스키마 | `tests/integration/conftest.py::create_schema(database_url)` | C-05가 그대로 쓰거나 대체 |

---

## 2. C-04 결과물 확인 (조사 문서·DDL과 다른 점)

리서치는 C-04 병합 전에 작성됐다. 병합된 모델·마이그레이션을 읽고 확인한 사실과 이 계획에 반영한 내용이다.

| 항목 | 리서치·`research.md` §4.1 | C-04 실제 (`cb46e02`) | 이 계획의 반영 |
|---|---|---|---|
| 모델 파일 | (가정) `app/models/call.py` 등 | `base.py`, `call_record.py`, `transcript.py`, `analysis.py`, `processing_log.py`, `edit_history.py`, `__init__.py`에서 6개 이름 re-export | `from app.models import CallRecord, Analysis, Transcript, ProcessingLog` |
| 명명 규칙 | 없음 | `Base.metadata`에 `naming_convention`(`ck_%(table_name)s_%(constraint_name)s` 등) | 영향 없음 |
| `category` 저장 값 | 영문 코드 권장(리서치 §7 #5) | **한글** `('질의', '불만', '건의', '교육 내용', '기타 문의')` + CHECK. 주석 "BE-A05 확정 전 임시값, 확정 시 마이그레이션으로 교체" | API는 규약대로 영문 코드. **변환 표 `CATEGORY_DB_VALUES`** 로 필터는 코드→DB 값, 응답은 DB 값→코드(`CategoryOut`). 저장 값이 바뀌면 표만 수정 |
| CHECK 제약 | DDL에 없음 | `call_record.status`·`source_type`, `analysis.category`·`action_status`, `processing_log.step`·`status` | 값 집합이 모두 확정 → `LogStep`·`LogStatus`도 enum으로 응답. API enum 값 = 모델 상수(테스트로 고정) |
| 값 상수 | — | 튜플 `CALL_STATUSES`, `SOURCE_TYPES`, `CATEGORIES`, `ACTION_STATUSES`, `LOG_STEPS`, `LOG_STATUSES` | API `StrEnum`은 `app/schemas/call.py`에 정의, 단위 테스트로 상수와 일치 확인 |
| `analysis.follow_up_required`·`needs_review`·`action_status` | NULL 허용 + DEFAULT | 그대로 NULL 허용(`Mapped[bool \| None]`, `Mapped[str \| None]`) | 응답 타입 `bool \| None`, `ActionStatus \| None`. NOT NULL 여부는 A에 확인(§9.1 A3) |
| `analysis.confidence` | `NUMERIC(4,3)` | `Mapped[Decimal \| None]` (`asdecimal` 기본) | 응답 `float \| None` — Pydantic이 `Decimal`을 `float`로 변환(실측 `Decimal("0.857")` → `0.857`) |
| trgm GIN 인덱스·`pg_trgm` | DDL에 없음 | 마이그레이션이 `CREATE EXTENSION IF NOT EXISTS pg_trgm` 후 `ix_analysis_question_summary_trgm`·`ix_analysis_action_summary_trgm`·`ix_transcript_corrected_text_trgm` 생성 | 쿼리는 그대로 ILIKE. 테스트 스키마는 마이그레이션으로 만들어 확장·인덱스까지 포함 |
| `processing_log(call_id)` 인덱스 | 없음(리서치 §7 #12 추가 제안) | 없음 | 상세 조회는 `WHERE call_id = ?` 순차 스캔(90일 정리로 규모 작음). 인덱스 추가는 A에 요청(§9.1 A4) |
| 관계(`relationship`) | — | `CallRecord.transcript`·`analysis`(1:0..1), `CallRecord.logs`(순서 없음), `edits` | 상세는 `joinedload(transcript, analysis)` 한 쿼리 + 로그는 정렬된 별도 쿼리 |
| 타임스탬프 | — | `TimestampMixin`(`created_at`·`updated_at`, `onupdate`) — `call_record`, `analysis` | 영향 없음 |
| FK `ON DELETE` | 없음 | 없음 | 소프트 삭제만 사용하므로 영향 없음 |
| `database_url` 설정·엔진·세션 | 없음 | **여전히 없음**. `alembic/env.py`가 `os.environ["DATABASE_URL"]`을 직접 읽음(없으면 `RuntimeError`) | 이번에 `Settings.database_url`, `app/core/db.py`, `app/api/deps.py` 추가 |
| 개발 DB 포트 | 5432 | `.env.example`·`docker-compose.dev.yml` **5433** | `database_url` 기본값 `...@localhost:5433/callcenter` |
| `alembic.ini` | 없음 | 있음. `prepend_sys_path = .`, 로깅 설정 포함 | 테스트에서는 ini를 읽지 않고 `Config()`에 `script_location`만 지정(§2.3 근거) |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| U1 | 모델 | C-04 모델을 그대로 사용, 모델 파일은 수정하지 않음. 필요한 변경은 A에게 요청(§9.1) |
| U2 | 테스트 DB | `TEST_DATABASE_URL` → testcontainers(`postgres:16`) → skip 순서. 스키마는 `alembic upgrade head`(함수 `create_schema` 하나). C-05로 대체 가능하게 최소한으로 |
| U3 | 키워드 `q` | `analysis.question_summary`, `analysis.action_summary`, `transcript.corrected_text` 세 컬럼을 `icontains(autoescape=True)`(ILIKE)로 OR 검색 |
| U4 | `is_stale` | 이번 응답에 넣지 않음(R-11 때 `stale` 필터와 함께). 상세 로그 키는 `processing_log` |
| U5 | 그 외 | 리서치 §7 권장안 채택(3.2) |

### 3.2 리서치 §7 권장안 채택 (C-04 반영 후)
| # | 항목 | 결정 |
|---|---|---|
| 5 | `category` | API는 영문 코드. DB 저장 값은 C-04가 정한 한글을 따르고 변환 표로 연결(§2). 저장 값을 코드로 바꿀지는 A 확인(§9.1 A1) |
| 6 | 담당자·고객사 | 정확히 일치(`=`) |
| 7 | 응답 필드 | 최소: `object_key`·`raw_json`·`file_hash`·`source_ref`·`file_size`·`queue_item_id`·`orchestrator_job_id`·`updated_at`·`corrected_text`·`stt_engine`·`prompt_version` 제외. `segments`는 `list[dict[str, Any]]` |
| 8 | `from > to` | 422 `VALIDATION_ERROR`, `loc: ["query", "from"]`, 규약 §4.3에 추가 |
| 9 | `category` | 반복 파라미터(다중 값) |
| 10 | `q` | 최대 100자(초과 422), 앞뒤 공백 제거 후 빈 값이면 필터 없음 |
| 11 | analysis 불리언 NULL | 모델이 NULL 허용이라 응답도 `\| None`. NOT NULL 전환은 A에 제안 |
| 12 | `processing_log(call_id)` 인덱스 | A에 추가 요청 |
| 13 | `DuplicateFileDetail.status` | 그대로 둠 |
| 14 | `database_url` | `.env.example`과 같은 개발 URL(포트 5433)을 기본값으로 |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| 엔진·세션 위치 | `app/core/db.py`의 `create_session_factory(url)`, `create_app()`이 `app.state.session_factory`에 저장 | `create_engine`은 연결을 지연하므로 OpenAPI 내보내기·단위 테스트가 DB 없이 동작(실측). 앱마다 팩토리가 있어 테스트가 설정별로 앱을 만들 수 있음. `architecture.md` §3.2는 세션 "주입"만 `api/deps.py`로 정함 |
| `get_db` | 요청당 `with session_factory() as session: yield session`. 커밋 없음(조회 전용). 쓰기 기능은 서비스가 커밋 | `architecture.md` §3.1 "Service: 트랜잭션" |
| 엔진 옵션 | `pool_pre_ping=True`만 | DB 재시작 후 끊긴 연결 재사용 방지 |
| API enum 위치 | `app/schemas/call.py`(StrEnum 6개) | 모델은 튜플 상수만 있고 수정하지 않는 원칙. 값 일치는 `test_call_enums.py`가 보장. 공용 위치(예: `app/models/` 쪽 enum)로 옮길지는 §9.1 A5 |
| 유형 변환 | `CATEGORY_DB_VALUES: dict[Category, str]`, 필터는 `CATEGORY_DB_VALUES[code]`, 응답은 `CategoryOut = Annotated[Category, BeforeValidator(...)]`로 DB 값을 코드로 바꾼 뒤 enum 검증 | 변환이 한 파일에 모임. DB 값이 이미 코드여도 그대로 통과하므로 저장 값 교체 시 표만 항등으로 바꾸면 됨. OpenAPI에는 `Category` enum(영문)만 노출 |
| 목록 필터 받기 | `@dataclass(frozen=True) CallListQuery` + `Depends()` (`PageParams`와 같은 방식) | 시그니처가 짧고 서비스·리포지토리에 그대로 전달. `Query(alias="from")`이 OpenAPI에 `from`으로 노출됨(실측) |
| `from > to` 검사 | `CallListQuery.__post_init__`에서 `AppError(VALIDATION_ERROR, detail={"errors": [...]})` | 규약 §3.4 "에러는 `AppError`로만". 응답 형식이 Pydantic 422와 같음. 다른 파라미터가 이미 잘못됐으면 FastAPI가 먼저 422를 내고 이 검사는 실행되지 않음 |
| `from > to` 에러 | `type: "date_range"`, `msg: "from은 to보다 늦을 수 없습니다"`(입력값 미포함) | 규약 §3.4.3 |
| 키워드 정규화 | `CallListQuery.keyword` 속성(strip, 빈 값 → `None`) | 길이 검사(`max_length=100`)는 원문 기준 |
| 키워드 JOIN | `q`가 있을 때만 `transcript` outer join | `transcript`·`analysis`는 `call_id` UNIQUE(`uq_*_call_id`)라 행이 늘지 않음 → `COUNT` 정확, `DISTINCT` 불필요 |
| `total` | 같은 조건의 별도 `COUNT` 쿼리 | 규약 §4.1 |
| 정렬 | `order_by_clause(sort)` — `-` 접두사 내림차순, `call_datetime`은 방향과 무관하게 `NULLS LAST`, 마지막에 같은 방향 `id` | 규약 §4.2 |
| 기간 | `kst_day_start(d)` = `datetime(y, m, d, tzinfo=KST)`, `call_datetime >= start(from)`, `call_datetime < start(to + 1일)` | 규약 §4.3. NULL `call_datetime`은 비교가 NULL이라 자연히 제외 |
| `metadata_incomplete` | `bool \| None`, `IS true/false` | `false`로도 거를 수 있음 |
| 응답 모델 | `CallBase` → `CallListItem`(+ `category`, `question_summary`, `action_status`), `CallDetail`(+ `transcript`, `analysis`, `processing_log`) | 프론트 초안 구조(`is_stale` 제외). `created_at`은 기본 정렬 기준이라 포함 |
| ORM → 응답 | 목록: `_base_fields(call)`(= `CallBase.model_fields` 이름으로 `getattr`) + 분석 3컬럼 dict를 `model_validate`. 상세: 하위 모델에 `from_attributes=True`를 두고 `call.transcript`·`call.analysis`·로그 ORM 객체를 그대로 넣음 | `model_construct()` 금지(규약 §5.1) — 검증을 거쳐 `KstDatetime`·enum·`Decimal→float` 변환 |
| 상세 조회 | `select(CallRecord).options(joinedload(transcript), joinedload(analysis))` + `list_logs`(정렬 쿼리) | C-04 관계 재사용. `CallRecord.logs`에는 `order_by`가 없어 로그만 별도 쿼리 |
| 로그 순서 | `created_at ASC, id ASC` | 처리 순서, 프론트 초안과 같음 |
| 경로 파라미터 | `/api/calls/{call_id}`, `Annotated[int, Path(ge=1, le=BIGINT_MAX)]` | 내장 `id`를 가리지 않음. `le`가 없으면 BIGINT 범위 밖 값이 DB에서 500. 0·음수·범위 초과는 422 |
| 상세 로그 바인딩 | `bind_call_id(request, call_id)` (404 포함) | 접근 로그에 `call_id` |
| 라우터 | `APIRouter(prefix="/api/calls", tags=["calls"])`, 목록 경로 `""` | 규약 §7.4. operationId `list_calls`, `get_call` |
| 404 문서화 | `responses=error_responses(ErrorCode.NOT_FOUND)` | 규약 §3.4.5 |
| 테스트 앱의 `get_call` 이름 충돌 | `tests/unit/conftest.py`의 테스트 라우트 함수 `get_call` → `bind_call` | `build_app()` 앱에 실제 `get_call`과 같은 operationId가 생겨 FastAPI 중복 경고. 경로·동작은 그대로 |
| 테스트 스키마 생성 | `create_schema(url)`: `alembic.config.Config()` + `script_location`만 지정, `DATABASE_URL`을 잠시 설정하고 `command.downgrade(base)` → `command.upgrade(head)` | `env.py`는 URL을 `DATABASE_URL` 환경 변수에서만 읽음. `alembic.ini`를 넘기면 `env.py`의 `fileConfig()`가 로깅을 재설정(`disable_existing_loggers`)해 이후 단위 테스트의 앱 로거가 꺼질 수 있어 ini를 쓰지 않음. `downgrade base`로 `TEST_DATABASE_URL`의 이전 실행 흔적을 지움(마이그레이션 downgrade 경로도 함께 확인됨). `create_all`보다 실제 스키마(확장·trgm 인덱스·CHECK)와 같음 |
| 테스트 격리 | 테스트마다 연결 단위 바깥 트랜잭션 + `Session(join_transaction_mode="create_savepoint")`, 끝에 롤백 | 데이터가 남지 않음. 단 `now()`가 트랜잭션 시작 시각이라 한 테스트 안의 기본 `created_at`이 모두 같음 → 정렬 테스트는 시각을 직접 지정 |
| testcontainers import | `testcontainers.community.postgres.PostgresContainer` | `testcontainers.postgres`는 4.15에서 deprecated |
| Docker 없을 때 | `PostgresContainer(...)` 생성·`start()` 중 예외 → `pytest.skip` | 생성자가 이미 Docker 클라이언트를 만들며 `DockerException`(실측) |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준) | 내용 |
|---|---|---|
| 수정 | `app/core/config.py` | `database_url` 필드(개발 URL 기본값, 포트 5433) |
| 신규 | `app/core/db.py` | `create_session_factory(database_url)` |
| 신규 | `app/schemas/call.py` | API enum 6개, `CATEGORY_DB_VALUES`, `CategoryOut`, `CallSort`, `CallListQuery`, `CallBase`, `CallListItem`, `TranscriptOut`, `AnalysisOut`, `ProcessingLogOut`, `CallDetail` |
| 신규 | `app/repositories/call_repository.py` | `kst_day_start`, `order_by_clause`, `filter_conditions`, `CallRepository` |
| 신규 | `app/services/call_service.py` | `CallService.list_calls`, `CallService.get_call` |
| 신규 | `app/api/deps.py` | `get_db`, `DbSession`, `get_call_service` |
| 신규 | `app/api/web/calls.py` | `router`, `list_calls`, `get_call` |
| 수정 | `app/main.py` | 세션 팩토리 생성, `calls.router` 등록 |
| 수정 | `docs/api/openapi.json` | 재생성(경로 2개, 스키마 추가) |
| 수정 | `docs/api/convention.md` | §4.3 `from > to`·`q`·담당자 규칙, §5.3 로그 enum 2행·`is_stale` 제공 시점 |
| 수정 | `docs/architecture/architecture.md` | §3.2 트리에 `core/db.py` 1줄 |
| 수정 | `README.md` | 통합 테스트 DB 선택 순서·`TEST_DATABASE_URL` 안내 |
| 수정 | `tests/unit/conftest.py` | 테스트 라우트 함수 이름 `get_call` → `bind_call` |
| 수정 | `tests/unit/test_config.py` | `DATABASE_URL` 격리·기본값·환경 변수 |
| 신규 | `tests/unit/test_call_enums.py` | API enum = 모델 CHECK 상수, 유형 변환 표 완전성 |
| 신규 | `tests/unit/test_call_query.py` | KST 경계, 정렬 SQL, 필터 SQL·이스케이프·유형 변환, `from > to` |
| 신규 | `tests/unit/test_call_schemas.py` | 응답 직렬화(+09:00, 유형 코드 변환, null, `Decimal→float`, 내부 필드 미노출) |
| 신규 | `tests/unit/test_calls_api.py` | 가짜 서비스로 파라미터 파싱·422·404·OpenAPI |
| 신규 | `tests/integration/conftest.py` | `create_schema`, `database_url`, `engine`, `db_session`, `api` 픽스처 |
| 신규 | `tests/integration/factories.py` | `make_call`, `make_transcript`, `make_analysis`, `make_log` |
| 신규 | `tests/integration/test_call_repository.py` | 실제 PostgreSQL 필터·정렬·페이지·상세 조회 |
| 신규 | `tests/integration/test_calls_api.py` | 실제 PostgreSQL 종단 간 응답 |

- **변경하지 않는 파일**: `app/models/*`, `alembic.ini`, `alembic/env.py`, `alembic/versions/*`, `.env.example`(이미 `DATABASE_URL` 있음), `pyproject.toml`(`integration` 마커 이미 있음).
- **새 의존성 없음.** SQLAlchemy·psycopg·Alembic·testcontainers는 이미 있다.

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_openapi.py` | 변경 없음. `test_committed_openapi_is_up_to_date`가 `openapi.json` 재생성을 강제, `test_operation_ids_are_unique_in_real_app`이 `list_calls`·`get_call` 고유성 확인 |
| `tests/unit/test_config.py` | 수정(§6.4). 개발자 셸에 `DATABASE_URL`이 있어도 결과가 같도록 `_ENV_NAMES`에 추가 |
| `tests/unit/conftest.py` | 함수 이름만 변경. `test_logging.py`는 경로 `/calls/{call_id}`로 호출하므로 영향 없음 |
| `tests/unit/test_app_smoke.py` 외 | 변경 없음. `create_app()`이 엔진을 만들어도 연결하지 않음 |

---

## 5. 모듈별 코드

> 아래 코드는 스크래치 복사본(`cb46e02` 기준)에서 `ruff check`·`ruff format --check`·`mypy .`(strict)를 통과한 그대로다.

### 5.1 `app/core/config.py` (필드 추가)
```python
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    docs_enabled: bool = True
    # 개발용 기본값(.env.example과 같음). 운영은 .env의 DATABASE_URL로 덮는다.
    database_url: str = "postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter"
```
- 기본값이 있어 `Settings(_env_file=None)`을 쓰는 `scripts/export_openapi.py`·단위 테스트가 그대로 동작한다.

### 5.2 `app/core/db.py` (신규)
```python
"""DB 엔진·세션 팩토리 (동기 SQLAlchemy 2.0 + psycopg 3)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """엔진과 세션 팩토리를 만든다. 실제 DB 연결은 첫 쿼리 때 일어난다."""
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
```

### 5.3 `app/schemas/call.py` (신규)
```python
"""상담 목록·상세 API 스키마 (W-01, W-02)."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.core.errors import AppError, ErrorCode
from app.schemas.common import KstDatetime

# ---------------------------------------------------------------- enum (convention.md §5.3)
# 값은 모델의 CHECK 상수(app/models/*.py)와 같아야 한다 (tests/unit/test_call_enums.py).


class CallStatus(StrEnum):
    REGISTERED = "REGISTERED"
    QUEUED = "QUEUED"
    STT_DONE = "STT_DONE"
    STORED = "STORED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    RETRY_REQUESTED = "RETRY_REQUESTED"


class SourceType(StrEnum):
    DRIVE = "DRIVE"
    WEB = "WEB"


class Category(StrEnum):
    INQUIRY = "INQUIRY"
    COMPLAINT = "COMPLAINT"
    SUGGESTION = "SUGGESTION"
    EDUCATION = "EDUCATION"
    ETC = "ETC"


class ActionStatus(StrEnum):
    OPEN = "OPEN"
    DONE = "DONE"


class LogStep(StrEnum):
    REGISTER = "REGISTER"
    QUEUE = "QUEUE"
    STT = "STT"
    GENAI = "GENAI"
    STORE = "STORE"
    EXCEL = "EXCEL"
    CRM = "CRM"
    RETRY = "RETRY"


class LogStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    RETRY = "RETRY"


# DB `analysis.category` 저장 값(현재 한글, app/models/analysis.py CATEGORIES) ↔ API 코드.
# 저장 값이 코드로 바뀌면 이 표만 고친다.
CATEGORY_DB_VALUES: dict[Category, str] = {
    Category.INQUIRY: "질의",
    Category.COMPLAINT: "불만",
    Category.SUGGESTION: "건의",
    Category.EDUCATION: "교육 내용",
    Category.ETC: "기타 문의",
}
_CATEGORY_BY_DB_VALUE = {value: code for code, value in CATEGORY_DB_VALUES.items()}


def _category_from_db(value: object) -> object:
    # DB 값이면 코드로 바꾸고, 그 밖의 값은 enum 검증에 맡긴다.
    return _CATEGORY_BY_DB_VALUE.get(value, value) if isinstance(value, str) else value


CategoryOut = Annotated[Category, BeforeValidator(_category_from_db)]

Q_MAX_LENGTH = 100

CallSort = Literal[
    "call_datetime",
    "-call_datetime",
    "created_at",
    "-created_at",
    "status_changed_at",
    "-status_changed_at",
]


# ---------------------------------------------------------------- 요청


@dataclass(frozen=True)
class CallListQuery:
    """`Depends(CallListQuery)`로 받는 목록 필터·정렬 쿼리. 페이지는 `PageParams`."""

    from_: Annotated[date | None, Query(alias="from")] = None
    to: Annotated[date | None, Query()] = None
    category: Annotated[list[Category] | None, Query()] = None
    agent: Annotated[str | None, Query()] = None
    client: Annotated[str | None, Query()] = None
    status: Annotated[list[CallStatus] | None, Query()] = None
    q: Annotated[str | None, Query(max_length=Q_MAX_LENGTH)] = None
    metadata_incomplete: Annotated[bool | None, Query()] = None
    sort: Annotated[CallSort, Query()] = "-created_at"

    def __post_init__(self) -> None:
        if self.from_ and self.to and self.from_ > self.to:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                detail={
                    "errors": [
                        {
                            "loc": ["query", "from"],
                            "msg": "from은 to보다 늦을 수 없습니다",
                            "type": "date_range",
                        }
                    ]
                },
            )

    @property
    def keyword(self) -> str | None:
        """앞뒤 공백을 뺀 검색어. 비면 None(필터 없음)."""
        stripped = (self.q or "").strip()
        return stripped or None


# ---------------------------------------------------------------- 응답


class CallBase(BaseModel):
    """목록·상세 공통 필드. `object_key`·`file_hash` 등 내부 값은 넣지 않는다."""

    id: int
    source_type: SourceType
    original_name: str
    duration_sec: int | None
    agent_name: str | None
    client_company: str | None
    call_datetime: KstDatetime | None
    metadata_incomplete: bool
    status: CallStatus
    status_changed_at: KstDatetime
    retry_count: int
    created_at: KstDatetime


class CallListItem(CallBase):
    # 분석 전이면 null
    category: CategoryOut | None
    question_summary: str | None
    action_status: ActionStatus | None


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # 항목 구조({speaker, start, end, text})는 E-03 확정 전이라 엄격 모델로 두지 않는다.
    segments: list[dict[str, Any]]


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: CategoryOut
    confidence: float | None  # DB NUMERIC(4,3) → Decimal → float
    question_summary: str | None
    action_summary: str | None
    # 아래 셋은 DB에서 NULL 허용(DEFAULT만 있음)이라 null일 수 있다.
    follow_up_required: bool | None
    action_status: ActionStatus | None
    entities: dict[str, Any] | None
    needs_review: bool | None


class ProcessingLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: LogStep
    status: LogStatus
    message: str | None
    created_at: KstDatetime


class CallDetail(CallBase):
    transcript: TranscriptOut | None
    analysis: AnalysisOut | None
    processing_log: list[ProcessingLogOut]
```

### 5.4 `app/repositories/call_repository.py` (신규)
```python
"""상담 조회 쿼리. 소프트 삭제된 건은 항상 제외한다 (architecture.md §3.1)."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Row, Select, UnaryExpression, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Analysis, CallRecord, ProcessingLog, Transcript
from app.schemas.call import CATEGORY_DB_VALUES, CallListQuery, CallSort
from app.schemas.common import KST

ListRow = Row[tuple[CallRecord, str | None, str | None, str | None]]

_SORT_COLUMNS = {
    "call_datetime": CallRecord.call_datetime,
    "created_at": CallRecord.created_at,
    "status_changed_at": CallRecord.status_changed_at,
}


def kst_day_start(day: date) -> datetime:
    """KST 기준 그날 00:00 (aware)."""
    return datetime(day.year, day.month, day.day, tzinfo=KST)


def order_by_clause(sort: CallSort) -> list[UnaryExpression[Any]]:
    """`-`는 내림차순. `call_datetime`은 방향과 무관하게 NULLS LAST, 끝에 같은 방향 id."""
    desc = sort.startswith("-")
    field = sort.removeprefix("-")
    column = _SORT_COLUMNS[field]
    primary = column.desc() if desc else column.asc()
    if field == "call_datetime":
        primary = primary.nulls_last()
    return [primary, CallRecord.id.desc() if desc else CallRecord.id.asc()]


def filter_conditions(query: CallListQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [CallRecord.deleted_at.is_(None)]
    if query.from_:
        conditions.append(CallRecord.call_datetime >= kst_day_start(query.from_))
    if query.to:
        conditions.append(CallRecord.call_datetime < kst_day_start(query.to + timedelta(days=1)))
    if query.category:
        db_values = [CATEGORY_DB_VALUES[code] for code in query.category]
        conditions.append(Analysis.category.in_(db_values))
    if query.agent is not None:
        conditions.append(CallRecord.agent_name == query.agent)
    if query.client is not None:
        conditions.append(CallRecord.client_company == query.client)
    if query.status:
        conditions.append(CallRecord.status.in_(query.status))
    if query.metadata_incomplete is not None:
        conditions.append(CallRecord.metadata_incomplete.is_(query.metadata_incomplete))
    if keyword := query.keyword:
        conditions.append(
            or_(
                Analysis.question_summary.icontains(keyword, autoescape=True),
                Analysis.action_summary.icontains(keyword, autoescape=True),
                Transcript.corrected_text.icontains(keyword, autoescape=True),
            )
        )
    return conditions


def _filtered[T: tuple[Any, ...]](stmt: Select[T], query: CallListQuery) -> Select[T]:
    # transcript·analysis는 call_id UNIQUE라 JOIN해도 행이 늘지 않는다 (COUNT 정확, DISTINCT 없음).
    stmt = stmt.outerjoin(Analysis, Analysis.call_id == CallRecord.id)
    if query.keyword:
        stmt = stmt.outerjoin(Transcript, Transcript.call_id == CallRecord.id)
    return stmt.where(*filter_conditions(query))


class CallRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_calls(self, query: CallListQuery, *, offset: int, limit: int) -> Sequence[ListRow]:
        stmt = select(
            CallRecord, Analysis.category, Analysis.question_summary, Analysis.action_status
        ).select_from(CallRecord)
        stmt = _filtered(stmt, query).order_by(*order_by_clause(query.sort))
        result = self._session.execute(stmt.offset(offset).limit(limit))
        # outer join이라 분석 컬럼은 None일 수 있다 (매핑 타입보다 넓은 ListRow로 반환).
        return result.all()  # type: ignore[return-value]

    def count_calls(self, query: CallListQuery) -> int:
        stmt = _filtered(select(func.count()).select_from(CallRecord), query)
        return self._session.execute(stmt).scalar_one()

    def get_call(self, call_id: int) -> CallRecord | None:
        """삭제되지 않은 건 + transcript·analysis(1:0..1)를 한 번에 읽는다."""
        stmt = (
            select(CallRecord)
            .options(joinedload(CallRecord.transcript), joinedload(CallRecord.analysis))
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
        )
        return self._session.scalars(stmt).one_or_none()

    def list_logs(self, call_id: int) -> Sequence[ProcessingLog]:
        # CallRecord.logs 관계에는 순서가 없어 별도 쿼리로 처리 순서를 보장한다.
        stmt = (
            select(ProcessingLog)
            .where(ProcessingLog.call_id == call_id)
            .order_by(ProcessingLog.created_at.asc(), ProcessingLog.id.asc())
        )
        return self._session.scalars(stmt).all()
```
렌더링되는 SQL(PostgreSQL, 실측)
```sql
-- q=" 50%_ ", from=2026-11-01, to=2026-11-23, status=FAILED, category=COMPLAINT
call_record.deleted_at IS NULL
AND call_record.call_datetime >= %(call_datetime_1)s      -- 2026-11-01 00:00+09:00
AND call_record.call_datetime < %(call_datetime_2)s       -- 2026-11-24 00:00+09:00
AND analysis.category IN (...)                            -- ['불만'] (DB 저장 값)
AND call_record.status IN (...)
AND ((analysis.question_summary ILIKE '%%' || %(question_summary_1)s || '%%' ESCAPE '/')   -- '50/%/_'
  OR (analysis.action_summary ILIKE ... ESCAPE '/')
  OR (transcript.corrected_text ILIKE ... ESCAPE '/'))
-- sort=-call_datetime
ORDER BY call_record.call_datetime DESC NULLS LAST, call_record.id DESC
```

### 5.5 `app/services/call_service.py` (신규)
```python
"""웹 상담 조회 유스케이스 (W-01 목록, W-02 상세)."""

from typing import Any

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallBase, CallDetail, CallListItem, CallListQuery
from app.schemas.common import Page, PageParams


def _base_fields(call: CallRecord) -> dict[str, Any]:
    return {name: getattr(call, name) for name in CallBase.model_fields}


class CallService:
    def __init__(self, repository: CallRepository) -> None:
        self._repository = repository

    def list_calls(self, query: CallListQuery, page: PageParams) -> Page[CallListItem]:
        rows = self._repository.list_calls(query, offset=page.offset, limit=page.size)
        items = [
            CallListItem.model_validate(
                {
                    **_base_fields(call),
                    "category": category,
                    "question_summary": question_summary,
                    "action_status": action_status,
                }
            )
            for call, category, question_summary, action_status in rows
        ]
        total = self._repository.count_calls(query)
        return Page(items=items, page=page.page, size=page.size, total=total)

    def get_call(self, call_id: int) -> CallDetail:
        call = self._repository.get_call(call_id)
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return CallDetail.model_validate(
            {
                **_base_fields(call),
                "transcript": call.transcript,
                "analysis": call.analysis,
                "processing_log": self._repository.list_logs(call_id),
            }
        )
```

### 5.6 `app/api/deps.py` (신규)
```python
"""라우터 공용 의존성: DB 세션, 서비스 주입."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.repositories.call_repository import CallRepository
from app.services.call_service import CallService


def get_db(request: Request) -> Iterator[Session]:
    """요청당 세션 하나. 응답 후 닫는다 (커밋은 서비스가 한다)."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def get_call_service(session: DbSession) -> CallService:
    return CallService(CallRepository(session))
```

### 5.7 `app/api/web/calls.py` (신규)
```python
"""웹 상담 조회 API: `GET /api/calls`, `GET /api/calls/{call_id}`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import get_call_service
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.call import CallDetail, CallListItem, CallListQuery
from app.schemas.common import Page, PageParams, error_responses
from app.services.call_service import CallService

BIGINT_MAX = 9_223_372_036_854_775_807

router = APIRouter(prefix="/api/calls", tags=["calls"])

CallServiceDep = Annotated[CallService, Depends(get_call_service)]


@router.get("")
def list_calls(
    query: Annotated[CallListQuery, Depends()],
    page: Annotated[PageParams, Depends()],
    service: CallServiceDep,
) -> Page[CallListItem]:
    return service.list_calls(query, page)


@router.get("/{call_id}", responses=error_responses(ErrorCode.NOT_FOUND))
def get_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: CallServiceDep,
) -> CallDetail:
    bind_call_id(request, call_id)
    return service.get_call(call_id)
```

### 5.8 `app/main.py` (수정)
```diff
 from fastapi.routing import APIRoute

+from app.api.web import calls
 from app.core.config import Settings, get_settings
+from app.core.db import create_session_factory
 from app.core.errors import ErrorCode, register_exception_handlers
@@
     register_exception_handlers(app)
+    # 엔진 생성만으로는 DB에 연결하지 않는다 (OpenAPI 내보내기·단위 테스트는 DB 없이 동작).
+    app.state.session_factory = create_session_factory(settings.database_url)
+    app.include_router(calls.router)

     # add_middleware는 목록 맨 앞에 끼워 넣으므로 ...
```

### 5.9 `docs/api/openapi.json` (재생성)
```bash
cd backend && uv run python -m scripts.export_openapi
```
생성 결과 요점(실측)
- `paths`: `/api/calls`(get, `list_calls`), `/api/calls/{call_id}`(get, `get_call`, 응답 200·404·422·500)
- `/api/calls` 쿼리: `from`, `to`(date), `category`·`status`(enum 배열), `agent`, `client`, `q`(`maxLength: 100`), `metadata_incomplete`, `sort`(enum 6개, 기본 `-created_at`), `page`, `size`
- 추가 스키마: `ActionStatus`, `AnalysisOut`, `CallDetail`, `CallListItem`, `CallStatus`, `Category`, `LogStatus`, `LogStep`, `Page_CallListItem_`, `ProcessingLogOut`, `SourceType`, `TranscriptOut`

### 5.10 공용 문서 보완

`docs/api/convention.md` §4.3 필터 — 기간 항목 뒤에 추가
```markdown
- `from`이 `to`보다 늦으면 422 `VALIDATION_ERROR`(`loc: ["query", "from"]`, `type: "date_range"`). 같은 날은 허용.
- 키워드 `q`: 최대 100자(초과 422), 앞뒤 공백을 지운 뒤 비어 있으면 조건 없음. 대소문자 무시 부분 일치이며 `%`·`_`는 글자 그대로 검색한다. 대상은 질문 요약·조치 요약·교정 전사문(`corrected_text`).
- 담당자 `agent`·고객사 `client`는 정확히 일치.
```
`docs/api/convention.md` §5.3 enum 표에 2행 추가
```markdown
| `processing_log.step` | `REGISTER`, `QUEUE`, `STT`, `GENAI`, `STORE`, `EXCEL`, `CRM`, `RETRY` |
| `processing_log.status` | `SUCCESS`, `FAIL`, `RETRY` |
```
`docs/api/convention.md` §5.3 마지막 줄 교체
```markdown
- 정체(stale)는 상태 값이 아니다. 목록 항목의 `is_stale`(서버 계산)과 `stale` 필터로 표현한다. 두 항목은 정체 감지(R-11) 이후 추가된다(그전에는 응답에 없고 `stale` 파라미터는 무시된다).
```
`docs/architecture/architecture.md` §3.2 트리 `core/` 아래 1줄 추가
```
│   │   ├── db.py                # 엔진·세션 팩토리
```
`README.md` "검사" 절 코드 블록 아래 추가
```markdown
통합 테스트(`integration` 마커)의 DB는 다음 순서로 고른다. 스키마는 `alembic upgrade head`로 만든다.

1. `TEST_DATABASE_URL` 환경 변수 (예: `postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter_test`) — **테스트 전용 DB**여야 한다. 시작 시 `alembic downgrade base`로 모든 테이블을 지운다.
2. 없으면 testcontainers로 `postgres:16` 컨테이너 (Docker 필요)
3. 둘 다 불가하면 skip
```

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 단위 테스트는 DB 없이 **항상** 돈다: enum·변환 표, 파라미터 검증, SQL 생성(PostgreSQL 방언으로 컴파일만), 응답 직렬화, OpenAPI. 라우터 테스트는 `dependency_overrides[get_call_service]`로 가짜 서비스를 넣는다.
- 통합 테스트(`pytestmark = pytest.mark.integration`)는 실제 PostgreSQL + 실제 마이그레이션 스키마에서 쿼리 결과를 확인한다. `TEST_DATABASE_URL`도 Docker도 없으면 **skip**(실패 아님).
- 통합 테스트 데이터의 `category`는 **DB 저장 값(한글)** 으로 넣는다(CHECK 제약). API 응답은 코드로 확인한다.
- 빠른 확인: `uv run pytest -m "not integration"`.

### 6.2 케이스 목록 (구현 순서)

**1단계 — 설정·enum (단위, 항상)**
| # | 테스트 | 기대 |
|---|---|---|
| 1 | `test_config::test_defaults_without_env`(수정) | `database_url` = 개발 URL(5433) |
| 2 | `test_config::test_env_example_is_compatible`(수정) | `.env.example` 값 = 개발 URL |
| 3 | `test_config::test_database_url_from_env` | `DATABASE_URL` 환경 변수 반영 |
| 4 | `test_api_enum_matches_db_check_values` ×5 | `CallStatus`·`SourceType`·`ActionStatus`·`LogStep`·`LogStatus` 값(순서 포함) = 모델 상수 |
| 5 | `test_category_mapping_covers_codes_and_db_values` | 표의 키 = `Category` 전체, 값 = `CATEGORIES` 전체 |

**2단계 — 쿼리 조립 (단위, 항상)**
| # | 테스트 | 기대 |
|---|---|---|
| 6 | `test_kst_day_start_is_aware_midnight` | `2026-11-23 00:00+09:00` |
| 7 | `test_order_by_clause` ×5 | `-created_at` → `created_at DESC, id DESC` / `call_datetime` 양방향 `NULLS LAST` / 오름차순은 `id ASC` |
| 8 | `test_no_filter_still_excludes_soft_deleted` | 조건 = `deleted_at IS NULL` 하나 |
| 9 | `test_period_uses_kst_day_bounds_with_to_inclusive` | 파라미터에 `11-01 00:00+09:00`, `11-24 00:00+09:00`(to + 1일, 미만) |
| 10 | `test_keyword_searches_three_columns_with_escaped_wildcards` | 3컬럼 `ILIKE`, `ESCAPE '/'`, 값 `50/%/_` |
| 11 | `test_blank_keyword_is_ignored` | `keyword is None`, 키워드 조건 없음 |
| 12 | `test_multi_value_and_exact_match_filters` | `status IN`, `category IN`(값 `["불만"]` = DB 값), `agent_name =`, `client_company =`, `metadata_incomplete IS false` |
| 13 | `test_from_after_to_raises_validation_error` | `AppError(VALIDATION_ERROR)`, `detail.errors[0]` = `{loc: [query, from], msg, type: date_range}` |
| 14 | `test_same_day_range_is_allowed` | 예외 없음 |

**3단계 — 응답 스키마 (단위, 항상)**
| # | 테스트 | 기대 |
|---|---|---|
| 15 | `test_list_item_maps_db_category_to_code` | `"불만"` → `"COMPLAINT"` |
| 16 | `test_list_item_without_analysis_has_null_fields` | `category`·`call_datetime` null, 시각 `+09:00` 초 단위 |
| 17 | `test_detail_reads_orm_like_objects_and_serializes` | 속성 객체에서 읽음, `"교육 내용"` → `EDUCATION`, `Decimal("0.850")` → `0.85`, NULL 불리언·`action_status` → null, `raw_json`·`object_key`·`file_hash` 미노출, 로그 `+09:00` |

**4단계 — 라우터·OpenAPI (단위, 항상, 가짜 서비스)**
| # | 테스트 | 기대 |
|---|---|---|
| 18 | `test_list_defaults` | 200 `{items: [], page: 1, size: 20, total: 0}`, 서비스가 받은 쿼리 = `CallListQuery()` |
| 19 | `test_list_parses_all_params` | `from` 별칭, 반복 `category`·`status`, 한글 값, `page=2&size=100` 전달 |
| 20 | `test_list_invalid_params_return_422` ×10 | `sort=id`·`sort=agent_name`·`size=101`·`page=0`·`status=DONE`·`category=질의`(API는 코드만)·`from=2026/11/01`·`q` 101자·`metadata_incomplete=maybe`·`from>to` → 422 `VALIDATION_ERROR`, 해당 `loc`, 서비스 미호출 |
| 21 | `test_q_with_100_chars_is_allowed` | 200 |
| 22 | `test_unknown_param_stale_is_ignored` | `stale=true` → 200, 필터 없음 |
| 23 | `test_get_call_returns_detail` | 200, `+09:00`, `transcript`·`analysis` null, `processing_log` `[]` |
| 24 | `test_get_call_not_found` | 404 `{code: NOT_FOUND, message: "대상을 찾을 수 없습니다.", detail: null}` |
| 25 | `test_get_call_invalid_id_returns_422` ×3 | `abc`·`0`·`9223372036854775808` → 422, `loc` `["path", "call_id"]` |
| 26 | `test_openapi_list_calls` | operationId `list_calls`, 태그 `calls`, 파라미터 11개, `sort` enum·기본값, `status` 배열, `q` maxLength 100, 응답 `Page_CallListItem_` |
| 27 | `test_openapi_get_call` | operationId `get_call`, 응답 200·404·422·500 |
| 28 | `test_openapi_enums` | `CallStatus`·`Category`(영문)·`LogStep` enum, `CallListItem`에 `is_stale` 없음, `CallDetail` 필수에 `processing_log` |
| 29 | 기존 `test_committed_openapi_is_up_to_date` | `openapi.json` 재생성 후 통과 |

**5단계 — 리포지토리 (통합, DB 없으면 skip)**
| # | 테스트 | 기대 |
|---|---|---|
| 30 | `test_soft_deleted_calls_are_excluded` | 목록·건수에서 삭제 건 제외 |
| 31 | `test_period_filter_uses_kst_day_and_includes_to` | `11-23 00:00`·`11-24 23:59:59`(KST) 포함, `11-22 23:59:59`·`11-25 00:00` 제외, `call_datetime` NULL 제외 |
| 32 | `test_only_from_or_only_to` | 한쪽만 와도 동작 |
| 33 | `test_status_and_category_multi_value` | 다중 값 IN, `Category.COMPLAINT` → DB `불만` 건만, 분석 없는 건 제외 |
| 34 | `test_agent_and_client_exact_match` | 정확히 일치, 부분 문자열 `가나` → 0건 |
| 35 | `test_metadata_incomplete_filter` | `true`/`false` 각각 |
| 36 | `test_keyword_searches_summaries_and_corrected_text` | 질문 요약·조치 요약·`corrected_text` 일치 3건, `segments`에만 있는 건 제외, `count` 3 |
| 37 | `test_keyword_is_case_insensitive_and_escapes_wildcards` | `ars`가 `ARS` 2건, `50%`는 1건(`500` 제외), `5_0` → 0건 |
| 38 | `test_default_sort_is_created_at_desc_with_id_tiebreak` | 같은 `created_at`은 `id` 같은 방향 |
| 39 | `test_call_datetime_sort_puts_nulls_last_both_directions` | 오름·내림 모두 NULL 마지막 |
| 40 | `test_offset_limit_and_count_out_of_range` | offset 2/limit 2 → 1건, offset 10 → `[]`, count 3 |
| 41 | `test_list_row_has_analysis_columns_or_none` | 분석 있으면 `("불만", "요약", "OPEN")`(DB 기본값), 없으면 `(None, None, None)` |
| 42 | `test_get_call_excludes_deleted_and_logs_are_ordered` | 삭제·없는 ID → None, 로그 `created_at` 오름차순 |

**6단계 — API 종단 간 (통합, DB 없으면 skip)**
| # | 테스트 | 기대 |
|---|---|---|
| 43 | `test_list_calls_end_to_end` | `q=환불&size=10` → total 1, 항목 `+09:00`·`category: COMPLAINT`(DB `불만`)·`OPEN`, `object_key` 없음, 삭제 건 제외 |
| 44 | `test_list_calls_page_beyond_last_returns_empty_items` | `page=5` → `items: []`, `total: 1` |
| 45 | `test_get_call_detail_end_to_end` | `segments` 그대로, `confidence` `0.857`(숫자), `raw_json` 없음, 로그 `+09:00` |
| 46 | `test_get_call_without_children` | `transcript`·`analysis` null, `processing_log` `[]` |
| 47 | `test_get_deleted_call_is_404` | 404 `NOT_FOUND` |

### 6.3 케이스 수
| 구분 | 신규 함수 | 실행 수 | 실행 조건 |
|---|---|---|---|
| 단위 (`tests/unit`) | 26 (+ 기존 2개 수정) | 45 | 항상 |
| 통합 (`tests/integration`) | 18 | 18 | `TEST_DATABASE_URL` 또는 Docker |

### 6.4 테스트 코드

`tests/unit/conftest.py` (함수 이름만 변경)
```diff
     @app.get("/calls/{call_id}")  # 동기 엔드포인트에서 call_id 바인딩 + 앱 로그
-    def get_call(call_id: int, request: Request) -> dict[str, int]:
+    def bind_call(call_id: int, request: Request) -> dict[str, int]:
```

`tests/unit/test_config.py` (수정)
```diff
 from app.core.config import Settings

-_ENV_NAMES = ("MAX_UPLOAD_MB", "CORS_ORIGINS", "LOG_LEVEL", "DOCS_ENABLED")
+_DEV_DATABASE_URL = "postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter"
+
+_ENV_NAMES = ("MAX_UPLOAD_MB", "CORS_ORIGINS", "LOG_LEVEL", "DOCS_ENABLED", "DATABASE_URL")
@@ def test_defaults_without_env() -> None:
     assert settings.docs_enabled is True
+    assert settings.database_url == _DEV_DATABASE_URL
@@ def test_env_example_is_compatible() -> None:
     assert settings.docs_enabled is True
+    assert settings.database_url == _DEV_DATABASE_URL
@@ (파일 끝)
+
+
+def test_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
+
+    assert Settings(_env_file=None).database_url == "postgresql+psycopg://u:p@db:5432/x"
```

`tests/unit/test_call_enums.py`
```python
from enum import StrEnum

import pytest

from app.models.analysis import ACTION_STATUSES, CATEGORIES
from app.models.call_record import CALL_STATUSES, SOURCE_TYPES
from app.models.processing_log import LOG_STATUSES, LOG_STEPS
from app.schemas.call import (
    CATEGORY_DB_VALUES,
    ActionStatus,
    CallStatus,
    Category,
    LogStatus,
    LogStep,
    SourceType,
)


@pytest.mark.parametrize(
    ("enum", "db_values"),
    [
        (CallStatus, CALL_STATUSES),
        (SourceType, SOURCE_TYPES),
        (ActionStatus, ACTION_STATUSES),
        (LogStep, LOG_STEPS),
        (LogStatus, LOG_STATUSES),
    ],
)
def test_api_enum_matches_db_check_values(enum: type[StrEnum], db_values: tuple[str, ...]) -> None:
    assert [member.value for member in enum] == list(db_values)


def test_category_mapping_covers_codes_and_db_values() -> None:
    assert set(CATEGORY_DB_VALUES) == set(Category)
    assert sorted(CATEGORY_DB_VALUES.values()) == sorted(CATEGORIES)
```

`tests/unit/test_call_query.py`
```python
from datetime import date, datetime

import pytest
from sqlalchemy import and_, create_engine

from app.core.errors import AppError, ErrorCode
from app.repositories.call_repository import filter_conditions, kst_day_start, order_by_clause
from app.schemas.call import CallListQuery, CallStatus, Category
from app.schemas.common import KST

_PG = create_engine("postgresql+psycopg://").dialect  # 연결하지 않고 SQL 문자열만 만든다


def _sql(query: CallListQuery) -> tuple[str, dict[str, object]]:
    compiled = and_(*filter_conditions(query)).compile(dialect=_PG)
    return str(compiled), compiled.params


def test_kst_day_start_is_aware_midnight() -> None:
    assert kst_day_start(date(2026, 11, 23)) == datetime(2026, 11, 23, tzinfo=KST)


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("-created_at", ["call_record.created_at DESC", "call_record.id DESC"]),
        ("created_at", ["call_record.created_at ASC", "call_record.id ASC"]),
        ("status_changed_at", ["call_record.status_changed_at ASC", "call_record.id ASC"]),
        ("-call_datetime", ["call_record.call_datetime DESC NULLS LAST", "call_record.id DESC"]),
        ("call_datetime", ["call_record.call_datetime ASC NULLS LAST", "call_record.id ASC"]),
    ],
)
def test_order_by_clause(sort: str, expected: list[str]) -> None:
    clauses = order_by_clause(sort)  # type: ignore[arg-type]

    assert [str(c.compile(dialect=_PG)) for c in clauses] == expected


def test_no_filter_still_excludes_soft_deleted() -> None:
    sql, _ = _sql(CallListQuery())

    assert sql == "call_record.deleted_at IS NULL"


def test_period_uses_kst_day_bounds_with_to_inclusive() -> None:
    sql, params = _sql(CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 23)))

    assert "call_record.call_datetime >= " in sql
    assert "call_record.call_datetime < " in sql
    assert datetime(2026, 11, 1, tzinfo=KST) in params.values()
    assert datetime(2026, 11, 24, tzinfo=KST) in params.values()


def test_keyword_searches_three_columns_with_escaped_wildcards() -> None:
    sql, params = _sql(CallListQuery(q=" 50%_ "))

    for column in (
        "analysis.question_summary",
        "analysis.action_summary",
        "transcript.corrected_text",
    ):
        assert f"{column} ILIKE" in sql
    assert "ESCAPE '/'" in sql
    assert set(params.values()) == {"50/%/_"}


def test_blank_keyword_is_ignored() -> None:
    query = CallListQuery(q="   ")

    assert query.keyword is None
    assert _sql(query)[0] == "call_record.deleted_at IS NULL"


def test_multi_value_and_exact_match_filters() -> None:
    sql, params = _sql(
        CallListQuery(
            status=[CallStatus.FAILED, CallStatus.NEEDS_REVIEW],
            category=[Category.COMPLAINT],
            agent="김상담",
            client="가나상사",
            metadata_incomplete=False,
        )
    )

    assert "call_record.status IN" in sql
    assert "analysis.category IN" in sql
    assert "call_record.agent_name = " in sql
    assert "call_record.client_company = " in sql
    assert "call_record.metadata_incomplete IS false" in sql
    assert params["agent_name_1"] == "김상담"
    assert params["category_1"] == ["불만"]  # API 코드 → DB 저장 값


def test_from_after_to_raises_validation_error() -> None:
    with pytest.raises(AppError) as exc_info:
        CallListQuery(from_=date(2026, 11, 2), to=date(2026, 11, 1))

    assert exc_info.value.code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.detail == {
        "errors": [
            {
                "loc": ["query", "from"],
                "msg": "from은 to보다 늦을 수 없습니다",
                "type": "date_range",
            }
        ]
    }


def test_same_day_range_is_allowed() -> None:
    CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 1))
```

`tests/unit/test_call_schemas.py`
```python
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.schemas.call import CallDetail, CallListItem

_BASE: dict[str, Any] = {
    "id": 1,
    "source_type": "DRIVE",
    "original_name": "a.wav",
    "duration_sec": 60,
    "agent_name": None,
    "client_company": None,
    "call_datetime": None,
    "metadata_incomplete": True,
    "status": "STORED",
    "status_changed_at": datetime(2026, 11, 23, 5, 30, 5, 999_999, tzinfo=UTC),
    "retry_count": 0,
    "created_at": datetime(2026, 11, 23, 5, 0, tzinfo=UTC),
}


def test_list_item_maps_db_category_to_code() -> None:
    item = CallListItem.model_validate(
        {**_BASE, "category": "불만", "question_summary": "q", "action_status": None}
    )

    assert item.model_dump(mode="json")["category"] == "COMPLAINT"


def test_list_item_without_analysis_has_null_fields() -> None:
    item = CallListItem.model_validate(
        {**_BASE, "category": None, "question_summary": None, "action_status": None}
    )

    body = item.model_dump(mode="json")
    assert body["category"] is None
    assert body["call_datetime"] is None
    assert body["status_changed_at"] == "2026-11-23T14:30:05+09:00"


def test_detail_reads_orm_like_objects_and_serializes() -> None:
    analysis = SimpleNamespace(
        category="교육 내용",
        confidence=Decimal("0.850"),
        question_summary="환불 문의",
        action_summary="환불 처리",
        follow_up_required=None,
        action_status=None,
        entities=None,
        needs_review=None,
        raw_json={"secret": "x"},
    )
    log = SimpleNamespace(
        step="REGISTER", status="SUCCESS", message=None, created_at=_BASE["created_at"]
    )
    detail = CallDetail.model_validate(
        {**_BASE, "transcript": None, "analysis": analysis, "processing_log": [log]}
    )

    body = detail.model_dump(mode="json")
    assert body["transcript"] is None
    assert body["analysis"]["category"] == "EDUCATION"
    assert body["analysis"]["confidence"] == 0.85
    assert body["analysis"]["follow_up_required"] is None
    assert body["analysis"]["action_status"] is None
    assert "raw_json" not in body["analysis"]
    assert body["processing_log"] == [
        {
            "step": "REGISTER",
            "status": "SUCCESS",
            "message": None,
            "created_at": "2026-11-23T14:00:00+09:00",
        }
    ]
    assert "object_key" not in body
    assert "file_hash" not in body
```

`tests/unit/test_calls_api.py`
```python
"""라우터 단위 테스트: 서비스를 가짜로 바꿔 DB 없이 파라미터 검증·응답 형식·OpenAPI를 확인한다."""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_call_service
from app.core.errors import AppError, ErrorCode
from app.schemas.call import CallDetail, CallListItem, CallListQuery, CallStatus, Category, LogStep
from app.schemas.common import Page, PageParams

_DETAIL = CallDetail.model_validate(
    {
        "id": 1,
        "source_type": "WEB",
        "original_name": "a.wav",
        "duration_sec": None,
        "agent_name": "김상담",
        "client_company": None,
        "call_datetime": datetime(2026, 11, 23, 5, 30, tzinfo=UTC),
        "metadata_incomplete": False,
        "status": "REGISTERED",
        "status_changed_at": datetime(2026, 11, 23, 5, 30, tzinfo=UTC),
        "retry_count": 0,
        "created_at": datetime(2026, 11, 23, 5, 30, tzinfo=UTC),
        "transcript": None,
        "analysis": None,
        "processing_log": [],
    }
)


class FakeCallService:
    def __init__(self) -> None:
        self.calls: list[tuple[CallListQuery, PageParams]] = []

    def list_calls(self, query: CallListQuery, page: PageParams) -> Page[CallListItem]:
        self.calls.append((query, page))
        return Page(items=[], page=page.page, size=page.size, total=0)

    def get_call(self, call_id: int) -> CallDetail:
        if call_id == 1:
            return _DETAIL
        raise AppError(ErrorCode.NOT_FOUND)


@pytest.fixture
def fake() -> FakeCallService:
    return FakeCallService()


@pytest.fixture
def api(build_app: Callable[..., FastAPI], fake: FakeCallService) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_call_service] = lambda: fake
    with TestClient(app) as client:
        yield client


def _error_locs(body: dict[str, Any]) -> list[list[str | int]]:
    return [err["loc"] for err in body["detail"]["errors"]]


def test_list_defaults(api: TestClient, fake: FakeCallService) -> None:
    response = api.get("/api/calls")

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    query, page = fake.calls[0]
    assert query == CallListQuery()
    assert query.sort == "-created_at"
    assert (page.page, page.size) == (1, 20)


def test_list_parses_all_params(api: TestClient, fake: FakeCallService) -> None:
    response = api.get(
        "/api/calls",
        params=[
            ("from", "2026-11-01"),
            ("to", "2026-11-23"),
            ("category", "COMPLAINT"),
            ("category", "INQUIRY"),
            ("agent", "김상담"),
            ("client", "가나상사"),
            ("status", "FAILED"),
            ("status", "NEEDS_REVIEW"),
            ("q", "환불"),
            ("metadata_incomplete", "true"),
            ("sort", "-call_datetime"),
            ("page", "2"),
            ("size", "100"),
        ],
    )

    assert response.status_code == 200
    query, page = fake.calls[0]
    assert query == CallListQuery(
        from_=date(2026, 11, 1),
        to=date(2026, 11, 23),
        category=[Category.COMPLAINT, Category.INQUIRY],
        agent="김상담",
        client="가나상사",
        status=[CallStatus.FAILED, CallStatus.NEEDS_REVIEW],
        q="환불",
        metadata_incomplete=True,
        sort="-call_datetime",
    )
    assert (page.page, page.size) == (2, 100)


@pytest.mark.parametrize(
    ("params", "loc"),
    [
        ({"sort": "id"}, ["query", "sort"]),
        ({"sort": "agent_name"}, ["query", "sort"]),
        ({"size": "101"}, ["query", "size"]),
        ({"page": "0"}, ["query", "page"]),
        ({"status": "DONE"}, ["query", "status", 0]),
        ({"category": "질의"}, ["query", "category", 0]),
        ({"from": "2026/11/01"}, ["query", "from"]),
        ({"q": "가" * 101}, ["query", "q"]),
        ({"metadata_incomplete": "maybe"}, ["query", "metadata_incomplete"]),
        ({"from": "2026-11-02", "to": "2026-11-01"}, ["query", "from"]),
    ],
)
def test_list_invalid_params_return_422(
    api: TestClient, fake: FakeCallService, params: dict[str, str], loc: list[str | int]
) -> None:
    response = api.get("/api/calls", params=params)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert loc in _error_locs(body)
    assert fake.calls == []


def test_q_with_100_chars_is_allowed(api: TestClient) -> None:
    assert api.get("/api/calls", params={"q": "가" * 100}).status_code == 200


def test_unknown_param_stale_is_ignored(api: TestClient, fake: FakeCallService) -> None:
    assert api.get("/api/calls", params={"stale": "true"}).status_code == 200
    assert fake.calls[0][0] == CallListQuery()


def test_get_call_returns_detail(api: TestClient) -> None:
    response = api.get("/api/calls/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["call_datetime"] == "2026-11-23T14:30:00+09:00"
    assert body["transcript"] is None
    assert body["analysis"] is None
    assert body["processing_log"] == []


def test_get_call_not_found(api: TestClient) -> None:
    response = api.get("/api/calls/2")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }


@pytest.mark.parametrize("call_id", ["abc", "0", "9223372036854775808"])
def test_get_call_invalid_id_returns_422(api: TestClient, call_id: str) -> None:
    response = api.get(f"/api/calls/{call_id}")

    assert response.status_code == 422
    assert ["path", "call_id"] in _error_locs(response.json())


# ---------------------------------------------------------------- OpenAPI


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    return build_app().openapi()


def test_openapi_list_calls(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/calls"]["get"]
    params = {p["name"]: p["schema"] for p in operation["parameters"]}

    assert operation["operationId"] == "list_calls"
    assert operation["tags"] == ["calls"]
    assert set(params) == {
        "from", "to", "category", "agent", "client", "status", "q",
        "metadata_incomplete", "sort", "page", "size",
    }  # fmt: skip
    assert params["sort"]["default"] == "-created_at"
    assert set(params["sort"]["enum"]) == {
        "call_datetime", "-call_datetime", "created_at", "-created_at",
        "status_changed_at", "-status_changed_at",
    }  # fmt: skip
    assert params["status"]["anyOf"][0]["type"] == "array"
    assert params["q"]["anyOf"][0]["maxLength"] == 100
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/Page_CallListItem_")


def test_openapi_get_call(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/calls/{call_id}"]["get"]

    assert operation["operationId"] == "get_call"
    assert set(operation["responses"]) == {"200", "404", "422", "500"}


def test_openapi_enums(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    assert set(schemas["CallStatus"]["enum"]) == set(CallStatus)
    assert set(schemas["Category"]["enum"]) == set(Category)
    assert set(schemas["LogStep"]["enum"]) == set(LogStep)
    assert "is_stale" not in schemas["CallListItem"]["properties"]
    assert "processing_log" in schemas["CallDetail"]["required"]
```

`tests/integration/conftest.py`
```python
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
```
- import 순서(`from alembic.config import Config`는 서드파티 묶음, `from alembic import command`는 퍼스트파티 묶음)는 `ruff check --fix`의 결과다. `backend/alembic/` 디렉터리 때문에 isort가 `alembic`을 로컬로 보기도 해서 생기며, 기존 `alembic/env.py`도 같은 모양이다.

`tests/integration/factories.py`
```python
"""최소 테스트 데이터 헬퍼 (임시 — C-05 팩토리로 대체 예정).

`now()`는 트랜잭션 시작 시각이라 한 테스트 안에서 기본값 `created_at`이 모두 같다.
정렬을 검증할 때는 시각을 직접 넘긴다.
"""

from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord, ProcessingLog, Transcript

_seq = count(1)


def make_call(session: Session, **overrides: Any) -> CallRecord:
    n = next(_seq)
    values: dict[str, Any] = {
        "source_type": "DRIVE",
        "object_key": f"audio/{n}.wav",
        "original_name": f"call-{n}.wav",
        "file_hash": f"{n:064x}",
        **overrides,
    }
    call = CallRecord(**values)
    session.add(call)
    session.flush()
    return call


def make_transcript(session: Session, call: CallRecord, **overrides: Any) -> Transcript:
    values: dict[str, Any] = {
        "segments": [{"speaker": "AGENT", "start": 0.0, "end": 1.5, "text": "안녕하세요"}],
        **overrides,
    }
    transcript = Transcript(call_id=call.id, **values)
    session.add(transcript)
    session.flush()
    return transcript


def make_analysis(session: Session, call: CallRecord, **overrides: Any) -> Analysis:
    values: dict[str, Any] = {"category": "질의", "raw_json": {}, **overrides}
    analysis = Analysis(call_id=call.id, **values)
    session.add(analysis)
    session.flush()
    return analysis


def make_log(session: Session, call: CallRecord, **overrides: Any) -> ProcessingLog:
    values: dict[str, Any] = {"step": "REGISTER", "status": "SUCCESS", **overrides}
    log = ProcessingLog(call_id=call.id, **values)
    session.add(log)
    session.flush()
    return log
```

`tests/integration/test_call_repository.py`
```python
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.repositories.call_repository import CallRepository
from app.schemas.call import CallListQuery, CallStatus, Category
from app.schemas.common import KST
from tests.integration.factories import make_analysis, make_call, make_log, make_transcript

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 0, 0, tzinfo=UTC)


def _ids(session: Session, **query: Any) -> list[int]:
    rows = CallRepository(session).list_calls(CallListQuery(**query), offset=0, limit=100)
    return [row[0].id for row in rows]


def test_soft_deleted_calls_are_excluded(db_session: Session) -> None:
    alive = make_call(db_session)
    make_call(db_session, deleted_at=T0)
    repo = CallRepository(db_session)

    assert _ids(db_session) == [alive.id]
    assert repo.count_calls(CallListQuery()) == 1


def test_period_filter_uses_kst_day_and_includes_to(db_session: Session) -> None:
    before = make_call(db_session, call_datetime=datetime(2026, 11, 22, 23, 59, 59, tzinfo=KST))
    first = make_call(db_session, call_datetime=datetime(2026, 11, 23, 0, 0, tzinfo=KST))
    last = make_call(db_session, call_datetime=datetime(2026, 11, 24, 23, 59, 59, tzinfo=KST))
    after = make_call(db_session, call_datetime=datetime(2026, 11, 25, 0, 0, tzinfo=KST))
    make_call(db_session, call_datetime=None, metadata_incomplete=True)

    ids = _ids(db_session, from_=date(2026, 11, 23), to=date(2026, 11, 24))

    assert sorted(ids) == [first.id, last.id]
    assert before.id not in ids and after.id not in ids


def test_only_from_or_only_to(db_session: Session) -> None:
    old = make_call(db_session, call_datetime=datetime(2026, 11, 1, 12, 0, tzinfo=KST))
    new = make_call(db_session, call_datetime=datetime(2026, 11, 20, 12, 0, tzinfo=KST))

    assert _ids(db_session, from_=date(2026, 11, 10)) == [new.id]
    assert _ids(db_session, to=date(2026, 11, 10)) == [old.id]


def test_status_and_category_multi_value(db_session: Session) -> None:
    failed = make_call(db_session, status="FAILED")
    review = make_call(db_session, status="NEEDS_REVIEW")
    make_call(db_session, status="STORED")
    complaint = make_call(db_session)
    make_analysis(db_session, complaint, category="불만")
    inquiry = make_call(db_session)
    make_analysis(db_session, inquiry, category="질의")

    status_ids = _ids(db_session, status=[CallStatus.FAILED, CallStatus.NEEDS_REVIEW])
    assert sorted(status_ids) == [failed.id, review.id]
    assert _ids(db_session, category=[Category.COMPLAINT]) == [complaint.id]


def test_agent_and_client_exact_match(db_session: Session) -> None:
    kim = make_call(db_session, agent_name="김상담", client_company="가나상사")
    make_call(db_session, agent_name="김상담2", client_company="가나상사")

    assert _ids(db_session, agent="김상담") == [kim.id]
    assert len(_ids(db_session, client="가나상사")) == 2
    assert _ids(db_session, client="가나") == []


def test_metadata_incomplete_filter(db_session: Session) -> None:
    incomplete = make_call(db_session, metadata_incomplete=True)
    complete = make_call(db_session)

    assert _ids(db_session, metadata_incomplete=True) == [incomplete.id]
    assert _ids(db_session, metadata_incomplete=False) == [complete.id]


def test_keyword_searches_summaries_and_corrected_text(db_session: Session) -> None:
    by_question = make_call(db_session)
    make_analysis(db_session, by_question, question_summary="요금 환불 요청")
    by_action = make_call(db_session)
    make_analysis(db_session, by_action, action_summary="환불 처리 완료")
    by_transcript = make_call(db_session)
    make_transcript(db_session, by_transcript, corrected_text="고객이 환불을 원함")
    only_segments = make_call(db_session)
    make_transcript(
        db_session,
        only_segments,
        segments=[{"speaker": "CUSTOMER", "start": 0, "end": 1, "text": "환불"}],
    )
    make_call(db_session)

    ids = _ids(db_session, q="환불")

    assert sorted(ids) == [by_question.id, by_action.id, by_transcript.id]
    assert CallRepository(db_session).count_calls(CallListQuery(q="환불")) == 3


def test_keyword_is_case_insensitive_and_escapes_wildcards(db_session: Session) -> None:
    upper = make_call(db_session)
    make_analysis(db_session, upper, question_summary="ARS 50% 할인")
    other = make_call(db_session)
    make_analysis(db_session, other, question_summary="ARS 500 할인")

    assert sorted(_ids(db_session, q="ars")) == [upper.id, other.id]
    assert _ids(db_session, q="50%") == [upper.id]
    assert _ids(db_session, q="5_0") == []


def test_default_sort_is_created_at_desc_with_id_tiebreak(db_session: Session) -> None:
    a = make_call(db_session, created_at=T0)
    b = make_call(db_session, created_at=T0)
    c = make_call(db_session, created_at=T0 + timedelta(minutes=1))

    assert _ids(db_session) == [c.id, b.id, a.id]
    assert _ids(db_session, sort="created_at") == [a.id, b.id, c.id]


def test_call_datetime_sort_puts_nulls_last_both_directions(db_session: Session) -> None:
    none = make_call(db_session, call_datetime=None)
    early = make_call(db_session, call_datetime=T0)
    late = make_call(db_session, call_datetime=T0 + timedelta(hours=1))

    assert _ids(db_session, sort="call_datetime") == [early.id, late.id, none.id]
    assert _ids(db_session, sort="-call_datetime") == [late.id, early.id, none.id]


def test_offset_limit_and_count_out_of_range(db_session: Session) -> None:
    for _ in range(3):
        make_call(db_session)
    repo = CallRepository(db_session)

    assert len(repo.list_calls(CallListQuery(), offset=2, limit=2)) == 1
    assert repo.list_calls(CallListQuery(), offset=10, limit=2) == []
    assert repo.count_calls(CallListQuery()) == 3


def test_list_row_has_analysis_columns_or_none(db_session: Session) -> None:
    analysed = make_call(db_session, created_at=T0 + timedelta(minutes=1))
    make_analysis(db_session, analysed, category="불만", question_summary="요약")
    make_call(db_session, created_at=T0)

    rows = CallRepository(db_session).list_calls(CallListQuery(), offset=0, limit=10)

    assert [tuple(row[1:]) for row in rows] == [("불만", "요약", "OPEN"), (None, None, None)]


def test_get_call_excludes_deleted_and_logs_are_ordered(db_session: Session) -> None:
    call = make_call(db_session)
    deleted = make_call(db_session, deleted_at=T0)
    second = make_log(db_session, call, step="QUEUE", created_at=T0 + timedelta(seconds=1))
    first = make_log(db_session, call, step="REGISTER", created_at=T0)
    make_log(db_session, deleted)
    repo = CallRepository(db_session)

    assert repo.get_call(call.id) is call
    assert repo.get_call(deleted.id) is None
    assert repo.get_call(999_999) is None
    assert [log.id for log in repo.list_logs(call.id)] == [first.id, second.id]
```

`tests/integration/test_calls_api.py`
```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.factories import make_analysis, make_call, make_log, make_transcript

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)


def test_list_calls_end_to_end(api: TestClient, db_session: Session) -> None:
    call = make_call(
        db_session, call_datetime=T0, agent_name="김상담", status="STORED", created_at=T0
    )
    make_analysis(db_session, call, category="불만", question_summary="환불 문의")
    make_call(db_session, deleted_at=T0)

    response = api.get("/api/calls", params={"q": "환불", "size": 10})

    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["size"], body["total"]) == (1, 10, 1)
    item = body["items"][0]
    assert item["id"] == call.id
    assert item["call_datetime"] == "2026-11-23T14:30:05+09:00"
    assert item["category"] == "COMPLAINT"
    assert item["action_status"] == "OPEN"
    assert "object_key" not in item


def test_list_calls_page_beyond_last_returns_empty_items(
    api: TestClient, db_session: Session
) -> None:
    make_call(db_session)

    body = api.get("/api/calls", params={"page": 5}).json()

    assert body["items"] == []
    assert body["total"] == 1


def test_get_call_detail_end_to_end(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session)
    make_transcript(db_session, call)
    make_analysis(db_session, call, confidence=Decimal("0.857"), raw_json={"x": 1})
    make_log(db_session, call, created_at=T0)

    response = api.get(f"/api/calls/{call.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"]["segments"][0]["speaker"] == "AGENT"
    assert body["analysis"]["confidence"] == 0.857
    assert "raw_json" not in body["analysis"]
    assert body["processing_log"][0]["created_at"] == "2026-11-23T14:30:05+09:00"


def test_get_call_without_children(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session)

    body = api.get(f"/api/calls/{call.id}").json()

    assert body["transcript"] is None
    assert body["analysis"] is None
    assert body["processing_log"] == []


def test_get_deleted_call_is_404(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session, deleted_at=T0)

    response = api.get(f"/api/calls/{call.id}")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
```

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 1 | 테스트 #1~5 작성 → `config.py`, `schemas/call.py`의 enum·`CATEGORY_DB_VALUES` | `uv run pytest tests/unit/test_config.py tests/unit/test_call_enums.py` |
| 2 | #6~14 작성 → `CallListQuery`·`CallSort`, `repositories/call_repository.py`의 함수 3개 | `uv run pytest tests/unit/test_call_query.py` |
| 3 | #15~17 작성 → 응답 모델·`CategoryOut` | `uv run pytest tests/unit/test_call_schemas.py` |
| 4 | #18~28 작성 → `core/db.py`, `services/call_service.py`, `api/deps.py`, `api/web/calls.py`, `main.py`, `conftest.py` 이름 변경 | `uv run pytest tests/unit` (이 시점에 `test_committed_openapi_is_up_to_date`만 실패) |
| 5 | `openapi.json` 재생성 | `uv run pytest -m "not integration"` 전부 통과 |
| 6 | 통합 픽스처·헬퍼, #30~47 작성 → `CallRepository` 메서드 | Docker Desktop 또는 `TEST_DATABASE_URL`이 있으면 `uv run pytest -m integration`, 없으면 skip 확인 |
| 7 | 공용 문서(`convention.md`, `architecture.md`, `README.md`) 수정 | 리뷰 |
| 8 | 전체 검증(§8) | |

---

## 8. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (DB 없으면 통합 18개 skip)
uv run pytest -m "not integration"   # 단위만
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
통합 테스트를 실제로 돌리는 방법(둘 중 하나)
```bash
# A. Docker Desktop 실행 중이면 그대로 (testcontainers가 postgres:16을 띄움)
uv run pytest -m integration

# B. 이미 떠 있는 테스트 전용 DB 사용 (예: docker-compose.dev.yml의 db에 callcenter_test DB를 만든 경우)
TEST_DATABASE_URL=postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter_test uv run pytest -m integration
```
- PowerShell: `$env:TEST_DATABASE_URL = "postgresql+psycopg://..."; uv run pytest -m integration`
- 기대: 단위 145(기존 100 + 신규 45) 통과, 통합 18 통과(또는 DB 없으면 18 skip).

---

## 9. 확인 필요

### 9.1 A (C-04 스키마·모델 소유, C-05 테스트 기반, R-02·R-04·R-07·R-11) — 모델·마이그레이션 변경은 A에게 요청
| # | 항목 | 현재 / 요청 |
|---|---|---|
| A1 | **`category` 저장 값** | 현재 한글 5개(BE-A05 확정 전 임시). API는 영문 코드라 `CATEGORY_DB_VALUES`로 변환 중. 저장 값을 영문 코드로 바꿀지(리서치 §7 #5 권장), 바꾸면 이 표를 항등으로 바꾸는 작업이 같은 PR에 필요. 한글을 유지하면 R-07(적재)·W-09·W-10·W-11도 이 표를 써야 함 |
| A2 | **유형 값 이름 일치** | 표의 한글 값(`질의`, `불만`, `건의`, `교육 내용`, `기타 문의`)이 `CATEGORIES`와 글자까지 같아야 함(`test_call_enums.py`가 검사). 공백 포함 `교육 내용`·`기타 문의` 유지 여부 |
| A3 | analysis NULL 허용 컬럼 | `follow_up_required`·`needs_review`·`action_status`가 NULL 허용(DEFAULT만). 응답이 `bool \| None`·`ActionStatus \| None`이 됨. NOT NULL 전환 요청(리서치 §7 #11) — 바꾸면 응답 타입을 좁힐 수 있음(OpenAPI 변경) |
| A4 | `processing_log(call_id)` 인덱스 | 없음. 상세 조회마다 `WHERE call_id = ?`. 추가 마이그레이션 요청(급하지 않음, 리서치 §7 #12) |
| A5 | API enum 위치 | 모델은 튜플 상수, API `StrEnum`은 `app/schemas/call.py`. R-02 상태 머신·R-04(`DuplicateFileDetail.status`)·R-07이 같은 enum을 쓰도록 위치를 합의할지(예: 모델 상수를 enum에서 만들기). 지금은 테스트로 일치만 보장 |
| A6 | `database_url` 이중 경로 | 앱은 `Settings.database_url`(이번 추가), `alembic/env.py`는 `os.environ["DATABASE_URL"]` 직접. `.env` 파일만 있고 환경 변수가 없으면 앱은 동작하고 Alembic은 `RuntimeError`. env.py가 `Settings`를 쓰게 할지 |
| A7 | `CallRecord.logs` 순서 | 관계에 `order_by`가 없어 로그는 별도 쿼리로 정렬. `order_by=ProcessingLog.created_at, id` 추가 여부(선택) |
| A8 | 테스트 기반 교체 | `tests/integration/conftest.py`(`create_schema`·`database_url`·`engine`·`db_session`·`api`)·`factories.py`를 C-05가 대체·유지할지. `create_schema`가 `alembic.ini` 대신 `Config()`를 쓰는 이유(§3.3: `fileConfig`가 앱 로거를 끔) 공유 |
| A9 | `pyproject.toml` `integration` 마커 설명 | "실제 PostgreSQL(testcontainers)" — `TEST_DATABASE_URL`도 쓰므로 C-05에서 문구 조정 여부 |
| A10 | 정체 판단(R-11) 반환 형태 | `is_stale`·`stale` 추가 시 `filter_conditions`에 조건 하나, `CallBase`에 필드 하나를 더하는 구조를 가정 |

### 9.2 GenAI·STT 파트 (E-03 등, A 경유)
| # | 항목 | 이 계획의 가정 |
|---|---|---|
| G1 | **`corrected_text`가 비어 있을 수 있음** | 교정(STT-05, P1)이 없으면 NULL → 전사 내용이 키워드 검색에 걸리지 않음. 대안(적재 시 `segments` 텍스트를 이어 붙인 검색용 컬럼, 또는 교정 없을 때 원문을 `corrected_text`에 저장)은 별도 합의 |
| G2 | `segments` 항목 구조 | `{speaker, start, end, text}` 가정, 응답은 `list[dict]`. 확정 후 `Segment` 모델로 좁힘(OpenAPI 변경) |
| G3 | `entities` 형태 | STT 출력 스키마(`stt/schema/call_schema.json`)에 맞춰 `[{type, value}]` 배열 또는 null로 변경(`EntityOut`). `type`은 문자열로 받아 값이 추가돼도 500이 나지 않게 함. 적재 시 배열 그대로 저장 필요(ORM 타입 힌트 `dict`는 A 소관) |
| G4 | GenAI 유형 출력 값 | 현재 DB 저장 값이 한글이므로 GenAI 결과 → DB는 한글 그대로일 수 있음. A1 결정에 따라 R-07의 변환 위치가 정해짐 |

### 9.3 프론트 (공지·확인)
| # | 항목 | 내용 |
|---|---|---|
| F1 | **`is_stale` 없음** | 목록·상세 모두 R-11 이후 추가. 그전에는 `stale` 파라미터를 보내도 무시된다(에러 아님). 프론트 초안 타입은 필수로 가정 |
| F2 | 키워드 검색 범위 | 질문 요약·조치 요약·`corrected_text`. 프론트 목(mock)은 `segments` 텍스트를 검색 — 결과가 다를 수 있음(G1) |
| F3 | 담당자·고객사 | 정확히 일치. 선택 상자 값 그대로 |
| F4 | `category` | 영문 코드만(`category=질의`는 422), 반복 파라미터로 다중 값 가능 |
| F5 | 새 422 | `from > to`(`loc: ["query", "from"]`, `type: "date_range"`), `q` 101자 이상, `call_id`가 0·음수·BIGINT 초과 |
| F6 | 응답 필드 | 목록·상세에 `created_at` 포함(초안에 없음). 상세 `transcript`는 `segments`만, `analysis`에 `raw_json`·`prompt_version` 없음, `follow_up_required`·`needs_review`·`action_status`는 null 가능(A3), 로그는 `step`·`status`(enum)·`message`·`created_at`(오래된 순) |
| F7 | 경로 표기 | OpenAPI 경로는 `/api/calls/{call_id}`(규약 표의 `{id}`와 같은 의미) |

### 9.4 환경
| # | 항목 | 내용 |
|---|---|---|
| E1 | **Docker Desktop 설치 후 통합 테스트 1회 실행** | 사전 검증 서버에는 `pg_trgm`이 없었다. `postgres:16`에서 `alembic upgrade head` 전체(확장·trgm GIN 인덱스)와 18개 통합 테스트 통과를 확인 |
| E2 | DB 로캘 | 공식 `postgres:16` 이미지는 `en_US.utf8`. 운영 DB 로캘이 `C`이면 한글 trgm 인덱스가 효과 없음(결과는 같음, 리서치 §4.3) |

---

## 10. 구현 시 주의
1. `app/models/*`·`alembic/*`는 고치지 않는다. 필요하면 §9.1에 추가하고 A에게 요청한다.
2. `CallListQuery`에 필드를 추가할 때는 `Annotated[..., Query()]`로 선언한다. `list[...]`를 `Query()` 없이 두면 본문으로 해석된다.
3. 응답 모델은 `model_construct()`로 만들지 않는다(규약 §5.1). 검증을 건너뛰면 유형 코드 변환·`KstDatetime`이 적용되지 않는다.
4. 422·`AppError`의 `msg`·`detail`에 요청 값(`q` 등)을 넣지 않는다(규약 §3.4.3). 접근 로그는 이미 쿼리 문자열을 남기지 않는다.
5. `TEST_DATABASE_URL`에는 개발 DB를 넣지 않는다. `create_schema`가 `downgrade base`를 한다.
6. 통합 테스트 데이터의 시각은 aware 값만 쓴다. 정렬 검증은 `created_at`을 직접 지정한다(같은 트랜잭션의 `now()`는 같다). `category`는 DB 저장 값(한글)으로 넣는다.
7. `repositories/call_repository.py`의 `# type: ignore[return-value]` 한 곳은 outer join으로 분석 컬럼이 None이 될 수 있어 매핑 타입보다 넓은 `ListRow`로 돌려주기 위한 것이다. 다른 곳에 늘리지 않는다.

## 11. 리뷰 반영

1. `from`·`to`에 허용 범위 `2000-01-01`~`2100-12-31`(`DATE_MIN`·`DATE_MAX`, `schemas/call.py`)을 둔다. `to=9999-12-31`일 때 `to + 1일` 계산이 넘쳐 500이 나던 문제를 막고, 범위 밖은 422로 응답한다. 테스트: `test_list_invalid_params_return_422`에 3건, `test_date_range_bounds_are_allowed`.
2. `agent`·`client`가 빈 값(공백만 있는 값 포함)이면 필터를 걸지 않는다(`q`와 같은 처리). 테스트: `test_blank_agent_and_client_are_ignored`.
3. 운영에서 `DATABASE_URL`이 빠져도 개발 기본값으로 뜨는 점은 코드를 바꾸지 않고 §9 A6 논의 때 함께 정한다.
4. 규약 `convention.md` §4.3에 1·2를 반영했다.
