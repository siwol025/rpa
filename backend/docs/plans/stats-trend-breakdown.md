# 통계 추이·분류 상세 구현 계획 — `GET /api/stats/trend`, `GET /api/stats/breakdown`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-10 통계 — 추이·분류 (P0, Phase 2, 선행 C-04) |
| 작업 브랜치 | `cyj` (기준 `ad131f6`, W-01·W-02 구현 이후) |
| 근거 | `docs/researchs/stats-trend-breakdown.md` v0.1(이하 "리서치"), `api/convention.md` v0.1, `plans/call-list-detail.md`, `app/**`(`schemas/call.py`·`schemas/common.py`·`repositories/call_repository.py`·`services/call_service.py`·`api/deps.py`·`api/web/calls.py`·`main.py`·`core/errors.py`), `app/models/call_record.py`·`analysis.py`, `scripts/export_openapi.py`, `tests/**`, `pyproject.toml` |
| 기준 버전 | FastAPI 0.165.0 / pydantic 2.14.4 / SQLAlchemy 2.0.58 / psycopg 3.3.9 / testcontainers 4.15.0 / PostgreSQL 16 |
| 사전 검증 | 이 문서의 코드·테스트를 `0ebcab0` 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). 이후 커밋 `ad131f6`(상세 `entities` 형식 변경)은 W-10이 쓰는 코드와 겹치지 않음. testcontainers `postgres:16`(Docker)로 통합 테스트까지 실행: **기존 169 + 신규 54(단위 43, 통합 11) = 223 통과, skip 0**. `ruff check`·`ruff format --check`·`mypy .`(66파일) 통과, `openapi.json` 재생성 후 `test_committed_openapi_is_up_to_date` 통과 |

---

## 1. 목표와 범위

### 1.1 목표
1. 웹 대시보드의 기간별 추이 `GET /api/stats/trend`(일·주·월, KST)와 담당자·고객사별 현황 `GET /api/stats/breakdown`(건수 + 유형별 건수)을 규약(`convention.md`)대로 제공한다.
2. 목록(W-01)과 **같은 조건**(소프트 삭제 제외, `call_datetime` 기준 KST 하루 단위 기간, `to` 포함)으로 집계해 목록 `total`·추이 합계·분류 합계가 서로 맞게 한다.
3. PostgreSQL 버킷팅 함정(세션 시간대, `'+09:00'` 부호 반전, GROUP BY 바인드 불일치, 월 단위 `generate_series` 밀림)을 코드 구조와 테스트로 막는다.

### 1.2 포함
- `app/schemas/stats.py`(기간 쿼리·응답 모델), `app/repositories/stats_repository.py`, `app/services/stats_service.py`, `app/api/web/stats.py`
- `app/api/deps.py`(`get_stats_service`), `app/main.py`(라우터 등록)
- `docs/api/openapi.json` 재생성
- 테스트: 단위(항상) + 통합(`integration` 마커, DB 없으면 skip)
- 공용 문서 보완: `convention.md` §4.3·§5.3 각 1줄

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| W-09 요약(`/api/stats/summary`), 정체 건수 | R-11 이후(W-09). `StatsService`에 메서드를 더하는 구조를 가정 |
| W-11 엑셀 | 이후. `StatsService.trend`·`breakdown`을 그대로 호출할 수 있게 응답 모델을 돌려줌 |
| `action_open`(미조치 건수), `uncategorized` 키 | 리서치 #10·#17: 근거 확인 후 호환 추가 |
| 유형별 추이, `category`·`agent`·`client`·`status` 공유 필터 | 리서치 #2·#18: 근거·사용처 없음. 선택 파라미터 추가는 호환 변경 |
| 상위 N + 기타(`limit`) | 리서치 #14: 전체 행. 이후 선택 파라미터로 호환 추가 가능 |
| 기간 검증·KST 경계의 `schemas/common.py` 이동 | §3.3 "공용화 방식" — 이번에는 기존 코드를 재사용만 하고 옮기지 않음 |
| `app/models/*`, `alembic/*` | C-04(A) 소유. 수정하지 않음 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| 통계 기간 쿼리 | `app.schemas.stats.StatsPeriod` (`Depends()`로 `from`·`to` 수신, `call_filter()`로 목록 조건 변환) | W-09 요약, W-11 엑셀 |
| 추이 | `StatsService.trend(period, granularity) -> TrendResponse` | W-11 일·주·월 시트 |
| 분류 | `StatsService.breakdown(period, by) -> BreakdownResponse` | W-11 담당자·고객사 시트 |
| 구간 계산 | `app.services.stats_service.{bucket_start, iter_buckets, bucket_count, MAX_TREND_BUCKETS}` | W-11 차트 범위 |
| 서비스 주입 | `app.api.deps.get_stats_service` | W-09 라우트 |

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 항목 | 실제 (`ad131f6`) | 이 계획의 반영 |
|---|---|---|
| 기간 검증 | `CallListQuery`(`schemas/call.py`)의 `from_`·`to`에 `Query(ge=DATE_MIN, le=DATE_MAX)`, `__post_init__`에서 `from > to` → `AppError(VALIDATION_ERROR, type "date_range")` | `StatsPeriod`가 같은 `DATE_MIN`/`DATE_MAX`를 쓰고, `from > to` 검사는 `CallListQuery`를 만들어 **그대로 재사용** |
| 기간 조건 | `filter_conditions(CallListQuery)`가 삭제 제외 + `call_datetime >= kst_day_start(from)` + `< kst_day_start(to + 1일)`. 유형·키워드 조건이 없으면 `Analysis`·`Transcript`를 참조하지 않음 | 통계 리포지토리가 `filter_conditions(period.call_filter())`를 그대로 사용 |
| 유형 변환 | `CATEGORY_DB_VALUES: dict[Category, str]`(한글 저장 값) | `count(*) FILTER (WHERE analysis.category = '<한글>')` 5개, 응답 키는 `Category` 코드 |
| 라우터 등록 | `main.py`의 `app.include_router(calls.router)` | 다음 줄에 `stats.router` |
| operationId | 라우트 함수 이름(`_operation_id`), 앱 전체 고유(`test_operation_ids_are_unique_in_real_app`) | `get_stats_trend`, `get_stats_breakdown` |
| enum 규약 | `convention.md` §5.3 "값은 영문 대문자 상수" / 정렬 `sort`는 소문자 `Literal` 허용 목록(§4.2) | `granularity`·`by`는 **`sort`와 같은 소문자 `Literal`**(§3.3, §9.4 R1) |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| U1 | trend 범위 상한 | 구간(버킷) 수 **최대 400**, 넘으면 422 `range_too_large`. `from`·`to`가 없으면 데이터의 첫·마지막 구간 기준으로 같은 상한 적용 |
| U2 | breakdown 유형별 건수 | 각 행에 `by_category`(유형 코드 5개, 0 포함): `{by, items: [{name, count, by_category}]}` |
| U3 | 이름 없음 | 담당자·고객사가 NULL이거나 빈(공백만 포함) 문자열이면 `name: null` 한 행으로 묶어 **맨 뒤** |

