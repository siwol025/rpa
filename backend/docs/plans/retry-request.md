# 재처리 요청 상세 구현 계획 — `POST /api/calls/{id}/retry`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-05 재처리 요청 (P1, Phase 2, 선행 R-02) — 요구: PRD WEB-09 |
| 기준 코드 | `2bde1c6` (W-07 웹 업로드 반영 이후) |
| 근거 | `docs/researchs/retry-request.md` v0.1(이하 "리서치"), `api/convention.md` v0.1 §2.2·§2.3, `architecture.md` §3.2·§4.3·§5, `app/services/state_machine.py`·`robot_service.py`, `app/api/deps.py`, `app/main.py`, `app/api/web/calls.py`, `app/api/robot/calls.py`, `app/schemas/{call,common,robot}.py`, `app/core/errors.py`, `tests/conftest.py`, `tests/factories.py`, `tests/integration/{conftest,test_state_machine,test_calls_api,test_robot_simulation}.py`, `tests/unit/{conftest,test_calls_api,test_openapi}.py`, `scripts/export_openapi.py` |
| 기준 버전 | FastAPI 0.165.0 / SQLAlchemy 2.0.58 / pydantic 2 (`.venv` 설치본) |
| 사전 검증 | 이 문서의 코드·테스트를 `2bde1c6` 레포 전체의 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). **기존 710 + 신규 31(단위 11·통합 20) = 741 통과**, 2 skip(수동 Drive). Docker(testcontainers) 사용. `ruff check`·`ruff format --check`·`mypy .`(106파일) 통과. `openapi.json` 재생성(추가 98줄, 삭제 없음) 후 `test_committed_openapi_is_up_to_date` 통과. 가드·잠금 읽기 테스트는 해당 코드를 빼면 실패하는 것도 확인(§6.3) |

---

## 1. 목표와 범위

### 1.1 목표
1. 웹 대시보드가 본문 없이 `POST /api/calls/{id}/retry`를 보내면 건을 `RETRY_REQUESTED`로 바꾸고 **202 `{call_id, status, retry_count}`** 를 돌려준다. 실제 재처리는 다음 Dispatcher 주기(R-09 조회 → Queue 추가 → R-05 `QUEUED`)에서 일어난다.
2. 전이·`retry_count` +1·`processing_log` 기록·404·409·행 잠금은 **상태 머신(`CallStateMachine.transition`)에 맡긴다.** 웹 쪽에서 `retry_count`를 다시 올리지 않는다.
3. 정체 기준(`STALE_THRESHOLD_MIN`)은 `create_app`에 넘긴 앱 설정에서 읽는다.
4. 문서·프론트 기준과 달리 상태 머신이 허용하는 "정체된 `RETRY_REQUESTED`의 재요청"을 **임시 가드로 409** 처리한다(§3.1 D-1).

### 1.2 포함
- `app/schemas/retry.py`(응답 모델 `RetryResult`), `app/services/retry_service.py`(서비스 + 임시 가드), `app/api/web/retry.py`(라우터 + 서비스 의존성)
- `app/main.py`: 라우터 import 1곳 + `include_router` 1줄
- `docs/api/openapi.json` 재생성
- 테스트: `tests/unit/test_retry_api.py`(라우터·OpenAPI, DB 없음), `tests/integration/test_retry_api.py`(실제 PostgreSQL)
- `docs/architecture/architecture.md` §3.2 디렉터리 구조 주석 갱신

### 1.3 제외
- 상태 머신(`state_machine.py`) 수정 — 정체 재처리 대상 축소는 A가 한다(§9.1 A1). 이 작업은 손대지 않는다.
- `app/api/deps.py`, `app/api/web/calls.py`, `app/services/call_service.py`, `app/schemas/call.py` 수정 — 같은 시기 다른 작업(W-03·W-04·W-12)이 수정하는 파일이라 건드리지 않는다(§3.1 D-5).
- 요청 본문(`reason`·`editor`), `edit_history` 기록(D-2·D-3).
- R-09 재처리 대상 조회, R-10 재처리용 음성 다운로드, R-11 `is_stale` 노출 — 별도 기능. W-05만으로는 재처리가 끝까지 돌지 않는다.
- `tests/integration/test_robot_simulation.py`의 `web_retry()`를 API 호출로 바꾸는 일 — A(R-12) 소유 파일(§9.1 A4).
- `docs/api/convention.md` — §2.2에 이미 `202 {call_id, status, retry_count}`, 404·409가 적혀 있어 바꿀 내용이 없다.

### 1.4 다른 기능이 사용할 공개 인터페이스

