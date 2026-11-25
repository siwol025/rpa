# 상담 삭제·메타데이터 보정 상세 구현 계획 — `DELETE /api/calls/{id}`, `PATCH /api/calls/{id}`(메타데이터)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-04 삭제(소프트 삭제), W-12 메타데이터 보정 — W-03(분석 수정·검토 완료)과 같은 PATCH 엔드포인트를 공유하며 W-03 필드는 이번 범위 밖 |
| 작업 위치 | worktree `rpa-followup`. **코드 기준은 `origin/main` `6a8f418`**(로봇 API·상태 머신 병합 후). worktree는 아직 `d9429d5`(HEAD 분리)이므로 main 기준으로 rebase한 뒤 구현한다(§10.5) |
| 근거 | `docs/researchs/call-delete-metadata.md` v0.1(이하 "리서치"), `api/convention.md` v0.1, `plans/call-list-detail.md`, `plans/stats-trend-breakdown.md`, `app/**`(`models/call_record.py`·`edit_history.py`, `repositories/call_repository.py`, `services/call_service.py`·`state_machine.py`·`robot_service.py`, `api/web/calls.py`, `api/deps.py`, `schemas/call.py`·`common.py`·`robot.py`, `core/errors.py`·`db.py`·`middleware.py`, `main.py`), `tests/conftest.py`, `tests/unit/*`, `tests/integration/*`, `scripts/export_openapi.py`, `docs/api/openapi.json` — 모두 `6a8f418` 기준 |
| 기준 버전 | FastAPI 0.165.0 / pydantic 2.14.4 / SQLAlchemy 2.0.58 / psycopg 3 / PostgreSQL 16(testcontainers) |
| 사전 검증 | 이 문서의 코드·테스트를 `origin/main` `6a8f418`의 `backend/` 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). Docker(29.9.3) + testcontainers `postgres:16`으로 통합 테스트까지 실행: **신규 89(단위 69, 통합 20) 모두 통과**, 기존 테스트 회귀 없음(통과 563 → 652). `ruff check .`·`ruff format --check .`·`mypy .`(98파일) 통과, `openapi.json` 재생성 후 `test_committed_openapi_is_up_to_date` 통과. 참고: 스크래치 복사본에는 레포 루트 `uipath/samples/`가 없어 기존 로봇 시뮬레이션·분석 통합 테스트 48건이 `FileNotFoundError`로 실패했는데, 변경 전 main 복사본에서도 같은 48건이 같은 이유로 실패함(환경 차이, 이 변경과 무관). 실제 worktree에서는 해당 폴더가 있으므로 전부 통과해야 함 |

---

## 1. 목표와 범위

### 1.1 목표
1. `DELETE /api/calls/{id}`: 상태와 관계없이 소프트 삭제(`deleted_at`)하고 204. 없는 건·이미 삭제된 건은 404. 삭제도 `edit_history`에 남긴다.
2. `PATCH /api/calls/{id}`: 담당자·고객사·통화 일시를 보낸 키만 바꾸고(`null`은 비우기), `metadata_incomplete`를 다시 판정하고, 바뀐 필드마다 `edit_history` 1행을 남긴 뒤 200 + 갱신된 상세.
3. 첫 쓰기 기능으로서 **트랜잭션·행 잠금 방식**을 정한다: `CallService`가 `Session`을 받아 유스케이스 단위로 커밋, `SELECT ... FOR UPDATE`는 `call_record`만 읽는 `lock_call`.
4. W-03이 같은 요청 모델·서비스 메서드에 **선택 필드와 단계만 추가**하면 되도록 구조를 잡는다.

