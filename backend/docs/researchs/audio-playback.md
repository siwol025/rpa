# 음성 재생 리서치 — `GET /api/calls/{id}/audio`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-06 음성 재생 (P0, Phase 2, 선행 R-03). 요구: PRD WEB-03(상담 상세에서 원본 음성 재생). 관련 기능: R-03 음성 사본 저장소(사용), R-10 로봇용 음성 다운로드(같은 저장소, 같은 조회 로직), W-02 상세, W-04 소프트 삭제, O-05 정리 배치, X-02 GCS 저장소 |
| 근거 | `docs/prd.md` §5.6(WEB-03)·§6·§7, `features.md` W-06·R-03·R-10·O-05·§3(A↔B 합의), `architecture.md` §1·§6.3·§7·§8.1·§10.1·§11·§12, `research.md` §5·§7, `api/convention.md` §1·§2.2·§3.4·§6·§7, `plans/common-module.md` §5.4, `researchs/common-module.md` §3, `backend/app/**`, `backend/tests/**`, 원격 브랜치 `origin/front`(프론트 초안, 미병합, `f731fc8`) |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / anyio 4.16.0 / Uvicorn 0.54.0 / httpx 0.28.1 (`uv.lock` 고정본. 스크래치 가상환경에 `uv sync --frozen`으로 설치해 확인) |
| 검증 방법 | 문서·코드 정독, 설치 라이브러리 소스 확인, 스크래치 폴더에서 `create_app(Settings(_env_file=None, …))`에 임시 라우트를 붙여 `TestClient`로 실측했다(레포 코드는 수정하지 않음). RFC 9110·6266·8187 조항은 원문 기준으로 정리했다 |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다. **[확인 필요]**는 다른 파트와 합의해야 하는 항목, **[가정]**은 근거 없이 정한 값이다.

---

## 0. 요약 (핵심 발견)

1. **[핵심] R-03 `AudioStorage`가 W-06에 필요한 것을 거의 다 제공한다.** `open(key, byte_range)`는 `(start, end|None)` 구간만 읽히는 스트림을 주고(끝은 파일 크기로 자름), `size(key)`는 `Content-Range`·`Content-Length` 계산에 쓴다. 없는 파일은 `AudioNotFoundError`, 시작 위치가 범위 밖이면 `InvalidRangeError`, 형식이 틀린 키는 파일 접근 전에 `InvalidKeyError`(경로 탈출 차단)를 던진다. 다만 **HTTP `Range` 헤더 파싱은 없다.** `bytes=-500`(끝에서 500바이트) 같은 suffix 범위는 호출자가 `size()`로 시작 위치를 계산해 넘겨야 한다.
2. **[핵심] Starlette 1.10 `FileResponse`는 Range를 지원하지만 그대로 쓰기 어렵다.** 파일 **경로**를 받으므로 `AudioStorage` 추상화를 우회해야 하고(`LocalStorage`는 경로를 공개하지 않음, GCS로 바꾸면 못 씀), 잘못된 Range에 **`400 text/plain`**(RFC 9110은 무시하고 200 권장), 범위 밖은 **`416 text/plain` 빈 본문**을 돌려 §7.2 에러 형식과 다르다(§4.2 실측). `StreamingResponse` + 자체 Range 파서 + `AudioStorage.open()` 조합이 현재 구조에 맞는다.
3. **[핵심] 기본 `get_db` 의존성을 그대로 쓰면 음성 전송이 끝날 때까지 DB 연결을 붙잡는다.** FastAPI 0.165의 yield 의존성 기본 scope는 `"request"`라 **응답 전송이 끝난 뒤** 정리 코드가 돈다(실측: `db_open → endpoint → chunk0..2 → db_close`). 브라우저는 재생 속도에 맞춰 천천히 받으므로 스트림 하나가 수 분 동안 풀 연결(기본 5 + overflow 10, 워커마다)을 점유한다. `Depends(get_db, scope="function")`로 바꾸면 엔드포인트 함수가 끝날 때 세션이 닫히고 그다음 스트리밍이 시작된다(실측: `open → close → chunk`). 테스트의 `dependency_overrides[get_db]`도 그대로 동작한다.
4. **모든 미삭제 `call_record`에는 음성 사본 키가 있다.** `object_key`는 `NOT NULL`이고, 로봇 등록(R-04)은 사본 저장 → INSERT 순서이며 INSERT 실패 시 사본을 지운다. 따라서 상태(`REGISTERED`~`FAILED`·`RETRY_REQUESTED`)와 무관하게 재생할 수 있다. 소프트 삭제 건(`deleted_at IS NOT NULL`)은 404. 사본이 없어지는 경우는 O-05 정리 배치(보존 기간 경과, 기간 미정 E-07) 또는 운영 사고뿐이다.
5. **프론트 초안은 평범한 `<audio>` 요소다.** `origin/front` `CallDetailPage.tsx:378` `<audio controls preload="none" src="/api/calls/{id}/audio">`. `fetch`·`crossorigin` 속성·커스텀 헤더를 쓰지 않으므로 응답 본문(에러 JSON)을 읽을 수 없고, 상태와 무관하게 플레이어를 항상 그린다. 개발 환경은 Vite 프록시(`/api` → `localhost:8000`)로 같은 출처다. 목(mock)은 Range 없이 `200 audio/wav`를 돌려준다.
6. **접근 로그는 이미 절반은 있다.** `RequestIdMiddleware`가 요청마다 `app.access` 로그(`request_id`·`method`·`path`·`status`·`latency_ms`·`call_id`)를 남기고, 라우트가 `bind_call_id()`를 부르면 `call_id`가 채워진다. W-06이 더할 것은 "누가(IP?)·어느 구간을" 정도다. 단 `convention.md` §6은 **헤더 값을 로그에 남기지 않는다**고 정하므로 `Range` 원문이 아니라 파싱한 숫자(`range_start`·`range_end`)를 남겨야 한다. 클라이언트 IP 기록 여부는 결정이 필요하다(로그인이 없어 "누가"를 나타낼 수단이 IP뿐, Nginx 없이 Uvicorn 직접 노출이라 `scope["client"]`가 실제 IP).
7. **`plans/common-module.md` §5.4의 chunked 제약이 W-06에 실제로 해당한다.** Uvicorn 0.54는 ASGI `spec_version` `"2.3"`을, `TestClient`는 값을 주지 않아(`"2.0"`) 둘 다 `StreamingResponse`가 `listen_for_disconnect`로 요청 본문을 소비한다. GET에 chunked 본문을 한도 이상 붙이면 206 헤더가 나간 뒤 연결이 끊기고 접근 로그 `status`는 500이 된다(실측). 정상 브라우저는 GET에 본문을 보내지 않으므로 영향은 비정상 요청뿐이다.
8. **브라우저 Range 패턴.** Chrome·Firefox는 재생 시작 시 `Range: bytes=0-`, 탐색(seek) 시 `bytes=N-`를 새 요청으로 보낸다. 206을 받지 못하면 탐색이 안 되거나 처음부터 다시 받는다. Safari(WebKit)는 먼저 `bytes=0-1`로 확인한 뒤 구간을 요청하며 206·정확한 `Content-Range`가 없으면 재생을 거부한다. 따라서 **단일 범위 206 + `Accept-Ranges: bytes` + 정확한 `Content-Length`**가 핵심이고, 다중 범위·`If-Range`는 미디어 재생에서 쓰이지 않는다.
9. **문서끼리 어긋난 곳.** `architecture.md` §8.1의 `AudioStorage` 시그니처(`put`·`signed_url`)는 구현(`save`·`size`·`check`, `signed_url` 없음)과 다르다. `convention.md` §2.2의 W-06 행은 에러로 404만 적혀 있고 416이 없다. `ErrorCode`에 416용 코드가 없다.

