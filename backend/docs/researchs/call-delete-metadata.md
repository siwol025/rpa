# 상담 삭제·메타데이터 보정 리서치 — `DELETE /api/calls/{id}`, `PATCH /api/calls/{id}`(메타데이터)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-04 삭제, W-12 메타데이터 보정 — 관련: W-03(같은 PATCH, 미구현), R-02(상태 머신·행 잠금, 미구현), R-04(등록 시 `metadata_incomplete` 판정, 미구현), R-07(분석 적재), R-09·R-11, O-05 |
| 근거 | `features.md` v0.2 §2.3·§5, `architecture.md` §3·§5·§6·§7.2·§11, `docs/prd.md` IN-05·WEB-04·WEB-08·§9 리스크, `docs/input_flow.md` §5.3·§6·§7, `researchs/research.md` §4.1·§4.2·§5, `api/convention.md` v0.1, `researchs/api-convention.md`, `plans/api-convention.md`, `plans/call-list-detail.md`, `app/**`, `alembic/versions/*`, `tests/**`, `stt/step2/to_backend.py`, 원격 브랜치 `origin/front`(`4f06f4e`, 프론트 초안) |
| 검증 방법 | 문서·코드 정독, `.venv`(FastAPI 0.165.0, Pydantic 2.14.4, SQLAlchemy 2.0.58)에서 스키마·라우트 동작 실측(레포 코드는 수정하지 않음). 이 PC는 Docker 데몬에 연결되지 않아 PostgreSQL 동작은 실측하지 못함(§8.4) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다.

---

## 0. 요약 (핵심 발견)

