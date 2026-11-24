# 통계 추이·분류 리서치 — `GET /api/stats/trend`, `GET /api/stats/breakdown`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-10 통계 — 추이·분류 (P0, Phase 2, 선행 C-04) — 관련: W-09(통계 요약), W-11(엑셀), W-01(목록), R-11(정체 감지) |
| 근거 | `docs/prd.md` §1·§5.5·§5.6·§6, `docs/input_flow.md` §7, `features.md` v0.2, `architecture.md` §5·§6·§7·§9, `research.md` §5, `back_stack.md` §3, `api/convention.md` v0.1, `researchs/api-convention.md`, `plans/api-convention.md`, `researchs/call-list-detail.md`, `plans/call-list-detail.md`, `backend/app/**`, `backend/tests/**`, `alembic/versions/2026_11_24_1153-8c600ef00817_init_schema.py`, 원격 브랜치 `origin/front`(프론트 초안, 미병합) |
| 검증 방법 | 문서·코드 정독. 임시 `postgres:16`(16.16) 컨테이너에 C-04 모델로 테이블을 만들고 버킷팅·GROUP BY·NULL 처리 SQL을 실측(레포 코드는 수정하지 않음, 컨테이너는 삭제함) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다.

---

## 0. 요약 (핵심 발견)

1. **요구사항 원문은 "건수" 중심이다.** WEB-01 "유형별 통계, 기간별 추이, 담당자/고객사별 현황"(`prd.md:167`). 건수 외 지표 근거는 엑셀 XL-02 "담당자별 처리 건수, 고객사별 불만/건의 현황, 미조치 건"(`prd.md:158`)뿐이다. W-10은 추이(`trend`)와 담당자·고객사별(`breakdown`), 유형별은 W-09(`summary.by_category`)가 맡는다(`features.md:86-87`).
2. **집계 기준 시각과 기간 규칙은 이미 규약으로 확정돼 있다.** `call_datetime` 기준, `from`·`to`는 KST 하루 단위·`to` 포함, `call_datetime`이 없는 건은 기간 필터에 걸리지 않음, "목록·통계·엑셀이 같은 기준"(`convention.md:122`). 허용 범위 2000-01-01~2100-12-31, `from > to`는 422 `date_range`(`convention.md:123-124`).
3. **프론트 초안(`origin/front`)이 응답 형태를 이미 가정한다.** `trend` → `{items: [{period: "YYYY-MM-DD", count}]}`(주는 월요일, 월은 1일), `breakdown` → `{items: [{name, count}]}`, 파라미터는 `from`·`to`(둘 다 선택)·`granularity`·`by`. 목(mock)은 빈 구간을 돌려주지 않고 프론트가 첫~마지막 구간 사이만 0으로 채운다(`frontend/src/lib/trend.ts` `fillBuckets`). 담당자·고객사가 null인 건은 목에서 빠진다. 프론트는 담당자·고객사 선택 상자 목록을 이 `breakdown` 응답의 이름으로 채운다(`features_frontend.md` FE-09).
4. **PostgreSQL 버킷팅 함정 3가지를 실측으로 확인했다.**
   - `date_trunc('day', timestamptz)`는 **세션 `TimeZone`(공식 이미지 기본 `Etc/UTC`)** 기준이다. `2026-11-23 00:30 KST`가 `2026-11-22`로 묶인다 → 시간대를 반드시 명시해야 한다.
   - `AT TIME ZONE '+09:00'`(문자열)은 POSIX 해석이라 **UTC−9**가 된다(`15:30Z` → `06:30`). `'Asia/Seoul'` 또는 `INTERVAL '+09:00'`을 써야 한다.
   - SQLAlchemy에서 `func.date_trunc("day", ...)`를 SELECT와 GROUP BY에 **서로 다른 객체로** 만들면 바인드 파라미터가 따로 생겨 `GroupingError`가 난다. **같은 표현식 객체(라벨)**를 재사용하면 통과한다.
5. **`generate_series(..., interval '1 month')`는 31일 시작이면 날짜가 밀린다**(`01-31 → 02-28 → 03-28`). 빈 구간 채우기는 구간 시작일로 정규화한 뒤 하거나 파이썬에서 하는 편이 안전하다.
6. **유형 저장 값은 한글, API는 영문 코드다.** 유형별 수치를 내려면 `CATEGORY_DB_VALUES`(`app/schemas/call.py:65-71`)로 변환해야 한다(A 확인 대기: `plans/call-list-detail.md` §9.1 A1).
7. **`client_company`는 메타데이터가 "완전"해도 NULL일 수 있다.** `metadata_incomplete` 해제 조건은 담당자·통화 일시만이다(`architecture.md` §5 표, `features.md:89`). 고객사별 집계에는 "미지정" 처리 방식이 꼭 필요하다.
8. **재사용 가능한 기존 코드**: `filter_conditions(query)`(소프트 삭제 + 기간 + 기타 필터, `app/repositories/call_repository.py:39-66`), `kst_day_start(day)`(`:23-25`), `DATE_MIN`/`DATE_MAX`·`from > to` 검사(`app/schemas/call.py:83-84`, `:113-126`), `KST`(`app/schemas/common.py:12`). 기간 필터·KST 경계 함수는 "W-09·W-11이 쓸 때 공용화"로 미뤄져 있었다(`plans/call-list-detail.md` §1.4).
9. 데이터 규모(일 수십~백여 건 [가정], `prd.md:248`)에서는 집계가 수만 행 이하다. `ix_call_dt`(`call_datetime`) 인덱스로 기간 범위를 거르면 성능 기준(대시보드 2초, `prd.md:247`)에 여유가 있다. 별도 표현식 인덱스·집계 테이블은 필요 없다.

---

## 1. 현재 상태

