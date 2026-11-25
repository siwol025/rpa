# 재처리 요청 리서치 — `POST /api/calls/{id}/retry`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-05 재처리 요청 (P1, Phase 2, 선행 R-02) — 요구: PRD WEB-09 / 관련: R-02 상태 머신(사용), R-09 재처리 대상 조회·R-10 재처리용 음성 다운로드(후속 소비자), R-11 정체 감지(같은 기준), R-05 `QUEUED` 재등록, W-03·W-04·W-12(같은 라우터·서비스를 동시에 수정) |
| 근거 | `docs/prd.md` §5(RPA-06·WEB-05·WEB-09)·§6·§7, `docs/input_flow.md` §5.3·§6.1·§6.2·§6.3·§7·§9, `features.md` R-02·R-05·R-09·R-10·R-11·R-12·W-03~W-05·W-12·§5·§6, `architecture.md` §3·§4.2·§4.3·§5·§7.2·§12·§13, `api/convention.md` v0.1 §2·§3·§5·§7, `backend/app/**`, `backend/tests/**`, 원격 브랜치 `origin/front`(프론트 초안, 미병합) |
| 기준 버전 | 코드 `2bde1c6`(main `6a8f418` 포함) / FastAPI 0.165.0 / SQLAlchemy 2.0.58 (`.venv` 설치본) |
| 검증 방법 | 문서·코드·테스트 정독, `git show origin/front:<path>`로 프론트 초안 확인, 스크래치 폴더에서 SQLAlchemy 식별자 맵 동작 실측(레포 코드는 수정하지 않음) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다. **[확인 필요]**는 다른 파트와 합의가 필요한 항목, **[가정]**은 근거 없이 정한 값이다.

---

## 0. 요약 (핵심 발견)

1. **상태 전이·`retry_count` +1·`processing_log` 기록·404·409·행 잠금은 이미 R-02(`CallStateMachine.transition`)가 모두 한다.** W-05가 새로 만드는 것은 라우터·얇은 서비스·응답 스키마·`commit`뿐이다. 웹 쪽에서 `retry_count`를 다시 올리면 이중 증가가 된다.
2. **응답 계약은 이미 정해져 있다.** `convention.md` §2.2: `202 {call_id, status, retry_count}`, 에러 404·409. `architecture.md` §4.3도 202. 프론트 초안(`origin/front`)도 본문 없이 `POST`하고 `202 RetryResult {call_id, status, retry_count}`를 기대한다.
3. **[핵심] 정체된 `RETRY_REQUESTED`의 재요청 허용 여부가 문서·프론트와 코드가 다르다.** 상태 머신은 `STALE_ELIGIBLE`(`REGISTERED`·`QUEUED`·`STT_DONE`·`RETRY_REQUESTED`) 전부에 정체 시 `RETRY_REQUESTED` 전이를 허용한다(테스트 `test_stale_processing_call_can_be_retried`가 `RETRY_REQUESTED`도 포함). 반면 `features.md` R-02·W-05, `architecture.md` §4.3·§5 표·§12, `input_flow.md` §6.3, 프론트 `canRetry`는 정체 재처리 대상을 `REGISTERED`·`QUEUED`·`STT_DONE`으로 한정하고, `RETRY_REQUESTED` 정체는 "Dispatcher가 멈춘 것 → 로봇 점검"으로 안내한다.
4. **정체 기준은 앱 설정 `STALE_THRESHOLD_MIN`(기본 30분)을 `app.state.settings`에서 읽어야 한다.** 모듈 함수 `state_machine.transition()`은 `get_settings()`(.env)를 읽으므로 테스트의 `create_app(Settings(...))` 값이 반영되지 않는다. 로봇 쪽과 같이 `get_settings_from_app` → `CallStateMachine(db, stale_threshold_min=...)` 패턴을 쓴다.
5. **같은 세션에서 잠금 없이 먼저 읽고 나서 `transition`을 부르면 정체 판정이 낡은 값으로 될 수 있다.** `transition`의 `SELECT ... FOR UPDATE`는 이미 식별자 맵에 있는 객체의 속성을 갱신하지 않는다(실측, §6.3). 사전 검사가 필요하면 첫 조회부터 잠금 조회여야 한다(`RobotService._lock_call` 패턴).
6. **동시 수정 충돌을 줄이려면 별도 파일(`app/api/web/retry.py`·`app/services/retry_service.py`)이 유리하다.** 다만 `main.py`(라우터 등록 1줄)·`openapi.json`(재생성)은 어느 안이든 건드린다(§9).
7. R-09(재처리 대상 조회)·R-10(재처리용 음성 다운로드)은 **아직 어느 브랜치에도 구현되지 않았다**(`origin/main`·`cyj`·`say` 확인). W-05만으로는 재처리가 끝까지 돌지 않으며, 통합 검증은 R-09·R-10 이후 가능하다.

---

## 1. 현재 상태

### 1.1 코드 (`2bde1c6`)