1. **쓰기 경로가 아직 하나도 없다.** `CallService`는 조회만 하고(`app/services/call_service.py`), `get_db`는 커밋하지 않으며(`app/api/deps.py:15-20` "커밋은 서비스가 한다"), 서비스는 `Session`을 갖고 있지 않다(`CallService(CallRepository(session))`). W-04·W-12가 첫 쓰기 기능이므로 **트랜잭션·커밋 위치**를 이번에 정해야 한다.
2. **소프트 삭제 제외는 이미 한 곳에 모여 있다.** `filter_conditions()`의 첫 조건이 `deleted_at IS NULL`(`app/repositories/call_repository.py:40`)이고, 통계(W-10)도 같은 함수를 쓴다(`app/repositories/stats_repository.py:56,70`). 상세 `get_call`도 `deleted_at IS NULL`(`:97`). **W-01 목록·W-10 통계·W-02 상세는 추가 작업 없이 삭제 건을 제외한다.**
3. **삭제·PATCH의 응답 규칙은 C-03에서 이미 확정됐다.** DELETE는 `204` 본문 없음, **이미 삭제된 건도 404**(`convention.md:44`, `plans/api-convention.md` 결정 #12). PATCH는 `200` + 갱신된 상세(`convention.md:43`), "보낸 키만 변경, `null`은 비우기"(`convention.md:141`).
4. **`metadata_incomplete` 판정 기준은 문서상 "`agent_name` 또는 `call_datetime`이 NULL"**이다(`research.md:168` DDL 주석, `architecture.md:277`, `features.md` W-12). 고객사는 판정에 들어가지 않는다. 프론트 목(mock)도 같은 식으로 **양방향 재계산**한다(`!agent_name || !call_datetime`). 등록(R-04, 미구현)과 같은 함수를 써야 한다.
5. **[중요] 분석 적재(R-07)가 `call_record`의 담당자·고객사·통화 일시를 다시 쓸 수 있다.** STT 변환 모듈은 `call` 덩어리로 `agent_name`·`client_company`·`call_datetime`·`duration_sec`를 돌려준다(`stt/step2/to_backend.py:20,94-101`). R-07이 이 값을 그대로 덮어쓰면 **웹에서 보정한 값이 재처리(W-05) 후 사라진다.** A·GenAI 파트와 정책 합의가 필요하다(§9.1).
6. **`SELECT ... FOR UPDATE`를 기존 `get_call`에 그대로 붙이면 안 된다.** `get_call`은 `joinedload`(LEFT OUTER JOIN)로 transcript·analysis를 함께 읽는데, PostgreSQL은 outer join의 nullable 쪽에 `FOR UPDATE`를 허용하지 않는다(알려진 PostgreSQL 동작, 이 PC에서는 미실측). 잠금은 `call_record`만 읽는 별도 쿼리(또는 `with_for_update(of=CallRecord)` → SQL `FOR UPDATE OF call_record`, 컴파일 결과 실측)로 해야 한다.
7. **프론트 초안은 한 번의 PATCH에 분석 필드와 메타데이터 필드를 섞어 보낸다**(`CallDetailPage.tsx`의 `diff()` + `review_completed`). W-12만 먼저 배포할 때 W-03 필드를 받으면 어떻게 응답할지가 핵심 결정이다(§7 #3). FastAPI/Pydantic 기본값은 **모르는 키를 조용히 무시**(200)라서, 그대로 두면 사용자는 저장된 줄 알고 분석 수정이 사라진다.
8. **`ux_call_hash`는 `WHERE deleted_at IS NULL` 부분 유니크 인덱스다**(`app/models/call_record.py:46-51`). 삭제하면 같은 해시의 재등록이 `409 DUPLICATE_FILE`이 아니라 **새 건 201**이 된다. 처리 중 삭제 + Dispatcher 재시도(`input_flow.md` §6.1 "processing/에 남은 파일 재등록") 조합에서 삭제한 건이 새 ID로 되살아날 수 있다(§5.3).
9. **`edit_history`는 모델·마이그레이션·테스트 팩토리가 모두 준비돼 있다**(`app/models/edit_history.py`, `tests/factories.py:make_edit_history`). 컬럼은 `field VARCHAR(50)`, `before_val`·`after_val TEXT`, `editor VARCHAR(50) NULL`, `edited_at DEFAULT now()`. **`call_id` 인덱스는 없다**(조회 API가 생기면 필요, FE-18 미정).
10. **이 PC에서 Docker 데몬에 연결되지 않는다**(`docker info` 실패). 통합 테스트(`tests/integration`, `@pytest.mark.integration`)는 실행 시 skip된다. 계획 단계에서 Docker Desktop 실행 또는 `TEST_DATABASE_URL` 준비가 필요하다.

---

## 1. 현재 상태

### 1.1 코드 (재사용 지점)

| 위치 | 현재 내용 | W-04·W-12에서의 쓰임 |
|---|---|---|
| `app/models/call_record.py` | `agent_name String(50) NULL`, `client_company String(100) NULL`, `call_datetime timestamptz NULL`, `metadata_incomplete bool NOT NULL DEFAULT false`, `deleted_at timestamptz NULL`, `status`·`status_changed_at`, `TimestampMixin.updated_at`(`onupdate=func.now()`, ORM 갱신 시만), 관계 `edits` | 갱신 대상 컬럼. 길이 제한의 근거 |
| `app/models/edit_history.py` | `call_id`(FK, NOT NULL), `field`(50), `before_val`·`after_val`(TEXT), `editor`(50, NULL), `edited_at`(server default `now()`) | 보정 이력 기록. `id`·`edited_at`은 DB가 채움 |
| `alembic/versions/2026_11_24_1153-8c600ef00817_init_schema.py` | 위 컬럼 그대로. `edit_history`에 인덱스 없음, FK에 `ON DELETE` 없음 | 스키마 변경 불필요(W-04·W-12 모두 기존 컬럼만 사용) |
| `app/repositories/call_repository.py` | `filter_conditions()`(삭제 제외 포함), `list_calls`·`count_calls`, `get_call`(삭제 제외 + `joinedload` transcript·analysis), `list_logs` | 삭제 후 조회 제외는 이미 됨. **잠금 조회·이력 추가 메서드는 새로 필요** |
| `app/services/call_service.py` | `_base_fields()`, `list_calls`, `get_call`(없으면 `AppError(NOT_FOUND)`) | PATCH 응답(갱신된 상세)은 `get_call(call_id)` 재사용 가능 |
| `app/api/web/calls.py` | `APIRouter(prefix="/api/calls", tags=["calls"])`, `BIGINT_MAX`, 경로 `Path(ge=1, le=BIGINT_MAX)`, `bind_call_id`, `responses=error_responses(ErrorCode.NOT_FOUND)` | 같은 파일에 `delete_call`·`update_call` 추가. operationId = 함수 이름(전역 고유) |
| `app/api/deps.py` | `get_db`(요청당 세션, 커밋 없음), `get_call_service(session)` | 서비스에 세션(또는 커밋 수단)을 넘기는 방식 결정 필요(§7 #12) |
| `app/core/db.py` | `sessionmaker(..., expire_on_commit=False)` | 커밋 후에도 ORM 객체 속성이 남음. 단 서버 기본값(`updated_at` 등)은 다시 읽지 않음 |
| `app/schemas/call.py` | enum, `CallBase`·`CallDetail`, `DATE_MIN`·`DATE_MAX`(2000-01-01~2100-12-31) | 응답 모델 재사용. 요청 모델(`CallUpdateRequest`)은 새로 추가(규약 §5.5 입·출력 분리) |
| `app/schemas/common.py` | `KstDatetime`(오프셋 없으면 KST, JSON 출력 시 `+09:00` 초 단위), `error_responses()` | `call_datetime` 입력 타입, OpenAPI 에러 문서화 |
| `app/core/errors.py` | `AppError`, `ErrorCode.NOT_FOUND`(404)·`INVALID_STATE_TRANSITION`(409)·`VALIDATION_ERROR`(422) | 새 에러 코드 불필요 |
| `app/core/logging.py:55` | `bind_call_id(request, call_id)` | DELETE·PATCH 접근 로그에 `call_id` |

### 1.2 테스트 기반

| 위치 | 내용 |
|---|---|
| `tests/integration/conftest.py` | (임시, W-01용) `TEST_DATABASE_URL` → testcontainers `postgres:16` → skip. `create_schema`(alembic `downgrade base`→`upgrade head`), `db_session`(연결 단위 바깥 트랜잭션 + `join_transaction_mode="create_savepoint"`, 끝에 롤백), `api`(`get_db` 오버라이드한 `TestClient`) |
| `tests/integration/factories.py` | `make_call`, `make_transcript`, `make_analysis`, `make_log` (최소 값) |
| `tests/conftest.py`·`tests/factories.py` | (C-05, A) `postgres_url`·`engine`·`db`·`client` 픽스처, `make_call_record`·…·**`make_edit_history`** |
| `tests/unit/test_calls_api.py` | `FakeCallService`를 `get_call_service` 오버라이드로 주입, DB 없이 라우터·OpenAPI 검증 |
| `tests/unit/test_openapi.py:150` | `docs/api/openapi.json`이 코드와 다르면 실패 → 라우트 추가 시 `uv run python -m scripts.export_openapi`로 재생성 필요 |

- `create_savepoint` 모드라 서비스 안의 `session.commit()`은 SAVEPOINT 해제로만 동작하고 테스트 끝에 모두 롤백된다(`tests/conftest.py` 주석과 같은 방식).
- 같은 트랜잭션의 `now()`는 같은 값이다(`tests/integration/factories.py` 주석). `deleted_at`·`edited_at`을 시각 순서로 검증하려면 값을 직접 넣거나 순서 검증을 피한다.

### 1.3 브랜치·의존 기능 상태

| 기능 | 상태 | W-04·W-12 영향 |
|---|---|---|
| R-02 상태 머신(`state_machine.py`, 행 잠금) | 미구현 (`app/services/`에 없음, `origin/csj`에도 없음) | W-12는 상태 전이가 없어 필요 없음. 잠금 쿼리는 직접 작성. W-03 때 R-02와 잠금 헬퍼 공유 여부 결정 |
| R-04 등록(`metadata_incomplete` 최초 판정) | 미구현 | 판정 함수를 W-12가 먼저 만들면 R-04가 재사용해야 함 |
| R-07 분석 적재 | 미구현. 변환 모듈만 `stt/step2/to_backend.py` | 보정 값 덮어쓰기 위험(§0 #5) |
| W-09 통계 요약 | 미구현 | 삭제 제외는 `filter_conditions` 재사용 시 자동 |

---

## 2. 요구사항 정리

### 2.1 출처별 요구

| 출처 | 내용 |
|---|---|
| `features.md` W-04 | `DELETE /api/calls/{id}` — 소프트 삭제(`deleted_at`). 선행 C-04 |
| `features.md` W-12 | `PATCH /api/calls/{id}` — 담당자·고객사·통화 일시 수정(상태 변화 없음), 담당자·통화 일시가 채워지면 `metadata_incomplete=false`, `edit_history` 기록. W-03과 같은 엔드포인트 |
| `features.md` W-03 (나중) | 같은 PATCH에 유형·요약·조치·조치 상태 수정, `editor` 입력, `edit_history`, `NEEDS_REVIEW → STORED`(R-02) |
| `architecture.md` §5 표 | `PATCH (메타데이터 수정)`: **모든 상태** 허용, 상태 변화 없음 / `PATCH (검토 완료)`: `NEEDS_REVIEW`만 → `STORED` |
| `architecture.md` §5 | "동시성: 상태 변경 시 `SELECT ... FOR UPDATE`로 행 잠금". 메타데이터 누락은 상태가 아님 |
| `architecture.md` §6.3 | 전사·분석은 소프트 삭제, 물리 삭제는 음성 사본과 같은 주기(O-05 배치) |
| `architecture.md` §7.2 | `NOT_FOUND` 404 = "없음 또는 소프트 삭제됨" |
| `architecture.md` §11 | 오조작 통제: 소프트 삭제, `edit_history`, 일일 백업 |
| `prd.md` WEB-04 | AI 결과 수정, 메타데이터 보정, 건 삭제 (P0) |
| `prd.md` WEB-08 | 수정 이력(누가/언제), 로그인이 없으므로 수정자 이름 자유 입력 **[가정]** (P2) |
| `prd.md` IN-05 | 담당자(3명 중 1인)·고객사·통화 일시를 파일명에서 추출, 실패 시 빈 값으로 등록 + "메타데이터 확인 필요" |
| `prd.md` §9 리스크 | "로그인 부재 → 무단 접근·데이터 삭제: 사내망 한정, **삭제는 소프트 삭제 + 수정 이력**" |
| `research.md` §4.1 | `metadata_incomplete` 주석: "agent_name 또는 call_datetime 누락 시 true, 웹에서 보정하면 false" |
| `research.md` §5 | PATCH: 분석·메타데이터 필드 모두 선택적, `editor` 포함, edit_history 기록. DELETE: 소프트 삭제 |
| `input_flow.md` §5.3 | 메타데이터 보정: 비어 있는 담당자·고객사·통화 일시를 웹에서 수정(`metadata_incomplete` 해제) |

### 2.2 C-03 규약 중 적용되는 것 (`api/convention.md`)

| 규칙 | 위치 | 적용 |
|---|---|---|
| DELETE 204 본문 없음, 404(이미 삭제된 건 포함) | §2.2 | W-04 |
| PATCH 200 갱신된 상세, 에러 404·409·422 | §2.2 | W-12는 409가 생기지 않음(W-03 검토 완료에서 생김) |
| PATCH는 보낸 키만 변경, `null`은 비우기(허용 필드만), `model_dump(exclude_unset=True)` | §5.2 | W-12 |
| 요청 시각은 오프셋 없으면 KST, 응답은 초 단위 `+09:00`, 내부는 aware(`datetime.now(UTC)`) | §5.1 | `call_datetime` 입력, `deleted_at` 값 |
| 요청·응답 모델 분리(`CallUpdateRequest` / `CallDetail`) | §5.5 | 요청 모델 이름이 규약에 예시로 나와 있음 |
| 에러는 `AppError`로만, validator 메시지에 입력값 금지 | §3.4 | 길이·빈 값 검증 메시지 |
| 엔드포인트 고유 에러는 `responses=error_responses(...)`로 문서화 | §3.4.5 | DELETE·PATCH 모두 `NOT_FOUND` (W-03 때 PATCH에 `INVALID_STATE_TRANSITION` 추가) |
| 로그에 요청·응답 본문을 남기지 않음 | §6 | 담당자 이름 등 본문 로그 금지 |
| 소프트 삭제된 건은 모든 웹 조회에서 제외 | §4.1 | 이미 구현됨 |
| 호환 변경 = 선택 요청 필드 추가 | §1.4 | W-03 필드를 나중에 추가해도 호환 변경 |

### 2.3 프론트 초안의 가정 (`origin/front` `4f06f4e`, 참고용)

| 항목 | 프론트 코드 | 의미 |
|---|---|---|
| API 함수 | `updateCall(id, patch) → apiSend<CallDetail>('PATCH', ...)`, `deleteCall(id) → apiSend('DELETE', ...)` (`src/api/calls.ts`) | PATCH 응답을 `CallDetail`로 기대, DELETE는 본문 없음(빈 본문이면 `undefined`, `src/api/client.ts`) |
| 요청 타입 `CallPatch` (`src/api/types.ts`) | `category?`, `question_summary?`, `action_summary?`, `action_status?`, `agent_name?: string\|null`, `client_company?: string\|null`, `call_datetime?: string\|null`, `review_completed?: true`, `editor?: string` | **평평한(flat) 한 객체**. 메타데이터 3개만 `null` 허용, 분석 필드는 `null`을 보내지 않음 |
| 변경분만 전송 (`CallDetailPage.tsx` `diff()`) | 바뀐 필드만 담음. 담당자·고객사는 `trim()` 후 빈 값이면 `null`. 통화 일시는 `datetime-local` 값 → `"YYYY-MM-DDTHH:mm:00+09:00"` 또는 `null`(`src/lib/format.ts` `fromInputValue`) | 빈 문자열은 보내지 않음. 통화 일시는 **분 단위**(초는 `:00`) |
| 수정자 | `editor.trim()`이 비어 있지 않을 때만 `patch.editor` 설정, 입력 `maxLength=50` | `editor`는 선택. 없으면 이력의 `editor`가 NULL |
| 입력 길이 | 담당자 `maxLength=50`, 고객사 `maxLength=100` | DB 길이와 같음 |
| 저장 버튼 | 한 폼에서 분석·메타데이터를 함께 편집, `{...changes, ...extra}` 한 번에 PATCH. 검토 완료 버튼은 `{...changes, review_completed: true}` | 분석·메타데이터 혼합 요청이 정상 경로 |
| 삭제 | 화면 안 확인 → `DELETE` → 성공 시 토스트 + 목록으로 이동, 실패 시 `Alert`로 에러 표시 | 404(다른 사람이 먼저 삭제)도 에러로 표시됨 |
| 목(mock) PATCH | 404 / `review_completed`인데 `NEEDS_REVIEW` 아니면 409 / 분석 없으면 분석 필드 무시 / `metadata_incomplete = !agent_name \|\| !call_datetime` / 갱신된 건 반환 | 양방향 재계산, 응답은 상세 |
| 목 DELETE | 없으면 404, 있으면 제거 후 204. **상태 제한 없음** | 처리 중 건도 삭제 가능으로 가정 |
| 열린 질문 | `features_frontend.md` FE-14(검토 완료 표시 방법), FE-18(수정 이력 화면 표시 여부·API) | W-03·이력 조회 때 결정 |

---

## 3. W-04 삭제 상세

### 3.1 동작 후보

```
DELETE /api/calls/{call_id}
  → 잠금 조회: SELECT ... FROM call_record WHERE id = :id AND deleted_at IS NULL FOR UPDATE
  → 없으면 404 NOT_FOUND (없는 ID, 이미 삭제된 건 모두)
  → deleted_at = datetime.now(UTC)   (규약 §5.1: 내부는 aware)
  → (결정 #9) 삭제 이력 기록
  → commit → 204 (본문 없음)
```

- 상태(`status`)·`status_changed_at`은 바꾸지 않는다(상태 머신 밖의 동작). `updated_at`은 ORM 갱신이라 `onupdate`로 자동 갱신된다.
- transcript·analysis·processing_log·edit_history는 그대로 둔다(물리 삭제는 O-05). 음성 사본도 지우지 않는다(`architecture.md` §6.3).
- FastAPI 0.165에서 `@router.delete(..., status_code=204)` + 반환 타입 `None`이면 본문 0바이트로 나간다(실측: `status 204, content b''`). OpenAPI에도 `204`가 문서화된다(실측).

### 3.2 이미 삭제된 건

| 요청 | 결과 | 근거 |
|---|---|---|
| `DELETE` 삭제된 건 | **404** (확정) | `convention.md:44`, `plans/api-convention.md` 결정 #12 |
| `PATCH` 삭제된 건 | 404 | `architecture.md` §7.2 "소프트 삭제됨 → NOT_FOUND", 조회와 같은 규칙 |
| `GET` 삭제된 건 | 404 | 이미 구현(`tests/integration/test_calls_api.py::test_get_deleted_call_is_404`) |

- 404 본문은 "없음"과 "삭제됨"을 구별하지 않는다(W-02와 같음).
- 프론트는 DELETE 404를 에러로 표시하고 상세 화면에 머문다. 이미 지워진 건이므로 목록으로 보내는 편이 자연스럽다 → 프론트 확인 사항(§9.3).

### 3.3 처리 중 상태 건의 삭제

`architecture.md` §5 전이표에는 삭제 행이 없다(삭제는 상태 전이가 아님). 프론트 목은 모든 상태에서 삭제를 허용한다.

| 상태 | 삭제 후 일어나는 일 |
|---|---|
| `STORED`·`NEEDS_REVIEW`·`FAILED` | 처리 종료 상태. 영향 없음 |
| `QUEUED`·`STT_DONE` | Performer가 이후 `PUT .../transcript`·`.../analysis`·`POST .../logs`를 호출 → 로봇 API가 삭제 건을 404로 처리한다면(§7.2 규칙) Performer가 그 응답을 어떻게 다룰지 RPA 합의 필요. STT·GenAI 비용은 이미 쓰였을 수 있음 |
| `REGISTERED` | Dispatcher가 Queue 추가 전에 멈춘 경우 파일이 `processing/`에 남아 있고, 다음 실행에서 **재등록을 시도**한다(`input_flow.md` §6.1). 부분 유니크 인덱스 때문에 409가 아니라 **새 건 201** → 삭제한 건이 새 ID로 다시 처리됨 |
| `RETRY_REQUESTED` | R-09(재처리 대상 조회)가 삭제 건을 제외해야 Dispatcher가 다시 가져가지 않음(A 확인). 제외하지 않으면 `PATCH .../status`에서 404 |

선택지는 §7 #1.

### 3.4 동시성

- 웹 삭제와 로봇 적재(R-06·R-07, R-02가 `FOR UPDATE` 사용 예정)가 겹치면, 둘 다 `call_record` 행을 잠그면 순서가 정해진다. 삭제가 먼저면 로봇 쪽 잠금 조회(삭제 제외)가 404, 로봇이 먼저면 적재 후 삭제.
- 두 사용자가 동시에 삭제: 하나는 204, 다른 하나는 잠금 대기 후 `deleted_at IS NULL` 조건에 걸려 404. 잠금 없이 `UPDATE ... WHERE deleted_at IS NULL`의 영향 행 수로 판단해도 같은 결과를 얻는다(단일 문장, 별도 잠금 불필요). 이력 기록(#9)을 같이 하려면 잠금 조회 후 ORM 갱신이 단순하다.

### 3.5 삭제 건이 빠져야 하는 곳

| 대상 | 현재 | 비고 |
|---|---|---|
| W-01 목록·건수 | 제외됨 (`filter_conditions`) | `test_soft_deleted_calls_are_excluded` 있음 |
| W-02 상세 | 404 | 테스트 있음 |
| W-10 추이·분류 | 제외됨 (`filter_conditions(period.call_filter())`) | |
| W-09 요약, W-11 엑셀, W-06 음성 | 미구현 | 같은 함수·같은 규칙을 쓰도록 계획에 명시 |
| R-05~R-10 로봇 API, R-11 정체 감지 | 미구현(A) | 삭제 건 처리 규칙 A 확인(§9.1) |
| 해시 중복 검사(R-04) | 인덱스가 삭제 건 제외 | 삭제 후 같은 파일 재등록 = 새 건 (의도인지 A·RPA 확인) |

---

## 4. W-12 메타데이터 보정 상세

### 4.1 부분 갱신 의미 (누락 vs `null`)

실측(Pydantic 2.14.4):

| 요청 본문 | `model_fields_set` | `model_dump(exclude_unset=True)` |
|---|---|---|
| `{}` | `set()` | `{}` |
| `{"agent_name": null}` | `{"agent_name"}` | `{"agent_name": None}` |
| `{"agent_name": "  김  "}` (strip 설정 시) | `{"agent_name"}` | `{"agent_name": "김"}` |

- 키 없음 = 변경 안 함, `null` = 비우기. 메타데이터 3개는 모두 DB에서 NULL 허용이므로 `null` 허용.
- 본문 자체가 없으면 FastAPI가 422(`missing`)를 낸다(실측). `{}`는 통과.
- W-03의 `category`·`action_status`처럼 **`null`을 허용하지 않는 필드**는 타입을 `X | None = None`으로 두되 명시적 `null`을 거부하는 검증이 필요하다. `field_validator`(after)는 기본값에는 실행되지 않고 명시적 `null`에는 실행되므로 `loc: ["body", "category"]`로 422를 낼 수 있다. `model_validator`로 하면 `loc`이 `["body"]`가 된다(실측). Pydantic 2.14에는 실험 기능 `pydantic.experimental.missing_sentinel.MISSING`도 있으나 실험 API라 권장하지 않는다.

### 4.2 값 검증

| 필드 | DB | 후보 규칙 | 실측·근거 |
|---|---|---|---|
| `agent_name` | `VARCHAR(50)` NULL | `Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)] \| None` | 공백만·빈 문자열 → 422 `string_too_short`, 51자 → 422 `string_too_long`. 길이는 strip 후 문자 수(PostgreSQL `VARCHAR(n)`도 문자 수) |
| `client_company` | `VARCHAR(100)` NULL | 같은 방식, `max_length=100` | 101자 → 422 |
| `call_datetime` | `timestamptz` NULL | `KstDatetime \| None` | `"2026-11-23T14:30"` → `14:30+09:00`, `"...Z"` → UTC 그대로(aware) 저장, `""` → 422. **`"2026-11-23"`(날짜만)도 자정으로 통과**(실측) |
| `editor` | `VARCHAR(50)` NULL | 선택, strip, `max_length=50` | 프론트는 빈 값이면 키를 보내지 않음 |

- 빈 문자열 처리(422 vs `null`로 정규화)는 §7 #5. 통계 분류(`dimension_column`, `app/repositories/stats_repository.py`)는 공백만 있는 값을 NULL로 합치고 있으므로, 저장 단계에서 빈 문자열을 막으면 이 보정이 필요 없는 데이터가 된다.
- **`call_datetime` 범위**: 현재 제한이 없다. 오타로 먼 미래(예: 2062년)가 들어가면 기간 없는 추이 조회(`GET /api/stats/trend`, `from`·`to` 생략)가 데이터 범위로 구간 수를 세어 400구간 초과 시 **422 `range_too_large`**가 된다(`app/services/stats_service.py:78-80`). 목록 필터와 같은 `DATE_MIN`~`DATE_MAX`(2000-01-01~2100-12-31, KST 날짜 기준)를 재사용하는 안이 있다(§7 #6).
- 프론트는 분 단위로 보낸다. 사용자가 통화 일시를 고치면 원래 초 값이 `:00`이 된다(바꾸지 않으면 키를 보내지 않으므로 영향 없음).
- `agent_name`은 PRD상 "3명 중 1인"이지만 현재 자유 입력이다. 오타가 목록 필터(정확히 일치)·담당자별 통계에서 별도 항목이 된다. 허용 목록 도입은 범위 밖(§9.4).

### 4.3 `metadata_incomplete` 재계산

| 출처 | 규칙 |
|---|---|
| `research.md:168` | `agent_name` 또는 `call_datetime` 누락 시 true, 웹 보정 시 false |
| `architecture.md:277`, `features.md` W-12 | "담당자·통화 일시가 채워지면 false" (반대 방향은 언급 없음) |
| 프론트 목 | `!agent_name \|\| !call_datetime` (양방향) |
| `input_flow.md` §7 | 추출하지 못한 메타데이터를 비워 등록 → 서버가 true 표시 |

후보 함수(공용, R-04도 사용):

```python
# 위치 후보: app/services/call_metadata.py 또는 app/models/call_record.py 근처 (A와 합의)
def is_metadata_incomplete(agent_name: str | None, call_datetime: datetime | None) -> bool:
    return not (agent_name and agent_name.strip()) or call_datetime is None
```

- 고객사는 판정에서 빠진다. GenAI가 대화에서 고객사를 추출해 채우는 흐름(`to_backend.py` `customer_company → client_company`)과도 맞다.
- 양방향(비우면 다시 true)으로 하면 "필드 값과 표시가 항상 일치"가 보장되고, 목록 `metadata_incomplete=true` 필터·W-09 요약 수치와 어긋나지 않는다(§7 #4).
- 재계산 시점: 요청에 메타데이터 키가 하나라도 있으면(값이 그대로여도) 재계산하면, 과거 데이터의 표시 불일치도 고쳐진다.
- 파생 값이므로 `edit_history`에 별도 행을 남기지 않는 안을 권장(§7 #7).

### 4.4 `edit_history` 기록 형식

| 컬럼 | 값 후보 |
|---|---|
| `call_id` | 대상 건 |
| `field` | API 필드 이름: `agent_name`, `client_company`, `call_datetime` (W-03: `category`, `question_summary`, `action_summary`, `action_status`) |
| `before_val`·`after_val` | 문자열. `None`은 SQL NULL. `call_datetime`은 응답과 같은 **초 단위 ISO 8601 `+09:00`** 문자열(`_to_kst(v).isoformat()`과 같은 규칙) |
| `editor` | 요청의 `editor`(strip 후), 없으면 NULL. 인증이 없으므로 **자기 신고 값**이며 신뢰 근거가 아님(`prd.md` WEB-08 [가정]) |
| `edited_at` | DB `now()`(서버 기본값) |

- **필드별 1행, 실제로 바뀐 필드만** 기록하는 안을 권장. 같은 값을 보내면 행을 만들지 않는다(§7 #7). 같은 요청의 행들은 `edited_at`이 같다(같은 트랜잭션의 `now()`).
- 요청 묶음 식별자(같은 저장 동작인지)는 컬럼이 없다. `edited_at`+`editor`로 대략 묶을 수 있다. 필요하면 A에게 컬럼 추가 요청(지금은 불필요).
- W-03에서 `category`를 기록할 때 API 코드(`COMPLAINT`)와 DB 값(`불만`) 중 무엇을 남길지는 W-03 때 결정(§8 W-03 확장 참고).

### 4.5 응답

- `200` + 갱신된 `CallDetail`(`convention.md:43`). 커밋 후 `CallService.get_call(call_id)`를 다시 부르면 기존 직렬화 경로(`model_validate`, `KstDatetime`, 유형 코드 변환)를 그대로 탄다.
- `expire_on_commit=False`라 커밋 후 세션의 `CallRecord`는 이미 메모리에 있는 값으로 재사용된다. 응답 필드(`agent_name` 등)는 방금 쓴 값이라 문제없다. `updated_at`(서버 `onupdate`)은 응답에 없다.
- 프론트는 성공 후 `['call', id]`·`['calls']`·`['stats']`를 다시 불러오므로(`useInvalidate`) 응답 본문을 덮어쓰지 않아도 화면은 맞춰진다.

### 4.6 동시성 (PATCH)

- 두 사람이 같은 건을 동시에 고치면 뒤 요청이 앞 요청의 값을 덮는다(마지막 쓰기 우선). `FOR UPDATE`로 행을 잠그면 뒤 요청의 `before_val`이 앞 요청의 `after_val`이 되어 **이력이 끊기지 않는다**. 잠그지 않으면 두 요청이 같은 `before_val`을 기록할 수 있다.
- 낙관적 잠금(`updated_at`·`If-Match` 비교 후 409)은 규약·프론트 어디에도 없고 사용자 3명 규모라 과하다(§7 #11).
- 잠금 쿼리는 `joinedload` 없는 단순 조회여야 한다(§0 #6).

```python
# 설명용 스케치
def lock_call(self, call_id: int) -> CallRecord | None:
    stmt = (
        select(CallRecord)
        .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
        .with_for_update()
    )
    return self._session.scalars(stmt).one_or_none()
```

---

## 5. W-03을 고려한 요청 스키마·서비스 구조

### 5.1 요청 스키마 (평평한 한 모델)

프론트 `CallPatch`가 평평하고, 규약이 "선택 요청 필드 추가 = 호환 변경"이므로 **한 모델에 필드를 추가해 가는 방식**이 가장 단순하다.

```python
# app/schemas/call.py (설명용 스케치)
AgentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
ClientCompany = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
EditorName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]

METADATA_FIELDS = ("agent_name", "client_company", "call_datetime")
# W-03에서 추가: ANALYSIS_FIELDS = ("category", "question_summary", "action_summary", "action_status")


class CallUpdateRequest(BaseModel):
    """PATCH /api/calls/{id}. 보낸 키만 변경, null은 비우기(허용 필드만)."""

    model_config = ConfigDict(extra="forbid")  # §7 #3

    agent_name: AgentName | None = None
    client_company: ClientCompany | None = None
    call_datetime: KstDatetime | None = None
    editor: EditorName | None = None
    # W-03: category: Category | None = None (명시적 null 거부 validator)
    #       question_summary·action_summary: str | None, action_status: ActionStatus | None
    #       review_completed: Literal[True] | None = None   (FE-14 결정에 따름)

    def metadata_changes(self) -> dict[str, Any]:
        return self.model_dump(include=set(METADATA_FIELDS), exclude_unset=True)
```

- `extra="forbid"`면 W-03 필드가 오기 전까지 `category` 등은 422 `extra_forbidden`(실측, `loc: ["body", "category"]`). W-03에서 필드를 선언하는 순간 허용으로 바뀐다(호환 변경).
- 대안: 중첩(`{"metadata": {...}, "analysis": {...}}`)은 구분이 명확하지만 프론트 초안·`research.md` §5 서술과 다르고 비호환 변경이 된다.
- `model_dump()`(python 모드)는 `KstDatetime`의 `PlainSerializer(when_used="json")`를 적용하지 않으므로 aware `datetime`이 그대로 나온다.

### 5.2 서비스 구조

```python
# app/services/call_service.py (설명용 스케치)
@dataclass(frozen=True)
class FieldChange:
    field: str
    before: str | None
    after: str | None


def apply_changes(target: object, changes: dict[str, Any]) -> list[FieldChange]:
    """값이 다른 필드만 대입하고 변경 목록을 돌려준다 (순수 함수 → 단위 테스트)."""


class CallService:
    def update_call(self, call_id: int, request: CallUpdateRequest) -> CallDetail:
        call = self._repository.lock_call(call_id)            # FOR UPDATE, 삭제 제외
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        metadata = request.metadata_changes()
        changes = apply_changes(call, metadata)
        if metadata:
            call.metadata_incomplete = is_metadata_incomplete(call.agent_name, call.call_datetime)
        # W-03: changes += self._update_analysis(call, request)   (분석 없음 → 결정 필요)
        # W-03: if request.review_completed: state_machine.complete_review(call)  (R-02, 409)
        self._repository.add_edit_history(call_id, changes, editor=request.editor)
        self._commit()
        return self.get_call(call_id)

    def delete_call(self, call_id: int) -> None:
        call = self._repository.lock_call(call_id)
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        call.deleted_at = datetime.now(UTC)
        # (결정 #9) 삭제 이력
        self._commit()
```

- 갱신 단계를 "메타데이터 적용 → (W-03) 분석 적용 → (W-03) 상태 전이 → 이력 기록 → 커밋" 순으로 두면, W-03은 단계 두 개를 끼워 넣는 것으로 끝난다. 한 요청 = 한 트랜잭션이라 검토 완료 409가 나면 메타데이터 변경도 함께 롤백된다(원자성).
- W-03의 상태 전이는 R-02(A)가 잠금·`processing_log` 기록을 맡는다. 이미 W-12가 행을 잠근 같은 트랜잭션 안에서 R-02 함수가 다시 `FOR UPDATE`를 해도 같은 트랜잭션이므로 막히지 않는다. 잠금 헬퍼를 R-02와 공유할지는 A와 합의(§9.1).
- 커밋 수단: `CallService(repository, session)`로 세션을 받거나, 리포지토리에 `commit()`을 두는 방식(§7 #12).

### 5.3 라우터

```python
@router.patch("/{call_id}", responses=error_responses(ErrorCode.NOT_FOUND))
def update_call(call_id: CallId, body: CallUpdateRequest, request: Request, service: CallServiceDep) -> CallDetail: ...

@router.delete("/{call_id}", status_code=204, responses=error_responses(ErrorCode.NOT_FOUND))
def delete_call(call_id: CallId, request: Request, service: CallServiceDep) -> None: ...
```

- operationId는 함수 이름(`update_call`, `delete_call`)이며 앱 전체에서 고유해야 한다. `tests/unit/conftest.py`의 테스트 라우트 이름(`echo`, `create_item`, `upload`, `raise_app_error`, `boom`, `bind_call`)과 겹치지 않는다.
- W-03 때 PATCH `responses`에 `ErrorCode.INVALID_STATE_TRANSITION` 추가.
- 라우트 추가 후 `docs/api/openapi.json` 재생성(`test_openapi.py:150`).

---

## 6. 테스트 전략

### 6.1 단위 (DB 없음)

| 대상 | 케이스 |
|---|---|
| `CallUpdateRequest` | 키 없음/`null`/값 구분(`model_fields_set`), strip, 빈 문자열·공백만 422, 길이 50/51·100/101, `extra` 키 422(`loc: ["body", "category"]`), `call_datetime` 오프셋 없음 → `+09:00`, 범위 밖(결정 #6), `editor` 51자 422 |
| `is_metadata_incomplete` | (값, 값)→false, (None, 값)·(값, None)·(공백, 값)→true |
| `apply_changes` | 같은 값은 변경 목록에 없음, `None`↔값 양방향, `call_datetime` 문자열화(`+09:00` 초 단위), 다른 시간대로 같은 시각을 보내면 변경 없음 |
| 라우터 (`FakeCallService`) | DELETE 204·본문 0바이트·`X-Request-Id`, 404 형식, `call_id` 0·음수·BIGINT 초과 422, PATCH 200 상세, 본문 없음 422, 서비스에 전달된 `model_fields_set` |
| OpenAPI | DELETE 응답 키 `{"204","404","422","500"}`, PATCH 요청 스키마 `CallUpdateRequest`(필드·`nullable`·`maxLength`), 응답 `CallDetail`, operationId |
| 잠금 SQL | `lock_call` 쿼리 컴파일 결과에 `FOR UPDATE`가 있고 `LEFT OUTER JOIN`이 없음(PostgreSQL 방언 컴파일, DB 불필요) |

### 6.2 통합 (PostgreSQL)

| 대상 | 케이스 |
|---|---|
| DELETE | 204 → DB `deleted_at` 설정, `status` 그대로 / 이후 GET 404, 목록·건수에서 빠짐, `/api/stats/breakdown`에서 빠짐 / 두 번째 DELETE 404 / 없는 ID 404 / 각 상태(`QUEUED` 등)에서 결정 #1대로 / 삭제 후 같은 `file_hash` 행 추가 가능(부분 인덱스, R-04 참고용) / (결정 #9) 이력 행 |
| PATCH | 일부 키만 갱신, 나머지 그대로 / `null`로 비우기 / `metadata_incomplete` true→false(담당자·일시 채움), false→true(비움, 결정 #4), 고객사만 바꿀 때 표시 불변 / `edit_history` 필드별 행·`before_val`·`after_val`·`editor`·값 같으면 행 없음 / `call_datetime` 저장값이 aware이고 응답 `+09:00` / `status`·`status_changed_at` 불변 / 삭제된 건 404 / 응답이 GET 상세와 같음 / 처리 중 상태에서도 200 |
| 동시성 | 같은 연결을 쓰는 savepoint 픽스처로는 두 트랜잭션 경합을 재현하기 어렵다. 필요하면 별도 엔진 연결 두 개 + `lock_timeout`으로 대기 확인(선택). 기본은 6.1의 SQL 검사로 대신 |

- 픽스처는 `tests/integration/conftest.py`의 `db_session`·`api`(W-01과 같은 방식)를 쓴다. 이력 검증에는 `select(EditHistory)`를 직접 쓰거나 `tests/factories.py`의 `make_edit_history` 형식을 참고한다.
- 서비스의 `commit()`은 `create_savepoint` 모드에서 SAVEPOINT 해제로만 동작한다. 같은 세션으로 바로 조회하면 결과가 보인다.
- 실행 환경: Docker 데몬 미연결 상태에서는 skip. 계획·구현 전에 Docker Desktop 실행 확인.

---

## 7. 결정 필요

| # | 항목 | 선택지 | 권장안 | 이유 |
|---|---|---|---|---|
| 1 | **[핵심]** 처리 중 건 삭제 허용 | A. 모든 상태 허용 / B. 비정체 처리 중(`REGISTERED`·`QUEUED`·`STT_DONE`·`RETRY_REQUESTED`)은 409 / C. 종료 상태(`STORED`·`NEEDS_REVIEW`·`FAILED`)만 | **A** | `architecture.md` §5에 제한 없음, 프론트 목도 허용, 잘못 올린 파일을 바로 지우는 용도. 단 로봇 API의 삭제 건 404 처리와 `REGISTERED` 재등록 부활(§3.3)을 A·RPA와 합의. B는 W-05의 정체 판단(R-11)에 의존해 선행 조건이 늘어남 |
| 2 | 삭제된 건 재삭제 | 404 / 204 멱등 | **404 (확정)** | C-03 결정 #12, `convention.md:44`. 재논의 대상 아님 |
| 3 | **[핵심]** W-03 미구현 기간에 W-03 필드가 오면 | A. `extra="forbid"` → 422 / B. 무시(기본값) → 200 / C. W-03 필드를 선언하고 409·501로 거절 / D. W-03과 같이 배포 | **A** (가능하면 D) | B는 분석 수정이 조용히 사라짐. C는 임시 코드가 늘어남. A는 W-03 필드 선언만으로 해제되고 호환 변경. 프론트에 "W-03 전까지 분석·메타데이터 동시 저장은 422" 공지 필요 |
| 4 | **[핵심]** `metadata_incomplete` 재계산 | A. 양방향(`agent_name` 또는 `call_datetime`이 비면 true) / B. 채워질 때 false로만 | **A**, 메타데이터 키가 요청에 있으면 항상 재계산 | 표시와 값이 항상 일치, 목록 필터·W-09 수치와 맞음, 프론트 목과 같음. 판정 함수 하나를 R-04와 공유 |
| 5 | 빈 문자열·공백 | A. strip 후 빈 값 422 / B. strip 후 빈 값을 `null`로 정규화 | **A** | 비우기는 `null` 한 가지 표현만. 프론트는 이미 `null`로 보냄. 길이는 strip 후 기준 |
| 6 | `call_datetime` 범위 | A. 제한 없음 / B. `DATE_MIN`~`DATE_MAX`(KST 날짜 기준) / C. B + 현재 시각 이후 금지 | **B** | 오타 한 건이 기간 없는 추이 조회를 422로 만드는 것을 막음(§4.2). C는 시계 차이·테스트 시각 고정 부담. 날짜만(`"2026-11-23"`) 입력을 막을지는 함께 결정(현재 자정으로 통과) |
| 7 | 이력 기록 단위 | A. 바뀐 필드만 필드별 1행 / B. 보낸 키 전부 / C. 요청당 1행(JSON) | **A**, `metadata_incomplete` 파생 변화는 기록 안 함 | 스키마(`field`·`before_val`·`after_val`)가 필드별 행을 전제. 같은 값 재전송이 이력을 어지럽히지 않음 |
| 8 | 이력 값 문자열 형식 | `call_datetime`: 응답과 같은 초 단위 `+09:00` / UTC ISO / DB 원문 | **응답과 같은 형식** | 화면(FE-18)에 그대로 보여 줄 수 있고 API 값과 비교 쉬움 |
| 9 | **[핵심]** 삭제 이력 | A. 남기지 않음(`deleted_at`만) / B. `edit_history`에 `field="deleted_at"`, `before NULL`, `after` 시각, `editor NULL` / C. `processing_log`(단계 enum에 없어 CHECK 변경 필요) | **B** | `prd.md` §9 "삭제는 소프트 삭제 + 수정 이력", 오조작 추적. 스키마 변경 없음. DELETE에 `editor`를 받을지(쿼리 파라미터 등)는 프론트와 별도 합의, 지금은 NULL |
| 10 | 빈 PATCH(`{}`)·`editor`만 | A. 200 + 상세(변경 없음, 이력 없음) / B. 422 | **A** | PATCH 의미상 무변경도 정상. 프론트는 변경이 없으면 저장 버튼을 막음 |
| 11 | PATCH 동시성 | A. `FOR UPDATE`(비관적) / B. 낙관적(`updated_at` 비교 409) / C. 잠금 없음 | **A** | `architecture.md` §5 방식과 같음, 이력 `before_val` 연속성 보장, 프론트 변경 없음 |
| 12 | 커밋 위치 | A. `CallService`가 `Session`을 받음(`get_call_service`에서 함께 전달) / B. `CallRepository.commit()` / C. `get_db`가 요청 끝에 커밋 | **A** | `architecture.md` §3.1 "Service: 유스케이스 단위 트랜잭션", `deps.py` 주석 "커밋은 서비스가 한다". C는 기존 결정과 다름. 단위 테스트의 `FakeCallService`는 영향 없음 |
| 13 | `editor` 규칙 | 선택·strip·최대 50 / 필수 | **선택** | WEB-08은 P2·[가정], 프론트도 선택. 공백만이면 `null`로 볼지 422로 볼지는 #5와 맞춰 결정(프론트는 보내지 않음) |
| 14 | 잠금 조회 위치 | A. `CallRepository.lock_call()`을 W-04·W-12가 먼저 만들고 R-02가 재사용 / B. R-02의 잠금 함수를 기다림 | **A** (A 리뷰) | W-04·W-12는 R-02 선행이 아님(`features.md`). 이름·반환 형태를 A와 맞춤 |

---

## 8. W-03 확장 시 남는 항목 (참고, 이번 범위 밖)

| 항목 | 내용 |
|---|---|
| 분석이 없는 건에 분석 필드 | `analysis` NULL(처리 전·실패)인데 `category` 등이 오면 409 / 422 / 무시 — 프론트 목은 무시 |
| 검토 완료 표시 | `review_completed: true`(프론트 초안) vs `status: "STORED"` — FE-14 |
| `category` 이력 값 | API 코드 vs DB 한글 값(`CATEGORY_DB_VALUES`) |
| 상태 전이 로그 | R-02는 전이마다 `processing_log` 기록인데 `LOG_STEPS`에 웹 검토용 단계가 없음(`REGISTER`…`RETRY`). A와 단계 값 합의 |
| `analysis.needs_review` | 검토 완료 시 false로 바꿀지(프론트 목은 바꿈) |
| PATCH 409 문서화 | `error_responses(NOT_FOUND, INVALID_STATE_TRANSITION)` |

---

## 9. 팀 확인 필요

### 9.1 백엔드 A (C-04·R-02·R-04·R-07·R-09·R-11·O-05)

| # | 항목 | 내용 |
|---|---|---|
| A1 | **`metadata_incomplete` 판정 함수 공유** | `agent_name`(공백 제외) 또는 `call_datetime`이 비면 true. R-04가 같은 함수를 쓰고, 로봇이 multipart로 빈 문자열을 보내면 `null`로 정규화할지 |
| A2 | **R-07 적재가 메타데이터를 덮어쓰는지** | `to_backend.py`의 `call` 덩어리(`agent_name`·`client_company`·`call_datetime`)를 `call_record`에 반영하면 웹 보정 값이 재처리 후 사라짐. 선택지: 반영 안 함 / 비어 있을 때만 채움 / 덮어쓰되 `metadata_incomplete` 재계산. 덮어쓰기라면 `edit_history`에 남길지 |
| A3 | 로봇 API의 삭제 건 처리 | R-05~R-08 잠금 조회도 `deleted_at IS NULL` → 404로 할지(§7.2 규칙). R-09 재처리 대상·R-11 정체 건수에서 삭제 건 제외 |
| A4 | 삭제 후 같은 파일 재등록 | 부분 유니크 인덱스라 새 건 201. 의도된 동작인지(삭제 후 재업로드 허용) |
| A5 | 잠금 헬퍼 | `CallRepository.lock_call(call_id)`(삭제 제외, `joinedload` 없음)을 R-02가 재사용할지, R-02 쪽에 둘지 |
| A6 | O-05 물리 삭제 순서 | FK에 `ON DELETE`가 없으므로 `edit_history`·`processing_log`·`transcript`·`analysis` → `call_record` 순서, 음성 사본 삭제 |
| A7 | `edit_history(call_id)` 인덱스 | 이력 조회 API(FE-18)가 생기면 필요. 지금은 쓰기만 해서 불필요 |

### 9.2 RPA 파트 (A 경유)

| # | 항목 | 내용 |
|---|---|---|
| P1 | 처리 중 삭제된 건에 대한 404 | Performer가 `PUT .../transcript`·`.../analysis`에서 404를 받으면 실패 보고 없이 Queue 건 종료(정체 건 재처리 후 409와 같은 처리, `input_flow.md` §6.3 [합의 필요]) |
| P2 | `REGISTERED` 건 삭제 후 Dispatcher 재등록 | `processing/`에 남은 파일 재등록 시 새 건이 만들어짐. 삭제한 건의 파일을 `failed/`로 옮길 수단이 없으므로 운영 안내 필요 여부 |

### 9.3 프론트

| # | 항목 | 내용 |
|---|---|---|
| F1 | **W-03 전 혼합 PATCH 422** | 결정 #3 A라면 W-03 배포 전까지 분석 필드를 함께 보내면 422 `extra_forbidden`(`loc: ["body", "category"]`) |
| F2 | DELETE 404 처리 | 다른 사람이 먼저 지운 경우 404 → 지금은 에러 표시. 목록으로 이동시킬지 |
| F3 | 빈 값 | 공백·빈 문자열은 422, 비우기는 `null`(현재 프론트 동작과 같음) |
| F4 | 통화 일시 | 분 단위 입력으로 초가 `:00`이 됨. 범위(결정 #6) 밖은 422 |
| F5 | `metadata_incomplete` | 담당자·통화 일시를 비우면 다시 true(결정 #4) |
| F6 | 수정 이력 표시 | FE-18 — API가 필요하면 별도 기능으로 |

### 9.4 팀·관리자

| # | 항목 | 내용 |
|---|---|---|
| T1 | 담당자 이름 입력 방식 | 자유 입력(현재) vs 3명 허용 목록(PRD IN-05 "3명 중 1인"). 오타가 필터·통계에서 별도 항목이 됨 |
| T2 | 삭제 권한 | 로그인이 없어 누구나 삭제 가능(사내망 한정). 복구 API(삭제 취소)는 범위 밖 — 필요하면 `deleted_at = NULL` + 해시 중복 검사가 필요 |

---

## 10. 계획 단계 체크리스트

1. 모델·마이그레이션 변경 없음(필요 시 §9.1로 A 요청).
2. `CallUpdateRequest`·`is_metadata_incomplete`·`apply_changes`·`lock_call`·`add_edit_history`·`update_call`·`delete_call` 추가, `get_call_service`에 세션 전달(결정 #12).
3. 라우트 2개(`update_call`, `delete_call`) + `bind_call_id` + `error_responses(NOT_FOUND)`.
4. `docs/api/openapi.json` 재생성, `convention.md` §2.2는 이미 맞음(결정 #5·#6·#9가 정해지면 §5.2 등에 한 줄씩 보완).
5. 단위 → 통합 순 TDD, Docker 실행 확인.