---

## 1. 현재 상태

### 1.1 코드 (브랜치 `cyj` 기준 `2bde1c6`)

| 위치 | 내용 | W-06과의 관계 |
|---|---|---|
| `app/infra/storage/base.py` | `AudioStorage` Protocol(`save`·`open`·`size`·`delete`·`check`), `ByteRange = tuple[int, int \| None]`(끝 포함), 예외 `StorageError` ← `InvalidKeyError`·`AudioNotFoundError`·`InvalidRangeError` | 그대로 사용 |
| `app/infra/storage/local.py` | `LocalStorage(root)`. 키 형식 `^<uuid4>\.(wav\|mp3)$`만 허용(`_path()`에서 검사 → 경로 탈출 불가). `open(key, None)`은 원본 파일 객체, `open(key, (s, e))`는 `fstat` 크기로 검사 후 `seek(s)` + `_LimitedReader`(RawIOBase, 남은 길이만큼만 읽힘, `close()`가 원본도 닫음). `size()`는 `stat().st_size`. **`OSError`(권한·디스크 오류)는 감싸지 않고 그대로 올라간다**(`FileNotFoundError`만 `AudioNotFoundError`로 바꿈) | Range 읽기 제공. 헤더 파싱·suffix 계산은 호출자 몫 |
| `app/infra/storage/__init__.py` | `create_audio_storage(settings)` → `app.state.audio_storage` (`main.py`) | 이미 앱 시작 시 생성됨 |
| `app/api/deps.py` | `get_audio_storage(request)` 이미 있음(R-04가 사용). `get_db`는 yield 의존성, `DbSession = Annotated[Session, Depends(get_db)]`(scope 지정 없음 = request) | 재사용. 세션 scope는 §5 |
| `app/services/robot_service.py` | 매직 바이트로 판별 → 확장자 `.wav`/`.mp3` → `storage.save()` → 반환 키를 **`call_record.object_key`**에 저장. 실패 시 `storage.delete(key)` | 키 = `object_key`, 확장자 = 키의 끝 |
| `app/services/upload_service.py:22` | `CANONICAL_MIME = {"wav": "audio/wav", "mp3": "audio/mpeg"}` | `Content-Type` 결정에 재사용 가능(§6.3) |
| `app/models/call_record.py` | `object_key TEXT NOT NULL`, `original_name TEXT NOT NULL`, `file_size BIGINT NULL`, `duration_sec INT NULL`, `status`, `deleted_at TIMESTAMPTZ NULL` | 조회 컬럼: `object_key`(필수), `original_name`(파일명 헤더를 쓸 경우) |
| `app/repositories/call_repository.py` | `get_call(id)`: `deleted_at IS NULL` + transcript·analysis `joinedload` | 재사용 가능하나 과함. 키만 읽는 메서드가 낫다(§11 D16) |
| `app/api/web/calls.py` | `router = APIRouter(prefix="/api/calls", tags=["calls"])`, `call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)]`, `bind_call_id(request, call_id)`, `responses=error_responses(ErrorCode.NOT_FOUND)` | 같은 라우터에 추가. 같은 패턴 |
| `app/core/errors.py` | `AppError`·`ErrorCode`·`error_response()`. 416·503(음성) 코드 없음. `_STATUS_TO_CODE`에 416 없음 | 416을 §7.2 형식으로 내려면 코드 추가 필요(§11 D4) |
| `app/core/middleware.py` | 순수 ASGI `RequestIdMiddleware`(헤더 부여 + `app.access` 로그), `UnhandledErrorMiddleware`(응답 시작 전 예외만 500 JSON, 시작 후는 다시 던짐), `BodySizeLimitMiddleware` | 스트리밍을 버퍼링하지 않음(§8) |
| `app/core/logging.py` | structlog JSON, `bind_call_id(request, call_id)` → `request.state.call_id` + contextvars | 접근 로그 `call_id` |
| `app/main.py` | 라우터 등록, 미들웨어 순서(바깥 → 안) RequestId → CORS → UnhandledError → RobotAuth → BodySizeLimit. CORS `expose_headers=[X-Request-Id]`만 | §8 |

R-10(`GET /api/robot/calls/{id}/audio`)은 아직 없다(`app/api/robot/calls.py`에 audio 라우트 없음).

### 1.2 테스트 구조

| 위치 | 패턴 |
|---|---|
| `tests/unit/conftest.py` | `_build_test_app(**overrides)` = `create_app(Settings(_env_file=None, …))` + 테스트 라우트 |
| `tests/unit/test_calls_api.py` | `app.dependency_overrides[get_call_service] = lambda: FakeCallService()` — DB 없이 라우터 검증 |
| `tests/unit/test_audio_storage_local.py` | `LocalStorage(tmp_path / "audio")`, `DATA = bytes(range(256)) * 40`(위치마다 값이 달라 구간 검증 쉬움) |
| `tests/unit/test_logging.py` | `capsys`로 stdout JSON 줄을 읽어 `logger == "app.access"` 줄 검사 |
| `tests/integration/conftest.py` | `TEST_DATABASE_URL` 또는 testcontainers. `db_session`(바깥 트랜잭션 롤백), `api` = `create_app(Settings(_env_file=None))` + `dependency_overrides[get_db] = lambda: db_session` |
| `tests/integration/factories.py` | `make_call(session, **overrides)` — **기본 `object_key`가 `"audio/{n}.wav"`라 `LocalStorage` 키 형식이 아니다**(`InvalidKeyError`). W-06 테스트는 `storage.save()`로 만든 실제 키를 넘겨야 한다 |
| `tests/conftest.py`(루트) | `db`·`audio_root(tmp_path/"audio")`·`robot_app`·`robot_client`(로봇 API용, 임시 음성 저장소) |
| `tests/unit/test_openapi.py` | 커밋된 `docs/api/openapi.json`과 코드 일치·operationId 고유성 검사 → 라우트 추가 시 재생성 필요 |