| 파일 | W-05와의 관계 |
|---|---|
| `app/services/state_machine.py` | `CallStateMachine.transition()` — 재사용 대상. `InvalidTransition`, `is_stale`, `STALE_ELIGIBLE`, 모듈 함수 `transition()` |
| `app/services/robot_service.py` | 상태 머신 사용 예(`_lock_call` → `transition` → `commit`) |
| `app/api/robot/calls.py` | 동작 API 라우터 패턴(`Path(ge=1, le=BIGINT_MAX)`, `bind_call_id`, `error_responses(NOT_FOUND, INVALID_STATE_TRANSITION)`, `{call_id, status}` 응답) |
| `app/api/deps.py` | `get_db`, `get_settings_from_app`, `get_robot_service`(설정의 `stale_threshold_min` 주입) |
| `app/api/web/calls.py` | `GET /api/calls`, `GET /api/calls/{call_id}`. `BIGINT_MAX` 상수, `CallServiceDep` |
| `app/services/call_service.py` | `CallService(CallRepository)` — 조회 전용, `commit` 없음 |
| `app/schemas/call.py` | `CallStatus`, `LogStep.RETRY`, `LogStatus.RETRY`. 재처리 응답 모델은 없음 |
| `app/schemas/common.py` | `error_responses()` |
| `app/core/errors.py` | `INVALID_STATE_TRANSITION`(409), `NOT_FOUND`(404) |
| `app/models/call_record.py` | `status`, `status_changed_at`, `retry_count`(NOT NULL, 기본 0), `queue_item_id`, `deleted_at` |
| `app/models/processing_log.py`, `edit_history.py` | 로그 / 사람 수정 이력 |
| `app/main.py` | 라우터 등록: `calls`, `robot_calls`, `stats`, `uploads` |

W-05 엔드포인트, 재처리 응답 스키마, R-09 `GET /api/robot/calls`, R-10 `GET /api/robot/calls/{id}/audio`는 없다.

### 1.2 `CallStateMachine.transition()` 내부 (정독 결과)

```text
transition(call_id, to_status, *, actor, reason=None, step=None, log_status=None,
           orchestrator_job_id=None, now=None) -> CallRecord
```

| 순서 | 동작 | W-05에 미치는 영향 |
|---|---|---|
| 1 | `now = now or datetime.now(UTC)` | 정체 판정 기준 시각. **잠금을 얻기 전에** 계산된다(대기가 길면 그만큼 이른 시각, 실무상 무시 가능) |
| 2 | `SELECT call_record WHERE id=? AND deleted_at IS NULL FOR UPDATE` | 없는 건·소프트 삭제 건 → `AppError(NOT_FOUND)` 404. 행 잠금으로 로봇과 직렬화 |
| 3 | `_is_allowed`: `_ALLOWED[current]`에 있으면 허용, 아니면 `target is RETRY_REQUESTED and is_stale(...)` | `FAILED`·`NEEDS_REVIEW`·`STORED` → 항상 허용. 처리 중 상태는 정체일 때만 |
| 4 | 거절 시 `InvalidTransition(current, target)` | 409 `INVALID_STATE_TRANSITION`, `detail={"current_status", "requested_status"}`. 아무것도 바뀌지 않음 |
| 5 | `status = target`, `status_changed_at = now` | |
| 6 | `if target is RETRY_REQUESTED: retry_count += 1` | **`retry_count`는 상태 머신이 올린다** |
| 7 | `ProcessingLog(step=RETRY, status=RETRY, message="[web] {current} -> RETRY_REQUESTED[: reason]")` | `actor`·`reason`이 메시지에 들어간다. 상세 화면 `processing_log`에 보인다 |
| 8 | `flush()` 후 `CallRecord` 반환 | **`commit`은 호출자** |

`is_stale(call, threshold_min, now)`: `status ∈ STALE_ELIGIBLE` 이고 `status_changed_at < now - threshold` (경계 미포함, `test_stale_boundary_is_exclusive`).

`_ALLOWED` 중 재처리 관련: `NEEDS_REVIEW → {STORED, RETRY_REQUESTED}`, `STORED → {RETRY_REQUESTED}`, `FAILED → {RETRY_REQUESTED}`, `RETRY_REQUESTED → {QUEUED}`.

### 1.3 상태별 W-05 결과 (현재 상태 머신 그대로 쓸 때)

| 현재 상태 | 정체 아님 | 정체(`STALE_THRESHOLD_MIN` 초과) |
|---|---|---|
| `FAILED`·`NEEDS_REVIEW`·`STORED` | 202 | 202 (정체 개념 없음, `is_stale`=False지만 전이표로 허용) |
| `REGISTERED`·`QUEUED`·`STT_DONE` | 409 | 202 |
| `RETRY_REQUESTED` | 409 | **202 (`retry_count` 한 번 더 +1)** ← 문서·프론트와 다름 (§4.1) |
| 없음 / 소프트 삭제 | 404 | 404 |

### 1.4 테스트 구조

| 위치 | 내용 |
|---|---|
| `tests/conftest.py` | `db`(테스트마다 바깥 트랜잭션 + `create_savepoint`, 코드의 `commit()`은 SAVEPOINT 해제로만 동작 → 끝에 롤백), `robot_app`/`robot_client`(`get_db`를 `db`로 override) |
| `tests/integration/conftest.py` | `engine`을 덮어씀(`TEST_DATABASE_URL` → testcontainers → skip), `db_session`, `api`(`create_app(Settings(_env_file=None))` + `get_db` override). 이 디렉터리에서 `db`도 이 `engine`을 쓴다 |
| `tests/factories.py` | `make_call_record(db, status=..., status_changed_at=..., deleted_at=..., retry_count=...)` |
| `tests/integration/factories.py` | 임시 팩토리 `make_call` 등 (C-05 팩토리로 대체 예정이라고 명시) |
| `tests/integration/test_state_machine.py` | 전이표 전체(허용·거절 파라미터화), 정체 허용/거절, 경계, `retry_count` 누적, 404(없음·삭제), `FOR UPDATE` 확인, 모듈 함수 |
| `tests/integration/test_robot_simulation.py` | `web_retry()`가 **W-05 대역**으로 상태 머신을 직접 호출(`actor="web"`). 실패→재처리→재적재, 저장 후 재분석, 정체 복구와 늦은 요청 409, 정체 아님 409 |
| `tests/unit/test_calls_api.py` | 서비스를 가짜로 바꿔 라우터 파라미터·응답·OpenAPI를 확인하는 패턴 |
| `tests/unit/test_openapi.py` | 커밋된 `docs/api/openapi.json`과 코드 생성 결과 비교(다르면 실패) |

