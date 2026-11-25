# 웹 업로드 리서치 — `POST /api/uploads`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-07 웹 업로드 (P1, Phase 2, 선행 C-02·**W-08**) — 요구: PRD IN-03 / 관련: W-08 Drive 연동 모듈(사용), O-02 헬스 체크(같은 어댑터 사용), R-04 로봇 등록(같은 형식 검증 필요), WEB-05(업로드 화면) |
| 근거 | `docs/prd.md` §5.1(IN-02·IN-03·IN-05)·§5.6(WEB-05)·§7, `docs/input_flow.md` v0.2 §3·§4.2·§4.3·§6.2·§7, `features.md` v0.2 W-07·W-08·R-04·O-02, `architecture.md` §3·§4.1·§7·§8.2·§10·§11, `research.md` §2.3·§5·§7, `back_stack.md` §2.2·§6, `api/convention.md` v0.1, `researchs/drive-inbox.md` v0.1, `plans/drive-inbox.md` v0.1(§1.4·§3·§9.4), `researchs/common-module.md` §3.3, `plans/common-module.md` §5.4, `backend/app/**`, `backend/tests/unit/**`, `stt/`(③), 원격 브랜치 `origin/front`(프론트 초안, 미병합)·`origin/csj`(`uipath/docs/features_rpa.md`, 미병합) |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / python-multipart 0.0.34 / anyio 4.16.0 / filetype 1.2.0 (`.venv` 설치본) |
| 검증 방법 | 문서·코드 정독, 설치 라이브러리 소스 확인, 스크래치 폴더에서 `create_app(Settings(_env_file=None, …))`에 임시 라우트를 붙여 `TestClient`로 multipart 동작 실측(레포 코드는 수정하지 않음) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다. **[확인 필요]**는 공식 문서·실측으로 확정하지 못했거나 다른 파트와 합의해야 하는 항목, **[가정]**은 근거 없이 정한 값이다.

---

## 0. 요약 (핵심 발견)

1. **[핵심] 웹 업로드는 DB에 아무것도 쓰지 않는다.** 서버는 검증 후 `InboxWriter.write()`로 `inbox/`에 파일을 올리고 202로 끝낸다(`features.md:84` "DB 등록 없음", `architecture.md:450` "등록은 Dispatcher 단일 경로", `input_flow.md` §4.3 "DB 등록: 하지 않음 (중복 등록 방지)"). `call_record` 행은 이후 Dispatcher가 `POST /api/robot/calls`(R-04, A 담당)로 만들며, 그때 `source_type=WEB`은 Drive 파일의 `properties.source=web`을 보고 Dispatcher가 정한다. 따라서 W-07은 **세션·Repository·모델을 쓰지 않는다**(`get_db` 의존성 불필요). 해시 중복 검사도 하지 않는다(같은 파일 재업로드는 Dispatcher 등록 시 `409 DUPLICATE_FILE`로 정리됨, `input_flow.md` §6.2).
2. **W-08 산출물로 W-07이 바로 쓸 수 있는 것이 준비돼 있다.** `InboxWriter`(Protocol: `write(filename, stream, content_type) -> str`, `check()`), `InboxUnavailableError(reason)`, `create_inbox_writer` → `app.state.inbox_writer`, `deps.get_inbox_writer` → `InboxWriter | None`(`None` = `INBOX_BACKEND=disabled`, 코드 기본값). `ErrorCode.INBOX_UNAVAILABLE`(503 "업로드 저장소를 사용할 수 없습니다.")도 있다. 단위 테스트 앱(`Settings(_env_file=None)`)은 기본값이 `disabled`라 writer가 `None`이다.
3. **W-08 인계 항목(`plans/drive-inbox.md` §9.4 H1~H7)이 W-07 설계 제약이다.** `None`이면 503(H1), `reason`은 응답에 넣지 않음(H2), `write`는 블로킹이라 **라우트를 `def`로**(H3), 로컬 금지 문자 규칙과 검증 맞추기(H4), 파일 하나 최악 약 3분(H6), `InboxUnavailableError`를 `exc_info`로 로그에 남기지 않음(H7). 파일명 NFC 정규화는 W-07 몫(D14), 부분 실패 정책도 W-07 몫(`researchs/drive-inbox.md` §4.3).
4. **[핵심] 프론트 초안은 "파일마다 요청 1개"로 보낸다.** `origin/front` `frontend/src/api/uploads.ts`: `form.append('files', file)`(필드 이름 `files`, **[확인 필요]** 주석), 큐로 한 번에 하나씩 순차 전송, 요청 타임아웃 5분, 응답 본문은 읽지 않음(`apiUpload` → `Promise<void>`), 목(mock)은 `202` 빈 본문. 담당자·고객사·통화 일시 입력란은 **없다**. 이유는 "서버 크기 제한이 요청 전체(파일 합계)에 걸리므로"다. 결과적으로 부분 실패는 프론트 기준으로 거의 일어나지 않는다.
5. **multipart 실측 결과** (FastAPI 0.165 / Starlette 1.10):
   - `list[UploadFile]` 필드 `files`로 1개·여러 개 모두 받는다. 필드가 없거나 다른 이름이면 422 `missing`(`loc: ["body","files"]`).
   - 한글 UTF-8 파일명은 그대로 들어온다. **NFD로 보낸 이름은 NFD 그대로**다(서버가 정규화해야 함).
   - **경로 성분을 제거하지 않는다**: `filename="../../etc/a b.wav"`가 그대로 `UploadFile.filename`이 된다. 예외로 `C:\…\a.wav`·`\\…` 형태(IE6 우회)만 마지막 성분으로 잘린다.
   - `filename=""`(브라우저에서 파일을 고르지 않은 경우)은 422 `missing`. `filename*=`(RFC 5987)만 있는 부분은 무시돼 문자열 필드가 되고 422 `value_error`.
   - **0바이트 파일은 통과한다**(`size=0`) → 서버 검증 필요.
   - 부분의 `Content-Type`이 없으면 `UploadFile.content_type`은 `None`. 브라우저가 보낸 값(`audio/wav`, `audio/x-wav`, `application/octet-stream` 등)은 확장자 기반이라 신뢰할 수 없다.
   - 파일 본문은 `SpooledTemporaryFile`(1 MiB까지 메모리, 넘으면 임시 파일)에 **요청 전체를 다 받은 뒤** 엔드포인트가 실행된다. 즉 클라이언트 → Drive로 흘려보내는 진짜 스트리밍은 아니다. `def` 엔드포인트는 AnyIO 워커 스레드에서 돈다.
   - 파일 수 한도는 라우트 데코레이터 `form_limits={"max_files": N}`로 줄 수 있고, 넘으면 Starlette가 `HTTPException(400)` → 우리 핸들러 **400 `BAD_REQUEST`**(메시지 원문은 버려짐).
   - 크기 한도: `Content-Length` 초과·chunked 초과 모두 413 `PAYLOAD_TOO_LARGE`이고 엔드포인트는 호출되지 않는다. `plans/common-module.md` §5.4의 chunked 제약(본문을 읽지 않는 `StreamingResponse` 라우트)은 본문을 읽는 W-07에는 해당하지 않는다.
6. **[핵심] 형식 검증은 "확장자 + 매직 바이트"가 실질이고, 클라이언트 MIME은 판정 근거로 약하다.** `architecture.md:545`는 "확장자 + MIME + 매직 바이트"를 요구한다. 브라우저 MIME은 OS 확장자 매핑에서 나오므로 내용과 무관하고, 매핑이 없으면 `application/octet-stream`이다. 내용에서 판정한 형식으로 **정규 MIME(`audio/wav`·`audio/mpeg`)을 정해 Drive에 넘기는 안**이 Dispatcher MIME 필터(W-08 §9.2 X2)와도 맞다.
7. **`filetype` 1.2.0이 의존성에 이미 있으나 mp3 판정이 좁다.** `Mp3.match`는 `ID3` 또는 `FF FB`/`FF F3`/`FF F2`만 인정해 CRC 보호 프레임(`FF FA`), MPEG 2.5(`FF E3`/`FF E2`)를 놓친다. WAV는 `RIFF`…`WAVE`(0~3, 8~11바이트)로 충분하다. M4A는 `ftypM4A`만 인정하고 `ftypisom`·`ftypmp42` 등은 mp4 영상으로 분류한다. 아직 앱 코드에서 `filetype`을 쓰는 곳은 없다.
8. **허용 확장자 설정 필드가 없다.** `.env.example`에 `ALLOWED_EXTENSIONS=wav,mp3`가 있지만 `Settings`에 필드가 없어(`extra="ignore"`) 지금은 무시된다. PRD IN-02는 wav·mp3(기타 **[결정 필요]**), ③ STT(`stt/step1/clova_stt.py:29`)는 `.m4a` 등도 허용하고 테스트 샘플도 `.m4a`다. Dispatcher는 wav·mp3 외를 `failed/`로 보낸다(`input_flow.md` §4.2) → 서버가 m4a를 받아도 처리되지 않는다.
9. **파일명은 원래 이름을 유지하는 것이 문서 기준이다**(`architecture.md:448`). 메타데이터(담당자·고객사·통화 일시)는 Dispatcher가 파일명 규칙 `{yyyyMMdd_HHmmss}_{담당자}_{고객사}.{wav|mp3}`(`input_flow.md` §7, **[결정 필요]**)으로 추출한다. 서버가 사용자 입력으로 규칙 파일명을 만들라는 요구는 어디에도 없고, 프론트에도 입력란이 없다. 규칙에 안 맞으면 `metadata_incomplete=true`로 등록되고 웹에서 보정한다(W-12).
10. **Drive는 이름에 거의 모든 문자를 허용하지만 하류는 Windows다.** Performer는 `processing/`의 원본을 내려받아 STT를 하고(`architecture.md` §4.1), 로봇 PC는 Windows다. `\ / : * ? " < > |`·제어 문자·끝 점/공백이 든 이름은 RPA 쪽 로컬 저장에서 문제가 될 수 있다 **[확인 필요: RPA]**. W-08의 `validate_local_name`이 같은 금지 문자 집합을 이미 갖고 있다(H4).
11. **최악 응답 시간.** 파일 하나가 Drive 재시도·타임아웃으로 최악 약 3분(H6), 프론트 타임아웃은 요청당 5분이다. 한 요청에 여러 파일을 담으면 `N × 3분`이 될 수 있어 프론트 타임아웃을 넘는다. 동기 엔드포인트는 클라이언트가 끊어도 업로드를 계속하므로, 화면은 실패인데 파일은 `inbox/`에 들어가는 경우가 생긴다(재업로드 시 Dispatcher 409로 정리).

