# Research — 백엔드 / DB / 서버 인프라

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.2 (A안 반영) |
| 작성일 | 2026-11-23 |
| 근거 | `prd.md` v0.1 — §4 아키텍처, §6 데이터 요구사항, §7 비기능, §9 역할 ① |
| 담당 | 역할 ① 백엔드 / DB / 서버 인프라 (1~2명) |
| 목적 | 기술 선택지 비교, 권장안 제시, 설계 초안, 구현 작업 목록 정리 |

> **[확인 필요]**: 작성자의 사전 지식을 기반으로 작성했고 공식 문서로 아직 재확인하지 않은 항목입니다. 구현 전에 해당 공식 문서로 검증하세요(특히 UiPath API의 엔드포인트명, 헤더명, 권한 Scope).
>
> **인입 방식 결정 반영 (v0.2):** 녹취 파일 인입은 **A안(RPA 직접 감지)**으로 확정되었습니다(`input_flow.md`). 이에 따라 백엔드는 Orchestrator API를 호출하지 않고 Webhook도 받지 않으며, 로봇이 호출하는 등록·적재 API를 제공하는 역할만 맡습니다.

---

## 1. 담당 범위 (PRD 기준)

| PRD 요구사항 | 백엔드 작업 |
|---|---|
| IN-03 | 웹 업로드 API → 파일을 `inbox/`에 저장 (DB 등록 없음) |
| IN-04~06 | 로봇 등록 API, 음성 사본 저장, 메타데이터·해시 기록, 중복 감지 |
| RPA-01·04 | 로봇이 전사·분석 결과·실패 사유를 적재·보고하는 API |
| RPA-06 | 재처리 대상 조회 API, `RETRY_REQUESTED` 상태 관리 |
| §6.1 / §6.2 | DB 스키마, JSON 검증 |
| §6.3 | REST API 전체 (웹용·로봇용) |
| WEB-01~09 지원 | 통계 집계, 조건 검색, 음성 스트리밍, 엑셀 다운로드, 재처리 요청, 정체 건 표시 |
| §7 | 접근 통제(로그인 없음), PII 보호, 로그·추적성, 배포 환경 |

---

## 2. 기술 스택 선정

### 2.1 Backend 프레임워크

| 후보 | 장점 | 단점 | 적합도 |
|---|---|---|---|
| **FastAPI (Python)** | Pydantic으로 GenAI JSON 스키마 검증이 간단, OpenAPI 문서 자동 생성(프론트 협업 용이), 엑셀(openpyxl)·LLM SDK·STT SDK 등 Python 생태계 활용, 학습 곡선 낮음 | 대규모 엔터프라이즈 구조화는 직접 설계 필요 | ★★★ |
| Spring Boot (Java) | 엔터프라이즈 표준, 안정성 | 보일러플레이트 많음, 단기 프로젝트에 공수 큼 | ★★ |
| NestJS (TypeScript) | 프론트와 언어 통일 | 엑셀·AI 관련 생태계가 Python보다 약함 | ★★ |

**권장: FastAPI + SQLAlchemy 2.x + Alembic(마이그레이션) + Pydantic v2**
- 이유: 이 프로젝트 백엔드의 핵심은 "파일 수신 → 상태 관리 → JSON 적재 → 집계/조회"이고, 무거운 비즈니스 로직이 없음.

### 2.2 DB

| 후보 | 장점 | 단점 |
|---|---|---|
| **PostgreSQL** | `JSONB`로 분석 결과·개체명·화자별 전사를 그대로 저장하면서 인덱싱 가능, `pg_trgm`으로 한글 부분 일치 검색, 집계 쿼리 강력, 무료 | — |
| MySQL | 익숙한 팀원 많음, JSON 타입 지원 | JSON 인덱싱·전문 검색이 상대적으로 불편 |
| SQLite | 설치 불필요, MVP 빠름 | 동시 쓰기(로봇 + 웹) 약함, 운영 부적합 |

**권장: PostgreSQL 16** (로컬 개발은 Docker 컨테이너로 동일 환경 유지)

### 2.3 파일 스토리지

| 단계 | 방식 | 비고 |
|---|---|---|
A안에서는 저장소가 두 종류로 나뉜다.