`robot_client`로도 `/api/calls/*`를 호출할 수 있다(웹 경로는 로봇 인증 미들웨어 대상이 아님 — `test_robot_simulation.py`가 `robot_client.get("/api/calls/{id}")` 사용).

---

## 2. 요구사항 정리

### 2.1 원문

| 출처 | 내용 |
|---|---|
| `features.md` W-05 | `POST /api/calls/{id}/retry` — `FAILED`·`NEEDS_REVIEW`·`STORED` 건과 **정체 건**을 `RETRY_REQUESTED`로 전이 (R-02 사용), `retry_count` +1. 정체되지 않은 처리 중 건은 409 |
| `features.md` R-02 | 정체된 `REGISTERED`·`QUEUED`·`STT_DONE`의 재처리 전이 허용 |
| `features.md` R-09 | `GET /api/robot/calls?status=RETRY_REQUESTED` — `call_id`, `retry_count` 목록 (Queue Reference `call_id-retryN` 생성용) |
| `features.md` R-10 | `GET /api/robot/calls/{id}/audio` — 서버 음성 사본 전송 |
| `features.md` R-11 | `REGISTERED`·`QUEUED`·`STT_DONE`·`RETRY_REQUESTED`에서 `STALE_THRESHOLD_MIN` 초과 건 조회·건수 |
| `prd.md` WEB-09 | 실패·검토 필요·정체 건의 재처리 요청 (다음 Dispatcher 주기에 반영) |
| `prd.md` RPA-06 | Dispatcher는 매 실행 시 `RETRY_REQUESTED` 건을 조회해 Queue에 다시 등록 |
| `architecture.md` §4.3 | `A-->>W: 202 (다음 Dispatcher 주기에 반영)`. 재처리 요청 시 `retry_count`를 1 올리고 Dispatcher가 `call_id-retryN`을 만든다. 정체 건 재처리 후 이전 Queue 건의 늦은 적재는 409(정상) |
| `architecture.md` §5 표 | `POST /api/calls/{id}/retry`: 허용 `FAILED`, `NEEDS_REVIEW`, `STORED` / 정체된 `REGISTERED`·`QUEUED`·`STT_DONE` → `RETRY_REQUESTED`(`retry_count` +1) |
| `architecture.md` §12 | `RETRY_REQUESTED` 정체는 Dispatcher가 멈춘 것이므로 RPA 파트에 로봇 점검 요청 |
| `input_flow.md` §5.3 | 재처리: 웹 요청 → 상태 `RETRY_REQUESTED`로 **표시만 함** (서버가 로봇을 직접 실행하지 않음) |
| `input_flow.md` §6.3 | 재처리 요청 시 **서버가** `retry_count`를 1 올림. 늦은 적재 409 → Performer는 실패 보고 없이 종료 **[RPA 파트와 합의 필요]** |
| `convention.md` §2.1·§2.2 | 비동기 접수 202. `POST /api/calls/{id}/retry` → `202 {call_id, status, retry_count}`, 에러 404·409 |
| `convention.md` §2.3 | 상태를 바꾸는 동작 API는 결과 상태를 돌려준다. 동작 결과의 식별자 키는 `call_id` |

### 2.2 해석

- W-05는 **상태 표시만** 바꾸는 API다. Orchestrator·로봇을 호출하지 않는다. 실제 재처리는 다음 Dispatcher 주기(R-09 조회 → Queue 추가 → R-05 `QUEUED`)에서 일어난다. 그래서 202.
- "정체 건"의 범위는 문서상 `REGISTERED`·`QUEUED`·`STT_DONE`이다(§4.1 참조).
- 재처리 대상에는 정상 완료(`STORED`)도 포함된다 = **재분석**. 기존 transcript·analysis는 지우지 않으며, 다음 처리의 적재가 덮어쓴다(`put_transcript`는 `STT_DONE`에서 덮어쓰기, `put_analysis`는 `action_status`를 덮어쓰지 않음).

---

## 3. 프론트 초안의 가정 (`origin/front`, 미병합)

