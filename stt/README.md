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
| `prompts\` | `prompt_v1.txt`, `prompt_v1_1.txt`(초안: 마스킹 토큰 목록 추가) |
| `schema\` | `call_schema.json`(출력 스키마 v1.0), `sample_success.json`, `sample_failed.json` |
| `test\` | 더미 CLOVA 응답, 녹음 대본(`녹음_대본_5건.md`), 정확도 평가표, 더미 결과(`out\`) |
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

- **입력:** `calls\in`의 음성 파일 (`.mp3 .wav .m4a .aac .ogg .flac .mp4` — 실제 지원 형식은 CLOVA 콘솔 가이드로 확인 필요)
- **출력:** `schema\call_schema.json` 형식 JSON. 주요 필드: `status`(SUCCESS/NEEDS_REVIEW/FAILED), `type`(INQUIRY 질의 / COMPLAINT 불만 / SUGGESTION 건의 / TRAINING 교육 내용 / OTHER 기타 문의), `type_confidence`, `summary`, `follow_up`, `keywords`, `entities`, `transcript`, `pii`, `processing`, `error`
- `NEEDS_REVIEW`: 유형 확신도 0.6 미만이거나 화자 구분이 불확실(`speaker_confidence=LOW`)한 건.
- 예시: `schema\sample_success.json`, `schema\sample_failed.json`
- **백엔드 적재 변환:** `call_schema.json`(v1.0)은 그대로 두고, 백엔드와 다른 부분은 적재할 때 `step2	o_backend.py`에서 바꿉니다. 테스트: `python test_to_backend.py`.
  - 유형은 `type_label`(한글)을 `category`로, `customer_question`/`agent_action`/`customer_company`는 `question_summary`/`action_summary`/`client_company`로 보냅니다.
  - `duration_sec`은 정수 초로 반올림하고, `entities`는 `[{type, value}]` 배열 그대로, `needs_review`는 STT 판정(`status == NEEDS_REVIEW`)을 그대로 따릅니다.
  - 전사 구간 키는 `start_sec`/`end_sec`로 확정(백엔드 협의 완료)이라 이름을 바꾸지 않고 그대로 보냅니다.

## 8. 화자 매핑·마스킹 규칙

- **상담원 판정:** 첫 발화에 인사 키워드("고객지원센터", "고객센터", "상담원", "무엇을 도와")가 있는 화자 → 없으면 먼저 말한 화자 + 안내 문구 빈도. 근거가 약하거나 규칙이 어긋나면 `speaker_confidence=LOW`.
- **마스킹 토큰:** `[RRN]` 주민번호 / `[CARD]` 카드 / `[PHONE]` 전화 / `[EMAIL]` 이메일 / `[ACCOUNT]` 계좌 / `[NAME]` 이름 / `[ADDRESS]` 주소 / `[PASSWORD]` 비밀번호 / `[BIRTH]` 출생연도. 적용 순서는 화자 분리 → 마스킹 → GenAI.

## 9. 알려진 한계 (중요)

- **STT 응답 구조는 가정입니다.** 엔드포인트, `segments[]`/`text`/`speaker.label` 필드, 시간 단위(ms)는 기억·추정 기반입니다. 실제 응답과 다르면 파서를 고쳐야 합니다.
- **분류 결과는 아직 검증되지 않았습니다.** `step2\analyze.py`의 `mock_llm`은 키워드 규칙으로 JSON을 흉내 내는 가짜 LLM입니다. 프롬프트 조립·파싱·검증·재시도·스키마 조립 같은 연결 부분만 검증했고, 분류 정확도는 실제 LLM으로 평가표 5건을 돌려야 알 수 있습니다.
- **마스킹은 정규식 기반입니다.** 숫자를 한글로 읽어 적은 경우("공일공…")는 못 잡고, 이름은 "상담원 ○○○입니다"·"성함은 ○○○" 같은 문맥만 잡습니다. 계좌번호는 하이픈 구분 형식만 대상입니다.
- 프롬프트 v1.1은 초안입니다. 평가표 오분류 결과는 아직 반영되지 않았습니다.
- 파일 손상·타임아웃 등 실제 파일 대상 이상 케이스, 단계별 로그 기록은 미구현입니다.
- UiPath xaml(Step1~3, Main)은 미작성입니다. 현재는 Python 레퍼런스 구현만 있습니다.