| 저장소 | 소유 | 용도 |
|---|---|---|
| 입력 폴더 (`inbox/ processing/ done/ failed/`) | RPA (Google Drive 공유 드라이브 **[가정]**) | 사용자 직접 업로드, 로봇 감지·처리 상태 표시. 백엔드는 웹 업로드 시 `inbox/`에 **업로드만** 함 |
| 음성 사본 저장소 | 백엔드 | 로봇 등록 시 함께 받은 음성 사본 보관 → 웹 재생, 재처리 시 로봇 다운로드 |

음성 사본 저장소 단계

| 단계 | 방식 | 비고 |
|---|---|---|
| Phase 1~2 | 서버 로컬 디스크 (Docker 볼륨) | 단순, 일 수십~백여 건 규모에 충분 |
| Phase 3 (선택) | Google Cloud Storage | 클라우드 배포 시. 서명 URL로 재생 |

**권장: 음성 사본 저장소는 인터페이스 뒤에 두고 `LocalStorage` → `GCSStorage` 구현 교체**
- DB에는 절대 경로 대신 `object_key`를 저장하고, 입력 위치는 `source_type`(DRIVE = 사용자 직접 / WEB = 웹 업로드 대행) + `source_ref`(Drive 파일 ID)로 별도 기록
- 원본 폴더의 파일이 이동·삭제되어도 서버 사본으로 재생·재처리가 가능하도록 원본과 독립시킨다

### 2.4 기타

| 영역 | 권장 | 비고 |
|---|---|---|
| 컨테이너 | Docker + docker-compose (api, db) | 팀원 로컬 환경 통일 |
| 리버스 프록시 | 사용하지 않음 (Uvicorn 직접 노출) | IP 제한은 VM 방화벽 + 앱 미들웨어, 업로드 용량 제한은 앱에서 처리 (`back_stack.md` §6.1) |
| 실시간 상태 갱신 | 프론트 폴링(3~5초), 필요 시 SSE | WebSocket은 양방향이 필요 없어 과함 |
| 클라우드 폴더 접근 | Google Drive API + 서비스 계정 (`google-api-python-client`) | 웹 업로드 → `inbox/` 업로드 전용. 서비스 계정은 개인 "내 드라이브" 저장 용량이 없으므로 **공유 드라이브** 사용 **[확인 필요]**. 업로드 시 `appProperties.source=web` 기록 |
| 백그라운드 작업 | FastAPI `BackgroundTasks` 수준으로 충분 | 무거운 처리는 UiPath 로봇이 담당하므로 Celery 불필요 |
| 엑셀 생성 | openpyxl | 상세 §6 참조 |

---

## 3. 시스템 연동 구조

### 3.1 핵심 결정: 누가 DB에 쓰는가?

| 방식 | 설명 | 평가 |
|---|---|---|
| A. 로봇이 DB 직접 접속 (UiPath Database Activities) | 구현 빠름 | 스키마 결합도 높음, 검증 로직 중복, DB 계정이 로봇에 노출 |
| **B. 로봇 → 백엔드 REST API 호출** | 로봇은 HTTP Request 액티비티로 결과 JSON을 POST | 검증·상태 전이·로그를 백엔드 한 곳에서 관리 ✅ |

**권장: B.** DB의 유일한 쓰기 주체는 백엔드이고, 로봇은 API 클라이언트로 동작.

### 3.2 처리 흐름 (A안: RPA 직접 감지)

```
[사용자] --직접 업로드--> [클라우드 inbox/ (Google Drive)]
[Web] --POST /api/uploads--> [Backend] --Drive API 업로드--> [클라우드 inbox/]

[Dispatcher 로봇] (Time Trigger, N분 주기)
   │ 1) inbox/ → processing/ 이동 (선점)
   │ 2) POST /api/robot/calls (음성 + 메타데이터 + 해시) → call_id   (REGISTERED, 중복이면 409)
   │ 3) Orchestrator Queue Item 추가 {call_id}
   │ 4) PATCH /api/robot/calls/{id}/status → QUEUED
   │ 5) GET /api/robot/calls?status=RETRY_REQUESTED → 재처리 건 Queue 재등록
   ▼
[Performer 로봇] (Queue Trigger)
   │ 6) STT → PUT /api/robot/calls/{id}/transcript                (STT_DONE)
   │ 7) GenAI·PII 마스킹 → PUT /api/robot/calls/{id}/analysis     (STORED / NEEDS_REVIEW)
   │ 8) 엑셀 기입 / CRM 입력, 원본 파일 done/ 이동
   │ ✕ 실패 시 POST /api/robot/calls/{id}/logs (FAILED), 원본 failed/ 이동

[Web] --GET /api/calls?status=... (폴링)--> 상태 표시, 정체 건 경고
```