| 이름 | 위치 | 비고 |
|---|---|---|
| `RetryResult` | `app/schemas/retry.py` | OpenAPI 스키마 이름. 프론트 초안 타입 `RetryResult`와 같다 |
| `RetryService.request_retry(call_id) -> RetryResult` | `app/services/retry_service.py` | 커밋까지 한다 |
| `get_retry_service` | `app/api/web/retry.py` | 테스트에서 `dependency_overrides` 키로 쓴다 |
| operationId `retry_call` | `app/api/web/retry.py` | 앱 전체에서 고유해야 한다(`_operation_id`) |

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 확인 항목 | 결과 |
|---|---|
| `CallStateMachine.transition` | 리서치 §1.2와 같다. `FOR UPDATE` 조회 → 404 / `_is_allowed` → `InvalidTransition`(409) → `status`·`status_changed_at` 갱신, `RETRY_REQUESTED`면 `retry_count += 1` → `ProcessingLog(step=RETRY, status=RETRY, message="[web] {src} -> RETRY_REQUESTED")` → `flush`(커밋 없음) |
| `STALE_ELIGIBLE` | `REGISTERED`·`QUEUED`·`STT_DONE`·`RETRY_REQUESTED`. `_is_allowed`가 이 집합 전체에 정체 시 `RETRY_REQUESTED` 전이를 허용 → 정체된 `RETRY_REQUESTED`도 202가 된다(문서와 다름) |
| 모듈 함수 `transition()` | `get_settings()`(.env, lru_cache)를 읽는다 → 웹 API에서는 쓰지 않는다(D-7) |
| `deps.py` | `DbSession`, `get_settings_from_app`가 이미 있다. `get_robot_service`가 같은 방식으로 `stale_threshold_min`을 주입 |
| `RobotService._lock_call` | `FOR UPDATE` 첫 조회 패턴. 다만 `populate_existing`은 쓰지 않는다 |
| `BIGINT_MAX` | `app/api/web/calls.py`와 `app/schemas/robot.py`에 각각 있다. 웹 라우터라 `calls.py` 것을 import한다(파일을 고치지는 않음) |
| 테스트 픽스처 | `tests/integration/conftest.py`의 `api`(`create_app(Settings(_env_file=None))` + `get_db`→`db_session`), `tests/factories.make_call_record(status=, status_changed_at=, retry_count=, deleted_at=)` |
| operationId 중복 | `retry_call`이라는 함수는 앱에 없다 |
| `main.py` 라우터 등록 | `calls`, `robot_calls`, `stats`, `uploads` 순 |

---

## 3. 결정 사항

### 3.1 사용자 확정 (리서치 §8 권장안 채택)

| ID | 항목 | 결정 |
|---|---|---|
| **D-1** | 정체된 `RETRY_REQUESTED`의 재요청 | **허용하지 않는다(문서·프론트 기준).** 상태 머신의 정체 재처리 대상을 `REGISTERED`·`QUEUED`·`STT_DONE`으로 좁혀 달라고 A에게 요청한다(리서치 D-1 (c)). A 반영 전까지 W-05 서비스에 **임시 가드**를 두어 409 `INVALID_STATE_TRANSITION`, `detail={"current_status": "RETRY_REQUESTED", "requested_status": "RETRY_REQUESTED"}`(상태 머신 거절과 같은 형식)로 막는다. 가드는 `RetryService._reject_already_requested` 한 곳에 두고 제거 조건을 주석과 §9.1 A1에 적는다 |
| D-2 | 요청 본문 | 없음. `reason`도 넘기지 않는다(로그 메시지 `[web] {src} -> RETRY_REQUESTED`만으로 이전 상태가 보인다) |
| D-3 | `edit_history` | 기록하지 않는다. 상태 이력은 `processing_log`가 담당 |
| D-4 | 이미 `RETRY_REQUESTED`인 건의 재요청(연타·동시 요청) | 409. 멱등 202로 만들지 않는다 |
| D-5 | 파일 구조 | **B′안**: 별도 `api/web/retry.py`(서비스 의존성 함수도 이 안에) + `services/retry_service.py` + `schemas/retry.py`. `deps.py`는 바꾸지 않는다. `main.py`는 import 1곳 + `include_router` 1줄 |
| D-6 | 성공 응답 | 202 `{call_id, status, retry_count}` |
| D-7 | 정체 임계값 | `get_settings_from_app` → `settings.stale_threshold_min` → `CallStateMachine(db, stale_threshold_min=...)` |
| D-8 | 응답 모델 이름 | `RetryResult` (프론트 초안 타입과 같은 이름) |

### 3.2 구현 세부 결정

| # | 항목 | 결정 | 이유 |
|---|---|---|---|
| P1 | `retry_count` 증가 위치 | 상태 머신만. 서비스·라우터는 읽기만 | 이중 증가 방지(리서치 §4.2). 통합 테스트로 "기존 2 → 3"을 확인 |
| P2 | 가드의 조회 방식 | `select(CallRecord) ... .with_for_update().execution_options(populate_existing=True)` 로 **첫 조회부터 행 잠금**, 세션에 이미 있는 객체도 DB 값으로 덮어씀 | 리서치 핵심 5: 잠금 없이 먼저 읽으면 `transition`의 `FOR UPDATE`가 식별자 맵의 낡은 객체를 돌려받아 현재 상태·정체 판정이 틀어진다. `populate_existing`은 요청 세션에 이미 로드된 객체가 있더라도(테스트처럼) 최신 행으로 맞춘다. 잠금을 잡은 뒤라 `transition`의 두 번째 `FOR UPDATE`는 같은 트랜잭션에서 즉시 통과하고, 그 사이 다른 트랜잭션이 행을 바꿀 수 없다 |
| P3 | 가드의 404 | 가드도 `deleted_at IS NULL` 조건으로 읽고 없으면 `AppError(NOT_FOUND)` | 상태 머신과 같은 조건·같은 에러. 가드를 지워도 404 동작이 바뀌지 않는다 |
| P4 | 가드의 409 | `InvalidTransition(call.status, CallStatus.RETRY_REQUESTED)` 재사용 | 상태 머신 거절과 응답이 완전히 같다(코드·메시지·`detail` 키). 프론트가 구분할 필요 없음 |
| P5 | 응답 값 추출 시점 | `commit` **전에** `RetryResult`를 만든다 | `expire_on_commit` 기본값 때문에 커밋 후 속성 접근이 SELECT를 한 번 더 보낸다 |
| P6 | 서비스 반환형 | `RetryResult`(스키마) | `CallService`·`UploadService`처럼 서비스가 응답 모델을 돌려주는 기존 관례 |
| P7 | 실패 시 커밋 | 하지 않는다. `get_db`가 세션을 닫으며 롤백 | 404·409에서 아무것도 바뀌지 않음(통합 테스트로 확인) |
| P8 | `now` 인자 | 넘기지 않는다(`transition` 안의 `datetime.now(UTC)`) | 테스트는 `status_changed_at`을 1분 전 / 60분 전으로 만들어 시계 흔들림을 피한다 |
| P9 | 라우트 함수 | `def`(동기) | DB 접근이 동기 세션. 다른 웹 라우터와 같다 |
| P10 | 경로 검증 | `Path(ge=1, le=BIGINT_MAX)` | 0·음수·BIGINT 초과는 422(DB 오버플로 500 방지). 기존 라우터와 같다 |
| P11 | 로그 `call_id` | `bind_call_id(request, call_id)`를 서비스 호출 전에 | 404·409 응답 로그에도 `call_id`가 남는다(로봇 라우터와 같은 순서) |
| P12 | 라우터 prefix·tags | `prefix="/api/calls"`, `tags=["calls"]` | 기존 `calls.router`와 같은 그룹으로 문서화. 메서드+경로가 겹치지 않아 라우터를 나눠도 문제없다 |

