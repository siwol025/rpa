# API 규약 상세 구현 계획 — 에러 모델 · 목록 · 시간 · OpenAPI 공유

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` C-03 API 규약 |
| 근거 | `docs/researchs/api-convention.md` v0.1(이하 "리서치"), `architecture.md` v0.3 §3.2·§4.1·§7·§10.3, `research.md` v0.2 §4.3·§5, `docs/input_flow.md` §6.2·§9, `features.md` v0.2, `plans/common-module.md`, `app/main.py`, `app/core/*.py`, `tests/unit/*.py`, `backend/.venv` 설치 소스 |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / pydantic 2.14.4 / Ruff 0.17.6 |
| 사전 검증 | 이 문서의 코드 스니펫과 테스트를 스크래치 복사본에 그대로 넣어 `pytest`(기존 63 + 신규 35 = 98 통과), `ruff check`, `ruff format --check`, `mypy .`(33파일)·`mypy`(18파일) 통과를 확인함 (레포 코드는 수정하지 않음) |

---

## 1. 목표와 범위

### 1.1 목표
1. 프론트·RPA·백엔드가 함께 보는 **API 규약 문서** 하나를 만든다(필드 표기, 상태 코드, 에러, 목록, 시간, enum, OpenAPI 공유).
2. OpenAPI 문서가 **실제 응답과 같게** 한다. 모든 operation의 422·500이 실제 에러 형식(`{code, message, detail}`)으로 문서화되고, FastAPI 기본 `HTTPValidationError`가 사라진다.
3. W-xx·R-xx가 그대로 가져다 쓰는 공용 스키마를 제공한다: 에러 모델 3종, `Page[T]`, `PageParams`(page·size 쿼리), `KstDatetime`(+09:00 직렬화), `error_responses()`.
4. OpenAPI를 **파일로 커밋**하고, 파일이 코드와 다르면 테스트가 실패하게 한다. 운영에서는 `DOCS_ENABLED=false`로 `/docs`·`/redoc`·`/openapi.json`을 끈다.
5. 중복 등록 409의 기존 건 정보 위치를 문서 전체에서 `detail.existing_id`·`detail.status`로 통일한다.

### 1.2 포함
- 신규 규약 문서 `backend/docs/api/convention.md` (전문은 §6)
- `app/schemas/common.py` 신규, `app/core/errors.py`에 `error_status()` 추가, `app/core/config.py`에 `docs_enabled` 추가, `app/main.py` 연결
- `scripts/export_openapi.py`(+ `scripts/__init__.py`) 신규, `docs/api/openapi.json` 생성·커밋
- `.env.example`에 `DOCS_ENABLED` 추가, `README.md`에 문서·명령 추가
- 공용 문서 정정: `architecture.md`, `research.md`, `features.md`, 레포 루트 `docs/input_flow.md`
- 단위 테스트 (`tests/unit/test_schemas_common.py`, `tests/unit/test_openapi.py` 신규, `tests/unit/test_config.py` 수정)

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| 실제 업무 엔드포인트(`/api/calls` 등) | W-xx·R-xx. 이번에는 테스트 안의 임시 라우트로만 검증 |
| `CallStatus`·`Category` 등 도메인 enum 코드 | C-04/R-02(상태), W-03·R-07(유형). 규약 문서에 값 목록만 정함 |
| 기간 필터(`from`/`to`) → KST 경계 시각 변환 함수, 정렬 파라미터 파서 | 첫 사용처 W-01이 규약대로 구현(쓰는 곳이 하나뿐인 지금 공용 함수로 만들지 않음) |
| 로봇 라우터 공통 401·403 `responses` | R-01이 라우터 생성 시 `error_responses(UNAUTHORIZED, FORBIDDEN_IP)` 지정 |
| 통계 응답 형태(W-09·W-10) | 프론트 화면 시안 기준으로 해당 기능에서 확정 (규약에는 "집계는 `Page`를 쓰지 않고 객체로 감싼다"만) |
| 엑셀 `Content-Disposition` CORS 노출 | W-11 |
| CI에서의 OpenAPI 검사 | CI가 아직 없음. `pytest`가 대신함 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| 목록 응답 | `Page[T]` (`items`, `page`, `size`, `total`) | `def list_calls(...) -> Page[CallListItem]` |
| 페이지 쿼리 | `PageParams` (dataclass, `page`≥1 기본 1, 1≤`size`≤100 기본 20, `offset` 속성) | `params: Annotated[PageParams, Depends()]` → `.offset`, `.size` |
| 시각 필드 | `KstDatetime` (`Annotated[datetime, ...]`) | `call_datetime: KstDatetime \| None` |
| KST 상수 | `KST` (`timezone(timedelta(hours=9))`) | 기간 경계 계산 |
| 엔드포인트 에러 문서화 | `error_responses(*codes: ErrorCode) -> dict[int \| str, dict[str, Any]]` | `@router.post(..., responses=error_responses(ErrorCode.DUPLICATE_FILE, ErrorCode.UNSUPPORTED_MEDIA))` |
| 에러 모델 | `ErrorResponse`, `ValidationErrorResponse`, `DuplicateFileErrorResponse` (+ `ValidationErrorItem`, `ValidationErrorDetail`, `DuplicateFileDetail`) | 문서화·계약 테스트 |
| 코드 → 기본 상태 | `app.core.errors.error_status(code) -> int` | `error_responses` 내부 |
| 문서 노출 설정 | `Settings.docs_enabled` (`DOCS_ENABLED`, 기본 `true`) | 운영 `.env`에 `DOCS_ENABLED=false` |
| OpenAPI 파일 | `docs/api/openapi.json`, 갱신 `uv run python -m scripts.export_openapi` | 스키마를 바꾼 PR에 함께 커밋 |

---

## 2. 결정 사항

### 2.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| U1 | 필드 이름 | 웹·로봇·쿼리·에러 `detail` 모두 **snake_case**, alias 없음 |
| U2 | 중복 409 | 기존 건 정보는 **`detail.existing_id`·`detail.status`**. `research.md`·`input_flow.md`(+ 같은 표기의 `architecture.md` 시퀀스, `features.md` R-04) 정정. RPA는 `detail.existing_id`를 읽는다 |
| U3 | OpenAPI 공유 | `docs/api/openapi.json` 커밋 + 최신 여부 테스트 + 내보내기 명령, 개발 서버 `/docs`, `DOCS_ENABLED`(기본 true, false면 `openapi_url=None`) |
| U4 | `category` | 영문 코드, 한글 표시명은 프론트 매핑 |

### 2.2 리서치 권장안 채택 (리서치 §8)
| # (§8) | 항목 | 결정 |
|---|---|---|
| 2 | 에러 모델 범위 | B안: `ErrorResponse` + `ValidationErrorResponse` + `DuplicateFileErrorResponse` |
| 3 | 기본 정렬·허용 필드 | 기본 `-created_at`, 허용 `call_datetime`·`created_at`·`status_changed_at`, 마지막에 `id` 같은 방향, NULL은 `NULLS LAST` |
| 4 | 다중 값 필터 | 반복 파라미터 `?status=A&status=B` |
| 5 | 기간 필터 | `from`/`to`는 `date`, **KST 하루 단위, `to` 포함**, 기준 `call_datetime` (누락 건은 `metadata_incomplete` 필터로 조회) |
| 6 | 로봇 재처리 대상 조회 | `{"items": [...]}`, 페이지 없음, 서버 상한 100 |
| 7 | `size` 상한 | 100 (기본 20) |
| 8 | 오프셋 없는 시각 입력 | **KST로 간주**, 오프셋이 있으면 존중 |
| 10 | 정체 표시 | 서버가 `is_stale` 제공 (W-01·R-11에서 구현) |
| 11 | 웹 업로드 결과 | 전체 선행 검증(하나라도 실패 시 415, `detail`에 파일 인덱스), 성공 시 202 `{items: [{filename}]}` (세부는 W-07) |
| 12 | 삭제된 건 재삭제 | 404 |
| 13 | 식별자 키 | 리소스 자체는 `id`, 다른 리소스를 가리키거나 동작 결과는 `call_id` |
| 15 | 운영 `/docs` | `DOCS_ENABLED` |
| 16 | 소수 초 | 응답은 초 단위(마이크로초 버림) |
| 17 | 422 `msg` | Pydantic 영어 그대로 |
| 18 | operationId | 라우트 함수 이름, 라우터 `tags` 지정 |
| 20 | 통계 응답 | 해당 기능에서 확정 |

### 2.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| 규약 문서 위치 | **전용 문서 `backend/docs/api/convention.md`**. `architecture.md` §7.2는 요약 예시·에러 코드 표를 유지하고 규약 문서로 링크 | 리서치 §7의 20개 규칙 + 상태 코드 표는 `architecture.md`(구조 문서) 한 절에 넣기에 길고, 프론트·RPA가 볼 계약 자료(`convention.md` + `openapi.json`)를 한 폴더에 모으면 찾기 쉽다. 에러 코드 표는 기존 위치(§7.2) 하나만 유지해 중복을 피한다 |
| OpenAPI 파일 위치 | `backend/docs/api/openapi.json` | 리서치 §6.2 예시 경로. 규약 문서와 같은 폴더 |
| 422·500 문서화 위치 | **앱 단위** `FastAPI(responses=error_responses(VALIDATION_ERROR, INTERNAL_ERROR))` | 한 곳에서 모든 라우트(나중에 추가되는 라우트 포함)의 기본 422를 대체. 라우터마다 붙이면 빠뜨린 라우터에 `HTTPValidationError`가 다시 생긴다. 파라미터 없는 라우트(예: `/health`)에도 422가 문서에 붙는 사소한 부정확은 감수(리서치 §2.4) |
| 엔드포인트 고유 에러 | 데코레이터 `responses=error_responses(...)`. 같은 HTTP 상태의 코드는 한 항목으로 합치고 `description`에 코드 이름을 나열. 상태에 코드가 하나이고 전용 모델이 있으면 그 모델(`VALIDATION_ERROR`→`ValidationErrorResponse`, `DUPLICATE_FILE`→`DuplicateFileErrorResponse`), 아니면 `ErrorResponse` | 20여 개 엔드포인트마다 `{409: {"model": ..., "description": ...}}`를 손으로 쓰지 않게 함. 409(`DUPLICATE_FILE`/`INVALID_STATE_TRANSITION`)처럼 한 상태에 여러 코드가 오는 경우를 정확히 표현 |
| `error_status()` 추가 | `errors.py`에 공개 함수로 `_ERROR_SPECS[code][0]` 반환 | `schemas/common.py`가 비공개 표를 직접 import하지 않게 함. `errors.py` → `schemas` 역방향 import는 만들지 않음(순환 방지) |
| 에러 모델 `code` 타입 | `ErrorCode`(StrEnum) | OpenAPI `ErrorCode` enum 12개 노출 → 프론트 타입 분기 |
| `DuplicateFileDetail.status` 타입 | `str` | 상태 enum(`CallStatus`)이 아직 없음. 상태 enum을 만드는 기능(C-04/R-02)이 `CallStatus`로 바꾼다 |
| 에러 모델과 핸들러 | 핸들러(`errors.py`)는 그대로 dict로 응답을 만든다. 모델은 문서화·계약 테스트용 | 기존 C-02 동작·테스트를 건드리지 않음. 테스트가 "실제 응답 == 모델 왕복"을 확인해 어긋남을 잡는다 |
| 에러 모델 `extra` | 기본값(무시) | `additionalProperties: false`를 문서에 넣으면 "필드 추가 = 호환 변경" 원칙과 충돌 |
| `Page` 문법 | PEP 695 `class Page[T](BaseModel)` | `target-version = "py312"`, Ruff `UP` 규칙과 일치. pydantic 2.14에서 동작 확인. 스키마 이름 `Page_X_`, title `Page[X]` |
| `PageParams` 형태 | `@dataclass(frozen=True)` + `Annotated[int, Query(...)]` 필드, `Depends()`로 주입 | 목록 필터 의존성과 자유롭게 조합 가능, 쿼리 모델(`Annotated[Model, Query()]`)과 달리 다른 쿼리 파라미터와 섞어 써도 문서가 평평하게 나옴(실측: `page`·`size` 두 파라미터, `minimum`/`maximum`/`default` 노출) |
| KST 표현 | 고정 오프셋 `timezone(timedelta(hours=9))` | 한국은 서머타임 없음. `zoneinfo`는 Windows에서 `tzdata`, slim 컨테이너에서 OS 시간대 DB가 필요(리서치 §4.2) |
| `KstDatetime` 구현 | `Annotated[datetime, AfterValidator(_assume_kst), PlainSerializer(_to_kst, return_type=datetime, when_used="json")]` | 입력: naive면 KST 부여. 출력: `astimezone(KST)` + `microsecond=0`. `return_type=datetime`이라 입·출력 스키마 모두 `format: date-time` 유지(`str`이면 사라짐). `when_used="json"`이라 `model_dump()`(파이썬 모드)는 원래 값 유지. 중첩·리스트·Optional에도 적용(실측) |
| naive 값 출력 가드 | 두지 않음 | 모델 검증을 거치면 항상 aware가 된다(`AfterValidator`). `model_construct()`로 검증을 건너뛰지 않는 것을 규약에 적음 |
| 소수 초 처리 | 버림(`replace(microsecond=0)`), 반올림 안 함 | `14:30:05.999` → `14:30:05`. 표시용이며 정렬은 `id` 동순위로 결정 |
| operationId | `generate_unique_id_function=_operation_id`(`route.name`) | 타입 생성 함수명이 `list_calls`처럼 짧아짐. 중복은 테스트(`test_operation_ids_are_unique_in_real_app`)로 막음 |
| `DOCS_ENABLED` | `docs_enabled: bool = True`. false면 `openapi_url=None` → `/docs`·`/redoc`·`/openapi.json`·`/docs/oauth2-redirect` 모두 404(§7.2 형식 `NOT_FOUND`), `app.openapi()`는 계속 동작(실측) | 기본값 true라 인자 없는 `create_app()`의 스모크 테스트 유지 |
| 내보내기 실행 방식 | `uv run python -m scripts.export_openapi` (`backend/`에서) | `[tool.uv] package = false`라 `python scripts/export_openapi.py`로 실행하면 `app`을 import할 수 없다. `-m`은 현재 디렉터리를 `sys.path`에 넣는다 |
| `scripts/__init__.py` | 둔다 | 없으면 `mypy .`가 "Source file found twice under different module names" 오류(실측) |
| 내보내기 설정 | `create_app(Settings(_env_file=None))` | 개발자 `.env`와 무관하게 같은 결과. OpenAPI 내용은 설정 값(CORS·크기 등)에 의존하지 않음 |
| 파일 형식 | `json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True) + "\n"`, `write_text(encoding="utf-8", newline="\n")` | diff 안정화, 한글 설명 가독성, Windows에서도 LF로 씀 |
| 최신 여부 비교 | **파싱한 JSON끼리** 비교 (`json.loads(file) == build_openapi()`) | 레포가 `core.autocrlf=true`라 체크아웃 시 CRLF가 될 수 있음. 텍스트 비교는 줄바꿈·들여쓰기 차이로 거짓 실패 |
| 앱 `version` | `0.1.0` 유지. 비호환 변경 시 올리는 규칙만 규약에 둠 | |

---

## 3. 파일별 변경 목록

| 구분 | 경로 (레포 루트 기준) | 내용 |
|---|---|---|
| 신규 | `backend/app/schemas/common.py` | `KST`, `KstDatetime`, 에러 모델 6개, `error_responses()`, `Page[T]`, `PageParams`, `PAGE_SIZE_DEFAULT`/`PAGE_SIZE_MAX` |
| 수정 | `backend/app/core/errors.py` | `error_status(code)` 추가 (기존 코드 변경 없음) |
| 수정 | `backend/app/core/config.py` | `docs_enabled: bool = True` |
| 수정 | `backend/app/main.py` | `FastAPI(openapi_url=..., responses=..., generate_unique_id_function=...)`, `_operation_id` |
| 신규 | `backend/scripts/__init__.py` | 빈 파일 |
| 신규 | `backend/scripts/export_openapi.py` | `OPENAPI_PATH`, `build_openapi()`, `main()` |
| 신규 | `backend/docs/api/openapi.json` | 내보내기 결과 (현재 라우트가 없어 `paths: {}`) |
| 신규 | `backend/docs/api/convention.md` | API 규약 문서 (§6 전문) |
| 수정 | `backend/.env.example` | `DOCS_ENABLED=true` |
| 수정 | `backend/README.md` | 문서 표에 규약·OpenAPI, 검사 절에 내보내기 명령 |
| 신규 | `backend/tests/unit/test_schemas_common.py` | KstDatetime, Page/PageParams, 에러 모델 = 실제 응답 |
| 신규 | `backend/tests/unit/test_openapi.py` | 422/500 문서화, `error_responses`, operationId, DOCS_ENABLED, 최신 여부 |
| 수정 | `backend/tests/unit/test_config.py` | `DOCS_ENABLED` 환경 변수 격리·기본값·파싱 |
| 수정 | `backend/docs/architecture/architecture.md` | §3.2 트리, §4.1 시퀀스 409 표기, §7.1 `/docs` 행, §7.2 링크·시간 규칙, §10.3 `DOCS_ENABLED` |
| 수정 | `backend/docs/researchs/research.md` | 141행, 284행 409 표기 |
| 수정 | `backend/docs/features/features.md` | 64행(R-04) 409 표기 |
| 수정 | `docs/input_flow.md` | §6.2(177·186행 + 안내 문장), §9(259행) |

새 의존성 없음.

### 3.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_config.py` | **수정**: `_ENV_NAMES`에 `DOCS_ENABLED` 추가(개발자 환경 변수 격리), `test_defaults_without_env`·`test_env_example_is_compatible`에 `docs_enabled is True` 단언 1줄씩 추가, 새 테스트 1개 |
| `tests/unit/test_app_smoke.py` | 변경 없음. 기본 `docs_enabled=True`라 `/openapi.json` 200 유지 |
| `tests/unit/test_errors.py`, `test_cors.py`, `test_request_id.py`, `test_body_size_limit.py`, `test_logging.py` | 변경 없음. 런타임 동작(핸들러·미들웨어)을 바꾸지 않음. `responses`·operationId는 문서에만 영향 |
| `tests/unit/conftest.py` | 변경 없음. 신규 테스트가 기존 `build_app`·`client` 픽스처와 테스트 라우트(`/nope`, `/items`, `/app-error`)를 재사용 |

---

## 4. 모듈별 코드

아래 코드는 스크래치 복사본에서 `ruff check`·`ruff format --check`·`mypy`(strict)·테스트 통과를 확인한 형태다.

### 4.1 `app/schemas/common.py` (신규)
```python
"""API 공통 스키마: 에러 응답, 목록(페이지), 시간(KST) 직렬화."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Query
from pydantic import AfterValidator, BaseModel, PlainSerializer

from app.core.errors import ErrorCode, error_status

KST = timezone(timedelta(hours=9))

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


# ---------------------------------------------------------------- 시간


def _assume_kst(value: datetime) -> datetime:
    # 오프셋 없는 입력은 KST로 본다. 오프셋이 있으면 그대로 둔다.
    return value.replace(tzinfo=KST) if value.tzinfo is None else value


def _to_kst(value: datetime) -> datetime:
    return value.astimezone(KST).replace(microsecond=0)


KstDatetime = Annotated[
    datetime,
    AfterValidator(_assume_kst),
    PlainSerializer(_to_kst, return_type=datetime, when_used="json"),
]
"""요청·응답 모델의 시각 필드 타입. JSON 출력은 항상 초 단위 ISO 8601 `+09:00`."""


# ---------------------------------------------------------------- 에러


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: dict[str, Any] | None


class ValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ValidationErrorDetail(BaseModel):
    errors: list[ValidationErrorItem]


class ValidationErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: ValidationErrorDetail


class DuplicateFileDetail(BaseModel):
    existing_id: int
    status: str


class DuplicateFileErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: DuplicateFileDetail


_DEDICATED_MODELS: dict[ErrorCode, type[BaseModel]] = {
    ErrorCode.VALIDATION_ERROR: ValidationErrorResponse,
    ErrorCode.DUPLICATE_FILE: DuplicateFileErrorResponse,
}


def error_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """라우터·데코레이터 `responses=` 값. 같은 HTTP 상태의 코드는 한 항목으로 묶는다."""
    grouped: dict[int, list[ErrorCode]] = {}
    for code in codes:
        grouped.setdefault(error_status(code), []).append(code)
    responses: dict[int | str, dict[str, Any]] = {}
    for status, group in grouped.items():
        model = _DEDICATED_MODELS.get(group[0], ErrorResponse) if len(group) == 1 else ErrorResponse
        responses[status] = {"model": model, "description": ", ".join(group)}
    return responses


# ---------------------------------------------------------------- 목록


class Page[T](BaseModel):
    items: list[T]
    page: int
    size: int
    total: int


@dataclass(frozen=True)
class PageParams:
    """`Depends(PageParams)`로 받는 `page`·`size` 쿼리."""

    page: Annotated[int, Query(ge=1)] = 1
    size: Annotated[int, Query(ge=1, le=PAGE_SIZE_MAX)] = PAGE_SIZE_DEFAULT

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size
```
실측 메모
- `Page[Row]` 스키마 키 `Page_Row_`, title `Page[Row]`, `required: [items, page, size, total]`.
- `?page=3&size=5`에서 빈 목록을 돌려주면 `{"items": [], "page": 3, "size": 5, "total": 1}` (범위 밖 페이지 = 빈 목록).
- `?size=101` → 422 `{"code": "VALIDATION_ERROR", ..., "detail": {"errors": [{"loc": ["query", "size"], "msg": "Input should be less than or equal to 100", "type": "less_than_equal"}]}}`.
- `"2026-11-23T14:30:05"`(naive)·`"2026-11-23T05:30:05Z"`·`"2026-11-23T14:30:05.999+09:00"` 입력은 모두 `"2026-11-23T14:30:05+09:00"`으로 출력.

### 4.2 `app/core/errors.py` (추가만)
`_STATUS_TO_CODE` 정의 뒤, `class AppError` 앞에 추가한다.
```python
def error_status(code: ErrorCode) -> int:
    """코드의 기본 HTTP 상태 (OpenAPI 문서화용)."""
    return _ERROR_SPECS[code][0]
```

### 4.3 `app/core/config.py`
```diff
     log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
+    docs_enabled: bool = True
```
pydantic bool 파싱: `true/false/1/0/yes/no/on/off`(대소문자 무시).

### 4.4 `app/main.py`
```diff
 from fastapi import FastAPI
 from fastapi.middleware.cors import CORSMiddleware
+from fastapi.routing import APIRoute

 from app.core.config import Settings, get_settings
-from app.core.errors import register_exception_handlers
+from app.core.errors import ErrorCode, register_exception_handlers
 from app.core.logging import configure_logging
 from app.core.middleware import (
     REQUEST_ID_HEADER,
     BodySizeLimitMiddleware,
     RequestIdMiddleware,
     UnhandledErrorMiddleware,
 )
+from app.schemas.common import error_responses
+
+
+def _operation_id(route: APIRoute) -> str:
+    # 프론트 타입 생성기가 함수 이름으로 쓴다. 라우트 함수 이름은 앱 전체에서 고유해야 한다.
+    return route.name


 def create_app(settings: Settings | None = None) -> FastAPI:
     settings = settings or get_settings()
     configure_logging(settings.log_level)

-    app = FastAPI(title="Callcenter AI RPA Backend", version="0.1.0")
+    app = FastAPI(
+        title="Callcenter AI RPA Backend",
+        version="0.1.0",
+        # openapi_url=None이면 /docs·/redoc·/openapi.json이 모두 꺼진다 (app.openapi()는 동작).
+        openapi_url="/openapi.json" if settings.docs_enabled else None,
+        # 모든 operation의 422·500을 실제 에러 형식으로 문서화한다 (FastAPI 기본 422 대체).
+        responses=error_responses(ErrorCode.VALIDATION_ERROR, ErrorCode.INTERNAL_ERROR),
+        generate_unique_id_function=_operation_id,
+    )
     register_exception_handlers(app)
```
나머지(미들웨어 등록, 모듈 수준 `app = create_app()`)는 그대로.

### 4.5 `scripts/export_openapi.py` (신규) + `scripts/__init__.py`(빈 파일)
```python
"""OpenAPI 스키마를 docs/api/openapi.json으로 내보낸다.

실행: cd backend && uv run python -m scripts.export_openapi
"""

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    # 개발자 .env·환경 변수와 무관하게 같은 결과가 나오도록 기본 설정으로 만든다.
    return create_app(Settings(_env_file=None)).openapi()


def main() -> None:
    text = json.dumps(build_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
```
- `pyproject.toml`의 mypy `files = ["app"]`는 바꾸지 않는다. `uv run mypy .`가 `scripts/`·`tests/`까지 검사한다(스크래치에서 33파일 통과).
- 테스트는 `from scripts.export_openapi import OPENAPI_PATH, build_openapi`로 import한다(`tests/__init__.py`가 있어 pytest가 `backend/`를 `sys.path`에 넣음, 실측).

### 4.6 `docs/api/openapi.json` (생성 결과)
구현 마지막에 명령으로 생성한다(손으로 쓰지 않음). 현재 라우트가 없으므로 결과는 아래와 같다.
```json
{
  "info": {
    "title": "Callcenter AI RPA Backend",
    "version": "0.1.0"
  },
  "openapi": "3.1.0",
  "paths": {}
}
```
에러 모델 스키마(`ErrorResponse` 등)는 그것을 쓰는 operation이 생길 때(W-xx·R-xx) `components.schemas`에 나타난다. 그때마다 파일을 다시 생성해 같은 PR에 포함한다.

### 4.7 `.env.example`
```diff
 # --- 로그 ---
 # DEBUG | INFO | WARNING | ERROR
 LOG_LEVEL=INFO
+
+# --- API 문서 ---
+# /docs·/redoc·/openapi.json 노출 여부. 운영에서는 false
+DOCS_ENABLED=true
```

### 4.8 `README.md`
```diff
 | 기능 목록·분담 | `docs/features/features.md` |
+| API 규약 | `docs/api/convention.md` |
+| OpenAPI (팀 간 계약) | `docs/api/openapi.json` |
```
```diff
 uv run pytest                     # 전체
 uv run pytest -m "not integration"   # Docker 없이 실행 가능한 테스트만
 ```
+
+### OpenAPI 갱신
+
+요청·응답 스키마나 라우트를 바꾸면 다시 생성해 같은 커밋에 포함한다(최신이 아니면 `pytest`가 실패한다).
+
+```bash
+uv run python -m scripts.export_openapi
+```
```

---

## 5. 공용 문서 정정 (결정 U2 외)

모두 중립 표현으로 바꾼다. 문서 버전 번호는 이번에 바꾸지 않는다.

### 5.1 409 중복 표기 통일
| 파일 | 위치 | 현재 | 변경 |
|---|---|---|---|
| `backend/docs/researchs/research.md` | 141행 (§4.3 중복) | `해시 중복 시 \`409 {existing_id, status}\`.` | `해시 중복 시 \`409 DUPLICATE_FILE\`(기존 건 정보는 에러 본문의 \`detail.existing_id\`·\`detail.status\`).` |
| 같은 파일 | 284행 (§5.2 표) | `중복 시 \`409 {existing_id, status}\`` | `중복 시 \`409 DUPLICATE_FILE\` (\`detail.existing_id\`, \`detail.status\`)` |
| `docs/input_flow.md` | 177행 (§6.2 표) | `서버 해시 중복 검사 → \`409 {existing_id, status}\` → 아래 표에 따라 처리` | `서버 해시 중복 검사 → \`409 DUPLICATE_FILE\`(\`detail.existing_id\`, \`detail.status\`) → 아래 표에 따라 처리` |
| 같은 파일 | 186행 | `\`existing_id\`로 Queue 추가부터 이어서 진행` | `\`detail.existing_id\`로 Queue 추가부터 이어서 진행` |
| 같은 파일 | "등록 응답별 Dispatcher 처리" 표 바로 위 | — | 문장 추가: `409 응답의 "기존 건 상태"는 에러 본문 \`detail.status\`, 기존 건 ID는 \`detail.existing_id\`에서 읽는다 (에러 형식: \`backend/docs/api/convention.md\` §3).` |
| 같은 파일 | 259행 (§9 표) | `→ \`{call_id}\` / \`409 {existing_id, status}\` (§6.2)` | `→ \`201 {call_id}\` / \`409 DUPLICATE_FILE\` (\`detail.existing_id\`, \`detail.status\`, §6.2)` |
| `backend/docs/architecture/architecture.md` | 172~173행 (§4.1 시퀀스) | `alt 중복 (409 {existing_id, status})` / `A-->>D: 409 {existing_id, status}` | `alt 중복 (409 DUPLICATE_FILE)` / `A-->>D: 409 DUPLICATE_FILE (detail.existing_id, detail.status)` |
| `backend/docs/features/features.md` | 64행 (R-04) | `**해시 중복 시 \`409 {existing_id, status}\`**` | `**해시 중복 시 \`409 DUPLICATE_FILE\`(\`detail.existing_id\`·\`detail.status\`)**` |

`architecture.md` §7.2 예시·표(387·395행)와 `researchs/common-module.md`, `plans/common-module.md`는 이미 `detail` 안이므로 그대로 둔다.

### 5.2 `architecture.md` 기타
§3.2 디렉터리 트리 (`alembic/` 줄 위에 추가)
```diff
 │   └── infra/
 │       ├── storage/             # base.py, local.py, gcs.py
 │       └── inbox/               # base.py, drive.py, local.py(개발용)
+├── scripts/export_openapi.py    # OpenAPI → docs/api/openapi.json
+├── docs/api/                    # convention.md(API 규약), openapi.json(계약, 커밋)
 ├── alembic/                     # 마이그레이션
```
§7.1 표 `/docs` 행
```diff
-| `/docs` | 개발자 | 운영 환경에서는 비활성 또는 IP 제한 | OpenAPI = 팀 간 계약서 |
+| `/docs` | 개발자 | 운영 환경에서는 비활성(`DOCS_ENABLED=false`) | OpenAPI = 팀 간 계약서. 커밋된 `backend/docs/api/openapi.json`으로 공유 |
```
§7.2 첫 줄 바로 아래(코드 블록 위)에 추가
```markdown
세부 규약(필드 표기, 상태 코드, 목록·정렬·기간 필터, 시간·enum 표기, OpenAPI 공유)은 `backend/docs/api/convention.md`를 따른다.
```
§7.2 마지막 목록 첫 항목
```diff
-- 시간은 모두 `TIMESTAMPTZ` 저장, API는 ISO 8601(+09:00) 반환
+- 시간은 모두 `TIMESTAMPTZ` 저장, API는 초 단위 ISO 8601(+09:00) 반환. 오프셋 없는 입력은 KST로 해석
```
§10.3 표 마지막에 추가
```diff
 | `LOG_LEVEL` | 로그 레벨 `DEBUG` \| `INFO`(기본) \| `WARNING` \| `ERROR` |
+| `DOCS_ENABLED` | `/docs`·`/redoc`·`/openapi.json` 노출 (기본 `true`, 운영 `false`) |
```

---

## 6. 규약 문서 전문 — `backend/docs/api/convention.md` (신규)

아래 내용을 그대로 파일로 만든다.

````markdown
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
| GET | `/api/calls/{id}/audio` | 200 / 206(Range) / 302(GCS 서명 URL) | 404 |
| GET | `/api/stats/*` | 200 (집계 객체) | 422 |
| GET | `/api/reports/excel` | 200 (xlsx) | 422 |
| POST | `/api/robot/calls` | 201 `{call_id}` | 409 `DUPLICATE_FILE`, 413, 415, 422 |
| PATCH | `/api/robot/calls/{id}/status` | 200 `{call_id, status}` | 404, 409, 422 |
| GET | `/api/robot/calls?status=RETRY_REQUESTED` | 200 `{items: [{call_id, retry_count}]}` | 422 |
| GET | `/api/robot/calls/{id}/audio` | 200 | 404 |
| PUT | `/api/robot/calls/{id}/transcript`, `.../analysis` | 200 `{call_id, status}` (같은 내용 재전송도 200) | 404, 409, 422 |
| POST | `/api/robot/calls/{id}/logs` | 201 | 404, 409, 422 |

로봇 API는 모두 401(`UNAUTHORIZED`)·403(`FORBIDDEN_IP`)이 추가로 가능하다. 모든 API는 422·500이 가능하다.

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

## 4. 목록

### 4.1 형식
```json
{ "items": [ ... ], "page": 1, "size": 20, "total": 154 }
```
- 코드: `Page[T]` 응답 모델, `PageParams` 쿼리 의존성(`app/schemas/common.py`).
- `page`는 1부터, `size`는 기본 20·최대 100. 범위를 벗어나면 422.
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
- 키워드 `q`는 로그에 남기지 않는다.

## 5. 값

### 5.1 시간
- 응답의 시각은 모두 **초 단위 ISO 8601 `+09:00`** (`"2026-11-23T14:30:05+09:00"`). 소수 초는 버린다.
- 요청의 시각은 오프셋이 있으면 그대로 해석하고, **오프셋이 없으면 KST로 간주**한다(`"2026-11-23T14:30:05"` = `14:30:05+09:00`).
- 날짜만 필요한 값(기간 필터)은 `YYYY-MM-DD`.
- 코드: 요청·응답 모델의 시각 필드는 `KstDatetime`으로 선언한다. 서버 내부·DB는 aware 값만 쓴다(`datetime.now(UTC)`; `datetime.now()`·`utcnow()` 금지). 응답 모델을 `model_construct()`로 만들지 않는다(검증을 건너뛰면 naive 값이 그대로 남는다).

### 5.2 null과 빈 값
- 값이 없는 필드는 생략하지 않고 `null`로 보낸다. 빈 목록은 `[]`.
- 처리 전이라 없는 하위 객체(상세의 `transcript`·`analysis`)는 `null`, 로그는 `[]`.
- PATCH는 보낸 키만 변경한다. `null`은 값 비우기이며 비울 수 있는 필드에만 허용한다(코드: `model_dump(exclude_unset=True)`).

### 5.3 enum
- 값은 영문 대문자 상수다. OpenAPI `enum`으로 노출한다.

| 값 집합 | 값 |
|---|---|
| `status` | `REGISTERED`, `QUEUED`, `STT_DONE`, `STORED`, `NEEDS_REVIEW`, `FAILED`, `RETRY_REQUESTED` |
| `category` | `INQUIRY`(질의), `COMPLAINT`(불만), `SUGGESTION`(건의), `EDUCATION`(교육 내용), `ETC`(기타 문의) — 한글 표시명은 프론트가 매핑 |
| `action_status` | `OPEN`, `DONE` |
| `source_type` | `DRIVE`, `WEB` |
| `speaker` | `AGENT`, `CUSTOMER` |

- 정체(stale)는 상태 값이 아니다. 목록 항목의 `is_stale`(서버 계산)과 `stale` 필터로 표현한다.

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
4. 라우터에 `tags`를 붙인다: 웹 `calls`·`uploads`·`stats`·`reports`, 로봇 `robot`.
5. 프론트 타입 생성 도구 선택은 프론트가 정한다(`openapi.json`은 OpenAPI 3.1).
````

---

## 7. 확인 필요

계획은 아래 권장안대로 진행하고, 합의 결과가 다르면 규약 문서와 해당 기능에서 바꾼다.

| # | 항목 | 확인 대상 | 영향 |
|---|---|---|---|
| 1 | 409 중복 응답에서 기존 건 정보를 **`detail.existing_id`·`detail.status`**로 읽는 것 | RPA 파트, 백엔드 A(R-04·E-04) | Dispatcher의 JSON 파싱 경로. 문서는 이번에 정정 |
| 2 | 오프셋 없는 시각 입력을 KST로 간주 (로봇 등록 `call_datetime`, 웹 PATCH) | RPA 파트, 백엔드 A(R-04) | 오프셋 필수로 바꾸려면 `AwareDatetime` 사용 |
| 3 | `category` 영문 코드 5개(`INQUIRY`, `COMPLAINT`, `SUGGESTION`, `EDUCATION`, `ETC`)와 GenAI 출력(한글) → 코드 변환 위치 | GenAI 파트(E-02), 백엔드 A(R-07), 프론트(표시명) | 적재 시 변환 규칙, 프론트 매핑 표 |
| 4 | 기간 필터 기준(`call_datetime`, KST 하루, `to` 포함)과 통화 일시 누락 건 제외 | 프론트, 통계(W-09~11) | 목록·통계·엑셀 수치 일치 |
| 5 | snake_case 응답·쿼리, 목록 형식·정렬 표기(`sort=-created_at`)·반복 파라미터, 응답 시간 초 단위 | 프론트 | 타입 생성, 쿼리 작성 |
| 6 | 로봇 재처리 대상 조회 `{"items": [{call_id, retry_count}]}`, 페이지 없음 | RPA 파트, 백엔드 A(R-09) | Dispatcher 파싱 |
| 7 | 식별자 키 규칙(리소스 `id`, 참조·동작 결과 `call_id`) | 프론트, RPA | 필드 이름 |
| 8 | 응답에 필드를 추가해도 UiPath JSON 파싱이 깨지지 않는지 | RPA 파트 | "필드 추가 = 호환 변경" 원칙의 전제 |
| 9 | `DuplicateFileDetail.status` 타입을 상태 enum으로 바꾸는 시점 | 백엔드 A (C-04/R-02) | 상태 enum 도입 시 `str` → `CallStatus`, `openapi.json` 재생성 |
| 10 | 운영 배포 `.env`에 `DOCS_ENABLED=false` 포함 | 배포(O-*) | 누락 시 운영에서 `/docs` 노출 |
| 11 | `features.md` R-04 행 정정(409 표기) | 백엔드 A (해당 행 소유) | 표기만 변경, 리뷰 시 확인 |

---

## 8. 테스트 계획 (TDD 순서)

### 8.1 원칙
- 공개 인터페이스로만 검증: HTTP 응답(`TestClient`), `app.openapi()` 결과, 모델의 `model_validate`/`model_dump(mode="json")`.
- 앱은 기존 `build_app` 픽스처(`create_app(Settings(_env_file=None, **overrides))` + 테스트 라우트)로 만든다. 업무 라우트는 만들지 않고 테스트 함수 안에서 임시 라우트를 붙인다.
- `uv run mypy .`가 `tests/`·`scripts/`도 strict로 검사하므로 테스트 함수·픽스처에 타입을 붙인다.
- 테스트 라우트 함수 이름은 테스트 파일 안에서 고유하게 짓는다(operationId 중복 경고 방지).

### 8.2 케이스 목록 (구현 순서)

**단계 1 — Tracer bullet** (`test_schemas_common.py`) · 구현: `schemas/common.py`에 `ErrorResponse`만

| ID | 테스트 | 기대 결과 |
|---|---|---|
| A1 | `test_error_response_matches_not_found_body` — `client.get("/nope")` | `ErrorResponse.model_validate(body).model_dump(mode="json") == body` |

**단계 2 — 에러 모델** (`test_schemas_common.py`) · 구현: `ValidationErrorItem/Detail/Response`, `DuplicateFileDetail/ErrorResponse`

| ID | 테스트 | 기대 결과 |
|---|---|---|
| A2 | `test_validation_error_response_matches_422_body` — `POST /items {"name":"a","count":"many"}` | 모델 왕복 == 실제 본문 |
| A3 | `test_duplicate_file_error_response_matches_409_body` — `GET /app-error` | 모델 왕복 == 실제 본문, `detail.existing_id == 123` |

**단계 3 — KstDatetime** (`test_schemas_common.py`, 테스트 모델 `Event(at: KstDatetime, ended_at: KstDatetime | None = None)`) · 구현: `KST`, `_assume_kst`, `_to_kst`, `KstDatetime`

| ID | 테스트 | 기대 결과 |
|---|---|---|
| A4 | `test_utc_datetime_serialized_as_kst_seconds` — `datetime(2026,11,23,5,30,5,123456,tzinfo=UTC)` | JSON `"2026-11-23T14:30:05+09:00"` (KST 변환 + 마이크로초 버림) |
| A5 | `test_naive_input_is_interpreted_as_kst` — `{"at": "2026-11-23T14:30:05"}` | `event.at == datetime(2026,11,23,14,30,5,tzinfo=KST)` |
| A6 | `test_offset_input_is_respected` — parametrize 3: `...05:30:05Z`, `...14:30:05+09:00`, `...06:30:05+01:00` | 모두 JSON `"2026-11-23T14:30:05+09:00"` |
| A7 | `test_python_mode_dump_keeps_original_value` | `model_dump()["at"]`이 입력한 UTC 값 그대로 (`when_used="json"`) |
| A8 | `test_nested_list_and_none_serialization` — `Wrapper(events: list[Event])` | `{"events": [{"at": "2026-01-01T09:00:00+09:00", "ended_at": None}]}` |
| A9 | `test_kst_datetime_schema_keeps_date_time_format` | validation·serialization 스키마 모두 `{"format": "date-time", "title": "At", "type": "string"}` |

**단계 4 — Page / PageParams** (`test_schemas_common.py`, 픽스처 `page_client`: `build_app()`에 `GET /things -> Page[Item]`, `GET /offset -> {"offset": params.offset}`) · 구현: `Page`, `PageParams`

| ID | 테스트 | 기대 결과 |
|---|---|---|
| A10 | `test_page_params_defaults` — `GET /things` | `{"items": [], "page": 1, "size": 20, "total": 0}` |
| A11 | `test_page_params_offset` — parametrize 3: (1,20)→0, (3,10)→20, (2,100)→100 | `{"offset": 기대값}` (`size=100` 경계 허용 포함) |
| A12 | `test_page_params_out_of_range_rejected` — parametrize 3: `page=0`, `size=0`, `size=101` | 422, `ValidationErrorResponse`로 파싱되고 `loc == ["query", "page"/"size"]` |
| A13 | `test_page_model_requires_all_fields` — `total` 누락 | `pydantic.ValidationError` |

**단계 5 — OpenAPI 에러 문서화·operationId** (`test_openapi.py`, 픽스처 `spec`: `build_app()`에 `GET /rows -> Page[Row]`(PageParams), `DELETE /rows/{row_id}` 204 + `error_responses(NOT_FOUND, INVALID_STATE_TRANSITION)`, `POST /register` 201 + `error_responses(DUPLICATE_FILE)`를 붙인 뒤 `app.openapi()`) · 구현: `error_status`, `error_responses`, `main.py`의 `responses`·`generate_unique_id_function`

| ID | 테스트 | 기대 결과 |
|---|---|---|
| B1 | `test_default_fastapi_validation_schema_is_not_documented` | `components.schemas`에 `HTTPValidationError`·`ValidationError` 없음 |
| B2 | `test_every_operation_documents_422_and_500_in_error_format` | 모든 operation(conftest 라우트 포함)의 422 → `ValidationErrorResponse`, 500 → `ErrorResponse` |
| B3 | `test_error_responses_documents_status_and_codes` — `DELETE /rows/{row_id}` | 응답 키 `{"204","404","409","422","500"}`, 404·409 → `ErrorResponse`, 409 `description == "INVALID_STATE_TRANSITION"` |
| B4 | `test_error_responses_merges_codes_with_same_status` — `error_responses(DUPLICATE_FILE, INVALID_STATE_TRANSITION)` 직접 호출 | 키 `[409]` 하나, `description == "DUPLICATE_FILE, INVALID_STATE_TRANSITION"` |
| B5 | `test_duplicate_file_documented_with_detail_model` — `POST /register` | 409 → `DuplicateFileErrorResponse`, `DuplicateFileDetail.required == {existing_id, status}` |
| B6 | `test_error_code_is_documented_as_enum` | `ErrorCode` 스키마 `enum` 집합 == `set(ErrorCode)` (12개) |
| B7 | `test_page_schema_and_query_params` — `GET /rows` | `page`: `minimum 1`, `default 1` / `size`: `maximum 100`, `default 20` / `Page_Row_.required == {items, page, size, total}` |
| B8 | `test_kst_datetime_documented_as_date_time` | `Row.at.format == "date-time"` |
| B9 | `test_operation_id_is_function_name` | `GET /rows` → `list_rows`, `POST /register` → `register_row` |
| B10 | `test_operation_ids_are_unique_in_real_app` — `create_app(Settings(_env_file=None)).openapi()` | operationId 중복 없음 (업무 라우트가 추가될 때 효력) |

**단계 6 — DOCS_ENABLED** (`test_config.py`, `test_openapi.py`) · 구현: `Settings.docs_enabled`, `main.py`의 `openapi_url`

| ID | 테스트 | 기대 결과 |
|---|---|---|
| C1 | 기존 `test_defaults_without_env`에 단언 추가 | `docs_enabled is True` |
| C2 | 기존 `test_env_example_is_compatible`에 단언 추가 (`.env.example`에 `DOCS_ENABLED=true` 추가 후) | `docs_enabled is True` |
| C3 | `test_docs_enabled_from_env` — parametrize 3: `"false"`→False, `"0"`→False, `"true"`→True | `Settings(_env_file=None).docs_enabled is 기대값` (`_ENV_NAMES`에 `DOCS_ENABLED` 추가로 격리) |
| C4 | `test_docs_enabled_by_default` — `build_app()` | `/docs`, `/redoc`, `/openapi.json` 모두 200 |
| C5 | `test_docs_disabled_hides_docs_but_keeps_schema` — `build_app(docs_enabled=False)` | 세 경로 모두 404 + `code == "NOT_FOUND"`, `app.openapi()["info"]["title"]` 정상 |

**단계 7 — OpenAPI 파일 내보내기** (`test_openapi.py`) · 구현: `scripts/__init__.py`, `scripts/export_openapi.py`, 명령 실행으로 `docs/api/openapi.json` 생성

| ID | 테스트 | 기대 결과 |
|---|---|---|
| D1 | `test_committed_openapi_is_up_to_date` | `json.loads(OPENAPI_PATH.read_text(encoding="utf-8")) == build_openapi()`. 실패 메시지에 재생성 명령 포함. **RED 확인**: 파일 생성 전에는 `FileNotFoundError`로 실패, 생성 후 통과. 추가로 파일의 `version`을 임시로 바꿔 실패하는지 수동 확인 후 되돌린다 |

**단계 8 — 문서** · 테스트 없음: `convention.md` 작성(§6), 공용 문서 정정(§5), `README.md`·`.env.example`(§4.7·4.8)

### 8.3 케이스 수
| 단계 | 케이스 ID | 함수 수 | pytest 실행 수 |
|---|---|---|---|
| 1~4 | A1–A13 (`test_schemas_common.py`) | 13 | 19 |
| 5~7 | B1–B10, C4–C5, D1 (`test_openapi.py`) | 13 | 13 |
| 6 | C3 (`test_config.py` 신규) | 1 | 3 |
| 6 | C1–C2 (기존 테스트 단언 추가) | 0 | 0 |
| 합계 | | **27개 신규 함수** | **신규 35건 → 전체 98건** (기존 63 + 35) |

### 8.4 테스트 코드
스크래치에서 통과를 확인한 전문. TDD 진행 시 단계 순서대로 나눠 추가한다.

`tests/unit/test_schemas_common.py`
```python
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.schemas.common import (
    KST,
    DuplicateFileErrorResponse,
    ErrorResponse,
    KstDatetime,
    Page,
    PageParams,
    ValidationErrorResponse,
)


class Event(BaseModel):
    at: KstDatetime
    ended_at: KstDatetime | None = None


class Item(BaseModel):
    id: int


# ---------------------------------------------------------------- KstDatetime


def test_utc_datetime_serialized_as_kst_seconds() -> None:
    event = Event(at=datetime(2026, 11, 23, 5, 30, 5, 123456, tzinfo=UTC))

    assert event.model_dump(mode="json")["at"] == "2026-11-23T14:30:05+09:00"


def test_naive_input_is_interpreted_as_kst() -> None:
    event = Event.model_validate({"at": "2026-11-23T14:30:05"})

    assert event.at == datetime(2026, 11, 23, 14, 30, 5, tzinfo=KST)


@pytest.mark.parametrize(
    "raw", ["2026-11-23T05:30:05Z", "2026-11-23T14:30:05+09:00", "2026-11-23T06:30:05+01:00"]
)
def test_offset_input_is_respected(raw: str) -> None:
    event = Event.model_validate({"at": raw})

    assert event.model_dump(mode="json")["at"] == "2026-11-23T14:30:05+09:00"


def test_python_mode_dump_keeps_original_value() -> None:
    value = datetime(2026, 11, 23, 5, 30, 5, 123456, tzinfo=UTC)

    assert Event(at=value).model_dump()["at"] == value


def test_nested_list_and_none_serialization() -> None:
    class Wrapper(BaseModel):
        events: list[Event]

    wrapper = Wrapper(events=[Event(at=datetime(2026, 1, 1, tzinfo=UTC))])

    assert wrapper.model_dump(mode="json") == {
        "events": [{"at": "2026-01-01T09:00:00+09:00", "ended_at": None}]
    }


def test_kst_datetime_schema_keeps_date_time_format() -> None:
    expected = {"format": "date-time", "title": "At", "type": "string"}

    assert Event.model_json_schema(mode="validation")["properties"]["at"] == expected
    assert Event.model_json_schema(mode="serialization")["properties"]["at"] == expected


# ---------------------------------------------------------------- Page / PageParams


@pytest.fixture
def page_client(build_app: Callable[..., FastAPI]) -> TestClient:
    app = build_app()

    @app.get("/things")
    def list_things(params: Annotated[PageParams, Depends()]) -> Page[Item]:
        return Page(items=[], page=params.page, size=params.size, total=0)

    @app.get("/offset")
    def get_offset(params: Annotated[PageParams, Depends()]) -> dict[str, int]:
        return {"offset": params.offset}

    return TestClient(app)


def test_page_params_defaults(page_client: TestClient) -> None:
    assert page_client.get("/things").json() == {"items": [], "page": 1, "size": 20, "total": 0}


@pytest.mark.parametrize(("page", "size", "offset"), [(1, 20, 0), (3, 10, 20), (2, 100, 100)])
def test_page_params_offset(page_client: TestClient, page: int, size: int, offset: int) -> None:
    response = page_client.get("/offset", params={"page": page, "size": size})

    assert response.json() == {"offset": offset}


@pytest.mark.parametrize(
    ("query", "loc"), [({"page": 0}, "page"), ({"size": 0}, "size"), ({"size": 101}, "size")]
)
def test_page_params_out_of_range_rejected(
    page_client: TestClient, query: dict[str, int], loc: str
) -> None:
    response = page_client.get("/things", params=query)

    assert response.status_code == 422
    body = ValidationErrorResponse.model_validate(response.json())
    assert [error.loc for error in body.detail.errors] == [["query", loc]]


def test_page_model_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        Page[Item].model_validate({"items": [], "page": 1, "size": 20})


# ---------------------------------------------------------------- 에러 모델 = 실제 응답


def test_error_response_matches_not_found_body(client: TestClient) -> None:
    body = client.get("/nope").json()

    assert ErrorResponse.model_validate(body).model_dump(mode="json") == body


def test_validation_error_response_matches_422_body(client: TestClient) -> None:
    body = client.post("/items", json={"name": "a", "count": "many"}).json()

    assert ValidationErrorResponse.model_validate(body).model_dump(mode="json") == body


def test_duplicate_file_error_response_matches_409_body(client: TestClient) -> None:
    body = client.get("/app-error").json()

    model = DuplicateFileErrorResponse.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert model.detail.existing_id == 123
```

`tests/unit/test_openapi.py`
```python
import json
from collections.abc import Callable
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.main import create_app
from app.schemas.common import KstDatetime, Page, PageParams, error_responses
from scripts.export_openapi import OPENAPI_PATH, build_openapi


class Row(BaseModel):
    id: int
    at: KstDatetime


def _ref(response: dict[str, Any]) -> str:
    ref: str = response["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    app = build_app()

    @app.get("/rows")
    def list_rows(params: Annotated[PageParams, Depends()]) -> Page[Row]:
        return Page(items=[], page=params.page, size=params.size, total=0)

    @app.delete(
        "/rows/{row_id}",
        status_code=204,
        responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_STATE_TRANSITION),
    )
    def delete_row(row_id: int) -> None:
        return None

    @app.post("/register", status_code=201, responses=error_responses(ErrorCode.DUPLICATE_FILE))
    def register_row(row: Row) -> Row:
        return row

    return app.openapi()


def test_default_fastapi_validation_schema_is_not_documented(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_every_operation_documents_422_and_500_in_error_format(spec: dict[str, Any]) -> None:
    for path in spec["paths"].values():
        for operation in path.values():
            assert _ref(operation["responses"]["422"]) == "ValidationErrorResponse"
            assert _ref(operation["responses"]["500"]) == "ErrorResponse"


def test_error_responses_documents_status_and_codes(spec: dict[str, Any]) -> None:
    responses = spec["paths"]["/rows/{row_id}"]["delete"]["responses"]

    assert set(responses) == {"204", "404", "409", "422", "500"}
    assert _ref(responses["404"]) == "ErrorResponse"
    assert _ref(responses["409"]) == "ErrorResponse"
    assert responses["409"]["description"] == "INVALID_STATE_TRANSITION"


def test_error_responses_merges_codes_with_same_status() -> None:
    responses = error_responses(ErrorCode.DUPLICATE_FILE, ErrorCode.INVALID_STATE_TRANSITION)

    assert list(responses) == [409]
    assert responses[409]["description"] == "DUPLICATE_FILE, INVALID_STATE_TRANSITION"


def test_duplicate_file_documented_with_detail_model(spec: dict[str, Any]) -> None:
    responses = spec["paths"]["/register"]["post"]["responses"]
    detail = spec["components"]["schemas"]["DuplicateFileDetail"]

    assert _ref(responses["409"]) == "DuplicateFileErrorResponse"
    assert set(detail["required"]) == {"existing_id", "status"}


def test_error_code_is_documented_as_enum(spec: dict[str, Any]) -> None:
    assert set(spec["components"]["schemas"]["ErrorCode"]["enum"]) == set(ErrorCode)


def test_page_schema_and_query_params(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/rows"]["get"]
    params = {param["name"]: param["schema"] for param in operation["parameters"]}
    page = spec["components"]["schemas"]["Page_Row_"]

    assert params["page"]["minimum"] == 1
    assert params["page"]["default"] == 1
    assert params["size"]["maximum"] == 100
    assert params["size"]["default"] == 20
    assert set(page["required"]) == {"items", "page", "size", "total"}


def test_kst_datetime_documented_as_date_time(spec: dict[str, Any]) -> None:
    at = spec["components"]["schemas"]["Row"]["properties"]["at"]

    assert at["format"] == "date-time"


def test_operation_id_is_function_name(spec: dict[str, Any]) -> None:
    assert spec["paths"]["/rows"]["get"]["operationId"] == "list_rows"
    assert spec["paths"]["/register"]["post"]["operationId"] == "register_row"


def test_docs_enabled_by_default(build_app: Callable[..., FastAPI]) -> None:
    client = TestClient(build_app())

    for url in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(url).status_code == 200


def test_docs_disabled_hides_docs_but_keeps_schema(build_app: Callable[..., FastAPI]) -> None:
    app = build_app(docs_enabled=False)
    client = TestClient(app)

    for url in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(url)
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
    assert app.openapi()["info"]["title"] == "Callcenter AI RPA Backend"


def test_operation_ids_are_unique_in_real_app() -> None:
    spec = create_app(Settings(_env_file=None)).openapi()
    ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]

    assert len(ids) == len(set(ids))


def test_committed_openapi_is_up_to_date() -> None:
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))

    assert committed == build_openapi(), (
        "docs/api/openapi.json이 최신이 아닙니다. "
        "`uv run python -m scripts.export_openapi`로 다시 생성해 함께 커밋하세요."
    )
```

`tests/unit/test_config.py` 변경
```diff
-_ENV_NAMES = ("MAX_UPLOAD_MB", "CORS_ORIGINS", "LOG_LEVEL")
+_ENV_NAMES = ("MAX_UPLOAD_MB", "CORS_ORIGINS", "LOG_LEVEL", "DOCS_ENABLED")
@@ def test_defaults_without_env() -> None:
     assert settings.log_level == "INFO"
+    assert settings.docs_enabled is True
@@ def test_env_example_is_compatible() -> None:
     assert settings.log_level == "INFO"
+    assert settings.docs_enabled is True
@@ (파일 끝)
+
+
+@pytest.mark.parametrize(("value", "expected"), [("false", False), ("0", False), ("true", True)])
+def test_docs_enabled_from_env(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
+    monkeypatch.setenv("DOCS_ENABLED", value)
+
+    assert Settings(_env_file=None).docs_enabled is expected
```

### 8.5 검증 명령
```bash
cd backend
uv run python -m scripts.export_openapi   # docs/api/openapi.json 생성·갱신
uv run pytest                              # 98 passed 기대 (경고 1건: StarletteDeprecationWarning, 기존과 동일)
uv run ruff check .
uv run ruff format --check .
uv run mypy .                              # app·scripts·tests strict
uv run mypy                                # pyproject files=["app"] (pre-commit 훅과 동일 범위)
```
수동 확인
```bash
cd backend
uv run uvicorn app.main:app --port 8000
# 브라우저 http://127.0.0.1:8000/docs → Swagger UI 표시
DOCS_ENABLED=false uv run uvicorn app.main:app --port 8001
curl -i http://127.0.0.1:8001/docs          # 404 {"code":"NOT_FOUND",...}
```

---

## 9. 구현 시 주의
1. `errors.py`가 `app.schemas`를 import하지 않게 한다(순환 import). 방향은 `schemas/common.py` → `core/errors.py`만.
2. `KstDatetime`의 `PlainSerializer`에 `return_type=str`을 쓰지 않는다 — 출력 스키마에서 `format: date-time`이 사라진다.
3. 공통 베이스 모델의 `@field_serializer("*")` 방식으로 바꾸지 않는다 — `list[datetime]` 필드에 적용되지 않는다(리서치 §4.2).
4. 앱 단위 `responses`를 라우터 단위로 옮기지 않는다 — 빠진 라우터에 FastAPI 기본 `HTTPValidationError`가 다시 생긴다(B1이 잡음).
5. `openapi.json`은 손으로 고치지 않는다. 항상 명령으로 생성한다.
6. `scripts/__init__.py`를 지우지 않는다(`mypy .` 모듈 이름 중복 오류).
7. 테스트에서 `from app.main import app`(모듈 수준 앱)을 쓰지 않는다 — 개발자 `.env`를 읽는다.
8. `docs/input_flow.md`는 레포 루트 `docs/`에 있다(`backend/docs/` 아님).
