# Tech Stack — ④ RPA 코어 & 보고서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 근거 | `features_rpa.md` v0.1, 백엔드 `back_stack.md` v0.1, ③ `call_schema.json` v1.0 |
| 범위 | 역할 ④ UiPath RPA 코어 & 보고서 |
| 제외 | STT·GenAI(③), 서버·DB(①), 웹(②) |

## 1. 한눈에 보기

| 영역 | 선택 | 버전/비고 |
|---|---|---|
| RPA 도구 | UiPath Studio | 25.10.4 (Windows 대상, .NET 8 런타임) |
| 구현 방식 | Coded Workflows (C#) | `CodedWorkflowBase` + `[Workflow]` |
| 식 언어 | VB (프로젝트 기본) | XAML 최소 사용 |
| 엑셀 제어 | Excel COM 늦은 바인딩 | 참조 추가 없이 `InvokeMember`, 바쁨 재시도 |
| JSON 파싱 | System.Text.Json | ③ JSON 읽기 |
| 설정 | `Data\Config.xlsx` | 코드 수정 없이 컬럼·값·경로 변경 |
| 작업 분배 | Orchestrator Queue + Time Trigger | Dispatcher/Performer |
| 구조 | REFramework | Performer에 적용 (3단계) |
| 서버 통신 | HTTP Request (REST/JSON) | `X-API-Key` 헤더 |
| 비밀 관리 | Orchestrator Assets | API 키 코드 직기입 금지 |
| 보고서 | Excel 템플릿 (표·피벗·슬라이서·차트) | `.xlsx` |

## 2. 구성 요소

### 2.1 Coded Workflows (C#)
| 이유 | 설명 |
|---|---|
| 유지보수 | 로직이 코드 한 곳에 모여 변경·리뷰가 쉽다 |
| 테스트 | Studio 없이 하네스로 컴파일·검증 가능 (7종 케이스 통과) |
| 주의 | 실행할 파일을 우클릭 → "주 항목으로 설정"하거나 Run File로 실행. 기본 Main.xaml은 비어 있음 |

파일 구성: `Late.cs`(COM 도우미) · `ExcelApp.cs`(엑셀 래퍼) · `AppConfig.cs`(Config 로드) · `ResultJson.cs`(JSON 읽기) · `Pipeline.cs`(처리 본체) · `ResultFolderToExcel.cs`(진입점)

### 2.2 Excel 처리
- 보고서 표(ListObject)에 `ListRows.Add`로 행 추가 → 계산 컬럼(일자·요일·월) 자동 채움
- 통화ID 기준 Upsert, 텍스트 컬럼은 서식 `@`, `=+-@`로 시작하는 값은 수식 방지 처리
- NEEDS_REVIEW 행은 조건부 서식으로 노란색, FAILED는 별도 `예외` 시트
- 저장 전 RefreshAll로 피벗·차트 갱신
- **주의**: 서버가 openpyxl로 이 파일을 열어 저장하면 슬라이서·차트가 사라진다 → 협의 필요 (W-11)

### 2.3 Config.xlsx 시트
| 시트 | 용도 |
|---|---|
| Settings | 폴더 경로, 시트·표 이름, 키 컬럼, 간격, 서버 API 스위치 |
| Constants | 고정 상수 |
| ColumnMap | JSON 경로 → 엑셀 컬럼, 필수 조건 |
| ErrorColumnMap | 예외 시트 컬럼 매핑 |
| ValueMap | 값 변환 (SUCCESS→정상, true→필요 등) |
| Routing | status별 대상 시트 |

### 2.4 Orchestrator
- Queue `CallCenter_Calls`: Reference = `call_id`, 재처리 `call_id-retryN`
- Time Trigger: Dispatcher 5분 주기
- 실행 계정/무인 로봇 사용 가능 여부는 확인 필요 (현재 attended 로봇)

### 2.5 서버 API 연동 (백엔드 A 문서 기준)
| 호출 | API | 시점 |
|---|---|---|
| 등록 | R-04 | 파일 감지 직후 |
| 상태 변경 | R-05 | Queue 추가 후 (QUEUED) |
| 전사 적재 | R-06 | STT 완료 후 (호출 주체 협의) |
| 분석 적재 | R-07 | 엑셀 기입 후 |
| 실패 로그 | R-08 | 3회 재시도 소진 후 1회 |

- 인증: `X-API-Key` + 로봇 PC IP 허용 목록(`ROBOT_ALLOWED_IPS`)
- 409: 현재 상태 포함 응답 → 처리 방식 확정 필요

## 3. 데이터 규약 (③ call_schema.json v1.0)
- 필수 키는 항상 존재, 값 없으면 null
- `call_id`: `^\d{8}_\d{6}_\d{3}$`
- status: SUCCESS / NEEDS_REVIEW / FAILED
- type: INQUIRY / COMPLAINT / SUGGESTION / TRAINING / OTHER (표시명 type_label)
- `schema_version`이 다르면 업무 오류로 `error` 폴더 이동

## 4. 개발·테스트 환경
| 항목 | 내용 |
|---|---|
| IDE | UiPath Studio 25.10.4 |
| 필수 설치 | Microsoft Excel (COM 사용) |
| 테스트 데이터 | `Runtime\out\case01~07` (성공, 확인필요, 실패, 중복 갱신, null, 필수값 누락, 버전 불일치) |
| 기대 결과 | 통화이력 3행(추가 3, 갱신 1), 예외 1행, processed 5, error 2 |
| 로그 위치 | `%LOCALAPPDATA%\UiPath\Logs` |
| 실행 가이드 | `README_실행방법.md` |

## 5. 확정 필요 항목
1. ③ 분석 호출 방식 (HTTP / 파일 전달 / 직접 모듈)
2. 서버 키 체계, R-06·R-07 호출 주체, 로봇 PC IP, 409 처리
3. 엑셀 보고서 제공 방식 (W-11 충돌)
4. 웹과 KPI·상태 표기 통일
5. 무인 로봇·Orchestrator 사용 가능 여부
6. Google Drive 서비스 계정·녹음 파일 보안 정책
7. Queue API를 Coded Workflow에서 쓰는 방법 검증
