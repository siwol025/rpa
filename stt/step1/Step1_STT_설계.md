# Step1_STT.xaml 설계 (뼈대)

> 이 문서는 UiPath Studio에서 xaml을 만들 때 따라 하는 설계서입니다. 액티비티 이름·속성은 Studio 버전에 따라 조금 다를 수 있습니다.
> 같은 로직의 동작 가능한 레퍼런스가 `clova_stt.py` (Python 폴백)이며, 먼저 이것으로 키/음성만 넣어 응답 구조를 확인하세요.

## 1. Arguments

| 이름 | 방향 | 타입 | 설명 |
|---|---|---|---|
| `in_AudioPath` | In | String | 음성 파일 전체 경로 |
| `out_SttJson` | Out | String | CLOVA 원본 응답 JSON 문자열 (성공 시) |
| `out_Success` | Out | Boolean | 성공 여부 |
| `out_ErrorMessage` | Out | String | 실패 시 `단계: 사유` (추가 제안. FAILED JSON의 error로 쓰기 위함) |
| `in_ConfigPath` | In | String | (선택) config.json 경로. 비우면 프로젝트 기준 기본값 |

## 2. Variables

| 이름 | 타입 | 용도 |
|---|---|---|
| `configText` | String | config.json 내용 |
| `cfg` | JObject | 파싱된 config (`Newtonsoft.Json.Linq.JObject`) |
| `invokeUrl`, `secretKey` | String | config에서 읽은 값 |
| `paramsJson` | String | CLOVA params JSON 문자열 |
| `respText` | String | 응답 본문 |
| `statusCode` | Int32 | HTTP 상태코드 |
| `resp` | JObject | 파싱된 응답 |
| `token` | String | async일 때 작업 토큰 |
| `pollCount` | Int32 | 폴링 횟수 |

## 3. 흐름 (Sequence)

```
[Try]
 0. Log Message  "Step1 시작: " + in_AudioPath          (키/URL은 로그에 남기지 않기)
    Assign out_Success = False, out_SttJson = "", out_ErrorMessage = ""

 1. 입력 검사
    If  Not File.Exists(in_AudioPath)  → Throw New Exception("INPUT: 음성 파일 없음")
    If  New FileInfo(in_AudioPath).Length = 0  → Throw New Exception("INPUT: 빈 파일")

 2. config 읽기
    Read Text File  (config.json) → configText
    Assign cfg        = Newtonsoft.Json.Linq.JObject.Parse(configText)
    Assign invokeUrl  = cfg("clova_invoke_url").ToString.TrimEnd("/"c)
    Assign secretKey  = cfg("clova_secret_key").ToString
    If  invokeUrl = "" OrElse invokeUrl.StartsWith("여기에_") OrElse secretKey.StartsWith("여기에_")
        → Throw New Exception("INPUT: config.json에 키가 입력되지 않음")

 3. params 만들기
    Assign paramsJson =
      "{""language"":""" & cfg("stt")("language").ToString & """," &
      """completion"":""" & cfg("stt")("completion").ToString & """," &
      """diarization"":{""enable"":true,""speakerCountMin"":" & cfg("stt")("speaker_count_min").ToString &
      ",""speakerCountMax"":" & cfg("stt")("speaker_count_max").ToString & "}," &
      """noiseFiltering"":true,""fullText"":true}"

 4. HTTP Request  (시도 A)
    Method      : POST
    URL         : invokeUrl & "/recognizer/upload"
    Headers     : X-CLOVASPEECH-API-KEY = secretKey
    Body        : multipart/form-data
                    part "media"  : 파일 = in_AudioPath
                    part "params" : 텍스트 = paramsJson, Content-Type = application/json
    Timeout     : 300000
    Output      : respText, statusCode
    → 멀티파트가 번거롭거나 막히면 [4B 폴백]으로 (아래)

 5. 상태 확인
    If statusCode <> 200 → Throw New Exception("STT: HTTP " & statusCode.ToString)

 6. 응답 파싱
    Assign resp = Newtonsoft.Json.Linq.JObject.Parse(respText)

 7. (async일 때만) 폴링
    If cfg("stt")("completion").ToString = "async"
        Assign token = resp("token").ToString
        Do While  resp("result").ToString <> "COMPLETED" AndAlso resp("result").ToString <> "FAILED" AndAlso pollCount < 60
            Delay 00:00:05
            HTTP Request GET  invokeUrl & "/recognizer/" & token   (같은 헤더)
            Assign resp = JObject.Parse(응답 본문) : pollCount += 1
        If pollCount >= 60 → Throw New Exception("STT: 결과 대기 시간 초과")

 8. 결과 판정
    If resp("result").ToString <> "COMPLETED"
        → Throw New Exception("STT: CLOVA 처리 실패 - " & resp("message").ToString)
    If resp("segments") Is Nothing OrElse resp("segments").Count = 0
        → Throw New Exception("STT: 인식된 발화 없음(무음/빈 음성)")

 9. 성공
    Assign out_SttJson = resp.ToString(Newtonsoft.Json.Formatting.None)
    Assign out_Success = True
    Log Message "Step1 완료"
[Catch  System.Exception]
    Assign out_Success = False
    Assign out_ErrorMessage = exception.Message        (Secret Key가 메시지에 섞이지 않았는지 확인)
    Log Message  Level=Error  "Step1 실패: " & exception.Message
```

