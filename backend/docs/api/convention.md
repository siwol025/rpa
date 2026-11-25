# API 규약

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 적용 대상 | 웹 API(`/api/*`), 로봇 API(`/api/robot/*`) |
| 근거 | `architecture.md` §7, `research.md` §5, `docs/input_flow.md` §6·§9, `researchs/api-convention.md` |
| 계약 파일 | `backend/docs/api/openapi.json` (코드에서 생성, 커밋) |
| 공용 코드 | `app/schemas/common.py`, `app/core/errors.py` |

> 이 문서는 프론트엔드·RPA·백엔드가 공유하는 API 계약 규칙이다. 개별 엔드포인트의 요청·응답 필드는 `openapi.json`이 기준이다.

---

## 1. 공통

1. JSON 본문의 필드 이름, 쿼리 파라미터, 에러 `detail`의 키는 모두 **snake_case**다(`call_id`, `call_datetime`, `existing_id`). 별칭(camelCase)은 제공하지 않는다.
2. 문자 인코딩은 UTF-8, 본문은 `application/json`(업로드는 `multipart/form-data`, 다운로드는 파일 형식).
3. 모든 응답에 `X-Request-Id` 헤더가 있다. 요청에 `[A-Za-z0-9-]{1,64}` 형식으로 보내면 그 값을 그대로 쓴다. 로봇은 이 값과 `call_id`를 UiPath 로그에 남기고, 프론트는 에러 표시·문의 시 사용할 수 있다.
4. URL 버전(`/api/v1`)은 두지 않는다. 변경 구분:
   - 호환 변경: 응답 필드 추가, enum 값 추가, 선택 요청 필드 추가
   - 비호환 변경: 필드 삭제·이름 변경·타입 변경, enum 값 삭제·변경, 필수 요청 필드 추가
   - 비호환 변경은 사용하는 파트(프론트·RPA)와 사전 합의 후 배포한다. 특히 로봇 API는 Orchestrator 배포 주기가 달라 동시 배포를 가정하지 않는다.
   - 비호환 변경 시 앱 `version`(`app/main.py`)을 올린다.

## 2. 성공 응답

### 2.1 상태 코드
| 상황 | 상태 | 본문 |
|---|---|---|
| 생성 | **201** | 생성 결과 (예: 로봇 등록 `{call_id}`) |
| 비동기 접수(실제 처리는 나중) | **202** | 접수 결과 (예: 웹 업로드, 재처리 요청) |
| 본문 없는 삭제 | **204** | 없음 |
| 조회·수정·멱등 적재(PUT)·그 외 동작 | **200** | 리소스 또는 동작 결과 |

### 2.2 엔드포인트별 기준
| Method | Endpoint | 성공 | 주요 에러 |
|---|---|---|---|
| POST | `/api/uploads` | 202 | 400, 413, 415, 422, 503 |
| GET | `/api/calls` | 200 `Page[...]` | 422 |
| GET | `/api/calls/{id}` | 200 | 404 |
| PATCH | `/api/calls/{id}` | 200 (갱신된 상세) | 404, 409, 422 |
| DELETE | `/api/calls/{id}` | 204 | 404 (이미 삭제된 건 포함) |
| POST | `/api/calls/{id}/retry` | 202 `{call_id, status, retry_count}` | 404, 409 |
| GET | `/api/calls/{id}/audio` | 200 / 206(Range) / 302(GCS 서명 URL) | 404, 416 |
| GET | `/api/stats/*` | 200 (집계 객체) | 422 |
| GET | `/api/reports/excel` | 200 (xlsx) | 422 |
| POST | `/api/robot/calls` | 201 `{call_id}` | 409 `DUPLICATE_FILE`, 413, 415, 422 |
| PATCH | `/api/robot/calls/{id}/status` | 200 `{call_id, status}` | 404, 409, 422 |
| GET | `/api/robot/calls?status=RETRY_REQUESTED` | 200 `{items: [{call_id, retry_count}]}` | 422 |
| GET | `/api/robot/calls/{id}/audio` | 200 | 404 |
| PUT | `/api/robot/calls/{id}/transcript`, `.../analysis` | 200 `{call_id, status}` (같은 내용 재전송도 200) | 404, 409, 422 |
| POST | `/api/robot/calls/{id}/logs` | 201 | 404, 409, 422 |
| GET | `/health` | 200 (`OK`·`DEGRADED`) / 503 (`FAIL`), 본문은 둘 다 헬스 형식(§3.6) | 500 |