---

## 1. 현재 상태

### 1.1 코드 (브랜치 `cyj`, `b9a1f2a`)
| 위치 | 상태 | W-07과의 관계 |
|---|---|---|
| `app/api/web/` | `calls.py`(W-01·W-02), `stats.py`(W-10) | `uploads.py` 추가 위치(`architecture.md` §3.2) |
| `app/services/` | `call_service.py`, `stats_service.py` | `upload_service.py` 추가 위치(`architecture.md` §3.2 "웹 업로드 검증 → InboxWriter") |
| `app/schemas/` | `common.py`(에러·`Page`·`KstDatetime`·`error_responses`), `call.py`, `stats.py` | 응답 모델 `upload.py` 후보 |
| `app/api/deps.py` | `get_db`, `get_inbox_writer`, `get_call_service`, `get_stats_service` | `get_upload_service(writer)` 추가 위치. DB 세션은 받지 않는다 |
| `app/main.py` | `app.state.inbox_writer = create_inbox_writer(settings)`, `calls`·`stats` 라우터 등록 | `uploads.router` 등록 1줄 |
| `app/infra/inbox/` | `base.py`(`InboxWriter`, `InboxUnavailableError`), `local.py`(`validate_local_name`, `LocalInboxWriter`), `drive.py`(`DriveInboxWriter`), `__init__.py`(`create_inbox_writer`) | 사용만 한다(수정 없음) |
| `app/core/config.py` | `max_upload_mb`(기본 100, `max_upload_bytes` = MiB), `inbox_backend`(기본 `disabled`), `inbox_local_path`, `drive_inbox_folder_id` | **`allowed_extensions` 없음**(§5.4) |
| `app/core/errors.py` | `BAD_REQUEST` 400, `PAYLOAD_TOO_LARGE` 413, `UNSUPPORTED_MEDIA` 415, `VALIDATION_ERROR` 422, `INBOX_UNAVAILABLE` 503 | 새 코드 불필요 |
| `app/core/middleware.py` | `BodySizeLimitMiddleware`(CL 사전 검사 + 수신 누적 검사, 초과 413) | 크기 제한은 이미 동작(C-02). W-07은 별도 처리 없음 |
| `app/models/call_record.py` | `source_type`(`DRIVE`/`WEB`), `source_ref`, `original_name`(Text), `agent_name`(String 50), `client_company`(String 100), `call_datetime` | W-07은 쓰지 않음. 참고: Dispatcher가 보낸 파일명이 `original_name`이 된다 **[확인 필요: R-04 구현]** |
| `pyproject.toml` | `python-multipart`, `filetype` 직접 의존성 있음, mypy override에 `filetype.*` | 형식 판정에 `filetype`을 쓸지 결정(D6) |

### 1.2 테스트 구조
| 위치 | 내용 | W-07 활용 |
|---|---|---|
| `tests/unit/conftest.py` | `build_app(**overrides)` = `create_app(Settings(_env_file=None, …))` + 테스트 라우트(`/upload` 등), `client`(1 MiB 한도) | 라우터 테스트 앱. 기본 writer `None` |
| `tests/unit/test_calls_api.py` | 가짜 서비스 + `app.dependency_overrides[get_call_service]` | 같은 방식으로 가짜 `InboxWriter`(또는 가짜 서비스) 주입 |
| `tests/unit/test_inbox_factory.py` | `app.state.inbox_writer` 교체·`get_inbox_writer` 테스트 선례 | `app.state.inbox_writer = Fake()` 방식 |
| `tests/unit/test_inbox_local.py` | `LocalInboxWriter` 단위 테스트(`tmp_path`) | 로컬 writer로 실제 파일까지 확인하는 라우터 테스트 근거 |
| `tests/unit/test_openapi.py` | 커밋된 `openapi.json` 일치, operationId = 함수 이름·고유, 422·500 문서화 | 라우트 추가 시 `openapi.json` 재생성 필요 |
| `tests/integration/` | 실제 PostgreSQL | W-07은 DB를 안 쓰므로 해당 없음 |

---

## 2. 요구사항 정리

### 2.1 원문
| 출처 | 원문 |
|---|---|
| PRD IN-03 (`prd.md:115`) | "웹 대시보드에서 음성 파일을 업로드할 수 있다 (다중 파일). 서버는 파일을 클라우드 `inbox/`에 대신 업로드만 하고 처리는 IN-01 경로를 따른다" (P1) |
| PRD IN-02 (`prd.md:114`) | "지원 포맷: .wav, .mp3 (기타 포맷 추가 여부 **[결정 필요]**). 미지원 파일은 `failed/`로 이동" |
| PRD IN-05 (`prd.md:117`) | "담당자(3명 중 1인), 고객사, 통화 일시 메타데이터를 파일명 규칙에서 자동 추출한다. 추출 실패 시 빈 값으로 등록하고 '메타데이터 확인 필요'로 표시 … **[파일명 규칙 결정 필요]**" |
| PRD WEB-05 (`prd.md:171`) | "파일 업로드 화면(업로드 후 '접수됨, 처리 대기' 안내) 및 처리 상태 모니터링 (폴링 갱신)" |
| PRD §7 API (`prd.md:217`) | "`POST /api/uploads` 음성 파일 업로드 → 서버가 클라우드 `inbox/`에 업로드 (DB 등록 없음)" |
| `features.md:84` W-07 | "`POST /api/uploads` — 다중 파일, 형식 검증(크기 제한은 C-02), `DriveInboxWriter`로 클라우드 `inbox/` 업로드(`properties.source=web`), DB 등록 없음, 202 응답" — P1, Phase 2, 선행 C-02·W-08 |
| `architecture.md` §4.1 | "U->>A: POST /api/uploads / A->>A: 확장자·MIME·크기 검증 / A->>I: Drive API 업로드 (properties.source=web) / A-->>U: 202 접수됨" |
| `architecture.md` §8.2 | "원래 파일명 유지(파일명 규칙으로 메타데이터 추출). Drive는 같은 이름을 허용하므로 별도 접미사 불필요" / "웹 업로드 시 DB 등록은 하지 않음 (등록은 Dispatcher 단일 경로)" / "실패 시 지수 백오프로 2회 재시도 후 `503 INBOX_UNAVAILABLE` (어댑터는 `InboxUnavailableError`, 서비스가 503으로 변환)" |
| `architecture.md` §10.3 | `ALLOWED_EXTENSIONS` = `wav,mp3` / `MAX_UPLOAD_MB` "요청 전체 크기 한도(MiB, 기본 100), 모든 API 공통, 앱에서 검사" |
| `architecture.md` §11 | "업로드 파일 (웹·로봇): 확장자 + MIME + 매직 바이트 검증, 음성 사본은 UUID 파일명, 실행 권한 없는 볼륨" |
| `input_flow.md` §4.3 | "서버가 확장자·MIME·용량 검증 후 Drive API로 `inbox/`에 업로드" / 출처 표시 `properties.source=web` / "DB 등록: 하지 않음 (중복 등록 방지). 업로드 화면에는 '접수됨, 처리 대기' 안내만 표시" |
| `convention.md:40` §2.2 | `POST /api/uploads` → 성공 202, 주요 에러 400, 413, 415, 422, 503 |
| `convention.md` §2.1 | "비동기 접수(실제 처리는 나중) → 202, 접수 결과 (예: 웹 업로드 …)" |
| `convention.md` §3.4 | `AppError`만 사용, `message`·`detail`에 요청 입력값을 넣지 않음, 파일 받는 엔드포인트는 `PAYLOAD_TOO_LARGE`·`UNSUPPORTED_MEDIA`를 문서화 |
| `back_stack.md` §2.2 | "동기(def) 엔드포인트 … Drive 업로드처럼 오래 걸리는 I/O도 FastAPI가 스레드풀에서 처리" |
| `plans/drive-inbox.md` §9.4 | H1~H7 (§0-3 요약) |