| 파일 | 내용 |
|---|---|
| `frontend/src/api/calls.ts` | `retryCall = (id) => apiSend<RetryResult>('POST', \`/calls/${id}/retry\`)` — **본문 없음**. `useRetryCall`은 성공·실패 모두 `onSettled`에서 목록·통계·상세를 다시 조회("409 등이면 화면 상태가 낡았다는 뜻") |
| `frontend/src/api/types.ts` | `RetryResult { call_id: number; status: CallStatus; retry_count: number }`. `CallBase.is_stale?: boolean`(R-11 이후) |
| `frontend/src/api/client.ts` | `apiSend`: 본문이 있으면 JSON 파싱, 비어 있으면 `undefined` — 202·204 모두 처리 가능 |
| `frontend/src/lib/status.ts` `canRetry` | `FAILED`·`NEEDS_REVIEW`·`STORED` → 가능. 그 밖에는 `stale && status !== 'RETRY_REQUESTED'`. 정체 여부를 모르면 정체 아님으로 봄 |
| `frontend/src/pages/CallDetailPage.tsx` | 상세의 "재처리·삭제" 패널. 불가 안내: 처리 중 → "처리 중인 상담은 재처리를 요청할 수 없어요.", `RETRY_REQUESTED` 정체 → "RPA 담당자에게 로봇 점검을 요청해 주세요.", 그 외 `RETRY_REQUESTED` → "다음 처리 주기에 반영돼요." 성공 토스트: "재처리를 요청했어요. 다음 처리 주기에 반영돼요" |
| `frontend/src/mocks/handlers.ts` | 없음 404, `canRetry` 불가 409 `INVALID_STATE_TRANSITION`, 성공 시 `status=RETRY_REQUESTED`, `retry_count+1`, `processing_log`에 `{step: RETRY, status: RETRY}` 추가, **202** + `RetryResult` |
| `features_frontend.md` | F-V08 재처리 요청(가능한 상태에서만), F-U03 "실패·정체 건 재처리 요청, 멈춘 재처리 요청은 로봇 점검 안내". 상태 표: `RETRY_REQUESTED` = "불가 (정체면 로봇 점검 안내)". `is_stale`이 없으면(R-11 이전) 처리 중 건은 재처리 요청 불가 |

정리: 프론트는 `convention.md` 계약(202, 본문 없음, `{call_id, status, retry_count}`)과 일치한다. **`RETRY_REQUESTED` 재요청은 프론트가 막고 있으나 서버는 정체면 허용한다.** 또 R-11 이전에는 프론트가 `is_stale`을 모르므로 처리 중 건의 재처리 버튼이 비활성이다 → 서버의 정체 허용 경로는 R-11(`is_stale` 노출) 이후에야 화면에서 쓰인다.

---

## 4. 쟁점별 조사

### 4.1 정체된 `RETRY_REQUESTED` 재요청 [핵심]

| 근거 | 허용? |
|---|---|
| `state_machine.py` `_is_allowed` + `STALE_ELIGIBLE` | 허용 (`retry_count` +1) |
| `test_state_machine.py` `test_stale_processing_call_can_be_retried` | `RETRY_REQUESTED` 포함해 허용을 테스트로 고정 |
| `features.md` R-02·W-05, `architecture.md` §4.3·§5 표, `input_flow.md` §6.3 | 대상에 없음 |
| `architecture.md` §12 | `RETRY_REQUESTED` 정체 = Dispatcher 정지 → 로봇 점검 요청 |
| 프론트 `canRetry`·안내 문구 | 불가, 로봇 점검 안내 |

`STALE_ELIGIBLE`은 R-11(정체 감지)에도 쓰이는 집합이라 `RETRY_REQUESTED`를 포함하는 것이 맞다. 문제는 **"정체 감지 대상"과 "정체 시 재처리 허용 대상"을 같은 집합으로 쓴 점**이다.

허용할 경우의 실제 영향: `RETRY_REQUESTED` 상태에서 다시 `RETRY_REQUESTED`로 바뀌며 `retry_count`만 오른다. Dispatcher가 멈춘 원인은 해결되지 않는다. Dispatcher가 이전 `retry_count` 값으로 이미 Queue Item을 만들고 `PATCH QUEUED` 보고 직전에 멈춘 경우라면, 재개 후 새 Reference(`call_id-retry(N+1)`)로 한 번 더 Queue에 넣을 수 있다(R-09 응답 시점과 Dispatcher 동작에 따라 다름 **[확인 필요]**).

선택지는 §8 D-1.

### 4.2 `retry_count` 증가 위치

- 이미 상태 머신이 `RETRY_REQUESTED` 전이 때 올린다. W-05에서 다시 올리면 안 된다.
- R-05(`mark_queued`)는 올리지 않는다(`test_robot_status.py`: "재처리 횟수는 웹 요청 때 올라가므로 여기서 바꾸지 않는다").
- R-09는 저장된 `retry_count`를 그대로 내려주고, Dispatcher가 `call_id-retryN`을 만든다(`input_flow.md` §6.3). 따라서 W-05 응답의 `retry_count` = R-09가 줄 값 = Queue Reference의 N. 일관된다.
- 웹 서비스로 옮기는 안은 상태 머신·A의 테스트(`test_retry_count_accumulates` 등)를 바꿔야 해서 이점이 없다.

### 4.3 정체 판정 기준 시각·임계값

- 기준 컬럼: `call_record.status_changed_at`(상태 머신이 전이마다 앱 시각 `datetime.now(UTC)`로 갱신). 최초 등록 행만 DB 기본값 `func.now()`(DB 트랜잭션 시작 시각)로 채워진다 → `REGISTERED` 정체 판정은 앱·DB 시계 차이만큼 오차가 생길 수 있다(단일 VM 배포라 실무상 무시 가능 **[가정]**).
- 판정 시각: 요청 처리 시 `transition` 안의 `datetime.now(UTC)`. 서비스가 `now`를 넘길 필요는 없다(테스트는 `status_changed_at`을 충분히 과거/최근으로 만들면 된다. 예: 60분 전 / 1분 전).
- 임계값: `Settings.stale_threshold_min`(기본 30, `>0`). **`request.app.state.settings`에서 읽는다**(`get_settings_from_app`). 모듈 함수 `transition()`은 `get_settings()`(lru_cache, .env)를 읽어 `create_app(Settings(...))`로 넘긴 값과 다를 수 있으므로 웹 API에서는 쓰지 않는 편이 맞다. R-11(정체 감지)과 같은 설정·같은 `is_stale` 함수를 써서 화면의 `is_stale`과 서버 판정이 일치해야 한다.
- 경계: `status_changed_at < now - threshold` (정확히 30분은 정체 아님).
- 프론트가 `is_stale`을 본 시점과 요청 시점 사이에 로봇이 진행시키면 서버는 409를 준다 → 프론트는 `onSettled`로 재조회. 정상 동작.