상세 흐름·보완책은 `input_flow.md` §3, §6 참조.

### 3.3 백엔드에서 빠지는 것

| 항목 | 이유 |
|---|---|
| Orchestrator OAuth 인증, AddQueueItem / StartJobs 호출 | Queue 등록을 Dispatcher 로봇이 수행 |
| Webhook 수신 엔드포인트·HMAC 검증·`webhook_event` 테이블 | 정상·실패 모두 로봇이 API로 직접 보고 |
| Orchestrator 관련 비밀값(Client Secret, Webhook Secret) | 불필요 |

로봇 크래시처럼 로봇이 보고하지 못하는 실패는 **정체 감지**로 확인한다: `QUEUED`·`STT_DONE` 상태가 일정 시간(예: 30분 **[가정]**) 이상 지속된 건을 대시보드에 경고로 표시하고, 웹에서 재처리 요청으로 복구한다(§4.3). 필요해지면 이후 `job.faulted` Webhook만 선택적으로 추가할 수 있다.

### 3.4 로봇 ↔ 백엔드 연동 요점

| 항목 | 내용 |
|---|---|
| 인증 | 모든 `/api/robot/*`는 `X-API-Key` 헤더. 키는 Orchestrator Credential Asset에 저장 |
| 등록 요청 | multipart: `file`, `file_hash`(SHA-256), `original_name`, `source_type`, `source_ref`, `call_datetime`, `agent_name`, `client_company` |
| 중복 | 해시 중복 시 `409 DUPLICATE_FILE`(기존 건 정보는 에러 본문의 `detail.existing_id`·`detail.status`). 로봇은 기존 건의 상태에 따라 처리: `REGISTERED`(이전 실행이 Queue 추가 전에 중단됨) → Queue 추가부터 이어서 진행 / `STORED`·`NEEDS_REVIEW` → `done/` / `FAILED` → `failed/` / 그 외(처리 중) → 그대로 둠 (`input_flow.md` §6.2) |
| 메타데이터 누락 | 파일명에서 담당자·통화 일시를 못 뽑으면 해당 필드를 비워 등록 → 서버가 `metadata_incomplete=true` 표시, 처리는 정상 진행, 웹에서 보정 |
| 멱등 | `PUT` 적재 API는 같은 내용 재전송 시 결과 동일. Queue 재시도로 같은 단계가 다시 호출돼도 안전 |
| 타임아웃·재시도 | 로봇의 HTTP 호출은 타임아웃 30초, 5xx·네트워크 오류 시 2회 재시도 후 Queue 예외 처리 **[가정]** |
| 추적 | 로봇은 응답의 `X-Request-Id`와 `call_id`를 UiPath 로그에 기록 |
| 업로드 크기 | 등록 요청에 음성 파일이 포함되므로 API 업로드 한도(예: 100MB)를 로봇 요청에도 동일 적용 |

---

## 4. DB 설계 (PRD §6.1 상세화)

### 4.1 테이블

