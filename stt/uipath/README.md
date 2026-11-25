# ③ UiPath GenAI·STT 프로젝트 (stt/uipath)

음성 파일 → STT → 파싱·화자 매핑 → 개인정보 마스킹 → 프롬프트 → 모델 호출·검증·재시도 → 결과 JSON(`call_schema.json` v1.0) → 폴더 정리까지를 UiPath로 옮긴 프로젝트입니다.
Python 구현(`stt/step1`, `stt/step2`)과 **같은 입력에서 같은 결과**가 나오는지 단계마다 비교하며 옮겼습니다. 팀의 ④ RPA 코어(저장소 루트 `uipath/`)와는 별개의 프로젝트입니다. 이 프로젝트가 `{call_id}.json`을 `out` 폴더에 떨어뜨리면 ④가 읽어 엑셀에 기입합니다.

## 폴더 구조 및 입출력 경로
- **작업 기준 폴더:** `<프로젝트 폴더>\calls` (저장소 기준 `stt/uipath/calls`, 예: `D:\work\rpa\stt\uipath\calls`). `Main_Folder.xaml`이 현재 작업 폴더(프로젝트 폴더) 아래의 `calls`를 쓰므로, 저장소 루트나 `stt\calls` 같은 다른 위치에 파일을 넣으면 읽지 못합니다.
- **하위 폴더:** `in`(입력), `out`(결과 JSON), `done`(처리한 원본), `failed`(실패한 원본). 실행할 때 없으면 `Main_Folder.xaml`이 만듭니다. `calls\`는 `.gitignore` 대상이라 저장소에 올라가지 않습니다.
- **처리 흐름:** `calls\in`의 파일을 `Main_Folder.xaml`로 처리해 성공(`SUCCESS`/`NEEDS_REVIEW`)이면 `done`, 실패(`FAILED`)면 `failed`로 옮기고, 어느 쪽이든 `calls\out\{call_id}.json`을 만듭니다. `call_id`는 `날짜_시각_순번`(예: `20261125_124453_001`) 형식이고, 같은 이름이 있으면 덮어쓰지 않고 번호를 붙입니다. 실패 건도 `status=FAILED` JSON이 생성됩니다.

### 입출력 폴더를 설정으로 바꾸기 (`config.json`의 `paths`)
기본은 프로젝트 폴더 아래 `calls\in|out|done|failed`입니다. ④(RPA 코어)나 다른 PC와 폴더를 맞춰야 하면 `config.json`에 `paths`를 넣으면 됩니다(`config.example.json` 참고). `Main_Folder.xaml`은 시작할 때 `입출력 폴더 정하기` 단계에서 이 값을 읽습니다(코드: `snippets\read_paths.vb`, Python 기준: `run_folder.resolve_folders`).

```json
"paths": {
  "input_dir": "D:\\robot\\stt_in",
  "output_dir": "D:\\robot\\stt_out",
  "done_dir": "D:\\robot\\stt_done",
  "failed_dir": "D:\\robot\\stt_failed"
}
```
- 항목마다 따로 쓸 수 있고, 없는 항목은 기본값(`calls\...`)입니다.
- **상대 경로**는 프로젝트 폴더(`stt\uipath`) 기준, **절대 경로**는 그대로 씁니다.
- 값이 비었거나 `<…>`·`여기에_…`로 시작하는 자리표시자이거나 문자열이 아니면 기본값입니다. 설정 파일이 없거나 JSON이 깨져 있어도 오류 없이 기본값으로 동작합니다.
- 설정 파일 위치는 아래 "`config.json` 경로"와 같습니다(`CLOVA_CONFIG` 또는 `프로젝트 폴더\..\config.json`). 테스트 워크플로(`Step8_Folder_Test`)는 임시 폴더를 쓰므로 이 설정을 읽지 않습니다.

**④(RPA 코어)와 같은 폴더 쓰기** (③ 설정만 바꾸고 ③ 코드는 그대로)
`stt\config.uipath-folders.example.json`의 `paths` 블록을 `stt\config.json`에 합치면, ③이 ④ `Config/config.json`과 **같은 폴더**를 씁니다. 경로는 ③ 프로젝트 폴더(`stt\uipath`) 기준 상대 경로라 저장소를 받은 PC에서 그대로 동작합니다.

| 용도 | ③ 설정 (`paths`) | 가리키는 폴더 (`<저장소>\` 기준) | ④ 설정 (`Config/config.json`) |
|---|---|---|---|
| 음성 입력 | `input_dir` | `uipath\Runtime\processing` | `processingFolder` |
| 완료 음성 | `done_dir` | `uipath\Runtime\done` | `doneFolder` |
| 실패 음성 | `failed_dir` | `uipath\Runtime\failed` | `failedFolder` |
| 결과 JSON | `output_dir` | `stt\uipath\calls\out` | `outFolder` |

**주의**
- ③은 처리한 음성을 `done`(SUCCESS·NEEDS_REVIEW) 또는 `failed`(FAILED)로 **옮깁니다**. ④ Performer도 같은 규칙으로 옮기는데 음성 이동이 `ContinueOnError=True`라, ③이 먼저 옮겼어도 오류 없이 지나가고 최종 위치는 같습니다.
- ④ Dispatcher는 음성을 `processing`으로 옮긴 뒤 서버 등록(R-04)에 그 파일을 읽습니다. **그 사이에 ③이 실행되면** ③이 파일을 먼저 `done`/`failed`로 옮겨 등록이 실패할 수 있으니, ③(`stt\uipath\Main.xaml`)은 Dispatcher가 도는 중에 실행하지 마세요(등록은 보통 몇 초).
- ④ Dispatcher의 `5. ③ 입력 폴더로 음성 복사` 단계(#30)는 기본으로 음성 사본을 `stt\uipath\calls\in`에 복사합니다. 위 설정에서는 ③이 그 폴더를 읽지 않아 사본이 쌓이기만 하므로, 환경변수 `STT_INPUT_DIR`를 `uipath\Runtime\processing`의 절대 경로로 지정하면 같은 폴더끼리라 복사가 실패(경고 로그)하며 사본이 생기지 않습니다.
- ④는 결과 JSON의 `source.file_name`이 음성 파일명과 같은 것을 찾으므로, `output_dir`에 같은 이름의 오래된 결과가 남아 있지 않게 ④가 처리 후 옮기는 동작을 유지해야 합니다.
- 서버와 ④는 **wav·mp3**만 접수합니다(③은 m4a 등도 CLOVA에 보낼 수 있지만 운영 입력은 wav·mp3로 맞추세요).
- 기본값(`paths`가 없을 때)은 예전처럼 `calls\in|out|done|failed`이고, ③ 코드는 이 설정으로 달라지는 것이 없습니다.

## 처리 흐름 도식 (`Main_Folder.xaml`, 음성 한 건 기준)
```
 [calls\in]  음성 파일(.wav .mp3 .m4a …)
     │  Main_Folder.xaml ─ 파일마다 반복 (한 건에서 예외가 나도 그 건만 FAILED 처리)
     ▼