로봇 API는 모두 401(`UNAUTHORIZED`)·403(`FORBIDDEN_IP`)이 추가로 가능하다. 모든 API는 422·500이 가능하다.

메타데이터 보정(담당자·고객사·통화 일시, `PATCH /api/calls/{id}`)과 삭제(`DELETE /api/calls/{id}`)는 처리 상태와 관계없이 허용한다(삭제는 상태를 바꾸지 않는 소프트 삭제). 두 요청은 대상 행을 잠그고(`SELECT ... FOR UPDATE`) 한 트랜잭션으로 처리한다.

### 2.3 본문 규칙
1. 상태를 바꾸는 동작 API는 결과 상태를 돌려준다(`{call_id, status}`). 웹은 재조회 없이 화면을 갱신하고, 로봇은 결과를 로그에 남긴다.
2. 식별자 키: 리소스 자체의 식별자는 `id`(웹 목록·상세), 다른 리소스를 가리키거나 동작 결과로 돌려주는 식별자는 `call_id`.
3. 목록이 아닌 집계(통계)는 `Page`를 쓰지 않고 객체로 감싼다. 배열을 최상위로 돌려주지 않는다(이후 필드 추가가 호환 변경이 되도록).

## 3. 에러

### 3.1 형식
```json
{ "code": "NOT_FOUND", "message": "대상을 찾을 수 없습니다.", "detail": null }
```
- `code`: 에러 코드(영문 상수). 코드 ↔ HTTP 상태 표는 `architecture.md` §7.2.
- `message`: 사용자에게 그대로 보여 줄 수 있는 한국어 문장.
- `detail`: 클라이언트 처리에 필요한 추가 정보 객체. 없으면 `null`(키는 항상 있음).

### 3.2 `VALIDATION_ERROR` (422)
```json
{
  "code": "VALIDATION_ERROR",
  "message": "요청 형식이 올바르지 않습니다.",
  "detail": {
    "errors": [
      { "loc": ["query", "size"], "msg": "Input should be less than or equal to 100", "type": "less_than_equal" }
    ]
  }
}
```
- `loc` 첫 요소는 `path`/`query`/`header`/`body`, 리스트 위치는 정수.
- `msg`는 Pydantic 영어 문구 그대로다. 화면 문구는 `message`, 필드 표시는 `loc`, 세부 분기는 `type`(안정적인 기계용 키)으로 한다.
- 요청 입력값은 담지 않는다.

### 3.3 `DUPLICATE_FILE` (409, 로봇 등록)
```json
{ "code": "DUPLICATE_FILE", "message": "이미 등록된 파일입니다.", "detail": { "existing_id": 123, "status": "REGISTERED" } }
```
- 로봇(Dispatcher)은 기존 건 ID를 **`detail.existing_id`**, 기존 건 상태를 **`detail.status`**에서 읽어 `input_flow.md` §6.2 표대로 처리한다. 최상위에는 `existing_id`·`status`가 없다.

### 3.4 규칙
1. 클라이언트의 분기는 `code`로 한다. `message` 문자열을 비교하지 않는다.
2. 서비스·라우터는 `AppError(ErrorCode.X, message=None, detail=None)`로만 에러를 던진다. `HTTPException`을 직접 쓰지 않는다(`HTTPException` 상태 매핑이 없어 403·409·415는 `BAD_REQUEST`, 503은 `INTERNAL_ERROR`로 나간다).
3. **validator·`AppError`의 `message`와 `detail`에 요청 입력값을 넣지 않는다.** 커스텀 validator의 `ValueError` 문구는 422 `msg`로 응답에 그대로 나간다. `ValueError(f"잘못된 전화번호 {value}")` 금지 → `ValueError("전화번호 형식이 아닙니다")`.
4. `detail`에는 식별자·상태·위치 같은 처리용 값만 넣는다. 예외 원문, SQL, 스택, 내부 경로는 넣지 않는다.
5. 엔드포인트 고유 에러는 OpenAPI에 문서화한다: `responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION)`. 422·500은 앱 전체에 이미 붙어 있다. 파일을 받는 엔드포인트는 `PAYLOAD_TOO_LARGE`·`UNSUPPORTED_MEDIA`를 추가한다. 로봇 라우터는 `APIRouter(responses=error_responses(ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN_IP))`.