`api` 픽스처는 `audio_storage_root` 기본값(`./data/audio`)을 쓰므로 W-06 통합 테스트는 `tmp_path`를 가리키는 별도 픽스처가 필요하다.

---

## 2. 요구사항 정리

### 2.1 원문

| 출처 | 내용 |
|---|---|
| `features.md` W-06 | `GET /api/calls/{id}/audio` — HTTP Range 스트리밍 (R-03 사용), 접근 로그 기록. P0, Phase 2 |
| `features.md` §3 | W-06은 R-03의 `AudioStorage.open(key, byte_range)` 인터페이스를 쓴다 |
| PRD WEB-03 | 상담 상세: 요약, 조치 이력, 화자 분리 전사 원문, **원본 음성 재생** (P0) |
| PRD §7 | 원본 음성 접근 범위 제한. 로그인이 없으므로 사내망/IP 제한 등 네트워크 수준 통제 |
| `architecture.md` §1-6 | 서버는 원본과 독립된 음성 사본을 보관해 재생·재처리에 사용 |
| `architecture.md` §8.1 | `LocalStorage`: API가 Range 응답으로 직접 스트리밍. `GCSStorage`(Phase 3): 서명 URL 302 |
| `architecture.md` §11 | 음성 재생·다운로드 **접근 로그 기록** |
| `research.md` §5·§7 | HTTP Range 지원(재생 위치 이동). 원본 음성은 PII 포함 → 접근 로그·보존 기간 |
| `convention.md` §2.2 | 성공 200 / 206(Range) / 302(GCS 서명 URL), 에러 404 |
| `convention.md` §6 | 응답에 `object_key`를 넣지 않는다. 로그에 본문·쿼리·**헤더 값**을 남기지 않는다 |

### 2.2 해석

- **인증 없음.** `/api/calls/*`는 웹용이라 인증이 없고 VM 방화벽이 통제한다(`architecture.md` §7.1). W-06도 같다.
- **302는 Phase 3(X-02) 이후.** 지금은 `LocalStorage`뿐이라 200/206만 구현 대상이다.
- **접근 로그의 목적은 감사(누가 어떤 녹취를 들었나).** 개인정보를 담은 원본 음성이라서다. 로그 자체에 PII(파일명·담당자·고객사)를 넣으면 안 된다.

---

## 3. 프론트 초안의 가정 (`origin/front`, 미병합)

| 파일 | 내용 |
|---|---|
| `frontend/src/api/calls.ts:10` | `audioUrl = (id) => apiUrl('/calls/${id}/audio')` → `${VITE_API_BASE_URL ?? '/api'}/calls/{id}/audio` |
| `frontend/src/pages/CallDetailPage.tsx:378` | `<audio aria-label="원본 음성 재생" controls preload="none" src={audioUrl(c.id)} />` — 상세가 로드되면 상태와 무관하게 표시 |
| `frontend/vite.config.ts:9` | 개발 서버 `/api` → `http://localhost:8000` 프록시(같은 출처) |
| `frontend/src/mocks/handlers.ts:196` | 목: 있으면 `200` + `Content-Type: audio/wav`(무음 WAV), 없으면 404. Range 미처리 |
| `features_frontend.md:62` | F-V04 원본 음성 재생 ↔ W-06 |

의미:

- `preload="none"`이라 상세 화면을 여는 것만으로는 요청이 나가지 않는다. 사용자가 재생을 누르면 첫 요청이 간다 → 접근 로그가 "실제로 들으려 한 경우"에 가깝게 남는다.
- `<audio>`는 응답 본문을 스크립트에 노출하지 않는다. 404·416·500의 JSON 본문은 프론트가 읽지 못하고 `error` 이벤트(`MEDIA_ERR_SRC_NOT_SUPPORTED` 등)만 받는다. "음성 없음"을 문구로 보여 주려면 별도 정보가 필요하다(§12).
- `crossorigin` 속성이 없으므로 다른 출처에서 서비스하더라도 no-cors 요청이라 CORS 헤더 없이 재생된다. `fetch`/Web Audio로 바꾸면 `Content-Range`(CORS 안전 목록 밖)를 `Access-Control-Expose-Headers`에 넣어야 한다.

---

## 4. HTTP Range 스펙 (RFC 9110)과 구현 수단

### 4.1 규칙 요약

| 항목 | 규칙 (RFC 9110) | W-06 적용 |
|---|---|---|
| 형식 §14.1.2 | `Range: bytes=<first>-<last>`(끝 포함), `bytes=<first>-`(끝까지), `bytes=-<n>`(마지막 n바이트). 단위 이름은 대소문자 무시. 쉼표로 여러 범위 | 세 형태 모두 지원 |
| 끝 보정 §14.1.2 | `last`가 없거나 `size` 이상이면 `size-1`로 본다. suffix `n`이 `size`보다 크면 전체 | `AudioStorage.open`이 끝을 자르므로 suffix만 호출자가 계산 |
| 잘못된 범위 §14.1.1·§14.2 | `first > last` 같은 문법 오류는 범위 지정 전체가 무효. 서버는 무효 Range를 **무시하거나 거절할 수 있다(MAY)**. 모르는 단위는 **반드시 무시(MUST)** | 무시하고 200 전체(권장, §11 D5) |
| 만족 불가 §14.1.1·§15.5.17 | 모든 범위가 만족 불가(시작 ≥ 크기, suffix 길이 0)면 **416**, `Content-Range: bytes */<size>`를 보내야 한다(SHOULD) | 416 |
| 206 §15.3.7·§14.4 | 단일 범위: `Content-Range: bytes <a>-<b>/<size>`, `Content-Length: b-a+1`. 200이었다면 보냈을 `Cache-Control`·`ETag` 등도 같이 보낸다 | 206 |
| 다중 범위 §14.6 | `multipart/byteranges`로 응답하거나 Range를 무시할 수 있다. 겹치거나 작은 범위가 많으면 거절 가능 | 무시하고 200(권장, §11 D6). 미디어 플레이어는 다중 범위를 보내지 않음 |
| 메서드 §14.2 | Range는 GET에만 정의. 다른 메서드면 무시 | GET만 있음 |
| `Accept-Ranges` §14.3 | 범위 요청을 지원함을 알림(`bytes`) | 200·206 모두 붙임 |
| `If-Range` §13.1.5 | Range와 함께 올 때만 의미. 검증자(ETag/날짜)가 현재 표현과 **강한 비교로** 일치할 때만 Range를 적용, 아니면 Range를 무시하고 200 전체. Range 없이 오면 무시 | 검증자를 발급하지 않으면 클라이언트가 보낼 일이 없다. 와도 Range 무시가 안전(§11 D7) |
| 인코딩 | Range는 표현(전송 인코딩 전) 기준. 압축(`Content-Encoding`)하면 구간 의미가 바뀐다 | 앱에 GZip 미들웨어 없음 → 문제 없음. Chrome은 미디어 요청에 `Accept-Encoding: identity`를 보냄 |

