# 기능 목록 — 백엔드 / DB (2인 분담)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.2 (검토 반영) |
| 작성일 | 2026-11-23 |
| 근거 | `prd.md`, `input_flow.md`, `research.md` §4·§5, `architecture.md` §5·§14, `back_stack.md` |

> 이름이 정해지면 "백엔드 A / B"를 실제 이름으로 바꿔 주세요.

## 한눈에 보기

| | 백엔드 A | 백엔드 B |
|---|---|---|
| **영역** | 로봇 연동·데이터 적재 | 웹 API·조회·통계 |
| **주요 기능** | 로봇 인증, 상태 관리, 음성 사본 저장, 등록·적재·실패 보고 API, 재처리 대상 조회, 정체 감지 | 목록·검색, 상세, 수정·삭제, 메타데이터 보정, 재처리 요청, 음성 재생, 웹 업로드(Drive), 통계, 엑셀 다운로드 |
| **기반·운영** | 프로젝트 셋업, DB 스키마·마이그레이션, 테스트 기반, 컨테이너, 데이터 정리 배치 | API 규약, 공통 모듈(설정·로그·에러·CORS·요청 크기 제한), 헬스 체크, VM 배포·방화벽, 백업 |
| **기능 수** | 17개 | 17개 |
| **주로 협업할 파트** | RPA, GenAI·STT | 프론트엔드 |
| **먼저 요청할 것** | GenAI 결과 스키마, 전사 포맷, 로봇 PC IP | 서비스 계정·공유 드라이브 권한, 엑셀 템플릿, 사내 VM |
| **주 수정 위치** | `api/robot/`, `services/robot_service.py`·`state_machine.py`, `models/`, `alembic/`, `infra/storage/` | `api/web/`, `services/call_service.py`·`stats_service.py`·`report_service.py`·`upload_service.py`, `infra/inbox/`, `core/` |

---

## 1. 분담 원칙

- **데이터가 들어오는 쪽은 A, 나가는 쪽은 B**로 나눠 서로 다른 파일(`api/robot/` vs `api/web/`)을 주로 수정하게 한다 → 충돌 최소화
- 공유 자원(DB 스키마, 상태 머신, API 규약)은 **소유자 1명 + 상대방 리뷰**로 운영
- 각자 자기 기능의 테스트를 함께 작성한다

### 우선순위·Phase 기준
| 구분 | 의미 |
|---|---|
| **P0** | 필수 — 1차 릴리스 전에 반드시 구현 |
| **P1** | 중요 — 일정이 부족하면 뒤로 미룰 수 있음 |
| **P2** | 선택 |
| **Phase 1** | MVP: 로봇이 등록·적재하는 흐름 + 기본 조회 (`architecture.md` §14) |
| **Phase 2** | 웹 연동: 수정·삭제·재처리·통계·엑셀·업로드·배포 |
| **Phase 3** | 선택 확장 (미배정) |

우선순위는 "얼마나 중요한가", Phase는 "언제 만드는가"를 뜻한다.

---

## 2. 기능 목록

### 2.1 기반 / 공통

| ID | 기능 | 상세 | 우선순위 | Phase | 담당 | 선행 |
|---|---|---|---|---|---|---|
| C-01 | 프로젝트 셋업 | 레포 구조, uv·`pyproject.toml`, Ruff·mypy·pre-commit, 개발용 docker-compose(api, db, adminer) | P0 | 1 | **A** | — |
| C-02 | 공통 모듈 | 설정(`Settings`), structlog JSON 로그·`X-Request-Id`, 공통 예외 → 에러 응답 매핑, **CORS**(`CORS_ORIGINS`), **요청 크기 제한 미들웨어**(`MAX_UPLOAD_MB` 초과 시 413, 모든 API 공통) | P0 | 1 | **B** | C-01 |
| C-03 | API 규약 | 응답·에러 코드·페이지네이션 형식 확정(`architecture.md` §7.2), OpenAPI 공유 방식, 프론트와 화면별 응답 형태 합의 | P0 | 1 | **B** (A 리뷰) | — |
| C-04 | DB 스키마 + 마이그레이션 | `research.md` §4.1 DDL 기준 5개 테이블. `call_record`의 `metadata_incomplete`·`status_changed_at`·`retry_count` 포함, `agent_name`·`call_datetime` NULL 허용. 인덱스·`pg_trgm`, Alembic 초기 마이그레이션 | P0 | 1 | **A** (B 리뷰) | C-01 |
| C-05 | 테스트 기반 | pytest 설정, testcontainers PostgreSQL 픽스처, 테스트 데이터 팩토리 (B도 2단계부터 사용) | P0 | 1 | **A** | C-04 |