### 1.1 코드 구조 (W-01·W-02 구현 후, 브랜치 `cyj`)
| 위치 | 내용 | W-10과의 관계 |
|---|---|---|
| `app/main.py:45` | `app.include_router(calls.router)` — 라우터는 기능별로 여기 등록 | `stats.router` 추가 위치 |
| `app/api/deps.py` | `get_db`(요청당 세션), `DbSession`, `get_call_service` | `get_stats_service` 추가 위치 |
| `app/api/web/calls.py` | `APIRouter(prefix="/api/calls", tags=["calls"])`, `Annotated[CallListQuery, Depends()]`로 쿼리 수신, 서비스 `Depends` 주입, 반환 타입 = 응답 모델 | 같은 형태로 `app/api/web/stats.py` |
| `app/schemas/call.py` | API enum(`Category` 등), `CATEGORY_DB_VALUES`·`CategoryOut`, `DATE_MIN`/`DATE_MAX`, `CallListQuery`(frozen dataclass + `__post_init__`에서 `from > to` → `AppError`) | 유형 변환·기간 검증 재사용 대상 |
| `app/schemas/common.py` | `KST`, `KstDatetime`, `Page[T]`, `PageParams`, `error_responses()` | 통계는 `Page`를 쓰지 않음(`convention.md:61`) |
| `app/services/call_service.py` | 생성자 `CallService(repository)`, 리포지토리 결과 → `model_validate`로 응답 모델 | `StatsService(StatsRepository)` 같은 구성 |
| `app/repositories/call_repository.py` | `kst_day_start`, `order_by_clause`, `filter_conditions`, `_filtered`(analysis outer join + 조건), `CallRepository` | 기간·삭제 조건 재사용 |
| `app/core/errors.py` | `ErrorCode`, `AppError(code, message, detail)` | 422 커스텀 검증 |
| `app/core/config.py` | `Settings`(설정 추가 시 필드 추가) | 통계용 설정은 현재 없음 |
| `app/models/*` | C-04 모델(A 소유, 수정하지 않음) | §3 |
| `docs/api/openapi.json` | 커밋된 계약 파일, `tests/unit/test_openapi.py`가 최신 여부 검사 | 라우트 추가 시 재생성 필수(`convention.md` §7.1) |

### 1.2 테스트 구조
| 위치 | 패턴 |
|---|---|
| `tests/unit/conftest.py` | `build_app()` → `create_app(Settings(_env_file=None))` + 테스트 라우트 |
| `tests/unit/test_calls_api.py` | 가짜 서비스(`FakeCallService`)를 `app.dependency_overrides[get_call_service]`로 바꿔 DB 없이 파라미터 파싱·422·응답 형식·OpenAPI 확인 |
| `tests/unit/test_call_query.py` | `create_engine("postgresql+psycopg://").dialect`로 **연결 없이** 조건식을 컴파일해 SQL 문자열·파라미터 확인 |
| `tests/unit/test_call_enums.py` | API enum ↔ 모델 CHECK 상수, `CATEGORY_DB_VALUES` ↔ `CATEGORIES` 일치 |
| `tests/integration/conftest.py` | `TEST_DATABASE_URL` → testcontainers `postgres:16` → skip. `create_schema(url)`는 `Config()`+`downgrade base`→`upgrade head`. `db_session`은 테스트마다 바깥 트랜잭션 + `create_savepoint` 후 롤백. `api` 픽스처는 `dependency_overrides[get_db]` |
| `tests/integration/factories.py` | `make_call`, `make_analysis`(`category`는 DB 한글 값), `make_transcript`, `make_log` |
| `tests/integration/test_call_repository.py`, `test_calls_api.py` | `pytestmark = pytest.mark.integration`, 시각은 aware 값으로 직접 지정(`datetime(..., tzinfo=KST)`) |
| `pyproject.toml` | `--strict-markers`, 마커 `integration`. `mypy --strict`(대상 `app`), Ruff `line-length = 100` |

주의: 한 테스트 안의 `now()`는 같다(트랜잭션 시작 시각). 통계 테스트도 `call_datetime`을 직접 넣어야 한다.

### 1.3 환경
- 이 PC에 **Docker 29.9.3이 설치돼 있다**(이전 리서치 시점과 달라짐). `postgres:16` 이미지(16.16, Debian, `TimeZone = Etc/UTC`)로 실측했다. 따라서 testcontainers 통합 테스트를 로컬에서 실행할 수 있다.

---

## 2. 요구사항 정리

### 2.1 원문
| 출처 | 원문 |
|---|---|
| PRD WEB-01 (`prd.md:167`, P0) | "통계 대시보드: 유형별 통계, 기간별 추이, 담당자/고객사별 현황" |
| PRD XL-02 (`prd.md:158`, P0, 엑셀) | "포함 지표 예: 기간별 총 상담 건수, 5대 유형별 건수·비율, 담당자별 처리 건수, 고객사별 불만/건의 현황, 미조치 건" |
| PRD XL-04 (`prd.md:160`, P1) | "일/주/월 단위 보고서를 자동 생성한다" |
| PRD 사용자 (`prd.md:51`) | 관리자/팀장: "유형별 통계, 불만·건의 추적, 엑셀 보고서 다운로드" |
| PRD 배경 (`prd.md:26`) | "유형별 추이·불만 현황 파악 및 보고에 추가 시간 소요" |
| PRD 규모·성능 (`prd.md:247-248`) | 대시보드 조회 응답 2초 이내 / 담당자 3명, 일 수십~백여 건 [가정] |
| PRD API (`prd.md:225-226`) | `GET /api/stats/trend` 기간별 추이, `GET /api/stats/breakdown` 담당자별·고객사별 현황 |
| `research.md:275-276` | `trend`: `granularity=day\|week\|month`, `breakdown`: `by=agent\|client` |
| `features.md:87` | W-10: "일/주/월 추이, 담당자별·고객사별 집계", 선행 C-04 |
| `features.md:86` | W-09: "총 건수, 유형별, 미조치, 검토 필요, 메타데이터 확인 필요, 실패, 정체(R-11 사용)" |
| `features.md:91` | W-11: "RPA 파트 템플릿에 데이터 시트 채워 반환, 최대 기간 제한", 선행 **W-10**, E-05 |
| `features.md` §6 (`:163`) | 진행 순서 3단계(B): "W-10 통계(추이·분류), W-08 Drive 모듈 → W-07 웹 업로드" — W-09는 5단계(R-11 후) |
| `architecture.md:457` | 엑셀: "StatsService 집계 + 상세 Row → ReportService" |
| `architecture.md:463` | 엑셀 최대 기간 제한 예: 1년 [가정] |
| `back_stack.md:72` | "기간별 추이·유형별 통계를 SQL로 바로 계산 (`date_trunc`, `GROUP BY`, `FILTER`)" |
| `architecture.md:116, 118, 126` | 파일 위치: `api/web/stats.py`, `schemas/stats`, `services/stats_service.py`("통계, 정체 건 집계") |