### 2.2 해석
- 산출물은 **라우트 1개 + 서비스 1개 + 응답 스키마 + 형식·파일명 검증 함수**다. 새 테이블·마이그레이션·Repository는 없다.
- "다중 파일"은 **API가 한 요청에 여러 파일을 받을 수 있음**으로 읽는다. 프론트가 파일마다 요청을 나눠 보내는 것도 "다중 파일 업로드" 화면 요구를 만족한다(§3).
- "형식 검증(크기 제한은 C-02)": 요청 크기는 미들웨어가 이미 막는다. W-07은 확장자·내용 형식·파일명·빈 파일을 본다.
- "202 응답": 처리(STT·분석)가 아니라 **`inbox/` 업로드까지 끝난 시점**의 응답이다. 202를 돌려줄 때 파일은 이미 `inbox/`에 있다(Drive는 업로드 완료 후에만 목록에 나타남). 처리 결과는 프론트가 상태 모니터링(W-01 폴링)으로 본다.
- 업로드된 건이 목록에 나타나는 시점은 Dispatcher가 등록한 뒤(최대 Time Trigger 주기, 5분 **[가정]**)다. 그 전에는 서버가 파일 존재를 모른다(`input_flow.md` §2 A안 단점).

### 2.3 웹 업로드 시 서버가 쓰는 것 / 쓰지 않는 것
| 대상 | W-07이 쓰는가 | 비고 |
|---|---|---|
| `inbox/` (Drive 공유 드라이브 / 로컬 폴더) | **쓴다** — 파일 1개당 `write()` 1회 | Drive: `name`, `parents=[inbox]`, `properties={"source":"web"}`, `mimeType`(W-07이 넘긴 값) |
| `call_record`·`processing_log` 등 DB | **쓰지 않는다** | 등록은 Dispatcher → R-04. "업로드됨" 같은 중간 상태도 없다(상태 머신 시작점은 `REGISTERED`) |
| 음성 사본 저장소(R-03) | **쓰지 않는다** | 사본은 R-04 등록 시 저장 |
| 임시 파일 | 요청 동안만 | Starlette `SpooledTemporaryFile`, 응답 후 FastAPI가 닫음(`file_stack.push_async_callback(body.close)`) |
| 로그 | 쓴다 | 파일명 없이(§10) |

---

## 3. 프론트 초안의 가정 (`origin/front`, 미병합)

| 항목 | 초안 | 위치 |
|---|---|---|
| 요청 | `POST {BASE}/uploads`(`BASE`=`/api`), `multipart/form-data`, 필드 이름 **`files`**(주석 "[확인 필요] 폼 필드 이름") | `src/api/uploads.ts` |
| 파일 수 | **요청 1개 = 파일 1개**. 여러 파일을 고르면 큐로 순차 전송("큰 녹취를 동시에 올리지 않도록") | `uploads.ts` 주석, `pages/UploadsPage.tsx` `queue` |
| 메타데이터 입력 | 없음(담당자·고객사·통화 일시 입력란 없음) | `UploadsPage.tsx` |
| 사전 검사 | 확장자 `wav`·`mp3`(소문자 비교), 크기 `> 100 * 1024 * 1024`면 거절. "최종 판단은 서버" | `src/lib/upload.ts` |
| 타임아웃 | 업로드 요청 5분(기본 15초) | `uploads.ts` `UPLOAD_TIMEOUT_MS` |
| 응답 | 본문을 읽지 않음(`apiUpload` → `Promise<void>`), 성공 시 "접수됨, 처리 대기" 표시 | `api/client.ts`, `UploadsPage.tsx` |
| 에러 | `{code, message, detail}`의 `message`를 그대로 표시. 413은 본문이 없을 때 "파일이 너무 커요." | `client.ts` `toApiError`·`fallbackMessage` |
| 목(mock) | `202` 빈 본문 | `src/mocks/handlers.ts:216-219` |
| 모니터 | 목록 항목 `original_name`·`source_type`(`DRIVE`/`WEB`)을 표시 | `src/api/types.ts:23-24` |

- 프론트 사전 검사는 **파일 크기**만 보지만 서버 한도는 **요청 전체 바이트**(multipart 경계·헤더 포함)다. 100 MiB에 아주 가까운 파일은 프론트 검사를 통과하고 서버에서 413이 날 수 있다(차이는 수백 바이트 수준).
- 응답 본문을 읽지 않으므로 응답 모델을 무엇으로 하든 초안은 깨지지 않는다(빈 본문도 허용).

---

## 4. multipart 처리 (FastAPI / Starlette)

### 4.1 동작 원리 (설치 소스)
- FastAPI는 엔드포인트 실행 전에 `await request.form(**limits)`로 본문 전체를 파싱한다(`fastapi/routing.py:463-468`). 파싱은 이벤트 루프에서 하고, 파일 쓰기는 `UploadFile.write`(스레드풀)로 한다(`starlette/formparsers.py:262-275`).
- 파일 부분마다 `SpooledTemporaryFile(max_size=1 MiB)`(`formparsers.py:135`, `:218`). 1 MiB를 넘으면 디스크 임시 파일로 넘어간다(실측: 900 KiB `_rolled=False`, 2 MiB `_rolled=True`). 파싱이 끝나면 `seek(0)` 상태로 엔드포인트에 넘어온다.
- 응답 후(예외 포함) FastAPI가 폼을 닫는다(`file_stack.push_async_callback(body.close)`).
- 파서 기본 한도: `max_files=1000`, `max_fields=1000`, 텍스트 필드 `max_part_size=1 MiB`(`starlette/requests.py` `form()`). FastAPI 0.165는 앱·라우터·라우트에 `form_limits={"max_files", "max_fields", "max_part_size"}`를 줄 수 있다(`fastapi/_form_limits.py`, `routing.py:953-966`).
- 파서 오류(`MultiPartException`: 경계 없음, 깨진 데이터, 파일·필드 수 초과)는 `HTTPException(400, detail=메시지)` → `_handle_http_exception` → **400 `BAD_REQUEST` "잘못된 요청입니다."**(원문 `detail`은 응답에 나가지 않음).
- 파일명: `Content-Disposition`의 `filename`을 latin-1로 받아 UTF-8로 다시 해석한다(`_user_safe_decode`). RFC 7578에 따라 `filename*=`은 무시한다(`python_multipart/multipart.py:241-246`). `C:\`·`\\`로 시작하는 값만 마지막 성분으로 자른다(IE6 우회, `:249-252`).
- HTML 표준의 multipart 인코딩은 파일명의 `"`·CR·LF를 `%22`·`%0D`·`%0A`로 바꿔 보낸다(WHATWG HTML "multipart/form-data encoding algorithm"). Starlette는 이를 되돌리지 않는다(실측: `a%22b.wav` 그대로) **[확인 필요: 브라우저별]**.

### 4.2 실측 (`list[UploadFile]` 파라미터 `files`, `def` 엔드포인트)
| 요청 | 결과 |
|---|---|
| 파일 2개(한글 NFC 이름 / 같은 이름 NFD) + 텍스트 필드 | 202. 이름은 보낸 그대로(NFD는 `is_normalized("NFC")=False`), `content_type`은 부분 헤더 값, `size` 정확, 스레드 `AnyIO worker thread` |
| `filename="../../etc/a b.wav"` | 202, **이름 그대로** |
| `filename="C:\\Users\\x\\a.wav"` | 202, 이름 `a.wav` |
| `filename=""`, 빈 내용 | 422 `missing` (`loc: ["body","files"]`) |
| `filename*=UTF-8''%EA%B9%80.wav`만 | 422 `value_error` "Expected UploadFile, received: <class 'str'>" (`loc: ["body","files",0]`) |
| `files` 필드 없음 / 다른 필드 이름 | 422 `missing` |
| 0바이트 `a.wav` | **202** (`size=0`) |
| 부분 `Content-Type` 없음 | 202, `content_type=None` |
| `form_limits={"max_files": 2}`에 파일 3개 | 400 `BAD_REQUEST` |
| 본문 1.1 MiB, 한도 1 MiB (`Content-Length` 있음) | 413 `PAYLOAD_TOO_LARGE` |
| chunked 1.25 MiB, 한도 1 MiB | 413 `PAYLOAD_TOO_LARGE`, 엔드포인트 호출 안 됨 |
| OpenAPI | `requestBody` → `Body_<operationId>` 스키마, `files: {type: array, items: {type: string, contentMediaType: application/octet-stream}}`, `required: ["files"]` |

### 4.3 동기 엔드포인트에서 `UploadFile.file` 사용
- `def` 엔드포인트에서는 `UploadFile.read()`(async) 대신 **`upload.file`(동기 파일 객체)**을 직접 쓴다. `file.read(n)`·`file.seek(0)` 모두 블로킹이지만 워커 스레드라 문제없다.
- `InboxWriter.write(name, upload.file, content_type)`에 그대로 넘긴다. Drive는 `MediaIoBaseUpload`가 `seek(0, SEEK_END)`로 크기를 재고 오프셋 0부터 읽고, Local은 `seek(0)` 후 복사한다(W-08 §3.3 "stream 위치"). 매직 바이트를 읽은 뒤 되감지 않아도 전체가 올라가지만, 검증 함수가 `seek(0)`으로 되돌려 두는 편이 의도를 분명히 한다.
- 스레드풀 토큰은 기본 40개이고 로봇 API 등 모든 `def` 엔드포인트가 공유한다. Drive 업로드 1건이 스레드 1개를 수 초~최악 3분 점유한다. 사용자 3명 규모에서는 문제되지 않는다 **[가정]**.
- 동기 엔드포인트는 클라이언트 연결 끊김을 감지하지 못한다. 프론트가 타임아웃으로 끊어도 서버는 업로드를 끝까지 진행한다.