---

## 4. 파일별 변경 목록

| 파일 | 구분 | 내용 | 다른 작업과 충돌 |
|---|---|---|---|
| `app/schemas/retry.py` | 신규 | `RetryResult` | 없음 |
| `app/services/retry_service.py` | 신규 | `RetryService.request_retry`, 임시 가드 `_reject_already_requested` | 없음 |
| `app/api/web/retry.py` | 신규 | `router`, `get_retry_service`, `retry_call` | 없음 |
| `app/main.py` | 수정(2줄) | `from app.api.web import calls, retry, stats, uploads`, `app.include_router(retry.router)` | 낮음 — 같은 줄을 다른 작업이 고치면 텍스트 충돌(손으로 합치기 쉬움) |
| `docs/api/openapi.json` | 재생성 | 경로 1개 + `RetryResult` 스키마 추가(98줄 추가, 삭제 없음) | **있음** — 다른 작업도 재생성한다. 병합 시 충돌하면 손으로 고치지 말고 병합 결과 코드로 `uv run python -m scripts.export_openapi`를 다시 실행해 커밋 |
| `tests/unit/test_retry_api.py` | 신규 | 라우터·OpenAPI 11건 | 없음 |
| `tests/integration/test_retry_api.py` | 신규 | 실제 DB 20건 | 없음 |
| `docs/architecture/architecture.md` | 수정 | §3.2 디렉터리 구조 주석 3곳(§7) | 낮음 |

### 4.1 기존 테스트 영향
- `tests/unit/test_openapi.py::test_committed_openapi_is_up_to_date` — `openapi.json` 재생성 전에는 실패한다. 같은 커밋에 재생성 파일을 넣는다.
- `test_operation_ids_are_unique_in_real_app` — `retry_call`이 고유하므로 통과.
- 그 밖의 기존 테스트는 영향 없음(스크래치에서 전체 통과 확인).

---

## 5. 모듈별 코드

### 5.1 `app/schemas/retry.py` (신규)

```python
"""재처리 요청 API 스키마 (W-05)."""

from pydantic import BaseModel

from app.schemas.call import CallStatus


class RetryResult(BaseModel):
    """재처리 요청 접수 결과. 실제 재처리는 다음 Dispatcher 주기에 일어난다."""

    call_id: int
    status: CallStatus
    retry_count: int  # 상태 머신이 올린 값. Dispatcher가 Queue Reference `call_id-retryN`에 쓴다
```

### 5.2 `app/services/retry_service.py` (신규)

```python
"""웹 재처리 요청 유스케이스 (W-05).

전이·`retry_count` +1·`processing_log` 기록·404·409·행 잠금은 상태 머신(R-02)이 한다.
이 서비스는 임시 가드와 커밋만 더한다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.schemas.call import CallStatus
from app.schemas.retry import RetryResult
from app.services.state_machine import CallStateMachine, InvalidTransition


class RetryService:
    def __init__(self, db: Session, *, stale_threshold_min: int) -> None:
        self._db = db
        self._machine = CallStateMachine(db, stale_threshold_min=stale_threshold_min)

    def request_retry(self, call_id: int) -> RetryResult:
        """건을 `RETRY_REQUESTED`로 바꾼다. 실제 재처리는 다음 Dispatcher 주기에 일어난다.

        허용: `FAILED`·`NEEDS_REVIEW`·`STORED`, 정체된 `REGISTERED`·`QUEUED`·`STT_DONE`.
        없는(또는 소프트 삭제된) 건은 404, 그 밖의 상태는 409 `INVALID_STATE_TRANSITION`.
        """
        self._reject_already_requested(call_id)
        call = self._machine.transition(call_id, CallStatus.RETRY_REQUESTED, actor="web")
        # 커밋하면 속성이 만료돼 다시 SELECT하므로 커밋 전에 응답 값을 꺼내 둔다.
        result = RetryResult(call_id=call.id, status=call.status, retry_count=call.retry_count)
        self._db.commit()
        return result

    def _reject_already_requested(self, call_id: int) -> None:
        """[임시 가드] 이미 `RETRY_REQUESTED`인 건은 정체 여부와 관계없이 409.

        상태 머신은 정체된 `RETRY_REQUESTED`의 재요청도 허용하지만, 문서·프론트는 이를
        Dispatcher 정지(로봇 점검 대상)로 보고 재처리 대상에서 뺀다. 상태 머신의 정체 재처리
        대상이 `REGISTERED`·`QUEUED`·`STT_DONE`으로 좁혀지면 이 메서드와 호출 1줄을 지운다.

        첫 조회부터 행 잠금(FOR UPDATE)으로 읽고 `populate_existing`으로 세션에 남은 객체를
        DB 값으로 덮어쓴다. 잠금 없이 먼저 읽으면 뒤이은 `transition`의 잠금 조회가 식별자 맵의
        낡은 객체를 돌려받아 정체 판정이 틀어진다.
        """
        call = self._db.scalars(
            select(CallRecord)
            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one_or_none()
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if call.status == CallStatus.RETRY_REQUESTED:
            raise InvalidTransition(call.status, CallStatus.RETRY_REQUESTED)
```