### 2.2 해석
| 질문 | 해석 |
|---|---|
| 지표 | 필수는 **상담 건수**. 차원별 **유형별 건수**는 XL-02("고객사별 불만/건의")·PRD 배경("불만 현황")이 근거. "미조치"(`action_status = OPEN`)는 XL-02·W-09 지표. 통화 시간(`duration_sec`) 등 그 밖의 지표는 근거 없음 |
| 기간 단위 | `day`·`week`·`month` 3개(`research.md:275`, XL-04). 분기·연은 근거 없음 |
| 차원 | `breakdown`은 담당자(`agent_name`)·고객사(`client_company`) 2개. 유형 차원은 W-09 `summary.by_category`가 담당(프론트 초안도 유형별 막대를 summary로 그림, `DashboardPage.tsx` "유형별 건수" 패널) |
| W-10과 W-09 경계 | W-10은 R-11(정체)에 의존하지 않는다(선행 C-04만). 정체·실패 건수 등 상태 KPI는 W-09 |

### 2.3 C-03 규약 중 W-10에 적용되는 것
| 규칙 | 근거 | 적용 |
|---|---|---|
| `GET /api/stats/*` 200 집계 객체, 에러 422 | `convention.md:47` | 404 없음 |
| 집계는 `Page`를 쓰지 않고 **객체로 감싼다**. 배열을 최상위로 돌려주지 않는다 | `convention.md:61` | `{..., items: [...]}` |
| 기간 `from`·`to`: `date`, KST 하루 단위, `to` 포함, 기준 `call_datetime`, 누락 건 제외, `Query(alias="from")` | `convention.md:122` | 목록과 같은 기준 → 수치 일치 |
| `from > to` → 422 `loc: ["query","from"]`, `type: "date_range"` / 범위 2000-01-01~2100-12-31 | `convention.md:123-124` | 같은 검증 |
| 소프트 삭제 제외 | `convention.md:112` | 집계에서도 제외 |
| 담당자·고객사 정확히 일치, 빈 값은 필터 없음 | `convention.md:126` | breakdown 이름 = 목록 필터 값이어야 드릴다운이 된다 |
| snake_case, enum 영문 대문자 상수, 유형 한글 표시는 프론트 | `convention.md:18`, `:144` | `by_category` 키는 `INQUIRY` 등 |
| 날짜만 필요한 값은 `YYYY-MM-DD` | `convention.md:134` | `period` |
| 숫자는 JSON 숫자, `Decimal` 금지 | `convention.md:152` | `count`는 `int`(`func.count()`는 `int`로 옴) |
| 요청·응답 모델 분리 | `convention.md:156` | |
| 라우터 태그 `stats`, operationId = 함수 이름(앱 전체 고유) | `convention.md:166-167` | 예: `get_stats_trend`, `get_stats_breakdown` |
| 에러는 `AppError`로만, `msg`·`detail`에 입력값 금지 | `convention.md:97-98` | 범위 초과 422 메시지 |
| 응답 형태는 프론트 화면 기준으로 W-09·W-10 착수 시 확정 | `plans/api-convention.md:38`, `researchs/api-convention.md:404` | §7 결정 |

### 2.4 프론트 초안의 가정 (`origin/front`, 미병합)
| 파일 | 내용 |
|---|---|
| `frontend/src/api/stats.ts` | `fetchTrend({from?, to?, granularity})` → `{items: TrendItem[]}`, `fetchBreakdown({from?, to?, by})` → `{items: BreakdownItem[]}` |
| `frontend/src/api/types.ts` | `Granularity = 'day'\|'week'\|'month'`, `TrendItem {period: string; count: number}` — 주석 "period: 구간의 시작일 YYYY-MM-DD (주는 월요일, 월은 1일)", `BreakdownItem {name: string; count: number}`(name null 불가), `Period {from?, to?}` |
| `frontend/src/mocks/handlers.ts` | trend: 기간 안 + `call_datetime` 있는 건만, 값이 있는 구간만, `period` 오름차순. 주 시작 = 월요일. breakdown: `agent_name`/`client_company`가 null이면 제외, `count` 내림차순 → `name` 오름차순 |
| `frontend/src/lib/trend.ts` | `fillBuckets`: 받은 첫 구간~마지막 구간 사이 빈 구간을 0으로 채움(이미 채워진 응답에도 무해). `period` 앞 10자만 사용 |
| `frontend/src/pages/DashboardPage.tsx` | 기본 단위 `day`, 기간은 URL 파라미터(없을 수 있음). `items.length === 0`이면 빈 상태 표시. 담당자·고객사 패널은 `BarList`로 전체 행을 그림(상위 N 없음, `key={r.name}`) |
| `features_frontend.md` | FE-01 "통계 응답 예시 JSON 요청", FE-09 "담당자·고객사 목록을 받을 방법 (지금은 통계 분류 응답의 이름 사용)" |

---

## 3. 데이터 모델 (C-04, 수정하지 않음)