---

## 5. 형식 검증

### 5.1 세 가지 근거 비교
| 근거 | 출처 | 신뢰도 | 용도 |
|---|---|---|---|
| 확장자 | 파일명 | 사용자가 바꿀 수 있음 | Dispatcher가 확장자로 거른다(`input_flow.md` §4.2) → **반드시 허용 목록과 일치해야 함** |
| MIME(클라이언트) | 부분 `Content-Type` | 브라우저가 OS 확장자 매핑으로 정함. 내용과 무관. 없거나 `application/octet-stream`일 수 있음 | 판정 근거로 약함 |
| 매직 바이트 | 파일 앞부분 | 내용 기반. 위조는 가능하나 실수(이름만 바꾼 파일, 다른 형식)는 잡음 | **실질 판정** |

브라우저별 MIME 예(일반적 이해 **[확인 필요]**): wav → `audio/wav`, `audio/x-wav`, `audio/wave`, `audio/vnd.wave`; mp3 → `audio/mpeg`, `audio/mp3`; m4a → `audio/x-m4a`, `audio/mp4`. OS 매핑이 없으면 `application/octet-stream` 또는 빈 값.

### 5.2 매직 바이트 규칙
| 형식 | 규칙 | 비고 |
|---|---|---|
| WAV | 0~3바이트 `RIFF`, 8~11바이트 `WAVE` | `RF64`·`BW64`(4 GiB 초과용), `RIFX`(빅엔디언)는 드묾 → 제외해도 무방 **[가정]**. 코덱(PCM, μ-law, ADPCM 등)은 헤더만으로 알 수 없음 → STT 지원 여부는 ③ 확인 |
| MP3 | (a) 0~2바이트 `ID3`(ID3v2 태그) 또는 (b) 프레임 동기: `b0 == 0xFF` and `(b1 & 0xE0) == 0xE0`, 레이어 비트 `(b1 >> 1) & 0x3 == 0b01`(Layer III), 버전 비트 `(b1 >> 3) & 0x3 != 0b01`(예약값 아님) | Layer III 조건이 없으면 ADTS AAC(`FF F1`/`FF F9`, 레이어 00)도 통과한다. (b)는 `FF FB/FA`(MPEG-1), `FF F3/F2`(MPEG-2), `FF E3/E2`(MPEG-2.5)를 포함. 비트레이트 인덱스 `1111`·샘플레이트 `11` 제외로 오탐을 더 줄일 수 있음(선택). ID3v2 뒤 내용이 정말 MP3인지는 확인하지 않음(태그 크기만큼 건너뛰면 가능, 과함 **[가정]**). 파일 앞에 0 패딩·잡음이 있는 MP3는 거절될 수 있음 |
| M4A (참고) | 4~7바이트 `ftyp`, 8~11바이트 브랜드 `M4A `·`mp42`·`isom` 등 | 허용 형식이 아님(§5.4) |

- 읽을 길이: 12바이트면 위 규칙에 충분하다. `filetype`은 8192바이트를 읽는다.
- 빈 파일(0바이트)·12바이트 미만은 어떤 규칙에도 맞지 않아 자연히 거절된다.
- **확장자와 내용이 서로 맞아야** 한다(`.mp3`인데 WAV 내용이면 거절). Dispatcher·STT는 확장자를 믿고 처리하기 때문이다 **[확인 필요: ③ STT가 확장자로 형식을 정하는지]**.

### 5.3 구현 수단
| 안 | 내용 | 장단점 |
|---|---|---|
| (a) `filetype` 라이브러리 | `filetype.audio.Wav().match(buf)` / `Mp3().match(buf)` 또는 `filetype.guess(buf)` | 이미 의존성. mp3 판정이 좁다(`FF FA`·`FF E3`·`FF E2` 누락, `filetype/types/audio.py:42-52`). `guess`는 다른 매처가 먼저 걸릴 수 있음. 타입 정보 없음(mypy override 있음) |
| (b) 자체 함수 | §5.2 규칙을 10~20줄 함수로 | 규칙이 명시적이고 테스트로 고정하기 쉬움. 라이브러리 동작 변화 영향 없음. `filetype`은 계속 미사용 상태로 남음 |
| (c) (a) + 보완 | WAV는 `filetype`, MP3는 자체 판정 | 두 방식 혼재 |

- R-04(로봇 등록, A 담당)도 "형식 검증"이 필요하다(`features.md` R-04, `architecture.md` §11 "웹·로봇"). 같은 함수를 공유하면 규칙이 어긋나지 않는다. 위치 후보: `app/services/audio_format.py`(서비스 공용) 또는 `app/core/`(공통 모듈) — A와 합의(§13).

### 5.4 허용 확장자
| 항목 | 현황 |
|---|---|
| PRD IN-02 | `.wav`, `.mp3` (기타 **[결정 필요]**) |
| `architecture.md` §10.3 | `ALLOWED_EXTENSIONS` = `wav,mp3` |
| `.env.example` | `ALLOWED_EXTENSIONS=wav,mp3` (Settings 필드 없음 → 무시됨) |
| 프론트 초안 | `['wav', 'mp3']`, `accept=".wav,.mp3"` |
| Dispatcher | wav·mp3 외는 `failed/`(`input_flow.md` §4.2) |
| ③ STT | `.mp3 .wav .m4a .aac .ogg .flac .mp4`(`stt/step1/clova_stt.py:29`, "콘솔 가이드 확인 필요"), 테스트 샘플 `call_01_질의.m4a` |

- 서버만 m4a를 허용하면 Dispatcher가 `failed/`로 보내 처리되지 않는다. 확장은 PRD·Dispatcher·STT가 함께 바뀌어야 한다.
- 설정으로 둘지(`ALLOWED_EXTENSIONS`) 상수로 둘지는 D5. 설정으로 둬도 매직 바이트 규칙이 없는 확장자는 받을 수 없으므로, "설정 값 ⊆ 규칙이 있는 형식"을 시작 시 검증해야 한다.
- 대소문자: 프론트는 소문자로 비교해 `.WAV`를 허용한다. Dispatcher 필터가 대소문자를 구분하는지 **[확인 필요: RPA]**. 서버에서 확장자를 소문자로 바꿔 저장하는 안이 있다(D8).

### 5.5 정규 MIME
Drive에 넘길 `content_type`(Drive `mimeType`):
- (a) 클라이언트 값 그대로 — `application/octet-stream`·`None`이 섞인다. `None`이면 `MediaIoBaseUpload` 호출 형태도 따져야 한다.
- (b) **판정한 형식의 정규값**(`wav` → `audio/wav`, `mp3` → `audio/mpeg`) — 일관되고 Dispatcher MIME 필터(W-08 X2)와 맞추기 쉽다. `audio/wav`는 IANA 등록값이 아니고(`audio/vnd.wave`가 등록값) 실무에서 `audio/wav`·`audio/x-wav`가 흔하다 **[확인 필요: Drive가 표시하는 형식·Dispatcher 필터]**.

---

## 6. 파일명 처리

### 6.1 규칙 파일명을 서버가 만들 것인가
| 안 | 내용 | 영향 |
|---|---|---|
| (a) 원래 이름 유지 | 사용자가 고른 파일 이름(정규화만)을 그대로 `inbox/`에 씀 | 문서(`architecture.md:448`)·프론트 초안과 일치. 규칙에 안 맞으면 `metadata_incomplete=true` → W-12 보정 |
| (b) 선택 입력으로 규칙 파일명 생성 | 요청에 `agent_name`·`client_company`·`call_datetime`(선택 Form 필드)을 받아 셋이 다 있으면 `{yyyyMMdd_HHmmss}_{담당자}_{고객사}.{ext}`로 이름을 만든다 | 프론트 화면·API 계약·문서 변경. 파일명 규칙이 아직 **[결정 필요]**라 규칙이 바뀌면 서버도 바뀜. 값에 `_`·금지 문자가 있으면 파싱이 깨짐 → 별도 검증 필요. 파일당 메타데이터라 다중 파일 요청에서 필드 대응이 복잡 |
| (c) 이름 규칙 검사만 | 규칙에 맞는지 서버가 검사해 응답에 경고 표시 | Dispatcher 파서와 같은 규칙을 서버가 중복 구현. 규칙 미확정 |

- 요구사항(IN-03·W-07)에는 업로드 시 메타데이터 입력이 없다. (b)·(c)는 요구 범위 밖의 추가 기능이다.