가드를 지울 때(§9.1 A1 반영 후) 남는 모양:

```python
    def request_retry(self, call_id: int) -> RetryResult:
        call = self._machine.transition(call_id, CallStatus.RETRY_REQUESTED, actor="web")
        result = RetryResult(call_id=call.id, status=call.status, retry_count=call.retry_count)
        self._db.commit()
        return result
```

이때 `select`·`AppError`·`ErrorCode`·`CallRecord`·`InvalidTransition` import도 함께 지운다.

### 5.3 `app/api/web/retry.py` (신규)

```python
"""웹 재처리 요청 API: `POST /api/calls/{call_id}/retry`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.deps import DbSession, get_settings_from_app
from app.api.web.calls import BIGINT_MAX
from app.core.config import Settings
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.common import error_responses
from app.schemas.retry import RetryResult
from app.services.retry_service import RetryService

router = APIRouter(prefix="/api/calls", tags=["calls"])


def get_retry_service(
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> RetryService:
    # 정체 기준은 create_app에 넘긴 설정을 쓴다(get_settings()의 .env 값이 아니라).
    return RetryService(session, stale_threshold_min=settings.stale_threshold_min)


RetryServiceDep = Annotated[RetryService, Depends(get_retry_service)]


@router.post(
    "/{call_id}/retry",
    status_code=202,
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
)
def retry_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: RetryServiceDep,
) -> RetryResult:
    """재처리를 요청한다. 상태만 `RETRY_REQUESTED`로 바꾸고 다음 Dispatcher 주기에 반영된다."""
    bind_call_id(request, call_id)
    return service.request_retry(call_id)
```

- 서비스 의존성 함수를 `deps.py`가 아니라 라우터 모듈에 둔다(B′안). `deps.py`를 동시에 수정하는 작업과 충돌하지 않게 하기 위해서다. 다른 작업이 병합된 뒤 `deps.py`로 옮기는 것은 별도 정리로 한다(§9.4 U2).

### 5.4 `app/main.py` (수정)

```diff
-from app.api.web import calls, stats, uploads
+from app.api.web import calls, retry, stats, uploads
@@
     app.include_router(uploads.router)
+    app.include_router(retry.router)
```

### 5.5 `docs/api/openapi.json` (재생성)

```bash
cd backend && uv run python -m scripts.export_openapi
```

추가되는 내용: `paths["/api/calls/{call_id}/retry"].post`(operationId `retry_call`, tags `calls`, 요청 본문 없음, 응답 202 `RetryResult`·404 `ErrorResponse`(`NOT_FOUND`)·409 `ErrorResponse`(`INVALID_STATE_TRANSITION`)·422·500), `components.schemas.RetryResult`(`call_id`·`status`(`CallStatus` 참조)·`retry_count`, 모두 필수).

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 상태별 허용/거절·`retry_count`·`processing_log`·404·이중 요청·임계값 주입은 **통합 테스트(실제 PostgreSQL)** 로 확인한다. 상태 머신 자체의 전이표·경계는 `test_state_machine.py`가 이미 다루므로 반복하지 않는다.
- 라우터의 경로 검증·에러 매핑·OpenAPI는 단위 테스트(가짜 서비스)로 확인한다(`test_calls_api.py` 패턴).
- 시간 값은 정체 기준 30분에서 멀리(1분 전 / 60분 전) 둔다.
- 통합 테스트는 `api` 픽스처(`get_db` → `db_session`)를 쓴다. 서비스의 `commit()`은 SAVEPOINT 해제로만 동작하고 테스트 끝에 롤백된다. 응답 후 DB 확인은 `db_session.refresh(call)`.

### 6.2 케이스 목록 (구현 순서)

| # | 파일 | 테스트 | 기대 |
|---|---|---|---|
| 1 | unit | `test_retry_returns_202_with_result` | 202, `{call_id, status, retry_count}`, 서비스에 `call_id` 전달 |
| 2 | unit | `test_retry_ignores_request_body` | 본문을 보내도 무시하고 202 (D-2) |
| 3 | unit | `test_retry_not_found_is_404` | 서비스 `AppError(NOT_FOUND)` → 404 표준 에러 |
| 4 | unit | `test_retry_invalid_transition_is_409_with_statuses` | `InvalidTransition` → 409, `detail` 두 키 |
| 5 | unit | `test_retry_rejects_invalid_path_id` ×4 | `0`·`-1`·`BIGINT_MAX+1`·`abc` → 422, `loc == ["path", "call_id"]`, 서비스 미호출 |
| 6 | unit | `test_retry_get_is_405` | `GET` → 405 |
| 7 | unit | `test_openapi_documents_retry_operation` | operationId·tags·본문 없음·응답 {202,404,409,422,500}·202 스키마 `RetryResult` |
| 8 | unit | `test_openapi_retry_result_schema` | 필수 3필드, `status`가 `CallStatus` 참조 |
| 9 | 통합 | `test_retry_finished_call_is_accepted` ×3 | `FAILED`·`NEEDS_REVIEW`·`STORED`(1분 전) → 202 + 응답 본문, DB 상태·`status_changed_at` 갱신, 로그 1행 `("RETRY","RETRY","[web] {src} -> RETRY_REQUESTED")` |
| 10 | 통합 | `test_retry_stale_processing_call_is_accepted` ×3 | `REGISTERED`·`QUEUED`·`STT_DONE`(60분 전) → 202, 로그 1행 |
| 11 | 통합 | `test_retry_count_accumulates` | 기존 2 → 응답·DB 3 (한 번만 증가) |
| 12 | 통합 | `test_retry_does_not_write_edit_history` | `edit_history` 0행 (D-3) |
| 13 | 통합 | `test_retry_is_visible_in_call_detail` | 이어서 `GET /api/calls/{id}`: `status`·`retry_count`·마지막 로그 `RETRY/RETRY` |
| 14 | 통합 | `test_retry_fresh_processing_call_is_409` ×3 | 처리 중(1분 전) → 409, `detail`, 상태·`retry_count`·로그 불변 |
| 15 | 통합 | `test_retry_already_requested_is_409_even_if_stale` ×2 | `RETRY_REQUESTED` 1분 전 / 60분 전 → 모두 409, `current_status=RETRY_REQUESTED`, 불변 (**가드**) |
| 16 | 통합 | `test_retry_twice_second_is_409` | 202 → 409, `retry_count == 1`, 로그 1행 (D-4) |
| 17 | 통합 | `test_retry_missing_call_is_404` | 404 표준 에러, `detail: null` |
| 18 | 통합 | `test_retry_deleted_call_is_404` | 소프트 삭제 → 404, 불변 |
| 19 | 통합 | `test_guard_reads_current_row_not_stale_session_object` | 세션 객체는 `FAILED`, DB 행은 정체된 `RETRY_REQUESTED` → 409(가드가 최신 행을 읽음) (**가드 잠금 읽기**) |
| 20 | 통합 | `test_stale_judgement_uses_current_row_not_stale_session_object` | 세션 객체는 1분 전 `QUEUED`, DB 행은 60분 전 → 202(정체 판정이 최신 행 기준) (**가드 잠금 읽기**) |
| 21 | 통합 | `test_stale_threshold_comes_from_app_settings` | 10분 전 `QUEUED`: 기본 설정 앱 409, `stale_threshold_min=5` 앱 202 (D-7) |