### 3.1 통계에 쓰는 컬럼
| 테이블.컬럼 | 타입 / 제약 | 통계 용도 |
|---|---|---|
| `call_record.call_datetime` | `TIMESTAMPTZ` NULL 허용, 인덱스 `ix_call_dt` | 기간 필터·버킷 기준 |
| `call_record.created_at` | `TIMESTAMPTZ` NOT NULL, `now()` | 대안 기준(§4.1) |
| `call_record.agent_name` | `VARCHAR(50)` NULL 허용 | 담당자 차원 |
| `call_record.client_company` | `VARCHAR(100)` NULL 허용 | 고객사 차원 |
| `call_record.status` | `VARCHAR(20)` CHECK 7개 값, 인덱스 `ix_call_status(status, status_changed_at)` | 상태 포함/제외(§4.2) |
| `call_record.metadata_incomplete` | `BOOLEAN` NOT NULL | 담당자·통화 일시 누락 표시 |
| `call_record.deleted_at` | `TIMESTAMPTZ` NULL | 소프트 삭제 제외 |
| `call_record.duration_sec` | `INTEGER` NULL | (근거 없는 선택 지표) |
| `analysis.category` | `VARCHAR(20)` NOT NULL, CHECK 한글 5개, 인덱스 `ix_analysis_cat`, `call_id` UNIQUE | 유형별 건수 |
| `analysis.action_status` | `VARCHAR(20)` NULL 허용, DEFAULT `'OPEN'`, CHECK `OPEN/DONE` | 미조치 |
| `analysis.needs_review` | `BOOLEAN` NULL 허용 | (W-09 영역) |

- `analysis`·`transcript`는 `call_id` UNIQUE라 outer join해도 행이 늘지 않는다 → `COUNT(*)` 정확(`call_repository.py:68`).
- 재처리는 같은 `call_record` 행의 상태만 바꾸므로(`retry_count` +1) 재처리로 건수가 중복되지 않는다. 해시 중복 등록은 409로 막힌다(`ux_call_hash ... WHERE deleted_at IS NULL`).
- 재분석 요청(`STORED`/`NEEDS_REVIEW` → `RETRY_REQUESTED`) 중에도 기존 `analysis` 행은 남아 있다(UPSERT 방식, R-07). 따라서 "유형 있음 ≠ 처리 완료 상태"일 수 있다.
- `metadata_incomplete = true` ⇔ 담당자 또는 통화 일시 누락(`input_flow.md:225`, `architecture.md` §5). **고객사 누락은 `metadata_incomplete`와 무관**하다.

---

## 4. 집계 기준

### 4.1 기준 시각
| 후보 | 장점 | 단점 |
|---|---|---|
| **`call_datetime`** (통화 시각) | 업무 의미("그날 받은 상담")와 일치. 규약·목록 필터와 같아 수치 일치(`convention.md:122`) | 파일명 파싱 실패 시 NULL → 추이에서 빠짐. 웹 보정(W-12) 시 과거 구간 수치가 바뀜 |
| `created_at` (등록 시각) | 항상 있음 | 업로드가 늦으면 다른 날로 잡힘. 규약과 다름 → 목록 `from/to` 결과와 수치 불일치 |
| `COALESCE(call_datetime, created_at)` | 누락 건도 그래프에 나옴 | 의미가 섞임, 목록과 불일치, 인덱스 사용 어려움 |

→ 규약이 이미 `call_datetime`으로 정함. 통화 일시가 없는 건은 추이에서 빠진다(목록에서는 `metadata_incomplete=true`로 조회).

### 4.2 어떤 건을 셀까
| 항목 | 선택지 | 고려 |
|---|---|---|
| 소프트 삭제 | 제외(고정) | 규약 §4.1 |
| 상태 | (a) 모든 상태 (b) 처리 완료(`STORED`·`NEEDS_REVIEW`)만 (c) `status` 필터 파라미터 | (a)는 목록의 같은 기간 `total`과 일치하고 "들어온 상담 수"를 뜻함. (b)는 "분석된 상담 수"지만 실패·처리 중 건이 사라져 목록과 불일치. `FAILED`도 실제 받은 통화다 |
| 분석 미완료 건(analysis 없음) | 건수에는 포함, 유형별 값에는 없음 | `by_category` 합 ≤ `count`. 차이 = 미분류. 차이를 따로 줄지(`uncategorized`) 결정 필요 |
| `call_datetime` NULL | 추이: 항상 제외(버킷 불가). breakdown: 기간이 없을 때 포함할지 | 목록 API는 기간이 없으면 NULL 건도 보여 준다. breakdown도 같게 하면 "기간 없음 = 전체"가 목록과 일치 |
| `action_status` NULL | 미조치로 볼지 | 컬럼은 DEFAULT `OPEN`이지만 NULL 허용(A3, `plans/call-list-detail.md` §9.1). 미조치 = `action_status = 'OPEN'`로 두면 NULL은 빠짐 |

### 4.3 SQL 스케치 (공통 조건)
```sql
FROM call_record
LEFT JOIN analysis ON analysis.call_id = call_record.id
WHERE call_record.deleted_at IS NULL
  AND call_record.call_datetime >= :from_start   -- kst_day_start(from)
  AND call_record.call_datetime <  :to_end       -- kst_day_start(to + 1일)
```
`filter_conditions(CallListQuery(from_=..., to=...))`가 정확히 이 조건(+ 삭제 제외)을 만든다(`call_repository.py:39-45`). 유형 조건이 없으면 analysis join이 필요 없지만 `by_category`·미조치 집계에는 필요하다.

---

## 5. 추이(`trend`) — KST 버킷팅

### 5.1 실측 결과 (`postgres:16` 16.16, 세션 `TimeZone = Etc/UTC`)
입력 `2026-11-22 15:30Z` = `2026-11-23 00:30 KST`(월요일).

| 식 | 결과 | 판정 |
|---|---|---|
| `date_trunc('day', ts)` | `2026-11-22 00:00+00` | **틀림**(세션 시간대 기준) |
| `date_trunc('day', ts, 'Asia/Seoul')` (PG 12+ 3인자) | `2026-11-22 15:00+00` (timestamptz) | 맞음. 날짜로 쓰려면 다시 `AT TIME ZONE 'Asia/Seoul'` 필요 |
| `date_trunc('day', ts AT TIME ZONE 'Asia/Seoul')::date` | `2026-11-23` | **맞음**(권장 형태) |
| `ts AT TIME ZONE '+09:00'` | `2026-11-22 06:30` | **틀림**(POSIX 부호 반전 → UTC−9) |
| `ts AT TIME ZONE INTERVAL '+09:00'` | `2026-11-23 00:30` | 맞음 |
| `date_trunc('week', '2026-11-29 14:59Z' AT TIME ZONE 'Asia/Seoul')` (KST 일요일 23:59) | `2026-11-23` | 주 시작 = **월요일**(ISO) |
| 같은 식, `2026-11-29 15:30Z`(KST 월요일 00:30) | `2026-11-30` | 월요일 경계 정확 |
| `date_trunc('month', '2026-11-30 15:00Z' AT TIME ZONE 'Asia/Seoul')` | `2026-12-01` | 월 경계 정확 |
| `generate_series(date '2026-01-31', date '2026-05-01', interval '1 month')` | `01-31, 02-28, 03-28, 04-28` | **밀림** — 시작을 월 1일로 맞춰야 함 |

