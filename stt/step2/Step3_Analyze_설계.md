# Step3_Analyze.xaml 설계 (Content Generation 연결)

Python 레퍼런스: `step2/analyze.py` (`build_prompt` → LLM → `extract_json` → `validate` → 재시도).
이 문서는 Studio의 `UiPath.GenAI.Activities > Content Generation`에 무엇을 넣고 무엇을 받는지 정리한 것입니다.
액티비티 속성의 **실제 표시 이름은 패키지 버전에 따라 다를 수 있으니 Studio 속성 창에서 확인**하고, 아래 "입력 ↔ 속성" 칸만 맞춰 주세요.

## 1. 워크플로 인자
| 이름 | 방향 | 타입 | 내용 |
|---|---|---|---|
| `in_Transcript` | In | String | PII 마스킹이 끝난 `full_text` (`[상담원] …\n[고객] …`) |
| `in_PromptPath` | In | String | `prompts\prompt_v1_2.txt` (채택) |
| `in_MaxRetry` | In | Int32 | 기본 2 (Config에서 받음) |
| `out_ResultJson` | Out | String | 검증을 통과한 분석 JSON 문자열 |
| `out_Success` | Out | Boolean | 성공 여부 |
| `out_ErrorReason` | Out | String | 실패 사유. 성공이면 빈 문자열 |

`in_Transcript`는 통화 상대방 발화가 그대로 들어간 **신뢰할 수 없는 텍스트**입니다. 프롬프트의 지시문으로 쓰이지 않게 아래처럼 USER 블록의 `INPUT:` 자리에만 넣습니다.

## 2. 변수
| 이름 | 타입 | 용도 |
|---|---|---|
| `promptRaw` | String | 프롬프트 파일 전체 |
| `promptBody` | String | `#` 설명 줄을 제거한 본문 |
| `systemPrompt` | String | `[SYSTEM]` ~ `[USER TEMPLATE]` 사이 |
| `userPrompt` | String | `[USER TEMPLATE]` 이후, `{{TRANSCRIPT}}` 치환 후 |
| `llmText` | String | 액티비티가 돌려준 원문 |
| `jsonText` | String | 코드펜스·설명 제거 후 JSON |
| `parsed` | JObject | 역직렬화 결과 |
| `attempt` | Int32 | 시도 횟수 (0부터) |
| `lastError` | String | 직전 시도의 실패 사유 |

## 3. 프롬프트 변수 구성 (Content Generation 호출 전)
```vb
' 1) 파일 읽기: Read Text File (Encoding UTF-8) → promptRaw
' 2) 설명용 '#' 줄 제거
promptBody = System.Text.RegularExpressions.Regex.Replace(promptRaw, "(?m)^[ \t]*#.*(\r?\n|$)", "")
' 3) SYSTEM / USER 분리
Dim m = System.Text.RegularExpressions.Regex.Match(promptBody, "\[SYSTEM\](.*?)\[USER TEMPLATE\](.*)", System.Text.RegularExpressions.RegexOptions.Singleline)
' m.Success가 False이면 out_Success=False, out_ErrorReason="프롬프트 파일에 [SYSTEM]/[USER TEMPLATE] 블록 없음"
systemPrompt = m.Groups(1).Value.Trim()
userPrompt   = m.Groups(2).Value.Trim().Replace("{{TRANSCRIPT}}", in_Transcript)
```
프롬프트 파일은 시작 시 한 번만 읽고, 건별 반복에서는 3)의 `Replace`만 합니다.

## 4. 입력 ↔ 속성 매핑
| 넣을 값 | Content Generation 쪽 | 비고 |
|---|---|---|
| `systemPrompt` | System prompt 속성이 있으면 거기에 | 없으면 `systemPrompt + vbCrLf + vbCrLf + userPrompt`를 Prompt 하나로 합침 |
| `userPrompt` | Prompt | |
| 온도 | 0 ~ 0.2 | 분류 일관성 우선 (체크리스트 No.17) |
| 최대 토큰 | 1,000 이상 | 출력 JSON이 약 300~500토큰. 잘리면 파싱 실패 |
| 타임아웃 | 60초 안팎 | 초과 시 해당 시도를 실패로 보고 재시도 |
| 모델 | 연결에서 허용되는 모델 중 하나 | 선택한 모델 이름을 README에 기록 |
| **출력 → `llmText`** | 결과 텍스트 속성 | 속성 이름은 Studio에서 확인 |