경계 사례(크기 `S`):

| 요청 | 결과 |
|---|---|
| `bytes=0-` | 206, `0-(S-1)/S` |
| `bytes=0-0` | 206, 1바이트 |
| `bytes=100-` (`100 < S`) | 206, `100-(S-1)/S` |
| `bytes=0-99999999` | 206, `0-(S-1)/S` (끝 보정) |
| `bytes=-10` | 206, `(S-10)-(S-1)/S` |
| `bytes=-99999999` | 206, 전체(`0-(S-1)/S`) |
| `bytes=S-`, `bytes=-0` | 416, `Content-Range: bytes */S` |
| `bytes=5-2`, `bytes=abc`, `bytes=`, `bytes=1-2-3` | 무효 → 무시하고 200 (권장안) |
| `items=0-1` | 모르는 단위 → 무시하고 200 (MUST) |
| `bytes=0-1,5-6` | 다중 → 무시하고 200 (권장안) |
| 아주 긴 숫자(5,000자리) | Python 3.12 `int()`가 `ValueError`(자릿수 한도 4,300) → 무효로 처리. 헤더 길이 상한을 두는 것도 방법 |
| `S = 0` | 모든 범위 만족 불가 → 416(또는 Range 무시 200). 등록 시 빈 파일은 매직 바이트 판별에서 415로 막히므로 실제로는 생기지 않는다 |

### 4.2 Starlette 1.10 `FileResponse` 실측

`FileResponse`는 Range를 자체 처리한다(`responses.py` `FileResponse.__call__`·`_parse_range_header`). 1 KiB 파일로 실측:

| 요청 `Range` | 결과 |
|---|---|
| `bytes=0-` | 206 `bytes 0-1023/1024` |
| `bytes=-10` | 206 `bytes 1014-1023/1024` |
| `bytes=0-99999` | 206 `bytes 0-1023/1024` |
| `bytes=1024-`, `bytes=-0` | 416 `text/plain` 빈 본문, `Content-Range: bytes */1024` |
| `bytes=5-2` | **400 `text/plain`** "Range header: start must be less than end" |
| `bytes=abc`, `items=0-1` | **400 `text/plain`** |
| `bytes=0-1,5-6` | 206 `multipart/byteranges` |
| `If-Range` 불일치 | 200 |
| (Range 없음) | 200, `ETag`(mtime+size MD5)·`Last-Modified`·`Accept-Ranges` 자동 |
| 한글 `filename` | `content-disposition: inline; filename*=utf-8''%EC%83%81%EB%8B%B4.wav` (ASCII 대체 `filename=` 없음) |

평가:

| 관점 | `FileResponse` | `StreamingResponse` + 자체 파서 + `AudioStorage.open` |
|---|---|---|
| 저장소 추상화 | 경로 필요 → `LocalStorage`에 경로 공개 메서드 추가 또는 `_path` 접근. GCS(X-02)에서 못 씀 | Protocol만 사용 |
| 에러 형식 | 400·416이 `text/plain`. 예외가 아니라 응답을 직접 보내므로 §7.2 핸들러를 거치지 않음 | §7.2 JSON(`AppError`)로 통일 가능 |
| RFC 적합성 | 무효 Range에 400(RFC는 무시 권장, 거절도 허용되지만 416이 아니라 400) | 원하는 대로 |
| 기능 | 다중 범위·If-Range·ETag·`pathsend` 자동 | 단일 범위만 직접 구현(약 30줄) |
| 테스트 | Starlette에 위임 | 파서는 순수 함수라 표 기반 단위 테스트가 쉬움 |

→ **권장: `StreamingResponse` + 자체 파서**(§11 D1).

### 4.3 `StreamingResponse` 동작 (Starlette 1.10 소스·실측)

- 동기 이터러블을 주면 `iterate_in_threadpool`로 감싸 **청크마다** `anyio.to_thread.run_sync(next, …)`로 읽는다. 스레드는 청크 하나 읽는 동안만 빌리므로, 느린 클라이언트가 스레드를 오래 점유하지 않는다(anyio 기본 한도 40은 동기 엔드포인트와 공유).
- 헤더에 `Content-Length`를 주면 그대로 나가고 Uvicorn은 chunked 대신 고정 길이로 보낸다. **실제로 보내는 바이트 수와 반드시 같아야 한다**(다르면 Uvicorn이 연결을 끊는다).
- ASGI `spec_version < 2.4`(Uvicorn 0.54 = `"2.3"`, `TestClient` = 미지정 `"2.0"`)이면 전송과 `listen_for_disconnect`를 같은 task group에서 돌리고, 클라이언트가 끊으면 전송 task를 취소한다. 이때 동기 제너레이터는 명시적으로 닫히지 않고 참조가 사라질 때 닫힌다(CPython 참조 카운트로 즉시). 파일 핸들 누수를 막으려면 제너레이터 안에서 `with stream:`로 열어 두는 형태가 안전하다.
- 실측(실제 `create_app` 미들웨어 스택 + 임시 라우트, 100 KiB 파일, `open(key, (100, None))`): 206, `Content-Range: bytes 100-102399/102400`, 본문 일치, `X-Request-Id` 있음, CORS `Access-Control-Allow-Origin` 붙음, `app.access` 로그 `status=206`·`call_id` 기록.
- FastAPI는 GET 라우트에 HEAD를 자동으로 붙이지 않는다(실측 405). 브라우저 미디어 요청은 HEAD를 쓰지 않는다.

---

## 5. DB 세션 수명과 스트리밍

FastAPI 0.165 `routing.py`: `request_stack`(scope `"request"`) 안에서 `function_stack`(scope `"function"`)을 열고, 엔드포인트 함수가 끝나면 `function_stack`을 닫은 뒤 `await response(...)`로 **응답을 보내고 나서** `request_stack`을 닫는다.

실측(동기 엔드포인트 + `StreamingResponse`):

| 의존성 선언 | 순서 |
|---|---|
| `Depends(get_db)` (기본, request) | `db_open → endpoint → chunk0 → chunk1 → chunk2 → db_close` |
| 서비스 의존성 안에서 `Depends(get_db, scope="function")` | `open → close → chunk` |
| 위 + `dependency_overrides[get_db] = lambda: "fake"` | 정상(테스트 오버라이드 유지) |