┌─ ① STT 호출 ───────────────────────── clova_call.vb ─┐        ┌───────────────────────────┐
│ 음성 검사(없음/0바이트/확장자)                          │◄──────│ config.json 읽기           │
│ POST {clova_invoke_url}/recognizer/upload              │ 키·URL │ (아래 "config.json 경로")   │
│   헤더 X-CLOVASPEECH-API-KEY, 노이즈 필터·화자 2명 옵션  │        └───────────────────────────┘
│ 완료 전이면 5초 간격 조회 (최대 60회)                    │
└───────────────┬────────────────────────────────────────┘
        실패 ──┼──► INPUT / STT 오류 ──────────────────────────────┐
                ▼ COMPLETED                                          │
┌─ ② 파싱·화자 매핑 ───────────────── parse_clova.vb ─┐              │
│ 같은 화자의 연속 발화 병합                             │              │
│ 상담원/고객 분리 (인사 키워드 우선), 근거 약하면 LOW    │              │
│ → "[상담원] … / [고객] …"                              │              │
└───────────────┬──────────────────────────────────────┘              │
                ▼                                                      │
┌─ ③ 개인정보 마스킹 ───────────────────── mask_pii.vb ─┐             │
│ 이메일·카드·주소·이름 등을 [EMAIL] [CARD] … 로 치환     │             │
└───────────────┬──────────────────────────────────────┘             │
                ▼                                                      │
┌─ ④ 프롬프트 조립 ──────────────────── build_prompt.vb ─┐            │
│ prompts\prompt_v1_2.txt → [SYSTEM] / [USER TEMPLATE]    │            │
│ {{TRANSCRIPT}} 자리에 마스킹된 전사본                     │            │
└───────────────┬───────────────────────────────────────┘            │
                ▼                                                      │
┌─ ⑤ 모델 호출 (최대 3회: 최초 1 + 재시도 2) ──────────────┐           │
│ Content Generation 커넥터 (systemPrompt + userPrompt)    │           │
│ 응답 검증 validate_response.vb (JSON·필수키·유형·길이)    │           │
│   통과 → 다음 단계      실패 → 재시도 → 3회 실패 시 VALIDATION│───────┤
└───────────────┬───────────────────────────────────────┘           │
                ▼                                                      ▼
