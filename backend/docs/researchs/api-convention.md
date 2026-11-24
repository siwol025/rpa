# API 규약 리서치 — 응답 · 에러 · 페이지네이션 · OpenAPI 공유

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` C-03 API 규약 (담당 B, A 리뷰) — 관련: W-01~W-12, R-04~R-10, C-02 |
| 근거 | `docs/prd.md`, `docs/input_flow.md` §6·§9, `architecture.md` v0.3 §3·§5·§6·§7·§11·§12, `research.md` v0.2 §4·§5, `back_stack.md` v0.1, `features.md` v0.2, `researchs/common-module.md`, `plans/common-module.md`, `backend/app/**`, `backend/.venv` 설치 소스 |
| 검증 방법 | 설치된 FastAPI 소스를 직접 읽고, 스크래치 스크립트(`TestClient`)로 OpenAPI 출력·직렬화 결과를 실측함 (레포 코드는 수정하지 않음) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 예시는 동작 확인용 스케치이며 최종 규약은 별도 계획/규약 문서에서 정한다.

---

## 0. 요약 (핵심 발견)

1. **에러 응답 본문은 이미 §7.2 형식으로 통일돼 있다.** `{code, message, detail}`이며 `detail`은 없으면 `null`로 항상 포함된다(`app/core/errors.py:80`). §7.2의 12개 에러 코드가 모두 `ErrorCode`에 있다(`errors.py:12-24`).
2. **OpenAPI 문서는 실제 응답과 다르다.** 경로·쿼리·본문 파라미터가 있는 모든 라우트에 FastAPI가 기본 `422 HTTPValidationError`(`{"detail": [{loc,msg,type,input,ctx}]}`)를 자동으로 넣는데(`fastapi/openapi/utils.py:508-527`), 실제 응답은 `{code, message, detail: {errors: [...]}}`이다. 404·409 등 다른 에러는 문서에 아예 없다.
3. **라우트(또는 라우터·앱)의 `responses`에 `422`(또는 `4XX`, `default`) 키가 있으면 FastAPI는 기본 422를 넣지 않는다**(`utils.py:510-513`, 실측). 즉 에러 응답 Pydantic 모델 + 라우터 단위 `responses=`만으로 문서를 실제 응답에 맞출 수 있다. 몽키패치는 필요 없다.
4. **Pydantic v2 제네릭 `Page[T]`가 FastAPI 0.165에서 그대로 동작한다.** 스키마 이름은 `Page_CallItem_`(title `Page[CallItem]`)로 생성된다(실측). `page>=1`, `size` 상한은 `Query(ge=, le=)`로 검증되고 위반 시 기존 `VALIDATION_ERROR` 형식으로 나간다(실측).
5. **기본 datetime 직렬화는 `+09:00`이 아니다.** UTC aware 값은 `"...Z"`로 나간다(실측). §7.2 "ISO 8601(+09:00)"을 지키려면 별도 직렬화가 필요하다. `Annotated[datetime, PlainSerializer(..., return_type=datetime)]`가 중첩·리스트까지 적용되고 OpenAPI의 `format: date-time`도 유지한다(실측). `return_type=str`로 쓰면 출력 스키마에서 `format`이 사라진다.
6. **naive datetime을 `astimezone()`하면 서버(컨테이너)의 로컬 시간대로 해석된다.** Windows(KST) 개발 PC와 UTC 컨테이너에서 결과가 달라지는 함정이 있다(실측). 응답 모델에는 aware 값만 들어와야 한다.
7. **`Decimal`(예: `analysis.confidence NUMERIC(4,3)`)은 JSON에서 문자열 `"0.850"`으로 나가고 OpenAPI 출력 타입도 `string`이다**(실측). 숫자로 주려면 응답 모델에서 `float`로 선언해야 한다.
8. 필드 이름 규칙은 어느 문서에도 명시돼 있지 않다. 기존 문서의 API 예시(`existing_id`, `call_id`, `retry_count`, `queue_item_id`, `metadata_incomplete`)와 DB 규칙(`back_stack.md:86`)은 모두 `snake_case`다.
9. 운영 `/docs` 비활성은 `FastAPI(openapi_url=None)` 한 줄로 `/docs`·`/redoc`·`/openapi.json`이 모두 404가 되며, 이때도 `app.openapi()`는 코드에서 호출 가능하다(실측) → 파일 내보내기와 양립한다. 현재 실행 환경을 구분하는 설정 값은 없다(`app/core/config.py:10-35`).
10. 문서 간 불일치 1건: `research.md:284`, `input_flow.md` §6.2·§9는 중복 응답을 `409 {existing_id, status}`(최상위)로 적었지만 §7.2와 현재 구현은 `detail` 안에 넣는다(`architecture.md:387`, `tests/unit/conftest.py` `/app-error`). 로봇이 읽을 경로가 `detail.existing_id`임을 RPA 파트와 맞춰야 한다.

---

## 1. 현재 상태

### 1.1 버전 (`.venv` 실측)
| 패키지 | 버전 |
|---|---|
| FastAPI | 0.165.0 |
| Starlette | 1.10.0 |
| Pydantic | 2.14.4 (pydantic-core 2.50.5) |
| OpenAPI 출력 버전 | 3.1.0 |

`pyproject.toml`은 `fastapi`·`pydantic>=2`로 범위만 두고 `uv.lock`으로 고정한다.

### 1.2 라우터·스키마
- `app/api/web/`, `app/api/robot/`, `app/schemas/`는 빈 패키지(`__init__.py`만)다. 등록된 업무 라우트는 없다.
- `create_app()`은 `FastAPI(title="Callcenter AI RPA Backend", version="0.1.0")`(`app/main.py:24`)로 생성하며 `docs_url`/`openapi_url`/`responses`/`generate_unique_id_function` 등은 기본값이다.
- 스모크 테스트가 `/openapi.json` 200을 확인한다(`tests/unit/test_app_smoke.py`). 운영에서 `/openapi.json`을 끄면 이 테스트의 전제(인자 없는 `create_app()`)와 충돌하지 않도록 설정 기본값을 개발용으로 둬야 한다.

### 1.3 에러 응답 (C-02 구현 결과)
형식: `{"code": <ErrorCode>, "message": <한국어 기본 메시지 또는 덮어쓴 값>, "detail": <object | null>}` (`errors.py:68-82`)

| code | HTTP | 기본 message (`errors.py:28-41`) | 발생 경로 |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | 요청 형식이 올바르지 않습니다. | `RequestValidationError`(경로·쿼리·본문·잘못된 JSON) |
| `DUPLICATE_FILE` | 409 | 이미 등록된 파일입니다. | `AppError` (R-04) |
| `INVALID_STATE_TRANSITION` | 409 | 현재 상태에서 허용되지 않는 요청입니다. | `AppError` (R-02) |
| `NOT_FOUND` | 404 | 대상을 찾을 수 없습니다. | `AppError`, 라우팅 404 |
| `PAYLOAD_TOO_LARGE` | 413 | 요청 크기가 제한을 초과했습니다. | `BodySizeLimitMiddleware` (`middleware.py:119`, 수신 중 초과는 `HTTPException(413)`) |
| `UNSUPPORTED_MEDIA` | 415 | 허용되지 않은 파일 형식입니다. | `AppError` (R-04, W-07) |
| `UNAUTHORIZED` | 401 | 인증에 실패했습니다. | `AppError` 또는 `HTTPException(401)` (R-01) |
| `FORBIDDEN_IP` | 403 | 허용되지 않은 IP입니다. | `AppError` / `error_response` (R-01) |
| `INBOX_UNAVAILABLE` | 503 | 업로드 저장소를 사용할 수 없습니다. | `AppError` (W-07/W-08) |
| `BAD_REQUEST` | 400 | 잘못된 요청입니다. | multipart 파싱 실패 등 `HTTPException(400)`, 매핑 없는 4xx |
| `METHOD_NOT_ALLOWED` | 405 | 허용되지 않은 메서드입니다. | 라우팅 405 (`Allow` 헤더 유지) |
| `INTERNAL_ERROR` | 500 | 서버 내부 오류가 발생했습니다. | `UnhandledErrorMiddleware` (`middleware.py:91`), 5xx `HTTPException` |

`VALIDATION_ERROR`의 `detail` 형식 (`errors.py:97-103`, `tests/unit/test_errors.py:60-70`)
```json
{
  "code": "VALIDATION_ERROR",
  "message": "요청 형식이 올바르지 않습니다.",
  "detail": {
    "errors": [
      {"loc": ["query", "page"], "msg": "Input should be greater than or equal to 1", "type": "greater_than_equal"},
      {"loc": ["query", "status", 0], "msg": "Input should be 'REGISTERED' or 'STORED'", "type": "enum"}
    ]
  }
}
```
- `input`·`ctx`·`url`은 제외한다. `loc` 첫 요소는 `path`/`query`/`header`/`body`, 리스트 인덱스는 정수로 들어간다.
- `msg`는 Pydantic 영어 문구 그대로다. 화면 표시는 `message`(한국어), 필드 하이라이트는 `loc`, 세부 분기는 `type`을 쓰는 구조다.
- 잘못된 JSON은 `type: "json_invalid"`로 422(`test_errors.py:72-77`), multipart 깨짐은 400 `BAD_REQUEST`(`test_errors.py:79-88`).

알려진 동작
- `_STATUS_TO_CODE`(`errors.py:44-50`)에 403·415가 없으므로 프레임워크가 `HTTPException(403)`/`(415)`를 던지면 HTTP 상태는 유지되고 `code`는 `BAD_REQUEST`가 된다. 현재 설계상 403·415는 `AppError`로만 던지므로 문제는 없지만, 규약 문서에 "403·415·409·503은 `AppError`로 던진다"를 적어 둘 필요가 있다.
- 모든 응답(500·413·preflight 포함)에 `X-Request-Id`가 붙고 CORS `expose_headers`에 포함돼 있다(`main.py:31-37`).

### 1.4 §7.2 대비 비어 있는 것
| 항목 | 상태 |
|---|---|
| 에러 응답 Pydantic 모델 (OpenAPI 문서화) | 없음 (`plans/common-module.md:36`에서 C-03으로 넘김) |
| 목록 응답 모델 `{items, page, size, total}` | 없음 |
| 페이지·크기·정렬 쿼리 규칙 | 없음 (`research.md:268`에 파라미터 이름만 있음) |
| 시간 직렬화 `+09:00` | 없음 (기본 직렬화는 `Z`) |
| 필드 이름 규칙, null 처리, Enum 값 표기 | 문서화 안 됨 |
| 엔드포인트별 성공 상태 코드 | 일부만 있음 (업로드 202, 재처리 202, 등록 201) |
| OpenAPI 공유 방식·운영 `/docs` 비활성 설정 | 없음 (`plans/common-module.md` §8 #5) |
| "validator 메시지에 입력값 금지" 규칙 | 규칙 문서 없음 (`plans/common-module.md:649`) |

---

## 2. 에러 응답 — OpenAPI 문서화

### 2.1 FastAPI가 422를 문서에 넣는 방식 (0.165.0 소스)
`fastapi/openapi/utils.py`
- `validation_error_definition`(49-64행): `ValidationError {loc, msg, type, input, ctx}`
- `validation_error_response_definition`(66-76행): `HTTPValidationError {detail: ValidationError[]}`
- 508-527행: `if (all_route_params or route.body_field) and not any(status in operation["responses"] for status in ["422", "4XX", "default"])` → 기본 422와 두 스키마를 추가

즉 **라우트에 파라미터나 본문이 있고, `responses`에 422/4XX/default가 없을 때만** 기본 422가 붙는다. 라우트의 `responses`는 `FastAPI(responses=)` → `include_router(responses=)` → `APIRouter(responses=)` → 데코레이터 `responses=` 순으로 합쳐진다.

### 2.2 실측 결과
```python
class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | None

router = APIRouter(prefix="/api/calls",
                   responses={422: {"model": ErrorBody, "description": "검증 실패"}, 404: {"model": ErrorBody}})
```
| 확인 항목 | 결과 |
|---|---|
| 라우터에 `responses={422: ...}` | 해당 라우터의 모든 operation 422가 `ErrorBody`로 바뀜. 기본 `HTTPValidationError` 미추가 |
| 같은 앱에 `responses` 없는 라우트가 하나라도 있으면 | 그 라우트에 기본 422가 붙고 `components.schemas`에 `HTTPValidationError`·`ValidationError`가 남음 |
| `FastAPI(responses={...})` 앱 수준 | `include_router`로 붙인 라우트에도 적용됨 |
| `status_code=204` DELETE + 경로 파라미터 | `204`, `422`, `404`가 문서에 나옴 (정상) |
| 라우팅 404·405, 413, 500 | 라우트가 아닌 미들웨어/프레임워크에서 나오므로 `responses`에 적지 않으면 문서에 없음 |

### 2.3 모델 설계 선택지
| 선택지 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 단일 `ErrorResponse` | `code: ErrorCode`, `message: str`, `detail: dict[str, Any] \| None` | 단순, 모든 상태 코드에 재사용 | `VALIDATION_ERROR`·`DUPLICATE_FILE`의 `detail` 구조가 문서에 안 보임 |
| B. 공통 + 구조가 있는 detail만 별도 | `ErrorResponse`(일반) + `ValidationErrorResponse`(`detail: {errors: ValidationErrorItem[]}`) + `DuplicateFileErrorResponse`(`detail: {existing_id, status}`) | 프론트·로봇이 실제로 파싱하는 두 형식이 문서·타입 생성에 반영됨 | 모델 3~4개 |
| C. 코드별 모델 전부 | 12개 | 정밀 | 과함 |

`code`를 `ErrorCode`(StrEnum)로 선언하면 OpenAPI에 `enum` 목록이 그대로 나가 프론트가 코드 분기를 타입으로 받을 수 있다. 다만 상태 코드별로 가능한 `code`를 좁혀 주지는 않는다(설명 `description`으로 보완).

### 2.4 부착 위치 선택지
| 위치 | 예 | 비고 |
|---|---|---|
| 공용 상수 | `COMMON_ERRORS = {422: {...}, 500: {...}}`, `NOT_FOUND = {404: {...}}` | 라우터/데코레이터에서 `responses={**COMMON_ERRORS, **NOT_FOUND}` |
| 라우터 단위 | `APIRouter(responses=COMMON_ERRORS)` | `api/web/*`, `api/robot/*`마다 지정. 로봇 라우터는 401·403 추가 |
| 앱 단위 | `FastAPI(responses=COMMON_ERRORS)` | 한 곳에서 끝나 `HTTPValidationError`가 문서에서 사라짐. 단 파라미터 없는 `/health`에도 422가 붙음(사소한 부정확) |
| 데코레이터 단위 | `@router.post(..., responses={409: ...})` | 엔드포인트 고유 에러(409 중복·상태 전이, 415, 503) |

`responses` 값의 `description`에 "가능한 code: `INVALID_STATE_TRANSITION`" 식으로 적으면 Swagger UI에서 바로 보인다.

---

## 3. 목록 · 페이지네이션

### 3.1 목록이 필요한 화면·API (PRD 기준)
| 화면 (PRD) | API | 페이지네이션 |
|---|---|---|
| 상담 목록·검색 WEB-02, 처리 상태 모니터링 WEB-05(폴링), 정체 건 경고, 메타데이터 확인 필요 | `GET /api/calls` (W-01) | 필요 — 유일한 대량 목록 |
| 상담 상세 WEB-03의 처리 로그 | `GET /api/calls/{id}` 안의 `logs[]` (W-02) | 불필요 (건당 수~수십 행, 상세에 포함) |
| 상세의 전사 `segments` | `GET /api/calls/{id}` 안 | 불필요 |
| 통계 WEB-01 | `/api/stats/*` (W-09·W-10) | 불필요 (집계 결과, 고정 크기) |
| 재처리 대상 조회 (로봇) | `GET /api/robot/calls?status=RETRY_REQUESTED` (R-09) | 선택 (§8 #6) |

### 3.2 제네릭 모델 (Pydantic v2)
```python
T = TypeVar("T")
class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total: int
```
- `response_model=Page[CallListItem]`로 사용. FastAPI 0.165에서 스키마 키 `Page_CallListItem_`, title `Page[CallListItem]`으로 생성(실측). openapi-typescript 등에서 타입 이름이 `Page_CallListItem_`가 되므로 거슬리면 `class CallPage(Page[CallListItem]): pass`처럼 이름 있는 하위 클래스를 쓰는 방법이 있다.
- Python 3.12 문법 `class Page[T](BaseModel)`도 Pydantic 2.14에서 지원되지만 mypy·Ruff 설정(`target-version = "py312"`)과 함께 하나로 통일하는 것이 좋다.

### 3.3 쿼리 파라미터
| 파라미터 | 실측 동작 | 선택지 |
|---|---|---|
| `page` | `Annotated[int, Query(ge=1)] = 1` → 0이면 422 `greater_than_equal` | 1부터 (§7.2 예시가 `page: 1`) |
| `size` | `Annotated[int, Query(ge=1, le=100)] = 20` → 1000이면 422 `less_than_equal` | 기본 20(§7.2 예시), 상한 50/100/200 |
| `status` 등 다중 값 | `Annotated[list[Status] \| None, Query()]` → `?status=FAILED&status=NEEDS_REVIEW` 동작, 잘못된 값은 422 `enum` | 반복 파라미터 vs 콤마 구분 (§8 #4) |
| `from`/`to` | 파이썬 예약어이므로 `Query(alias="from")`. 문서에는 `from`으로 나옴(실측) | `date`(YYYY-MM-DD) vs `datetime` |
| `q` | 키워드(`pg_trgm`). 로그에 남기지 않음(C-02 결정 #18) | 최소 길이(`pg_trgm`은 3글자 미만에서 인덱스 효율이 떨어짐) **[확인 필요]** |

기간 필터 해석 (선택지)
- `from`/`to`를 `date`로 받고 **KST 기준 하루 단위, `to` 포함** → SQL은 `call_datetime >= from 00:00+09:00 AND call_datetime < (to+1일) 00:00+09:00`. 화면의 날짜 선택기와 1:1이고 시간대 실수가 적다.
- `call_datetime`은 NULL 허용(`architecture.md:348`)이므로 기간 필터를 걸면 메타데이터 누락 건이 빠진다. 기준 시각을 `call_datetime`만 쓸지, 없으면 `created_at`으로 대신할지 정해야 한다(§8 #5).

### 3.4 정렬
| 선택지 | 예 | 비고 |
|---|---|---|
| 부호 접두사 | `sort=-call_datetime` | 간결, 흔한 관례. 값은 허용 목록(`Literal`/Enum)으로 검증 → OpenAPI에 목록 노출 |
| 필드+방향 분리 | `sort=call_datetime&order=desc` | 파라미터 2개 |
| 콤마 다중 | `sort=-status_changed_at,id` | 현재 화면에 필요 없음 |

규칙 후보
- 허용 필드: `call_datetime`, `created_at`, `status_changed_at` (정체 모니터링용) 정도. 임의 컬럼 허용 금지(SQL 주입·인덱스 없는 정렬 방지).
- 항상 마지막에 `id` 동순위 정렬을 붙여 페이지 간 중복·누락 방지(폴링 중 신규 건 유입 시에도 결정적 순서).
- `call_datetime`은 NULL 가능 → `NULLS LAST` 명시.
- 기본값: `-call_datetime` 또는 `-created_at` (§8 #3).

### 3.5 범위 밖 페이지
| 선택지 | 동작 | 평가 |
|---|---|---|
| 빈 목록 | `page=999` → `{"items": [], "page": 999, "size": 20, "total": 154}` | 필터 변경·삭제로 마지막 페이지가 사라져도 에러 없이 처리, 프론트가 `total`로 이동 가능. 일반적 |
| 404 | `NOT_FOUND` | 폴링 중 삭제 한 건으로 에러가 나는 등 프론트 처리 부담 |

### 3.6 `total` 계산 비용
- 규모: 일 수십~백여 건(`prd.md:248`) → 연 수만 행. `COUNT(*)`(필터 포함)는 인덱스(`call_datetime`, `status, status_changed_at`, `pg_trgm`)로 충분히 빠르다. PRD 응답 2초(`prd.md:247`) 대비 부담 없음.
- 구현 방식: 목록 쿼리 + 같은 WHERE의 `COUNT(*)` 별도 쿼리. `count(*) OVER()` 윈도 함수 방식은 범위 밖 페이지에서 행이 없어 `total`을 못 얻으므로 3.5의 "빈 목록 + total"과 맞지 않는다.
- 커서 페이지네이션은 필요 없다(규모 작음, 화면이 페이지 번호 방식).

---

## 4. 필드 · 값 직렬화

### 4.1 필드 이름
| 근거 | 표기 |
|---|---|
| DB 컬럼 | `snake_case` (`back_stack.md:86`) |
| 기존 API 예시 | `existing_id`, `call_id`, `retry_count`, `queue_item_id`, `metadata_incomplete`, `file_hash`, `source_ref` (`architecture.md:387`, `input_flow.md` §9, `research.md:140`) |
| 프론트 요구 | 문서에 없음 |

camelCase로 내보내려면 `ConfigDict(alias_generator=to_camel, validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)`(Pydantic 2.11+ 옵션)로 가능하고, FastAPI 응답·OpenAPI 모두 `callDatetime`으로 나온다(실측). 그러나 로봇 API(UiPath)·에러 `detail`·쿼리 파라미터까지 일관되게 바꿔야 하고 기존 문서 예시를 모두 고쳐야 한다. 웹/로봇 표기를 나누면 같은 개념이 두 이름을 갖는다.

### 4.2 시간 (TIMESTAMPTZ → ISO 8601 +09:00)
규칙 출처: `architecture.md:407` "API는 ISO 8601(+09:00)", `back_stack.md` §3.3 "서버 저장은 UTC, API 응답은 +09:00".

실측
| 방식 | 출력 | 중첩 모델 | `list[datetime]` | OpenAPI 출력 `format: date-time` |
|---|---|---|---|---|
| 기본 | `2026-11-23T05:30:05Z` | — | — | 있음 |
| `Annotated[datetime, PlainSerializer(f, return_type=datetime, when_used="json")]` | `2026-11-23T14:30:05+09:00` | 적용 | 적용 | **있음** |
| 같은 방식 `return_type=str` | 같음 | 적용 | 적용 | **없음** (`type: string`만) |
| 공통 베이스 `@field_serializer("*", mode="wrap", when_used="json")` | `+09:00` | 적용 | **미적용** (`...Z` 그대로) | 있음 |

- Pydantic v2에는 "모든 datetime을 특정 시간대로" 같은 전역 `model_config` 옵션이 없다. 응답 모델의 시간 필드 타입을 공용 `Annotated` 별칭(예: `KstDatetime`)으로 통일하는 방식이 가장 확실하다.
- `when_used="json"`이므로 `model_dump()`(파이썬 모드)는 원래 값 유지 → 서비스·테스트 로직에 영향 없음.
- 소수 초: 기본 `isoformat()`은 마이크로초(`.123456`)를 포함한다. `isoformat(timespec="seconds")`로 자를지 결정 필요(화면은 초 단위면 충분).
- **naive 값 주의**: `naive.astimezone(KST)`는 프로세스 로컬 시간대를 가정한다(실측: KST 개발 PC에서는 벽시계 값 그대로 `+09:00`). UTC 컨테이너에서는 9시간 차이가 난다. psycopg 3는 `TIMESTAMPTZ`를 aware `datetime`으로 돌려주므로 DB 경유 값은 안전하지만, 코드에서 `datetime.now()`(naive)를 쓰면 깨진다 → `datetime.now(UTC)`만 사용, 직렬화기에서 naive면 예외/로그로 드러내는 방식 검토.
- 시간대 설정: 현재 `Settings`에 시간대 항목 없음. 값이 고정(KST)이고 §7.2에 명시돼 있으므로 상수 `ZoneInfo("Asia/Seoul")`로 충분하다. Windows에는 IANA 시간대 DB가 없어 `zoneinfo`가 `tzdata` 패키지를 쓴다. 현재 `tzdata`는 psycopg의 Windows 전용 간접 의존성(`uv.lock:763`, `sys_platform == 'win32'`)으로만 설치돼 있고, Linux 컨테이너는 OS의 `/usr/share/zoneinfo`에 의존한다(slim 이미지에 없을 수 있음 **[확인 필요]**). 고정 오프셋 `timezone(timedelta(hours=9))`는 의존성이 없고 한국은 서머타임이 없어 결과가 같다.
- 입력 쪽: `AwareDatetime`을 쓰면 오프셋 없는 값(`2026-11-23T14:30:05`)이 422 `timezone_aware`가 된다(실측). 로봇은 파일명(`yyyyMMdd_HHmmss`, 시간대 없음, `input_flow.md` §7)에서 시각을 뽑으므로 등록 API(R-04)의 `call_datetime` 입력을 "오프셋 필수"로 할지 "오프셋 없으면 KST로 간주"로 할지 정해야 한다(§8 #8, A·RPA 합의 사항). 웹 PATCH(W-12)의 `call_datetime`도 같은 규칙을 쓰는 것이 일관적이다.

### 4.3 null vs 생략
- FastAPI 기본은 값이 없으면 `null`로 **키를 포함**한다(`response_model_exclude_none` 미사용 시). 출력 스키마에서도 기본값 있는 필드가 `required`로 표시된다(실측: `M-Output.required`에 `opt` 포함) → 프론트 타입이 `string | null`로 정확해진다.
- 같은 모델을 입력·출력에 함께 쓰면 FastAPI가 `M-Input`/`M-Output` 두 스키마를 만든다(`separate_input_output_schemas=True` 기본, 실측). 요청·응답 모델을 분리해 선언하면 이름이 깔끔하다.
- PATCH(W-03·W-12) 입력은 "키 없음 = 변경 안 함, `null` = 값 비우기"를 구분해야 한다 → `model_dump(exclude_unset=True)` / `model_fields_set` 사용. 비울 수 있는 필드(예: `client_company`)와 비울 수 없는 필드(`category`)를 구분.
- 응답에서 없는 하위 객체: 상세의 `transcript`·`analysis`는 처리 전이면 `null`(키 유지), `logs`는 빈 배열.

### 4.4 Enum 값
| 값 집합 | 출처 | 비고 |
|---|---|---|
| `status`: `REGISTERED`, `QUEUED`, `STT_DONE`, `STORED`, `NEEDS_REVIEW`, `FAILED`, `RETRY_REQUESTED` | `architecture.md` §5 | 영문 대문자 상수. `StrEnum`으로 선언하면 OpenAPI `enum`으로 노출 |
| `category`: 질의, 불만, 건의, 교육 내용, 기타 문의 | `prd.md` AI-01, `research.md:195` | 한글 값 그대로 vs 코드(`INQUIRY/COMPLAINT/SUGGESTION/EDUCATION/ETC`) 병행 검토 중(`research.md:238`) → §8 #9 |
| `action_status`: `OPEN`, `DONE` | `research.md:200` | |
| `source_type`: `DRIVE`, `WEB` | `research.md:158` | |
| `segments[].speaker`: `AGENT`, `CUSTOMER` | `research.md:185` | E-03 확정 대상 |
| `processing_log.step`/`status` | `research.md:214-215` | |

- 잘못된 enum 값의 422 `msg`는 허용 값 목록을 보여 줄 뿐 입력값은 담지 않는다(실측 `"Input should be 'REGISTERED' or 'STORED'"`).
- 한글 enum 값은 URL 쿼리(`?category=교육 내용`)에서 인코딩·공백 문제가 생기기 쉽다.
- 정체(`stale`)는 상태 값이 아니다(§12). 목록 항목에 `is_stale: bool` 같은 계산 필드를 넣을지는 프론트의 경고 표시 방식에 따라 정한다(§8 #10).

### 4.5 숫자
- `Decimal` → JSON 문자열 `"0.850"`, OpenAPI 출력 `type: string`(실측). `confidence`는 응답 모델에서 `float`로 선언하면 `0.85` 숫자로 나간다.
- `BIGINT` id는 JS `Number` 안전 범위(2^53) 안이므로 숫자로 내보내도 된다.

---

## 5. 단일 리소스 · 동작 응답

### 5.1 엔드포인트별 상태 코드 (`research.md` §5, `architecture.md` §4·§5 기준)
웹 (`/api/*`)
| Method | Endpoint | 성공 | 성공 본문 (후보) | 예상 에러 |
|---|---|---|---|---|
| POST | `/api/uploads` | **202** (`architecture.md:165`, W-07) | 접수 결과 (파일별 이름·Drive 파일 ID 여부) §8 #11 | 413, 415, 422, 400, 503 |
| GET | `/api/calls` | 200 | `Page[CallListItem]` | 422 |
| GET | `/api/calls/{id}` | 200 | 상세 (call + transcript + analysis + logs) | 404, 422 |
| PATCH | `/api/calls/{id}` | 200 | 갱신된 상세 (재조회 불필요) | 404, 409(검토 완료가 `NEEDS_REVIEW` 아님), 422 |
| DELETE | `/api/calls/{id}` | **204** (본문 없음) | — | 404 (이미 삭제된 건 포함, §8 #12) |
| POST | `/api/calls/{id}/retry` | **202** (`architecture.md:227`) | `{id, status: "RETRY_REQUESTED", retry_count}` | 404, 409 |
| GET | `/api/calls/{id}/audio` | 200 / **206**(Range) / GCS면 302 | 음성 바이트 | 404, 416(범위 오류 — 현재 `ErrorCode` 없음) |
| GET | `/api/stats/summary` | 200 | KPI 객체 | 422 |
| GET | `/api/stats/trend` | 200 | `{granularity, points: [{period, count, by_category?}]}` 형태 합의 필요 | 422 |
| GET | `/api/stats/breakdown` | 200 | `{by, rows: [{key, count, ...}]}` 형태 합의 필요 | 422 |
| GET | `/api/reports/excel` | 200 (xlsx) | 파일, `Content-Disposition` | 422 (기간 초과 포함) |

로봇 (`/api/robot/*`, 공통 401·403 추가)
| Method | Endpoint | 성공 | 성공 본문 (후보) | 예상 에러 |
|---|---|---|---|---|
| POST | `/api/robot/calls` | **201** (`architecture.md:178`) | `{call_id}` (`input_flow.md` §9) | 409 `DUPLICATE_FILE` + `detail{existing_id, status}`, 413, 415, 422 |
| PATCH | `/api/robot/calls/{id}/status` | 200 | `{call_id, status}` | 404, 409, 422 |
| GET | `/api/robot/calls?status=RETRY_REQUESTED` | 200 | `{items: [{call_id, retry_count}]}` (§8 #6) | 422 |
| GET | `/api/robot/calls/{id}/audio` | 200 | 음성 바이트 | 404 |
| PUT | `.../transcript` | 200 (재전송도 200, 멱등) | `{call_id, status}` | 404, 409, 422 |
| PUT | `.../analysis` | 200 | `{call_id, status}` (`STORED`/`NEEDS_REVIEW` → 로봇이 결과 확인 가능) | 404, 409, 422 |
| POST | `.../logs` | 201 | `{id}` 또는 `{call_id, status}` | 404, 409(FAIL 보고인데 전이 불가), 422 |

관찰
- 동작(action) 응답이 `{call_id, status}`를 돌려주면 로봇이 UiPath 로그에 결과 상태를 남길 수 있고(`architecture.md:408`) 웹은 재조회 없이 화면을 갱신할 수 있다.
- 단일 리소스의 식별자 키 이름: 웹 상세는 `id`, 로봇 응답은 `call_id`(문서 예시)로 섞여 있다. 웹 목록·상세도 `id`로 둘지, 전체를 `call_id`로 통일할지 정해야 한다(§8 #13).
- PUT 적재 재전송이 200(같은 결과)이므로 로봇은 200/201 외 4xx를 "재시도해도 소용없음", 5xx·네트워크 오류를 "재시도"로 구분하면 된다(`research.md:144` [가정]). 단, 정체 건 재처리 이후 옛 Queue 건의 409는 정상 종료로 처리(`input_flow.md` §6.3, RPA 합의 필요).
- 파일 다운로드(엑셀) 한글 파일명은 `Content-Disposition: attachment; filename="report_20261101-20261130.xlsx"; filename*=UTF-8''...` 형식이 안전하고, 프론트가 `fetch`로 받아 이름을 읽으려면 CORS `expose_headers`에 `Content-Disposition`을 추가해야 한다(`plans/common-module.md` §1.3에서 해당 기능으로 넘김). `<audio src>` 재생은 CORS 노출 헤더가 필요 없다.

---

## 6. OpenAPI 공유

### 6.1 현재 상태와 운영 비활성
- `architecture.md:380`: `/docs`는 "운영 환경에서는 비활성 또는 IP 제한", "OpenAPI = 팀 간 계약서".
- 실측: `FastAPI(openapi_url=None)` → `/docs`, `/openapi.json` 모두 404. `docs_url=None, redoc_url=None`만 주면 UI만 끄고 `/openapi.json`은 남는다. 어느 경우든 `app.openapi()`는 코드에서 호출된다.
- 운영/개발 구분 값이 필요하다. 후보: `DOCS_ENABLED: bool = True`(개발 기본, 운영 `.env`에서 `false`) 또는 `APP_ENV: Literal["dev","prod"]`. 기본값을 개발용으로 두면 스모크 테스트(`/openapi.json` 200)가 그대로 유지된다. 현재 IP 제한 미들웨어는 `/api/robot/*` 전용이라 "IP 제한" 방식은 별도 구현이 필요하다.

### 6.2 공유 방식 선택지
| 선택지 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 개발 서버 `/docs`만 | 프론트·RPA가 개발 서버에 접속해 확인 | 추가 작업 없음 | 서버가 떠 있어야 함, 변경 이력 없음, 리뷰에서 계약 변경이 안 보임 |
| B. `openapi.json` 파일 커밋 | 스크립트로 `app.openapi()`를 파일로 내보내 레포에 커밋 (예: `backend/docs/api/openapi.json`) | PR diff로 계약 변경이 보임, 서버 없이 타입 생성·Swagger Editor 열람 가능 | 갱신 누락 위험 |
| C. B + 최신 여부 테스트 | 테스트가 `app.openapi()`와 커밋된 파일을 비교해 다르면 실패 | 누락 방지, 리뷰어(A·B 상호)가 계약 변경을 강제로 확인 | 스키마 변경 시마다 파일 재생성 필요 |
| D. CI 산출물 | CI가 생성해 아티팩트로 배포 | 레포 오염 없음 | CI 구성 필요(현재 없음) |

내보내기 스케치 (실행 시 설정이 필요 없도록 `create_app(Settings(_env_file=None))` 사용)
```python
# scripts/export_openapi.py (가칭)
import json, sys
from app.core.config import Settings
from app.main import create_app
spec = create_app(Settings(_env_file=None)).openapi()
json.dump(spec, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
```
- `sort_keys=True`와 고정 들여쓰기로 diff를 안정화. `ensure_ascii=False`면 한글 설명이 그대로 보인다(Windows 콘솔 출력 시에는 파일로 직접 쓰기 권장 — 콘솔 cp949에서 한글이 깨지는 것을 실측).
- `info.version`(`main.py:24`, 현재 `0.1.0`)은 계약 변경 시 올리는 값으로 쓸 수 있다.

### 6.3 operationId·태그
- 기본 operationId는 `list_calls_api_calls_get`처럼 함수명+경로+메서드(실측). 타입 생성기는 이 값을 함수 이름으로 쓰므로 `FastAPI(generate_unique_id_function=lambda r: r.name)` 등으로 함수명만 쓰는 방법이 있다(함수명 중복 금지 규칙 필요).
- `tags=["calls"]`, `["robot"]`로 묶으면 Swagger UI와 생성 코드가 그룹화된다.

### 6.4 버전 관리
- 사내 단일 프론트·로봇 소비자, 동시 배포 가능 → URL 버전(`/api/v1`) 없이 운영하는 것이 일반적. 로봇은 Orchestrator 배포 주기가 달라 **로봇 API의 비호환 변경은 사전 합의 후 배포** 규칙이 필요하다.
- 비호환 변경 정의(필드 삭제·이름 변경·타입 변경·enum 값 삭제)와 호환 변경(필드 추가·enum 값 추가)을 규약에 적어 둘 수 있다. 응답에 필드를 추가해도 UiPath JSON 파싱이 깨지지 않는지는 **[확인 필요]**(일반적으로 무시됨).

### 6.5 프론트 타입 생성 (참고 — 결정은 프론트 담당)
- `openapi-typescript`(타입만 생성), `openapi-fetch`(타입 안전 fetch), `orval`·`@hey-api/openapi-ts`(클라이언트·React Query 훅 생성) 등이 OpenAPI 3.1을 입력으로 받는다. 백엔드가 제공할 것은 정확한 `openapi.json`(§2·§4의 422 모델, nullable, enum, date-time format)뿐이다.

---

## 7. 규약 문서에 넣을 규칙 후보

에러
1. 에러 본문은 항상 `{code, message, detail}`. `detail`은 없으면 `null`. 상태 코드 ↔ `code`는 §7.2 표를 따른다.
2. 서비스·라우터는 `AppError(ErrorCode.X, ...)`로만 에러를 던진다. `HTTPException`을 직접 쓰지 않는다(403·415 등 매핑 누락 방지, §1.3).
3. `message`는 사용자에게 그대로 보여 줄 수 있는 한국어 문장. 프론트의 분기는 `code`로 한다(`message` 문자열 비교 금지).
4. **validator·`AppError`의 `message`/`detail`에 요청 입력값을 넣지 않는다.** 커스텀 validator의 `ValueError(f"... {value}")`는 `msg`(`"Value error, bad phone 010-1234-5678"`)로 응답에 그대로 나간다(실측). 전화번호·이름 등 PII가 노출될 수 있다(`plans/common-module.md:649`).
5. `detail`에는 식별자·상태 등 클라이언트 처리에 필요한 값만 넣는다(예: `existing_id`, `status`). 예외 메시지 원문·SQL·스택은 넣지 않는다.
6. 모든 라우터는 공용 에러 `responses`를 붙여 OpenAPI의 422가 실제 형식과 같게 한다. 엔드포인트 고유 에러(409·415·503)는 데코레이터에 추가한다.

목록
7. 목록 응답은 `{items, page, size, total}`. `page`는 1부터, `size` 기본 20·상한 N. 범위 밖 페이지는 빈 `items`(에러 아님).
8. 정렬은 허용 목록의 필드만, 마지막에 `id` 동순위 정렬. NULL 가능 필드는 `NULLS LAST`.
9. 소프트 삭제 건은 모든 웹 조회에서 제외(`architecture.md:397` "없음 또는 소프트 삭제됨" → 404).

값
10. 필드 이름 표기 하나로 통일(§8 #1). 쿼리 파라미터도 같은 표기.
11. 시간 응답은 ISO 8601 `+09:00`. 서버 내부·DB는 UTC aware 값만 사용, naive `datetime` 금지.
12. 값이 없는 필드는 생략하지 않고 `null`. 빈 목록은 `[]`.
13. enum은 문서에 정의된 상수만, OpenAPI `enum`으로 노출. 값 추가는 호환 변경, 삭제·변경은 비호환.
14. 금액·비율 등 숫자는 JSON 숫자(`Decimal` 응답 금지 → `float`).
15. 요청·응답 모델을 분리 선언(`...Request`/`...Response`)해 OpenAPI의 `-Input`/`-Output` 분리를 피한다.

PATCH·동작
16. PATCH는 보낸 키만 변경, `null`은 값 비우기(허용된 필드만).
17. 생성 201, 비동기 접수 202, 본문 없는 삭제 204, 그 외 200. 동작 API는 결과 상태를 본문에 돌려준다.

보안·로그
18. 응답·로그에 `X-API-Key`, 서비스 계정 정보, 음성 사본 내부 경로(`object_key`)·Drive 파일 ID를 노출할지 여부를 명시(기본: `object_key`는 응답에서 제외 — UUID 키라도 내부 구조 노출 불필요). 검색어 `q`는 로그 금지(C-02 결정 #18).
19. 모든 응답에 `X-Request-Id`. 프론트는 에러 표시 시 이 값을 보여 주거나 문의에 사용할 수 있다.

OpenAPI
20. 스키마 변경 PR에는 갱신된 `openapi.json`을 포함한다(§8 #14 채택 시).

---

## 8. 미결 사항 (선택지와 권장안)

**[핵심]** 표시는 프론트·RPA 등 다른 파트에 영향을 주거나 되돌리기 어려운 결정으로, 사용자/팀 확인이 필요하다.

| # | 항목 | 선택지 | 권장안 | 이유 |
|---|---|---|---|---|
| 1 | **[핵심]** 필드 이름 표기 | (a) 전체 `snake_case` (b) 웹만 camelCase (c) 전체 camelCase | **(a)** | 기존 모든 문서 예시·DB·로봇 계약이 snake_case. 변환 계층이 없어 단순, 웹/로봇 간 같은 개념이 같은 이름. 프론트가 camelCase를 원하면 타입 생성 단계에서 변환 가능 |
| 2 | **[핵심]** 에러 모델 범위 | §2.3 A / B / C | **B** (공통 `ErrorResponse` + `ValidationErrorResponse` + `DuplicateFileErrorResponse`) | 프론트(422 필드 표시)·로봇(409 `existing_id`)이 실제 파싱하는 두 형식만 정밀하게 문서화, 나머지는 공통 |
| 3 | 목록 기본 정렬·허용 필드 | `-call_datetime` / `-created_at` | **`-created_at`(+`id`)**, 허용: `call_datetime`, `created_at`, `status_changed_at` | `created_at`은 NOT NULL이라 메타데이터 누락 건도 자연스럽게 섞이고, 폴링 모니터링에서 "새로 들어온 건이 위"가 직관적. 통화 일시 정렬은 선택 가능 |
| 4 | 다중 값 필터 형식 | 반복 파라미터 `?status=A&status=B` / 콤마 `?status=A,B` | **반복 파라미터** | FastAPI `list[...]` 기본 동작, OpenAPI `array`로 정확히 표현돼 타입 생성기와 호환(실측). 콤마는 커스텀 파싱 필요 |
| 5 | **[핵심]** 기간 필터 의미 | `date`(KST, `to` 포함) / `datetime`(오프셋 포함); 기준 필드 `call_datetime` / `call_datetime` 없으면 `created_at` | **`date`, KST 하루 단위, `to` 포함**, 기준은 **`call_datetime`**, 누락 건은 `metadata_incomplete` 필터로 따로 조회 | 날짜 선택기와 1:1, 시간대 실수 방지. 통계·엑셀(W-09~11)도 같은 기준이어야 수치가 맞으므로 프론트·통계 담당과 함께 확정 |
| 6 | 로봇 재처리 대상 조회 형식 | 페이지네이션 `Page` / `{items}`만 (상한 N) / 배열 그대로 | **`{"items": [{call_id, retry_count}]}`, 페이지 없음(서버 상한 예: 100)** | Dispatcher는 한 번에 전부 가져가야 하고 대상 수가 적음. 객체로 감싸야 이후 필드 추가가 호환 변경. RPA 파트(A 담당 합의)와 확인 |
| 7 | `size` 상한 | 50 / 100 / 200 | **100** | 규모상 부담 없음, 프론트가 한 화면에 보여 줄 현실적 최대. 기본 20은 §7.2 예시 유지 |
| 8 | **[핵심]** 시간 입력에 오프셋 없는 값 | 422로 거부(`AwareDatetime`) / KST로 간주 | **KST로 간주**(naive → `+09:00` 부여), 응답은 항상 `+09:00` | 로봇은 파일명(시간대 없음)에서 시각을 뽑고, 웹 날짜·시간 입력도 보통 오프셋이 없음. 오프셋이 있으면 그대로 존중. 등록 API(R-04) 담당·RPA와 합의 필요 |
| 9 | **[핵심]** `category` 값 표기 | 한글 값 / 영문 코드 / 코드 + 표시명 병행 | **영문 코드(`INQUIRY` 등) API 노출, 한글 표시명은 프론트(또는 별도 매핑 응답)** | URL 쿼리 인코딩·공백(`교육 내용`) 문제 회피, 다른 enum과 표기 일관. 단 GenAI 출력은 한글이므로 적재(R-07)에서 변환 규칙 필요 → GenAI 파트(E-02)·A와 함께 결정. 한글 유지로 결정되면 그대로 따름 |
| 10 | 정체 표시 | 목록 항목에 `is_stale` 계산 필드 / 프론트가 `status_changed_at`으로 계산 | **서버가 `is_stale` 제공** | 기준값 `STALE_THRESHOLD_MIN`이 서버 설정이라 프론트가 알 수 없음. `stale=true` 필터·통계와 같은 판단 함수(R-11) 사용 |
| 11 | 웹 업로드 다중 파일 결과 | 전부 검증 후 업로드, 하나라도 형식 오류면 415 전체 거부 / 파일별 결과 배열(부분 성공) | **검증은 전체 선행(하나라도 실패 시 415, `detail`에 파일 인덱스), Drive 업로드 성공 시 202 `{items: [{filename}]}`** | 부분 성공은 프론트 처리가 복잡. 단 Drive 업로드 도중 실패(503) 시 이미 올라간 파일이 남는 문제는 W-07에서 결정 |
| 12 | 삭제된 건 재삭제 | 404 / 204(멱등) | **404** | §7.2 "없음 또는 소프트 삭제됨 → NOT_FOUND"와 일관 |
| 13 | 식별자 키 이름 | 웹 `id`·로봇 `call_id` 혼용 / 모두 `id` / 모두 `call_id` | **리소스 자체는 `id`, 다른 리소스를 가리키거나 동작 결과는 `call_id`** | 문서 예시(`{call_id}`, `existing_id`)를 바꾸지 않으면서 규칙으로 설명 가능. 단순화를 원하면 로봇 응답까지 `id`로 통일도 가능 |
| 14 | **[핵심]** OpenAPI 공유 방식 | §6.2 A / B / C / D | **C** (`openapi.json` 커밋 + 최신 여부 테스트) + 개발 서버 `/docs` | CI가 아직 없어도 `pytest`만으로 계약 변경이 PR diff에 강제로 드러남. A 리뷰 체계(`features.md:28`)와 맞음 |
| 15 | 운영 `/docs` 비활성 | `DOCS_ENABLED` bool / `APP_ENV` / IP 제한 | **`DOCS_ENABLED`(기본 true, 운영 false → `openapi_url=None`)** | 용도 하나에 설정 하나. `APP_ENV`는 다른 동작 분기를 끌어들이기 쉬움. 공유는 커밋된 파일로 충분하므로 운영 IP 제한 구현 불필요 |
| 16 | 소수 초 | 마이크로초 포함 / 초 단위로 자름 | **초 단위(`timespec="seconds"`)** | 화면 표시·비교에 충분, 문자열이 짧고 일정. 단 정렬·커서에 시간을 쓰지 않으므로(§3.4 `id` 동순위) 정밀도 손실 영향 없음 |
| 17 | 422 `msg` 언어 | Pydantic 영어 그대로 / 한국어 번역 | **영어 그대로**, 화면은 `message`+`loc`+`type`으로 구성 | 번역 표 유지 비용, `type`이 안정적인 기계용 키 |
| 18 | operationId | 기본값 / 함수명(`route.name`) | **함수명**, 라우터 `tags` 지정 | 타입 생성 시 함수 이름이 짧고 읽기 쉬움. 함수명 중복 금지 규칙 필요 |
| 19 | 중복 응답 위치 | 최상위 `{existing_id, status}` / `detail` 안 | **`detail` 안**(§7.2·현재 구현) — `research.md:284`·`input_flow.md` §9 표기 정정 | 에러 형식 통일. RPA 파트에 "`detail.existing_id`, `detail.status`를 읽는다"로 전달 (A 담당 E-04와 함께) |
| 20 | 통계 응답 형태 | §5.1 후보 / 프론트 차트 라이브러리 형식에 맞춤 | **프론트와 화면 시안 기준으로 W-09·W-10 착수 시 확정** | C-03에서는 "목록이 아닌 집계는 `Page`를 쓰지 않고 객체로 감싼다"만 규칙화 |

---

## 9. 다음 단계에 넘길 사실
- 에러 모델·`Page[T]`·`KstDatetime`·공용 `responses` 상수의 위치 후보: `app/schemas/common.py`(`architecture.md:117` "schemas/ ... common").
- 현재 `create_app()`에 라우터가 없어 OpenAPI 테스트는 테스트 전용 라우트로 검증해야 한다(`tests/unit/conftest.py` 패턴).
- 기존 테스트 `test_app_smoke.py`는 `/openapi.json` 200에 의존 → 운영 비활성 설정은 기본값 true여야 유지된다.
- 이 문서의 실측 스크립트는 레포 밖 스크래치에서 실행했으며 레포에 남기지 않았다.