### 2.2 로봇 연동 / 데이터 적재 — 백엔드 A

| ID | 기능 | API / 대상 | 상세 | 우선순위 | Phase | 선행 | PRD |
|---|---|---|---|---|---|---|---|
| R-01 | 로봇 인증 | 미들웨어 | `X-API-Key` 검증(키 2개 동시 허용, 실패 401), `/api/robot/*` 로봇 PC IP 확인(`ROBOT_ALLOWED_IPS`, 실패 403) | P0 | 1 | C-02, E-04 | — |
| R-02 | 상태 머신 | `CallStateMachine` | `architecture.md` §5 전이표 구현, 허용되지 않은 전이 409, `SELECT ... FOR UPDATE`, `status_changed_at` 갱신, 전이마다 `processing_log` 기록. **정체 판단**(`status_changed_at` > `STALE_THRESHOLD_MIN`)으로 정체된 `REGISTERED`·`QUEUED`·`STT_DONE`의 재처리 전이 허용 | P0 | 1 | C-04 | §6.1 |
| R-03 | 음성 사본 저장소 | `AudioStorage` / `LocalStorage` | 저장·열기(Range)·삭제 인터페이스, UUID 키 | P0 | 1 | C-01 | IN-04 |
| R-04 | 등록 | `POST /api/robot/calls` | multipart 수신, 형식 검증(크기 제한은 C-02), 음성 사본 저장 → `REGISTERED`, 실패 시 사본 삭제(보상 처리). **해시 중복 시 `409 {existing_id, status}`** (Dispatcher가 상태별로 이어서 처리, `input_flow.md` §6.2). **메타데이터 누락 시 `metadata_incomplete=true`**로 등록 | P0 | 1 | R-01~03 | IN-04~06 |
| R-05 | 상태 변경 | `PATCH /api/robot/calls/{id}/status` | `QUEUED` 전이(`REGISTERED`·`RETRY_REQUESTED`에서만), `queue_item_id` 기록 | P0 | 1 | R-02 | RPA-03 |
| R-06 | 전사 적재 | `PUT /api/robot/calls/{id}/transcript` | `segments` 검증, UPSERT(멱등) → `STT_DONE` | P0 | 1 | R-02, E-03 | RPA-04 |
| R-07 | 분석 적재 | `PUT /api/robot/calls/{id}/analysis` | GenAI 결과 Pydantic 스키마 검증(5대 유형 Enum), 신뢰도 임계값 → `STORED` / `NEEDS_REVIEW`, UPSERT(멱등) | P0 | 1 | R-02, E-02 | RPA-01, AI-05·07 |
| R-08 | 로그·실패 보고 | `POST /api/robot/calls/{id}/logs` | 단계 로그 기록, FAIL 시 `FAILED` 전이. 로봇은 Queue 재시도 한도를 다 쓴 뒤에만 FAIL 보고 (E-04 합의) | P0 | 1 | R-02 | RPA-04 |
| R-09 | 재처리 대상 조회 | `GET /api/robot/calls?status=RETRY_REQUESTED` | `call_id`, `retry_count` 목록 반환 (Queue Reference `call_id-retryN` 생성용) | P1 | 2 | R-02 | RPA-06 |
| R-10 | 재처리용 음성 다운로드 | `GET /api/robot/calls/{id}/audio` | 서버 음성 사본 전송 | P1 | 2 | R-03 | RPA-06 |
| R-11 | 정체 감지 | 서비스 함수 | `REGISTERED`·`QUEUED`·`STT_DONE`·`RETRY_REQUESTED`에서 `STALE_THRESHOLD_MIN` 초과한 건의 조회·건수 함수. B의 목록 필터(W-01)·통계(W-09)에서 사용 | **P0** | 2 | R-02 | WEB-05 |
| R-12 | 로봇 시뮬레이션 테스트 | 테스트 스크립트 | 등록 → QUEUED → 적재 / 실패 / 재처리 / **409 상태별 재등록** / **정체 건 재처리** 흐름을 UiPath 없이 검증, RPA 파트에 요청 예시 JSON 제공 | P0 | 1 | R-04~08 | — |

### 2.3 웹 API — 백엔드 B