### 3.2 리서치 §9 권장안 채택
| # | 항목 | 결정 |
|---|---|---|
| 1 | 집계 대상 | 소프트 삭제 제외, **모든 상태**(`FAILED`·처리 중 포함) |
| 2 | trend 응답 | `{granularity, items: [{period: date, count: int}]}` |
| 3 | 빈 구간 | **파이썬에서 0 채움**. 범위 = `from`~`to`(없는 쪽은 데이터의 첫·마지막 구간). 해당 기간 데이터가 **0건이면 `items: []`** |
| 4 | 버킷 계산 | SQL `date_trunc('<unit>', timezone('Asia/Seoul', call_datetime))`, 단위는 허용 목록 → `literal_column`, SELECT·GROUP BY에 같은 라벨 객체 |
| 5 | 주 시작·표기 | 월요일, `period` = 구간 시작일 `YYYY-MM-DD`(월은 1일). 첫·마지막 구간은 부분 구간일 수 있음 |
| 6 | 기간 기본값 | `from`·`to` 둘 다 선택, 없으면 전체 |
| 7 | 범위 상한 | U1 |
| 8 | `granularity` | 기본 `day` |
| 9 | breakdown 응답 | U2 |
| 10 | `action_open` | 보류 |
| 11 | NULL·빈 값 | U3 |
| 12 | 그룹 키 | 저장 값 그대로(빈 값 판정에만 `btrim`). `"김상담 "`은 `"김상담"`과 다른 행 |
| 13 | 정렬 | `count` 내림차순 → `name` 오름차순(파이썬 문자열 비교 = 유니코드 코드 포인트) → null 마지막. 파이썬에서 정렬 |
| 14 | 상위 N | 없음(전체 행) |
| 15 | `by` | **필수**(없으면 422 `missing`) |
| 16 | breakdown의 `call_datetime` NULL | 목록과 같게: 기간이 있으면 제외, 없으면 포함. trend는 항상 제외 → 기간 없을 때 두 합계가 다를 수 있음 |
| 17 | 미분류 | `by_category` 합 ≤ `count`(차이 = 분석 전 건) |
| 18 | 공유 필터 | 기간만 |
| 19 | 공용화 | §3.3 "공용화 방식"(리팩터 최소안) |
| 20 | operationId | `get_stats_trend`, `get_stats_breakdown` |
| 21 | 응답 날짜 타입 | `date`(`YYYY-MM-DD`) |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| **공용화 방식(리팩터 최소안)** | 기존 W-01 코드(`schemas/call.py`, `repositories/call_repository.py`)는 **한 줄도 고치지 않는다.** `StatsPeriod`가 `DATE_MIN`/`DATE_MAX`를 import하고, `call_filter()`가 `CallListQuery(from_, to)`를 만들어 ① `__post_init__`에서 `from > to` 검사(같은 에러 본문)를 ② 리포지토리에서 `filter_conditions`(삭제 제외·KST 경계)를 그대로 재사용 | 규칙이 **복사가 아니라 같은 코드**라 목록·통계 수치가 어긋날 수 없다. W-01 회귀 위험·리뷰 범위가 없다. `schemas/common.py` 이동은 사용처가 셋이 되는 W-09·W-11 때 한 번에(그때 `StatsPeriod`가 바뀌어도 호출부는 같음). 단점: `StatsPeriod` → `CallListQuery` 의존(통계가 목록 스키마를 앎) — §9.4 R2 |
| 기간 받기 | `@dataclass(frozen=True) StatsPeriod` + `Annotated[StatsPeriod, Depends()]` (`PageParams`처럼 독립 의존성) | `granularity`·`by`는 라우트 인자로 따로 받는다. 상속으로 묶으면 필수 `by`가 기본값 있는 필드 뒤에 와 dataclass 순서 제약에 걸림. W-09·W-11이 기간만 그대로 재사용 |
| `granularity`·`by` 타입 | `Literal["day","week","month"]`, `Literal["agent","client"]` | `sort`(§4.2)와 같은 "쿼리 선택 값 = 소문자 허용 목록". 리서치·`research.md`·프론트 초안 값과 같음. §5.3 대문자 enum은 데이터 값(상태·유형)에 적용한다고 규약에 1줄 추가(§5.7) |
| 응답 `granularity`·`by` | 요청 값을 그대로 돌려줌 | 프론트가 단위를 따로 들고 있지 않아도 됨 |
| `by_category` 모델 | `CategoryCounts`(필드 `INQUIRY`…`ETC`, 모두 필수 `int`) | `dict[Category, int]`보다 OpenAPI에 5개 키가 **필수**로 드러남. 필드 = `Category` 전체임을 테스트로 고정 |
| **시간대** | SQL에 `timezone('Asia/Seoul', call_datetime)`를 상수로 넣음. `date_trunc(unit, ts)` 2인자(세션 `TimeZone` 의존)와 `AT TIME ZONE '+09:00'`(POSIX 해석 UTC−9) 금지 | 리서치 §5.1 실측. 한국은 2000년 이후 서머타임이 없어 파이썬 고정 오프셋 `KST`와 결과가 같음 |
| **GROUP BY** | `period_column()`·`dimension_column()`이 **라벨 객체 하나**를 만들고 SELECT·GROUP BY에 같은 객체를 씀. 추이 표현식은 단위·시간대를 `literal_column` 상수로 넣어 바인드 파라미터가 없음 | 별도 생성 시 바인드 이름이 달라 `GroupingError`(리서치 §5.1). 분류 표현식은 `btrim(...) = ''`의 바인드가 하나뿐임을 단위 테스트로 확인 |
| `literal_column` 안전성 | 단위는 `_TRUNC_UNITS[granularity]`(허용 목록 dict)에서만, 시간대는 모듈 상수 | 사용자 입력 문자열이 SQL에 들어가지 않음. `granularity`는 FastAPI가 `Literal`로 먼저 검증 |
| 결과 타입 | `timezone()` 결과는 naive `datetime` → 리포지토리가 `.date()`로 바꿔 `dict[date, int]` 반환 | 응답에 naive 시각을 넣지 않음(`convention.md` §5.1) |
| **빈 구간** | 서비스가 `iter_buckets`로 채움. 월 다음 구간은 `date(y + m // 12, m % 12 + 1, 1)` | SQL `generate_series(.., '1 month')`의 31일 밀림 회피. 항상 1일에서 시작 |
| 범위 검사 시점 | `from`·`to`가 모두 있으면 **조회 전**, 하나라도 없으면 조회 후 데이터 범위로 | 닫힌 기간은 데이터와 무관하게 결정적 422. 열린 기간은 데이터가 2000년 이전 등으로 넓으면 422 → 클라이언트가 기간을 지정 |
| 범위 에러 | 422 `VALIDATION_ERROR`, `detail.errors[0]` = `{loc: ["query","from"], msg: "기간이 너무 깁니다. 구간은 최대 400개입니다", type: "range_too_large"}` | `date_range`와 같은 형식. `msg`에 요청 값 없음(규약 §3.4.3). 열린 기간에서도 같은 `loc` |
| 상한 400 | `MAX_TREND_BUCKETS = 400` (서비스 모듈 상수, 설정 아님) | 일 400일(1년 + 여유), 주 약 7.7년, 월 약 33년. 엑셀(1년 [가정])과 별도 |
| 0건 | 추이·분류 모두 `items: []` | 프론트 빈 상태 판단(`items.length === 0`)과 호환 |
| NULL·빈 이름 | `CASE WHEN btrim(col) = '' THEN NULL ELSE col END`로 그룹 → NULL 그룹 하나 | `btrim(NULL)`은 NULL이라 ELSE로 가서 NULL. 그룹 키는 저장 값 그대로 |
| 유형 집계 | `count(*) FILTER (WHERE analysis.category = :db_value)` 5개, `analysis` outer join | `analysis.call_id` UNIQUE라 행이 늘지 않음. 분석 없는 건은 어느 FILTER에도 안 걸림 |
| 정렬 위치 | 서비스(`sorted(key=(name is None, -count, name or ""))`) | DB 콜레이션과 무관하게 결정적. 행 수가 적음 |
| 서비스 반환 | 응답 Pydantic 모델(`TrendResponse`, `BreakdownResponse`) | 라우터·W-11이 그대로 사용. `model_construct()` 미사용 |
| 라우터 에러 문서화 | 추가 `responses` 없음 | 422·500은 앱 전역 `responses`로 이미 문서화. 404 없음(규약 §2) |
| 라우터 단위 테스트 방식 | 가짜 **리포지토리** + 실제 `StatsService`를 `dependency_overrides[get_stats_service]`에 넣음 | 범위 상한 422가 서비스에 있어 가짜 서비스로는 확인할 수 없음. DB 없이 파라미터 → 서비스 → 422까지 확인. `mypy .`가 테스트도 검사하므로 `cast(StatsRepository, fake)` |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준) | 내용 |
|---|---|---|
| 신규 | `app/schemas/stats.py` | `Granularity`, `BreakdownBy`, `StatsPeriod`, `TrendPoint`, `TrendResponse`, `CategoryCounts`, `BreakdownItem`, `BreakdownResponse` |
| 신규 | `app/repositories/stats_repository.py` | `period_column`, `dimension_column`, `DimensionCount`, `StatsRepository.count_by_period`, `count_by_dimension` |
| 신규 | `app/services/stats_service.py` | `MAX_TREND_BUCKETS`, `bucket_start`, `bucket_count`, `iter_buckets`, `ensure_bucket_limit`, `StatsService.trend`, `breakdown` |
| 신규 | `app/api/web/stats.py` | `router`, `get_stats_trend`, `get_stats_breakdown` |
| 수정 | `app/api/deps.py` | `get_stats_service` |
| 수정 | `app/main.py` | `stats.router` 등록 |
| 수정 | `docs/api/openapi.json` | 재생성(경로 2개, 스키마 5개 추가: `BreakdownItem`, `BreakdownResponse`, `CategoryCounts`, `TrendPoint`, `TrendResponse`) |
| 수정 | `docs/api/convention.md` | §4.3 `range_too_large` 1줄, §5.3 쿼리 선택 값 1줄 |
| 신규 | `tests/unit/test_stats_buckets.py` | 구간 시작·순회·개수·상한 |
| 신규 | `tests/unit/test_stats_schemas.py` | 기간 규칙 재사용, `CategoryCounts` 키, 직렬화 |
| 신규 | `tests/unit/test_stats_query.py` | SQL 컴파일(시간대·상수·바인드 하나) |
| 신규 | `tests/unit/test_stats_service.py` | 가짜 리포지토리로 0 채움·부분 구간·범위 검사·정렬 |
| 신규 | `tests/unit/test_stats_api.py` | 파라미터·422·OpenAPI |
| 신규 | `tests/integration/test_stats_repository.py` | 실제 PostgreSQL 버킷 경계·NULL/빈 이름·유형 집계 |
| 신규 | `tests/integration/test_stats_api.py` | 종단 간 응답 |