### 6.3 가드·잠금 읽기 테스트가 실제로 잡는지 (스크래치 확인)

| 코드 변형 | 결과 |
|---|---|
| 그대로 | 20건 모두 통과 |
| `populate_existing=True` 제거 | #19·#20 실패 |
| 가드 앞에 잠금 없는 `db.get(CallRecord, id)` 추가 + `populate_existing` 제거 | #19·#20 실패 |
| 가드 호출 제거 | #15(stale)·#19·#20 실패 |

#19·#20은 "다른 요청이 먼저 커밋해 세션 객체가 낡은 상황"을 `db.connection().execute(update(...))`(식별자 맵을 거치지 않는 갱신)로 흉내 낸다. 실제 요청 세션은 요청마다 새로 열리므로 운영에서 이 상황이 생기려면 같은 세션에서 먼저 읽는 코드가 있어야 하는데, 가드가 그런 코드가 되지 않도록 고정하는 테스트다.

### 6.4 케이스 수
단위 11건(파라미터 포함), 통합 20건(파라미터 포함). 합계 31건.

### 6.5 테스트 코드

#### `tests/unit/test_retry_api.py` (신규)

```python
"""재처리 요청 라우터 단위 테스트: 서비스를 가짜로 바꿔 DB 없이 경로 검증·응답·OpenAPI를 본다."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.web.calls import BIGINT_MAX
from app.api.web.retry import get_retry_service
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.schemas.call import CallStatus
from app.schemas.retry import RetryResult
from app.services.state_machine import InvalidTransition

S = CallStatus


class FakeRetryService:
    def __init__(self) -> None:
        self.requested: list[int] = []

    def request_retry(self, call_id: int) -> RetryResult:
        self.requested.append(call_id)
        if call_id == 404:
            raise AppError(ErrorCode.NOT_FOUND)
        if call_id == 409:
            raise InvalidTransition(S.QUEUED, S.RETRY_REQUESTED)
        return RetryResult(call_id=call_id, status=S.RETRY_REQUESTED, retry_count=1)


@pytest.fixture
def fake() -> FakeRetryService:
    return FakeRetryService()


@pytest.fixture
def api(build_app: Callable[..., FastAPI], fake: FakeRetryService) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_retry_service] = lambda: fake
    with TestClient(app) as client:
        yield client


def test_retry_returns_202_with_result(api: TestClient, fake: FakeRetryService) -> None:
    response = api.post("/api/calls/7/retry")

    assert response.status_code == 202
    assert response.json() == {"call_id": 7, "status": "RETRY_REQUESTED", "retry_count": 1}
    assert fake.requested == [7]


def test_retry_ignores_request_body(api: TestClient, fake: FakeRetryService) -> None:
    response = api.post("/api/calls/7/retry", json={"reason": "무시됨"})

    assert response.status_code == 202
    assert fake.requested == [7]


def test_retry_not_found_is_404(api: TestClient) -> None:
    response = api.post("/api/calls/404/retry")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }


def test_retry_invalid_transition_is_409_with_statuses(api: TestClient) -> None:
    response = api.post("/api/calls/409/retry")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"] == {"current_status": "QUEUED", "requested_status": "RETRY_REQUESTED"}


@pytest.mark.parametrize("call_id", ["0", "-1", str(BIGINT_MAX + 1), "abc"])
def test_retry_rejects_invalid_path_id(
    api: TestClient, fake: FakeRetryService, call_id: str
) -> None:
    response = api.post(f"/api/calls/{call_id}/retry")

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["loc"] == ["path", "call_id"]
    assert fake.requested == []


def test_retry_get_is_405(api: TestClient) -> None:
    assert api.get("/api/calls/7/retry").status_code == 405


# ---------------------------------------------------------------- OpenAPI


@pytest.fixture
def operation() -> dict[str, Any]:
    spec = create_app(Settings(_env_file=None)).openapi()
    op: dict[str, Any] = spec["paths"]["/api/calls/{call_id}/retry"]["post"]
    return op


def test_openapi_documents_retry_operation(operation: dict[str, Any]) -> None:
    responses = operation["responses"]

    assert operation["operationId"] == "retry_call"
    assert operation["tags"] == ["calls"]
    assert "requestBody" not in operation
    assert set(responses) == {"202", "404", "409", "422", "500"}
    schema_ref = responses["202"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/RetryResult"
    assert responses["409"]["description"] == "INVALID_STATE_TRANSITION"


def test_openapi_retry_result_schema() -> None:
    schema = create_app(Settings(_env_file=None)).openapi()["components"]["schemas"]["RetryResult"]

    assert set(schema["required"]) == {"call_id", "status", "retry_count"}
    assert schema["properties"]["status"]["$ref"] == "#/components/schemas/CallStatus"
```