### 1.2 포함
- `app/schemas/call.py`: `AgentName`·`ClientCompany`·`EditorName` 타입, `METADATA_FIELDS`, `CallUpdateRequest`
- `app/services/call_metadata.py`(신규): `is_metadata_incomplete` (등록 R-04와 공유할 판정)
- `app/repositories/call_repository.py`: `lock_call`, `add_edit_history`
- `app/services/call_service.py`: `FieldChange`, `history_value`, `apply_changes`, `CallService(repository, session)`, `update_call`, `delete_call`
- `app/api/deps.py`: `get_call_service`에서 세션 전달(1줄)
- `app/api/web/calls.py`: `update_call`(PATCH), `delete_call`(DELETE) 라우트
- `docs/api/openapi.json` 재생성, `docs/api/convention.md` 보완(§8)
- 테스트: 단위 + 통합(실제 PostgreSQL, 잠금·이력 포함)

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| W-03 필드(`category`·`question_summary`·`action_summary`·`action_status`·`review_completed`)와 `NEEDS_REVIEW → STORED` 전이 | W-03. 이번에는 `extra="forbid"`로 422. W-03에서 선택 필드를 선언하면 허용으로 바뀜(호환 변경) |
| 수정 이력 조회 API | FE-18 미정. `edit_history(call_id)` 인덱스도 그때(리서치 §9.1 A7) |
| 삭제 취소(복구) | 범위 밖(리서치 §9.4 T2) |
| 로봇 서비스·상태 머신 코드(`robot_service.py`, `state_machine.py`) | A 소유. 수정하지 않는다. `robot_service`의 인라인 판정을 공용 함수로 바꾸는 것은 A에게 제안만(§10.1 A1) |
| `app/models/*`, `alembic/*` | 스키마 변경 없음(기존 컬럼만 사용). C-04(A) 소유 |
| `app/main.py`, `app/core/config.py` | 변경 없음(`calls.router`는 이미 등록됨) |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| 메타데이터 누락 판정 | `app.services.call_metadata.is_metadata_incomplete(agent_name, call_datetime)` (`agent_name is None or call_datetime is None`, 로봇 등록 인라인 판정과 같은 규칙) | 로봇 등록(`robot_service._create_record`)이 인라인 식 대신 사용 가능(A 선택) |
| 행 잠금 조회 | `CallRepository.lock_call(call_id) -> CallRecord \| None` (삭제 제외, 관계 미로딩, `FOR UPDATE` — 상태 머신·로봇 서비스와 같은 SQL) | W-03 검토 완료(잠금 후 같은 트랜잭션에서 `CallStateMachine.transition`) |
| 수정 이력 추가 | `CallRepository.add_edit_history(call_id, field, before, after, *, editor)` | W-03 분석 필드 수정 |
| 이력 값 문자열화 / 변경 적용 | `app.services.call_service.{history_value, apply_changes, FieldChange}` | W-03 분석 필드 적용(같은 규칙) |
| 요청 모델 | `app.schemas.call.CallUpdateRequest` (평평한 모델, 선택 필드 추가로 확장) | W-03 |
| 수정자 타입 | `app.schemas.call.EditorName` | W-03, 이후 쓰기 API |

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 항목 | 실제 (`6a8f418`) | 이 계획의 반영 |
|---|---|---|
| **상태 머신** (`services/state_machine.py`, A) | `CallStateMachine(db, stale_threshold_min=...).transition(call_id, to_status, actor=..., reason=...)`. 내부에서 `select(CallRecord).where(id, deleted_at IS NULL).with_for_update()`로 잠그고 `flush`까지만, **커밋은 호출자**. 없거나 삭제된 건 404, 허용 안 되는 전이 `InvalidTransition`(409). 편의 함수 `transition(db, ...)`은 `get_settings()`의 정체 기준 사용 | W-12·W-04는 전이가 없어 호출하지 않음. 잠금 SQL·"flush는 하위, 커밋은 서비스" 구조를 같게 맞춤(§3.3 "잠금 쿼리 위치"). W-03이 `update_call`의 표시된 자리에서 `transition`을 부르면 같은 트랜잭션 재잠금이라 막히지 않음(통합 테스트 #16a로 확인) |
| **로봇 서비스** (`services/robot_service.py`, A) | `RobotService(db, storage, stale_threshold_min=...)`가 세션을 받아 메서드마다 `commit()`. 잠금은 private `_lock_call`(위와 같은 SQL, 없으면 404). 등록 시 `metadata_incomplete = agent_name is None or call_datetime is None`(인라인). 폼(`schemas/robot.py`)이 공백만 있는 값을 `None`으로 바꿈 | `CallService(repository, session)` + 쓰기 메서드 커밋은 같은 패턴. 판정 함수는 **같은 식**(`None`만 검사)으로 정의 |
| **분석 적재(R-07)** | `put_analysis`는 `analysis`(유형·요약·조치·후속 여부·엔티티 등)만 쓰고 `call_record`의 담당자·고객사·통화 일시는 **쓰지 않음**. 재분석 시 `action_status`도 덮어쓰지 않음 | 리서치 §0 #5 "재처리 후 웹 보정 값이 사라짐" 우려는 **해소**(현재 코드 기준). 이후 A가 메타데이터 반영을 추가하면 다시 검토(§10.1 A2) |
| 테스트 픽스처 | 루트 `tests/conftest.py`(A): `postgres_url`, `engine`, `db`(롤백 세션), `client`, `audio_root`, `robot_app`, `robot_client`. 기존 `tests/integration/conftest.py`(B): `database_url`, `engine`, `db_session`, `api` | 새 통합 테스트는 **B 픽스처(`db_session`·`api`·`engine`)만** 사용. `tests/integration/` 안에서 `engine`은 가까운 conftest(B)가 우선이라 `db_session`과 같은 DB를 가리킴. 새 픽스처 `committed_call`·헬퍼 `_history`는 기존 이름과 겹치지 않음(확인함) |
| `main.py`·`deps.py` | `app.state.settings`·`app.state.audio_storage`, `deps.get_settings_from_app`·`get_audio_storage`·`get_robot_service` 추가. `get_call_service`는 그대로 `CallService(CallRepository(session))` | `get_call_service` 1줄만 수정. W-03 때 상태 머신용 정체 기준이 필요하면 `get_settings_from_app`을 받아 넘김(이번에는 불필요) |
| `openapi.json` | 로봇 API 경로·스키마 포함 | 재생성 시 로봇 항목은 그대로, PATCH·DELETE·`CallUpdateRequest`만 추가 |
| 삭제 제외 | `filter_conditions()` 첫 조건 `deleted_at IS NULL`, `get_call`도 같은 조건. 통계(`stats_repository.py`)도 `filter_conditions` 사용 | 목록·상세·통계는 추가 작업 없이 삭제 건 제외. 통합 테스트로 목록·상세·`/api/stats/breakdown` 제외 확인 |
| 상세 조회 | `get_call`은 `joinedload(transcript)`·`joinedload(analysis)` → LEFT OUTER JOIN | 잠금은 이 쿼리를 쓰지 않고 `lock_call`(JOIN 없음)으로 따로 |
| 서비스·세션 | `CallService(CallRepository(session))`, `get_db`는 커밋하지 않음(주석 "커밋은 서비스가 한다") | `CallService(repository, session)`로 받고 쓰기 메서드가 `commit()` |
| 세션 설정 | `sessionmaker(..., expire_on_commit=False)` | 커밋 후 `get_call(call_id)` 재조회로 응답 생성. 응답에 `updated_at`이 없어 서버 `onupdate` 값을 다시 읽을 필요 없음 |
| `edit_history` | `field VARCHAR(50)`, `before_val`·`after_val TEXT`, `editor VARCHAR(50) NULL`, `edited_at DEFAULT now()` | 스키마 변경 없음 |
| `KstDatetime` | `AfterValidator(_assume_kst)` + `PlainSerializer(when_used="json")` | `model_dump()`(python 모드)는 aware `datetime` 그대로 → 서비스에서 그대로 대입 |
| 기간 상수 | `DATE_MIN`·`DATE_MAX`(2000-01-01~2100-12-31) in `schemas/call.py` | `call_datetime` 범위 검사에 재사용 |
| 접근 로그 | `RequestIdMiddleware`는 `method`·`path`·`status`·`call_id`만 남김(쿼리 문자열 없음) | DELETE `?editor=`가 로그에 남지 않음 |
| 단위 라우터 테스트 | `FakeCallService`를 `dependency_overrides[get_call_service]`로 주입 | 같은 방식에 `update_call`·`delete_call` 추가 |
| 통합 픽스처 | `db_session`(바깥 트랜잭션 + `create_savepoint`, 끝에 롤백), `api`, session 범위 `engine` | 서비스 `commit()`은 SAVEPOINT 해제. 두 트랜잭션 경합(잠금) 테스트만 `engine`으로 별도 세션을 열고 커밋한 행을 직접 지움 |
| Docker | 데몬 실행 중(29.9.3), testcontainers 동작 확인 | 통합 테스트를 **정식 검증 범위**에 포함(§9). 잠금(`FOR UPDATE`)·삭제 이력·부분 인덱스는 통합 테스트로 검증 |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| U1 | 삭제 허용 상태 | **모든 상태**에서 허용(처리 중 포함). 상태·`status_changed_at`·하위 데이터는 그대로 |
| U2 | 이미 삭제된 건 | `DELETE`·`PATCH` 모두 **404** `NOT_FOUND`(없음과 구별하지 않음). DELETE 성공 **204** 본문 없음 |
| U3 | W-03 미구현 기간의 W-03 필드 | `CallUpdateRequest`에 `extra="forbid"` → 422 `extra_forbidden`(`loc: ["body", "<키>"]`). 평평한 모델에 선택 필드를 추가해 확장 |
| U4 | 서비스 순서 | 잠금 → 메타데이터 적용 → `metadata_incomplete` 재계산 → (W-03 자리) → 이력 → 커밋 → 상세 반환 |
| U5 | `metadata_incomplete` | **양방향 재계산**. 요청에 메타데이터 키가 하나라도 있으면(값이 그대로여도) "`agent_name` 또는 `call_datetime`이 NULL" 기준으로 다시 계산. 판정 함수는 `app/services/call_metadata.py`로 분리하고 식은 로봇 등록의 인라인 판정(`agent_name is None or call_datetime is None`)과 **똑같이** 둔다(빈 문자열은 웹 422·로봇 폼 `None` 변환으로 저장 전에 걸러지므로 공백 검사를 따로 하지 않음) |
| U6 | 삭제 이력 | `edit_history`에 `field="deleted_at"`, `before_val=NULL`, `after_val`=삭제 시각 문자열, `editor`=선택 입력(없으면 NULL) |

### 3.2 리서치 권장안 채택
| # (리서치 §7) | 항목 | 결정 |
|---|---|---|
| 5 | 빈 문자열·공백 | 앞뒤 공백 제거 후 빈 값이면 **422** `string_too_short`. 비우기는 `null`만 |
| 6 | `call_datetime` 범위 | KST 날짜 기준 `DATE_MIN`~`DATE_MAX`(2000-01-01~2100-12-31) 재사용, 밖이면 422 `datetime_range` |
| 7 | 이력 단위 | **실제로 바뀐 필드만, 필드별 1행**. 같은 값 재전송은 행 없음. `metadata_incomplete` 변화는 파생 값이라 기록하지 않음 |
| 8 | 이력 값 형식 | 문자열. 시각은 응답과 같은 **초 단위 ISO 8601 `+09:00`**, `None`은 SQL NULL |
| 10 | 빈 PATCH(`{}`)·`editor`만 | 200 + 상세, 변경·이력 없음 |
| 11 | 동시성 | `FOR UPDATE` 비관적 잠금. 잠금 조회는 `call_record`만 읽는 `lock_call`(joinedload OUTER JOIN과 FOR UPDATE 충돌 회피) |
| 12 | 커밋 위치 | `CallService`가 `Session`을 받아 커밋(`get_call_service`에서 전달) |
| 13 | `editor` | 선택, 앞뒤 공백 제거, 1~50자(공백만이면 422 — #5와 같은 규칙) |
| 14 | 잠금 헬퍼 위치 | `CallRepository.lock_call`을 새로 둔다. 상태 머신·로봇 서비스의 잠금은 A 코드라 그대로 두고 **SQL만 같게** 맞춘다(§3.3 "잠금 쿼리 위치") |
| — | PATCH 응답 | 200 + 갱신된 `CallDetail`(커밋 후 `get_call` 재사용) |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| **잠금 쿼리 위치** | `CallRepository.lock_call(call_id)` 신규. SQL은 상태 머신·`RobotService._lock_call`과 **같은 문장**(`SELECT call_record.* ... WHERE id = :id AND deleted_at IS NULL FOR UPDATE`, JOIN 없음). 상태 머신을 잠금 용도로 부르거나 `RobotService._lock_call`(private)을 가져다 쓰지 않는다 | ① W-12·W-04는 상태 전이가 없어 `transition`을 부를 수 없고, 상태 머신에는 잠금만 하는 공개 함수가 없다. ② B 코드(`CallService`)는 쿼리를 리포지토리에 두고 가짜 리포지토리로 단위 테스트하는 구조라 같은 계층 규칙을 따른다. ③ A의 private 함수에 의존하면 A가 바꿀 때 웹이 깨진다. ④ SQL이 같으므로 W-03에서 `lock_call` 후 같은 세션으로 `CallStateMachine.transition`을 불러도 같은 트랜잭션의 재잠금이라 막히지 않는다(통합 #16a) |
| **트랜잭션 구조** | `CallService(repository, session)`: 잠금·변경·이력은 flush 전 단계, 마지막에 서비스가 `commit()` 1회. W-03의 `transition`(flush만)도 그 사이에 끼움 | 상태 머신 docstring "flush까지만, 커밋은 호출자", `RobotService`의 "세션을 받아 메서드 끝에서 커밋"과 같은 구조. 검토 완료 409가 나면 메타데이터 변경도 함께 롤백(한 요청 = 한 트랜잭션) |
| **DELETE의 `editor` 전달** | **쿼리 파라미터 `?editor=`**(선택, `EditorName`과 같은 규칙: 공백 제거, 1~50자) | DELETE 본문은 HTTP 의미가 정의되지 않아 일부 클라이언트·프록시가 버린다. 헤더는 latin-1만 허용돼 한글 이름을 그대로 못 넣는다. 접근 로그는 쿼리 문자열을 남기지 않는다(§2). 프론트는 지금 보내지 않으므로 이력의 `editor`는 NULL → 프론트가 수정자 입력을 붙이면 `?editor=`로 전달(§10.3 F1) |
| 문자열 타입 | `Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=N)]` 별칭 3개(`AgentName` 50, `ClientCompany` 100, `EditorName` 50) | DB 길이와 같음, 길이는 공백 제거 후 문자 수. OpenAPI에 `maxLength`·`minLength` 노출 |
| `call_datetime` 범위 검사 | `field_validator("call_datetime")`(after)에서 `PydanticCustomError("datetime_range", ...)` | `loc`이 `["body","call_datetime"]`, `type`이 안정적인 값. 메시지에 입력값 없음(규약 §3.4). 명시적 `null`이면 검사 생략 |
| 날짜만 입력(`"2026-11-23"`) | 막지 않음(자정 KST로 해석) | `KstDatetime` 기존 동작 유지. 프론트는 항상 시각까지 보냄. 막을지는 §10.4 R1 |
| `metadata_changes()` | `model_dump(include=METADATA_FIELDS, exclude_unset=True)` | 보낸 키만, `null` 포함. `editor`는 메타데이터가 아니므로 제외 |
| 변경 판정 | `apply_changes`가 `getattr(target, f) == new`이면 건너뜀 | aware `datetime`끼리는 같은 순간이면 같음(`Z`로 보내도 변경 없음) |
| 이력 문자열화 | `history_value`: `datetime` → `astimezone(KST).replace(microsecond=0).isoformat()`, 그 외 `str()`, `None` → `None` | 응답 `KstDatetime` 직렬화와 같은 결과. `schemas/common.py`의 비공개 `_to_kst`는 건드리지 않음 |
| `is_metadata_incomplete` 위치 | `app/services/call_metadata.py`(신규, 함수 하나) | 모델·`robot_service.py`(A 소유)를 수정하지 않고, A가 원하면 인라인 식을 이 함수로 바꿀 수 있음. 고객사는 판정에 넣지 않음 |
| 이력 추가 API | `add_edit_history(call_id, field, before, after, *, editor)` 1행 단위 | 리포지토리가 서비스 타입(`FieldChange`)을 몰라도 됨(계층 역전 방지) |
| `deleted_at` 값 | `datetime.now(UTC)`(규약 §5.1) | 이력 `after_val`은 같은 값을 `history_value`로 |
| 삭제 대상 | `call_record.deleted_at`만. 전사·분석·로그·이력·음성 사본은 그대로 | 물리 삭제는 O-05(A) |
| 404 후 커밋 | 잠금 조회가 `None`이면 `AppError(NOT_FOUND)`를 던지고 커밋하지 않음 | 세션은 요청 끝에 닫히며 롤백 |
| 빈 PATCH 커밋 | 변경이 없어도 `commit()` 호출 | 잠금 해제. 쓸 내용이 없어 비용 없음 |
| 응답 생성 | 커밋 후 `self.get_call(call_id)` | 기존 직렬화 경로(유형 코드 변환, `KstDatetime`) 재사용. 같은 세션의 identity map 객체에 transcript·analysis가 채워짐(통합 테스트로 확인: PATCH 응답 == GET 응답) |
| 라우트 | `update_call`(PATCH), `delete_call`(DELETE, `status_code=204`), 둘 다 `bind_call_id` + `responses=error_responses(ErrorCode.NOT_FOUND)` | operationId = 함수 이름, 앱 전체 고유. W-03 때 PATCH에 `INVALID_STATE_TRANSITION` 추가 |
| `call_id` 경로 검증 | 기존 `get_call`처럼 `Annotated[int, Path(ge=1, le=BIGINT_MAX)]`를 그대로 반복 | 기존 라우트를 고치지 않기 위해 별칭을 새로 만들지 않음 |
| 서비스 단위 테스트 | 가짜 리포지토리 + 가짜 세션(`commit` 횟수) + DB에 넣지 않은 `CallRecord` 객체 | DB 없이 순서·이력·재계산·404 시 미커밋 확인. `mypy`를 위해 `cast` |
| 잠금 SQL 단위 테스트 | `scalars()`만 가진 캡처 세션으로 `lock_call`의 문장을 받아 PostgreSQL 방언으로 컴파일 | JOIN 없음·`FOR UPDATE`·삭제 제외를 DB 없이 고정 |
| 잠금 통합 테스트 | `engine`으로 세션 두 개, 두 번째에 `SET LOCAL lock_timeout = '200ms'` → `OperationalError("lock timeout")` | 실제 행 잠금 확인. 커밋한 데이터는 픽스처가 `edit_history`→`call_record` 순으로 지움 |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준) | 내용 | 커밋(§12) |
|---|---|---|---|
| 수정 | `app/schemas/call.py` | `EditorName`(1) / `AgentName`·`ClientCompany`·`METADATA_FIELDS`·`CallUpdateRequest`(2), import, 모듈 docstring | 1, 2 |
| 신규 | `app/services/call_metadata.py` | `is_metadata_incomplete` | 2 |
| 수정 | `app/repositories/call_repository.py` | `lock_call`, `add_edit_history`, `EditHistory` import, docstring | 1 |
| 수정 | `app/services/call_service.py` | `CallService(repository, session)`, `history_value`, `delete_call`, `_lock`(1) / `FieldChange`, `apply_changes`, `update_call`(2) | 1, 2 |
| 수정 | `app/api/deps.py` | `get_call_service` 1줄 | 1 |
| 수정 | `app/api/web/calls.py` | `delete_call`(1) / `update_call`(2), import, docstring | 1, 2 |
| 수정 | `docs/api/openapi.json` | 재생성(커밋마다) | 1, 2 |
| 수정 | `docs/api/convention.md` | §5.1·§5.2·§2.2 아래 규칙 보완(§8) | 3 |
| 수정 | `tests/unit/test_call_query.py` | `lock_call` SQL 1건 | 1 |
| 수정 | `tests/unit/test_calls_api.py` | `FakeCallService.delete_call`·`update_call`, 라우터·OpenAPI 테스트 | 1, 2 |
| 신규 | `tests/unit/test_call_service.py` | 순수 함수·서비스 쓰기 유스케이스 | 1, 2 |
| 신규 | `tests/unit/test_call_update_request.py` | 요청 모델·판정 함수 | 2 |
| 신규 | `tests/integration/test_call_write.py` | 잠금·이력·DELETE·PATCH 종단 간 | 1, 2 |

- **변경하지 않는 파일**: `app/main.py`, `app/core/config.py`, `app/core/*`, `app/services/state_machine.py`·`robot_service.py`, `app/schemas/robot.py`, `app/schemas/common.py`, `app/models/*`, `alembic/*`, `tests/integration/conftest.py`·`factories.py`, `tests/conftest.py`·`tests/factories.py`, `pyproject.toml`.
- **새 의존성·마이그레이션 없음.**

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_openapi.py` | 변경 없음. `test_committed_openapi_is_up_to_date`가 재생성을 강제, `test_operation_ids_are_unique_in_real_app`이 `update_call`·`delete_call` 고유성 확인(단위 `conftest.py` 테스트 라우트 이름과 겹치지 않음) |
| `tests/unit/test_calls_api.py` 기존 케이스 | 그대로 통과(가짜 서비스에 메서드만 추가) |
| `tests/integration/*` 기존 케이스 | 영향 없음. `CallService` 생성자가 바뀌지만 직접 생성하는 테스트 없음(`get_call_service`만 사용). 로봇·상태 머신 테스트는 `CallService`·`CallRepository`를 쓰지 않음 |

### 4.2 병행 작업(웹 업로드 `POST /api/uploads`)과의 충돌
같은 시기에 다른 worktree가 `app/api/deps.py`, `app/main.py`, `app/core/config.py`, `docs/api/openapi.json`을 수정한다.

| 파일 | 이 계획의 변경 | 충돌 대응 |
|---|---|---|
| `app/api/deps.py` | `get_call_service` 본문 **1줄**만(`CallService(CallRepository(session), session)`). import·다른 함수 불변 | 업로드 쪽이 의존성 함수를 추가해도 줄이 겹치지 않으면 자동 병합. 겹치면 두 변경을 모두 살림 |
| `app/main.py`, `app/core/config.py` | **변경 없음** | — |
| `docs/api/openapi.json` | 생성 파일 | 손으로 병합하지 않는다. 먼저 병합된 쪽 위에서 rebase/merge 후 `uv run python -m scripts.export_openapi`로 **다시 생성**해 커밋(파일 전체가 정렬된 JSON이라 재생성 결과가 정답) |
| `docs/api/convention.md` | §5.1·§5.2 줄 추가 | 업로드가 §2.2·§3을 고쳐도 다른 줄. 겹치면 둘 다 유지 |

---

## 5. 모듈별 코드

> 아래 코드는 `6a8f418` 기준 스크래치 복사본에서 `ruff check`·`ruff format --check`·`mypy .`(strict)와 단위·통합 테스트를 통과한 그대로다. 수정 파일은 `6a8f418` 대비 diff, 신규 파일은 전문이다.

### 5.1 `app/schemas/call.py` (수정)
- 커밋 1에서는 `EditorName`만 추가하고(import는 `StringConstraints`만), 커밋 2에서 나머지를 추가한다. 아래는 최종 diff.
```diff
--- a/app/schemas/call.py
+++ b/app/schemas/call.py
@@ -1,15 +1,16 @@
-"""상담 목록·상세 API 스키마 (W-01, W-02)."""
+"""상담 목록·상세·수정·삭제 API 스키마."""
 
 from dataclasses import dataclass
-from datetime import date
+from datetime import date, datetime
 from enum import StrEnum
-from typing import Annotated, Literal
+from typing import Annotated, Any, Literal
 
 from fastapi import Query
-from pydantic import BaseModel, BeforeValidator, ConfigDict
+from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, field_validator
+from pydantic_core import PydanticCustomError
 
 from app.core.errors import AppError, ErrorCode
-from app.schemas.common import KstDatetime
+from app.schemas.common import KST, KstDatetime
 
 # ---------------------------------------------------------------- enum (convention.md §5.3)
 # 값은 모델의 CHECK 상수(app/models/*.py)와 같아야 한다 (tests/unit/test_call_enums.py).
@@ -132,6 +133,46 @@
         return stripped or None
 
 
+# 문자열 값은 앞뒤 공백을 지운 뒤 검사한다. 비우기는 null 한 가지로만 표현한다(빈 값 422).
+AgentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
+ClientCompany = Annotated[
+    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
+]
+# 수정자 이름. 로그인이 없어 자기 신고 값이다. PATCH 본문·DELETE 쿼리에서 선택 입력.
+EditorName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
+
+METADATA_FIELDS = ("agent_name", "client_company", "call_datetime")
+
+
+class CallUpdateRequest(BaseModel):
+    """`PATCH /api/calls/{id}`. 보낸 키만 변경하고 `null`은 값 비우기다.
+
+    선언하지 않은 키는 422(`extra_forbidden`). 유형·요약·조치·검토 완료 필드는
+    분석 수정 기능에서 선택 필드로 추가한다(호환 변경).
+    """
+
+    model_config = ConfigDict(extra="forbid")
+
+    agent_name: AgentName | None = None
+    client_company: ClientCompany | None = None
+    call_datetime: KstDatetime | None = None
+    editor: EditorName | None = None
+
+    @field_validator("call_datetime")
+    @classmethod
+    def _call_datetime_in_range(cls, value: datetime | None) -> datetime | None:
+        # 범위는 목록 기간 필터와 같다(KST 날짜 기준). 메시지에 입력값을 넣지 않는다.
+        if value is not None and not DATE_MIN <= value.astimezone(KST).date() <= DATE_MAX:
+            raise PydanticCustomError(
+                "datetime_range", "통화 일시는 2000-01-01부터 2100-12-31 사이여야 합니다"
+            )
+        return value
+
+    def metadata_changes(self) -> dict[str, Any]:
+        """요청에 들어 있는 메타데이터 키와 값(`null` 포함). 보낸 키가 없으면 빈 dict."""
+        return self.model_dump(include=set(METADATA_FIELDS), exclude_unset=True)
+
+
 # ---------------------------------------------------------------- 응답
 
 
```

### 5.2 `app/services/call_metadata.py` (신규)
```python
"""상담 메타데이터 규칙. 로봇 등록과 웹 보정이 같은 판정을 쓴다."""

from datetime import datetime


def is_metadata_incomplete(agent_name: str | None, call_datetime: datetime | None) -> bool:
    """담당자 또는 통화 일시가 없으면 True. 고객사는 판정에 넣지 않는다.

    입력 단계에서 빈 문자열을 막거나(웹 422) `None`으로 바꾸므로(로봇 등록) `None`만 본다.
    로봇 등록(`robot_service._create_record`)의 인라인 판정과 같은 규칙이다.
    """
    return agent_name is None or call_datetime is None
```

### 5.3 `app/repositories/call_repository.py` (수정)
```diff
--- a/app/repositories/call_repository.py
+++ b/app/repositories/call_repository.py
@@ -1,4 +1,4 @@
-"""상담 조회 쿼리. 소프트 삭제된 건은 항상 제외한다 (architecture.md §3.1)."""
+"""상담 조회·수정 쿼리. 소프트 삭제된 건은 항상 제외한다 (architecture.md §3.1)."""
 
 from collections.abc import Sequence
 from datetime import date, datetime, timedelta
@@ -7,7 +7,7 @@
 from sqlalchemy import ColumnElement, Row, Select, UnaryExpression, func, or_, select
 from sqlalchemy.orm import Session, joinedload
 
-from app.models import Analysis, CallRecord, ProcessingLog, Transcript
+from app.models import Analysis, CallRecord, EditHistory, ProcessingLog, Transcript
 from app.schemas.call import CATEGORY_DB_VALUES, CallListQuery, CallSort
 from app.schemas.common import KST
 
@@ -98,6 +98,35 @@
         )
         return self._session.scalars(stmt).one_or_none()
 
+    def lock_call(self, call_id: int) -> CallRecord | None:
+        """삭제되지 않은 건을 행 잠금(`FOR UPDATE`)으로 읽는다. 트랜잭션 끝까지 잠금이 유지된다.
+
+        상태 머신·로봇 서비스의 잠금 조회와 같은 SQL이다. 관계를 함께 읽지 않는다
+        (PostgreSQL은 OUTER JOIN의 NULL 가능 쪽에 FOR UPDATE 불가).
+        """
+        stmt = (
+            select(CallRecord)
+            .where(CallRecord.id == call_id, CallRecord.deleted_at.is_(None))
+            .with_for_update()
+        )
+        return self._session.scalars(stmt).one_or_none()
+
+    def add_edit_history(
+        self,
+        call_id: int,
+        field: str,
+        before: str | None,
+        after: str | None,
+        *,
+        editor: str | None,
+    ) -> None:
+        """수정 이력 1행. `edited_at`은 DB 기본값(now())."""
+        self._session.add(
+            EditHistory(
+                call_id=call_id, field=field, before_val=before, after_val=after, editor=editor
+            )
+        )
+
     def list_logs(self, call_id: int) -> Sequence[ProcessingLog]:
         # CallRecord.logs 관계에는 순서가 없어 별도 쿼리로 처리 순서를 보장한다.
         stmt = (
```

### 5.4 `app/services/call_service.py` (전문, 기존 `list_calls`·`get_call`은 그대로)
- 커밋 1: `CallService.__init__`(세션), `history_value`, `delete_call`, `_lock`. 커밋 2: `FieldChange`, `apply_changes`, `update_call`, `call_metadata`·`CallUpdateRequest` import.
```python
"""웹 상담 유스케이스: 목록·상세 조회, 메타데이터 보정, 삭제."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallBase, CallDetail, CallListItem, CallListQuery, CallUpdateRequest
from app.schemas.common import KST, Page, PageParams
from app.services.call_metadata import is_metadata_incomplete


def _base_fields(call: CallRecord) -> dict[str, Any]:
    return {name: getattr(call, name) for name in CallBase.model_fields}


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: str | None
    after: str | None


def history_value(value: object) -> str | None:
    """수정 이력 저장 문자열. 시각은 응답과 같은 초 단위 ISO 8601 `+09:00`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(KST).replace(microsecond=0).isoformat()
    return str(value)


def apply_changes(target: object, changes: dict[str, Any]) -> list[FieldChange]:
    """값이 다른 필드만 대입하고 바뀐 필드 목록을 돌려준다. 같은 순간의 시각은 같은 값이다."""
    applied: list[FieldChange] = []
    for field, new in changes.items():
        old = getattr(target, field)
        if old == new:
            continue
        setattr(target, field, new)
        applied.append(FieldChange(field, history_value(old), history_value(new)))
    return applied


class CallService:
    def __init__(self, repository: CallRepository, session: Session) -> None:
        self._repository = repository
        self._session = session  # 유스케이스 단위 트랜잭션: 쓰기 메서드가 커밋한다.

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

    def update_call(self, call_id: int, request: CallUpdateRequest) -> CallDetail:
        """보낸 키만 바꾸고 바뀐 필드마다 이력 1행. 상태는 바꾸지 않는다."""
        call = self._lock(call_id)
        metadata = request.metadata_changes()
        changes = apply_changes(call, metadata)
        if metadata:
            call.metadata_incomplete = is_metadata_incomplete(call.agent_name, call.call_datetime)
        # 분석 필드 적용·검토 완료 전이(CallStateMachine.transition, flush만)는 이 자리에
        # 추가한다. 같은 트랜잭션이라 이미 잡은 행 잠금을 다시 잡아도 막히지 않는다.
        for change in changes:
            self._repository.add_edit_history(
                call_id, change.field, change.before, change.after, editor=request.editor
            )
        self._session.commit()
        return self.get_call(call_id)

    def delete_call(self, call_id: int, *, editor: str | None = None) -> None:
        """소프트 삭제. 상태·하위 데이터는 그대로 두고 삭제 이력을 남긴다."""
        call = self._lock(call_id)
        call.deleted_at = datetime.now(UTC)
        self._repository.add_edit_history(
            call_id, "deleted_at", None, history_value(call.deleted_at), editor=editor
        )
        self._session.commit()

    def _lock(self, call_id: int) -> CallRecord:
        call = self._repository.lock_call(call_id)
        if call is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return call
```

### 5.5 `app/api/deps.py` (수정, 1줄)
```diff
--- a/app/api/deps.py
+++ b/app/api/deps.py
@@ -33,7 +33,7 @@
 
 
 def get_call_service(session: DbSession) -> CallService:
-    return CallService(CallRepository(session))
+    return CallService(CallRepository(session), session)
 
 
 def get_stats_service(session: DbSession) -> StatsService:
```

### 5.6 `app/api/web/calls.py` (전문, 기존 `list_calls`·`get_call`은 그대로)
```python
"""웹 상담 API: 목록·상세 조회, 메타데이터 보정(`PATCH`), 삭제(`DELETE`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import get_call_service
from app.core.errors import ErrorCode
from app.core.logging import bind_call_id
from app.schemas.call import CallDetail, CallListItem, CallListQuery, CallUpdateRequest, EditorName
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


@router.patch("/{call_id}", responses=error_responses(ErrorCode.NOT_FOUND))
def update_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    body: CallUpdateRequest,
    request: Request,
    service: CallServiceDep,
) -> CallDetail:
    bind_call_id(request, call_id)
    return service.update_call(call_id, body)


@router.delete("/{call_id}", status_code=204, responses=error_responses(ErrorCode.NOT_FOUND))
def delete_call(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: CallServiceDep,
    editor: Annotated[EditorName | None, Query()] = None,
) -> None:
    bind_call_id(request, call_id)
    service.delete_call(call_id, editor=editor)
```

### 5.7 `docs/api/openapi.json` (재생성)
```bash
cd backend && uv run python -m scripts.export_openapi
```
- 기존 로봇 API 항목은 그대로 두고 추가만 생긴다: 경로 `/api/calls/{call_id}`의 `patch`(`update_call`, 요청 `CallUpdateRequest`, `additionalProperties: false`, 응답 200 `CallDetail`·404·422·500), `delete`(`delete_call`, 쿼리 `editor`, 응답 204·404·422·500), 스키마 `CallUpdateRequest`. 기존 항목은 바뀌지 않음.
- Windows에서 `core.autocrlf=true`라도 테스트는 JSON을 파싱해 비교하므로 줄바꿈 차이는 무관하다.

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 단위 테스트를 먼저(DB 없음) 작성해 규칙을 고정하고, DB 동작(행 잠금, 이력 기본값, 부분 인덱스, 실제 저장 값, 삭제 후 조회 제외)은 **통합 테스트로 검증**한다. Docker가 켜져 있으므로 통합 테스트도 매 단계 실행한다.
- 같은 트랜잭션의 `now()`는 같으므로 이력 순서는 `EditHistory.id`로 확인한다.
- 커밋 1(삭제)에 들어갈 테스트와 커밋 2(보정)에 들어갈 테스트를 표의 "커밋" 열로 구분한다.

### 6.2 케이스 목록 (구현 순서)
| # | 파일 | 테스트 | 확인 내용 | 커밋 |
|---|---|---|---|---|
| 1 | `unit/test_call_query.py` | `test_lock_call_selects_only_call_record_for_update` | SQL이 `FOR UPDATE`로 끝남, `JOIN` 없음, `deleted_at IS NULL`, id 바인드 | 1 |
| 2 | `unit/test_call_service.py` | `test_history_value_formats_datetime_as_kst_seconds` | 마이크로초 버림 `+09:00`, `None`, 문자열 | 1 |
| 3 | 〃 | `test_delete_sets_aware_deleted_at_and_records_history` | aware `deleted_at`, 상태 불변, 이력 `("deleted_at", None, 시각, editor)`, 커밋 1회 | 1 |
| 4 | 〃 | `test_delete_without_editor_records_null_editor` | editor NULL | 1 |
| 5 | 〃 | `test_delete_missing_or_deleted_call_is_not_found_without_commit` | 404, 커밋 0회 | 1 |
| 6 | `unit/test_calls_api.py` | `test_delete_returns_204_without_body` | 204, 본문 0바이트, `X-Request-Id` | 1 |
| 7 | 〃 | `test_delete_passes_stripped_editor` | `?editor= 이수정 ` → `"이수정"` | 1 |
| 8 | 〃 | `test_delete_invalid_editor_returns_422` ×3 | `""`·공백·51자 → `["query","editor"]` | 1 |
| 9 | 〃 | `test_delete_not_found` | 404 `NOT_FOUND` | 1 |
| 10 | 〃 | `test_write_invalid_id_returns_422` ×6 | PATCH·DELETE × `abc`·`0`·BIGINT 초과 (커밋 1에서는 `method`를 `delete`만으로 두고 커밋 2에서 `patch` 추가) | 1, 2 |
| 11 | 〃 | `test_openapi_delete_call` | operationId, 응답 키 `{204,404,422,500}`, 204 본문 없음, `editor` 쿼리 선택·`maxLength` 50 | 1 |
| 12 | `integration/test_call_write.py` | `test_lock_call_excludes_deleted` | 삭제·없는 건 `None` | 1 |
| 13 | 〃 | `test_lock_call_works_on_call_with_children` | 전사가 있는 건도 잠금 조회 성공(JOIN 없음) | 1 |
| 14 | 〃 | `test_add_edit_history_uses_db_default_time` | 행 값, `edited_at` aware | 1 |
| 15 | 〃 | `test_lock_call_blocks_other_transaction` | 다른 트랜잭션은 `lock timeout` | 1 |
| 16 | 〃 | `test_lock_after_other_transaction_deleted_returns_none` | 먼저 삭제·커밋되면 다음 잠금 조회 `None`(→ 404) | 1 |
| 16a | 〃 | `test_state_machine_can_transition_after_lock_call` | `lock_call` 후 같은 세션에서 `CallStateMachine.transition(NEEDS_REVIEW→STORED)`이 막히지 않음(W-03 구조 확인) | 1 |
| 17 | 〃 | `test_delete_soft_deletes_in_any_status` ×4 | `REGISTERED`·`QUEUED`·`STORED`·`FAILED` 모두 204, 상태·`status_changed_at` 불변, 이력 1행 | 1 |
| 18 | 〃 | `test_deleted_call_disappears_from_reads_and_second_delete_is_404` | GET 404, 목록 `total` 0, `breakdown` 빈 목록, 재삭제 404, 이력 1행만 | 1 |
| 19 | 〃 | `test_delete_without_editor_records_null` | 이력 editor NULL | 1 |
| 20 | 〃 | `test_delete_unknown_id_is_404` | | 1 |
| 21 | 〃 | `test_same_file_hash_can_be_added_after_delete` | 부분 유니크 인덱스(등록 기능 참고) | 1 |
| 22 | `unit/test_call_update_request.py` | `test_missing_key_null_and_value_are_distinguished` | `model_fields_set`, `metadata_changes()` | 2 |
| 23 | 〃 | `test_empty_body_has_no_changes`, `test_editor_is_not_a_metadata_change` | | 2 |
| 24 | 〃 | `test_strings_are_stripped` | | 2 |
| 25 | 〃 | `test_blank_string_is_rejected` ×6 | 3필드 × `""`·공백 → `string_too_short` | 2 |
| 26 | 〃 | `test_max_length_counts_characters_after_strip` ×3 | 50/100/50 통과(앞뒤 공백 포함), +1 `string_too_long` | 2 |
| 27 | 〃 | `test_unknown_keys_are_rejected` ×4 | `category`·`question_summary`·`review_completed`·`status` → `extra_forbidden` | 2 |
| 28 | 〃 | `test_call_datetime_without_offset_is_kst`, `..._with_offset_is_kept`, `..._null_clears`, `..._empty_string_is_rejected` | | 2 |
| 29 | 〃 | `test_call_datetime_range_bounds_are_kst_dates` ×3, `test_call_datetime_out_of_range_is_rejected` ×3 | 경계는 KST 날짜(`1999-12-31T15:00Z` 허용, `2100-12-31T15:00Z` 거부), `datetime_range`, 메시지에 입력값 없음 | 2 |
| 30 | 〃 | `test_is_metadata_incomplete` ×4 | (값,값) false / 담당자 None·시각 None·둘 다 None → true (로봇 등록 식과 같음) | 2 |
| 31 | `unit/test_call_service.py` | `test_apply_changes_sets_only_different_values` | 같은 값·같은 순간 다른 표기 → 변경 없음 | 2 |
| 32 | 〃 | `test_apply_changes_clears_and_formats_datetime` | `None` 비우기, 시각 문자열 | 2 |
| 33 | 〃 | `test_update_applies_metadata_records_history_and_commits` | 잠금 호출, 값·플래그, 이력 2행·editor, 커밋 1회, 상세 반환 | 2 |
| 34 | 〃 | `test_update_clearing_agent_marks_incomplete_again` | 양방향(false→true) | 2 |
| 35 | 〃 | `test_update_client_only_recomputes_stale_flag_without_history_row` | 고객사만 보내도 재계산, 플래그 변화는 이력 없음 | 2 |
| 36 | 〃 | `test_update_same_values_records_nothing` | 이력 없음, 커밋 1회 | 2 |
| 37 | 〃 | `test_update_empty_body_keeps_flag_and_returns_detail` | 메타데이터 키 없으면 재계산 안 함 | 2 |
| 38 | 〃 | `test_update_does_not_touch_status` | | 2 |
| 39 | 〃 | `test_update_missing_call_is_not_found_without_commit` | | 2 |
| 40 | `unit/test_calls_api.py` | `test_patch_passes_only_sent_keys` | 200, 서비스에 보낸 키만 | 2 |
| 41 | 〃 | `test_patch_empty_object_is_ok`, `test_patch_not_found`, `test_patch_without_body_returns_422` | | 2 |
| 42 | 〃 | `test_patch_invalid_body_returns_422` ×6 | `category`·`review_completed`·공백·101자·범위 밖·`editor` 51자, 서비스 미호출 | 2 |
| 43 | 〃 | `test_openapi_update_call` | operationId, 응답 키, 요청 필수, `additionalProperties: false`, 필드 4개, `maxLength`, nullable | 2 |
| 44 | `integration/test_call_write.py` | `test_patch_fills_metadata_and_records_history` | 저장 값(aware), 응답 == GET 상세, 상태 불변, 이력 3행 순서·editor | 2 |
| 45 | 〃 | `test_patch_null_clears_and_marks_incomplete` | 다른 필드 불변, 이력 before 문자열 | 2 |
| 46 | 〃 | `test_patch_same_values_writes_no_history` | 다른 표기 같은 시각 포함 | 2 |
| 47 | 〃 | `test_patch_empty_body_returns_detail_unchanged` | | 2 |
| 48 | 〃 | `test_patch_deleted_call_is_404` | 이력 없음 | 2 |
| 49 | 〃 | `test_patch_with_analysis_field_is_422_and_changes_nothing` | 혼합 요청 422 → DB 불변 | 2 |

### 6.3 케이스 수
| 구분 | 신규 |
|---|---|
| 단위 | 69 (`test_call_update_request.py` 31, `test_call_service.py` 13, `test_calls_api.py` +24, `test_call_query.py` +1) |
| 통합 | 20 (`test_call_write.py`) |
| 합계 | 89 (사전 검증: `6a8f418` 기준 통과 563 → 652, 신규 89 모두 통과) |

### 6.4 테스트 코드

`tests/unit/test_call_query.py` (추가분)
```diff
--- a/tests/unit/test_call_query.py
+++ b/tests/unit/test_call_query.py
@@ -1,10 +1,18 @@
 from datetime import date, datetime
+from types import SimpleNamespace
+from typing import Any, cast
 
 import pytest
 from sqlalchemy import and_, create_engine
+from sqlalchemy.orm import Session
 
 from app.core.errors import AppError, ErrorCode
-from app.repositories.call_repository import filter_conditions, kst_day_start, order_by_clause
+from app.repositories.call_repository import (
+    CallRepository,
+    filter_conditions,
+    kst_day_start,
+    order_by_clause,
+)
 from app.schemas.call import CallListQuery, CallStatus, Category
 from app.schemas.common import KST
 
@@ -116,3 +124,30 @@
 
 def test_same_day_range_is_allowed() -> None:
     CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 1))
+
+
+class _CaptureSession:
+    """실행하지 않고 넘겨받은 문장만 모은다."""
+
+    def __init__(self) -> None:
+        self.statements: list[Any] = []
+
+    def scalars(self, stmt: Any) -> Any:
+        self.statements.append(stmt)
+        return SimpleNamespace(one_or_none=lambda: None)
+
+
+def test_lock_call_selects_only_call_record_for_update() -> None:
+    # PostgreSQL은 OUTER JOIN의 NULL 가능 쪽에 FOR UPDATE를 허용하지 않는다 → JOIN이 없어야 한다.
+    capture = _CaptureSession()
+
+    assert CallRepository(cast(Session, capture)).lock_call(7) is None
+
+    (stmt,) = capture.statements
+    compiled = stmt.compile(dialect=_PG)
+    sql = str(compiled)
+    assert sql.endswith("FOR UPDATE")
+    assert "JOIN" not in sql
+    assert "FROM call_record \nWHERE call_record.id = " in sql
+    assert "call_record.deleted_at IS NULL" in sql
+    assert 7 in compiled.params.values()
```

`tests/unit/test_calls_api.py` (추가분)
```diff
--- a/tests/unit/test_calls_api.py
+++ b/tests/unit/test_calls_api.py
@@ -10,7 +10,15 @@
 
 from app.api.deps import get_call_service
 from app.core.errors import AppError, ErrorCode
-from app.schemas.call import CallDetail, CallListItem, CallListQuery, CallStatus, Category, LogStep
+from app.schemas.call import (
+    CallDetail,
+    CallListItem,
+    CallListQuery,
+    CallStatus,
+    CallUpdateRequest,
+    Category,
+    LogStep,
+)
 from app.schemas.common import Page, PageParams
 
 _DETAIL = CallDetail.model_validate(
@@ -37,6 +45,8 @@
 class FakeCallService:
     def __init__(self) -> None:
         self.calls: list[tuple[CallListQuery, PageParams]] = []
+        self.updates: list[tuple[int, CallUpdateRequest]] = []
+        self.deletes: list[tuple[int, str | None]] = []
 
     def list_calls(self, query: CallListQuery, page: PageParams) -> Page[CallListItem]:
         self.calls.append((query, page))
@@ -46,6 +56,15 @@
         if call_id == 1:
             return _DETAIL
         raise AppError(ErrorCode.NOT_FOUND)
+
+    def update_call(self, call_id: int, request: CallUpdateRequest) -> CallDetail:
+        self.updates.append((call_id, request))
+        return self.get_call(call_id)
+
+    def delete_call(self, call_id: int, *, editor: str | None = None) -> None:
+        self.deletes.append((call_id, editor))
+        if call_id != 1:
+            raise AppError(ErrorCode.NOT_FOUND)
 
 
 @pytest.fixture
@@ -187,6 +206,102 @@
     assert ["path", "call_id"] in _error_locs(response.json())
 
 
+# ---------------------------------------------------------------- PATCH·DELETE
+
+
+def test_patch_passes_only_sent_keys(api: TestClient, fake: FakeCallService) -> None:
+    response = api.patch("/api/calls/1", json={"agent_name": " 김상담 ", "client_company": None})
+
+    assert response.status_code == 200
+    assert response.json()["call_datetime"] == "2026-11-23T14:30:00+09:00"
+    ((call_id, body),) = fake.updates
+    assert call_id == 1
+    assert body.model_fields_set == {"agent_name", "client_company"}
+    assert body.metadata_changes() == {"agent_name": "김상담", "client_company": None}
+
+
+def test_patch_empty_object_is_ok(api: TestClient, fake: FakeCallService) -> None:
+    assert api.patch("/api/calls/1", json={}).status_code == 200
+    assert fake.updates[0][1].model_fields_set == set()
+
+
+def test_patch_not_found(api: TestClient) -> None:
+    response = api.patch("/api/calls/2", json={"agent_name": "김상담"})
+
+    assert response.status_code == 404
+    assert response.json()["code"] == "NOT_FOUND"
+
+
+@pytest.mark.parametrize(
+    ("body", "loc"),
+    [
+        ({"category": "COMPLAINT"}, ["body", "category"]),
+        ({"review_completed": True}, ["body", "review_completed"]),
+        ({"agent_name": "  "}, ["body", "agent_name"]),
+        ({"client_company": "가" * 101}, ["body", "client_company"]),
+        ({"call_datetime": "2101-01-01T00:00:00+09:00"}, ["body", "call_datetime"]),
+        ({"editor": "가" * 51}, ["body", "editor"]),
+    ],
+)
+def test_patch_invalid_body_returns_422(
+    api: TestClient, fake: FakeCallService, body: dict[str, Any], loc: list[str | int]
+) -> None:
+    response = api.patch("/api/calls/1", json=body)
+
+    assert response.status_code == 422
+    assert response.json()["code"] == "VALIDATION_ERROR"
+    assert loc in _error_locs(response.json())
+    assert fake.updates == []
+
+
+def test_patch_without_body_returns_422(api: TestClient, fake: FakeCallService) -> None:
+    response = api.patch("/api/calls/1")
+
+    assert response.status_code == 422
+    assert fake.updates == []
+
+
+def test_delete_returns_204_without_body(api: TestClient, fake: FakeCallService) -> None:
+    response = api.delete("/api/calls/1")
+
+    assert response.status_code == 204
+    assert response.content == b""
+    assert response.headers["X-Request-Id"]
+    assert fake.deletes == [(1, None)]
+
+
+def test_delete_passes_stripped_editor(api: TestClient, fake: FakeCallService) -> None:
+    assert api.delete("/api/calls/1", params={"editor": " 이수정 "}).status_code == 204
+    assert fake.deletes == [(1, "이수정")]
+
+
+@pytest.mark.parametrize("editor", ["", "  ", "가" * 51])
+def test_delete_invalid_editor_returns_422(
+    api: TestClient, fake: FakeCallService, editor: str
+) -> None:
+    response = api.delete("/api/calls/1", params={"editor": editor})
+
+    assert response.status_code == 422
+    assert ["query", "editor"] in _error_locs(response.json())
+    assert fake.deletes == []
+
+
+def test_delete_not_found(api: TestClient) -> None:
+    response = api.delete("/api/calls/2")
+
+    assert response.status_code == 404
+    assert response.json()["code"] == "NOT_FOUND"
+
+
+@pytest.mark.parametrize("method", ["patch", "delete"])
+@pytest.mark.parametrize("call_id", ["abc", "0", "9223372036854775808"])
+def test_write_invalid_id_returns_422(api: TestClient, method: str, call_id: str) -> None:
+    response = api.request(method.upper(), f"/api/calls/{call_id}", json={})
+
+    assert response.status_code == 422
+    assert ["path", "call_id"] in _error_locs(response.json())
+
+
 # ---------------------------------------------------------------- OpenAPI
 
 
@@ -231,3 +346,34 @@
     assert set(schemas["LogStep"]["enum"]) == set(LogStep)
     assert "is_stale" not in schemas["CallListItem"]["properties"]
     assert "processing_log" in schemas["CallDetail"]["required"]
+
+
+def test_openapi_update_call(spec: dict[str, Any]) -> None:
+    operation = spec["paths"]["/api/calls/{call_id}"]["patch"]
+    request = spec["components"]["schemas"]["CallUpdateRequest"]
+    props = request["properties"]
+
+    assert operation["operationId"] == "update_call"
+    assert set(operation["responses"]) == {"200", "404", "422", "500"}
+    assert operation["requestBody"]["required"] is True
+    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
+    assert ref.endswith("/CallDetail")
+    assert set(props) == {"agent_name", "client_company", "call_datetime", "editor"}
+    assert request["additionalProperties"] is False
+    assert "required" not in request
+    assert props["agent_name"]["anyOf"][0]["maxLength"] == 50
+    assert props["client_company"]["anyOf"][0]["maxLength"] == 100
+    assert props["call_datetime"]["anyOf"][0]["format"] == "date-time"
+    assert {"type": "null"} in props["agent_name"]["anyOf"]
+
+
+def test_openapi_delete_call(spec: dict[str, Any]) -> None:
+    operation = spec["paths"]["/api/calls/{call_id}"]["delete"]
+    params = {p["name"]: p for p in operation["parameters"]}
+
+    assert operation["operationId"] == "delete_call"
+    assert set(operation["responses"]) == {"204", "404", "422", "500"}
+    assert "content" not in operation["responses"]["204"]
+    assert params["editor"]["in"] == "query"
+    assert params["editor"]["required"] is False
+    assert params["editor"]["schema"]["anyOf"][0]["maxLength"] == 50
```

`tests/unit/test_call_update_request.py` (신규)
```python
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.call import CallUpdateRequest
from app.schemas.common import KST
from app.services.call_metadata import is_metadata_incomplete


def _error(body: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ValidationError) as exc_info:
        CallUpdateRequest.model_validate(body)
    (error,) = exc_info.value.errors()
    return dict(error)


def test_missing_key_null_and_value_are_distinguished() -> None:
    request = CallUpdateRequest.model_validate({"agent_name": None, "client_company": "가나상사"})

    assert request.model_fields_set == {"agent_name", "client_company"}
    assert request.metadata_changes() == {"agent_name": None, "client_company": "가나상사"}


def test_empty_body_has_no_changes() -> None:
    assert CallUpdateRequest.model_validate({}).metadata_changes() == {}


def test_editor_is_not_a_metadata_change() -> None:
    request = CallUpdateRequest.model_validate({"editor": " 김수정 "})

    assert request.editor == "김수정"
    assert request.metadata_changes() == {}


def test_strings_are_stripped() -> None:
    request = CallUpdateRequest.model_validate(
        {"agent_name": "  김상담 ", "client_company": " 가 "}
    )

    assert request.metadata_changes() == {"agent_name": "김상담", "client_company": "가"}


@pytest.mark.parametrize("field", ["agent_name", "client_company", "editor"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_string_is_rejected(field: str, value: str) -> None:
    error = _error({field: value})

    assert error["loc"] == (field,)
    assert error["type"] == "string_too_short"


@pytest.mark.parametrize(
    ("field", "limit"), [("agent_name", 50), ("client_company", 100), ("editor", 50)]
)
def test_max_length_counts_characters_after_strip(field: str, limit: int) -> None:
    CallUpdateRequest.model_validate({field: " " + "가" * limit + " "})

    assert _error({field: "가" * (limit + 1)})["type"] == "string_too_long"


@pytest.mark.parametrize("key", ["category", "question_summary", "review_completed", "status"])
def test_unknown_keys_are_rejected(key: str) -> None:
    error = _error({"agent_name": "김상담", key: "x"})

    assert error["loc"] == (key,)
    assert error["type"] == "extra_forbidden"


def test_call_datetime_without_offset_is_kst() -> None:
    request = CallUpdateRequest.model_validate({"call_datetime": "2026-11-23T14:30"})

    assert request.metadata_changes() == {
        "call_datetime": datetime(2026, 11, 23, 14, 30, tzinfo=KST)
    }


def test_call_datetime_with_offset_is_kept() -> None:
    request = CallUpdateRequest.model_validate({"call_datetime": "2026-11-23T05:30:00Z"})

    assert request.call_datetime == datetime(2026, 11, 23, 5, 30, tzinfo=UTC)


def test_call_datetime_null_clears() -> None:
    assert CallUpdateRequest.model_validate({"call_datetime": None}).metadata_changes() == {
        "call_datetime": None
    }


@pytest.mark.parametrize(
    "value", ["2000-01-01T00:00:00+09:00", "2100-12-31T23:59:59+09:00", "1999-12-31T15:00:00Z"]
)
def test_call_datetime_range_bounds_are_kst_dates(value: str) -> None:
    CallUpdateRequest.model_validate({"call_datetime": value})


@pytest.mark.parametrize(
    "value", ["1999-12-31T23:59:59+09:00", "2101-01-01T00:00:00+09:00", "2100-12-31T15:00:00Z"]
)
def test_call_datetime_out_of_range_is_rejected(value: str) -> None:
    error = _error({"call_datetime": value})

    assert error["loc"] == ("call_datetime",)
    assert error["type"] == "datetime_range"
    assert value not in error["msg"]


def test_call_datetime_empty_string_is_rejected() -> None:
    assert _error({"call_datetime": ""})["loc"] == ("call_datetime",)


# ---------------------------------------------------------------- metadata_incomplete 판정


@pytest.mark.parametrize(
    ("agent_name", "call_datetime", "expected"),
    [
        ("김상담", datetime(2026, 11, 23, tzinfo=KST), False),
        (None, datetime(2026, 11, 23, tzinfo=KST), True),
        ("김상담", None, True),
        (None, None, True),
    ],
)
def test_is_metadata_incomplete(
    agent_name: str | None, call_datetime: datetime | None, expected: bool
) -> None:
    assert is_metadata_incomplete(agent_name, call_datetime) is expected
```

`tests/unit/test_call_service.py` (신규)
```python
"""CallService 쓰기 유스케이스 단위 테스트: 가짜 리포지토리·세션으로 DB 없이 확인한다."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models import CallRecord
from app.repositories.call_repository import CallRepository
from app.schemas.call import CallUpdateRequest
from app.schemas.common import KST
from app.services.call_service import CallService, FieldChange, apply_changes, history_value

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)  # 14:30:05 KST


def _record(**overrides: Any) -> CallRecord:
    values: dict[str, Any] = {
        "id": 1,
        "source_type": "DRIVE",
        "original_name": "a.wav",
        "duration_sec": None,
        "agent_name": "김상담",
        "client_company": None,
        "call_datetime": T0,
        "metadata_incomplete": False,
        "status": "STORED",
        "status_changed_at": T0,
        "retry_count": 0,
        "created_at": T0,
        "deleted_at": None,
        **overrides,
    }
    return CallRecord(**values)  # DB에 넣지 않는 일시적(transient) 객체


class FakeCallRepository:
    def __init__(self, call: CallRecord | None) -> None:
        self.call = call
        self.history: list[tuple[int, str, str | None, str | None, str | None]] = []
        self.locked: list[int] = []

    def lock_call(self, call_id: int) -> CallRecord | None:
        self.locked.append(call_id)
        return self.call

    def get_call(self, call_id: int) -> CallRecord | None:
        return self.call

    def list_logs(self, call_id: int) -> list[Any]:
        return []

    def add_edit_history(
        self, call_id: int, field: str, before: str | None, after: str | None, *, editor: str | None
    ) -> None:
        self.history.append((call_id, field, before, after, editor))


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _service(repo: FakeCallRepository, session: FakeSession) -> CallService:
    return CallService(cast(CallRepository, repo), cast(Session, session))


def _patch(**body: Any) -> CallUpdateRequest:
    return CallUpdateRequest.model_validate(body)


# ---------------------------------------------------------------- 순수 함수


def test_history_value_formats_datetime_as_kst_seconds() -> None:
    assert history_value(T0.replace(microsecond=999_999)) == "2026-11-23T14:30:05+09:00"
    assert history_value(None) is None
    assert history_value("김상담") == "김상담"


def test_apply_changes_sets_only_different_values() -> None:
    target = SimpleNamespace(agent_name="김상담", client_company=None, call_datetime=T0)

    changes = apply_changes(
        target,
        {
            "agent_name": "김상담",
            "client_company": "가나상사",
            "call_datetime": T0.astimezone(KST),  # 같은 순간, 다른 표기
        },
    )

    assert changes == [FieldChange("client_company", None, "가나상사")]
    assert target.client_company == "가나상사"
    assert target.call_datetime is T0


def test_apply_changes_clears_and_formats_datetime() -> None:
    target = SimpleNamespace(agent_name="김상담", call_datetime=T0)
    new_dt = datetime(2026, 11, 24, 9, 0, tzinfo=KST)

    changes = apply_changes(target, {"agent_name": None, "call_datetime": new_dt})

    assert changes == [
        FieldChange("agent_name", "김상담", None),
        FieldChange("call_datetime", "2026-11-23T14:30:05+09:00", "2026-11-24T09:00:00+09:00"),
    ]
    assert target.agent_name is None


# ---------------------------------------------------------------- update_call


def test_update_applies_metadata_records_history_and_commits() -> None:
    call = _record(agent_name=None, call_datetime=None, metadata_incomplete=True)
    repo, session = FakeCallRepository(call), FakeSession()

    detail = _service(repo, session).update_call(
        1, _patch(agent_name="김상담", call_datetime="2026-11-23T14:30", editor="이수정")
    )

    assert repo.locked == [1]
    assert call.agent_name == "김상담"
    assert call.metadata_incomplete is False
    assert repo.history == [
        (1, "agent_name", None, "김상담", "이수정"),
        (1, "call_datetime", None, "2026-11-23T14:30:00+09:00", "이수정"),
    ]
    assert session.commits == 1
    assert detail.agent_name == "김상담"
    assert detail.metadata_incomplete is False
    assert detail.status == "STORED"


def test_update_clearing_agent_marks_incomplete_again() -> None:
    call = _record()
    repo = FakeCallRepository(call)

    _service(repo, FakeSession()).update_call(1, _patch(agent_name=None))

    assert call.metadata_incomplete is True
    assert repo.history == [(1, "agent_name", "김상담", None, None)]


def test_update_client_only_recomputes_stale_flag_without_history_row() -> None:
    # 값은 채워져 있는데 표시가 true로 남아 있던 건도 메타데이터 키가 오면 바로잡는다.
    call = _record(metadata_incomplete=True)
    repo = FakeCallRepository(call)

    _service(repo, FakeSession()).update_call(1, _patch(client_company="가나상사"))

    assert call.metadata_incomplete is False
    assert [row[1] for row in repo.history] == ["client_company"]


def test_update_same_values_records_nothing() -> None:
    repo, session = FakeCallRepository(_record()), FakeSession()

    _service(repo, session).update_call(1, _patch(agent_name="김상담", call_datetime=T0))

    assert repo.history == []
    assert session.commits == 1


def test_update_empty_body_keeps_flag_and_returns_detail() -> None:
    call = _record(metadata_incomplete=True)  # 메타데이터 키가 없으면 재계산하지 않는다
    repo, session = FakeCallRepository(call), FakeSession()

    detail = _service(repo, session).update_call(1, _patch(editor="이수정"))

    assert call.metadata_incomplete is True
    assert repo.history == []
    assert detail.id == 1


def test_update_does_not_touch_status() -> None:
    call = _record(status="QUEUED")

    _service(FakeCallRepository(call), FakeSession()).update_call(1, _patch(agent_name="박상담"))

    assert call.status == "QUEUED"
    assert call.status_changed_at == T0


def test_update_missing_call_is_not_found_without_commit() -> None:
    session = FakeSession()

    with pytest.raises(AppError) as exc_info:
        _service(FakeCallRepository(None), session).update_call(1, _patch(agent_name="김상담"))

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert session.commits == 0


# ---------------------------------------------------------------- delete_call


def test_delete_sets_aware_deleted_at_and_records_history() -> None:
    call = _record(status="QUEUED")
    repo, session = FakeCallRepository(call), FakeSession()
    before = datetime.now(UTC)

    _service(repo, session).delete_call(1, editor="이수정")

    assert call.deleted_at is not None
    assert call.deleted_at.tzinfo is not None
    assert before - timedelta(seconds=1) <= call.deleted_at <= datetime.now(UTC)
    assert call.status == "QUEUED"
    assert repo.history == [(1, "deleted_at", None, history_value(call.deleted_at), "이수정")]
    assert session.commits == 1


def test_delete_without_editor_records_null_editor() -> None:
    repo = FakeCallRepository(_record())

    _service(repo, FakeSession()).delete_call(1)

    assert repo.history[0][4] is None


def test_delete_missing_or_deleted_call_is_not_found_without_commit() -> None:
    session = FakeSession()

    with pytest.raises(AppError) as exc_info:
        _service(FakeCallRepository(None), session).delete_call(1)

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert session.commits == 0
```

`tests/integration/test_call_write.py` (신규)
```python
"""메타데이터 보정·삭제: 실제 PostgreSQL에서 저장 값·이력·잠금을 확인한다."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import CallRecord, EditHistory
from app.repositories.call_repository import CallRepository
from app.schemas.common import KST
from app.services.state_machine import CallStateMachine
from tests.integration.factories import make_analysis, make_call, make_transcript

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 23, 5, 30, 5, tzinfo=UTC)  # 14:30:05 KST

HistoryRow = tuple[str, str | None, str | None, str | None]


def _history(session: Session, call_id: int) -> list[HistoryRow]:
    rows = session.scalars(
        select(EditHistory).where(EditHistory.call_id == call_id).order_by(EditHistory.id)
    )
    return [(r.field, r.before_val, r.after_val, r.editor) for r in rows]


# ---------------------------------------------------------------- 리포지토리


def test_lock_call_excludes_deleted(db_session: Session) -> None:
    alive = make_call(db_session)
    deleted = make_call(db_session, deleted_at=T0)
    repo = CallRepository(db_session)

    assert repo.lock_call(alive.id) is alive
    assert repo.lock_call(deleted.id) is None
    assert repo.lock_call(alive.id + 10_000) is None


def test_lock_call_works_on_call_with_children(db_session: Session) -> None:
    # 관계를 JOIN하지 않으므로 하위 행 유무와 관계없이 FOR UPDATE가 실행된다.
    call = make_call(db_session)
    make_transcript(db_session, call)

    assert CallRepository(db_session).lock_call(call.id) is call


def test_add_edit_history_uses_db_default_time(db_session: Session) -> None:
    call = make_call(db_session)

    CallRepository(db_session).add_edit_history(call.id, "agent_name", None, "김상담", editor=None)
    db_session.flush()

    (row,) = db_session.scalars(select(EditHistory).where(EditHistory.call_id == call.id))
    assert (row.field, row.before_val, row.after_val, row.editor) == (
        "agent_name",
        None,
        "김상담",
        None,
    )
    assert row.edited_at.tzinfo is not None


def test_state_machine_can_transition_after_lock_call(db_session: Session) -> None:
    # 검토 완료(W-03)가 lock_call 후 같은 트랜잭션에서 상태 머신을 부르는 구조를 미리 확인한다.
    call = make_call(db_session, status="NEEDS_REVIEW")
    assert CallRepository(db_session).lock_call(call.id) is call

    CallStateMachine(db_session, stale_threshold_min=30).transition(call.id, "STORED", actor="web")

    assert call.status == "STORED"


@pytest.fixture
def committed_call(engine: Engine) -> Iterator[int]:
    """다른 연결에서 보이도록 커밋한 건. 끝나면 지운다(롤백 픽스처 `db_session`을 쓰지 않음)."""
    with Session(engine) as session:
        call_id = make_call(session).id
        session.commit()
    yield call_id
    with Session(engine) as session:
        session.execute(delete(EditHistory).where(EditHistory.call_id == call_id))
        session.execute(delete(CallRecord).where(CallRecord.id == call_id))
        session.commit()


def test_lock_call_blocks_other_transaction(engine: Engine, committed_call: int) -> None:
    with Session(engine) as first, Session(engine) as second:
        assert CallRepository(first).lock_call(committed_call) is not None
        second.connection().exec_driver_sql("SET LOCAL lock_timeout = '200ms'")

        with pytest.raises(OperationalError, match="lock timeout"):
            CallRepository(second).lock_call(committed_call)

        first.rollback()
        second.rollback()


def test_lock_after_other_transaction_deleted_returns_none(
    engine: Engine, committed_call: int
) -> None:
    # 먼저 잠근 쪽이 삭제하고 커밋하면, 기다리던 쪽은 deleted_at 조건에 걸려 None → 404.
    with Session(engine) as first:
        call = CallRepository(first).lock_call(committed_call)
        assert call is not None
        call.deleted_at = T0
        first.commit()

    with Session(engine) as second:
        assert CallRepository(second).lock_call(committed_call) is None


# ---------------------------------------------------------------- PATCH


def test_patch_fills_metadata_and_records_history(api: TestClient, db_session: Session) -> None:
    call = make_call(
        db_session, metadata_incomplete=True, status="NEEDS_REVIEW", status_changed_at=T0
    )
    make_analysis(db_session, call, category="불만")

    response = api.patch(
        f"/api/calls/{call.id}",
        json={
            "agent_name": " 김상담 ",
            "client_company": "가나상사",
            "call_datetime": "2026-11-23T14:30",
            "editor": "이수정",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "김상담"
    assert body["call_datetime"] == "2026-11-23T14:30:00+09:00"
    assert body["metadata_incomplete"] is False
    assert body["status"] == "NEEDS_REVIEW"
    assert body["analysis"]["category"] == "COMPLAINT"
    assert body == api.get(f"/api/calls/{call.id}").json()
    db_session.expire_all()
    stored = db_session.get(CallRecord, call.id)
    assert stored is not None
    assert stored.call_datetime == datetime(2026, 11, 23, 14, 30, tzinfo=KST)
    assert stored.status_changed_at == T0
    assert _history(db_session, call.id) == [
        ("agent_name", None, "김상담", "이수정"),
        ("client_company", None, "가나상사", "이수정"),
        ("call_datetime", None, "2026-11-23T14:30:00+09:00", "이수정"),
    ]


def test_patch_null_clears_and_marks_incomplete(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session, agent_name="김상담", call_datetime=T0, client_company="가나상사")

    body = api.patch(f"/api/calls/{call.id}", json={"call_datetime": None}).json()

    assert body["call_datetime"] is None
    assert body["metadata_incomplete"] is True
    assert body["agent_name"] == "김상담"
    assert body["client_company"] == "가나상사"
    assert _history(db_session, call.id) == [
        ("call_datetime", "2026-11-23T14:30:05+09:00", None, None)
    ]


def test_patch_same_values_writes_no_history(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session, agent_name="김상담", call_datetime=T0)

    response = api.patch(
        f"/api/calls/{call.id}",
        json={"agent_name": "김상담", "call_datetime": "2026-11-23T14:30:05+09:00"},
    )

    assert response.status_code == 200
    assert _history(db_session, call.id) == []


def test_patch_empty_body_returns_detail_unchanged(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session, metadata_incomplete=True)

    response = api.patch(f"/api/calls/{call.id}", json={})

    assert response.status_code == 200
    assert response.json()["metadata_incomplete"] is True
    assert _history(db_session, call.id) == []


def test_patch_deleted_call_is_404(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session, deleted_at=T0)

    response = api.patch(f"/api/calls/{call.id}", json={"agent_name": "김상담"})

    assert response.status_code == 404
    assert _history(db_session, call.id) == []


def test_patch_with_analysis_field_is_422_and_changes_nothing(
    api: TestClient, db_session: Session
) -> None:
    call = make_call(db_session)

    response = api.patch(
        f"/api/calls/{call.id}", json={"agent_name": "김상담", "category": "COMPLAINT"}
    )

    assert response.status_code == 422
    db_session.expire_all()
    stored = db_session.get(CallRecord, call.id)
    assert stored is not None
    assert stored.agent_name is None


# ---------------------------------------------------------------- DELETE


@pytest.mark.parametrize("status", ["REGISTERED", "QUEUED", "STORED", "FAILED"])
def test_delete_soft_deletes_in_any_status(
    api: TestClient, db_session: Session, status: str
) -> None:
    call = make_call(db_session, status=status, status_changed_at=T0)

    response = api.delete(f"/api/calls/{call.id}", params={"editor": "이수정"})

    assert response.status_code == 204
    assert response.content == b""
    db_session.expire_all()
    stored = db_session.get(CallRecord, call.id)
    assert stored is not None
    assert stored.deleted_at is not None
    assert (stored.status, stored.status_changed_at) == (status, T0)
    ((field, before, after, editor),) = _history(db_session, call.id)
    assert (field, before, editor) == ("deleted_at", None, "이수정")
    assert after == stored.deleted_at.astimezone(KST).replace(microsecond=0).isoformat()


def test_deleted_call_disappears_from_reads_and_second_delete_is_404(
    api: TestClient, db_session: Session
) -> None:
    call = make_call(db_session, agent_name="김상담", call_datetime=T0)
    make_analysis(db_session, call)

    assert api.delete(f"/api/calls/{call.id}").status_code == 204

    assert api.get(f"/api/calls/{call.id}").status_code == 404
    assert api.get("/api/calls").json()["total"] == 0
    assert api.get("/api/stats/breakdown", params={"by": "agent"}).json()["items"] == []
    second = api.delete(f"/api/calls/{call.id}")
    assert second.status_code == 404
    assert second.json()["code"] == "NOT_FOUND"
    assert len(_history(db_session, call.id)) == 1


def test_delete_without_editor_records_null(api: TestClient, db_session: Session) -> None:
    call = make_call(db_session)

    assert api.delete(f"/api/calls/{call.id}").status_code == 204

    assert _history(db_session, call.id)[0][3] is None


def test_delete_unknown_id_is_404(api: TestClient) -> None:
    assert api.delete("/api/calls/999999999").status_code == 404


def test_same_file_hash_can_be_added_after_delete(db_session: Session) -> None:
    # ux_call_hash는 deleted_at IS NULL 부분 인덱스 → 삭제 후 같은 해시 행 추가 가능(등록 참고).
    call = make_call(db_session, file_hash="f" * 64)
    call.deleted_at = T0
    db_session.flush()

    assert make_call(db_session, file_hash="f" * 64).id != call.id
```

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 1 | #1 작성 → `CallRepository.lock_call` | `uv run pytest tests/unit/test_call_query.py` |
| 2 | #2~5 작성 → `EditorName`(schemas), `add_edit_history`, `history_value`, `CallService.__init__(repository, session)`, `_lock`, `delete_call` | `uv run pytest tests/unit/test_call_service.py` |
| 3 | `deps.py` 1줄 | `uv run pytest tests/unit tests/integration/test_calls_api.py` (기존 통과 유지) |
| 4 | #6~11 작성 → `delete_call` 라우트 | `uv run pytest tests/unit/test_calls_api.py` (이 시점에 `test_committed_openapi_is_up_to_date`만 실패) |
| 5 | `openapi.json` 재생성 | `uv run pytest -m "not integration"` 전부 통과 |
| 6 | #12~21(16a 포함) 작성(구현은 이미 있음, 실패하면 구현 수정) | `uv run pytest -m integration` |
| 7 | 검증(§9) → **커밋 1** | |
| 8 | #22~30 작성 → `AgentName`·`ClientCompany`·`METADATA_FIELDS`·`CallUpdateRequest`, `call_metadata.py` | `uv run pytest tests/unit/test_call_update_request.py` |
| 9 | #31~39 작성 → `FieldChange`, `apply_changes`, `update_call` | `uv run pytest tests/unit/test_call_service.py` |
| 10 | #40~43 작성(#10에 `patch` 추가) → `update_call` 라우트 | `uv run pytest tests/unit/test_calls_api.py` |
| 11 | `openapi.json` 재생성 | `uv run pytest -m "not integration"` |
| 12 | #44~49 작성 | `uv run pytest -m integration` |
| 13 | 검증(§9) → **커밋 2** | |
| 14 | `convention.md` 보완(§8) → **커밋 3** | 리뷰 |

---

## 8. 문서 갱신 (`docs/api/convention.md`, 공용 문서 — 중립 표현)

§2.2 표 아래(로봇 API 401·403 문장 다음)에 추가:
```markdown
`PATCH /api/calls/{id}`·`DELETE /api/calls/{id}`는 처리 상태와 관계없이 허용한다(삭제는 상태를 바꾸지 않는 소프트 삭제). 두 요청은 대상 행을 잠그고(`SELECT ... FOR UPDATE`) 한 트랜잭션으로 처리한다.
```

§5.1 끝에 추가:
```markdown
- 요청의 통화 일시(`call_datetime`)는 KST 날짜 기준 `2000-01-01`~`2100-12-31`만 허용한다(기간 필터와 같은 범위, 벗어나면 422 `type: "datetime_range"`).
```

§5.2 끝에 추가:
```markdown
- 문자열 입력은 앞뒤 공백을 지운 뒤 검사한다. 지운 결과가 빈 값이면 422(`string_too_short`)다. 값 비우기는 `null` 한 가지로만 표현한다.
- PATCH 요청 모델은 선언하지 않은 키를 받지 않는다(422 `extra_forbidden`, `loc: ["body", "<키>"]`). 필드는 선택 필드로 추가한다(호환 변경).
- 수정·삭제는 `edit_history`에 남긴다: 실제로 바뀐 필드마다 1행(같은 값 재전송은 기록하지 않음), 값은 문자열(시각은 응답과 같은 초 단위 `+09:00`). 파생 값(`metadata_incomplete`)은 기록하지 않는다. 삭제는 `field: "deleted_at"` 1행이다. 수정자 이름은 선택 입력(공백 제거 후 1~50자)으로 PATCH는 본문 `editor`, DELETE는 쿼리 `?editor=`로 받는다. 로그인이 없으므로 자기 신고 값이다.
```

- `architecture.md`·`features.md`는 변경하지 않는다(내용과 충돌 없음). 위 문장은 특정 담당자 관점이 아닌 중립 표현으로 쓴다.

---

## 9. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (Docker 실행 중이면 통합 포함)
uv run pytest -m integration         # 통합만 — 이번 기능의 정식 검증 범위
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
- 통합 테스트는 testcontainers가 `postgres:16`을 띄운다(Docker 데몬 실행 중, CLI 경로 `"/c/Program Files/Docker/Docker/resources/bin"`). 또는 `TEST_DATABASE_URL`(테스트 전용 DB).
- **통합 테스트가 skip되면 검증 미완료로 본다**(출력의 `skipped`에 `tests/integration`이 없어야 함. 기존 skip 2건은 Drive 실연동 테스트).
- 기대: 변경 전 main 기준 통과 수 + 89, 실패 0. (스크래치 사전 검증은 루트 `uipath/samples/` 부재로 기존 48건 실패 → 실제 worktree에서는 해당 없음. 전체 실행은 컨테이너 2개(루트·B 통합 conftest 각각)로 약 5분)
- 통합 픽스처가 둘이라 PostgreSQL 컨테이너가 2개 뜬다(루트 `postgres_url`, B `database_url`). 정상 동작이다.

---

## 10. 확인 필요

### 10.1 A (C-04·R-02·R-04·R-07·R-09·R-11·O-05)
| # | 항목 | 내용 |
|---|---|---|
| A1 | **판정 함수 공유** | `robot_service._create_record`의 인라인 식(`agent_name is None or call_datetime is None`)과 `is_metadata_incomplete`는 같은 규칙. 한쪽이 바뀌면 어긋나므로 A가 인라인 식을 이 함수 호출로 바꿀지 결정(B는 A 코드 수정 안 함) |
| A2 | R-07 적재와 보정 값 (**해소**) | `6a8f418`의 `put_analysis`는 `analysis`만 쓰고 `call_record`의 담당자·고객사·통화 일시를 쓰지 않음 → 리서치 §0 #5 우려 해소. 이후 적재가 메타데이터를 반영하도록 바뀌면 웹 보정 값과의 우선순위를 다시 합의 |
| A3 | 로봇 API의 삭제 건 | R-05~R-08은 이미 `_lock_call`(삭제 제외)로 404(`6a8f418` 확인). R-09 재처리 대상 조회·R-11 정체 건수(미구현)에서도 삭제 건 제외 요청 |
| A4 | 삭제 후 같은 파일 재등록 | 부분 유니크 인덱스라 새 건이 생김(테스트 #21). 의도인지 |
| A5 | 잠금 SQL 일치 | `lock_call`·상태 머신·`RobotService._lock_call`이 같은 SQL을 각각 가짐. 잠금 조건(삭제 제외 등)을 바꿀 때 세 곳을 함께 고쳐야 함 — 공용화 여부는 W-03 때 A와 결정 |
| A6 | O-05 물리 삭제 순서 | FK에 `ON DELETE`가 없음 → `edit_history`·`processing_log`·`transcript`·`analysis` → `call_record` |

### 10.2 RPA (A 경유)
| # | 항목 | 내용 |
|---|---|---|
| P1 | 처리 중 삭제된 건 | Performer가 적재 API에서 404를 받으면 실패 보고 없이 Queue 건 종료 |
| P2 | `REGISTERED` 삭제 후 Dispatcher 재등록 | `processing/`에 남은 파일이 새 건으로 등록될 수 있음 |

### 10.3 프론트
| # | 항목 | 내용 |
|---|---|---|
| F1 | **삭제 수정자** | `DELETE /api/calls/{id}?editor=<이름>`(선택). 지금처럼 보내지 않으면 이력 editor NULL |
| F2 | **W-03 전 혼합 PATCH 422** | 분석 필드·`review_completed`를 함께 보내면 422 `extra_forbidden`. W-03 배포 전까지 메타데이터만 보내야 함 |
| F3 | 빈 값 | 공백·빈 문자열은 422, 비우기는 `null`(현재 프론트 동작과 같음). `editor`도 공백만이면 422(현재 프론트는 보내지 않음) |
| F4 | 통화 일시 | 범위 밖 422 `datetime_range`. 분 단위 입력이면 초가 `:00`이 됨 |
| F5 | `metadata_incomplete` | 담당자·통화 일시를 비우면 다시 true |
| F6 | DELETE 404 | 다른 사람이 먼저 지운 경우 404 → 목록으로 이동시킬지 |

### 10.4 규약·리뷰
| # | 항목 | 내용 |
|---|---|---|
| R1 | 날짜만 입력 | `"call_datetime": "2026-11-23"`이 자정 KST로 통과. 막으려면 `KstDatetime` 공용 동작을 바꿔야 해 범위 밖으로 둠 |
| R2 | 마이크로초 비교 | DB 값에 소수 초가 있고 같은 초로 다시 보내면 "변경"으로 기록되며 이력 before·after 문자열이 같아 보일 수 있음. 현재 데이터는 초 단위(파일명 추출)라 실영향 없음 |
| R3 | `extra="forbid"` 범위 | 오타 키도 422(의도). W-03 필드 선언 전까지 프론트 초안과 호환되지 않음 |

### 10.5 작업 환경
| # | 항목 | 내용 |
|---|---|---|
| E1 | **브랜치·기준** | worktree `rpa-followup`은 HEAD 분리(`d9429d5`). 구현 전 `origin/main`(`6a8f418`) 기준으로 맞추고, 규칙상 개인 브랜치에서 커밋(PR로 `main` 병합) |
| E2 | 리서치 문서 | `docs/researchs/call-delete-metadata.md`가 미추적. 커밋 3(docs)에 계획서와 함께 넣을지 결정 |

---

## 11. 구현 시 주의
1. 잠금은 `lock_call`로만 한다. `get_call`(joinedload)에 `with_for_update()`를 붙이지 않는다(PostgreSQL: OUTER JOIN의 NULL 가능 쪽에 FOR UPDATE 불가). 상태 머신·로봇 서비스의 잠금 SQL과 같게 유지한다.
2. 서비스 쓰기 메서드는 `self._session.commit()`으로 끝낸다. 리포지토리·라우터·`get_db`에서 커밋하지 않는다.
3. 404는 커밋 전에 던진다(잠금 조회 `None`).
4. 시각은 aware만: `datetime.now(UTC)`. 이력 문자열은 `history_value`로만 만든다.
5. `metadata_incomplete`는 메타데이터 키가 **하나라도 요청에 있을 때만** 재계산하고 이력에 남기지 않는다. `editor`만 있는 요청은 메타데이터 요청이 아니다.
6. 422 `msg`에 입력값을 넣지 않는다(`PydanticCustomError` 메시지는 상수).
7. 요청·응답 본문, 수정자 이름을 로그에 남기지 않는다.
8. 통합 테스트에서 커밋이 필요한 경우(잠금 경합)만 `engine`을 직접 쓰고 반드시 지운다. 그 밖에는 `db_session`/`api`(롤백) 픽스처를 쓴다.
9. 라우트를 바꾸면 `openapi.json`을 재생성해 **같은 커밋**에 넣는다. 병합 충돌 시 손으로 고치지 말고 재생성한다.
10. W-03은 `CallUpdateRequest`에 선택 필드를, `update_call`의 주석 자리에 "분석 적용 → 검토 완료 전이"를 넣고, PATCH `responses`에 `INVALID_STATE_TRANSITION`을 추가한다. 이때 `apply_changes`·`history_value`·`add_edit_history`를 재사용한다.

---

## 12. 커밋 분할안
작업단위 ID는 커밋 메시지에 넣지 않는다. 기능 단위로 나눈다.

| 순서 | 메시지(안) | 포함 |
|---|---|---|
| 1 | `feat: 상담 소프트 삭제 API(DELETE /api/calls/{id})와 삭제 이력 추가` | `EditorName`, `lock_call`, `add_edit_history`, `history_value`, `CallService` 세션 주입·`delete_call`, `deps.py` 1줄, `delete_call` 라우트, `openapi.json`, 테스트 #1~21(16a 포함) |
| 2 | `feat: 상담 메타데이터 보정 API(PATCH /api/calls/{id}) 추가` | `CallUpdateRequest` 등, `call_metadata.py`, `FieldChange`·`apply_changes`·`update_call`, `update_call` 라우트, `openapi.json`, 테스트 #10(patch)·#22~49 |
| 3 | `docs: API 규약에 수정·삭제 입력 규칙과 수정 이력 기준 추가` | `convention.md`(§8), (선택) 리서치·계획 문서 |
