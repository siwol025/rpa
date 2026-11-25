# ③ UiPath GenAI & STT 파이프라인

통화 녹음 파일 → 음성인식(STT) → 화자 정제 → 개인정보 마스킹 → GenAI 분류·요약 → 결과 JSON 저장.

> **상태: 초안.** 현재 키·실제 녹음이 없어 Python 레퍼런스 구현과 더미 데이터로 검증한 상태입니다. UiPath xaml(Step1~3, Main)은 Studio에서 작성이 남아 있습니다. 실제 CLOVA 응답·실제 LLM 결과로 확인하기 전까지 아래 "알려진 한계"를 꼭 읽어 주세요.

## 1. 처리 흐름

```
음성 파일 (calls\in)
  → Step1  CLOVA Speech 호출(STT)            step1\clova_stt.py   (xaml: Step1_STT.xaml)
  → Step2  화자 매핑·발화 병합·전문 생성      step1\parse_clova.py
  → PII    정규식 마스킹                      step2\mask_pii.py
  → Step3  프롬프트 조립 → GenAI → 검증·재시도 step2\analyze.py
  → 결과 JSON (call_schema.json 형식)         step2\run_dummy.py (조립)
  → 성공: calls\out / 처리 후 원본 calls\done, 실패: calls\failed
```

실패한 건도 `status=FAILED`와 `error.stage/reason`을 담은 같은 구조의 JSON으로 출력합니다.

## 2. 폴더 구성

| 경로 | 내용 |
|---|---|
| `config.json` | 실제 키·경로·STT 설정 (**.gitignore 등록, 공유 금지**) |
| `config.example.json` | 키 없는 양식 (공유용) |
| `step1\` | STT 호출(`clova_stt.py`), 응답 파싱·화자 매핑(`parse_clova.py`), 테스트, `Step1_STT_설계.md`(xaml 설계서) |
| `step2\` | 마스킹(`mask_pii.py`), 프롬프트 조립·검증(`analyze.py`), 더미 파이프라인(`run_dummy.py`), 테스트 |
| `prompts\` | `prompt_v1.txt`, `prompt_v1_1.txt`(마스킹 토큰 목록 추가), **`prompt_v1_2.txt`(채택: v1_1에서 '불만 우선' 규칙을 약하게 — COMPLAINT는 불만이 통화의 주된 용건일 때만)** |
| `schema\` | `call_schema.json`(출력 스키마 v1.0), `sample_success.json`, `sample_failed.json` |
| `test\` | 더미 CLOVA 응답, 녹음 대본(`녹음_대본_5건.md`)과 경계 사례 가상 대본(`경계사례_대본_6건.md`), 정확도 평가표, 더미 결과(`out\`) |
| `calls\` | `in` 입력 / `out` 결과 / `done` 처리 완료 / `failed` 실패 |

## 3. 필요 환경

- Python 3 + `pip install requests jsonschema` (키로 실제 호출할 때 `requests`, 스키마 검증에 `jsonschema`)
- UiPath Studio (xaml 작성·실행 시). Python 폴백을 쓰면 UiPath.Python.Activities 패키지 필요
- NAVER Cloud Platform의 CLOVA Speech Invoke URL·Secret Key (실제 STT 호출 시)
- GenAI: UiPath GenAI Activities(AI Units 필요) 또는 OpenAI API HTTP 호출 중 하나

## 4. 설정 (`config.json`)

`config.example.json`을 복사해 `config.json`을 만들고 아래 두 값을 채웁니다.

```
clova_invoke_url : CLOVA Speech Invoke URL
clova_secret_key : Secret Key   ← 절대 코드·로그·결과 JSON·공유 폴더에 넣지 않기
```

그 외: `stt`(언어 `ko-KR`, `completion` sync/async, 화자 수 2, 폴링 5초×최대 60회), `paths`(입력·출력·완료·실패 폴더).

## 5. 키·녹음 없이 돌려보기 (더미)

```
cd step1
python parse_clova.py --in ..\test\sample_response_1.json     # 화자 매핑·전문 생성
python test_step1.py                                           # 25개 테스트

