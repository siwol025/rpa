# 로봇 API 요청 예시 (RPA 파트용)

UiPath(Dispatcher·Performer)가 호출하는 `/api/robot/*` API의 요청 예시다. 이 폴더의 JSON 파일은
테스트가 실제로 서버에 보내 검증하므로 항상 현재 API와 맞다.

| 항목 | 값 |
|---|---|
| API 문서(Swagger) | `http://<서버 주소>:8000/docs` — 개발 환경은 `http://localhost:8000/docs` **[운영 서버 주소 미정]** |
| 계약서(OpenAPI) | `backend/docs/api/openapi.json` |
| 인증 | 모든 요청에 `X-API-Key: <키>` 헤더. 로봇 PC의 IP만 허용 |
| 에러 형식 | `{ "code": "...", "message": "...", "detail": ... }` — 분기는 `code`로 한다 |

인증 실패는 `401 UNAUTHORIZED`(키 오류), `403 FORBIDDEN_IP`(허용되지 않은 IP)다.

## 처리 순서

```
Dispatcher: ① 등록 → ② Queue 추가 → ③ QUEUED 보고
Performer : ④ 전사 적재 → ⑤ 분석 적재   (실패하면 ⑥ 실패 보고)
```

| 순서 | 호출 | 성공 | 상태 변화 |
|---|---|---|---|
| ① | `POST /api/robot/calls` | 201 `{ "call_id": 1 }` | → `REGISTERED` |
| ③ | `PATCH /api/robot/calls/{call_id}/status` | 200 `{ "call_id", "status" }` | → `QUEUED` |
| ④ | `PUT /api/robot/calls/{call_id}/transcript` | 200 `{ "call_id", "status" }` | → `STT_DONE` |
| ⑤ | `PUT /api/robot/calls/{call_id}/analysis` | 200 `{ "call_id", "status" }` | → `STORED` 또는 `NEEDS_REVIEW` |
| ⑥ | `POST /api/robot/calls/{call_id}/logs` | 201 `{ "call_id", "status" }` | `FAIL`이면 → `FAILED` |

`call_id`는 서버가 정한 숫자 ID다(결과 JSON의 문자열 `call_id`와 다르다).

## ① 등록 — multipart/form-data

텍스트 변환 **전에** 먼저 등록한다. 그래야 처리 중 실패해도 대시보드에 남는다.

```bash
curl -X POST http://localhost:8000/api/robot/calls \
  -H "X-API-Key: <키>" \
  -F "file=@20261124_1512_김지현_한빛물산.wav" \
  --form-string "file_hash=<파일의 SHA-256, 16진수 64자>" \
  --form-string "original_name=20261124_1512_김지현_한빛물산.wav" \
  --form-string "source_type=DRIVE" \
  --form-string "source_ref=<Drive 파일 ID>" \
  --form-string "call_datetime=2026-11-24T15:12:00+09:00" \
  --form-string "agent_name=김지현" \
  --form-string "client_company=한빛물산"
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `file` | O | 음성 파일. **wav, mp3만** 받는다(확장자가 아니라 파일 내용으로 판별). 크기 한도 100MB |
| `file_hash` | O | 파일의 SHA-256(소문자 16진수 64자). 서버가 다시 계산해 다르면 422 |
| `original_name` | O | 원본 파일명(255자 이하) |
| `source_type` | O | `DRIVE`(사용자가 폴더에 올림) 또는 `WEB`(웹 업로드 대행) |
| `source_ref` | | Drive 파일 ID 등 |
| `call_datetime` | | 통화 일시. 오프셋이 없으면 KST로 본다 |
| `agent_name` | | 담당자(50자 이하) |
| `client_company` | | 고객사(100자 이하) |

파일명에서 담당자·통화 일시를 못 뽑았으면 **그 필드를 생략하거나 빈 값으로** 보낸다. 서버가
`metadata_incomplete=true`로 등록하고 처리는 그대로 진행한다(웹에서 보정).

### 409 중복 — Dispatcher가 할 일

같은 파일이 이미 있으면 `409 DUPLICATE_FILE`이고, 기존 건은 `detail`에 들어 있다.

```json
{ "code": "DUPLICATE_FILE", "message": "이미 등록된 파일입니다.",
  "detail": { "existing_id": 123, "status": "REGISTERED" } }
