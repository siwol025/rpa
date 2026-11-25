# ③ UiPath GenAI·STT 프로젝트 (stt/uipath)

음성 파일 → STT → 파싱·화자 매핑 → 개인정보 마스킹 → 프롬프트 → 모델 호출·검증·재시도 → 결과 JSON(`call_schema.json` v1.0) → 폴더 정리까지를 UiPath로 옮긴 프로젝트입니다.
Python 구현(`stt/step1`, `stt/step2`)과 **같은 입력에서 같은 결과**가 나오는지 단계마다 비교하며 옮겼습니다. 팀의 ④ RPA 코어(저장소 루트 `uipath/`)와는 별개의 프로젝트입니다. 이 프로젝트가 `{call_id}.json`을 `out` 폴더에 떨어뜨리면 ④가 읽어 엑셀에 기입합니다.

## 폴더 구조 및 입출력 경로
- **작업 기준 폴더:** `<프로젝트 폴더>\calls` (저장소 기준 `stt/uipath/calls`, 로컬 예시 `C:\Users\Woori\Documents\UiPath_GenAI_STT\uipath\calls`). `Main_Folder.xaml`이 현재 작업 폴더(프로젝트 폴더) 아래의 `calls`를 쓰므로, 저장소 루트나 `stt\calls` 같은 다른 위치에 파일을 넣으면 읽지 못합니다.
- **하위 폴더:** `in`(입력), `out`(결과 JSON), `done`(처리한 원본), `failed`(실패한 원본). 실행할 때 없으면 `Main_Folder.xaml`이 만듭니다. `calls\`는 `.gitignore` 대상이라 저장소에 올라가지 않습니다.
- **처리 흐름:** `calls\in`의 파일을 `Main_Folder.xaml`로 처리해 성공(`SUCCESS`/`NEEDS_REVIEW`)이면 `done`, 실패(`FAILED`)면 `failed`로 옮기고, 어느 쪽이든 `calls\out\{call_id}.json`을 만듭니다. `call_id`는 `날짜_시각_순번`(예: `20261125_124453_001`) 형식이고, 같은 이름이 있으면 덮어쓰지 않고 번호를 붙입니다. 실패 건도 `status=FAILED` JSON이 생성됩니다.

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

그 밖의 워크플로: `Main_Step1to7.xaml`(저장된 CLOVA 응답으로 전체 흐름, `sttMode`=`live`이면 실제 호출), `Main_Step1to5.xaml`, `Main_Step123.xaml`(앞부분 생략한 축소 흐름), `Run_All.xaml`(Step1~8 테스트를 차례로 실행하고 `Main_Step1to7`까지). `Main.xaml`은 처음의 모델 호출 연결 테스트입니다.

테스트 입력·정답·비교 도구는 `stt/step2/uipath_port/`에 있습니다 (사용법은 그쪽 README). `Invoke Code`의 VB 코드 원본도 거기(`snippets\`)에 있고, XAML은 그 파일에서 생성됩니다. **XAML을 직접 고치면 다음 생성 때 사라지니 `snippets\`나 `build_xaml*.py`를 고치세요.**

## 알아 둘 점
- 테스트 데이터(`test_data`, `genai_test` 등)는 AI Hub 샘플에서 만들어서 저장소에 올리지 않았습니다 (`stt/step2/uipath_port/README.md`의 준비 방법 참고).
- 사용하는 프롬프트는 `prompts\prompt_v1_2.txt`이고 `stt\prompts\prompt_v1_2.txt`의 복사본입니다(`prompt_v1_1.txt`는 이전 버전으로 남아 있음). 프롬프트를 고치면 `make_fixtures.py`를 실행해 다시 복사하세요.
- JSON 파서가 Python보다 너그럽고(작은따옴표·주석·끝 쉼표 허용), 글자 수는 UTF-16 단위로 셉니다. 모델·STT 호출 예외는 `호출 오류(예외 형식 이름)`으로 기록하며 형식 이름이 Python과 다릅니다 (HTTP 상태·JSON 오류 문구는 같음).
- 실제 CLOVA 호출과 예상 밖 예외 안전장치는 이 PC에서 직접 검증하지 못했습니다 (가짜 서버·정상 경로만 검증).