SQLAlchemy(2.0.58) + psycopg 3.3.9 실측:

| 작성 방식 | 결과 |
|---|---|
| `b = func.date_trunc("day", func.timezone("Asia/Seoul", col)).label("period")`, `select(b, func.count()).group_by(b)` | 성공. 같은 객체라 바인드 파라미터 이름이 같다 |
| SELECT와 GROUP BY에 `func.date_trunc("day", ...)`를 **각각 새로 생성** | **`GroupingError: column "call_record.call_datetime" must appear in the GROUP BY clause`** |
| `literal_column("'day'")`, `literal_column("'Asia/Seoul'")` | 성공(SQL에 상수로 들어감). 단위 값은 허용 목록(enum)에서만 와야 함 |
| `literal("week", literal_execute=True)` | 성공(`POSTCOMPILE`로 상수화) |
| 결과 타입 | `timezone()` 결과는 `timestamp without time zone` → 파이썬 **naive `datetime`**. `.date()`로 바꿔 쓴다 |

- `func.timezone(zone, ts)`는 `ts AT TIME ZONE zone`과 같은 함수다.
- `'Asia/Seoul'`은 PostgreSQL 내장 시간대 DB를 쓴다(공식 이미지 포함). 파이썬 쪽은 고정 오프셋 `KST`(`common.py:12`)를 쓰는데, 한국은 1988년 이후 서머타임이 없고 날짜 허용 범위가 2000년부터라 두 값의 결과가 같다.

### 5.2 버킷 계산 위치
| 방식 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. SQL `date_trunc(unit)` GROUP BY** | 단위별로 DB에서 묶음 | `back_stack.md:72` 방침과 일치, 전송 행 = 버킷 수 | 시간대·바인드 함정(§5.1)을 지켜야 함 |
| B. SQL은 KST **일** 단위 GROUP BY, 주·월은 파이썬에서 합산 | 쿼리 하나로 3단위 + 엑셀 일별 시트 재사용 | 쿼리 분기 없음, 주·월 경계 로직을 단위 테스트로 검증 | 단위 변환 코드가 파이썬에 생김 |
| C. 행을 모두 읽어 파이썬에서 버킷 | 시각 목록만 조회 | DB 없이 테스트 쉬움 | 기간이 길면 전송량 증가, 방침과 다름 |

### 5.3 빈 구간 0 채우기
| 방식 | 장점 | 단점 |
|---|---|---|
| (a) 채우지 않음(값 있는 구간만) | 프론트 목과 같음, 범위 제한 불필요 | 기간 앞뒤의 0 구간이 그래프에서 사라짐(프론트는 첫~끝 사이만 채움). 엑셀(W-11)이 따로 채워야 함 |
| (b) SQL `generate_series` + LEFT JOIN | 한 쿼리 | 월 단위 밀림(§5.1), 시작 정규화·시간대 처리 복잡, 범위가 열려 있으면(`from` 없음) 시작을 정할 수 없음 |
| **(c) 파이썬에서 채움** | 주·월 시작 정규화가 단순(`d - timedelta(d.weekday())`, `d.replace(day=1)`), 단위 테스트 가능 | 버킷 수 상한 필요 |

- 채우는 범위: `from`·`to`가 있으면 그 범위의 구간, 없으면 데이터의 첫·마지막 구간.
- 구간 경계: `from`이 수요일이면 첫 주 구간의 `period`는 그 전 월요일이지만 건수는 `from` 이후만 센다(부분 구간). 월도 같다. 응답에 이 사실을 문서화해야 한다.
- 프론트 영향: 데이터가 0건인데 `from`·`to`가 있으면 (c)는 0으로 채운 배열을 돌려준다 → 프론트의 `items.length === 0` 빈 상태 판단이 바뀐다(`total` 필드 또는 "0건이면 빈 배열" 규칙 필요).

### 5.4 기간 파라미터 검증
| 항목 | 기존 규칙 | W-10 고려 |
|---|---|---|
| 형식·범위 | `date`, 2000-01-01~2100-12-31, `from > to` 422 `date_range` | 그대로 사용(목록과 일관) |
| 기본값 | 목록은 둘 다 선택(없으면 전체) | 프론트는 기간 없이도 호출함. 선택지: 전체 / 최근 N일 / 필수 |
| 최대 범위 | 목록은 없음(페이지로 제한). 엑셀은 1년 [가정](`architecture.md:463`) | `day` 단위로 2000~2100 전체를 채우면 약 3.7만 구간. 버킷 수 상한(예: 일 366·주 ~260·월 ~120, 또는 단일 상한)과 초과 시 422(`type` 예: `range_too_large`) 검토 |
| `granularity` | — | `Literal["day","week","month"]` 또는 `StrEnum`. 밖이면 422(자동). 기본값 여부 |

---

## 6. 분류(`breakdown`)