- **변경하지 않는 파일**: `app/schemas/call.py`, `app/schemas/common.py`, `app/repositories/call_repository.py`, `app/models/*`, `alembic/*`, `tests/integration/conftest.py`·`factories.py`(그대로 재사용), `pyproject.toml`, `docs/architecture/architecture.md`(§3.2 트리에 `stats` 파일이 이미 있음).
- **새 의존성 없음.**

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_openapi.py` | 변경 없음. `test_committed_openapi_is_up_to_date`가 재생성을 강제, `test_operation_ids_are_unique_in_real_app`이 새 operationId 고유성 확인, `test_every_operation_documents_422_and_500_in_error_format`은 `build_app()` 앱 전체에 적용돼 통계 경로도 검사 |
| 그 밖의 기존 테스트 | 변경 없음(W-01 코드 미수정) |

---

## 5. 모듈별 코드

> 아래 코드는 스크래치 복사본에서 `ruff check`·`ruff format --check`·`mypy .`(strict)와 단위·통합 테스트를 통과한 그대로다.

### 5.1 `app/schemas/stats.py` (신규)
```python
"""통계 추이·분류 API 스키마 (W-10)."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BaseModel

from app.schemas.call import DATE_MAX, DATE_MIN, CallListQuery

# 쿼리 파라미터 선택 값은 `sort`처럼 소문자 허용 목록(Literal)으로 둔다.
Granularity = Literal["day", "week", "month"]
BreakdownBy = Literal["agent", "client"]


# ---------------------------------------------------------------- 요청


@dataclass(frozen=True)
class StatsPeriod:
    """`Depends(StatsPeriod)`로 받는 통계 기간. 규칙은 목록(`CallListQuery`)과 같다."""

    from_: Annotated[date | None, Query(alias="from", ge=DATE_MIN, le=DATE_MAX)] = None
    to: Annotated[date | None, Query(ge=DATE_MIN, le=DATE_MAX)] = None

    def __post_init__(self) -> None:
        self.call_filter()  # from > to 이면 목록과 같은 422(date_range)

    def call_filter(self) -> CallListQuery:
        """목록 필터로 변환한다. 삭제 제외·KST 경계 조건(`filter_conditions`)을 그대로 쓰기 위함."""
        return CallListQuery(from_=self.from_, to=self.to)


# ---------------------------------------------------------------- 응답


class TrendPoint(BaseModel):
    period: date  # 구간 시작일(KST). 주는 월요일, 월은 1일
    count: int


class TrendResponse(BaseModel):
    granularity: Granularity
    items: list[TrendPoint]


class CategoryCounts(BaseModel):
    """유형 코드별 건수. 5개 키가 항상 있다(0 포함). 분석 전인 건은 어느 키에도 없다."""

    INQUIRY: int
    COMPLAINT: int
    SUGGESTION: int
    EDUCATION: int
    ETC: int


class BreakdownItem(BaseModel):
    name: str | None  # 담당자·고객사가 없거나 빈 값이면 null (한 행으로 묶어 맨 뒤)
    count: int
    by_category: CategoryCounts


class BreakdownResponse(BaseModel):
    by: BreakdownBy
    items: list[BreakdownItem]
```

### 5.2 `app/repositories/stats_repository.py` (신규)
```python
"""통계 집계 쿼리. 조건(삭제 제외·기간)은 목록과 같은 `filter_conditions`를 쓴다."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, DateTime, Label, case, func, literal_column, null, select
from sqlalchemy.orm import Session

from app.models import Analysis, CallRecord
from app.repositories.call_repository import filter_conditions
from app.schemas.call import CATEGORY_DB_VALUES, Category
from app.schemas.stats import BreakdownBy, Granularity, StatsPeriod

# date_trunc 단위. SQL에 상수로 들어가므로 이 허용 목록의 값만 쓴다.
_TRUNC_UNITS: dict[Granularity, str] = {"day": "day", "week": "week", "month": "month"}
# '+09:00' 문자열은 POSIX 해석(UTC-9)이라 쓰지 않는다. 세션 TimeZone에도 의존하지 않는다.
_KST_ZONE = "Asia/Seoul"

_DIMENSION_COLUMNS = {
    "agent": CallRecord.agent_name,
    "client": CallRecord.client_company,
}


@dataclass(frozen=True)
class DimensionCount:
    name: str | None
    count: int
    by_category: dict[Category, int]


def period_column(granularity: Granularity) -> Label[Any]:
    """KST 기준 구간 시작 시각(naive). SELECT·GROUP BY에 이 객체 하나를 같이 쓴다."""
    local = func.timezone(literal_column(f"'{_KST_ZONE}'"), CallRecord.call_datetime)
    unit: ColumnElement[str] = literal_column(f"'{_TRUNC_UNITS[granularity]}'")
    return func.date_trunc(unit, local, type_=DateTime()).label("period")


def dimension_column(by: BreakdownBy) -> Label[Any]:
    """담당자·고객사 이름. 공백만 있는 값은 NULL로 합치고, 나머지는 저장 값 그대로 쓴다."""
    column = _DIMENSION_COLUMNS[by]
    return case((func.btrim(column) == "", null()), else_=column).label("name")


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def count_by_period(self, period: StatsPeriod, granularity: Granularity) -> dict[date, int]:
        """값이 있는 구간만 `{구간 시작일: 건수}`. 통화 일시가 없는 건은 제외."""
        bucket = period_column(granularity)
        stmt = (
            select(bucket, func.count())
            .select_from(CallRecord)
            .where(*filter_conditions(period.call_filter()), CallRecord.call_datetime.is_not(None))
            .group_by(bucket)
        )
        return {start.date(): count for start, count in self._session.execute(stmt)}

    def count_by_dimension(self, period: StatsPeriod, by: BreakdownBy) -> list[DimensionCount]:
        name = dimension_column(by)
        by_category = [
            func.count().filter(Analysis.category == CATEGORY_DB_VALUES[code]) for code in Category
        ]
        stmt = (
            select(name, func.count(), *by_category)
            .select_from(CallRecord)
            .outerjoin(Analysis, Analysis.call_id == CallRecord.id)
            .where(*filter_conditions(period.call_filter()))
            .group_by(name)
        )
        return [
            DimensionCount(
                name=row[0],
                count=row[1],
                by_category=dict(zip(Category, row[2:], strict=True)),
            )
            for row in self._session.execute(stmt)
        ]
```
렌더링되는 SQL(PostgreSQL, 실측. 바인드 캐스트 `::TIMESTAMP WITH TIME ZONE`·`::VARCHAR`는 생략)
```sql
-- count_by_period(StatsPeriod(from_=2026-11-01, to=2026-11-30), "week")
SELECT date_trunc('week', timezone('Asia/Seoul', call_record.call_datetime)) AS period, count(*) AS count_1
FROM call_record
WHERE call_record.deleted_at IS NULL
  AND call_record.call_datetime >= %(call_datetime_1)s   -- 2026-11-01 00:00+09:00
  AND call_record.call_datetime < %(call_datetime_2)s    -- 2026-12-01 00:00+09:00
  AND call_record.call_datetime IS NOT NULL
GROUP BY date_trunc('week', timezone('Asia/Seoul', call_record.call_datetime))

-- count_by_dimension(StatsPeriod(), "client")
SELECT CASE WHEN (btrim(call_record.client_company) = %(btrim_1)s) THEN NULL
            ELSE call_record.client_company END AS name,
       count(*) AS count_1,
       count(*) FILTER (WHERE analysis.category = %(category_1)s) AS anon_1,   -- '질의'
       ...                                                                      -- '불만' … '기타 문의'
FROM call_record LEFT OUTER JOIN analysis ON analysis.call_id = call_record.id
WHERE call_record.deleted_at IS NULL
GROUP BY CASE WHEN (btrim(call_record.client_company) = %(btrim_1)s) THEN NULL
              ELSE call_record.client_company END                               -- 같은 바인드 btrim_1
```

### 5.3 `app/services/stats_service.py` (신규)
```python
"""통계 유스케이스 (W-10 추이·분류)."""

from collections.abc import Iterator
from datetime import date, timedelta

from app.core.errors import AppError, ErrorCode
from app.repositories.stats_repository import StatsRepository
from app.schemas.stats import (
    BreakdownBy,
    BreakdownItem,
    BreakdownResponse,
    CategoryCounts,
    Granularity,
    StatsPeriod,
    TrendPoint,
    TrendResponse,
)

MAX_TREND_BUCKETS = 400


def bucket_start(day: date, granularity: Granularity) -> date:
    """그날이 속한 구간의 시작일. 주는 월요일, 월은 1일."""
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def bucket_count(first: date, last: date, granularity: Granularity) -> int:
    """구간 시작일 `first`~`last`(포함) 사이 구간 수."""
    if granularity == "month":
        return (last.year - first.year) * 12 + last.month - first.month + 1
    days = (last - first).days
    return days // 7 + 1 if granularity == "week" else days + 1


def iter_buckets(first: date, last: date, granularity: Granularity) -> Iterator[date]:
    current = first
    while current <= last:
        yield current
        if granularity == "month":
            # 1일에서 출발하므로 월말 밀림(01-31 → 02-28 → 03-28)이 없다.
            current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        else:
            current += timedelta(days=7 if granularity == "week" else 1)


def ensure_bucket_limit(first: date, last: date, granularity: Granularity) -> None:
    if bucket_count(first, last, granularity) > MAX_TREND_BUCKETS:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [
                    {
                        "loc": ["query", "from"],
                        "msg": f"기간이 너무 깁니다. 구간은 최대 {MAX_TREND_BUCKETS}개입니다",
                        "type": "range_too_large",
                    }
                ]
            },
        )


