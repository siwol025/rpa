# 기능 목록 — ④ RPA 코어 & 보고서 (UiPath)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 (초안) |
| 작성일 | 2026-11-24 |
| 근거 | 백엔드 `features_backend_A.md` v0.1, `back_stack.md` v0.1, 프론트 `features_frontend.md` v0.1, ③ `call_schema.json` v1.0, `결정사항_공유_RPA직접감지.docx` |

## 한눈에 보기

| 항목 | 내용 |
|---|---|
| 영역 | 녹음 파일 감지 → 분석 요청 → 결과 JSON 검증 → 엑셀 보고서 기입 → 서버 상태 보고 (로봇 본체) |
| 제외 | STT·GenAI 분석 자체(③), 서버 DB·API(①), 웹 화면(②) |
| 기술 스택 | UiPath Studio 25.10.4, Coded Workflows(C#), Excel COM(늦은 바인딩), System.Text.Json, Config.xlsx, Orchestrator Queue + Time Trigger, REFramework |
| 기능 수 | 엑셀 기입 9개 + 파이프라인 6개 + 서버 연동 6개 + 운영 3개 = 24개 |
| 주로 협업할 파트 | ③ 예린(JSON 규약), ① 백엔드(R-01~R-12 API), ② 프론트(엑셀 다운로드·KPI 정의) |
| 먼저 요청할 것 | ③: null 규칙·call_datetime 대체값·분류 단일화 / ①: 키 체계, R-06·R-07 호출 주체, 로봇 PC IP, 409 처리 / ②: 상태·KPI 정의 |
| 주 작업 위치 | `CallCenter\*.cs`, `Data\Config.xlsx`, `Runtime\`, `Main.xaml` |

## 1. 진행 원칙

- 서버·③을 기다리지 않는다: 샘플 JSON 7종(`Runtime\out`)으로 엑셀 기입을 먼저 완성하고, 서버 호출은 Config 스위치(`ServerApiEnabled`)로 끈 채 개발한다.
- 바뀔 수 있는 것은 코드가 아니라 Config로 뺀다: 컬럼 매핑(ColumnMap)·값 변환(ValueMap)·경로·임계값은 `Config.xlsx`에서 수정한다.
- 오류는 두 종류로 나눈다: 업무 오류(재시도해도 소용없음)는 `error` 폴더로, 시스템 오류(일시적)는 파일을 그대로 두어 다음 실행에서 재시도한다.
- 같은 `call_id`는 새 행이 아니라 갱신(Upsert)한다.
- 구현은 5단계로 나눈다: ①JSON→엑셀 ②예외·재시도 ③Performer(Queue) ④Dispatcher(감지) ⑤서버 API.

### 우선순위·Phase 기준 (백엔드 문서와 동일)

| 구분 | 의미 |
|---|---|
| P0 | 필수 — 1차 릴리스 전에 반드시 구현 |
| P1 | 중요 — 일정이 부족하면 뒤로 미룰 수 있음 |
| P2 | 선택 |
| Phase 1 | MVP: 파일 → 분석 → 엑셀 기입 |
| Phase 2 | 서버 연동·재처리·보고서 고도화 |

## 2. 처리 흐름과 상태 보고

```
[Dispatcher] 클라우드 폴더 감지(Time Trigger) → inbox→processing 이동(선점) → 파일명 파싱
   → R-04 등록(REGISTERED) → Queue 추가 → R-05 (QUEUED)
[Performer]  Queue 항목 → ③ 분석 요청 → R-06 전사(STT_DONE) → JSON 수신·검증
   → 엑셀 Upsert → R-07 분석(STORED / NEEDS_REVIEW) → 파일 이동
   실패 3회 → R-08 로그(FAIL, stage·reason) → FAILED
[재처리]     웹 재처리 요청(RETRY_REQUESTED) → Dispatcher가 Queue 재삽입(Reference `call_id-retryN`) → R-05
```

| 상황 | 로봇 동작 | 서버 상태 |
|---|---|---|
| JSON status=SUCCESS | 본 시트 추가·갱신 | STORED |
| JSON status=NEEDS_REVIEW | 본 시트 + 노란색 행 | NEEDS_REVIEW |
| JSON status=FAILED | 예외 시트 기록 | FAILED (R-08) |
| 필수값 누락·schema_version 불일치·알 수 없는 status | JSON을 `error` 폴더로, 재시도 없음 | FAILED (업무 오류) |
| 엑셀 파일 잠김·COM 오류 | 파일 유지, 다음 실행에서 재시도 | 변경 없음, 로그만 |
| 서버 409 | 상태 확인 후 무시 또는 로그 (확정 필요) | — |

## 3. 기능 목록

### 3.1 엑셀 기입 (1단계 — 구현 완료·Studio 검증 중)

| ID | 기능 | 상세 | 우선순위 | Phase | 선행 |
|---|---|---|---|---|---|
| X-01 | Config 로드 | `Data\Config.xlsx` 읽기(Settings, Constants, ColumnMap, ErrorColumnMap, ValueMap, Routing). 경로는 프로젝트 기준 상대경로 | P0 | 1 | — |
| X-02 | 결과 JSON 읽기·검증 | 점(.) 경로로 값 추출, null→빈칸, schema_version·call_id 형식·status·필수값 검사 | P0 | 1 | X-01 |
| X-03 | 컬럼·값 매핑 | ColumnMap(11개 기입 컬럼), ValueMap(SUCCESS→정상 등), 날짜 변환 | P0 | 1 | X-01 |
| X-04 | 상태별 분기 | SUCCESS/NEEDS_REVIEW→본 시트, FAILED→예외 시트(Routing) | P0 | 1 | X-02 |
| X-05 | 템플릿에서 보고서 생성 | 보고서가 없으면 빈 양식 복사 | P0 | 1 | X-01 |
| X-06 | Upsert | 통화ID 기준 갱신/추가, 빈 행 재사용, 계산 컬럼(일자·요일·월) 자동 채움 | P0 | 1 | X-03 |
| X-07 | 새로고침·저장 | 피벗·차트 RefreshAll 후 저장 | P0 | 1 | X-06 |
| X-08 | 파일 이동 | processed / error 폴더로, 이름 충돌 시 고유 이름 | P0 | 1 | X-04 |
| X-09 | Excel 바쁨 재시도 | RPC_E_SERVERCALL_RETRYLATER 등 최대 약 10초 재시도 | P0 | 1 | — |

### 3.2 파이프라인 (2~4단계)

| ID | 기능 | 상세 | 우선순위 | Phase | 선행 |
|---|---|---|---|---|---|
| P-01 | 예외·재시도 시나리오 | 3회 재시도, 업무/시스템 오류 분리 확정, 오류 알림 | P0 | 1 | X-08 |
| P-02 | Performer (REFramework) | Queue 항목 1건씩 처리, 분석 요청→엑셀→상태 보고 | P0 | 1 | P-01, X-06 |
| P-03 | ③ 분석 호출 | 연결 방식 확정 필요(HTTP/파일 전달/직접 모듈) | P0 | 1 | ③ 협의 |
| P-04 | Dispatcher | 5분 간격 Time Trigger, inbox→processing 이동 선점, 파일명 파싱(일시·담당자·고객사) | P0 | 1 | P-02 |
| P-05 | Queue 구성 | Queue `CallCenter_Calls`, Reference `call_id`(재처리 `call_id-retryN`) | P0 | 1 | P-04 |
| P-06 | 클라우드 폴더 연동 | Google Drive 감지·다운로드 (서비스 계정·보안 정책 확인 필요) | P1 | 2 | P-04 |

### 3.3 서버 연동 (5단계)

| ID | 기능 | API | 상세 | 우선순위 | Phase | 선행 |
|---|---|---|---|---|---|---|
| S-01 | 인증 헤더 | 공통 | `X-API-Key`는 Orchestrator Asset에 보관, 코드·Config에 직접 기입 금지 | P0 | 2 | E-04 |
| S-02 | 등록 | R-04 | REGISTERED, 중복 시 409 처리 | P0 | 2 | S-01 |
| S-03 | 상태 변경 | R-05 | QUEUED, `queue_item_id` 전달 | P0 | 2 | S-02 |
| S-04 | 전사 적재 | R-06 | STT_DONE (호출 주체 협의) | P1 | 2 | S-03 |
| S-05 | 분석 적재 | R-07 | STORED / NEEDS_REVIEW (호출 주체 협의) | P0 | 2 | S-03 |
| S-06 | 실패 로그 | R-08 | 3회 소진 후 FAIL 1회, stage·reason 포함 | P0 | 2 | S-03 |

### 3.4 운영 / 보고서

| ID | 기능 | 상세 | 우선순위 | Phase | 선행 |
|---|---|---|---|---|---|
| O-01 | 보고서 템플릿 | 통화이력·예외 시트, 피벗·슬라이서·차트, KPI. 웹 대시보드 KPI와 정의 통일 | P0 | 1 | — |
| O-02 | 배포·실행 환경 | 프로젝트 게시, 무인 로봇 또는 대체 실행(작업 스케줄러) | P1 | 2 | P-04 |
| O-03 | 실행 가이드·인수인계 | README, Config 항목 설명 | P1 | 1 | — |

## 4. 다른 파트에 요청할 것

| 대상 | 요청 | 상태 |
|---|---|---|
| ③ 예린 | agent_name null 시 파일명 규칙, call_datetime null 시 received_at 대체, 분류 단일화(type), 업무/주제/통화시간 필드 필요 여부 | 미확정 |
| ① 백엔드 | `call_id`(문자열) vs 서버 id 키, R-06·R-07 호출 주체(로봇/③), 로봇 PC IP, 409 처리 방식 | 미확정 |
| ① 백엔드 | **W-11**: 서버가 openpyxl로 엑셀을 채우면 슬라이서·차트 소실 → 로봇이 만든 보고서를 그대로 제공하는 방식 제안 | 협의 필요 |
| ② 프론트 | 상태 표기(완료/분석 중/실패 ↔ SUCCESS/NEEDS_REVIEW/FAILED), KPI(상담 건수, 불만 비율, 자동 처리 완료율, 평균 통화시간) 정의 | 미확정 |

## 5. 진행 순서

1. 1단계: JSON 폴더 → 엑셀 (Studio 실행 검증 — 마지막 단계)
2. 2단계: 예외·재시도 시나리오
3. 3단계: Performer + Queue
4. 4단계: Dispatcher + Time Trigger
5. 5단계: 서버 API 연동 (R-04 → R-05 → R-07 → R-08)
6. 6단계: 클라우드 폴더·배포, 보고서 KPI를 웹과 정렬