### 6.1 차원·NULL·빈 값
| 항목 | 사실 | 선택지 |
|---|---|---|
| 파라미터 | `by=agent\|client`(`research.md:276`) | 필수 / 기본 `agent` |
| NULL | `agent_name`: 누락 시 NULL(`metadata_incomplete`). `client_company`: 메타데이터 완전해도 NULL 가능 | (a) 제외(프론트 목) (b) `name: null` 행 하나로 포함 (c) `"미지정"` 같은 문자열 |
| 빈 문자열 | 실측: `''`는 별도 그룹으로 나온다. 목록 필터는 빈 값을 "필터 없음"으로 봄(`convention.md:126`) → 빈 문자열 그룹은 목록에서 드릴다운 불가 | `CASE WHEN btrim(col) = '' THEN NULL ELSE col END`로 NULL과 합침. 등록 시 정규화(R-04, A)도 요청 대상 |
| 앞뒤 공백 | 그룹 키를 `btrim`하면 목록의 정확 일치 필터 값과 달라짐 | 그룹 키는 저장 값 그대로, 빈 값 판정에만 `btrim` |
| 정렬 | 프론트 목: `count` 내림차순 → `name` 오름차순 | NULL 행은 마지막. 이름 정렬은 DB 콜레이션(공식 이미지 `en_US.utf8`) 영향 → 파이썬 정렬로 고정하는 방법도 있음 |
| 상위 N + 기타 | 담당자 3명(`prd.md:20`), 고객사 수는 미상 | 프론트는 전체 행을 그리고 이 목록으로 필터 선택 상자를 채운다(FE-09) → 자르면 선택 상자가 불완전. 상위 N은 이후 `limit` 파라미터로 호환 추가 가능 |
| NULL 드릴다운 | 목록 API에는 `agent IS NULL` 필터가 없음 | 담당자 NULL은 `metadata_incomplete=true`로 근사, 고객사 NULL은 방법 없음 |

### 6.2 행에 담을 값
| 후보 | 근거 | 비고 |
|---|---|---|
| `count` | WEB-01, 프론트 초안 | 필수 |
| `by_category` (5개 코드 → 건수, 0 포함) | XL-02 "고객사별 불만/건의 현황", PRD 배경 | `count(*) FILTER (WHERE analysis.category = '불만')` 5개 또는 `GROUP BY key, category` 후 파이썬 피벗. 키는 `CATEGORY_DB_VALUES` 역변환 |
| `action_open` (미조치 건수) | XL-02 "미조치 건", W-09 지표 | `FILTER (WHERE analysis.action_status = 'OPEN')` |
| 비율 | XL-02 "건수·비율" | 프론트·엑셀이 계산 가능 → 서버 불필요 |

실측: `select(count(), count().filter(Analysis.category == "불만"), count().filter(Analysis.action_status == "OPEN"))`가 PostgreSQL `FILTER` 절로 동작.

### 6.3 목록 API와 공유할 수 있는 필터
| 필터 | 공유 가능성 |
|---|---|
| `from`·`to` | **필수 공유**(규약) |
| `category` | 예: "고객사별 불만만" — XL-02와 맞음. `by_category`를 주면 불필요 |
| `agent`·`client` | 예: 특정 고객사의 추이. 근거 없음 |
| `status`, `metadata_incomplete`, `q` | 근거 없음 |

`CallListQuery`를 그대로 받으면 `sort`·`q` 등 통계에 의미 없는 파라미터가 OpenAPI에 노출된다. 필터를 늘릴 때는 호환 변경(선택 파라미터 추가)이므로 지금은 기간만 받고 나중에 추가할 수 있다.

---

## 7. W-09(요약)·W-11(엑셀) 재사용 고려

| 항목 | 고려 사항 |
|---|---|
| 서비스 위치 | `architecture.md:126` `services/stats_service.py` 하나에 W-09·W-10을 둔다. 엑셀(W-11)은 `ReportService`가 `StatsService`를 호출(`architecture.md:457`) |
| 기간 규칙 | 세 기능 모두 같은 `from`/`to` 검증·KST 경계를 써야 수치가 맞는다(`plans/api-convention.md:649`). 기간 쿼리 모델과 경계 함수를 한 곳에 두면 중복이 없다 |
| 공용화 대상 | `kst_day_start`(현재 `call_repository.py`), `DATE_MIN`/`DATE_MAX`·`from > to` 검사(현재 `CallListQuery`). 계획 문서는 "W-09·W-11이 쓸 때 `schemas/common.py`로"라고 적었다(`plans/call-list-detail.md` §1.4). W-10이 두 번째 사용처다 |
| 유형 변환 | `CATEGORY_DB_VALUES`(`schemas/call.py`) 재사용. A가 저장 값을 영문 코드로 바꾸면 표만 항등으로 교체 |
| 반환 형태 | 서비스가 응답 모델(Pydantic)을 돌려주면 라우터·엑셀이 그대로 쓴다. 엑셀은 버킷을 0으로 채운 형태가 차트 범위에 맞다(§5.3 (c)) |
| 엑셀 최대 기간 | 1년 [가정]. 통계 범위 상한과 같은 상수를 쓸지 결정 |
| W-09 정체 | R-11 함수 사용 — W-10과 무관. 요약의 `total`이 trend 합계·breakdown 합계와 같은 조건(상태 전체, 삭제 제외, 같은 기간)이어야 대시보드 수치가 서로 맞는다 |

---

## 8. 기존 패턴을 따르는 파일·함수 후보