class StatsService:
    def __init__(self, repository: StatsRepository) -> None:
        self._repository = repository

    def trend(self, period: StatsPeriod, granularity: Granularity) -> TrendResponse:
        start = bucket_start(period.from_, granularity) if period.from_ else None
        end = bucket_start(period.to, granularity) if period.to else None
        if start and end:  # 닫힌 기간은 조회 전에 검사
            ensure_bucket_limit(start, end, granularity)
        counts = self._repository.count_by_period(period, granularity)
        if not counts:
            return TrendResponse(granularity=granularity, items=[])
        first = start or min(counts)
        last = end or max(counts)
        ensure_bucket_limit(first, last, granularity)  # 열린 기간은 데이터 범위로 검사
        items = [
            TrendPoint(period=day, count=counts.get(day, 0))
            for day in iter_buckets(first, last, granularity)
        ]
        return TrendResponse(granularity=granularity, items=items)

    def breakdown(self, period: StatsPeriod, by: BreakdownBy) -> BreakdownResponse:
        rows = sorted(
            self._repository.count_by_dimension(period, by),
            key=lambda row: (row.name is None, -row.count, row.name or ""),
        )
        items = [
            BreakdownItem(
                name=row.name,
                count=row.count,
                by_category=CategoryCounts.model_validate(
                    {code.value: n for code, n in row.by_category.items()}
                ),
            )
            for row in rows
        ]
        return BreakdownResponse(by=by, items=items)
