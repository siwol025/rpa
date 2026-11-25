# 통계 요약 · 목록 정체 필터 구현 계획

> 선행: 정체 감지(`app/services/stale_detection.py`, main 머지). 리서치 생략(짧은 계획).

## 1. 통계 요약 `GET /api/stats/summary?from&to`

응답(200, 키 항상 존재):

```json
{"total": 0, "by_category": {"INQUIRY": 0, "COMPLAINT": 0, "SUGGESTION": 0, "EDUCATION": 0, "ETC": 0},
 "action_open": 0, "needs_review": 0, "metadata_incomplete": 0, "failed": 0, "stale": 0}
```

| 항목 | 기준 | 기간 적용 |
|---|---|---|
| `total` | 삭제 제외 전체 건 | O (통화 일시, 목록 `from`·`to`와 같은 KST 경계) |
| `by_category` | 분석 유형별 건수. 분석 전인 건은 어느 키에도 없음 | O |
| `action_open` | 분석 `action_status = OPEN` | X |
| `needs_review` | 상태 `NEEDS_REVIEW` | X |
| `metadata_incomplete` | `metadata_incomplete = true` | X |
| `failed` | 상태 `FAILED` | X |
| `stale` | 정체 감지 `stale_condition`(설정 `STALE_THRESHOLD_MIN`) | X |

- 처리 대기 건수(미조치·검토 필요·메타데이터 확인 필요·실패·정체)는 할 일 목록이라 기간과 무관한 전체 건수다. 기간을 적용하면 통화 일시가 없는 메타데이터 확인 필요 건이 모두 빠진다.
- 기간 검증(`from > to` 422)은 추이·분류와 같다(`StatsPeriod`).
- 쿼리 1회: `COUNT(*) FILTER (WHERE …)`로 7+4개 값을 한 번에 센다.

## 2. 목록 정체 필터 · `is_stale`

- `CallListQuery.stale: bool | None` — `true`=정체 건만, `false`=정체 아닌 건만, 없으면 전체.
- `is_stale: bool`을 목록 항목과 상세에 추가(규약 §5.3). 기준은 상태 머신 `is_stale`과 같다.
- 한 요청 안에서는 같은 `now`로 필터와 `is_stale`을 계산한다.
- `CallService`·`StatsService`가 `stale_threshold_min`을 받는다(deps에서 설정 주입).

## 3. 변경 파일

- `app/schemas/stats.py`(`StatsSummary`), `app/repositories/stats_repository.py`(`summary`), `app/services/stats_service.py`, `app/api/web/stats.py`
- `app/schemas/call.py`(`stale` 쿼리, `is_stale` 응답), `app/repositories/call_repository.py`(`filter_conditions` 정체 조건), `app/services/call_service.py`, `app/api/deps.py`
- `docs/api/convention.md`(정체 항목 추가됨으로 갱신, 요약 기간 규칙), `docs/api/openapi.json`

## 4. 테스트

- 단위: 요약 서비스 매핑, 라우터 파라미터·422·OpenAPI, 목록 `stale` 파싱, `is_stale` 계산(경계: 기준 시각 정확히 같으면 정체 아님)
- 통합: 요약 각 건수(삭제 제외, 기간이 처리 대기 건수에 영향 없음), 목록 `stale=true/false` 필터와 `is_stale`, 상세 `is_stale`

## 5. 확인 필요

- 요약의 기간 적용 범위(처리 대기 건수는 전체) — 프론트(대시보드 카드) 확인
- `action_open`은 실패·처리 중 건을 포함하지 않는다(분석이 있는 건만) — 의도 맞는지 프론트 확인