| 구분 | 파일 | 내용 (기존 대응) |
|---|---|---|
| 신규 | `app/schemas/stats.py` | `Granularity`, `BreakdownBy`(enum/Literal), 요청 dataclass(예: `StatsPeriodQuery` / `TrendQuery` / `BreakdownQuery`, `CallListQuery`처럼 `@dataclass(frozen=True)` + `Annotated[..., Query()]` + `__post_init__`), 응답 `TrendResponse{granularity, items: list[TrendPoint]}`, `BreakdownResponse{by, items: list[BreakdownRow]}` |
| 신규 | `app/repositories/stats_repository.py` | `StatsRepository(session)`: `count_by_period(...)`, `count_by_dimension(...)`. 조건은 `filter_conditions` 또는 공용 기간 조건 재사용 |
| 신규 | `app/services/stats_service.py` | `StatsService(repository)`: `trend(query)`(버킷 0 채우기·`date` 변환), `breakdown(query)`(NULL·정렬·유형 피벗) |
| 신규 | `app/api/web/stats.py` | `APIRouter(prefix="/api/stats", tags=["stats"])`, `@router.get("/trend")`, `@router.get("/breakdown")`, `StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]` |
| 수정 | `app/api/deps.py` | `get_stats_service(session: DbSession) -> StatsService` |
| 수정 | `app/main.py` | `app.include_router(stats.router)` |
| (공용화 시) 수정 | `app/schemas/common.py`, `app/schemas/call.py`, `app/repositories/call_repository.py` | `kst_day_start`·날짜 범위 상수·`from > to` 검사 이동(W-01 동작 불변, 기존 테스트로 확인) |
| 재생성 | `docs/api/openapi.json` | `uv run python -m scripts.export_openapi` |
| 신규 테스트 | `tests/unit/test_stats_api.py` | 가짜 `StatsService` + `dependency_overrides[get_stats_service]`: 기본값, `granularity`·`by` 잘못된 값 422, `from > to` 422, 날짜 범위 밖 422, 범위 상한 422, 응답 형태, OpenAPI(`get_stats_trend` 등 operationId·enum 노출) |
| 신규 테스트 | `tests/unit/test_stats_service.py` 또는 `test_stats_buckets.py` | 0 채우기·주(월요일)·월(1일) 정규화·부분 구간, 정렬·NULL 처리(DB 없이) |
| 신규 테스트 | `tests/unit/test_stats_query.py` | 연결 없이 컴파일한 SQL에 `timezone('Asia/Seoul', ...)`·`date_trunc` 상수가 있는지, GROUP BY 표현식 일치 |
| 신규 테스트 | `tests/integration/test_stats_repository.py`, `test_stats_api.py` | `pytestmark = integration`. KST 경계(`23:59:59+09:00` vs `00:00+09:00`), 일요일 23:59 KST/월요일 00:00 KST, 월말·월초, 소프트 삭제 제외, `call_datetime` NULL 제외, 담당자 NULL·빈 문자열, 유형 한글 값 → 코드 |
| 재사용 | `tests/integration/factories.py` | `make_call(call_datetime=..., agent_name=..., client_company=..., deleted_at=...)`, `make_analysis(category="불만", action_status=...)` — 추가 팩토리 불필요 |

---

## 9. 미정 사항 (선택지와 권장안)

**[핵심]** 표시는 API 계약(OpenAPI)·수치 의미를 바꾸는 결정이다.

| # | 항목 | 선택지 | 권장안 | 이유 |
|---|---|---|---|---|
| 1 | **[핵심]** 집계 대상 상태 | 모든 상태 / 처리 완료만 / `status` 파라미터 | **모든 상태**(삭제 제외) | 목록 같은 기간 `total`·W-09 `total`과 일치. 실패도 받은 통화. 상태 필터는 필요 시 호환 추가 |
| 2 | **[핵심]** `trend` 응답 형태 | `{granularity, items: [{period, count}]}` / `points` 이름 / `by_category` 포함 | **`{granularity, items: [{period: date, count: int}]}`** | 프론트 초안 키(`items`, `period`, `count`)와 같고, `granularity`를 함께 주면 프론트가 단위를 따로 들고 있지 않아도 된다(초안은 직접 붙임). 유형별 추이는 근거가 약해 이후 호환 추가 |
| 3 | **[핵심]** 빈 구간 0 채우기 | 채우지 않음 / SQL `generate_series` / 파이썬 | **파이썬에서 채움**. 범위 = `from`~`to`(없는 쪽은 데이터의 첫·마지막 구간), **해당 기간 데이터가 0건이면 `items: []`** | 엑셀(W-11)·프론트가 같은 모양을 받음, 월 밀림·시간대 함정 회피. 0건 → 빈 배열은 프론트 빈 상태 판단과 호환. `fillBuckets`는 채워진 응답에도 무해 |
| 4 | **[핵심]** 버킷 계산 | SQL `date_trunc(unit)` / SQL 일 단위 + 파이썬 합산 / 파이썬 | **SQL `date_trunc(unit, timezone('Asia/Seoul', call_datetime))`**, 단위는 enum 허용 목록 → `literal_column`, SELECT·GROUP BY에 **같은 라벨 객체** | `back_stack.md:72` 방침. 함정 3개(§5.1)는 SQL 컴파일 단위 테스트 + KST 경계 통합 테스트로 고정 |
| 5 | 주 시작 요일·`period` 표기 | 월요일(ISO) / 일요일 | **월요일, `period` = 구간 시작일 `YYYY-MM-DD`**(월은 1일). 첫·마지막 구간은 부분 구간일 수 있음을 문서화 | PG `date_trunc('week')`·파이썬 `weekday()`·프론트 초안과 일치 |
| 6 | **[핵심]** 기간 기본값 | 없으면 전체 / 최근 N일 / 필수 | **목록과 같이 둘 다 선택, 없으면 전체** | 규약 일관성, 프론트가 기간 없이 호출함 |
| 7 | **[핵심]** 범위 상한 | 없음 / 단위별 버킷 수 상한 / 단일 기간 상한(1년) | **버킷 수 상한 1개(예: 400) 초과 시 422** `VALIDATION_ERROR`(`loc: ["query","from"]`, `type: "range_too_large"`), `from`·`to`가 모두 있을 때만 검사. 열린 범위는 데이터 범위로 채우되 같은 상한으로 잘라야 하는지 확인 | 일 단위 1년 ≈ 366, 주 ≈ 7.7년, 월 ≈ 33년이 하나의 규칙으로 허용됨. 엑셀은 별도 1년 [가정] |
| 8 | `granularity` 기본값 | 필수 / `day` | **기본 `day`** | 프론트 기본 단위와 같고, `sort` 기본값처럼 OpenAPI에 명시됨 |
| 9 | **[핵심]** `breakdown` 응답 형태 | `{by, items: [{name, count}]}` / `rows` / `key` | **`{by, items: [{name: str \| null, count, by_category: {INQUIRY: n, ...}}]}`** | 프론트 키(`items`, `name`, `count`)와 같음. `by_category`는 XL-02(고객사별 불만/건의) 근거, W-11 재사용. 5개 코드 키를 항상 포함(0 포함) |
| 10 | `action_open` 포함 | 포함 / 제외 | **보류(W-11 템플릿 확인 후 호환 추가)** | XL-02 "미조치 건"은 전체 KPI(W-09)로 충족 가능. E-05 템플릿에 담당자별 미조치가 있으면 추가 |
| 11 | **[핵심]** NULL·빈 값 이름 | 제외 / `name: null` 행 / 문자열 `"미지정"` | **`name: null` 행 하나로 포함(정렬은 항상 마지막)**, 공백만 있는 값도 null로 합침 | 행 합계 = 같은 기간 총 건수(요약과 일치). 표시 문구는 프론트가 정함. 프론트 타입(`name: string`)·`key`·선택 상자 목록에서 null 제외 필요 → 프론트 공지 |
| 12 | 그룹 키 정규화 | 저장 값 그대로 / `btrim` | **저장 값 그대로**(빈 값 판정에만 `btrim`) | 목록 `agent`/`client` 정확 일치 필터로 드릴다운 가능. 앞뒤 공백 제거는 등록(R-04)·보정(W-12) 입력 단계에서 하도록 A와 합의 |
| 13 | 정렬 | DB `ORDER BY` / 파이썬 | **`count` 내림차순 → `name` 오름차순 → null 마지막**, 파이썬 정렬로 확정 | DB 콜레이션과 무관하게 결정적. 행 수가 적음 |
| 14 | 상위 N + 기타 | 전체 / 상위 N + `기타` | **전체 행**(이후 `limit` 선택 파라미터로 호환 추가 가능) | 담당자 3명, 프론트가 이 목록으로 필터 선택 상자를 채움(FE-09) |
| 15 | `by` 기본값 | 필수 / `agent` | **필수** | 의미 있는 기본값이 없음, 잘못 호출 시 바로 422 |
| 16 | breakdown에서 `call_datetime` NULL 건 | 기간 없을 때 포함 / 항상 제외 | **목록과 같게**: 기간이 있으면 제외, 없으면 포함 | `filter_conditions` 재사용 시 자연히 그렇게 됨. 단 trend 합계와 breakdown 합계가 (기간 없을 때) 다를 수 있음을 문서화 |
| 17 | 미분류(analysis 없음) 표시 | `by_category` 합 ≤ `count`로 둠 / `uncategorized` 키 추가 | **합 ≤ `count`로 두고 문서화** | enum 밖 키를 섞지 않음. 필요하면 별도 필드로 호환 추가 |
| 18 | 공유 필터 | 기간만 / `category`·`agent`·`client` 추가 | **기간만** | 근거·프론트 사용처 없음. 선택 파라미터 추가는 호환 변경 |
| 19 | 기간 검증·경계 공용화 | W-10에 복제 / `schemas/common.py`로 이동해 W-01과 공유 / `CallListQuery(from_, to)`를 만들어 `filter_conditions` 재사용 | **이동해 공유**(`kst_day_start`, `DATE_MIN`/`DATE_MAX`, `from > to` 검사를 공용 기간 쿼리로) + 저장소 조건은 공용 기간 조건 함수 | 두 번째 사용처에서 공용화하기로 한 계획(§7)과 일치. W-01 동작은 기존 테스트로 보장. 리팩터 범위를 최소로 하려면 세 번째 선택지(`CallListQuery` 재사용)도 가능 |
| 20 | 엔드포인트 이름(operationId) | `get_stats_trend`·`get_stats_breakdown` / `stats_trend` / `get_trend` | **`get_stats_trend`, `get_stats_breakdown`** (W-09는 `get_stats_summary`) | 앱 전체 고유, 프론트 생성 함수명으로 의미가 분명 |
| 21 | 응답 날짜 타입 | `date` / `KstDatetime`(구간 시작 시각) | **`date`**(`YYYY-MM-DD`) | 규약 "날짜만 필요한 값은 `YYYY-MM-DD`", 프론트 초안과 같음 |