### 6.2 정규화·검사 단계 (안)
| 순서 | 처리 | 근거 |
|---|---|---|
| 1 | `filename`이 `None`/빈 값이면 거절 | 실측상 FastAPI가 먼저 422로 막지만 방어 |
| 2 | 경로 성분 제거: `/`·`\` 기준 마지막 성분 (`PurePosixPath`/`PureWindowsPath` 또는 `rsplit`) | Starlette는 `../`를 지우지 않는다(실측). 브라우저는 보통 이름만 보낸다 |
| 3 | `unicodedata.normalize("NFC", name)` | macOS 브라우저의 NFD 한글(W-08 D14). Dispatcher 담당자 이름 비교 대비 |
| 4 | 앞뒤 공백 처리(제거 또는 거절) | Windows는 끝 공백·점을 잘라 다른 이름이 됨(W-08 L2) |
| 5 | 금지 문자·제어 문자·`.`/`..` 거절 | `validate_local_name`과 같은 집합(`\ / : * ? " < > \|`, 코드 < 32). 로봇 PC(Windows) 다운로드 대비 **[확인 필요: RPA]** |
| 6 | 길이 상한 | NTFS 경로 성분 255(UTF-16 단위). Drive 이름 길이 상한은 공식 문서에서 찾지 못함 **[확인 필요]**. 200~255자 **[가정]** |
| 7 | 확장자 분리·허용 목록 확인 | `rpartition(".")`, 소문자 비교. 확장자 없음·`.wav`(이름 없음) 처리 |

- 2단계를 "제거"가 아니라 "경로가 있으면 거절"로 할 수도 있다. 정상 브라우저는 경로를 보내지 않으므로 어느 쪽이든 사용자 영향은 거의 없다.
- Windows 예약 이름(`CON`, `NUL` 등)은 W-08도 다루지 않았다. 녹취 파일명이 이런 이름일 가능성은 낮다 **[가정]**.
- `%22` 등 브라우저 퍼센트 인코딩은 되돌리지 않는다(되돌리면 `"`가 생겨 5단계에서 거절됨). 녹취 파일명에 `"`가 들어갈 일은 드묾 **[가정]**.
- 정규화 결과가 실제 `inbox/` 파일 이름이고, Dispatcher가 이 이름을 등록 시 보내면 `call_record.original_name`이 된다 **[확인 필요: R-04가 `original_name`을 어디서 받는지]**.
- 같은 이름 중복: Drive는 같은 폴더의 같은 이름을 허용(접미사 불필요, `architecture.md:448`). Local은 ` (n)` 접미사(W-08 D11). 서버는 처리하지 않는다.

---

## 7. API 초안

### 7.1 경로·요청
```
POST /api/uploads
Content-Type: multipart/form-data
  files: <파일>        (1개 이상, 같은 이름 반복)
```
- 라우터: `APIRouter(prefix="/api/uploads", tags=["uploads"])`(`convention.md` §7-4 태그 `uploads`), 경로 `""`, `status_code=202`.
- 함수 이름(= operationId, 앱 전체 고유): 예 `upload_files` → OpenAPI 스키마 `Body_upload_files`.
- 엔드포인트는 **`def`**(H3). 파라미터 `files: Annotated[list[UploadFile], File()]`.
- 단일 필드 `file`로 받는 안도 있으나, 프론트 초안이 `files`를 쓰고 IN-03이 다중 파일이라 `files` 목록이 양쪽을 다 받는다(1개도 목록).
- 파일 수 상한: 요청 크기 한도가 사실상 상한이지만, 최악 응답 시간(§9.3) 때문에 개수 상한을 두는 안이 있다(D3).

### 7.2 응답 (202)
| 안 | 본문 | 비고 |
|---|---|---|
| (a) 접수 목록 | `{"items": [{"name": "20261123_143005_김상담_A산업.mp3"}]}` | `convention.md` §2.3-3(최상위 배열 금지). `name`은 정규화된 실제 저장 이름 → 모니터 목록의 `original_name`과 맞춰 볼 수 있음 |
| (b) (a) + 파일 식별자 | `{"items": [{"name": …, "file_id": "…"}]}` | Drive는 파일 ID, Local은 저장 파일명(접미사 포함)이라 의미가 백엔드마다 다르다. 프론트 사용처 없음. Drive 파일 ID 자체는 권한 없이는 열 수 없지만 굳이 노출할 이유가 없음 |
| (c) 본문 없음 | 202 빈 본문 | 프론트 목과 같음. 이후 필드 추가가 호환 변경이 되려면 객체가 나음 |
| (d) 개수만 | `{"accepted": 1}` | 최소 |

- (a)에서 Local writer가 붙인 접미사(` (1)`)는 개발용이라 응답에 반영하지 않아도 된다. 반영하려면 `write()` 반환값(Local = 저장 파일명)을 쓰면 되지만 Drive에서는 파일 ID라 섞인다.
- 응답 모델 이름 후보: `UploadResponse`, `UploadedFile`(`convention.md` §5.5 요청·응답 모델 분리).

### 7.3 에러 매핑
| 상황 | 코드 | HTTP | 발생 위치 | `detail` |
|---|---|---|---|---|
| 요청 크기 > `MAX_UPLOAD_MB` | `PAYLOAD_TOO_LARGE` | 413 | 미들웨어(C-02) | `null` |
| multipart 깨짐·경계 없음·파서 한도(`max_files` 등) 초과 | `BAD_REQUEST` | 400 | Starlette 파서 → 핸들러 | `null` |
| `files` 없음·빈 파일명·`filename*`만 | `VALIDATION_ERROR` | 422 | FastAPI | `{"errors":[{"loc":["body","files"(,i)], …}]}` |
| 파일 수 > 상한 (D3에서 서비스 검사 시) | `VALIDATION_ERROR` | 422 | 서비스 | `errors[{loc:["body","files"], type:"too_many_files"}]` 형태 후보 |
| 파일명 금지 문자·길이 초과·경로 | `VALIDATION_ERROR` | 422 | 서비스 | `errors[{loc:["body","files",i], type:"filename_invalid"}]` 형태 후보. **이름 값은 넣지 않음**(`convention.md` §3.4-3) |
| 확장자 불허·확장자 없음 | `UNSUPPORTED_MEDIA` | 415 | 서비스 | `{"index": i}` 또는 `null` (D9) |
| 내용(매직 바이트)이 확장자와 불일치·빈 파일 | `UNSUPPORTED_MEDIA` | 415 | 서비스 | 위와 같음 |
| `writer is None` (disabled) | `INBOX_UNAVAILABLE` | 503 | 서비스 | `null` (H1) |
| `InboxUnavailableError` (재시도 소진·권한·설정·로컬 I/O) | `INBOX_UNAVAILABLE` | 503 | 서비스 변환 | `null` 또는 부분 실패 정보(§8.3). `reason` 넣지 않음(H2) |
| `LocalInboxWriter`의 `ValueError` | (검증에서 먼저 막아야 함) | 500 | — | 6.2 규칙이 `validate_local_name`을 포함하면 발생하지 않음 |
| 그 밖의 예외 | `INTERNAL_ERROR` | 500 | `UnhandledErrorMiddleware` | — |

- 에러는 모두 `AppError(ErrorCode.X, detail=…)`로 던진다(`convention.md` §3.4-2). 422를 서비스에서 만들 때 `detail` 형식은 `{"errors":[{"loc","msg","type"}]}`(`ValidationErrorDetail`)를 따라야 프론트가 같은 방식으로 읽는다. `msg`는 고정 문구(입력값 미포함).
- 빈 파일을 415로 볼지 422로 볼지: 내용 판정 실패와 같은 경로라 415가 단순하다. "형식"이 아니라 "값" 문제로 보면 422.
- OpenAPI: `responses=error_responses(ErrorCode.BAD_REQUEST, ErrorCode.PAYLOAD_TOO_LARGE, ErrorCode.UNSUPPORTED_MEDIA, ErrorCode.INBOX_UNAVAILABLE)`(422·500은 앱 전체에 이미 있음). `convention.md:40`의 400·413·415·422·503과 일치.

---

## 8. 처리 흐름

### 8.1 검증 순서 (안)
```
[미들웨어]  Content-Length / 누적 바이트 > 한도 → 413
[FastAPI]   multipart 파싱 (400) → files 파라미터 검증 (422)
[서비스]
  0. writer is None → 503                       (D10: 0을 맨 앞에 둘지)
  1. 파일 수 > 상한 → 422                        (D3)
  2. 파일마다: 이름 정규화·검사 → 422
               확장자 허용 → 415
               매직 바이트 판정(12바이트 읽고 seek(0)) → 415
  3. (전부 통과한 뒤) 파일마다 순차: writer.write(정규화 이름, upload.file, 정규 MIME)
        InboxUnavailableError → 503 (§8.3 정책)
  4. 202 응답
```
- **모든 파일을 먼저 검증하고 그다음 업로드**하면 "형식 오류인 파일 때문에 일부만 올라간" 상태가 생기지 않는다. 검증 실패 응답은 업로드 전에 나가므로 `inbox/`에는 아무것도 없다.
- 0단계 위치: 본문 파싱은 이미 끝난 뒤라 비용 차이는 없다. 맨 앞이면 "기능이 꺼져 있음"을 형식 오류보다 먼저 알려 준다. 맨 뒤면 disabled 환경(Phase 1·단위 테스트 기본)에서도 형식 검증 응답을 확인할 수 있다.
- 업로드는 **순차**(W-08 리서치 §3.8: 병렬화 불필요, httplib2 스레드 안전성·할당량 측면에서도 안전).