### 3.5 웹 업로드 (`POST /api/uploads`)
- 한 요청에 여러 파일을 보낼 수 있다(multipart 필드 `files`, 최대 10개). 모든 파일을 검증한 뒤 순서대로 올리므로, 4xx 응답이면 어떤 파일도 올라가지 않았다.
- 422 `VALIDATION_ERROR`의 서비스 검증 `type`: `filename_invalid`(`loc: ["body", "files", i]`, 사용할 수 없는 파일명), `too_many_files`(`loc: ["body", "files"]`).
- 415 `UNSUPPORTED_MEDIA`의 `detail`은 `{"index": i}`(요청에서 몇 번째 파일인지, 0부터). 확장자가 허용 목록(`ALLOWED_EXTENSIONS`)에 없거나, 내용이 확장자와 다른 형식이거나, 빈 파일이면 415다.
- 503 `INBOX_UNAVAILABLE`은 업로드 저장소가 꺼져 있거나(`INBOX_BACKEND=disabled`) 업로드 중 실패한 경우다. 업로드 중 실패면 앞 순서의 파일은 이미 올라갔을 수 있다(다시 올리면 등록 단계에서 중복으로 정리된다). `detail`은 `null`.
- 202 본문은 `{"items": [{"name": ...}]}`이고, `name`은 저장된 이름(경로 성분 제거, NFC 정규화, 확장자 소문자)이다.

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

### 3.7 음성 재생 (`GET /api/calls/{id}/audio`)
- 단일 바이트 범위(`bytes=a-b`, `bytes=a-`, `bytes=-n`)만 206으로 응답한다(`Content-Range`, `Accept-Ranges: bytes`). 문법 오류·모르는 단위·다중 범위이거나 `If-Range`가 함께 오면 Range를 무시하고 200 전체를 보낸다.
- 범위가 파일 밖이면 416 `RANGE_NOT_SATISFIABLE`(§3.1 형식, `detail: null`)과 `Content-Range: bytes */<크기>` 헤더. 헤더가 필요해 라우터가 `error_response(..., headers=...)`를 직접 반환한다(§3.4-2의 예외).
- 없는 건·삭제된 건·음성 사본 파일이 없는 건은 모두 404 `NOT_FOUND`다. 응답은 `Cache-Control: private, no-store`.

## 4. 목록

### 4.1 형식
```json
{ "items": [ ... ], "page": 1, "size": 20, "total": 154 }
```
- 코드: `Page[T]` 응답 모델, `PageParams` 쿼리 의존성(`app/schemas/common.py`).
- `page`는 1부터 최대 10000, `size`는 기본 20·최대 100. 범위를 벗어나면 422.
- 마지막 페이지를 넘는 `page`는 에러가 아니라 빈 `items`와 실제 `total`을 돌려준다.
- `total`은 같은 필터 조건의 전체 건수(별도 `COUNT` 쿼리).
- 소프트 삭제된 건은 모든 웹 조회에서 제외한다.
- 로봇 재처리 대상 조회는 페이지 없이 `{"items": [...]}`(서버 상한 100건)로 돌려준다.

### 4.2 정렬
- 파라미터 `sort`, 값은 필드 이름, 내림차순은 앞에 `-` (`sort=-created_at`). 한 번에 하나.
- 허용 필드는 엔드포인트마다 허용 목록(`Literal`)으로 정해 OpenAPI에 노출한다. 목록 밖의 값은 422. `GET /api/calls`: `call_datetime`, `created_at`, `status_changed_at`, 기본 `-created_at`.
- 항상 마지막에 같은 방향의 `id` 정렬을 붙여 순서를 결정적으로 만든다. NULL 가능 필드(`call_datetime`)는 방향과 관계없이 `NULLS LAST`.