영향: `get_db`는 `with session_factory() as session: yield session`이고, 첫 SELECT에서 autobegin된 트랜잭션이 연결을 잡는다. request scope면 그 연결이 **음성 전송이 끝날 때까지** 풀로 돌아가지 않는다. 엔진은 `create_engine(url, pool_pre_ping=True)` 기본값(QueuePool 5 + overflow 10, `pool_timeout` 30초)이고 Uvicorn 워커는 2~4개(`architecture.md` §10.1). 동시 재생이 워커당 15개를 넘으면 다른 API 요청이 30초 대기 후 실패한다. 브라우저는 버퍼가 차면 수신을 늦추므로(TCP 배압) 긴 통화일수록 오래 잡는다.

대안:

| 안 | 내용 | 비고 |
|---|---|---|
| A (권장) | 음성용 서비스 의존성이 `Annotated[Session, Depends(get_db, scope="function")]`를 받는다 | 엔드포인트 반환 시 세션 닫힘. FastAPI 공식 기능 |
| B | 서비스가 조회 후 `session.close()`(또는 `rollback()`) 호출 | 서비스가 세션 수명을 알게 됨 |
| C | 그대로 둠 | 풀 고갈 위험 |

참고: 실측에서 scope를 지정하지 않은(yield 없는) 서비스 의존성이 `Depends(get_db, scope="function")`에 의존하는 구성(`/a`)과 서비스 의존성 자체에 `scope="function"`을 준 구성(`/b`) 모두 정상 동작했다. 같은 라우트의 다른 의존성이 기본 `DbSession`(request scope)을 함께 쓰면 그 세션은 다시 전송 끝까지 열려 있으므로, 음성 라우트에서는 `DbSession`을 쓰지 않아야 한다.

---

## 6. 요청/응답 계약 (초안)

### 6.1 요청

```
GET /api/calls/{id}/audio
Range: bytes=0-            (선택)
If-Range: ...              (선택, §11 D7)
```

- `id`: `Path(ge=1, le=BIGINT_MAX)`(기존 `get_call`과 동일). 범위 밖·정수 아님 → 422 `VALIDATION_ERROR`.
- 쿼리·본문 없음.

### 6.2 응답 헤더

| 헤더 | 200 | 206 | 비고 |
|---|---|---|---|
| `Content-Type` | `audio/wav` / `audio/mpeg` | 같음 | 키 확장자 → 정규 MIME(§6.3) |
| `Content-Length` | 파일 크기 | 구간 길이 | 정확해야 함 |
| `Content-Range` | — | `bytes a-b/S` | |
| `Accept-Ranges` | `bytes` | `bytes` | |
| `Cache-Control` | (결정) | 같음 | §11 D8. 권장 `private, no-store` |
| `Content-Disposition` | (결정) | 같음 | §6.4, §11 D9 |
| `X-Content-Type-Options` | `nosniff` (선택) | 같음 | 키 확장자로 정한 형식을 브라우저가 추측하지 않게 |
| `X-Request-Id` | 미들웨어 | 미들웨어 | |
| `ETag`·`Last-Modified` | (결정) | | §11 D7. 권장: 보내지 않음 |

### 6.3 Content-Type

- 저장 확장자는 R-04가 **매직 바이트**로 정한 것이다(`robot_service._EXTENSION_BY_MIME`: `filetype`의 `audio/x-wav` → `.wav`, `audio/mpeg` → `.mp3`). 따라서 `object_key`의 확장자가 실제 형식이다. `original_name`의 확장자는 믿지 않는다.
- 정규 MIME은 이미 `upload_service.CANONICAL_MIME`(`wav → audio/wav`, `mp3 → audio/mpeg`)이 있다. `audio/wav`는 Chrome·Firefox·Safari 모두 재생한다(`audio/x-wav`·`audio/wave`도 인식). 공용 위치(예: `app/core/` 또는 `app/infra/storage/`)로 옮겨 W-07·W-06·R-10이 같이 쓰는 안을 계획에서 정한다.
- 확장자가 표에 없으면(현재 키 정규식상 불가능) 500으로 보는 게 맞다.

### 6.4 Content-Disposition (RFC 6266 / RFC 8187)

- `<audio>` 재생에는 필요 없다. Chrome 플레이어의 "다운로드" 메뉴·주소창 직접 열기에서 저장 파일명이 된다. 없으면 URL 끝(`audio`)이 이름이 된다.
- `inline`이어야 브라우저가 직접 열 때 내려받지 않고 재생한다.
- 비ASCII 이름은 `filename*=UTF-8''<퍼센트 인코딩>`(RFC 8187, 구 5987). 구형 클라이언트용 ASCII `filename="..."`을 함께 두고 `filename*`을 뒤에 둔다(RFC 6266 §4.3 권고). ASCII 대체에는 `"`·`\`·제어 문자(CR/LF 포함)를 넣지 않는다 → 헤더 주입 방지.
- `original_name`에는 담당자·고객사 이름이 들어 있을 수 있다(파일명 규칙 `{yyyyMMdd_HHmmss}_{담당자}_{고객사}`, `input_flow.md` §7). 응답 헤더에는 둘 수 있지만(상세 API가 이미 같은 값을 보여 줌) **로그에는 넣지 않는다**.
- `original_name`의 확장자와 실제 형식이 다를 수 있으므로 이름을 쓸 경우 확장자를 키 기준으로 맞추는 편이 낫다.

예:
```
Content-Disposition: inline; filename="call-123.wav"; filename*=UTF-8''20261123_143005_%EA%B9%80%EC%83%81%EB%8B%B4_ABC.wav
```

### 6.5 상태 코드

| 상황 | 상태 | 본문 |
|---|---|---|
| Range 없음 / 무효·다중·모르는 단위 Range / `If-Range` 무시 | 200 | 전체 |
| 단일 유효 범위 | 206 | 구간 |
| 모든 범위 만족 불가 | 416 + `Content-Range: bytes */S` | §11 D4 |
| `id` 형식 오류 | 422 `VALIDATION_ERROR` | 기존 |
| 없는 건 / 소프트 삭제 건 | 404 `NOT_FOUND` | 기존 |
| 레코드는 있으나 사본 파일 없음(`AudioNotFoundError`) | 404 `NOT_FOUND` (권장, §11 D10) | |
| `object_key`가 키 형식 아님(`InvalidKeyError`) | 500 `INTERNAL_ERROR` (권장, §11 D11) | 데이터 손상 |
| 저장소 I/O 오류(`OSError`, `StorageError`) — 응답 시작 전 | 500 (권장) 또는 503 신규 코드(§11 D12) | |
| 스트리밍 중 오류 | 연결 중단 (형식 응답 불가) | 로그만 |
| GET 외 메서드 | 405 `METHOD_NOT_ALLOWED` | 기존 |

`convention.md` §2.2 W-06 행의 에러 열에 416(및 결정 시 503)을 추가해야 한다.

---

## 7. 처리 흐름 (스케치)

```python
# 설명용 스케치 — 이름·위치는 계획에서 정한다
@router.get("/{call_id}/audio", response_class=StreamingResponse, responses=...)
def get_call_audio(call_id: CallId, request: Request, service: AudioServiceDep) -> StreamingResponse:
    bind_call_id(request, call_id)
    audio = service.open_audio(call_id, request.headers.get("range"), request.headers.get("if-range"))
    # ↑ 1) repo: deleted_at IS NULL 인 object_key 조회 → 없으면 AppError(NOT_FOUND)
    #   2) size = storage.size(key)            (AudioNotFoundError → NOT_FOUND)
    #   3) byte_range = parse_range(header, size)  → None(전체) | (start, end) | 만족 불가 예외
    #   4) stream = storage.open(key, byte_range)  (AudioNotFoundError → NOT_FOUND)
    #   5) 접근 로그 1줄
    # 세션은 여기서(함수 종료 시) 닫힌다 — scope="function"
    return StreamingResponse(_iter(audio.stream), status_code=audio.status, media_type=..., headers=...)