### 8.2 `InboxWriter`가 `None`일 때
- `INBOX_BACKEND=disabled`(코드 기본값, Phase 1)이면 `get_inbox_writer`가 `None`을 준다. W-07은 **503 `INBOX_UNAVAILABLE`**(H1, D8). 메시지 기본 문구 그대로.
- 라우트는 disabled여도 등록한다(OpenAPI 계약이 설정에 따라 바뀌지 않게).
- 서비스 생성: `UploadService(writer: InboxWriter | None)`로 받고 서비스가 `None`을 처리하는 안, 또는 의존성 함수(`get_upload_service`)에서 `None`이면 바로 `AppError`를 던지는 안. 후자는 형식 검증보다 503이 항상 먼저가 된다(D10과 연동).

### 8.3 여러 파일 중 일부 실패 (Drive 업로드 단계)
검증은 §8.1대로 업로드 전에 끝나므로, 부분 실패는 **업로드 단계의 `InboxUnavailableError`**만 해당한다.

| 안 | 동작 | 응답 | 장단점 |
|---|---|---|---|
| (a) 첫 실패에서 중단 | 순차 업로드, 실패하면 남은 파일은 시도하지 않음 | 503, `detail: null` | 가장 단순. 이미 올라간 파일은 `inbox/`에 남아 정상 처리된다. 사용자는 어느 파일이 들어갔는지 모르고 전체를 다시 올릴 수 있다 → 중복은 Dispatcher 409로 정리(`input_flow.md` §6.2) |
| (a') (a) + 성공 개수 | (a)와 같음 | 503, `detail: {"accepted": k}` 또는 `{"accepted_names": [...]}` | 사용자에게 부분 성공을 알릴 수 있음. 이름 목록은 입력값 반향이라 `convention.md` §3.4-3과 충돌 소지(개수·인덱스는 무방) |
| (b) 모두 시도, 파일별 결과 | 실패해도 다음 파일 계속 | 전부 실패면 503, 일부 성공이면 202 + `items[{name, status: "ACCEPTED"/"FAILED"}]` | 정보가 가장 많음. 202인데 실패가 섞여 프론트 처리 분기 증가. Drive 장애 시 실패가 확실한 시도를 파일 수만큼 반복(파일당 최악 3분) |
| (c) 사전 `check()` 후 (a) | 업로드 전 `writer.check()`로 접근 확인 | (a)와 같음 | 권한·설정 오류는 업로드 전에 걸러짐. 요청마다 Drive 호출 1회 추가, 일시 오류는 여전히 업로드 중 발생 |

- 프론트 초안은 **파일마다 요청을 나눠** 보내므로(§3) 어떤 안이든 프론트가 보는 결과는 "그 파일 성공/실패"와 같다. 정책 차이는 한 요청에 여러 파일을 보내는 클라이언트(다른 도구, 이후 화면 변경)에만 나타난다.
- 중복 파일이 `inbox/`에 들어가면: 원본이 처리 중(`QUEUED` 등)이면 Dispatcher는 아무것도 하지 않아 중복 파일이 `processing/`에 남고, 다음 주기들에 재등록 시도 → 원본이 `STORED`·`NEEDS_REVIEW`가 되면 `done/`으로 이동한다(`input_flow.md` §6.1·§6.2). 최종적으로 정리되지만 그동안 Dispatcher 호출이 반복된다.

---

## 9. 크기 제한·스트리밍·시간

### 9.1 크기
- 한도는 **요청 전체 바이트**, `MAX_UPLOAD_MB`(MiB) × 1024²(`config.py` `max_upload_bytes`). multipart 경계·헤더 포함. 여러 파일이면 합계 기준(`plans/common-module.md` 결정 3).
- W-07에서 파일별 크기 한도를 따로 둘 요구는 없다. 파일 하나 ≤ 요청 한도.
- 프론트가 파일마다 요청을 나누므로 실질적으로 "파일 하나 ≤ 약 100 MiB"가 된다.
- 0바이트 파일은 §5.2에서 거절된다.

### 9.2 스트리밍
- 클라이언트 → 서버: Starlette가 본문을 끝까지 받아 임시 파일에 쓴 뒤 엔드포인트 실행(§4.1). 메모리는 파일당 최대 1 MiB, 나머지는 디스크.
- 서버 → Drive: `MediaIoBaseUpload(resumable=True)`, 청크 기본 100 MiB라 한도 안에서는 세션 POST 1회 + PUT 1회(W-08 D5). 임시 파일에서 읽어 보낸다.
- 결과적으로 요청 하나는 임시 디스크를 최대 약 `MAX_UPLOAD_MB` 쓴다. 동시 업로드 수만큼 곱해진다. 컨테이너 임시 디렉터리 용량·쓰기 권한(non-root, O-01) **[확인 필요: A·O-01]**. Linux에서 `TemporaryFile`은 생성 직후 이름이 지워져(익명) 다른 프로세스에 보이지 않는다.
- 클라이언트 → Drive 직접 스트리밍(본문 파싱 없이 `request.stream()`을 Drive로 흘려보내기)은 `def` 엔드포인트·형식 선검증(앞 12바이트)·다중 파일과 맞지 않고 구현이 복잡하다. 요구 규모에서 필요 없다 **[가정]**.

### 9.3 시간
| 구간 | 최악 | 근거 |
|---|---|---|
| 클라이언트 → 서버 전송 | 망 속도 의존 (100 MiB, 사내망) | — |
| 파일 1개 Drive 업로드 | 약 3분 | H6: 타임아웃 30초 × (요청 + 재시도·상태 조회) + 백오프 |
| 자격 증명 없음(비 GCP) | 호출마다 약 3초 추가 | H5: GCE 메타데이터 확인. `NO_GCE_CHECK=true`로 끔 |
| 프론트 타임아웃 | 요청당 5분 | `uploads.ts` |

- 파일 N개를 한 요청에 담으면 최악 `N × 3분`. 파일 수 상한(D3)을 두면 이 값이 제한된다. 프론트가 1개씩 보내는 한 최악 3분 < 5분.
- Uvicorn은 요청 처리 시간 제한이 없다(별도 설정 없음). 앞단 프록시를 두지 않는 구성(`architecture.md` §10.1)이라 프록시 타임아웃도 없다.

---

## 10. 보안·PII·로그

- **파일명에 담당자 이름·고객사**가 들어간다(`input_flow.md` §7). W-08 D12와 같이 **로그에 파일명을 남기지 않는 것**을 기본으로 한다. 추적은 `request_id`(자동 바인딩), 파일 수, 크기, (Drive) 파일 ID로 한다. 어댑터가 이미 `inbox_written`(info: `file_id`, `size_bytes`)·`inbox_write_failed`(warning: `reason`)를 남긴다.
- 서비스 로그 후보: `upload_accepted`(파일 수, 총 바이트), `upload_rejected`(코드, 파일 인덱스·이유 분류 — 이름 없이). 중복 로그를 피하려면 어댑터 로그로 충분한지 계획에서 정한다.
- `InboxUnavailableError` 변환 시 **`exc_info`로 로그를 남기지 않는다**(H7: `__cause__`에 키 파일 경로 등이 있을 수 있음). `AppError` 핸들러는 로그를 남기지 않으므로 `raise AppError(...) from exc`도 응답·로그에 원인을 노출하지 않는다. 원인 체인을 아예 끊으려면 `from None`.
- 응답 `message`·`detail`에 파일명·`reason`·Drive 오류 원문·폴더 ID·서비스 계정 정보를 넣지 않는다(`convention.md` §3.4·§6, H2).
- 422 `msg`는 고정 문구(`ValueError("파일명에 사용할 수 없는 문자가 있습니다")` 같은 형태, 입력값 미포함). FastAPI 기본 검증 오류는 핸들러가 `input`을 지워서 내보낸다(`errors.py` `_handle_validation_error`).
- 음성 내용(고객 음성 = PII)은 요청 동안 임시 파일에만 있고 응답 후 닫힌다. 서버에 사본을 남기지 않는다(사본 보관은 R-04).
- 매직 바이트 검증은 "실수 방지" 수준이다. 악성 파일 탐지가 아니다. 업로드된 파일은 서버에서 실행·해석하지 않고 Drive로 넘기기만 한다. 하류(STT 디코더)가 신뢰할 수 없는 입력을 다룬다는 점은 ③에 공유할 사항.
- 접근 통제: 웹 API는 인증 없음, VM 방화벽 IP 허용 목록(`architecture.md` §7.1). 사내망 누구나 `inbox/`에 파일을 넣을 수 있다는 뜻이므로 개수·크기 한도가 남용 방지 역할을 겸한다.
- CORS: `CORSMiddleware`가 `allow_methods=["*"]`라 multipart POST preflight도 통과한다(C-02).

---

## 11. 테스트 전략

| 수준 | 대상 | 방법 | 필요 환경 |
|---|---|---|---|
| 단위 | 파일명 정규화·검사 함수 | 표 기반 parametrize: NFD→NFC, `../a.wav`, `a\\b.wav`, 금지 문자 각각, 제어 문자, 끝 공백·점, 길이 경계, 확장자 대소문자·없음 | 없음 |
| 단위 | 형식 판정 함수 | 최소 헤더 바이트: `b"RIFF\x00\x00\x00\x00WAVE"`, `b"ID3\x04\x00…"`, `b"\xff\xfb\x90\x00"`, `\xff\xfa`, `\xff\xe3`, ADTS `\xff\xf1`(거절), `ftypM4A`(거절), 빈 값, 11바이트, 확장자-내용 불일치. 판정 후 스트림 위치가 0인지 | 없음 |
| 단위 | `UploadService` | **가짜 `InboxWriter`**(받은 이름·바이트·`content_type` 기록, N번째 호출에서 `InboxUnavailableError` 주입). 검증 실패 시 `write` 미호출, 순차 호출, 부분 실패 정책, `None` → 503, 정규 MIME 전달, `reason`이 `AppError`에 없음 | 없음 |
| 단위(라우터) | `POST /api/uploads` | `build_app()` + `app.state.inbox_writer = Fake()`(또는 `dependency_overrides[get_inbox_writer]`) + `TestClient`. 202 본문, 400(깨진 multipart), 413(한도 작게), 415, 422(`files` 없음·이름), 503(기본 disabled 그대로), `X-Request-Id`, 업로드 후 파일 닫힘 | 없음 |
| 단위(실제 어댑터) | 라우트 + `LocalInboxWriter` | `build_app(inbox_backend="local", inbox_local_path=tmp_path)`로 실제 파일이 NFC 이름·원본 바이트로 생기는지, 같은 이름 두 번 → ` (1)` | 없음(`tmp_path`) |
| 단위 | OpenAPI | `responses`에 400·413·415·503, `requestBody` `multipart/form-data` `files` 배열, 커밋된 `openapi.json` 갱신(`test_committed_openapi_is_up_to_date`) | 없음 |
| 단위 | 로그 | `caplog`/structlog 캡처로 파일명이 로그에 없음 | 없음 |
| 수동 | Drive 실연동 | W-08 수동 테스트(`tests/drive/`, `drive` 마커)로 충분. 필요하면 라우트 경유 1건 추가 | E-01 |

- 기존 `tests/unit/conftest.py`의 `/upload` 테스트 라우트는 C-02 검증용이라 W-07과 별개다.
- 가짜 writer는 `InboxWriter` Protocol을 구조적으로 만족하면 된다(상속 불필요, mypy가 확인).
- DB를 쓰지 않으므로 `integration` 마커 테스트는 필요 없다. "LocalInboxWriter 통합"은 `architecture.md` §13 "통합: LocalInboxWriter(임시 폴더)"에 해당하지만 DB가 없어 단위 디렉터리에 둘 수 있다(위치는 계획에서 결정).
- 큰 파일(> 1 MiB, 디스크 스풀) 경로도 1건 확인하면 `upload.file`이 디스크 파일일 때도 동작함을 보장한다.

---

## 12. 기존 패턴을 따르는 파일·함수 후보

| 파일 | 내용 |
|---|---|
| `app/api/web/uploads.py` (신규) | `router = APIRouter(prefix="/api/uploads", tags=["uploads"])`, `@router.post("", status_code=202, responses=error_responses(...))`, `def upload_files(files: Annotated[list[UploadFile], File()], service: UploadServiceDep) -> UploadResponse` |
| `app/services/upload_service.py` (신규) | `UploadService(writer: InboxWriter \| None)`, `upload(files) -> UploadResponse`, 검증 → 순차 `write` → `InboxUnavailableError` 변환 |
| `app/schemas/upload.py` (신규) | `UploadedFile`, `UploadResponse` |
| 형식·파일명 검증 함수 (신규) | 서비스 파일 안 private 함수 또는 공용 모듈(R-04와 공유 시, §5.3) |
| `app/api/deps.py` (수정) | `get_upload_service(writer: Annotated[InboxWriter \| None, Depends(get_inbox_writer)]) -> UploadService` |
| `app/main.py` (수정) | `app.include_router(uploads.router)` |
| `app/core/config.py` (수정, D5 선택 시) | `allowed_extensions` 필드(쉼표 구분, `cors_origins`와 같은 `NoDecode` + `_split_comma` 방식) |
| `tests/unit/test_upload_*.py` (신규) | §11 |
| `docs/api/openapi.json` (재생성) | `uv run python -m scripts.export_openapi` |

```python
# 스케치 (설명용)
@router.post("", status_code=202, responses=error_responses(
    ErrorCode.BAD_REQUEST, ErrorCode.PAYLOAD_TOO_LARGE,
    ErrorCode.UNSUPPORTED_MEDIA, ErrorCode.INBOX_UNAVAILABLE))
def upload_files(
    files: Annotated[list[UploadFile], File()],
    service: UploadServiceDep,
) -> UploadResponse:
    return service.upload(files)


class UploadService:
    def __init__(self, writer: InboxWriter | None) -> None:
        self._writer = writer

    def upload(self, files: list[UploadFile]) -> UploadResponse:
        if self._writer is None:
            raise AppError(ErrorCode.INBOX_UNAVAILABLE)
        checked = [_check(i, f) for i, f in enumerate(files)]   # (이름, 파일 객체, 정규 MIME), 실패 시 AppError
        for name, stream, mime in checked:
            try:
                self._writer.write(name, stream, mime)
            except InboxUnavailableError:
                raise AppError(ErrorCode.INBOX_UNAVAILABLE) from None   # reason·원인 체인 비노출
        return UploadResponse(items=[UploadedFile(name=n) for n, _, _ in checked])
```
- 서비스가 `UploadFile`(FastAPI 타입)을 받을지, `(filename, BinaryIO)` 쌍으로 바꿔 받을지는 계획에서 정한다. 후자면 서비스 테스트에 `UploadFile`을 만들 필요가 없다.

---

## 13. 다른 파트 확인 필요

| 대상 | # | 항목 | 내용 |
|---|---|---|---|
| ② 프론트 | F1 | **필드 이름·전송 방식** | `files` 필드, 파일마다 요청 1개(현행 초안) 유지 여부. API는 여러 파일도 받음 |
| ② 프론트 | F2 | 응답 본문 | 202 본문 형태(§7.2). 초안은 읽지 않으므로 어떤 형태든 호환 |
| ② 프론트 | F3 | 에러 표시 | 415·422·503 `message` 그대로 표시. 422 `detail.errors[].loc`의 파일 인덱스 사용 여부. 503 문구 "업로드 저장소를 사용할 수 없습니다."가 disabled·Drive 장애 모두에 쓰임 |
| ② 프론트 | F4 | 크기 경계 | 프론트 검사는 파일 크기, 서버는 요청 전체 바이트 → 100 MiB 근처 파일은 서버 413 가능 |
| ② 프론트 | F5 | 확장자 대소문자 | 프론트는 `.WAV` 허용. 서버·Dispatcher와 맞추기(D8) |
| ④ RPA | X1 | `properties.source=web` | W-08 §9.2 X1 그대로(미합의) |
| ④ RPA | X2 | MIME | Drive `mimeType`을 서버가 정규값(`audio/wav`·`audio/mpeg`)으로 넣는 안. Dispatcher 필터가 확장자·MIME 중 무엇을 보는지 |
| ④ RPA | X3 | 파일명 | NFC 정규화, 확장자 대소문자, Windows 금지 문자·길이(로봇 PC 다운로드), 파일명 규칙 확정(`input_flow.md` §7) |
| ④ RPA | X5 | `original_name` | Dispatcher가 등록 시 보내는 파일명 = `inbox/` 파일 이름인지 |
| ③ STT | S1 | 형식·코덱 | m4a 등 추가 형식 지원 여부(PRD IN-02 **[결정 필요]**), WAV 코덱(PCM 외) 지원 범위, 확장자로 형식을 정하는지 |
| A (백엔드) | A1 | **형식 검증 공유** | R-04도 같은 "확장자 + MIME + 매직 바이트" 검증 필요. 공용 함수 위치·규칙 합의 |
| A (백엔드) | A2 | `ALLOWED_EXTENSIONS` | Settings 필드 추가 시 R-04와 같은 설정을 쓰는지 |
| A (백엔드) | A3 | `filetype` 의존성 | 자체 판정(§5.3 (b))을 쓰면 `filetype`이 계속 미사용. 유지 여부는 C-01 소유자 판단 |
| A / O-01 | A4 | 임시 디렉터리 | 컨테이너 임시 디렉터리 용량·non-root 쓰기 가능 여부(요청당 최대 약 100 MiB) |
| E-01 | E1 | 실제 Drive | W-08 §9.3 E1~E6 (W-07 자체 추가 항목 없음) |

---

## 14. 미정 사항 (선택지와 권장안)

| ID | 항목 | 선택지 | 권장안 |
|---|---|---|---|
| **D1 [핵심]** | 요청 형식 | (a) `files: list[UploadFile]` (1개 이상) (b) `file: UploadFile` 단일 | **(a)**. IN-03 "다중 파일"과 프론트 초안 필드 이름 `files`를 모두 만족하고, 1개 전송도 그대로 받는다 |
| **D2 [핵심]** | 부분 실패 정책(§8.3) | (a) 첫 실패에서 중단, 503 `detail: null` (a') (a) + 성공 개수 (b) 모두 시도 + 파일별 결과 (c) 사전 `check()` + (a) | **(a)**. 검증은 업로드 전에 전부 끝내므로 부분 실패는 Drive 장애뿐이고, 프론트는 파일마다 요청을 보내 차이가 드러나지 않는다. 다중 파일 클라이언트가 생기면 (a')로 확장(개수만, 이름 미포함) |
| D3 | 파일 수 상한 | (a) 없음(요청 크기로만 제한) (b) 서비스 검사 → 422 (c) `form_limits={"max_files": N}` → 400 | **(b)**, N = 10 **[가정]**. 최악 응답 시간(N × 3분)을 제한하고, 422 `loc`로 원인이 분명하다. 파서 기본 한도(1000)는 그대로 |
| **D4 [핵심]** | 파일명 생성 | (a) 원래 이름 유지(정규화만) (b) 선택 메타데이터 입력으로 규칙 파일명 생성 (c) 규칙 검사·경고만 | **(a)**. 문서(`architecture.md:448`)·요구(IN-03)·프론트 초안과 일치. 규칙 미확정 상태에서 서버가 규칙을 복제하지 않는다. 메타데이터 누락은 W-12 보정 경로가 있다 |
| **D5 [핵심]** | 허용 형식·설정 | (a) wav·mp3 고정 상수 (b) `ALLOWED_EXTENSIONS` Settings 필드(규칙 있는 형식만 허용하도록 시작 시 검증) (c) m4a 추가 | **(b)** wav·mp3. `.env.example`·`architecture.md` §10.3에 이미 있는 변수라 필드만 추가하면 된다. m4a 등은 PRD IN-02 결정·Dispatcher·STT 변경과 함께. R-04와 같은 설정을 쓰도록 A와 합의(A2). 설정 없이 가려면 (a) |
| **D6 [핵심]** | 형식 판정 방식 | (a) `filetype` (b) 자체 함수(§5.2) (c) 혼합 / MIME: (d) 클라이언트 MIME도 허용 목록으로 거절 (e) 클라이언트 MIME은 판정에 쓰지 않음 | **(b) + (e)**. 매직 바이트(+ 확장자 일치)를 판정 기준으로 하고, 브라우저 MIME은 OS 매핑이라 거절 근거로 쓰지 않는다(정상 파일 오거절 방지). "MIME 검증"은 내용에서 판정한 형식의 MIME으로 해석. `filetype`은 mp3 변형을 놓친다. R-04와 공유(A1) |
| D7 | Drive에 넘길 MIME | (a) 클라이언트 값 (b) 판정 형식의 정규값 | **(b)** `audio/wav`·`audio/mpeg`. Dispatcher와 확인(X2) |
| D8 | 확장자 대소문자 | (a) 대소문자 무시 허용, 이름 그대로 (b) 허용 + 확장자만 소문자로 바꿔 저장 (c) 소문자만 허용 | **(b)** — Dispatcher 필터가 대소문자를 구분해도 안전. RPA 확인(X3) 후 (a)로 단순화 가능 |
| D9 | 415 `detail` | (a) `null` (b) `{"index": i}` | **(b)**. 다중 파일 요청에서 어떤 파일인지 알려 주되 입력값(이름)은 넣지 않는다. 프론트는 1개씩 보내 무시해도 됨 |
| D10 | disabled 503 위치 | (a) 검증보다 먼저 (b) 검증 뒤(업로드 직전) | **(a)**. 기능이 꺼져 있으면 무엇을 올려도 소용없으므로 먼저 알린다. 형식 검증 테스트는 가짜 writer를 주입해 수행 |
| D11 | 경로 성분 | (a) 마지막 성분만 취함 (b) 경로가 있으면 422 | **(a)**. 일부 클라이언트(구형 브라우저·도구)가 경로를 보내도 동작. 결과 이름은 6.2의 나머지 검사를 거침 |
| D12 | 금지 문자·공백 | (a) 거절(422) (b) `_` 치환 | **(a)**. `validate_local_name`과 같은 집합 + 앞뒤 공백·끝 점 거절. 치환은 고객사 값 등 메타데이터를 조용히 바꾼다. RPA 확인(X3) |
| D13 | 파일명 길이 상한 | 200 / 255자 / 바이트 기준 | **255자**(NTFS 성분 한도) **[가정]**. Drive 상한은 확인 필요 |
| D14 | 응답 본문(§7.2) | (a) `{items:[{name}]}` (b) + `file_id` (c) 빈 본문 (d) 개수 | **(a)**. 객체라 이후 필드 추가가 호환 변경이고, 정규화된 이름을 돌려줘 모니터 목록과 맞춰 볼 수 있다 |
| D15 | 빈 파일 코드 | (a) 415 (b) 422 | **(a)**. 매직 바이트 판정 실패와 같은 경로 |
| D16 | 서비스 입력 타입 | (a) `UploadFile` 목록 (b) `(filename, BinaryIO, content_type)` 값 객체 | 계획에서 결정. (b)면 서비스가 FastAPI 타입에 의존하지 않고 테스트가 단순 |
| D17 | 검증 함수 위치 | (a) `upload_service.py` 내부 (b) 공용 모듈(R-04와 공유) | A 합의(A1) 전에는 (a)로 두고 공유 시 이동. 합의가 먼저 되면 (b) |

외부 의존 미결(이 기능이 영향받는 것):
- 파일명 규칙 확정(`input_flow.md` §7 **[결정 필요]**) — W-07 동작에는 영향 없음(D4 (a)일 때), 화면 안내 문구에 영향.
- PRD IN-02 지원 형식 확정 — D5.
- E-01(서비스 계정·공유 드라이브) — 실제 Drive 업로드 확인. 그전에는 `INBOX_BACKEND=local`로 개발.

---

## 15. 구현 시 주의
1. 라우트는 `def`로 둔다. `async def`에서 `writer.write()`를 직접 부르면 이벤트 루프가 최대 수 분 막힌다(H3).
2. `InboxUnavailableError.reason`·원본 예외를 응답·`exc_info` 로그에 넣지 않는다(H2·H7).
3. 로그·422 `msg`·`detail`에 파일명을 넣지 않는다(D12 W-08, `convention.md` §3.4-3).
4. **검증을 모두 끝낸 뒤 업로드**한다. 파일 하나 검증 실패로 앞 파일만 올라간 상태를 만들지 않는다.
5. 매직 바이트를 읽은 뒤 `seek(0)`. 어댑터도 처음부터 읽지만 의도를 분명히 한다.
6. 라우트 추가 후 `openapi.json`을 재생성해 같은 PR에 넣는다(`convention.md` §7-1). 함수 이름은 앱 전체에서 고유해야 한다.
7. DB 세션을 주입하지 않는다(W-07은 DB를 쓰지 않음).
8. `LocalInboxWriter`의 `ValueError`가 500이 되지 않도록 W-07 파일명 검사가 `validate_local_name` 규칙을 포함해야 한다(H4).

---

## 16. 참고 자료
- FastAPI — Request Files: https://fastapi.tiangolo.com/tutorial/request-files/
- Starlette — Requests (form, `max_files`·`max_fields`·`max_part_size`): https://www.starlette.io/requests/
- 설치 소스: `.venv/Lib/site-packages/starlette/formparsers.py`(`spool_max_size` `:135`, 파일 부분 `:208-229`, 파싱 `:235-288`), `starlette/requests.py`(`MultiPartException` → `HTTPException(400)` `:284-297`), `python_multipart/multipart.py`(`parse_options_header` `:221-254`), `fastapi/routing.py`(폼 파싱 `:460-505`, `form_limits` `:953-966`), `fastapi/_form_limits.py`, `filetype/types/audio.py`(`Mp3.match` `:42-52`, `M4a.match` `:68-`, `Wav.match` `:138-`), `filetype/utils.py`(`_NUM_SIGNATURE_BYTES = 8192`)
- Python — `tempfile.SpooledTemporaryFile`: https://docs.python.org/3/library/tempfile.html#tempfile.SpooledTemporaryFile
- Python — `unicodedata.normalize`: https://docs.python.org/3/library/unicodedata.html#unicodedata.normalize
- RFC 7578 (multipart/form-data, `filename*` 비사용 §4.2): https://datatracker.ietf.org/doc/html/rfc7578
- WHATWG HTML — multipart/form-data 인코딩(파일명 `"`·CR·LF 퍼센트 인코딩): https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#multipart-form-data
- WAV(RIFF) 형식: Microsoft "Multimedia Programming Interface and Data Specifications 1.0"(RIFF/WAVE) — 일반 참고
- MP3 프레임 헤더(동기 11비트, 버전·레이어 비트): ISO/IEC 11172-3·13818-3 — 일반 참고 **[확인 필요: 원문 미열람]**
- Microsoft — Windows 파일 이름 규칙(금지 문자·끝 점/공백·예약 이름): https://learn.microsoft.com/windows/win32/fileio/naming-a-file
- Google Drive API — 파일 업로드: https://developers.google.com/workspace/drive/api/guides/manage-uploads (이름 길이 상한은 공식 문서에서 찾지 못함)
- 선행 문서: `researchs/drive-inbox.md`, `plans/drive-inbox.md` §1.4·§3·§9.4, `researchs/common-module.md` §3.3, `plans/common-module.md` §5.4
