# 엑셀 보고서 다운로드 계획 — `GET /api/reports/excel`

| 항목 | 내용 |
|---|---|
| 대상 기능 | `features.md` W-11 중 **기간 지정 보고서**. 정기 보고서(로봇 생성 파일 업로드·제공)는 주기·보관 규칙을 정한 뒤 별도 진행 |
| 템플릿 | RPA 파트 빈 양식(`uipath/Runtime/template/콜센터_보고서_빈양식.xlsx`)을 `backend/templates/report.xlsx`로 복사(Docker 빌드 범위가 `backend/`라서). 양식이 바뀌면 두 파일을 함께 갱신 |

## 1. 템플릿 구조 (RPA 파트 제공 정보 + 파일 확인)

- 시트: 대시보드, 통화이력(표 `tblCalls`, 상담 1건 = 1행, A~N), 예외(표 `tblErrors`, 실패 1건 = 1행, A~F), 집계, 사용안내
- 피벗 4개 → 피벗 캐시 1개, 원본 `tblCalls`, `refreshOnLoad="1"`. 차트 4개는 집계 시트의 피벗 결과를 참조. 슬라이서 3개(담당자·유형·처리 상태)
- 대시보드 수식이 `tblCalls`·`tblErrors` 값을 직접 센다: 유형 `"불만"`, 후속조치 필요 `"필요"`, 처리 상태 `"확인필요"`
- `tblCalls`의 일자·요일·월(L~N)은 계산 열(수식)

## 2. 결정

| # | 내용 | 이유 |
|---|---|---|
| D1 | **xlsx 내부 XML을 직접 채운다.** 통화이력·예외 시트의 행과 표 범위만 바꾸고 나머지 파일은 그대로 둔다. `calcChain.xml` 제거, `fullCalcOnLoad="1"` | openpyxl로 열고 저장하면 기존 차트·슬라이서가 사라진다. 피벗 캐시가 열 때 새로 고침이라 Excel에서 열면 피벗·차트·슬라이서·대시보드가 로봇 보고서와 같게 다시 계산된다 |
| D2 | 다운로드 파일은 Excel의 제한된 보기로 열린다. "편집 사용"을 누르기 전에는 대시보드·집계가 빈 양식 값으로 보이고, 통화이력·예외 시트는 바로 보인다 | 제한된 보기에서는 재계산·피벗 새로 고침을 하지 않는다(서버에서 바꿀 수 없음) |
| D3 | 쿼리 `from`·`to`(KST 날짜)는 선택. 비우면 `to`=오늘(KST), `from`=`to`의 365일 전. `from ≤ to`, 기간 최대 366일, 위반은 422 | 대용량 방지(architecture.md §9 "최대 기간 제한"). 프론트 다운로드 버튼이 기간 없이도 호출하므로 기본 기간을 둠(사용자 결정) |
| D4 | 기간 판정: `call_datetime`이 기간 안이거나, `call_datetime`이 없고 등록 시각(`created_at`, KST 날짜)이 기간 안. 삭제 건 제외 | 통화 일시가 없는 건이 보고서에서 빠지지 않게 한다(대시보드의 "담당자·통화일시 누락" 점검이 이 건을 센다) |
| D5 | 통화이력: `STORED`·`NEEDS_REVIEW` 중 분석 결과가 있는 건, 통화 일시 오름차순(없는 건은 뒤, 같으면 id) | 로봇 보고서는 분석이 끝난 건만 적는다 |
| D6 | 예외: `FAILED` 건, 같은 순서 | 로봇 보고서의 예외 시트와 같음 |
| D7 | 통화ID = 서버 상담 id | 웹에서 바로 찾을 수 있게 (사용자 결정) |

## 3. 열 매핑

통화이력: 통화ID `id` / 통화일시 `call_datetime`(KST, 엑셀 날짜) / 담당자 `agent_name` / 고객사 `client_company` / 유형 `analysis.category`(DB 한글 값) / 고객 질문 `question_summary` / 조치 내역 `action_summary` / 요약 `raw_json.summary` / 후속조치 필요 `follow_up_required`(`true`→`필요`, `false`→`불필요`, 없음→빈칸) / 후속 조치 `raw_json.follow_up` / 처리 상태 `STORED`→`정상`, `NEEDS_REVIEW`→`확인필요` / 일자·요일·월은 템플릿 수식

예외: 통화ID `id` / 파일명 `original_name` / 오류 단계·사유: 마지막 `FAIL` 처리 로그 메시지(`[robot] A -> FAILED: [STAGE] 사유`)에서 꺼냄, 단계 표기가 없으면 로그 `step` / 수신시각 `created_at`(KST) / 재시도 횟수 `retry_count`

값이 없으면 셀을 비운다. 문자열은 인라인 문자열 셀이라 `=`로 시작해도 수식으로 실행되지 않는다. XML에 쓸 수 없는 제어 문자는 지운다.

## 4. 변경 파일

- `app/services/excel_report.py`: 템플릿 바이트 + 행 목록 → xlsx 바이트 (DB 무관 순수 함수)
- `app/repositories/report_repository.py`, `app/services/report_service.py`, `app/schemas/report.py`, `app/api/web/reports.py`, `app/api/deps.py`, `app/main.py`
- `templates/report.xlsx`, `docs/api/convention.md`·`openapi.json`

## 5. 테스트

- 단위(채우기): 표 범위·dimension·조건부 서식 범위 갱신, 셀 값·스타일·수식 열, 빈 값 생략, 특수문자 이스케이프·제어 문자 제거, `calcChain` 제거·`fullCalcOnLoad`, 그 밖의 파일은 바이트 동일, 행 0건이면 빈 양식 그대로
- 단위(기간·실패 사유 파싱), API 단위(422·헤더)
- 통합: 실제 DB 데이터로 받은 파일을 openpyxl로 읽어 행 값 확인, 기간·삭제·상태 필터
- 수동: 이 PC의 Excel로 생성 파일을 열어 피벗 새로 고침 후 대시보드 수치 확인

## 6. 확인 필요

- RPA: 템플릿을 바꾸면 `backend/templates/report.xlsx`도 갱신해야 함. 표 이름·열 순서·피벗 원본(`tblCalls`)이 바뀌면 서버 코드 수정 필요
- 프론트: 기간을 비우면 최근 366일. 기간이 366일을 넘으면 422(`period_too_long`). 파일명은 `Content-Disposition`의 `filename*`(UTF-8)에도 있음
- 웹 수정값(유형·요약 등)은 반영되지만 `요약`·`후속 조치`는 GenAI 원본(`raw_json`)이라 웹에서 고칠 수 없음