def _iter(stream: BinaryIO, chunk: int = 64 * 1024) -> Iterator[bytes]:
    with stream:
        while data := stream.read(chunk):
            yield data
```

```python
def parse_range(header: str | None, size: int) -> ByteRange | None:
    """None = Range 무시(200). 만족 불가면 예외(416)."""
    if header is None: return None
    unit, sep, spec = header.partition("=")
    if not sep or unit.strip().lower() != "bytes" or "," in spec: return None
    first, dash, last = spec.strip().partition("-")
    if not dash: return None
    try:
        if first == "":                       # suffix: bytes=-n
            n = int(last)                     # 숫자만 허용(공백·부호 검사 필요)
            if n == 0: raise Unsatisfiable(size)
            return (max(size - n, 0), None)
        start = int(first)
        end = int(last) if last else None
    except ValueError:
        return None
    if end is not None and end < start: return None
    if start >= size: raise Unsatisfiable(size)
    return (start, end)
```

주의:
- `int()`는 `" 5"`, `"+5"`, `"٥"`(아라비아 숫자)도 받는다. RFC의 `1*DIGIT`만 허용하려면 `str.isascii() and str.isdigit()` 검사를 먼저 한다(`BodySizeLimitMiddleware`의 `Content-Length` 검사와 같은 방식).
- `size()`와 `open()` 사이에 파일이 지워지면(O-05 배치) `open()`이 `AudioNotFoundError`를 던진다 → 404. 응답 헤더를 만들기 전에 `open()`까지 끝내야 404를 낼 수 있다.
- `Content-Length`/`Content-Range` 끝값은 `min(end, size-1)`로 계산해 `open()`의 보정과 맞춘다.
- `open(key, None)`(전체)은 일반 파일 객체를 돌려주므로 둘 다 `read(n)`으로 같은 방식으로 읽힌다(실측).

---

## 8. 미들웨어와의 상호작용

| 미들웨어 | 영향 | 확인 |
|---|---|---|
| `RequestIdMiddleware` | `http.response.start`에 `X-Request-Id`만 추가, 본문 메시지는 그대로 전달(버퍼링 없음). 요청 종료 시 `app.access` 1줄(`status` 206 기록) | 실측 |
| `CORSMiddleware` | `Origin`이 허용 목록이면 `Access-Control-Allow-Origin` 부여. `expose_headers`는 `X-Request-Id`뿐 | `<audio>`(no-cors)엔 무관. `fetch`로 쓰면 `Content-Range`·`Accept-Ranges` 노출 필요 |
| `UnhandledErrorMiddleware` | 응답 시작 전 예외 → 500 JSON + `app.error` 로그. 시작 후 예외 → 다시 던짐(연결 중단, Uvicorn 로그) | 스트리밍 중 디스크 오류는 형식 응답 불가 |
| `RobotAuthMiddleware` | `/api/robot` 경로만 검사 | 무관 |
| `BodySizeLimitMiddleware` | `Content-Length` 초과 GET → 본문을 읽기 전 413(정상). **chunked 본문 초과 GET** → `listen_for_disconnect`가 본문을 소비하다 `_BodyTooLargeError` → 206 헤더 전송 후 본문 0바이트로 끊김, 접근 로그 `status=500` | 실측. `plans/common-module.md` §5.4가 예고한 제약. 정상 브라우저는 해당 없음(§11 D14) |
| GZip | 없음 | Range와 충돌 없음 |

---

## 9. 접근 로그

### 9.1 이미 남는 것

`app.access` (요청마다 1줄):
```json
{"event": "request", "logger": "app.access", "method": "GET", "path": "/api/calls/7/audio",
 "status": 206, "latency_ms": 52.7, "call_id": 7, "request_id": "…", "timestamp": "…"}
```
`latency_ms`는 전송 완료까지 걸린 시간이다(스트리밍 포함).

### 9.2 W-06이 추가로 남길 후보

| 필드 | 값 | PII·규약 |
|---|---|---|
| `event` | `audio_access` | |
| `call_id`·`request_id` | contextvars로 자동 | |
| `range_start`·`range_end` | 파싱 결과(정수, 전체면 `null`) | `Range` **원문은 금지**(`convention.md` §6 헤더 값) |
| `status` | 200/206/416 | |
| `bytes` | 보낼 길이(`Content-Length`) | |
| `client_ip` | `scope["client"][0]` | 로그인 없는 환경에서 유일한 "누가". 개인 PC 식별 가능 → 결정 필요(§11 D3) |
| (금지) | `original_name`, `object_key`, 담당자·고객사, `User-Agent` 원문 | PII·내부 키·헤더 값 |

고려점:
- 재생 한 번에 요청이 여러 개(시작 `bytes=0-`, 탐색마다 1개, Safari는 `0-1` 확인 포함) → 감사 목적이면 전부 남겨도 양이 작다(요청당 1줄).
- 404·416도 남길지: 존재하지 않는 건 탐색 시도 추적에 쓸모가 있다. `app.access`에 이미 status가 남으므로 `audio_access`는 성공(200/206)만 남겨도 된다.
- 접근 로그 보존 기간은 Docker 로그 로테이션에 따른다(`architecture.md` §12). 감사 로그로 오래 보관해야 하면 DB 테이블(마이그레이션은 A 담당)이나 별도 파일이 필요하다 **[확인 필요]**.
- 로그 줄을 언제 찍을지: 응답을 만들기 직전(엔드포인트 안)이 간단하다. 실제로 끝까지 전송됐는지는 `app.access`의 `status`·`latency_ms`로 보완된다.

---

## 10. 보안

| 위협 | 통제 |
|---|---|
| 경로 탈출(`../`) | URL에는 `call_id`(정수)만 받는다. 파일 키는 DB `object_key`이고 `LocalStorage._path()`가 UUID 정규식으로 검사 후 접근 → `InvalidKeyError` |
| 내부 키 노출 | 응답 본문·헤더·에러 `detail`·로그에 `object_key`를 넣지 않는다(`convention.md` §6) |
| 삭제 건 재생 | `deleted_at IS NULL` 조건(기존 repository 규칙) |
| 헤더 주입 | `Content-Disposition` ASCII 대체에서 `"`·`\`·제어 문자 제거, 비ASCII는 퍼센트 인코딩 |
| 내용 추측(MIME sniffing) | `X-Content-Type-Options: nosniff`(선택) |
| 캐시 잔존 | PII 음성 → `Cache-Control: private, no-store` 권장(공유 PC·프록시 캐시 방지) |
| 대량 수집 | 인증 없음 → 방화벽 IP 허용 목록이 유일한 통제. 접근 로그로 사후 추적 |
| 큰 Range 숫자 DoS | 자릿수·헤더 길이 검사로 `ValueError`를 무효 처리 |