```

| `detail.status` | 의미 | Dispatcher 처리 |
|---|---|---|
| `REGISTERED` | 이전 실행이 Queue 추가 전에 중단됨 | `existing_id`로 Queue 추가부터 이어서 → ③ |
| `QUEUED`·`STT_DONE`·`RETRY_REQUESTED` | 이미 처리 중 | 아무것도 하지 않음 |
| `STORED`·`NEEDS_REVIEW` | 이미 처리 완료 | 파일을 `done/`으로 이동 |
| `FAILED` | 이미 실패 처리됨 | 파일을 `failed/`로 이동 (복구는 웹 재처리) |

## ③ QUEUED 보고 — [`status-queued.json`](status-queued.json)

`REGISTERED` 또는 `RETRY_REQUESTED` 건만 가능하다. 응답을 못 받아 **같은 `queue_item_id`로 다시 보내면 200**이다.

## ④ 전사 적재 — [`transcript.json`](transcript.json)

결과 JSON(`call_schema.json`)의 `transcript.segments`, `transcript.full_text`, `processing.stt_engine`을 옮긴다.
`speaker`는 `AGENT`·`CUSTOMER`·`UNKNOWN`, 시간은 초 단위이고 `end_sec`는 `start_sec`보다 작을 수 없다.
**같은 내용을 다시 보내도 200**이다(멱등).

## ⑤ 분석 적재 — 결과 JSON 그대로

[`uipath/samples/test_cases/case01_success.json`](../../../../uipath/samples/test_cases/case01_success.json)처럼 결과 JSON 전체를 그대로 보낸다.

- `schema_version`은 `"1.0"`만 받는다. 다른 값은 422.
- `status`는 `SUCCESS` → 상태 `STORED`, `NEEDS_REVIEW` → 상태 `NEEDS_REVIEW`. 서버는 임계값으로 다시 판정하지 않는다.
- `status`가 `FAILED`인 결과는 받지 않는다(422). 실패는 ⑥으로 보고한다.
- `type`은 `INQUIRY`·`COMPLAINT`·`SUGGESTION`·`TRAINING`·`OTHER`. 성공·검토 필요 건은 필수다.
- 서버가 쓰지 않는 필드(`summary`, `sentiment`, `keywords` 등)도 그대로 보존된다.
- **같은 내용을 다시 보내도 200**이다(멱등). 재처리라면 이전 결과를 대체한다.

## ⑥ 로그·실패 보고 — [`log-step.json`](log-step.json), [`log-fail.json`](log-fail.json)

| `step` | `REGISTER`·`QUEUE`·`STT`·`GENAI`·`STORE`·`EXCEL`·`CRM`·`RETRY` |
|---|---|
| `status` | `SUCCESS`·`FAIL`·`RETRY` |
| `stage` | 실패 단계(`FAIL`일 때): `INPUT`·`STT`·`PII`·`GENAI`·`VALIDATION` (결과 JSON의 `error.stage`와 같은 값) |

- **재시도를 모두 쓴 뒤 최종 실패일 때만 `FAIL`을 한 번** 보낸다. 처리 중인 건이 `FAILED`로 바뀐다.
- 엑셀 기입처럼 **분석 저장 후**의 실패는 `step=EXCEL`, `status=FAIL`로 보내면 상태는 `STORED`·`NEEDS_REVIEW` 그대로이고 로그만 남는다.
- `message`(사유)에 Secret Key나 통화 원문을 넣지 않는다.

## 재처리 — 대상 조회와 음성 다운로드

웹에서 재처리를 요청한 건(`RETRY_REQUESTED`)은 Dispatcher가 다음 주기에 다시 Queue에 넣는다.

| 호출 | 응답 |
|---|---|
| `GET /api/robot/calls?status=RETRY_REQUESTED` | 200 `{ "items": [ { "call_id": 12, "retry_count": 1 } ] }` — 오래 기다린 순, 최대 100건 |
| `GET /api/robot/calls/{call_id}/audio` | 200 음성 파일 본문(`audio/wav`·`audio/mpeg`). 없는 건·사본 없음은 404 |

`status`는 `RETRY_REQUESTED`만 받는다(다른 값은 422). 흐름은 **목록 조회 → 음성 다운로드 → Queue 추가 → ③ QUEUED 보고**이며,
이후는 처음 처리와 같다. 음성은 서버 사본에서 받으므로 원본 폴더에서 파일이 옮겨졌어도 된다.

## 409 — 상태가 맞지 않을 때

`PATCH`·`PUT`·`POST .../logs`가 현재 상태와 맞지 않으면 409다. 현재 상태가 `detail`에 있다.

```json
{ "code": "INVALID_STATE_TRANSITION", "message": "현재 상태에서 허용되지 않는 요청입니다.",
  "detail": { "current_status": "RETRY_REQUESTED", "requested_status": "STT_DONE" } }
```

정체 건이 재처리 요청된 뒤 **이전 Queue 건이 뒤늦게** 적재·실패 보고를 하면 이렇게 거절된다. 정상 동작이며
새 Queue 건이 처리한다. Performer는 실패 보고 없이 해당 Queue 건을 종료한다 **[RPA 파트와 합의 필요]**.

## 직접 돌려 보기

UiPath 없이 흐름 전체를 서버에 대고 점검할 수 있다.

```bash
cd backend
uv run python -m scripts.simulate_robot --base-url http://localhost:8000 --api-key <키>
```

실행할 때마다 서버에 시뮬레이션용 건이 등록되므로 운영 DB에는 쓰지 않는다.