#### `tests/integration/test_retry_api.py` (신규)

```python
"""재처리 요청 `POST /api/calls/{id}/retry` (실제 PostgreSQL)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import Settings
from app.main import create_app
from app.models import CallRecord, EditHistory, ProcessingLog
from app.schemas.call import CallStatus
from tests.factories import make_call_record

pytestmark = pytest.mark.integration

S = CallStatus

# 기본 정체 기준 30분에 여유를 둔 값(분). 정확한 경계는 상태 머신 테스트가 다룬다.
FRESH = 1
STALE = 60


def _ago(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def _logs(db: Session, call_id: int) -> list[ProcessingLog]:
    return list(
        db.scalars(
            select(ProcessingLog).where(ProcessingLog.call_id == call_id).order_by(ProcessingLog.id)
        )
    )


def _assert_unchanged(db: Session, call: CallRecord, status: CallStatus, retry_count: int) -> None:
    db.refresh(call)
    assert call.status == status
    assert call.retry_count == retry_count
    assert _logs(db, call.id) == []


# ---------------------------------------------------------------- 허용


@pytest.mark.parametrize("src", [S.FAILED, S.NEEDS_REVIEW, S.STORED])
def test_retry_finished_call_is_accepted(api: TestClient, db_session: Session, src: S) -> None:
    call = make_call_record(db_session, status=src, status_changed_at=_ago(FRESH))
    before = datetime.now(UTC)

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 202
    assert response.json() == {"call_id": call.id, "status": "RETRY_REQUESTED", "retry_count": 1}
    db_session.refresh(call)
    assert call.status == S.RETRY_REQUESTED
    assert call.status_changed_at >= before
    logs = _logs(db_session, call.id)
    assert [(log.step, log.status, log.message) for log in logs] == [
        ("RETRY", "RETRY", f"[web] {src} -> RETRY_REQUESTED")
    ]


@pytest.mark.parametrize("src", [S.REGISTERED, S.QUEUED, S.STT_DONE])
def test_retry_stale_processing_call_is_accepted(
    api: TestClient, db_session: Session, src: S
) -> None:
    call = make_call_record(db_session, status=src, status_changed_at=_ago(STALE))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 202
    assert response.json() == {"call_id": call.id, "status": "RETRY_REQUESTED", "retry_count": 1}
    assert len(_logs(db_session, call.id)) == 1


def test_retry_count_accumulates(api: TestClient, db_session: Session) -> None:
    call = make_call_record(db_session, status=S.FAILED, retry_count=2)

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.json()["retry_count"] == 3
    db_session.refresh(call)
    assert call.retry_count == 3  # 상태 머신이 한 번만 올린다 (웹에서 다시 올리지 않음)


def test_retry_does_not_write_edit_history(api: TestClient, db_session: Session) -> None:
    call = make_call_record(db_session, status=S.FAILED)

    api.post(f"/api/calls/{call.id}/retry")

    edits = db_session.scalars(select(EditHistory).where(EditHistory.call_id == call.id))
    assert list(edits) == []


def test_retry_is_visible_in_call_detail(api: TestClient, db_session: Session) -> None:
    call = make_call_record(db_session, status=S.STORED)

    api.post(f"/api/calls/{call.id}/retry")
    detail = api.get(f"/api/calls/{call.id}").json()

    assert detail["status"] == "RETRY_REQUESTED"
    assert detail["retry_count"] == 1
    assert detail["processing_log"][-1]["step"] == "RETRY"
    assert detail["processing_log"][-1]["status"] == "RETRY"


# ---------------------------------------------------------------- 거절


@pytest.mark.parametrize("src", [S.REGISTERED, S.QUEUED, S.STT_DONE])
def test_retry_fresh_processing_call_is_409(api: TestClient, db_session: Session, src: S) -> None:
    call = make_call_record(db_session, status=src, status_changed_at=_ago(FRESH))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "INVALID_STATE_TRANSITION"
    assert body["detail"] == {"current_status": src, "requested_status": "RETRY_REQUESTED"}
    _assert_unchanged(db_session, call, src, 0)


@pytest.mark.parametrize("minutes", [FRESH, STALE], ids=["fresh", "stale"])
def test_retry_already_requested_is_409_even_if_stale(
    api: TestClient, db_session: Session, minutes: int
) -> None:
    # 임시 가드: 상태 머신은 정체된 RETRY_REQUESTED의 재요청을 허용하지만 이 API는 막는다.
    call = make_call_record(
        db_session, status=S.RETRY_REQUESTED, status_changed_at=_ago(minutes), retry_count=1
    )

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "current_status": "RETRY_REQUESTED",
        "requested_status": "RETRY_REQUESTED",
    }
    _assert_unchanged(db_session, call, S.RETRY_REQUESTED, 1)


def test_retry_twice_second_is_409(api: TestClient, db_session: Session) -> None:
    call = make_call_record(db_session, status=S.FAILED)

    first = api.post(f"/api/calls/{call.id}/retry")
    second = api.post(f"/api/calls/{call.id}/retry")

    assert first.status_code == 202
    assert second.status_code == 409
    db_session.refresh(call)
    assert call.retry_count == 1
    assert len(_logs(db_session, call.id)) == 1


def test_retry_missing_call_is_404(api: TestClient) -> None:
    response = api.post("/api/calls/999999999/retry")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "대상을 찾을 수 없습니다.",
        "detail": None,
    }


def test_retry_deleted_call_is_404(api: TestClient, db_session: Session) -> None:
    call = make_call_record(db_session, status=S.FAILED, deleted_at=_ago(FRESH))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 404
    _assert_unchanged(db_session, call, S.FAILED, 0)


# ---------------------------------------------------------------- 잠금 읽기 순서 (식별자 맵)


def _change_row_behind_session(db: Session, call_id: int, **values: object) -> None:
    """세션의 식별자 맵을 거치지 않고 행만 바꾼다 (다른 요청이 먼저 커밋한 상황 흉내)."""
    db.connection().execute(update(CallRecord).where(CallRecord.id == call_id).values(**values))


def test_guard_reads_current_row_not_stale_session_object(
    api: TestClient, db_session: Session
) -> None:
    # 세션 객체는 FAILED지만 DB는 이미 정체된 RETRY_REQUESTED다.
    call = make_call_record(db_session, status=S.FAILED, retry_count=1)
    _change_row_behind_session(
        db_session, call.id, status=S.RETRY_REQUESTED, status_changed_at=_ago(STALE)
    )

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "RETRY_REQUESTED"
    _assert_unchanged(db_session, call, S.RETRY_REQUESTED, 1)


def test_stale_judgement_uses_current_row_not_stale_session_object(
    api: TestClient, db_session: Session
) -> None:
    # 세션 객체는 방금 바뀐 QUEUED지만 DB의 status_changed_at은 정체 기준을 넘었다.
    call = make_call_record(db_session, status=S.QUEUED, status_changed_at=_ago(FRESH))
    _change_row_behind_session(db_session, call.id, status_changed_at=_ago(STALE))

    response = api.post(f"/api/calls/{call.id}/retry")

    assert response.status_code == 202


# ---------------------------------------------------------------- 설정


@pytest.fixture
def api_threshold_5(db_session: Session) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, stale_threshold_min=5))
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client


def test_stale_threshold_comes_from_app_settings(
    api: TestClient, api_threshold_5: TestClient, db_session: Session
) -> None:
    rejected = make_call_record(db_session, status=S.QUEUED, status_changed_at=_ago(10))
    accepted = make_call_record(db_session, status=S.QUEUED, status_changed_at=_ago(10))

    assert api.post(f"/api/calls/{rejected.id}/retry").status_code == 409  # 기본 30분
    assert api_threshold_5.post(f"/api/calls/{accepted.id}/retry").status_code == 202  # 5분
```