```

### 5.4 `app/api/web/stats.py` (신규)
```python
"""웹 통계 API: `GET /api/stats/trend`, `GET /api/stats/breakdown`."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_stats_service
from app.schemas.stats import (
    BreakdownBy,
    BreakdownResponse,
    Granularity,
    StatsPeriod,
    TrendResponse,
)
from app.services.stats_service import StatsService

router = APIRouter(prefix="/api/stats", tags=["stats"])

StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]


@router.get("/trend")
def get_stats_trend(
    period: Annotated[StatsPeriod, Depends()],
    service: StatsServiceDep,
    granularity: Annotated[Granularity, Query()] = "day",
) -> TrendResponse:
    return service.trend(period, granularity)


@router.get("/breakdown")
def get_stats_breakdown(
    by: Annotated[BreakdownBy, Query()],
    period: Annotated[StatsPeriod, Depends()],
    service: StatsServiceDep,
) -> BreakdownResponse:
    return service.breakdown(period, by)
```
- `get_stats_trend`의 `granularity`는 기본값이 있어 시그니처 마지막에 둔다. OpenAPI 파라미터 순서는 `granularity`, `from`, `to`(실측).
- `get_stats_breakdown`의 `by`는 기본값 없음 → 필수(`required: true`).

### 5.5 `app/api/deps.py` (수정)
```diff
 from app.repositories.call_repository import CallRepository
+from app.repositories.stats_repository import StatsRepository
 from app.services.call_service import CallService
+from app.services.stats_service import StatsService
@@ (파일 끝)
 def get_call_service(session: DbSession) -> CallService:
     return CallService(CallRepository(session))
+
+
+def get_stats_service(session: DbSession) -> StatsService:
+    return StatsService(StatsRepository(session))
```

### 5.6 `app/main.py` (수정)
```diff
-from app.api.web import calls
+from app.api.web import calls, stats
@@
     app.include_router(calls.router)
+    app.include_router(stats.router)
```

### 5.7 `docs/api/openapi.json` (재생성)
```bash
cd backend && uv run python -m scripts.export_openapi
```
생성 결과 요점(실측)
- `paths`: `/api/stats/trend`(get, `get_stats_trend`, 태그 `stats`, 응답 200·422·500), `/api/stats/breakdown`(get, `get_stats_breakdown`)
- `trend` 쿼리: `granularity`(enum `day`·`week`·`month`, 기본 `day`), `from`·`to`(date, 선택)
- `breakdown` 쿼리: `by`(enum `agent`·`client`, **필수**), `from`·`to`
- 추가 스키마: `TrendResponse`, `TrendPoint`(`period` `format: date`), `BreakdownResponse`, `BreakdownItem`(`name` nullable), `CategoryCounts`(5개 키 필수, 설명 = 클래스 docstring)
- 재생성은 구현 마지막에 한 번 하고, 다른 미커밋 변경이 섞이지 않았는지 `openapi.json` diff가 통계 경로·스키마 추가뿐인지 확인한다.

### 5.8 공용 문서 보완

`docs/api/convention.md` §4.3 필터 — `from`·`to` 허용 범위 줄 다음에 추가
```markdown
- 통계 추이(`GET /api/stats/trend`)는 구간이 400개를 넘으면 422 `VALIDATION_ERROR`(`loc: ["query", "from"]`, `type: "range_too_large"`). `from`·`to`가 없으면 데이터의 첫·마지막 구간으로 센다.
```
`docs/api/convention.md` §5.3 enum — "값은 영문 대문자 상수다" 줄 다음에 추가
```markdown
- 쿼리 파라미터의 선택 값(`sort`, `granularity`, `by`)은 enum이 아니라 소문자 허용 목록이다(§4.2와 같은 방식, 목록 밖은 422).
```

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 단위 테스트는 DB 없이 **항상** 돈다: 구간 계산, 스키마·직렬화, SQL 생성(PostgreSQL 방언 컴파일만), 서비스(가짜 리포지토리), 라우터·OpenAPI(실제 서비스 + 가짜 리포지토리).
- 통합 테스트(`pytestmark = pytest.mark.integration`)는 기존 `tests/integration/conftest.py`(`db_session`, `api`)·`factories.py`(`make_call`, `make_analysis`)를 그대로 쓴다. 테스트 DB 세션 시간대가 UTC라 시간대 누락 버그가 드러난다.
- 시각은 aware 값(`tzinfo=KST`)으로 직접 넣는다. KST 자정 직전·직후(UTC로는 전날 15시대), 일요일 23:59 KST, 월말 경계를 포함한다. `category`는 DB 저장 값(한글)으로 넣는다.

### 6.2 케이스 목록 (구현 순서)

**1단계 — 구간 계산 (단위, `test_stats_buckets.py`)** → `services/stats_service.py`의 순수 함수
| # | 테스트 | 기대 |
|---|---|---|
| 1 | `test_bucket_start` ×5 | 일=그날, 월요일=그대로, 일요일 → 그 주 월요일, `2026-01-01` → `2025-12-29`(연도 경계), 월 → 1일 |
| 2 | `test_iter_buckets_month_does_not_drift_and_crosses_year` | `2026-11-01`~`2027-03-01` 5개, 매번 1일 |
| 3 | `test_iter_buckets_day_and_week` | 2월 말 → 3월 1일, 주는 7일 간격 |
| 4 | `test_bucket_count` ×4 | 일 1·365, 주 3, 월 4(연도 경계) |
| 5 | `test_bucket_limit_allows_400_and_rejects_401` | 400개 통과, 401개 `AppError` + `range_too_large` 본문 |

**2단계 — 스키마 (단위, `test_stats_schemas.py`)** → `schemas/stats.py`
| # | 테스트 | 기대 |
|---|---|---|
| 6 | `test_period_reuses_call_list_date_rules` | `call_filter()` = `CallListQuery(from_, to)` |
| 7 | `test_period_from_after_to_raises_date_range` | `type: "date_range"` |
| 8 | `test_category_counts_has_every_category_code` | 필드 = `Category` 값 전체 |
| 9 | `test_trend_period_serializes_as_date` | `"period": "2026-11-23"` |
| 10 | `test_breakdown_item_allows_null_name` | `name: null`, `by_category` 5키 |

**3단계 — SQL 조립 (단위, `test_stats_query.py`)** → `repositories/stats_repository.py`의 `period_column`·`dimension_column`
| # | 테스트 | 기대 |
|---|---|---|
| 11 | `test_period_column_truncates_in_asia_seoul` | `date_trunc('week', timezone('Asia/Seoul', call_record.call_datetime))`, `+09:00` 없음 |
| 12 | `test_period_column_has_no_bind_params` | 3단위 모두 `params == {}` |
| 13 | `test_dimension_column_merges_blank_into_null_and_reuses_one_bind` | `CASE WHEN (btrim(...) = ` … `ELSE ... END`, SELECT·GROUP BY 합쳐 바인드 값 `[""]` 하나 |

**4단계 — 서비스 (단위, `test_stats_service.py`, 가짜 리포지토리)** → `StatsService`
| # | 테스트 | 기대 |
|---|---|---|
| 14 | `test_trend_fills_zero_buckets_across_requested_range` | `11-01`~`11-04` 4개, 값 없는 날 0, 리포지토리에 `(period, "day")` 전달 |
| 15 | `test_trend_partial_week_starts_on_monday` | `from` 수요일 → 첫 구간 그 전 월요일(`11-16`) |
| 16 | `test_trend_open_range_uses_first_and_last_data_bucket` | 기간 없음 → 데이터 첫·끝 월 사이 0 채움 |
| 17 | `test_trend_without_data_returns_empty_items` | 기간이 있어도 0건이면 `[]` |
| 18 | `test_trend_closed_range_too_large_is_rejected_before_query` | 401일 → 422, 리포지토리 미호출 / 같은 기간 `week`는 허용 |
| 19 | `test_trend_open_range_too_large_is_rejected_after_query` | `to`만 있고 데이터가 2020~2026 → 422, 조회 1회 |
| 20 | `test_breakdown_sorts_by_count_then_name_with_null_last` | `count` 내림 → `name` 오름 → null 마지막(null 건수가 가장 커도), `by_category` 코드 키·0 포함 |
| 21 | `test_breakdown_without_data_returns_empty_items` | `[]` |

**5단계 — 라우터·OpenAPI (단위, `test_stats_api.py`)** → `api/web/stats.py`, `deps.py`, `main.py`
| # | 테스트 | 기대 |
|---|---|---|
| 22 | `test_trend_defaults` | 200 `{granularity: "day", items: []}`, `StatsPeriod()` 전달 |
| 23 | `test_trend_parses_params` | `from` 별칭·`to`·`granularity=month` 전달 |
| 24 | `test_breakdown_parses_params` | 200 `{by: "agent", items: []}`, `from`만 전달 |
| 25 | `test_invalid_params_return_422` ×9 | `granularity=year`·`DAY`(대문자) → `literal_error` / `from=1999-12-31` → `greater_than_equal` / `to=2101-01-01` → `less_than_equal` / `from>to` → `date_range` / `2026-01-01~2027-02-05` → `range_too_large` / `by` 없음 → `missing` / `by=category` → `literal_error` / breakdown `from>to` → `date_range`. 모두 리포지토리 미호출 |
| 26 | `test_trend_400_days_is_allowed` | `2026-01-01~2027-02-04` → 200 |
| 27 | `test_openapi_trend` | operationId `get_stats_trend`, 태그 `stats`, 파라미터 `from`·`to`·`granularity`, enum·기본값, `from` 선택, `period` `format: date` |
| 28 | `test_openapi_breakdown` | operationId `get_stats_breakdown`, `by` 필수·enum, `CategoryCounts` 5키 필수, `BreakdownItem` 필수 3키 |
| 29 | 기존 `test_committed_openapi_is_up_to_date` | `openapi.json` 재생성 후 통과 |

**6단계 — 리포지토리 (통합, `test_stats_repository.py`)** → `StatsRepository`
| # | 테스트 | 기대 |
|---|---|---|
| 30 | `test_day_bucket_uses_kst_not_session_timezone` | `11-22 23:59:59 KST` → 22일, `11-23 00:00`·`00:30 KST`(UTC 전날) → 23일 |
| 31 | `test_week_bucket_starts_monday_kst` | 일요일 23:59 KST → `11-23` 주, 월요일 00:00 KST → `11-30` 주 |
| 32 | `test_month_bucket_boundary_kst` | `11-30 23:59` → 11월, `12-01 00:00` → 12월 |
| 33 | `test_trend_excludes_deleted_and_missing_datetime_counts_all_statuses` | `FAILED`·`STORED` 둘 다 셈, 삭제·`call_datetime` NULL 제외 |
| 34 | `test_trend_period_filter_is_kst_day_with_to_inclusive` | `from` 전날 23:59:59·`to` 다음날 00:00 제외, `to` 당일 23:59:59 포함 |
| 35 | `test_breakdown_merges_null_and_blank_names` | NULL·`""`·`"   "` → `None` 3건, `"김상담 "`은 별도 행, 삭제 제외 |
| 36 | `test_breakdown_counts_categories_by_code` | 한글 `불만`·`교육 내용` → `COMPLAINT`·`EDUCATION` 각 1, 분석 전 건은 `count`에만 |
| 37 | `test_breakdown_includes_missing_datetime_only_without_period` | 기간 없음 2건, 기간 있음 1건 |

**7단계 — API 종단 간 (통합, `test_stats_api.py`)**
| # | 테스트 | 기대 |
|---|---|---|
| 38 | `test_trend_end_to_end` | 주 단위 3구간 `[1, 0, 1]`, 월요일 00:30 KST가 다음 주로 |
| 39 | `test_trend_open_range_too_large_end_to_end` | 데이터 2024~2026, 기간 없이 `day` → 422 `range_too_large`, `month`는 200 |
| 40 | `test_breakdown_end_to_end` | 고객사 행 + `name: null` 행 마지막, `by_category` 5키 |

### 6.3 케이스 수
| 구분 | 신규 함수 | 실행 수 | 실행 조건 |
|---|---|---|---|
| 단위 (`tests/unit`) | 28 | 43 | 항상 |
| 통합 (`tests/integration`) | 11 | 11 | `TEST_DATABASE_URL` 또는 Docker |

### 6.4 테스트 코드

`tests/unit/test_stats_buckets.py`
```python
from datetime import date

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.stats_service import (
    MAX_TREND_BUCKETS,
    bucket_count,
    bucket_start,
    ensure_bucket_limit,
    iter_buckets,
)


@pytest.mark.parametrize(
    ("day", "granularity", "expected"),
    [
        (date(2026, 11, 25), "day", date(2026, 11, 25)),
        (date(2026, 11, 23), "week", date(2026, 11, 23)),  # 월요일
        (date(2026, 11, 29), "week", date(2026, 11, 23)),  # 일요일 → 그 주 월요일
        (date(2026, 1, 1), "week", date(2025, 12, 29)),  # 연도 경계
        (date(2026, 1, 31), "month", date(2026, 1, 1)),
    ],
)
def test_bucket_start(day: date, granularity: str, expected: date) -> None:
    assert bucket_start(day, granularity) == expected  # type: ignore[arg-type]


def test_iter_buckets_month_does_not_drift_and_crosses_year() -> None:
    months = list(iter_buckets(date(2026, 11, 1), date(2027, 3, 1), "month"))

    assert months == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2027, 1, 1),
        date(2027, 2, 1),
        date(2027, 3, 1),
    ]


def test_iter_buckets_day_and_week() -> None:
    assert list(iter_buckets(date(2026, 2, 27), date(2026, 3, 1), "day")) == [
        date(2026, 2, 27),
        date(2026, 2, 28),
        date(2026, 3, 1),
    ]
    assert list(iter_buckets(date(2026, 11, 16), date(2026, 11, 30), "week")) == [
        date(2026, 11, 16),
        date(2026, 11, 23),
        date(2026, 11, 30),
    ]


@pytest.mark.parametrize(
    ("first", "last", "granularity", "expected"),
    [
        (date(2026, 1, 1), date(2026, 1, 1), "day", 1),
        (date(2026, 1, 1), date(2026, 12, 31), "day", 365),
        (date(2026, 11, 16), date(2026, 11, 30), "week", 3),
        (date(2025, 11, 1), date(2026, 2, 1), "month", 4),
    ],
)
def test_bucket_count(first: date, last: date, granularity: str, expected: int) -> None:
    assert bucket_count(first, last, granularity) == expected  # type: ignore[arg-type]


def test_bucket_limit_allows_400_and_rejects_401() -> None:
    first = date(2026, 1, 1)
    ensure_bucket_limit(first, date(2027, 2, 4), "day")  # 400개

    with pytest.raises(AppError) as exc_info:
        ensure_bucket_limit(first, date(2027, 2, 5), "day")  # 401개

    assert MAX_TREND_BUCKETS == 400
    assert exc_info.value.code is ErrorCode.VALIDATION_ERROR
    assert exc_info.value.detail == {
        "errors": [
            {
                "loc": ["query", "from"],
                "msg": "기간이 너무 깁니다. 구간은 최대 400개입니다",
                "type": "range_too_large",
            }
        ]
    }
```

`tests/unit/test_stats_schemas.py`
```python
from datetime import date

import pytest

from app.core.errors import AppError
from app.schemas.call import CallListQuery, Category
from app.schemas.stats import (
    BreakdownItem,
    CategoryCounts,
    StatsPeriod,
    TrendPoint,
    TrendResponse,
)


def test_period_reuses_call_list_date_rules() -> None:
    period = StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 23))

    assert period.call_filter() == CallListQuery(from_=date(2026, 11, 1), to=date(2026, 11, 23))


def test_period_from_after_to_raises_date_range() -> None:
    with pytest.raises(AppError) as exc_info:
        StatsPeriod(from_=date(2026, 11, 2), to=date(2026, 11, 1))

    assert exc_info.value.detail is not None
    assert exc_info.value.detail["errors"][0]["type"] == "date_range"


def test_category_counts_has_every_category_code() -> None:
    assert set(CategoryCounts.model_fields) == {code.value for code in Category}


def test_trend_period_serializes_as_date() -> None:
    body = TrendResponse(
        granularity="week", items=[TrendPoint(period=date(2026, 11, 23), count=3)]
    ).model_dump(mode="json")

    assert body == {"granularity": "week", "items": [{"period": "2026-11-23", "count": 3}]}


def test_breakdown_item_allows_null_name() -> None:
    zero = dict.fromkeys(CategoryCounts.model_fields, 0)
    item = BreakdownItem(name=None, count=2, by_category=CategoryCounts.model_validate(zero))

    assert item.model_dump(mode="json") == {"name": None, "count": 2, "by_category": zero}
```

`tests/unit/test_stats_query.py`
```python
from sqlalchemy import create_engine, func, select

from app.models import CallRecord
from app.repositories.stats_repository import dimension_column, period_column
from app.schemas.stats import Granularity

_PG = create_engine("postgresql+psycopg://").dialect  # 연결하지 않고 SQL 문자열만 만든다


def test_period_column_truncates_in_asia_seoul() -> None:
    sql = str(period_column("week").compile(dialect=_PG))

    assert sql == "date_trunc('week', timezone('Asia/Seoul', call_record.call_datetime))"
    assert "+09:00" not in sql


def test_period_column_has_no_bind_params() -> None:
    # 단위·시간대가 상수라 SELECT·GROUP BY 표현식이 항상 같게 렌더링된다.
    granularities: list[Granularity] = ["day", "week", "month"]
    for granularity in granularities:
        compiled = period_column(granularity).compile(dialect=_PG)
        assert compiled.params == {}


def test_dimension_column_merges_blank_into_null_and_reuses_one_bind() -> None:
    name = dimension_column("client")
    stmt = select(name, func.count()).select_from(CallRecord).group_by(name)
    compiled = stmt.compile(dialect=_PG)
    sql = str(compiled)

    assert "CASE WHEN (btrim(call_record.client_company) = " in sql
    assert "ELSE call_record.client_company END" in sql
    assert "GROUP BY" in sql
    # 같은 라벨 객체를 쓰면 바인드 파라미터가 하나다 (따로 만들면 GroupingError).
    assert list(compiled.params.values()) == [""]
```

`tests/unit/test_stats_service.py`
```python
from datetime import date
from typing import cast

import pytest

from app.core.errors import AppError
from app.repositories.stats_repository import DimensionCount, StatsRepository
from app.schemas.call import Category
from app.schemas.stats import BreakdownBy, Granularity, StatsPeriod
from app.services.stats_service import StatsService


class FakeStatsRepository:
    def __init__(
        self,
        periods: dict[date, int] | None = None,
        dimensions: list[DimensionCount] | None = None,
    ) -> None:
        self.periods = periods or {}
        self.dimensions = dimensions or []
        self.calls: list[tuple[str, StatsPeriod, str]] = []

    def count_by_period(self, period: StatsPeriod, granularity: Granularity) -> dict[date, int]:
        self.calls.append(("period", period, granularity))
        return self.periods

    def count_by_dimension(self, period: StatsPeriod, by: BreakdownBy) -> list[DimensionCount]:
        self.calls.append(("dimension", period, by))
        return self.dimensions


def _service(repo: FakeStatsRepository) -> StatsService:
    return StatsService(cast(StatsRepository, repo))


def _row(name: str | None, count: int, **by_category: int) -> DimensionCount:
    counts = {code: by_category.get(code.value, 0) for code in Category}
    return DimensionCount(name=name, count=count, by_category=counts)


def test_trend_fills_zero_buckets_across_requested_range() -> None:
    repo = FakeStatsRepository({date(2026, 11, 2): 3})
    period = StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 4))

    body = _service(repo).trend(period, "day").model_dump(mode="json")

    assert body["granularity"] == "day"
    assert body["items"] == [
        {"period": "2026-11-01", "count": 0},
        {"period": "2026-11-02", "count": 3},
        {"period": "2026-11-03", "count": 0},
        {"period": "2026-11-04", "count": 0},
    ]
    assert repo.calls == [("period", period, "day")]


def test_trend_partial_week_starts_on_monday() -> None:
    repo = FakeStatsRepository({date(2026, 11, 23): 2})
    period = StatsPeriod(from_=date(2026, 11, 18), to=date(2026, 11, 25))  # 수 ~ 다음 주 수

    items = _service(repo).trend(period, "week").items

    assert [(i.period, i.count) for i in items] == [
        (date(2026, 11, 16), 0),
        (date(2026, 11, 23), 2),
    ]


def test_trend_open_range_uses_first_and_last_data_bucket() -> None:
    repo = FakeStatsRepository({date(2026, 9, 1): 1, date(2026, 11, 1): 4})

    items = _service(repo).trend(StatsPeriod(), "month").items

    assert [(i.period, i.count) for i in items] == [
        (date(2026, 9, 1), 1),
        (date(2026, 10, 1), 0),
        (date(2026, 11, 1), 4),
    ]


def test_trend_without_data_returns_empty_items() -> None:
    period = StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 30))

    body = _service(FakeStatsRepository()).trend(period, "day")

    assert body.items == []


def test_trend_closed_range_too_large_is_rejected_before_query() -> None:
    repo = FakeStatsRepository()
    period = StatsPeriod(from_=date(2026, 1, 1), to=date(2027, 2, 5))  # 401일

    with pytest.raises(AppError) as exc_info:
        _service(repo).trend(period, "day")

    assert exc_info.value.detail is not None
    assert exc_info.value.detail["errors"][0]["type"] == "range_too_large"
    assert repo.calls == []
    _service(repo).trend(period, "week")  # 같은 기간도 주 단위면 허용


def test_trend_open_range_too_large_is_rejected_after_query() -> None:
    repo = FakeStatsRepository({date(2020, 1, 1): 1, date(2026, 11, 1): 1})

    with pytest.raises(AppError):
        _service(repo).trend(StatsPeriod(to=date(2026, 11, 30)), "day")
    assert len(repo.calls) == 1


def test_breakdown_sorts_by_count_then_name_with_null_last() -> None:
    repo = FakeStatsRepository(
        dimensions=[
            _row(None, 9),
            _row("나상사", 2),
            _row("가상사", 2),
            _row("다상사", 5, COMPLAINT=3, INQUIRY=1),
        ]
    )

    body = _service(repo).breakdown(StatsPeriod(), "client").model_dump(mode="json")

    assert body["by"] == "client"
    assert [(i["name"], i["count"]) for i in body["items"]] == [
        ("다상사", 5),
        ("가상사", 2),
        ("나상사", 2),
        (None, 9),
    ]
    assert body["items"][0]["by_category"] == {
        "INQUIRY": 1,
        "COMPLAINT": 3,
        "SUGGESTION": 0,
        "EDUCATION": 0,
        "ETC": 0,
    }


def test_breakdown_without_data_returns_empty_items() -> None:
    assert _service(FakeStatsRepository()).breakdown(StatsPeriod(), "agent").items == []
```

`tests/unit/test_stats_api.py`
```python
"""라우터 단위 테스트: 실제 StatsService + 가짜 리포지토리로 DB 없이 파라미터·422·OpenAPI 확인."""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_stats_service
from app.repositories.stats_repository import StatsRepository
from app.schemas.stats import StatsPeriod
from app.services.stats_service import StatsService
from tests.unit.test_stats_service import FakeStatsRepository


@pytest.fixture
def repo() -> FakeStatsRepository:
    return FakeStatsRepository()


@pytest.fixture
def api(build_app: Callable[..., FastAPI], repo: FakeStatsRepository) -> Iterator[TestClient]:
    app = build_app()
    app.dependency_overrides[get_stats_service] = lambda: StatsService(cast(StatsRepository, repo))
    with TestClient(app) as client:
        yield client


def test_trend_defaults(api: TestClient, repo: FakeStatsRepository) -> None:
    response = api.get("/api/stats/trend")

    assert response.status_code == 200
    assert response.json() == {"granularity": "day", "items": []}
    assert repo.calls == [("period", StatsPeriod(), "day")]


def test_trend_parses_params(api: TestClient, repo: FakeStatsRepository) -> None:
    params = {"from": "2026-11-01", "to": "2026-11-30", "granularity": "month"}

    assert api.get("/api/stats/trend", params=params).status_code == 200
    assert repo.calls == [
        ("period", StatsPeriod(from_=date(2026, 11, 1), to=date(2026, 11, 30)), "month")
    ]


def test_breakdown_parses_params(api: TestClient, repo: FakeStatsRepository) -> None:
    response = api.get("/api/stats/breakdown", params={"by": "agent", "from": "2026-11-01"})

    assert response.status_code == 200
    assert response.json() == {"by": "agent", "items": []}
    assert repo.calls == [("dimension", StatsPeriod(from_=date(2026, 11, 1)), "agent")]


@pytest.mark.parametrize(
    ("path", "params", "loc", "error_type"),
    [
        ("/api/stats/trend", {"granularity": "year"}, ["query", "granularity"], "literal_error"),
        ("/api/stats/trend", {"granularity": "DAY"}, ["query", "granularity"], "literal_error"),
        ("/api/stats/trend", {"from": "1999-12-31"}, ["query", "from"], "greater_than_equal"),
        ("/api/stats/trend", {"to": "2101-01-01"}, ["query", "to"], "less_than_equal"),
        (
            "/api/stats/trend",
            {"from": "2026-11-02", "to": "2026-11-01"},
            ["query", "from"],
            "date_range",
        ),
        (
            "/api/stats/trend",
            {"from": "2026-01-01", "to": "2027-02-05"},
            ["query", "from"],
            "range_too_large",
        ),
        ("/api/stats/breakdown", {}, ["query", "by"], "missing"),
        ("/api/stats/breakdown", {"by": "category"}, ["query", "by"], "literal_error"),
        (
            "/api/stats/breakdown",
            {"by": "agent", "from": "2026-11-02", "to": "2026-11-01"},
            ["query", "from"],
            "date_range",
        ),
    ],
)
def test_invalid_params_return_422(
    api: TestClient,
    repo: FakeStatsRepository,
    path: str,
    params: dict[str, str],
    loc: list[str],
    error_type: str,
) -> None:
    response = api.get(path, params=params)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert {"loc": loc, "type": error_type} in [
        {"loc": e["loc"], "type": e["type"]} for e in body["detail"]["errors"]
    ]
    assert repo.calls == []


def test_trend_400_days_is_allowed(api: TestClient) -> None:
    params = {"from": "2026-01-01", "to": "2027-02-04"}
    assert api.get("/api/stats/trend", params=params).status_code == 200


# ---------------------------------------------------------------- OpenAPI


@pytest.fixture
def spec(build_app: Callable[..., FastAPI]) -> dict[str, Any]:
    return build_app().openapi()


def test_openapi_trend(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/stats/trend"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}

    assert operation["operationId"] == "get_stats_trend"
    assert operation["tags"] == ["stats"]
    assert set(params) == {"from", "to", "granularity"}
    assert params["granularity"]["schema"]["enum"] == ["day", "week", "month"]
    assert params["granularity"]["schema"]["default"] == "day"
    assert not params["from"]["required"]
    point = spec["components"]["schemas"]["TrendPoint"]["properties"]["period"]
    assert point["format"] == "date"


def test_openapi_breakdown(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/stats/breakdown"]["get"]
    params = {p["name"]: p for p in operation["parameters"]}
    schemas = spec["components"]["schemas"]

    assert operation["operationId"] == "get_stats_breakdown"
    assert operation["tags"] == ["stats"]
    assert params["by"]["required"] is True
    assert params["by"]["schema"]["enum"] == ["agent", "client"]
    assert set(schemas["CategoryCounts"]["required"]) == {
        "INQUIRY", "COMPLAINT", "SUGGESTION", "EDUCATION", "ETC",
    }  # fmt: skip
    assert set(schemas["BreakdownItem"]["required"]) == {"name", "count", "by_category"}
```
- `FakeStatsRepository`는 `test_stats_service.py`에서 import한다(`tests`는 패키지). 다른 파일에서도 쓰게 되면 `tests/unit/conftest.py` 또는 별도 헬퍼로 옮긴다.

`tests/integration/test_stats_repository.py`
```python
from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.repositories.stats_repository import StatsRepository
from app.schemas.call import Category
from app.schemas.common import KST
from app.schemas.stats import StatsPeriod
from tests.integration.factories import make_analysis, make_call

pytestmark = pytest.mark.integration


def _kst(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=KST)


def test_day_bucket_uses_kst_not_session_timezone(db_session: Session) -> None:
    # 00:30 KST = 전날 15:30 UTC. 세션 TimeZone(UTC)으로 자르면 전날로 묶인다.
    make_call(db_session, call_datetime=_kst(2026, 11, 22, 23, 59, 59))
    make_call(db_session, call_datetime=_kst(2026, 11, 23, 0, 0))
    make_call(db_session, call_datetime=_kst(2026, 11, 23, 0, 30))

    counts = StatsRepository(db_session).count_by_period(StatsPeriod(), "day")

    assert counts == {date(2026, 11, 22): 1, date(2026, 11, 23): 2}


def test_week_bucket_starts_monday_kst(db_session: Session) -> None:
    make_call(db_session, call_datetime=_kst(2026, 11, 29, 23, 59))  # 일요일
    make_call(db_session, call_datetime=_kst(2026, 11, 30, 0, 0))  # 월요일

    counts = StatsRepository(db_session).count_by_period(StatsPeriod(), "week")

    assert counts == {date(2026, 11, 23): 1, date(2026, 11, 30): 1}


def test_month_bucket_boundary_kst(db_session: Session) -> None:
    make_call(db_session, call_datetime=_kst(2026, 11, 30, 23, 59))
    make_call(db_session, call_datetime=_kst(2026, 12, 1, 0, 0))

    counts = StatsRepository(db_session).count_by_period(StatsPeriod(), "month")

    assert counts == {date(2026, 11, 1): 1, date(2026, 12, 1): 1}


def test_trend_excludes_deleted_and_missing_datetime_counts_all_statuses(
    db_session: Session,
) -> None:
    day = _kst(2026, 11, 23, 10, 0)
    make_call(db_session, call_datetime=day, status="FAILED")
    make_call(db_session, call_datetime=day, status="STORED")
    make_call(db_session, call_datetime=day, deleted_at=day)
    make_call(db_session, call_datetime=None, metadata_incomplete=True)

    counts = StatsRepository(db_session).count_by_period(StatsPeriod(), "day")

    assert counts == {date(2026, 11, 23): 2}


def test_trend_period_filter_is_kst_day_with_to_inclusive(db_session: Session) -> None:
    make_call(db_session, call_datetime=_kst(2026, 11, 22, 23, 59, 59))
    make_call(db_session, call_datetime=_kst(2026, 11, 24, 23, 59, 59))
    make_call(db_session, call_datetime=_kst(2026, 11, 25, 0, 0))
    period = StatsPeriod(from_=date(2026, 11, 23), to=date(2026, 11, 24))

    counts = StatsRepository(db_session).count_by_period(period, "day")

    assert counts == {date(2026, 11, 24): 1}


def test_breakdown_merges_null_and_blank_names(db_session: Session) -> None:
    make_call(db_session, agent_name="김상담")
    make_call(db_session, agent_name="김상담")
    make_call(db_session, agent_name="김상담 ")  # 저장 값 그대로 (공백 포함은 별도 행)
    make_call(db_session, agent_name=None)
    make_call(db_session, agent_name="")
    make_call(db_session, agent_name="   ")
    make_call(db_session, agent_name="이상담", deleted_at=_kst(2026, 11, 23))

    rows = StatsRepository(db_session).count_by_dimension(StatsPeriod(), "agent")

    assert {row.name: row.count for row in rows} == {"김상담": 2, "김상담 ": 1, None: 3}


def test_breakdown_counts_categories_by_code(db_session: Session) -> None:
    complaint = make_call(db_session, client_company="가나상사")
    make_analysis(db_session, complaint, category="불만")
    education = make_call(db_session, client_company="가나상사")
    make_analysis(db_session, education, category="교육 내용")
    make_call(db_session, client_company="가나상사")  # 분석 전

    (row,) = StatsRepository(db_session).count_by_dimension(StatsPeriod(), "client")

    assert row.name == "가나상사"
    assert row.count == 3
    assert row.by_category == {
        Category.INQUIRY: 0,
        Category.COMPLAINT: 1,
        Category.SUGGESTION: 0,
        Category.EDUCATION: 1,
        Category.ETC: 0,
    }


def test_breakdown_includes_missing_datetime_only_without_period(db_session: Session) -> None:
    make_call(db_session, agent_name="김상담", call_datetime=_kst(2026, 11, 23, 9, 0))
    make_call(db_session, agent_name="김상담", call_datetime=None)
    repo = StatsRepository(db_session)

    (all_time,) = repo.count_by_dimension(StatsPeriod(), "agent")
    (in_period,) = repo.count_by_dimension(StatsPeriod(from_=date(2026, 11, 23)), "agent")

    assert all_time.count == 2
    assert in_period.count == 1
```

`tests/integration/test_stats_api.py`
```python
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.common import KST
from tests.integration.factories import make_analysis, make_call

pytestmark = pytest.mark.integration


def test_trend_end_to_end(api: TestClient, db_session: Session) -> None:
    make_call(db_session, call_datetime=datetime(2026, 11, 18, 9, 0, tzinfo=KST))
    make_call(db_session, call_datetime=datetime(2026, 11, 30, 0, 30, tzinfo=KST))

    params = {"from": "2026-11-16", "to": "2026-12-06", "granularity": "week"}
    response = api.get("/api/stats/trend", params=params)

    assert response.status_code == 200
    assert response.json() == {
        "granularity": "week",
        "items": [
            {"period": "2026-11-16", "count": 1},
            {"period": "2026-11-23", "count": 0},
            {"period": "2026-11-30", "count": 1},
        ],
    }


def test_trend_open_range_too_large_end_to_end(api: TestClient, db_session: Session) -> None:
    make_call(db_session, call_datetime=datetime(2024, 1, 1, 9, 0, tzinfo=KST))
    make_call(db_session, call_datetime=datetime(2026, 11, 23, 9, 0, tzinfo=KST))

    response = api.get("/api/stats/trend")

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["type"] == "range_too_large"
    assert api.get("/api/stats/trend", params={"granularity": "month"}).status_code == 200


def test_breakdown_end_to_end(api: TestClient, db_session: Session) -> None:
    a = make_call(db_session, client_company="가나상사")
    make_analysis(db_session, a, category="불만")
    make_call(db_session, client_company="가나상사")
    make_call(db_session, client_company=None)

    response = api.get("/api/stats/breakdown", params={"by": "client"})

    assert response.status_code == 200
    zero = {"INQUIRY": 0, "COMPLAINT": 0, "SUGGESTION": 0, "EDUCATION": 0, "ETC": 0}
    assert response.json() == {
        "by": "client",
        "items": [
            {"name": "가나상사", "count": 2, "by_category": {**zero, "COMPLAINT": 1}},
            {"name": None, "count": 1, "by_category": zero},
        ],
    }
```

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 1 | #1~5 작성 → `services/stats_service.py`의 `bucket_start`·`bucket_count`·`iter_buckets`·`ensure_bucket_limit`·`MAX_TREND_BUCKETS` (서비스 클래스 전, `Granularity`가 필요하므로 `schemas/stats.py`의 `Literal` 2줄 먼저) | `uv run pytest tests/unit/test_stats_buckets.py` |
| 2 | #6~10 작성 → `schemas/stats.py` 나머지(`StatsPeriod`, 응답 모델) | `uv run pytest tests/unit/test_stats_schemas.py` |
| 3 | #11~13 작성 → `repositories/stats_repository.py`의 `period_column`·`dimension_column` | `uv run pytest tests/unit/test_stats_query.py` |
| 4 | #14~21 작성 → `DimensionCount`, `StatsRepository`(메서드 시그니처), `StatsService` | `uv run pytest tests/unit/test_stats_service.py` |
| 5 | #22~28 작성 → `api/web/stats.py`, `deps.py`, `main.py` | `uv run pytest tests/unit` (이 시점에 `test_committed_openapi_is_up_to_date`만 실패) |
| 6 | `openapi.json` 재생성 | `uv run pytest -m "not integration"` 전부 통과 |
| 7 | #30~40 작성 → `StatsRepository.count_by_period`·`count_by_dimension` 본문 | `uv run pytest -m integration` (Docker 또는 `TEST_DATABASE_URL`) |
| 8 | `convention.md` 2줄 | 리뷰 |
| 9 | 전체 검증(§8) | |

- 커밋은 기능 하나(`feat: 통계 추이·분류 API 추가` 등)로, 코드·테스트·`openapi.json`·`convention.md`를 함께 넣는다.

---

## 8. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (DB 없으면 통합 skip)
uv run pytest -m "not integration"   # 단위만
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
- 통합 테스트는 Docker가 켜져 있으면 testcontainers가 `postgres:16`을 띄운다. 또는 `TEST_DATABASE_URL`(테스트 전용 DB) 지정.
- 기대(사전 검증 시점): 단위 기존 + 43, 통합 기존 18 + 11 전부 통과.

---

## 9. 확인 필요

### 9.1 A (C-04 스키마·모델, R-04·R-07)
| # | 항목 | 현재 / 요청 |
|---|---|---|
| A1 | **유형 저장 값** | 통계도 `CATEGORY_DB_VALUES`(한글)에 의존(`plans/call-list-detail.md` §9.1 A1). 저장 값을 코드로 바꾸면 표만 항등으로 바꾸면 되고 통계 코드는 그대로 |
| A2 | **담당자·고객사 입력 정규화** | 등록(R-04)·보정(W-12) 시 앞뒤 공백 제거, 빈 문자열 → NULL 저장 요청. 지금은 통계가 공백만 있는 값을 NULL로 합치지만 `"김상담 "`처럼 앞뒤 공백이 있는 값은 별도 행이 됨(목록 정확 일치 필터와 맞추기 위해 그룹 키를 바꾸지 않음) |
| A3 | `action_status` NULL 허용 | 이번에는 미조치 집계를 하지 않음. 이후 `action_open` 추가 시 NULL을 미조치로 볼지 영향 |

### 9.2 프론트
| # | 항목 | 내용 |
|---|---|---|
| F1 | **응답 형태** | `trend`: `{granularity, items: [{period: "YYYY-MM-DD", count}]}` / `breakdown`: `{by, items: [{name, count, by_category: {INQUIRY, COMPLAINT, SUGGESTION, EDUCATION, ETC}}]}`. FE-01 응답 예시로 전달 |
| F2 | **`name: null` 행** | 이름 없음(NULL·빈 값) 건이 한 행으로 맨 뒤에 옴. 초안 타입 `name: string`을 `string \| null`로, `key`·담당자/고객사 선택 상자 목록에서 null 처리 필요. 표시 문구("미지정" 등)는 프론트가 정함. null 행은 목록 API로 드릴다운할 방법이 없음(담당자는 `metadata_incomplete=true`로 근사) |
| F3 | **0 채움된 `trend`** | 서버가 구간 사이 0을 채워 보냄(`fillBuckets`는 그대로 무해). `from`·`to`를 주면 그 범위 전체가 채워짐. 기간 내 0건이면 `items: []` |
| F4 | 부분 구간 | 주·월 단위에서 `from`이 구간 중간이면 첫 `period`는 `from`보다 이른 날짜(그 주 월요일·그달 1일)이고 건수는 `from` 이후만. 마지막 구간도 같음 |
| F5 | 새 422 | `range_too_large`(구간 400개 초과, 기간 없이 호출해도 데이터 범위가 넓으면 발생 → 단위를 키우거나 기간 지정), `by` 누락, `granularity`·`by` 대문자 값 |
| F6 | 합계 차이 | 기간 없이 호출하면 `breakdown` 합계에는 통화 일시가 없는 건이 포함되고 `trend` 합계에는 없음. 기간을 주면 둘이 같음 |
| F7 | 선택 상자 목록(FE-09) | 지금처럼 `breakdown` 이름을 쓸 수 있음(전체 행, 상위 N 없음). 기간을 주면 그 기간에 건이 있는 이름만 나옴 — 별도 목록 API가 필요한지 확인 |

### 9.3 RPA (E-05 엑셀 템플릿)
| # | 항목 | 내용 |
|---|---|---|
| X1 | 템플릿 지표 | 담당자별 미조치 건, 고객사별 유형 외 지표가 있으면 `action_open` 등 호환 추가(리서치 #10) |
| X2 | 기간 상한 | 엑셀 최대 기간(1년 [가정])과 추이 상한(400구간)은 별개. W-11에서 일 단위 1년 시트는 상한 안 |

### 9.4 규약·리뷰
| # | 항목 | 내용 |
|---|---|---|
| R1 | **`granularity`·`by` 값 표기** | `convention.md` §5.3은 "enum 값은 영문 대문자"인데 이 계획은 `sort`와 같은 소문자 허용 목록(`day`·`agent`)을 씀(`research.md`·프론트 초안과 일치). §5.8의 규약 1줄 추가로 구분을 명시. 대문자(`DAY`·`AGENT`)로 통일하기로 하면 `Literal` 값·테스트·프론트 초안이 함께 바뀜(공개 전이라 지금이 바꾸기 쉬움) |
| R2 | 공용화 시점 | `StatsPeriod`가 `CallListQuery`를 빌려 쓰는 구조(§3.3). W-09·W-11 착수 시 기간 모델·`kst_day_start`·기간 조건을 `schemas/common.py`(또는 별도 모듈)로 옮길지 결정 |
| R3 | `range_too_large`의 `loc` | 열린 기간(데이터 범위가 원인)에도 `["query","from"]`. 별도 `loc`(예: `["query"]`)가 낫다면 변경 |
| R4 | 빈 이름 판정 차이 | 통계는 PostgreSQL `btrim`(일반 공백만), 목록 필터는 파이썬 `str.strip()`(탭·줄바꿈 포함). 값이 `"\t"`뿐이면 통계에서 별도 이름 행이 됨. §9.1 입력 정규화로 해결하거나 `btrim(col, E' \t\r\n')`로 맞춤 |
| R5 | KST 통합 테스트의 세션 시간대 전제 | `TEST_DATABASE_URL`의 세션 시간대가 KST면 경계 회귀를 못 잡음(SQL 컴파일 단위 테스트가 보완). 필요 시 테스트 시작에 `SET TIME ZONE 'UTC'` |

---

## 10. 구현 시 주의
1. SQL 시간대는 `'Asia/Seoul'`만 쓴다. `func.date_trunc(unit, CallRecord.call_datetime)`(세션 시간대)와 `AT TIME ZONE '+09:00'`(UTC−9)는 쓰지 않는다.
2. `period_column()`·`dimension_column()` 결과를 변수 하나에 담아 SELECT·GROUP BY에 같이 넘긴다. GROUP BY용으로 함수를 다시 호출하면 바인드 이름이 달라 `GroupingError`가 날 수 있다(분류 표현식).
3. `literal_column`에는 허용 목록 dict·모듈 상수만 넣는다. 요청 문자열을 f-string으로 넣지 않는다.
4. `timezone()` 결과는 naive `datetime`이다. `.date()`만 쓰고 `KstDatetime`에 넣지 않는다.
5. 월 다음 구간은 1일에서 계산한다. `timedelta(days=30)`·`generate_series(.., '1 month')`를 쓰지 않는다.
6. 유형 조건은 DB 저장 값(`CATEGORY_DB_VALUES`), 응답 키는 코드. 통합 테스트 데이터의 `category`는 한글.
7. 422 `msg`·`detail`에 요청 값(날짜 등)을 넣지 않는다(규약 §3.4.3).
8. `schemas/call.py`·`repositories/call_repository.py`는 이번에 수정하지 않는다(§3.3). 수정이 필요해지면 W-01 테스트를 함께 돌린다.
9. 라우트를 바꾸면 `openapi.json`을 재생성해 같은 커밋에 넣는다.