### 4.4 없는 건·삭제된 건

- 상태 머신이 `deleted_at IS NULL` 조건으로 잠금 조회 → 없거나 삭제면 `AppError(NOT_FOUND)` 404. W-05에서 별도 처리 불필요.
- 경로 `id`는 기존 패턴대로 `Path(ge=1, le=BIGINT_MAX)` → 0·음수·BIGINT 초과는 422(DB 오버플로 500 방지). `BIGINT_MAX`는 `app/api/web/calls.py`와 `app/schemas/robot.py`에 각각 정의되어 있다.
- 후속 영향(W-05 밖): `RETRY_REQUESTED` 건이 W-04로 삭제되면 R-09가 `deleted_at IS NULL`로 걸러야 Dispatcher가 삭제 건을 다시 돌리지 않는다 **[A 확인 필요]**.

### 4.5 동시성 (로봇과 경합)

| 상황 | 결과 |
|---|---|
| 웹 재처리 ↔ 로봇 적재/실패 보고가 같은 건에 동시 도착 | 둘 다 `SELECT ... FOR UPDATE`(로봇은 `_lock_call`, 웹은 `transition`)로 직렬화. 먼저 잠근 쪽이 커밋할 때까지 다른 쪽은 대기 |
| 정체 `QUEUED`에 웹 재처리가 먼저 | `RETRY_REQUESTED`. 늦게 깨어난 이전 Performer의 transcript·analysis·FAIL은 409(`test_stuck_call_is_recovered_...`로 검증됨) |
| 로봇이 먼저 진행(`QUEUED → STT_DONE`) | `status_changed_at` 갱신 → 웹 재처리 시점엔 정체 아님 → 409 |
| 재처리 버튼 연타 / 두 사람 동시 요청 | 첫 요청 202, 두 번째는 `RETRY_REQUESTED`(정체 아님) → 409. 선택지 §8 D-4 |
| 웹 재처리 ↔ W-03 검토 완료(`NEEDS_REVIEW → STORED`) | 둘 다 상태 머신 경유라 직렬화. 늦은 쪽은 상태에 따라 202(`STORED → RETRY_REQUESTED`) 또는 409 |
| 웹 재처리 ↔ W-04 삭제 | 삭제가 잠금 없이 `deleted_at`만 쓰면 재처리와 순서가 어긋날 수 있음(삭제 후 `RETRY_REQUESTED`로 바뀌는 건 불가 — 재처리 쪽 잠금 조회가 `deleted_at IS NULL` 확인. 반대로 재처리 커밋 후 삭제는 정상). 삭제 구현이 잠금을 쓸지는 W-04 쪽 판단 |

- 잠금 대기 시간 제한(`lock_timeout`)은 설정되어 있지 않다. 로봇 트랜잭션이 짧아 문제 없다고 보지만, 길게 잡는 트랜잭션이 생기면 웹 요청이 그만큼 대기한다 **[가정]**.
- **식별자 맵 주의 (§6.3)**: W-05 서비스가 `transition` 전에 같은 세션으로 건을 잠금 없이 읽으면, `transition`의 `FOR UPDATE` 결과가 그 낡은 객체로 돌아와 상태·`status_changed_at`이 갱신되지 않는다. 사전 조회가 필요하면 첫 조회를 잠금 조회로 하거나 `populate_existing`을 쓴다.

### 4.6 기록: `processing_log` / `edit_history`

- `processing_log`: 상태 머신이 1행 남긴다. `step=RETRY`, `status=RETRY`, `message="[web] FAILED -> RETRY_REQUESTED"`(+ `: {reason}`). 상세 화면(W-02)에 그대로 보인다. 프론트 목업도 같은 `{step: RETRY, status: RETRY}`를 추가한다.
- `reason` 후보: 없음 / 서버가 정하는 고정 문구(예: 정체 복구 시 `"stale"`) / 사용자 입력. 프론트는 본문을 보내지 않는다 → §8 D-2.
- `edit_history`: 사람이 **필드 값**을 바꾼 이력(`field`, `before_val`, `after_val`, `editor`)이다. 재처리는 필드 수정이 아니고 `editor` 입력도 없다(프론트 본문 없음). 상태 변화는 `processing_log`에 남으므로 `edit_history`에는 쓰지 않는 것이 자연스럽다 → §8 D-3.
- 개인정보: `reason`을 사용자 입력으로 받으면 `processing_log.message`에 자유 텍스트가 들어간다(로그 정리 배치 O-05 대상). 응답·에러에는 넣지 않는다(`convention.md` §3.4).

### 4.7 요청·응답 계약