| ID | 기능 | API / 대상 | 상세 | 우선순위 | Phase | 선행 | PRD |
|---|---|---|---|---|---|---|---|
| W-01 | 상담 목록·검색 | `GET /api/calls` | 기간·유형·담당자·고객사·상태·키워드(`pg_trgm`) 필터, **`metadata_incomplete` 필터**, **`stale` 필터**(R-11 사용, R-11 완료 후 추가), 페이지네이션·정렬, 소프트 삭제 제외 | P0 | 1 | C-03, C-04, C-05 | WEB-02 |
| W-02 | 상담 상세 | `GET /api/calls/{id}` | call + transcript + analysis + processing_log 묶어 반환 | P0 | 1 | C-04, C-05 | WEB-03 |
| W-03 | 분석 결과 수정·검토 완료 | `PATCH /api/calls/{id}` | 유형·요약·조치·조치 상태 수정, `editor` 입력, `edit_history` 기록, `NEEDS_REVIEW` → `STORED` (R-02 사용) | P0 | 2 | R-02 | WEB-04·08 |
| W-04 | 삭제 | `DELETE /api/calls/{id}` | 소프트 삭제(`deleted_at`) | P0 | 2 | C-04 | WEB-04 |
| W-05 | 재처리 요청 | `POST /api/calls/{id}/retry` | `FAILED`·`NEEDS_REVIEW`·`STORED` 건과 **정체 건**을 `RETRY_REQUESTED`로 전이 (R-02 사용), `retry_count` +1. 정체되지 않은 처리 중 건은 409 | P1 | 2 | R-02 | WEB-09 |
| W-06 | 음성 재생 | `GET /api/calls/{id}/audio` | HTTP Range 스트리밍 (R-03 사용), 접근 로그 기록 | P0 | 2 | R-03 | WEB-03 |
| W-07 | 웹 업로드 | `POST /api/uploads` | 다중 파일, 형식 검증(크기 제한은 C-02), `DriveInboxWriter`로 클라우드 `inbox/` 업로드(`appProperties.source=web`), DB 등록 없음, 202 응답 | P1 | 2 | C-02, **W-08** | IN-03 |
| W-08 | Drive 연동 모듈 | `InboxWriter` | `DriveInboxWriter`(서비스 계정, 공유 드라이브), 개발용 `LocalInboxWriter`, 재시도·503 처리, 헬스 체크용 접근 확인 함수 | P1 | 2 | C-01, **E-01** | IN-03 |
| W-09 | 통계 — 요약 | `GET /api/stats/summary` | 총 건수, 유형별, 미조치, 검토 필요, **메타데이터 확인 필요**, 실패, 정체(R-11 사용) | P0 | 2 | R-11 | WEB-01 |
| W-10 | 통계 — 추이·분류 | `GET /api/stats/trend`, `/api/stats/breakdown` | 일/주/월 추이, 담당자별·고객사별 집계 | P0 | 2 | C-04 | WEB-01 |
| W-11 | 엑셀 다운로드 | `GET /api/reports/excel` | RPA 파트 템플릿에 데이터 시트 채워 반환, 최대 기간 제한 | P1 | 2 | W-10, E-05 | XL-05 |
| **W-12** | **메타데이터 보정** | `PATCH /api/calls/{id}` | 담당자·고객사·통화 일시 수정(상태 변화 없음), 담당자·통화 일시가 채워지면 `metadata_incomplete=false`, `edit_history` 기록. W-03과 같은 엔드포인트의 메타데이터 필드 | P0 | 2 | C-04 | IN-05, WEB-04 |

### 2.4 배포 / 운영

| ID | 기능 | 상세 | 우선순위 | Phase | 담당 | 선행 |
|---|---|---|---|---|---|---|
| O-01 | 운영용 컨테이너 | Dockerfile(멀티 스테이지, non-root), 운영 docker-compose(api, db), `restart` 정책 | P0 | 2 | **A** | C-01 |
| O-02 | 헬스 체크 | `GET /health` — DB, 음성 저장소, Drive `inbox/` 접근 확인 | P1 | 2 | **B** | R-03, W-08 |
| O-03 | VM 배포·접근 통제 | 사내 VM 배포, 방화벽(8000 포트 사내망·로봇 PC만), 요청 크기 제한 동작 확인, 서비스 계정 키 배치 | P0 | 2 | **B** | O-01, E-06 |
| O-04 | 백업 | `pg_dump` 일 1회 cron, 음성 사본 볼륨 백업, 복구 절차 문서 | P1 | 2 | **B** | O-03 |
| **O-05** | **데이터 정리 배치** | 일 1회: 보존 기간 지난 음성 사본·소프트 삭제 데이터 물리 삭제, 90일 지난 `processing_log` 정리 (`architecture.md` §6.3) | P2 | 2 | **A** | R-03, C-04, E-07 |

### 2.5 선택 (Phase 3, 미배정)