```sql
-- 상담 건
CREATE TABLE call_record (
  id              BIGSERIAL PRIMARY KEY,
  source_type     VARCHAR(20)  NOT NULL,          -- DRIVE(사용자 직접) | WEB(웹 업로드 대행)
  source_ref      TEXT,                           -- Drive 파일 ID
  object_key      TEXT         NOT NULL,          -- 서버 음성 사본 키
  original_name   TEXT         NOT NULL,
  file_hash       CHAR(64)     NOT NULL,          -- SHA-256, 중복 감지
  file_size       BIGINT,
  duration_sec    INT,
  agent_name      VARCHAR(50),                    -- 파일명 파싱 실패 시 NULL 허용 (담당자 3명 → agent 테이블로 분리 가능)
  client_company  VARCHAR(100),
  call_datetime   TIMESTAMPTZ,
  metadata_incomplete BOOLEAN  NOT NULL DEFAULT false, -- agent_name 또는 call_datetime 누락 시 true, 웹에서 보정하면 false
  status          VARCHAR(20)  NOT NULL DEFAULT 'REGISTERED',
  status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(), -- 정체 감지 기준 시각
  retry_count     INT          NOT NULL DEFAULT 0, -- 재처리 횟수 (Queue Reference: call_id-retryN)
  queue_item_id   BIGINT,
  deleted_at      TIMESTAMPTZ,                    -- 소프트 삭제
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_call_hash ON call_record(file_hash) WHERE deleted_at IS NULL;
CREATE INDEX ix_call_dt ON call_record(call_datetime);
CREATE INDEX ix_call_status ON call_record(status, status_changed_at);

-- 전사
CREATE TABLE transcript (
  id              BIGSERIAL PRIMARY KEY,
  call_id         BIGINT NOT NULL UNIQUE REFERENCES call_record(id),
  segments        JSONB  NOT NULL,   -- [{speaker:"AGENT|CUSTOMER", start, end, text}] (PII 마스킹 후)
  corrected_text  TEXT,              -- GenAI 교정본
  stt_engine      VARCHAR(50),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 분석 결과
CREATE TABLE analysis (
  id                 BIGSERIAL PRIMARY KEY,
  call_id            BIGINT NOT NULL UNIQUE REFERENCES call_record(id),
  category           VARCHAR(20) NOT NULL,  -- 질의|불만|건의|교육 내용|기타 문의
  confidence         NUMERIC(4,3),
  question_summary   TEXT,
  action_summary     TEXT,
  follow_up_required BOOLEAN DEFAULT false,
  action_status      VARCHAR(20) DEFAULT 'OPEN',  -- OPEN|DONE (미조치 건 집계용)
  entities           JSONB,
  raw_json           JSONB NOT NULL,        -- GenAI 원본 응답 보존
  prompt_version     VARCHAR(20),
  needs_review       BOOLEAN DEFAULT false,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_analysis_cat ON analysis(category);

-- 처리 로그
CREATE TABLE processing_log (
  id                  BIGSERIAL PRIMARY KEY,
  call_id             BIGINT REFERENCES call_record(id),
  step                VARCHAR(30) NOT NULL,   -- REGISTER|QUEUE|STT|GENAI|STORE|EXCEL|CRM|RETRY
  status              VARCHAR(20) NOT NULL,   -- SUCCESS|FAIL|RETRY
  message             TEXT,
  orchestrator_job_id VARCHAR(64),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 수정 이력 (P2)
CREATE TABLE edit_history (
  id         BIGSERIAL PRIMARY KEY,
  call_id    BIGINT NOT NULL REFERENCES call_record(id),
  field      VARCHAR(50) NOT NULL,
  before_val TEXT,
  after_val  TEXT,
  editor     VARCHAR(50),               -- 로그인 없음 → 자유 입력
  edited_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 4.2 설계 판단

| 이슈 | 결정 |
|---|---|
| 5대 유형 복수 분류 (PRD 미결 #3) | 우선 단일 `category` 컬럼. 복수 허용으로 결정되면 `analysis_category(call_id, category)` 조인 테이블로 분리 |
| 카테고리 값 | DB `CHECK` 제약 또는 Python `Enum`으로 5개 값만 허용. 한글 값을 그대로 저장하되 API에는 코드(`INQUIRY/COMPLAINT/SUGGESTION/EDUCATION/ETC`) 병행 검토 |
| 삭제 | 소프트 삭제(`deleted_at`). 원본 음성 파일은 보존 기간 경과 후 배치로 물리 삭제 |
| 재분석 | 재분석 시 `analysis` 덮어쓰기 + 이전 값은 `edit_history`/`processing_log`에 기록. 이력 보존이 중요하면 버전 테이블로 확장 |
| 한글 검색 | `pg_trgm` + GIN 인덱스로 `question_summary`, `action_summary`, `corrected_text` 부분 일치 검색. 형태소 수준 검색이 필요해지면 그때 검토 |

### 4.3 상태 전이

```
REGISTERED → QUEUED → STT_DONE → STORED
     │          │         └──→ NEEDS_REVIEW (confidence < 임계값) ──(사람 검토)──→ STORED
     └──────────┴─────────┴──→ FAILED
