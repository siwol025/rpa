# ④ RPA 코어 — 1단계: 결과 JSON 폴더 → 엑셀 보고서

③(예린)이 만든 결과 JSON(`{call_id}.json`)을 읽어 검증·매핑한 뒤 엑셀 보고서에 기입합니다.

## 실행 방법 (Studio 25.10)
1. Studio에서 이 프로젝트(`팀프로젝트`)를 연다. 처음 열 때 코드 파일이 컴파일된다(오류가 있으면 Error List에 표시됨).
2. 프로젝트 패널의 `CallCenter\ResultFolderToExcel.cs` 를 우클릭 → **Run File** (인자 `configPath`는 비워 둠).
3. 결과 확인
   - `Runtime\report\콜센터_보고서.xlsx` 가 템플릿(`Runtime\template`)에서 자동 생성되고 데이터가 기입된다.
   - 처리된 JSON은 `Runtime\out\processed\`, 업무 오류 JSON은 `Runtime\out\error\` 로 이동한다.
   - 출력(Output) 패널에 `[Info]/[Warn]/[Error]` 로그가 나온다.

## 폴더 / 파일
| 경로 | 설명 |
|---|---|
| `Data\Config.xlsx` | 설정·컬럼 매핑·값 변환·라우팅 (경로는 프로젝트 루트 기준 상대 경로) |
| `Runtime\out\` | ③이 JSON을 떨어뜨리는 폴더. 테스트용 7종이 들어 있음 |
| `Runtime\template\콜센터_보고서_빈양식.xlsx` | 보고서가 없을 때 복사해 쓰는 빈 양식 |
| `CallCenter\*.cs` | 구현 코드. 핵심 로직은 `Pipeline.cs` (UiPath 의존성 없음) |

## 테스트 7종의 기대 결과 (처음 실행 시)
통화이력 3행(통화ID 001은 case04가 덮어씀), 예외 1행, `processed` 5개, `error` 2개(case06, case07).

## 다시 실행하려면
- `Runtime\out\processed`, `Runtime\out\error` 의 JSON을 `Runtime\out\` 으로 되돌리고 `Runtime\report\콜센터_보고서.xlsx` 를 삭제한 뒤 실행.

## 주의
- 보고서 엑셀 파일이 열려 있으면(잠김) 시스템 오류로 기록되고 해당 파일은 그대로 남는다(다음 실행에서 재시도).
- 엑셀(데스크톱)이 설치돼 있어야 한다. 개발 중에는 `Config.xlsx > Settings > ExcelVisible` 을 `True` 로 두면 엑셀 창이 보인다.
- 컬럼이 바뀌면 `Config.xlsx > ColumnMap` 과 엑셀 템플릿만 수정한다(코드 수정 불필요).

---

## 액티비티 버전 (Flow_JsonToExcel.xaml)

코드 버전(ResultFolderToExcel.cs)과 같은 일을 UiPath 액티비티로 만든 것입니다.

1. Studio 프로젝트 패널에서 `Flow_JsonToExcel.xaml`을 더블클릭해 엽니다. (안 보이면 패널 새로고침)
2. 빨간 오류 표시가 있으면 어느 블록에 어떤 메시지인지 캡처해서 알려 주세요.
3. 파일에서 우클릭 → Run File 로 실행합니다.
4. 실행 전에 `Runtime\out`에 JSON 7개, `Runtime\report`에 보고서가 없는 상태여야 합니다. (코드 버전 결과와 비교용)

흐름: 준비(경로·폴더·양식 복사) → For Each JSON(읽기 → 검사 → 엑셀 기입 → 파일 이동, 오류는 업무/시스템 구분) → 요약 로그.
기대 마지막 로그: 처리 파일 7건 | 본시트 추가 3, 갱신 1 | 예외시트 1 | processed 5, error 2 | 시스템 오류 0
---

## Queue 버전 (Dispatcher + Performer)

| 파일 | 역할 |
|---|---|
| `Flow_Dispatcher.xaml` | `Runtime\out`의 JSON을 `Runtime\processing`으로 옮기고(선점) Orchestrator 큐 `CallCenter_Calls`에 항목으로 넣는다 |
| `Flow_Performer.xaml` | 큐에서 항목을 하나씩 꺼내 JSON을 읽고 엑셀에 기입한 뒤, 성공/업무 오류/시스템 오류를 큐 항목 상태로 기록한다 |

실행 순서: (1) Orchestrator에서 큐 만들기 → (2) Flow_Dispatcher 실행 → (3) Flow_Performer 실행.

준비물: Orchestrator 폴더에 큐 `CallCenter_Calls` 생성 (Automatic retry 3회 권장, Unique reference는 끔).
Dispatcher 실행 전에 `Runtime\out`에 JSON 7개가 있고 `Runtime\report`에 보고서가 없는 상태여야 합니다.

## 작업 폴더 설정 (경로)
- 모든 입출력 경로는 `baseDir` 한 곳에서 정한다. 환경변수 `CALLCENTER_BASE`가 있으면 그 폴더, 없으면 Studio가 연 프로젝트 폴더(`uipath\`)를 쓴다.
- Studio에서 실행할 때는 설정이 필요 없다. 작업 스케줄러나 Robot으로 실행할 때만 `CALLCENTER_BASE`를 지정한다.
- 폴더 아래에 `Runtime\out`(입력 JSON), `Runtime\processing`, `Runtime\out\processed`, `Runtime\out\error`, `Runtime\report`, `Runtime\template`이 있어야 한다. `Runtime\template`만 저장소에 올라가고 나머지는 실행 중에 쓰는 폴더라 올라가지 않는다(`.gitignore`). 처음 받았으면 빈 폴더를 만들고 `samples\test_cases\*.json`을 `Runtime\out`에 복사해 시험한다.

## 서버(백엔드) 연동 시험
샘플 음성 3개와 결과 JSON 3개를 서버에 보내 정상·확인필요·실패 경로를 확인한다.

| 파일 | 역할 |
|---|---|
| `Main_ServerTest.xaml` | 시험 실행 진입점 (샘플 3건 전송) |
| `Flow_ServerSend.xaml` | 파일 1건 전송: 등록(R-04) → QUEUED(R-05) → 성공·확인필요는 전사(R-06)+분석(R-07), 실패는 로그(R-08, `status=FAIL`+`stage`) |
| `Flow_Api_Register.xaml` | 음성 파일 업로드(multipart, SHA-256 계산, 409 중복 응답 해석) |
| `Flow_Api_Call.xaml` | JSON 요청 한 번 보내기(PATCH/PUT/POST/GET) |

- 설정은 환경변수로 받는다. `CALLCENTER_API_URL`(서버 주소, 없으면 `http://localhost:8000`), `CALLCENTER_API_KEY`(API 키). 키는 파일·로그에 남기지 않는다.
- 환경변수를 바꾼 뒤에는 Studio를 다시 열어야 적용된다.
- 실행: Studio에서 `Main_ServerTest.xaml`을 열고 **Run File**.
- 같은 샘플을 다시 보내면 서버가 409(중복)로 답하고, 상태에 따라 이어서 진행하거나 건너뛴다.
- 샘플 음성(`samples\audio`)은 무음 wav이며, 파일명은 `{yyyyMMdd_HHmmss}_{담당자}_{고객사}.wav` 규칙을 따른다.
- 서버에 시험용 건이 실제로 등록되므로 운영 DB에는 쓰지 않는다.

### 재처리 시험
- `Main_RetryTest.xaml`을 **Run File**로 실행한다. 웹 화면에서 재처리를 요청해 둔 건(`RETRY_REQUESTED`)이 있어야 대상이 나오고, 없으면 0건으로 끝난다.
- 순서: 대상 조회(R-09) → 음성 다운로드(R-10, `Runtime\processing`에 저장) → 큐 재등록(Reference = `call_id-retryN`) → QUEUED 보고(R-05).
- 큐에 넣으려면 Studio가 Orchestrator에 연결돼 있고 `CallCenter_Calls` 큐가 있어야 한다.
