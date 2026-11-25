# 분석 결과 수정·검토 완료 계획 — `PATCH /api/calls/{id}`

| 항목 | 내용 |
|---|---|
| 대상 기능 | `features.md` W-03. 메타데이터 보정(W-12)과 같은 PATCH에 선택 필드를 추가한다(호환 변경) |
| 선행 | R-02 상태 머신(`CallStateMachine.transition`, flush만), W-12 구조(`lock_call`·`apply_changes`·`add_edit_history`) |

## 1. 요청 필드 (모두 선택, 보낸 키만 반영)

| 필드 | 타입 | `null` | 저장 위치 |
|---|---|---|---|
| `category` | `INQUIRY`·`COMPLAINT`·`SUGGESTION`·`EDUCATION`·`ETC` | 422 | `analysis.category` (DB 값으로 변환) |
| `question_summary` | 문자열, 공백 제거 후 1~2000자 | 비우기 | `analysis.question_summary` |
| `action_summary` | 〃 | 비우기 | `analysis.action_summary` |
| `action_status` | `OPEN`·`DONE` | 422 | `analysis.action_status` |
| `review_completed` | `true`만 | 422 (`false`도 422) | 상태 `NEEDS_REVIEW → STORED` |

## 2. 결정

| # | 내용 | 이유 |
|---|---|---|
| D1 | 분석 필드는 분석 결과가 있는 건이면 상태와 관계없이 수정 가능. 분석 결과가 없으면 409 `INVALID_STATE_TRANSITION` | 수정 대상이 없음. 재처리로 분석이 다시 적재되면 수정값은 덮어써지며 이력은 남는다 |
| D2 | `review_completed: true`는 `NEEDS_REVIEW`에서만 허용, 그 밖(이미 `STORED` 포함)은 상태 머신의 409 | 상태 전이 표(architecture.md)와 같음. 중복 요청을 성공으로 숨기지 않음 |
| D3 | 검토 완료 시 `analysis.needs_review=false`도 함께 바꾼다 | 로봇 분석 적재가 `needs_review`를 상태와 같게 맞추는 규칙과 일치 |
| D4 | 한 요청 = 한 트랜잭션. 순서: 잠금 → 분석 결과 존재 확인(409) → 검토 완료 전이(409) → 메타데이터 → 분석 필드 → 이력 → 커밋. 409는 어떤 값도 바꾸기 전에 낸다 | W-12 구조 그대로. 실패 시 반영된 값이 없음을 세션 정리에 기대지 않음 |
| D5 | 이력: 바뀐 분석 필드마다 1행(`category`는 DB 저장 값 그대로), 검토 완료는 `field: "status"`, `NEEDS_REVIEW → STORED` 1행. `needs_review`는 파생 값이라 기록하지 않음. 처리 로그는 상태 머신이 `actor=web`으로 남김 | 수정자(`editor`)가 남는 곳은 `edit_history`뿐 |

## 3. 변경 파일

- `app/schemas/call.py`: `CallUpdateRequest`에 필드 5개, `analysis_changes()` 추가
- `app/services/call_service.py`: `update_call`에 분석 적용·검토 완료 전이, `CallService`가 상태 머신 사용
- `app/api/web/calls.py`: PATCH `responses`에 `INVALID_STATE_TRANSITION`
- `docs/api/convention.md`·`docs/api/openapi.json`: PATCH 규칙 갱신

## 4. 테스트

- 단위(요청 모델): 필드 검증(코드값·`null` 422·공백 제거·길이·`review_completed=false` 422), `analysis_changes`가 보낸 키만 DB 값으로 반환
- 통합(PATCH): 분석 필드 수정·이력, 같은 값 무이력, 분석 없음 409·무변경, 검토 완료 전이·로그·`needs_review`·이력, `STORED`에서 검토 완료 409, 메타데이터+검토 완료 혼합 시 409면 메타데이터도 롤백, 기존 "분석 필드 422" 테스트는 오타 키 422로 교체

## 5. 확인 필요

- 프론트: 검토 완료 입력 이름(`review_completed: true`), 유형은 코드값으로 보냄
- A: 재처리로 분석이 다시 적재되면 웹 수정값이 덮어써지는 동작(D1) 괜찮은지