FAILED / STORED / NEEDS_REVIEW ──(웹 재처리 요청)──→ RETRY_REQUESTED ──(Dispatcher 재등록)──→ QUEUED
REGISTERED / QUEUED / STT_DONE (정체 시) ──(웹 재처리 요청)──→ RETRY_REQUESTED
```
- 상태 전이는 백엔드 서비스 계층 한 곳에서만 수행하고, 허용되지 않은 전이는 409 반환
- **정체 건 복구:** `REGISTERED`·`QUEUED`·`STT_DONE`에서 `status_changed_at`이 `STALE_THRESHOLD_MIN`을 넘긴 건은 웹에서 재처리 요청 가능. 정체되지 않은(처리 중인) 건은 409
- 재처리 후 이전 Queue 건이 뒤늦게 적재를 시도하면 상태가 맞지 않아 409로 거절될 수 있다 (정상 동작, 새 Queue 건이 처리)
- 메타데이터 누락(`metadata_incomplete`)은 처리 상태와 별개의 표시로 관리한다 (`NEEDS_REVIEW`는 AI 신뢰도 전용)
- 분석 적재와 저장이 한 트랜잭션이므로 `ANALYZED` 상태는 두지 않음
- 백엔드는 로봇을 직접 실행할 수 없으므로 재처리는 "표시 → Dispatcher가 다음 주기에 가져감" 방식 (PRD RPA-06, WEB-09)

---

## 5. API 설계 (PRD §6.3 상세화)

### 5.1 웹(프론트)용

| Method | Endpoint | 설명 | 비고 |
|---|---|---|---|
| POST | `/api/uploads` | multipart 업로드(다중) → 클라우드 `inbox/`에 업로드 | DB 등록 없음. 용량·확장자·MIME 검증. 응답은 202 "접수됨" |
| GET | `/api/calls` | 목록 | `from,to,category,agent,client,status,q,stale,metadata_incomplete,page,size,sort` |
| GET | `/api/calls/{id}` | 상세 (call + transcript + analysis + logs) | |
| PATCH | `/api/calls/{id}` | 분석 결과·메타데이터 수정, 검토 완료 | 분석(유형·요약·조치·조치 상태)과 메타데이터(담당자·고객사·통화 일시) 필드 모두 선택적으로 수정. `editor` 필드 포함, edit_history 기록 |
| DELETE | `/api/calls/{id}` | 소프트 삭제 | |
| POST | `/api/calls/{id}/retry` | 재처리 요청 | 상태를 `RETRY_REQUESTED`로만 변경. 실패·검토 필요·저장 완료 건과 정체 건 대상 |
| GET | `/api/calls/{id}/audio` | 음성 스트리밍 | HTTP Range 지원(재생 위치 이동). GCS면 서명 URL로 리다이렉트 |
| GET | `/api/stats/summary` | KPI (총 건수, 유형별, 미조치, 검토 필요, 메타데이터 확인 필요, 실패, 정체) | `from,to` |
| GET | `/api/stats/trend` | 기간별 추이 | `granularity=day|week|month` |
| GET | `/api/stats/breakdown` | 담당자별/고객사별 | `by=agent|client` |
| GET | `/api/reports/excel` | 엑셀 다운로드 | `from,to` |
| GET | `/api/events` | SSE 상태 스트림 (선택) | |

### 5.2 로봇(UiPath)용 — `/api/robot/*`, API Key 필수

| Method | Endpoint | 호출자 | 설명 |
|---|---|---|---|
| POST | `/api/robot/calls` | Dispatcher | 등록 (음성 사본 + 메타데이터 + 해시) → `{call_id}`, 중복 시 `409 DUPLICATE_FILE` (`detail.existing_id`, `detail.status`) |
| PATCH | `/api/robot/calls/{id}/status` | Dispatcher | `QUEUED` 전이 (`queue_item_id` 포함). `REGISTERED`·`RETRY_REQUESTED`에서만 허용 |
| GET | `/api/robot/calls?status=RETRY_REQUESTED` | Dispatcher | 재처리 대상 조회 (`call_id`, `retry_count` 반환) |
| GET | `/api/robot/calls/{id}/audio` | Performer | 재처리 시 음성 사본 다운로드 |
| PUT | `/api/robot/calls/{id}/transcript` | Performer | 전사 결과 적재 |
| PUT | `/api/robot/calls/{id}/analysis` | Performer | 분석 JSON 적재 (Pydantic으로 PRD §6.2 스키마 검증, 실패 시 422 → 로봇이 재시도/예외 처리) |
| POST | `/api/robot/calls/{id}/logs` | 둘 다 | 단계 로그, 실패 보고(`FAILED` 전이) |

### 5.3 공통 규약
- 응답 포맷, 에러 포맷(`{code, message, detail}`), 페이지네이션 형식을 프론트와 먼저 합의
- OpenAPI(`/docs`)를 프론트·RPA 담당과 공유 계약서로 사용
- PUT 적재 API는 멱등(같은 내용 재전송 시 동일 결과)

---

## 6. 엑셀 보고서 책임 분리

PRD상 엑셀 대시보드 생성은 역할 ④(RPA)이지만, 웹 다운로드(XL-05)는 백엔드 API가 필요함.

| 방식 | 설명 | 평가 |
|---|---|---|
| A. RPA가 생성한 파일을 백엔드가 저장·제공 | 정기 보고서(일/주/월)는 로봇이 생성 후 업로드 | 정기 보고서에 적합 |
| B. 백엔드가 템플릿 기반 즉시 생성 (openpyxl) | 사용자가 지정한 임의 기간 다운로드 | 임의 기간 조회에 적합 |

**권장: A + B 병행.** 역할 ④가 만든 **템플릿(.xlsx, 차트·슬라이서 포함)을 공유**하고, 백엔드는 템플릿의 데이터 시트만 채워 반환. 차트는 데이터 시트 범위를 참조하도록 템플릿을 설계하면 openpyxl로 데이터만 바꿔도 차트가 갱신됨.
- 주의: openpyxl은 기존 파일의 **슬라이서·피벗 캐시를 보존하지 못할 수 있음 [확인 필요]** → 슬라이서가 필수라면 B 대신 A(로봇이 Excel 앱으로 생성)로 처리하거나, 테이블(ListObject) 기반 + 열기 시 새로 고침 방식 검토

---

## 7. 보안 및 개인정보 (로그인 없음 전제)

| 위협 | 대응 |
|---|---|
| 외부인의 대시보드 접근 | 사내망/VPN 전용 배포, VM 방화벽 IP 허용 목록. 클라우드 배포 시 Cloud IAP 등 앞단 접근 제어 검토 |
| 로봇용 API 오남용 | `/api/robot/*`는 `X-API-Key` 필수, 키는 Orchestrator Credential Asset에 저장 |
| 웹 업로드로 `inbox/` 오염 | 확장자·MIME 검증 후에만 업로드, 서비스 계정은 최소 권한(공유 드라이브 "기여자" 등)만 부여 **[확인 필요]** |
| 서비스 계정 키 유출 | 키 파일(JSON)은 Git 제외·서버에만 보관, 주기적 교체. 클라우드 배포 시 Workload Identity로 키 파일 제거 |
| 클라우드의 녹취 원본 노출 | 공유 드라이브 멤버 최소화, `done/` 보관 기간 단축, 링크 공유 금지 |
| 대량 삭제·오수정 | 소프트 삭제, 수정 이력, 일일 DB 백업 |
| PII 노출 | DB에는 마스킹된 전사만 저장(마스킹은 역할 ③). 원본 음성은 PII를 포함하므로 접근 로그 기록 및 보존 기간 설정 **[보존 기간 결정 필요]** |
| 악성 파일 업로드 | 확장자 + MIME + 매직 바이트 검증, 최대 용량 제한(예: 100MB), 저장 파일명은 UUID로 재생성 |
| 비밀 정보 관리 | `.env` + 환경 변수, Git 커밋 금지, 로봇 API Key·DB 비밀번호·서비스 계정 키 분리 |

---

## 8. 인프라 / 배포

### 8.1 환경

| 환경 | 구성 |
|---|---|
| 로컬 개발 | docker-compose: `api`(FastAPI, hot reload), `db`(PostgreSQL), `adminer`/pgAdmin(선택). 웹 업로드 대상은 로컬 폴더 또는 테스트용 Drive 폴더로 대체 |
| 테스트/시연 | 사내 VM 1대에 docker-compose (api, db). 로봇 PC에서 접근 가능한 네트워크여야 함 |
| 클라우드(확장) | Cloud Run(api) + Cloud SQL(PostgreSQL) + GCS — Phase 3 (선택) |

### 8.2 네트워크 체크 포인트
- 통신 방향은 **로봇 → 백엔드 단방향**. Orchestrator → 백엔드 인바운드(Webhook)가 없으므로 백엔드를 사내망에만 두어도 됨
- 로봇(Unattended Robot PC) → 백엔드 API 접근 경로 확보
- 백엔드 VM → Google Drive API(`www.googleapis.com`) 아웃바운드 HTTPS 허용 (웹 업로드용)
- 로봇 PC → Google Drive 접근 (RPA의 감지·다운로드·폴더 이동)

### 8.3 운영
- 헬스 체크: `GET /health` (DB 연결 포함)
- 구조화 로그(JSON), 요청 ID를 로봇 로그와 연결(`X-Request-Id`)
- DB 일일 백업(`pg_dump`), 스토리지 백업 정책
- 마이그레이션은 Alembic으로만 수행

---

## 9. 구현 작업 목록

구현 작업 목록과 담당자 배정은 **`features.md`로 일원화**한다. (이전 WBS 초안 B-01~B-15는 `features.md`의 기능 ID로 대체되어 삭제함)

### 타 역할과의 인터페이스 합의 항목 (킥오프 직후 우선 확정)
| 상대 | 합의 항목 |
|---|---|
| ② 프론트 | API 응답·에러·페이지네이션 포맷, 통계 API 형태, 업로드 UX("접수됨" 안내), 재처리 버튼·정체 경고 표시 |
| ③ GenAI/STT | 분석 JSON 스키마, 전사 `segments` 포맷, PII 마스킹 범위, 카테고리 코드 |
| ④ RPA | 로봇 API 호출 순서(등록 → QUEUED → 적재)·재시도 정책, 409 응답 상태별 처리, 파일명 규칙·메타데이터 누락 시 전송 방식, 폴더 구조, Dispatcher 주기, 로봇 PC IP, 엑셀 템플릿 |

---

## 10. 미결 사항 (백엔드 관점)

1. 클라우드 서비스 확정(Google Drive 가정), 공유 드라이브 사용 가능 여부, 서버용 서비스 계정 발급·권한
2. 서버 배포 위치: 사내 VM vs 클라우드 → 로그인 없는 접근 통제 방식 결정
3. 5대 유형 단일/복수 분류 → 스키마 영향
4. 원본 음성·전사 보존 기간 및 삭제 정책
5. 엑셀 슬라이서 필수 여부 → 엑셀 생성 주체(로봇 vs 백엔드) 결정
6. 담당자·고객사 마스터 데이터 관리 여부 (자유 입력 vs 테이블 관리)
7. 일평균 통화량·파일 크기 → 스토리지 용량·업로드 제한값 산정
8. 정체 감지 기준 시간 (Dispatcher 주기 + 평균 처리 시간 기준)

---

## 11. 참고 자료
- FastAPI: https://fastapi.tiangolo.com
- SQLAlchemy 2.0: https://docs.sqlalchemy.org/en/20/
- Alembic: https://alembic.sqlalchemy.org
- PostgreSQL JSONB / pg_trgm: https://www.postgresql.org/docs/current/datatype-json.html , https://www.postgresql.org/docs/current/pgtrgm.html
- UiPath Orchestrator (Queue, Time Trigger, Credential Asset — 역할 ④ 참고용): https://docs.uipath.com/orchestrator
- openpyxl: https://openpyxl.readthedocs.io
- Google Drive API (파일 업로드, 공유 드라이브, 서비스 계정): https://developers.google.com/drive/api/guides/about-sdk **[공유 드라이브·서비스 계정 제약 확인 필요]**