### 4.3 필터
- 여러 값: 같은 이름을 반복한다 `?status=FAILED&status=NEEDS_REVIEW` (콤마 구분 아님).
- 기간: `from`·`to`는 날짜(`YYYY-MM-DD`), **KST 기준 하루 단위, `to` 포함**. 즉 `from 00:00+09:00 ≤ 시각 < (to + 1일) 00:00+09:00`. 목록·통계·엑셀이 같은 기준을 쓴다. 기준 시각은 `call_datetime`이며 통화 일시가 없는 건(`metadata_incomplete`)은 기간 필터에 걸리지 않는다(`metadata_incomplete=true` 필터로 조회). 코드에서는 예약어라 `Query(alias="from")`.
- `from`이 `to`보다 늦으면 422 `VALIDATION_ERROR`(`loc: ["query", "from"]`, `type: "date_range"`). 같은 날은 허용.
- `from`·`to`의 허용 범위는 `2000-01-01`~`2100-12-31`, 벗어나면 422 `VALIDATION_ERROR`.
- 통계 추이(`GET /api/stats/trend`)는 구간이 400개를 넘으면 422 `VALIDATION_ERROR`(`loc: ["query", "from"]`, `type: "range_too_large"`). `from`·`to`가 없으면 데이터의 첫·마지막 구간으로 센다.
- 키워드 `q`: 최대 100자(초과 422), 앞뒤 공백을 지운 뒤 비어 있으면 조건 없음. 대소문자 무시 부분 일치이며 `%`·`_`는 글자 그대로 검색한다. 대상은 질문 요약·조치 요약·교정 전사문(`corrected_text`).
- 담당자 `agent`·고객사 `client`는 정확히 일치. 빈 값(공백만 있는 값 포함)은 필터 없음으로 본다.
- 키워드 `q`는 로그에 남기지 않는다.

## 5. 값

### 5.1 시간
- 응답의 시각은 모두 **초 단위 ISO 8601 `+09:00`** (`"2026-11-23T14:30:05+09:00"`). 소수 초는 버린다.
- 요청의 시각은 오프셋이 있으면 그대로 해석하고, **오프셋이 없으면 KST로 간주**한다(`"2026-11-23T14:30:05"` = `14:30:05+09:00`).
- 날짜만 필요한 값(기간 필터)은 `YYYY-MM-DD`.
- 코드: 요청·응답 모델의 시각 필드는 `KstDatetime`으로 선언한다. 서버 내부·DB는 aware 값만 쓴다(`datetime.now(UTC)`; `datetime.now()`·`utcnow()` 금지). 응답 모델을 `model_construct()`로 만들지 않는다(검증을 건너뛰면 naive 값이 그대로 남는다).
- 요청의 통화 일시(`call_datetime`)는 KST 날짜 기준 `2000-01-01`~`2100-12-31`만 허용한다(기간 필터와 같은 범위, 벗어나면 422 `type: "datetime_range"`).

### 5.2 null과 빈 값
- 값이 없는 필드는 생략하지 않고 `null`로 보낸다. 빈 목록은 `[]`.
- 처리 전이라 없는 하위 객체(상세의 `transcript`·`analysis`)는 `null`, 로그는 `[]`.
- PATCH는 보낸 키만 변경한다. `null`은 값 비우기이며 비울 수 있는 필드에만 허용한다(코드: `model_dump(exclude_unset=True)`).
- 문자열 입력은 앞뒤 공백을 지운 뒤 검사한다. 지운 결과가 빈 값이면 422(`string_too_short`)다. 값 비우기는 `null` 한 가지로만 표현한다.
- PATCH 요청 모델은 선언하지 않은 키를 받지 않는다(422 `extra_forbidden`, `loc: ["body", "<키>"]`). 필드는 선택 필드로 추가한다(호환 변경).
- 수정·삭제는 `edit_history`에 남긴다: 실제로 바뀐 필드마다 1행(같은 값 재전송은 기록하지 않음), 값은 문자열(시각은 응답과 같은 초 단위 `+09:00`). 파생 값(`metadata_incomplete`)은 기록하지 않는다. 삭제는 `field: "deleted_at"` 1행이다. 수정자 이름은 선택 입력(공백 제거 후 1~50자)으로 PATCH는 본문 `editor`, DELETE는 쿼리 `?editor=`로 받는다. 로그인이 없으므로 자기 신고 값이다.

