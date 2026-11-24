# UiPath 변환 검증 도구 (step2/uipath_port)

Python 로직을 UiPath `Invoke Code`(VB.NET)로 옮길 때, **같은 입력에서 같은 결과가 나오는지** 비교하는 도구입니다. 비교 대상은 `stt/uipath` 프로젝트입니다.

## 구성
| 경로 | 역할 |
|---|---|
| `snippets\*.vb` | `Invoke Code`에 들어가는 VB 코드 **원본**. XAML은 이 파일에서 생성됩니다 |
| `common.py` | 경로·Python 기준 결과(정답) 계산·비교 함수. 정답은 `analyze.py`·`parse_clova.py`·`mask_pii.py`·`run_dummy.py`·`clova_stt.py`·`run_folder.py`가 직접 계산합니다 |
| `make_fixtures.py` (+`fixtures_stt.py`, `fixtures_folder.py`) | 단계별 테스트 입력과 정답을 `stt/uipath/test_data`에 만듭니다 |
| `vb_check.py` | VB 코드를 이 PC에서 컴파일·실행해 Python 정답과 비교 (Studio 없이 확인) |
| `build_xaml*.py` | 코드 조각을 넣어 `stt/uipath`의 XAML(단계별 테스트, 전체 흐름, `Run_All`)을 생성 |
| `compare_uipath.py` | Studio에서 실행한 결과를 Python 정답과 비교 |
| `fake_clova.py` | 로컬 가짜 CLOVA 서버 (STT 호출·폴더 처리 테스트용. 실제 CLOVA에 연결하지 않음) |

## 준비
- Python 3 (`requests`, `jsonschema`, `openpyxl`), Windows 기본 VB 컴파일러(`vbc.exe`, .NET Framework 4)와 Newtonsoft.Json 10.0.3(`%USERPROFILE%\.nuget\packages`)이 있으면 `vb_check.py`가 동작합니다. 없으면 건너뜁니다.
- UiPath 프로젝트 위치: 기본 `stt\uipath`, 다른 곳이면 환경변수 `UIPATH_PROJECT`.
- **AI Hub 샘플 데이터가 필요합니다 (저장소에 없음).** 테스트 입력을 만들 때 아래 로컬 파일을 씁니다.
  - `stt\test\out\stt\S0000772x_raw.json` — 실제 CLOVA 응답 5건 (`step1\clova_stt.py`로 만든 것)
  - `stt\uipath\genai_test\S0000772x_response.txt` — 모델 응답 5건 (`Main_Step123`/`Main_Step1to7` 실행 결과)
  - `stt\test\out\stt\genai\S0000772x_transcript.txt` — 마스킹된 전사본
  AI Hub 데이터는 재배포가 제한될 수 있어 올리지 않았습니다.

## 사용
```
cd stt\step2\uipath_port
python make_fixtures.py     # 입력·정답 생성 (stt\uipath\test_data)
python vb_check.py          # VB 코드 vs Python  (fake_clova.py 가 떠 있지 않을 때 실행)
python build_xaml.py        # stt\uipath 의 XAML 생성

# Studio 에서 Run_All.xaml 을 Run File 로 실행한 뒤 (Step6·8 전에 가짜 서버를 켜 둠)
python fake_clova.py --port 8765 --raw ..\..\uipath\test_data\step6\_server\raw_ok.json --raw-high ..\..\uipath\test_data\step6\_server\raw_high.json
python compare_uipath.py --step all     # Step1~8
python compare_uipath.py --step main7   # Main_Step1to7 (실제 모델 호출 결과)
```
`vb_check.py`와 `fake_clova.py`는 같은 포트(8765)를 쓰니 동시에 켜지 마세요 (요청이 섞입니다).

## 알려진 차이와 한계
- JSON 파서가 Python보다 너그럽고, 글자 수는 UTF-16 단위, 호출 예외 이름이 Python과 다릅니다.
- 시간 값 반올림(`round(ms/1000, 2)`)은 Python과 같게 정수 연산으로 구현했습니다 (경계 값 21개 일치 확인).
- 검증한 것은 코드 조각의 로직(.NET Framework)과 Studio 실행 결과입니다. 실제 CLOVA·실제 모델의 반응, 예상 밖 예외 경로는 검증하지 못했습니다.