┌─ ⑥ 결과 JSON 조립·상태 판정 ────────── assemble_result.vb ─────────────────┐
│ 확신도 < 0.6 또는 화자 LOW → NEEDS_REVIEW │ 정상 → SUCCESS │ 오류 → FAILED │
└───────────────┬───────────────────────────────────────────────────────────┘
                ▼
   calls\out\{call_id}.json  (실패 건도 status=FAILED JSON 생성)
                ▼
   원본 이동:  SUCCESS · NEEDS_REVIEW → calls\done   /   FAILED → calls\failed
```
VB 코드 원본은 `stt/step2/uipath_port/snippets/`에 있습니다(위 도식의 `*.vb`). Python 원본과의 대응은 아래 "단계별 테스트" 표를 보세요.

### `config.json` 경로
**UiPath(Studio)가 읽는 위치** (`Main_Folder.xaml`, `Main_Step1to7.xaml`):
1. 환경변수 `CLOVA_CONFIG`가 있으면 그 파일
2. 없으면 `<프로젝트 폴더>\..\config.json` → 저장소 기준 `stt/config.json`

- 읽는 값은 `clova_invoke_url`, `clova_secret_key`, `stt{…}`(언어·화자 수·노이즈 필터·조회 간격과 횟수)와 입출력 폴더 `paths{…}`(위 "입출력 폴더를 설정으로 바꾸기")입니다. 모델 호출은 Content Generation 커넥터(UiPath 연결)가 하므로 UiPath 쪽에는 모델 키가 없습니다.
- 프로젝트를 `stt/uipath`가 아닌 다른 폴더에서 열면 2번 경로가 틀어져 "config.json을 읽을 수 없음"이 납니다. 이때는 `CLOVA_CONFIG`로 경로를 지정하세요.

**Python이 읽는 위치**: 같은 `stt/config.json`입니다. `step1/clova_stt.py`와 `step2/openai_llm.py`가 기본으로 이 파일을 쓰고(`--config`로 변경), `config.json`의 `openai` 항목(`api_key`, `model`, `base_url` 등)은 Python 평가·검증용이라 UiPath 흐름에는 쓰이지 않습니다.

**테스트용**: `uipath/test_data_run/step8/config.json`(가짜 CLOVA 서버 주소)을 `Step8_Folder_Test.xaml`이 읽습니다.

**공유**: 실제 키가 든 `stt/config.json`은 `.gitignore` 대상이라 저장소에 올라가지 않습니다. 양식은 `stt/config.example.json`입니다.

## 운영 흐름: `Main_Folder.xaml`
`calls\in`의 음성 파일을 이름순으로 처리하고 결과를 `calls\out`(결과 JSON), `calls\done` / `calls\failed`(원본)로 정리합니다.
- 결과 JSON은 성공이든 실패든 `out\{call_id}.json`으로 저장합니다 (실패는 `status=FAILED`와 `error.stage/reason`).
- 원본: `SUCCESS`/`NEEDS_REVIEW`는 `done`, `FAILED`(STT 실패·입력 오류·분석 실패)는 `failed`. 같은 이름이 있으면 `이름_1.확장자`로 저장합니다.
- `.`/`~$`로 시작하는 파일, `Thumbs.db`, `desktop.ini`, 하위 폴더는 건드리지 않습니다.
- 이동에 실패하면 파일을 제자리에 두고 경고만 남깁니다. 예상 밖의 예외는 진행 중이던 단계(`STT`/`PII`/`GENAI`)의 실패 건으로 기록하고 계속합니다.

### 실행 전 준비
- **CLOVA 설정:** 환경변수 `CLOVA_CONFIG`가 가리키는 파일, 없으면 `stt\config.json`(프로젝트 폴더의 상위)에서 `clova_invoke_url`, `clova_secret_key`를 읽습니다. 키는 저장소에 올리지 않습니다 (`config.example.json` 참고). **프로젝트를 `uipath` 폴더가 아닌 다른 경로로 열면** 상위 폴더에서 설정 파일을 찾지 못해 "config.json을 읽을 수 없음"으로 실패하니, 운영·실행 환경에서는 `CLOVA_CONFIG`로 경로를 지정하거나 설정 파일 위치를 확인하세요.
- **모델 호출:** `Content Generation`은 UiPath Integration Service 커넥터입니다. 이 프로젝트의 연결(`ConnectionId`)은 만든 사람의 Orchestrator 테넌트에 속하므로, **다른 사람이 열면 Studio에서 자신의 연결로 다시 지정**해야 합니다. 모델 이름과 온도·최대 토큰도 그 액티비티에서 지정합니다 (`genaiModel` 변수는 결과 JSON의 `processing.genai_model`에 기록됩니다). Python 쪽 `openai_llm.py`(Groq 등 OpenAI 호환 호출)는 평가·검증용이며 이 워크플로에는 연결돼 있지 않습니다.
- 실제 CLOVA 호출은 무료 인식 시간을 쓰고 음성을 외부로 보냅니다.

## 단계별 테스트
| 단계 | 옮긴 로직 | Python 원본 | 테스트 워크플로 |
|---|---|---|---|
| 6 | CLOVA STT 호출 (설정·음성 확인, 업로드, 폴링, 오류 변환) | `clova_stt.transcribe` | `Step6_SttCall_Test.xaml` (가짜 CLOVA 서버 필요) |
| 7 | STT 응답 파싱·화자 매핑·병합 | `parse_clova.to_transcript` | `Step7_Parse_Test.xaml` |
| 4 | 개인정보 마스킹 | `mask_pii.mask_transcript` | `Step4_Mask_Test.xaml` |
| 1 | 프롬프트 조립 | `analyze.build_prompt` | `Step1_BuildPrompt_Test.xaml` |
| 2 | 응답 JSON 추출·검증 | `analyze.extract_json` + `validate` | `Step2_Validate_Test.xaml` |
| 3 | 재시도 루프 | `analyze.analyze` | `Step3_Retry_Test.xaml` |
| 5 | 최종 JSON 조립·상태 판정 | `run_dummy.process` | `Step5_Assemble_Test.xaml` |
| 8 | 폴더 순회·결과 저장·파일 이동 | `run_folder.py` | `Step8_Folder_Test.xaml` (가짜 CLOVA 서버 필요) |

(번호는 만든 순서입니다. 실제 처리 순서는 6 → 7 → 4 → 1 → 모델 호출 → 2 → 3 → 5 → 결과 저장·이동.)

그 밖의 워크플로: `Main_Step1to7.xaml`(저장된 CLOVA 응답으로 전체 흐름, `sttMode`=`live`이면 실제 호출), `Main_Step1to5.xaml`, `Main_Step123.xaml`(앞부분 생략한 축소 흐름), `Run_All.xaml`(Step1~8 테스트를 차례로 실행하고 `Main_Step1to7`까지). `Main.xaml`은 프로젝트 시작 파일로, 운영 흐름 `Main_Folder.xaml`을 호출합니다(Studio의 일반 **실행** 버튼이 이 파일을 실행하므로 `calls\in` 처리가 시작됩니다). 처음의 모델 호출 연결 테스트는 `Main_ModelTest.xaml`로 옮겼습니다(5건을 호출해 `genai_test\{세션}_response.txt`만 저장). `Main.xaml`·`Main_ModelTest.xaml` 외 xaml은 `build_xaml*.py`가 생성하며, 생성 스크립트는 `Main_ModelTest.xaml`에서 Content Generation 설정을 읽습니다.

테스트 입력·정답·비교 도구는 `stt/step2/uipath_port/`에 있습니다 (사용법은 그쪽 README). `Invoke Code`의 VB 코드 원본도 거기(`snippets\`)에 있고, XAML은 그 파일에서 생성됩니다. **XAML을 직접 고치면 다음 생성 때 사라지니 `snippets\`나 `build_xaml*.py`를 고치세요.**

## 알아 둘 점
- 테스트 데이터(`test_data`, `genai_test` 등)는 AI Hub 샘플에서 만들어서 저장소에 올리지 않았습니다 (`stt/step2/uipath_port/README.md`의 준비 방법 참고).
- 사용하는 프롬프트는 `prompts\prompt_v1_2.txt`이고 `stt\prompts\prompt_v1_2.txt`의 복사본입니다(`prompt_v1_1.txt`는 이전 버전으로 남아 있음). 프롬프트를 고치면 `make_fixtures.py`를 실행해 다시 복사하세요.
- JSON 파서가 Python보다 너그럽고(작은따옴표·주석·끝 쉼표 허용), 글자 수는 UTF-16 단위로 셉니다. 모델·STT 호출 예외는 `호출 오류(예외 형식 이름)`으로 기록하며 형식 이름이 Python과 다릅니다 (HTTP 상태·JSON 오류 문구는 같음).
- 실제 CLOVA 호출과 예상 밖 예외 안전장치는 이 PC에서 직접 검증하지 못했습니다 (가짜 서버·정상 경로만 검증).