| 항목 | 내용 |
|---|---|
| 요청 | `POST /api/calls/{id}/retry`, 본문 없음 (프론트 초안과 일치) |
| 성공 | **202** `{"call_id": 12, "status": "RETRY_REQUESTED", "retry_count": 1}` (`convention.md` §2.2, `architecture.md` §4.3, 프론트 `RetryResult`) |
| 404 | `NOT_FOUND`, `detail: null` — 없음 또는 소프트 삭제 |
| 409 | `INVALID_STATE_TRANSITION`, `detail: {"current_status": "QUEUED", "requested_status": "RETRY_REQUESTED"}` |
| 422 | 경로 `id` 범위 밖 (앱 전체 공통) |
| OpenAPI | `responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION)`, `status_code=202`, tags `calls`, operationId = 함수 이름(앱 전체 고유, 예: `retry_call`) |
| 응답 모델 | 새 모델 필요(예: `CallRetryResult` / `RetryResult`). 위치 후보: `app/schemas/call.py`(W-03·W-12가 요청 모델을 추가할 가능성 → 충돌) 또는 새 파일 `app/schemas/retry.py` |
| 계약 파일 | `docs/api/openapi.json` 재생성 필수(`test_committed_openapi_is_up_to_date`) |

200(상세 반환)·204(본문 없음)는 규약과 프론트 가정에 어긋나므로 택하지 않는 편이 맞다. 202에 `is_stale`을 넣을 필요는 없다(전이 직후는 항상 정체 아님).

### 4.8 정체 사유가 응답·로그에 드러나는가

현재 `processing_log.message`는 `"[web] QUEUED -> RETRY_REQUESTED"`라서 이전 상태가 처리 중이었다는 점으로 정체 복구임을 알 수 있다. 별도 표시가 필요하면 `reason`에 넣는다(§8 D-2).

---

## 5. 재사용 지점

| 필요 | 재사용 | 비고 |
|---|---|---|
| 전이·잠금·404·409·`retry_count`·로그 | `CallStateMachine(db, stale_threshold_min=...).transition(call_id, CallStatus.RETRY_REQUESTED, actor="web", reason=...)` | `flush`만 함 → 서비스가 `commit` |
| 임계값 | `deps.get_settings_from_app` → `settings.stale_threshold_min` | `get_robot_service`와 같은 방식 |
| DB 세션 | `deps.get_db` / `DbSession` | |
| 경로 검증 | `Path(ge=1, le=BIGINT_MAX)` | `app/api/web/calls.py` 또는 `app/schemas/robot.py`의 상수 |
| 로그 `call_id` 바인딩 | `app.core.logging.bind_call_id(request, call_id)` | |
| OpenAPI 에러 문서화 | `app.schemas.common.error_responses` | |
| 에러 | `InvalidTransition`(409), `AppError(NOT_FOUND)` — 모두 상태 머신이 던짐 | 서비스에서 새로 던질 것 없음 (D-1에서 서비스 가드를 택하면 `InvalidTransition` 재사용) |
| 테스트 데이터 | `tests/factories.make_call_record`(통합), `tests/integration/conftest.api`/`robot_client` | |

---

## 6. 처리 흐름

### 6.1 기본 흐름 (안)

```text
라우터: retry_call(call_id, request, service)
  bind_call_id(request, call_id)
  call = service.request_retry(call_id)          # 202
  return RetryResult(call_id=call.id, status=call.status, retry_count=call.retry_count)

서비스: request_retry(call_id)
  call = machine.transition(call_id, RETRY_REQUESTED, actor="web", reason=?)
  db.commit()
  return call
```

- `commit` 후 `call` 속성 접근은 만료 후 재조회(세션 `expire_on_commit` 기본 True)로 1회 SELECT가 더 나간다. 로봇 라우터도 같은 방식(`RobotCallStatus(call_id=call.id, status=call.status)`)이라 허용 범위. 커밋 전에 값을 꺼내 두면 재조회를 피할 수 있다.
- 실패(404·409) 시 서비스는 `commit`하지 않는다. 요청 세션은 `get_db`가 닫으며 롤백된다.

### 6.2 D-1에서 "서비스 가드"를 택할 때

```text
call = SELECT ... WHERE id=? AND deleted_at IS NULL FOR UPDATE   # 첫 조회부터 잠금
if call is None: 404
if call.status == RETRY_REQUESTED: raise InvalidTransition(RETRY_REQUESTED, RETRY_REQUESTED)
machine.transition(...)   # 같은 세션·같은 잠금 안에서 다시 FOR UPDATE (RobotService 패턴)
```

### 6.3 식별자 맵 실측

스크래치 폴더에서 SQLAlchemy 2.0.58로 확인:

```text
세션 s1에서 get(C, 1) → status=STT_DONE 로드
다른 연결에서 status=STORED로 갱신·커밋
s1.scalars(select(C).where(id==1).with_for_update()).one().status          → STT_DONE (낡은 값, 같은 객체)
s1.scalars(select(C)...with_for_update().execution_options(populate_existing=True)).one().status → STORED
```

→ 잠금 조회라도 이미 로드된 객체의 속성은 덮어쓰지 않는다. W-05 서비스에서 `transition` 전 잠금 없는 조회(예: `CallRepository.get_call`)를 두면 정체 판정·현재 상태가 낡을 수 있다. 상태 머신만 부르거나, 첫 조회를 잠금 조회로 한다.

---

## 7. 파일 구조 — 동시 작업과의 충돌

같은 시기에 W-04(삭제)·W-03/W-12(PATCH)가 `app/api/web/calls.py`, `app/services/call_service.py`, `app/api/deps.py`를 수정한다.