| ID | 기능 | 비고 |
|---|---|---|
| X-01 | SSE 실시간 상태 (`GET /api/events`) | 폴링으로 부족할 때 |
| X-02 | `GCSStorage` 음성 사본 저장소 | 클라우드 배포 시 |
| X-03 | 클라우드 배포 (Cloud Run + Cloud SQL) | 필요 시 |

---

## 3. 외부 준비 사항 (다른 파트·관리자에게 먼저 요청)

| ID | 필요한 것 | 요청 대상 | 필요한 기능 | 요청 담당 | 시점 |
|---|---|---|---|---|---|
| E-01 | Google 서비스 계정 발급 + 공유 드라이브 멤버 추가 | 프로젝트 관리자 / Google Workspace 관리자 | W-08, W-07, O-02 | **B** | 1주차 (승인에 시간 걸림) |
| E-02 | GenAI 결과 JSON 스키마 확정 | GenAI·STT 파트 | R-07 | **A** | 1주차 |
| E-03 | 전사 `segments` 포맷 확정 | GenAI·STT 파트 | R-06 | **A** | 1주차 |
| E-04 | 로봇 PC IP, 409 상태별 처리 방식, FAIL 보고 시점 합의 | RPA 파트 | R-01, R-04, R-08 | **A** | 1주차 |
| E-05 | 엑셀 보고서 템플릿(.xlsx) | RPA 파트 | W-11 | **B** | 3주차 전 |
| E-06 | 사내 VM, 방화벽 설정 권한 | 인프라 담당 / 관리자 | O-03 | **B** | 3주차 전 |
| E-07 | 음성·전사 보존 기간 결정 | 팀 / 관리자 | O-05 | **A** | Phase 2 중 |

---

## 4. 담당별 기능 ID

| | 백엔드 A | 백엔드 B |
|---|---|---|
| 기반 | C-01, C-04, C-05 (3) | C-02, C-03 (2) |
| 기능 | R-01 ~ R-12 (12) | W-01 ~ W-12 (12) |
| 운영 | O-01, O-05 (2) | O-02, O-03, O-04 (3) |
| **합계** | **17개** | **17개** |
| 외부 요청 | E-02, E-03, E-04, E-07 | E-01, E-05, E-06 |

---

## 5. 서로 의존하는 지점

**B가 A의 기능을 사용**

| B의 기능 | 사용하는 A의 기능 | 합의 사항 |
|---|---|---|
| W-03 검토 완료, W-05 재처리 요청 | R-02 상태 머신 (정체 판단 포함) | 전이 함수 시그니처를 1주차에 먼저 확정 |
| W-06 음성 재생, O-02 헬스 체크 | R-03 음성 사본 저장소 | `AudioStorage.open(key, byte_range)` 인터페이스 |
| W-01 정체 필터, W-09 통계 요약 | R-11 정체 감지 | 정체 판단 기준·반환 형태 |
| W-01·02·10·12 조회·통계·보정, 테스트 | C-04 DB 스키마, C-05 테스트 기반 | 컬럼 추가는 A가 마이그레이션 작성, B 리뷰 |

**A가 B의 기능을 사용**

| A의 기능 | 사용하는 B의 기능 | 합의 사항 |
|---|---|---|
| R-01 ~ R-10 전체 | C-02 공통 모듈(에러·로그·요청 크기 제한), C-03 API 규약 | 에러 코드·로그 형식을 1주차에 먼저 확정 |

---

## 6. 진행 순서 (권장)

| 순서 | 백엔드 A | 백엔드 B |
|---|---|---|
| 1 | C-01 셋업 → C-04 스키마 → C-05 테스트 기반 / E-02·E-03·E-04 요청 | C-03 API 규약 → C-02 공통 모듈 / E-01·E-05·E-06 요청 |
| 2 | R-02 상태 머신, R-03 저장소, R-01 인증 | W-01 목록·검색(정체 필터 제외), W-02 상세 |
| 3 | R-04 ~ R-08 로봇 API, R-12 시뮬레이션 테스트 → **MVP 완료** | W-10 통계(추이·분류), W-08 Drive 모듈 → W-07 웹 업로드 |
| 4 | R-09 ~ R-11 재처리·정체 감지, O-01 컨테이너 | W-03·W-12 수정·보정, W-04 삭제, W-05 재처리 요청, W-06 음성 |
| 5 | O-05 정리 배치, RPA 파트와 실제 로봇 연동 테스트 지원 | W-09 통계 요약, W-01 정체 필터, W-11 엑셀, O-02 헬스 체크, O-03 배포, O-04 백업 |