---

## 11. 결정 필요

| # | 항목 | 선택지 | 권장안 |
|---|---|---|---|
| D1 | **[핵심]** 구현 방식 | (a) `StreamingResponse` + 자체 단일 범위 파서 + `AudioStorage.open` (b) `FileResponse`(경로 공개 필요) | (a). 추상화 유지(X-02 대비), §7.2 에러 형식, RFC 권장 동작 |
| D2 | **[핵심]** DB 세션 수명 | (a) `Depends(get_db, scope="function")` (b) 서비스가 직접 close (c) 그대로 | (a) |
| D3 | **[핵심]** 접근 로그 형식 | (a) `app.access`만으로 충분 (b) 별도 `audio_access` 줄(call_id·range·status·bytes) (c) (b) + `client_ip` (d) DB 감사 테이블 | (c) 단, IP 기록은 팀 합의 필요. 합의 전이면 (b) |
| D4 | **[핵심]** 416 응답 본문 | (a) 신규 `ErrorCode.RANGE_NOT_SATISFIABLE`(416) + §7.2 JSON + `Content-Range` 헤더 (b) 빈 본문 (c) 기존 `BAD_REQUEST` 코드에 상태만 416 | (a). `AppError`에 헤더를 실을 수단이 없으므로 예외 핸들러 또는 라우터에서 `error_response(headers=…)` 사용 방식 결정 필요 |
| D5 | 무효 Range(문법 오류) | (a) 무시하고 200 (b) 416 (c) 400 | (a) RFC 권장, 브라우저 호환 |
| D6 | 다중 범위 | (a) 무시하고 200 (b) 첫 범위만 206 (c) multipart | (a). (b)는 RFC 위반(요청과 다른 구간) |
| D7 | `If-Range`/`ETag` | (a) 검증자 미발급, `If-Range`가 오면 Range 무시 (b) `ETag: "<file_hash>"`(내용 SHA-256, 사본은 불변) 발급 + 강한 비교 (c) 무시하고 항상 Range 적용 | (a). 사본은 불변이라 검증자 이득이 작다. (b)는 해시 노출 범위 검토 필요. (c)는 RFC MUST 위반 소지 |
| D8 | `Cache-Control` | (a) `private, no-store` (b) `private, no-cache` (c) 없음 | (a) PII |
| D9 | `Content-Disposition` | (a) 없음 (b) `inline; filename="call-{id}.{ext}"` (c) (b) + `filename*`에 `original_name`(확장자는 키 기준) | (c) 또는 (b). 프론트 다운로드 요구가 없으면 (b)로 충분 |
| D10 | 레코드는 있는데 사본 없음 | (a) 404 `NOT_FOUND` + 경고 로그 (b) 410 Gone/신규 코드 (c) 500 | (a). `<audio>`는 어차피 구분 못 함. O-05 정책 확정 후 재검토 |
| D11 | `InvalidKeyError`(DB 값 손상) | (a) 500(예외 전파, `app.error`) (b) 404 | (a) 숨기지 않음 |
| D12 | 저장소 I/O 장애 | (a) 500 그대로 (b) 신규 503 코드(`AUDIO_UNAVAILABLE`) | (a). 로컬 디스크 장애는 서버 오류. 503 코드는 GCS 도입(X-02) 때 검토 |
| D13 | MIME 매핑 위치 | (a) `upload_service.CANONICAL_MIME` import (b) 공용 모듈로 이동 | (b)가 의존 방향상 깔끔(서비스 간 import 회피). 변경 범위가 W-07 코드에 닿음 |
| D14 | chunked 본문 + 스트리밍 제약 | (a) 수용·문서화 (b) `BodySizeLimitMiddleware`가 응답 시작 후 초과 시 `http.disconnect` 반환 | (a). 비정상 요청만 해당. W-11 엑셀 다운로드 때 함께 (b) 검토 |
| D15 | Range 파서 위치 | (a) W-06 서비스 내부 (b) 공용 모듈(R-10도 사용) | (b) — R-10은 200만 요구하지만 같은 응답 생성 로직을 공유할 수 있다 |
| D16 | 키 조회 쿼리 | (a) `CallRepository.get_call` 재사용 (b) `object_key`(+`original_name`)만 읽는 새 메서드 | (b). transcript·analysis JOIN 불필요 |
| D17 | HEAD | (a) 미지원(405) (b) `methods=["GET","HEAD"]` | (a) |
| D18 | 청크 크기 | 64 KiB(`FileResponse`와 같음) | 64 KiB **[가정]** |

---

## 12. 다른 파트 확인 필요

### A (R-03·R-10·O-05 담당)

1. **R-10 공유.** `GET /api/robot/calls/{id}/audio`(R-10)는 같은 키 조회·저장소 열기를 쓴다. Range 파서·응답 생성 함수를 공용으로 둘지(§11 D15), 로봇 다운로드도 접근 로그 대상인지(`architecture.md` §11 "재생·다운로드 접근 로그").
2. **O-05 정리 배치의 사본 삭제 방식.** 보존 기간이 지난 **미삭제** 건의 사본만 지우고 레코드를 남기는지, 그때 `object_key`를 그대로 두는지(지금은 `NOT NULL`) 혹은 표시 컬럼을 추가하는지. W-06의 "사본 없음" 처리(§11 D10)와 프론트 문구가 여기에 달려 있다.
3. **`architecture.md` §8.1 갱신.** 문서 시그니처(`put`·`signed_url`)가 실제 Protocol(`save`·`open`·`size`·`delete`·`check`)과 다르다. GCS(X-02)의 302 서명 URL 방식은 Range·접근 로그를 저장소가 처리하게 되므로, 그때 접근 로그를 "서명 URL 발급 시점"으로 옮기는 것도 함께 정해야 한다.
4. **감사 로그 보관.** 접근 로그를 DB에 남길 경우(§11 D3 (d)) 테이블·마이그레이션은 A 담당(`features.md` §3).

### 프론트