| 안 | 변경 파일 | 충돌 가능성 | 비고 |
|---|---|---|---|
| A. 기존 파일에 추가 | `api/web/calls.py`(라우트), `services/call_service.py`(메서드), `api/deps.py`(`get_call_service`에 설정 주입 변경), `schemas/call.py`(응답 모델) | **높음** — 네 파일 모두 동시 수정 대상. 특히 `CallService` 생성자 변경(세션·설정 주입)은 PATCH 작업과 정면 충돌 | `architecture.md` §3.2는 "call_service.py: 웹 조회·수정·삭제·재처리 요청"으로 적어 둠 |
| B. 별도 라우터·서비스 | 새 `api/web/retry.py`(prefix `/api/calls`, tags `calls`), 새 `services/retry_service.py`, 새 `schemas/retry.py`(또는 `call.py` 끝), `deps.py`에 `get_retry_service` 추가, `main.py` `include_router` 1줄 | **낮음** — `deps.py` 끝에 함수 추가가 다른 작업의 추가와 같은 위치면 텍스트 충돌(해결 쉬움) | 경로가 `/api/calls/{id}/retry`로 같은 prefix지만 라우터를 나눠도 문제없음(메서드+경로 고유). 문서 §3.2와 파일 배치가 달라지므로 문서 갱신 필요 |
| B′. B + 의존성도 라우터 모듈 안 | B에서 `deps.py`를 건드리지 않고 `retry.py`에 `get_retry_service` 정의(`get_db`·`get_settings_from_app` import) | **가장 낮음** | "서비스 주입은 deps.py" 관례에서 벗어남 |
| C. 기존 `CallService`를 두고 메서드만 추가, 상태 머신은 메서드 인자로 | `call_service.py` 메서드 추가, `calls.py` 라우트 추가 | 중간 — 같은 파일 끝에 추가하면 텍스트 충돌 | 생성자 변경은 피함 |

어느 안이든 `docs/api/openapi.json`은 양쪽 작업이 모두 재생성하므로 병합 시 충돌한다 → 나중에 병합하는 쪽이 병합 후 `uv run python -m scripts.export_openapi`로 다시 만든다. `main.py`는 B·B′에서만 1줄 추가(PATCH·DELETE는 기존 `calls.router`에 붙으므로 `main.py`를 건드리지 않을 가능성이 높음).

---

## 8. 결정 필요

| ID | 항목 | 선택지 | 권장안 |
|---|---|---|---|
| **D-1 [핵심]** | 정체된 `RETRY_REQUESTED`의 재요청 | (a) 상태 머신 그대로 허용(202, `retry_count` +1) — 문서·프론트 수정 필요 / (b) W-05 서비스에서 `RETRY_REQUESTED`면 409(잠금 조회 후 가드, §6.2) / (c) A에게 상태 머신 `_is_allowed`의 정체 재처리 대상을 `REGISTERED`·`QUEUED`·`STT_DONE`으로 좁혀 달라고 요청(`STALE_ELIGIBLE`은 R-11용으로 유지), A의 테스트 수정 포함 | **(c)**. 전이 규칙은 상태 머신에만 둔다는 원칙(`state_machine.py` 머리말, features R-02)과 문서·프론트를 모두 만족. A 반영 전까지 W-05는 (b)로 막거나, (c) 반영을 선행 조건으로 둔다 |
| **D-2 [핵심]** | 요청 본문(`reason`·`editor`) | (a) 본문 없음, `reason` 미사용 / (b) 본문 없음, 서버가 `reason`을 정함(정체 복구면 예: `"stale"`) / (c) 선택 본문 `{reason?, editor?}` — 선택 필드 추가는 호환 변경 | **(a)** 또는 **(b)**. 프론트는 본문을 보내지 않고 규약·목업도 본문이 없다. 필요해지면 (c)를 호환 변경으로 추가 |
| D-3 | `edit_history` 기록 | (a) 기록 안 함(`processing_log`만) / (b) `field="status"` 행 추가(`editor` 없음) | **(a)**. 필드 수정이 아니고 `editor` 입력이 없다. 상태 이력은 `processing_log`가 담당 |
| D-4 | 이미 `RETRY_REQUESTED`인 건의 재요청(연타·동시 요청) | (a) 409(현재 동작) / (b) 202로 멱등 처리(`retry_count` 그대로) | **(a)**. 규약 §2.2·프론트 목업과 같고, 프론트가 `onSettled`로 재조회한다. 연타는 프론트가 `isPending`으로 막는다 |
| **D-5 [핵심]** | 파일 구조 | §7 A / B / B′ / C | **B**(별도 `retry.py` 라우터 + `retry_service.py` + 응답 스키마 분리, `deps.py`에 getter 1개). `deps.py` 충돌이 걱정되면 B′. 병합 후 `architecture.md` §3.2·`openapi.json` 갱신 |
| D-6 | 성공 상태 코드·본문 | 202 `{call_id, status, retry_count}` / 200 상세 / 204 | **202 `{call_id, status, retry_count}`** (규약·아키텍처·프론트 확정값. 결정이라기보다 확인) |
| D-7 | 임계값 주입 | (a) `get_settings_from_app`으로 받은 값으로 `CallStateMachine` 생성 / (b) 모듈 함수 `transition()`(`get_settings()`) | **(a)**. 테스트·운영 모두 `create_app`에 넘긴 설정과 일치 |
| D-8 | 응답 모델 위치·이름 | `schemas/call.py`에 추가 / 새 `schemas/retry.py`. 이름 `CallRetryResult` / `RetryResult` | 새 파일 + 프론트 타입과 같은 `RetryResult`(OpenAPI 스키마 이름이 프론트 생성 타입과 맞음) **[가정]** |

---

## 9. 테스트 전략

Docker 사용 가능 → 통합 테스트(실제 PostgreSQL)를 중심으로 한다.

### 9.1 통합 (`tests/integration/test_retry_api.py` 등, `api` 또는 `robot_client` + `db`)