---

## 7. 문서 갱신 (중립 표현)

`docs/architecture/architecture.md` §3.2 디렉터리 구조의 주석만 실제 배치에 맞춘다.

```diff
-│   │   ├── web/                 # uploads.py, calls.py, stats.py, reports.py
+│   │   ├── web/                 # uploads.py, calls.py, retry.py, stats.py, reports.py
@@
-│   ├── schemas/                 # Pydantic: call, transcript, analysis(GenAI JSON), stats, common
+│   ├── schemas/                 # Pydantic: call, transcript, analysis(GenAI JSON), stats, retry, common
@@
-│   │   ├── call_service.py      # 웹 조회·수정·삭제·재처리 요청
+│   │   ├── call_service.py      # 웹 조회·수정·삭제
+│   │   ├── retry_service.py     # 웹 재처리 요청 (상태 머신 호출)
```

- `architecture.md` §4.3·§5 표·§12, `convention.md` §2.2, `features.md` W-05는 이미 구현과 같다(정체 재처리 대상 `REGISTERED`·`QUEUED`·`STT_DONE`, 202 `{call_id, status, retry_count}`, 404·409). 바꾸지 않는다.
- `convention.md`는 다른 작업이 같은 시기에 수정하므로 건드리지 않는다.

---

## 8. 구현 순서와 검증 명령

1. `schemas/retry.py` → 단위 #1~#8 작성(실패) → `api/web/retry.py`·`services/retry_service.py`(가드 없이 `transition` + `commit`)·`main.py` → 단위 통과
2. 통합 #9~#14·#16~#18·#21 작성 → 통과 확인
3. 통합 #15·#19·#20 작성(#15 stale·#19·#20 실패) → 가드 `_reject_already_requested` 추가 → 통과
4. `openapi.json` 재생성 → 전체 검증
5. `architecture.md` §3.2 갱신

```bash
cd backend
export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"   # Windows Git Bash에서 docker CLI
uv run pytest tests/unit/test_retry_api.py tests/integration/test_retry_api.py
uv run python -m scripts.export_openapi
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy .
```

---

## 9. 확인 필요

### 9.1 A (R-02 상태 머신, R-09·R-12)