cd ..\step2
python run_dummy.py                                            # 더미 2건 → test\out\*_result.json
python run_dummy.py --messy                                    # LLM이 ```json 코드펜스를 붙이는 경우 흉내
python test_step2.py                                           # 32개 테스트
```

더미 `sample_response_1/2.json`은 `test\녹음_대본_5건.md`의 1번(질의)·2번(불만)을 CLOVA 응답 형태로 만든 것입니다. 이메일·전화번호가 들어 있어 마스킹 테스트에 쓰입니다(모두 가상 값).

## 6. 실제 키·녹음이 생기면

1. `config.json`에 키 입력.
2. 응답 구조 확인 (원본 응답이 `sample_response.json`으로 저장됨):
   `python clova_stt.py --audio ..\test\call_01_질의.m4a --raw-out ..\test\sample_response.json`
3. 파서 확인: `python parse_clova.py --in ..\test\sample_response.json` — 안 되면 `parse_clova.py`의 `extract_segments()`를 실제 키 이름·시간 단위에 맞게 수정.
4. `Step1_STT_설계.md`를 따라 Studio에서 xaml 작성, Python 결과와 비교.
5. 녹음 5개로 실행 후 `test\정확도_평가표.xlsx`에 결과 입력.

## 7. 입력·출력

- **입력:** `calls\in`의 음성 파일. 운영에서는 서버·④와 맞춰 **`.wav`·`.mp3`**를 씁니다(③의 `clova_stt.py`는 `.m4a .aac .ogg .flac .mp4`도 CLOVA에 보낼 수 있지만, 실제 지원 형식은 CLOVA 콘솔 가이드로 확인 필요). 폴더 위치는 `config.json`의 `paths`로 바꿀 수 있습니다(`uipath/README.md`의 "입출력 폴더를 설정으로 바꾸기").
- **출력:** `schema\call_schema.json` 형식 JSON. 주요 필드: `status`(SUCCESS/NEEDS_REVIEW/FAILED), `type`(INQUIRY 질의 / COMPLAINT 불만 / SUGGESTION 건의 / TRAINING 교육 내용 / OTHER 기타 문의), `type_confidence`, `summary`, `follow_up`, `keywords`, `entities`, `transcript`, `pii`, `processing`, `error`
- `NEEDS_REVIEW`: 유형 확신도 0.6 미만이거나 화자 구분이 불확실(`speaker_confidence=LOW`)한 건.
- 예시: `schema\sample_success.json`, `schema\sample_failed.json`
- **백엔드 적재 변환(참고용):** `step2\to_backend.py`는 백엔드 로봇 API(R-07)가 확정되기 전의 변환 기준입니다. 실제 운영 흐름에서는 ④가 결과 JSON을 **그대로** R-07에 보내고 서버가 같은 계약(`call_schema.json` v1.0)으로 받으므로, 이 변환기는 필드 대응을 확인하는 참고용입니다. 테스트: `python test_to_backend.py`.
  - 유형은 `type_label`(한글)을 `category`로, `customer_question`/`agent_action`/`customer_company`는 `question_summary`/`action_summary`/`client_company`로 보냅니다.
  - `duration_sec`은 정수 초로 반올림하고, `entities`는 `[{type, value}]` 배열 그대로, `needs_review`는 STT 판정(`status == NEEDS_REVIEW`)을 그대로 따릅니다.
  - 전사 구간 키는 `start_sec`/`end_sec`로 확정(백엔드 협의 완료)이라 이름을 바꾸지 않고 그대로 보냅니다.

## 8. 화자 매핑·마스킹 규칙

- **상담원 판정:** 첫 발화에 인사 키워드("고객지원센터", "고객센터", "상담원", "무엇을 도와")가 있는 화자 → 없으면 먼저 말한 화자 + 안내 문구 빈도. 근거가 약하거나 규칙이 어긋나면 `speaker_confidence=LOW`.
- **마스킹 토큰:** `[RRN]` 주민번호 / `[CARD]` 카드 / `[PHONE]` 전화 / `[EMAIL]` 이메일 / `[ACCOUNT]` 계좌 / `[NAME]` 이름 / `[ADDRESS]` 주소 / `[PASSWORD]` 비밀번호 / `[BIRTH]` 출생연도. 적용 순서는 화자 분리 → 마스킹 → GenAI.

## 9. 알려진 한계 (중요)

- **STT 응답 구조는 실제 응답 5건으로 확인했습니다.** 엔드포인트(`/recognizer/upload`), `segments[]`/`text`/`speaker.label` 필드, 시간 단위(ms)가 가정과 맞았습니다(11/24 Python 호출). 다만 UiPath(Studio)에서 실제 CLOVA를 호출해 확인한 적은 없고, Studio 쪽은 가짜 CLOVA 서버와 저장된 응답으로만 검증했습니다.
- **분류 결과는 아직 검증되지 않았습니다.** `step2\analyze.py`의 `mock_llm`은 키워드 규칙으로 JSON을 흉내 내는 가짜 LLM입니다. 프롬프트 조립·파싱·검증·재시도·스키마 조립 같은 연결 부분을 이 가짜 LLM으로 검증했습니다. 분류 정확도는 실제 LLM으로 가상 대본에서만 확인했고(아래 v1_2 항목), 실제 통화 녹음 기준 평가는 아직 없습니다.
- **마스킹은 정규식 기반입니다.** 숫자를 한글로 읽어 적은 경우("공일공…")는 못 잡고, 이름은 "상담원 ○○○입니다"·"성함은 ○○○" 같은 문맥만 잡습니다. 계좌번호는 하이픈 구분 형식만 대상입니다.
- **프롬프트는 v1_2를 채택했습니다.** 평가표 오분류 결과를 반영한 것이 아니라, 'v1_1은 문제 제기가 조금만 있어도 불만으로 분류한다'는 관찰(5건 중 4건이 불만)에 따라 규칙을 완화한 것입니다. 효과는 입증되지 않았습니다. AI Hub 샘플 5건(Groq `openai/gpt-oss-120b`)으로 돌려 보니 정답이 있는 3건 기준 정확도가 v1_1 2/3 → v1_2 1/3이었고, 정답 라벨 자체가 의심스러워 우열을 판단할 수 없습니다. 상세는 `test\정확도_평가표_v2.xlsx`의 `GenAI_검수_gptoss`(v1_1)·`GenAI_검수_v1_2` 시트.
- **가상 대본 평가 결과(유형 정확도):** 정답이 정해진 가상 대본으로 `step2\run_script_eval.py`(STT 없이 대사 → 마스킹 → 프롬프트 → 모델, Groq `openai/gpt-oss-120b`)를 돌렸습니다.
  - 기본 대본 5건(`test\녹음_대본_5건.md`, 유형별 1건): v1_1·v1_2 모두 5/5. 분류 신호가 뚜렷한 쉬운 기준선이라 두 프롬프트를 구분하지 못합니다.
  - 경계 사례 6건(`test\경계사례_대본_6건.md`): v1_1 5/6, v1_2 6/6. 정의 일치형 5건(약한 불만이 섞인 질의, 질문이 섞인 불만, 감정만 강한 질의, 애매한 건의, 건의로 시작한 불만)은 두 프롬프트 모두 5/5이고, 갈린 건 정의 의존형 1건뿐입니다. 질의 중심 통화에 정정 요구가 한 번 섞인 사례(edge_03)를 v1_1은 COMPLAINT, v1_2는 INQUIRY로 분류했고, v1_2의 규칙 완화가 의도한 방향으로 동작한 사례입니다.
  - **해석의 한계:** 위 사례의 정답은 채택한 v1_2 정의를 따라 작성자가 정했고 팀 확인을 거치지 않았습니다. 이런 혼합 통화를 질의로 볼지 불만으로 볼지는 팀의 정의 결정 사항이라, v1_2가 더 정확하다고 단정할 수 없습니다. 표본은 경계 6건·기본 5건뿐이고 STT 오류·화자 분리 실패의 영향은 빠져 있습니다. 판단 근거는 모델의 설명이 아니라 응답의 핵심 질문·요약과 프롬프트 규칙에서 추정한 것입니다. 상세는 평가표 v2의 `대본_유형평가`·`경계사례_유형평가` 시트.
  - 실제 통화 녹음과 정의가 합의된 경계 사례로 다시 평가해야 분류 정확도를 말할 수 있습니다.
- 기본 프롬프트 경로는 `prompt_v1_2.txt`로 바꿨습니다(`run_genai_test.py`, `run_folder.py`, `uipath_port\build_xaml*.py`·`make_fixtures.py`, `Step3_Analyze_설계.md`). 생성 스크립트를 다시 실행해 Studio 프로젝트의 `Main_*.xaml`·`Step8_Folder_Test.xaml`·`prompts\`도 갱신했습니다. `analyze.py`의 기본값(`prompt_v1.txt`)은 모의 LLM 테스트용이라 그대로 뒀습니다.
- GenAI 연결 테스트는 `config.json`의 `openai.base_url`로 OpenAI 호환 서버(예: Groq)를 지정할 수 있고, `run_genai_test.py --max-output-tokens`로 출력 한도를 올릴 수 있습니다(추론 모델은 추론 토큰도 포함).
- 빈 파일·미지원 형식·STT 실패·모델 응답 검증 실패는 구현하고 `Step8_Folder_Test`로 검증했습니다(14건 일치, 가짜 CLOVA·모의 응답 기준). 파일 손상 같은 예상 밖 예외의 안전장치는 직접 확인하지 못했습니다. 단계별 로그는 Studio 로그(건별·요약)만 남기고 별도 로그 파일은 만들지 않습니다.
- UiPath 프로젝트(`stt/uipath`)에 단계별 테스트(Step1~8)와 전체 흐름(`Main_Step1to7`)·운영용 폴더 처리(`Main_Folder`)가 구현돼 있고 Python과 같은 결과가 나옴을 확인했습니다(자세한 내용은 `stt/uipath/README.md`). 실제 CLOVA·Content Generation 연동은 Studio에서 검증하지 못했습니다.