| 케이스 | 기대 |
|---|---|
| `FAILED`·`NEEDS_REVIEW`·`STORED` (파라미터화, `status_changed_at`=방금) | 202, `{call_id, status: RETRY_REQUESTED, retry_count: 이전+1}`, DB 상태·`status_changed_at` 갱신, `processing_log` 1행(`RETRY`/`RETRY`, 메시지 `[web] {src} -> RETRY_REQUESTED`) |
| 정체 `REGISTERED`·`QUEUED`·`STT_DONE` (`status_changed_at`=60분 전) | 202 |
| 정체 아님 `REGISTERED`·`QUEUED`·`STT_DONE` (1분 전) | 409, `detail == {current_status: src, requested_status: RETRY_REQUESTED}`, 상태·`retry_count`·로그 불변 |
| `RETRY_REQUESTED` 정체 아님 / 정체 | 409 / D-1 결정에 따름 |
| 기존 `retry_count=2`인 `FAILED` | 응답 `retry_count == 3` (누적) |
| 없는 id / 소프트 삭제 | 404 `NOT_FOUND`, `detail: null` |
| `id=0`, `id=BIGINT_MAX+1` | 422 |
| 같은 건 두 번 요청 | 202 → 409 |
| 커밋 확인 | 응답 후 `db.refresh(call)`로 상태 확인(테스트 세션은 SAVEPOINT라 롤백되지만 같은 연결에서 보임) |
| 상세 반영 | 이어서 `GET /api/calls/{id}`의 `status`·`retry_count`·`processing_log` 마지막 항목 |
| 임계값 설정 반영 | `create_app(Settings(_env_file=None, stale_threshold_min=5))` + `get_db` override, 10분 전 `QUEUED` → 202 (기본 30이면 409) |

- 시간 경계는 상태 머신 테스트가 이미 다룬다(`test_stale_boundary_is_exclusive`). API 테스트는 여유 있는 값(1분 / 60분)으로 시계 흔들림을 피한다.
- 시뮬레이션: `test_robot_simulation.py`의 `web_retry()`를 실제 API 호출로 바꾸면 W-05 → R-05 → 재적재 E2E가 된다. 다만 이 파일은 A의 R-12이므로 바꿀지 **[A 확인 필요]**. 새 테스트 파일에서 같은 흐름(실패 → 웹 API 재처리 → `PATCH status QUEUED` → 재적재 → `STORED`, `retry_count == 1`)을 별도로 두는 방법도 있다.
- 동시성: 행 잠금은 `test_transition_locks_the_row`가 이미 확인한다. 두 연결 경합 테스트는 롤백 픽스처(단일 연결) 구조상 어렵고 이득이 작다 → 생략 권장.

### 9.2 단위 (DB 없음)

`tests/unit/test_calls_api.py` 패턴으로 가짜 서비스를 주입해 라우터만 확인: 202·응답 키, 서비스 예외 → 404/409 매핑, 422 경로 검증, OpenAPI(`status 202`, 404·409 문서화, operationId, 응답 스키마 이름). `openapi.json` 재생성 후 `test_committed_openapi_is_up_to_date` 통과.

---

## 10. 다른 파트 확인 필요

### 10.1 백엔드 A (R-02·R-09·R-10·R-11·R-12)

1. **D-1**: 상태 머신의 정체 재처리 허용 대상에서 `RETRY_REQUESTED`를 뺄지(문서·프론트 기준). 빼면 `test_stale_processing_call_can_be_retried`·`test_not_stale_processing_call_cannot_be_retried` 파라미터 조정 필요.
2. R-09 응답 시점: Dispatcher가 받은 `retry_count`와 W-05가 올린 값이 항상 같은지(조회 후 `PATCH QUEUED` 전 재요청 시나리오). R-09에서 `deleted_at IS NULL` 필터 적용 여부.
3. R-09·R-10 일정 — W-05 단독으로는 재처리가 완결되지 않음.
4. `test_robot_simulation.py`의 `web_retry()`를 W-05 API 호출로 바꿀지.
5. 모듈 함수 `state_machine.transition()`(`get_settings()` 사용)을 W-05에서 쓰지 않는 것에 이견이 없는지.

### 10.2 프론트

1. 계약 확인: 본문 없음, 202 `{call_id, status, retry_count}`, 404·409 — 초안과 일치.
2. D-1이 (a)로 가면 `canRetry`·안내 문구 수정 필요. (b)/(c)면 현행 유지.
3. R-11(`is_stale`) 전에는 처리 중 건의 재처리 버튼이 비활성이므로 정체 복구는 R-11 이후 화면에서 가능하다는 점(서버는 그전에도 허용).
4. D-2에서 `reason` 입력을 받기로 하면 입력 UI 추가.

### 10.3 RPA (Dispatcher·Performer)

1. RPA-06: Dispatcher가 R-09 결과의 `retry_count`로 `call_id-retryN` Reference를 만들고 R-05로 `QUEUED` 보고하는 흐름 구현 여부(`origin/csj`에서 재처리 흐름은 확인되지 않음).
2. 정체 건 재처리 후 이전 Queue 건의 늦은 요청 409 → Performer가 실패 보고 없이 종료(`input_flow.md` §6.3 **[RPA 파트와 합의 필요]**).
3. `STORED`·`NEEDS_REVIEW` 재처리(재분석) 시 엑셀 행 처리(덮어쓰기/추가) 기준.
4. `RETRY_REQUESTED` 정체 시 로봇 점검 연락 경로(`architecture.md` §12).