1. **에러 표시.** `<audio>`는 404 등의 JSON을 읽지 못한다. "음성 사본 없음"을 문구로 보여 주려면 (a) 상세 API(W-02)에 `audio_available` 같은 필드 추가, (b) `error` 이벤트에서 일반 문구만 표시 중 선택 **[확인 필요]**.
2. **목 갱신.** 현재 목은 Range를 무시하고 200을 준다. 실제 서버는 `bytes=0-`에 206을 주므로 탐색 동작 차이는 목에서 재현되지 않는다(문제는 아님).
3. **운영 출처.** 운영에서 프론트를 API와 같은 출처로 서비스하는지. `<audio>`만 쓰면 무관하지만, 나중에 `fetch`·Web Audio·`crossorigin`을 쓰면 `Access-Control-Expose-Headers`에 `Content-Range`·`Accept-Ranges` 추가가 필요하다.
4. **다운로드 버튼 필요 여부.** 필요하면 `Content-Disposition` 파일명 정책(§11 D9) 확정.

### 팀 / 관리자

1. **클라이언트 IP 기록**(§11 D3) — 로그인 없는 환경에서 접근 주체를 남길 유일한 수단. 개인정보 처리 방침과 맞는지.
2. **음성 보존 기간**(E-07) — 사본 삭제 시점이 정해져야 "사본 없음" 빈도를 알 수 있다.

---

## 13. 테스트 전략

### 13.1 단위 (`-m "not integration"`, DB 없음)

**Range 파서(순수 함수, 표 기반 parametrize)** — §4.1 경계 사례 표 전체:
`None`, `bytes=0-`, `bytes=0-0`, `bytes=100-`, 끝 초과 보정, `bytes=-10`, suffix 초과(전체), `bytes=S-`/`bytes=-0`(416), `bytes=5-2`·`bytes=abc`·`bytes=`·`bytes=1-2-3`(무시), `items=0-1`(무시), `BYTES=0-1`(대소문자), 다중 범위(무시), `+5`·공백·비ASCII 숫자(무시), 5,000자리 숫자(무시).

**라우터·서비스** — `LocalStorage(tmp_path)`에 `DATA`를 저장하고, 키를 돌려주는 가짜 repository(또는 서비스 의존성 오버라이드)를 쓴다:

| 케이스 | 기대 |
|---|---|
| Range 없음 | 200, 본문 = `DATA`, `Content-Length`, `Accept-Ranges: bytes`, `Content-Type: audio/wav`, `Cache-Control` |
| `bytes=0-` | 206, `Content-Range: bytes 0-(S-1)/S` |
| `bytes=100-199` | 206, 본문 = `DATA[100:200]`, `Content-Length: 100` |
| `bytes=-10` | 206, 마지막 10바이트 |
| `bytes=S-` | 416, `Content-Range: bytes */S`, §7.2 본문(D4 결정 시) |
| 무효·다중 Range, `If-Range` 동반 | 200 전체 |
| `.mp3` 키 | `Content-Type: audio/mpeg` |
| 없는 건 | 404 `NOT_FOUND` |
| 키는 있으나 파일 없음 | 404 `NOT_FOUND` |
| 손상 키 | 500 `INTERNAL_ERROR`, 응답에 키 없음 |
| `id=0`, `id=abc` | 422 |
| `X-Request-Id` 존재 | |
| 응답 어디에도 `object_key` 없음 | 헤더·본문 검사 |
| 접근 로그 | `capsys`로 `audio_access`(D3) 줄: `call_id`·`range_start`·`range_end`·`status`, `Range` 원문·`original_name` 없음. `app.access` `status=206`·`call_id` |
| 세션 수명 | `get_db` 오버라이드를 yield 제너레이터로 두고 정리 시점을 기록 → 첫 청크 전에 닫혔는지(D2) |
| OpenAPI | `openapi.json` 재생성, operationId 고유(R-10 함수 이름과 겹치지 않게, 예: `get_call_audio`) |

### 13.2 통합 (`@pytest.mark.integration`)

- 별도 픽스처: `create_app(Settings(_env_file=None, audio_storage_root=tmp_path/"audio"))` + `dependency_overrides[get_db] = lambda: db_session`.
- `key = LocalStorage(root).save(io.BytesIO(DATA), extension=".wav")` → `make_call(db_session, object_key=key)`(기본 `object_key`는 키 형식이 아님).
- 케이스: 정상 206, 소프트 삭제 건 404, 다른 상태(`FAILED` 등)도 재생 가능.

### 13.3 수동 확인

- `uv run uvicorn …` + 브라우저 상세 화면에서 재생·탐색, 개발자 도구 Network에서 `Range: bytes=0-` → 206, 탐색 시 `bytes=N-` → 206 확인. Safari가 있으면 `bytes=0-1` 확인 요청도 확인.
- `curl -r 0-99 -i`로 헤더 확인.

---

## 14. 구현 시 주의

1. `Content-Length`는 실제 전송 바이트와 정확히 같아야 한다(끝 보정값 `min(end, S-1)` 사용).
2. `storage.open()`까지 응답 시작 전에 끝내야 404/416을 형식 응답으로 낼 수 있다.
3. 제너레이터 안에서 `with stream:`로 닫는다(클라이언트 중단 시에도 닫히게).
4. 라우트는 `def`(동기)로 둔다. 저장소 I/O가 블로킹이고, 청크 읽기는 Starlette가 스레드풀에서 한다.
5. `Range` 원문·`original_name`·`object_key`를 로그·에러 `detail`에 넣지 않는다.
6. `convention.md` §2.2 W-06 행(416 등), `architecture.md` §11·§12(접근 로그 필드)를 함께 갱신한다.
7. 라우트 추가 후 `uv run python -m scripts.export_openapi`로 `openapi.json` 재생성(같은 PR). 200/206 응답의 `content`를 `audio/wav`·`audio/mpeg` 바이너리로 문서화한다.

---

## 15. 참고 자료

- RFC 9110 HTTP Semantics — §13.1.5 If-Range, §14 Range Requests(§14.1.1~14.1.2 byte ranges, §14.2 Range, §14.3 Accept-Ranges, §14.4 Content-Range, §14.6 multipart/byteranges), §15.3.7 206, §15.5.17 416
- RFC 6266 Content-Disposition in HTTP (§4.3 filename/filename*)
- RFC 8187 Indicating Character Encoding and Language for HTTP Header Field Parameters (RFC 5987 대체)
- Starlette 1.10.0 `starlette/responses.py`(`StreamingResponse`, `FileResponse`), `starlette/concurrency.py`(`iterate_in_threadpool`)
- FastAPI 0.165.0 `fastapi/routing.py`(`request_stack`/`function_stack`), `fastapi/param_functions.py`(`Depends(scope=…)`)
- Uvicorn 0.54.0 `protocols/http/h11_impl.py`·`httptools_impl.py`(ASGI `spec_version "2.3"`)