### 9.1 다른 파트 확인 필요
| 대상 | 항목 |
|---|---|
| A (C-04·R-04·R-07) | 유형 저장 값 한글 유지 여부(`plans/call-list-detail.md` §9.1 A1) — 통계도 `CATEGORY_DB_VALUES`에 의존 / 담당자·고객사 입력 정규화(앞뒤 공백, 빈 문자열 → NULL) / `action_status` NULL 허용(A3) — 미조치 집계 의미 |
| 프론트 | FE-01 응답 예시 JSON(이 문서 §9 #2·#9 확정 후) / `name: null` 행 처리(타입·`key`·선택 상자) / 0 채우기된 `trend`(데이터 0건이면 `[]`) / 부분 구간 표시 / FE-09: 담당자·고객사 선택 상자를 breakdown으로 계속 채울지, 별도 목록 API가 필요한지 |
| RPA (E-05) | 엑셀 템플릿의 지표(담당자별 미조치, 고객사별 유형 등) → #9·#10 확정에 영향 |

---

## 10. 구현 시 주의
1. 시간대: SQL에서 `'Asia/Seoul'`을 명시한다. `date_trunc(unit, ts)`(세션 시간대)와 `AT TIME ZONE '+09:00'`(UTC−9)는 쓰지 않는다.
2. `date_trunc` 표현식은 한 번 만들어 라벨 객체를 SELECT·GROUP BY·ORDER BY에 재사용한다(별도 생성 시 `GroupingError`).
3. `timezone()` 결과는 naive `datetime`으로 온다. 응답에는 `.date()`만 쓰고 `KstDatetime`에 naive 값을 넣지 않는다(`convention.md:136`).
4. 단위 문자열은 enum 허용 목록에서만 SQL로 넘긴다(`literal_column` 사용 시 사용자 입력 문자열을 그대로 넣지 않는다).
5. 유형 조건·집계는 DB 저장 값(한글)으로, 응답 키는 영문 코드로 바꾼다(`CATEGORY_DB_VALUES`).
6. 통합 테스트 데이터의 `call_datetime`은 aware 값으로 직접 지정하고, KST 자정 직전·직후, 일요일 23:59 KST, 월말 경계를 포함한다. 테스트 DB 세션 시간대는 UTC이므로 시간대 누락 버그가 드러난다.
7. 라우트를 추가하면 `openapi.json`을 재생성해 같은 커밋에 넣는다(`test_openapi.py`).
8. 422 `msg`·`detail`에 요청 값(날짜 등)을 넣지 않는다(`convention.md:98`).