### 5.3 enum
- 값은 영문 대문자 상수다. OpenAPI `enum`으로 노출한다.
- 쿼리 파라미터의 선택 값(`sort`, `granularity`, `by`)은 enum이 아니라 소문자 허용 목록이다(§4.2와 같은 방식, 목록 밖은 422).

| 값 집합 | 값 |
|---|---|
| `status` | `REGISTERED`, `QUEUED`, `STT_DONE`, `STORED`, `NEEDS_REVIEW`, `FAILED`, `RETRY_REQUESTED` |
| `category` | `INQUIRY`(질의), `COMPLAINT`(불만), `SUGGESTION`(건의), `EDUCATION`(교육 내용), `ETC`(기타 문의) — 한글 표시명은 프론트가 매핑 |
| `action_status` | `OPEN`, `DONE` |
| `source_type` | `DRIVE`, `WEB` |
| `speaker` | `AGENT`, `CUSTOMER` |
| `processing_log.step` | `REGISTER`, `QUEUE`, `STT`, `GENAI`, `STORE`, `EXCEL`, `CRM`, `RETRY` |
| `processing_log.status` | `SUCCESS`, `FAIL`, `RETRY` |
| 헬스 `status` | `OK`, `DEGRADED`, `FAIL` |
| 헬스 `checks.*` | `OK`, `FAIL`, `DISABLED` |

- 정체(stale)는 상태 값이 아니다. 목록 항목의 `is_stale`(서버 계산)과 `stale` 필터로 표현한다. 두 항목은 정체 감지(R-11) 이후 추가된다(그전에는 응답에 없고 `stale` 파라미터는 무시된다).

### 5.4 숫자
- 숫자는 JSON 숫자로 보낸다. `Decimal`을 응답 모델에 쓰지 않는다(문자열로 나감). 신뢰도 `confidence`는 `float`(예: `0.85`).
- ID는 정수(BIGINT, JS 안전 범위 안).

### 5.5 모델 선언
- 요청 모델과 응답 모델을 분리한다(`CallUpdateRequest` / `CallDetail` 등). 같은 모델을 입·출력에 쓰면 OpenAPI에 `-Input`/`-Output` 스키마가 생긴다.
- 목록 응답은 `Page[CallListItem]`처럼 쓴다(OpenAPI 스키마 이름 `Page_CallListItem_`).

## 6. 보안·로그
- 응답에 음성 사본 내부 키(`object_key`), API Key, 서비스 계정 정보를 넣지 않는다.
- 로그에 요청·응답 본문, 쿼리 문자열(`q` 포함), 헤더 값을 남기지 않는다.

## 7. OpenAPI 공유
1. 계약 파일은 `backend/docs/api/openapi.json`이다. 라우트·요청·응답 모델을 바꾸면 `cd backend && uv run python -m scripts.export_openapi`로 다시 생성해 **같은 PR에 포함**한다. 파일이 코드와 다르면 `pytest`가 실패한다. 리뷰어는 이 파일의 diff로 계약 변경을 확인한다.
2. 개발 서버에서는 `/docs`(Swagger UI)·`/redoc`·`/openapi.json`을 연다. 운영은 `DOCS_ENABLED=false`로 모두 끈다(404).
3. operationId는 라우트 함수 이름이다(`list_calls`). 함수 이름은 앱 전체에서 고유해야 한다(테스트로 확인).
4. 라우터에 `tags`를 붙인다: 웹 `calls`·`uploads`·`stats`·`reports`, 로봇 `robot`, 운영 `health`.
5. 프론트 타입 생성 도구 선택은 프론트가 정한다(`openapi.json`은 OpenAPI 3.1).