| # | 항목 | 내용 |
|---|---|---|
| **A1** | **정체 재처리 대상 축소 (임시 가드 제거 조건)** | `CallStateMachine._is_allowed`의 정체 허용 대상을 `REGISTERED`·`QUEUED`·`STT_DONE`으로 좁혀 달라는 요청. `STALE_ELIGIBLE`(R-11 정체 감지용)은 `RETRY_REQUESTED`를 포함한 채 유지하고, 재처리 허용용 집합을 따로 둔다. `test_stale_processing_call_can_be_retried`·`test_not_stale_processing_call_cannot_be_retried` 파라미터 조정 포함. **반영되면** ① `RetryService._reject_already_requested`와 그 호출 1줄, 관련 import 삭제(§5.2), ② 통합 #19·#20 삭제(가드의 잠금 읽기를 고정하는 테스트라 가드와 함께 사라진다), ③ #15는 그대로 둔다(상태 머신 거절로 계속 통과해야 한다) |
| A2 | R-09 응답 | Dispatcher가 받는 `retry_count`가 W-05가 올린 값과 같은지, `deleted_at IS NULL` 필터 적용 여부(삭제된 `RETRY_REQUESTED` 건 재처리 방지) |
| A3 | R-09·R-10 일정 | W-05 단독으로는 재처리가 완결되지 않는다 |
| A4 | `test_robot_simulation.py` `web_retry()` | 상태 머신 직접 호출을 W-05 API 호출로 바꿀지. 바꾸면 W-05 → R-05 → 재적재 E2E가 된다 |
| A5 | 모듈 함수 `state_machine.transition()` | W-05는 쓰지 않는다(`get_settings()`가 `create_app` 설정과 다를 수 있음). 이견이 없는지 |

### 9.2 프론트

| # | 항목 | 내용 |
|---|---|---|
| F1 | 계약 | 본문 없음, 202 `RetryResult {call_id, status, retry_count}`, 404·409 — 초안(`origin/front`)과 일치 |
| F2 | `RETRY_REQUESTED` 재요청 | 정체 여부와 관계없이 409. 초안 `canRetry`·안내 문구(로봇 점검)와 일치 |
| F3 | 정체 복구 버튼 | R-11(`is_stale` 노출) 전에는 처리 중 건의 버튼이 비활성. 서버는 그전에도 정체 건을 허용한다 |

### 9.3 RPA (Dispatcher·Performer)

| # | 항목 | 내용 |
|---|---|---|
| X1 | Reference | R-09의 `retry_count`로 `call_id-retryN`을 만들고 R-05로 `QUEUED` 보고하는 흐름 |
| X2 | 늦은 적재 409 | 정체 건 재처리 후 이전 Queue 건의 적재·FAIL은 409 → 실패 보고 없이 종료(`input_flow.md` §6.3 [RPA 파트와 합의 필요]) |
| X3 | `STORED`·`NEEDS_REVIEW` 재처리 | 재분석 시 엑셀 행 처리 기준(덮어쓰기/추가) |

### 9.4 미확인·가정

| # | 항목 | 내용 |
|---|---|---|
| U1 | 잠금 대기 | `lock_timeout` 미설정. 로봇 트랜잭션이 짧다고 보고 그대로 둔다 [가정] |
| U2 | 의존성 함수 위치 | `get_retry_service`를 라우터 모듈에 둔 것은 동시 수정 충돌 회피용이다. 다른 작업이 병합된 뒤 `deps.py`로 옮길지는 리뷰에서 정한다 |
| U3 | `BIGINT_MAX` 중복 | `calls.py`·`robot.py`에 따로 있다. W-05는 `calls.py` 것을 import만 한다. 공용 위치로 모으는 일은 범위 밖 |

### 9.5 알려진 제한

| # | 항목 | 내용 |
|---|---|---|
| L1 | 가드 동안의 잠금 | 가드와 `transition`이 같은 행을 두 번 `FOR UPDATE`로 읽는다(같은 트랜잭션이라 두 번째는 대기 없음). SELECT 1회 추가 비용 |
| L2 | `REGISTERED` 정체 판정 | 최초 등록 행의 `status_changed_at`은 DB `now()`, 판정은 앱 시각 → 시계 차이만큼 오차(단일 VM이라 무시 [가정]) |
| L3 | 동시 요청 경합 테스트 | 두 연결 경합은 롤백 픽스처(단일 연결) 구조상 테스트하지 않는다. 행 잠금 자체는 `test_transition_locks_the_row`가 확인 |

---

## 10. 구현 시 주의
1. 서비스·라우터에서 `retry_count`를 바꾸지 않는다. 상태 머신만 올린다.
2. `transition` 전에 같은 세션으로 건을 **잠금 없이** 읽지 않는다(`CallRepository.get_call`, `db.get` 등). 가드는 반드시 `with_for_update()` + `populate_existing=True`.
3. 가드의 409는 `InvalidTransition`을 재사용한다. 새 에러 코드·메시지를 만들지 않는다.
4. 404·409 경로에서 `commit`하지 않는다.
5. 모듈 함수 `state_machine.transition()`을 쓰지 않는다. 임계값은 `get_settings_from_app`에서.
6. `deps.py`·`calls.py`·`call_service.py`·`schemas/call.py`를 수정하지 않는다.
7. 라우트를 추가했으므로 `openapi.json`을 재생성해 같은 커밋에 넣는다(`convention.md` §7-1). 병합 충돌 시 재생성으로 해결한다.

---

## 11. 커밋 분할안

작업 단위 ID(W-05 등)는 커밋 메시지에 넣지 않는다.

| 순서 | 커밋 메시지 | 포함 파일 |
|---|---|---|
| 1 | `docs: 재처리 요청 리서치·구현 계획 추가` | `docs/researchs/retry-request.md`, `docs/plans/retry-request.md` |
| 2 | `feat: 재처리 요청 API(POST /api/calls/{id}/retry) 추가 — 상태 머신으로 RETRY_REQUESTED 전이` | `app/schemas/retry.py`, `app/services/retry_service.py`, `app/api/web/retry.py`, `app/main.py`, `docs/api/openapi.json`, `tests/unit/test_retry_api.py`, `tests/integration/test_retry_api.py` |
| 3 | `docs: 아키텍처 디렉터리 구조에 재처리 요청 라우터·서비스 반영` | `docs/architecture/architecture.md` |

- 임시 가드는 API 동작의 일부(409 계약)라 2번에 함께 넣는다. 가드 제거(§9.1 A1 반영 후)는 별도 커밋으로 한다(예: `refactor: 재처리 요청의 임시 RETRY_REQUESTED 가드 제거`).