## 5. 응답 처리와 재시도
```
attempt = 0
Do
  Content Generation → llmText   (예외 시 lastError="GenAI 호출 실패", 재시도)
  jsonText = 첫 "{" ~ 마지막 "}" 구간만 추출 (```json 코드펜스·앞뒤 설명 제거)
  parsed   = JObject.Parse(jsonText)  (실패 시 lastError="JSON 파싱 실패")
  검증 통과?  → out_ResultJson = jsonText, out_Success = True, 종료
  아니면 lastError 기록, attempt += 1
Loop While attempt <= in_MaxRetry
최종 실패 → out_Success=False, out_ErrorReason=lastError  (stage = VALIDATION 또는 GENAI)
```
검증 항목(`analyze.py`의 `validate`와 동일):
- 필수 키 10개(감정 분석 `sentiment`는 추출 대상이 아니라 제거함): `type, type_confidence, customer_company, customer_question, agent_action, summary, follow_up_required, follow_up, keywords, entities`
- `type` ∈ {INQUIRY, COMPLAINT, SUGGESTION, TRAINING, OTHER} (백엔드 코드 EDUCATION/ETC로의 변환은 적재 단계 `step2/to_backend.py`)
- `type_confidence`는 0.0~1.0 숫자, `summary`는 비어 있지 않고 300자 이내
- `customer_question`, `agent_action`은 null이거나 1~200자 문자열
- `follow_up_required`는 boolean
- `keywords`는 5개 이하 배열
- `entities`는 `{type, value}` 배열이며(백엔드도 같은 배열로 저장) `type` ∈ {PRODUCT, ORG, DATE, AMOUNT, REF_NO, OTHER}, `value`는 비어 있지 않음

## 6. 출력 JSON → 최종 결과 JSON 매핑
`call_schema.json`은 평면 구조(최상위 22개 필드)입니다. LLM이 채우는 11개 필드는 이름 그대로 최상위에 복사하고, 나머지는 RPA(Main/Step)가 채웁니다.

| 최종 필드 | 채우는 주체 | 출처 |
|---|---|---|
| `type`, `type_confidence`, `customer_company`, `customer_question`, `agent_action`, `summary`, `follow_up_required`, `follow_up`, `keywords`, `entities` | LLM (`out_ResultJson`) | |
| `type_label` | RPA | `type` 코드 → 한글 라벨 |
| `transcript` | RPA | Step2 화자 정제 결과 (마스킹 후) |
| `pii` | RPA | `mask_pii`의 `{masked, counts}` |
| `schema_version`, `call_id`, `source`, `call_datetime`, `agent_name`, `processing`, `status`, `error` | RPA | 파일명·시각·단계별 결과 (`agent_name` 등 null 허용 여부는 `call_schema.json`으로 확인) |
| `status` 판정 | RPA | 확신도 < 0.6 또는 `speaker_confidence=LOW`면 `NEEDS_REVIEW`, 실패면 `FAILED` (백엔드도 이 판정을 그대로 따름) |

## 7. 알려둘 점
- **로그**: 프롬프트·응답 원문에는 통화 내용이 들어 있습니다. 단계 로그에는 길이와 성공 여부만 남기고, 원문은 오류 분석용 파일로만 저장하세요. (키·URL은 어떤 로그에도 넣지 않음)
- **화자 1명 통화**(`speaker_confidence=LOW`, 예: S00007729)는 `[알수없음]` 한 줄짜리 스크립트가 들어옵니다. 프롬프트는 화자 표시가 틀릴 수 있다고 안내하고 있으니 그대로 호출하고, 결과 status만 `NEEDS_REVIEW`로 둡니다.
- **STT 오인식**: 업체명·이름 같은 고유명사가 틀리는 경우가 있습니다. 요약에 이름을 쓰지 않는 현재 프롬프트 규칙이 이를 어느 정도 완화합니다.
- 이 스펙은 Studio 단건 테스트 성공 후 작성했지만, 이 프롬프트 전체(예시 5개 포함)를 실제로 호출한 결과는 아직 없습니다. 첫 실호출 후 출력이 5절 검증을 통과하는지 확인하세요.