`out_ErrorMessage`의 "단계: 사유" 형식(`INPUT:`, `STT:`)은 call_schema.json의 `error.stage`/`error.reason`으로 그대로 쪼개 쓸 수 있습니다.

## 4. [4B] Python 폴백 (HTTP Request 멀티파트가 안 될 때)

필요: Python 설치 + `pip install requests`, UiPath.Python.Activities 패키지.

```
Python Scope  (Path = Python 설치 폴더, Version = 설치 버전)
   Load Python Script   File = ...\UiPath_GenAI_STT\step1\clova_stt.py   → pyScript (PythonObject)
   Invoke Python Method Name = "run"
                        Instance = pyScript
                        InputParameters = {in_AudioPath, in_ConfigPath}
                        Result → pyResult (PythonObject)
   Get Python Object    pyResult → resultJson (String)

Assign result = Newtonsoft.Json.Linq.JObject.Parse(resultJson)
If result("success").ToObject(Of Boolean)
    out_SttJson  = result("stt_json").ToString(Newtonsoft.Json.Formatting.None)
    out_Success  = True
Else
    out_Success      = False
    out_ErrorMessage = result("error")("stage").ToString & ": " & result("error")("reason").ToString
```
`run()`은 이미 INPUT 검사, config 읽기, 업로드, 폴링, 결과 판정을 모두 처리하므로 폴백에서는 3~8단계를 생략합니다.

## 5. 키·음성이 생겼을 때 테스트 순서

1. `config.json`에 Invoke URL / Secret Key 입력.
2. Python으로 먼저 응답 구조 확인 (원본 응답이 `sample_response.json`으로 저장됨):
   `python clova_stt.py --audio ..\test\call_01_질의.m4a --raw-out ..\test\sample_response.json`
3. 파서가 실제 응답에서도 도는지 확인:
   `python parse_clova.py --in ..\test\sample_response.json`
   - 안 되면 `parse_clova.py`의 `extract_segments()`에서 키 이름·단위를 실제 응답에 맞춰 수정.
4. UiPath에서 `Step1_STT.xaml`을 `in_AudioPath = ...\call_01_질의.m4a`로 실행해 `out_SttJson`이 `sample_response.json`과 같은지 비교.
5. `python test_step1.py` 가 계속 통과하는지 확인 (파서를 고쳤다면 더미도 실제 응답 형태로 갱신).

## 6. 확인해야 할 가정 (실제 응답으로 검증 필요)

| 가정 | 확인 방법 |
|---|---|
| 엔드포인트 `/recognizer/upload`, 헤더 `X-CLOVASPEECH-API-KEY` | 콘솔 API 가이드 |
| 응답 최상위 `result`(`COMPLETED`/`FAILED`), `segments[]`, `text`(전체 텍스트) | `sample_response.json` |
| `segments[].start/end` 단위가 ms | 값 크기로 확인 (통화 2분이면 end가 약 120000) |
| 화자 정보가 `speaker.label` 또는 `diarization.label` | `sample_response.json` |
| 지원 음성 포맷 (`clova_stt.py`의 `ALLOWED_EXT`) | 콘솔 가이드 |
| async 응답 형태(`token`)와 조회 엔드포인트 `/recognizer/{token}` | async 사용 시 |
