# 음성 재생 상세 구현 계획 — `GET /api/calls/{id}/audio`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-06 음성 재생 (P0, Phase 2, 선행 R-03) — 요구: PRD WEB-03 |
| 기준 커밋 | `2bde1c6` + **선행 커밋 "음성 형식 판정·정규 MIME 공용 모듈(`app/core/audio_format.py`)"** (cyj에 먼저 들어감, §4.2) |
| 근거 | `docs/researchs/audio-playback.md` v0.1(이하 "리서치"), `app/infra/storage/*`, `app/services/{robot_service,upload_service,call_service}.py`, `app/models/call_record.py`, `app/repositories/call_repository.py`, `app/api/{deps,web/calls,web/uploads}.py`, `app/main.py`, `app/core/{errors,middleware,logging,config}.py`, `app/schemas/common.py`, `tests/{conftest,factories}.py`, `tests/integration/{conftest,factories,test_calls_api}.py`, `tests/unit/{conftest,test_calls_api,test_logging,test_errors,test_openapi}.py`, `scripts/export_openapi.py`, `docs/api/convention.md`, `docs/architecture/architecture.md` |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / SQLAlchemy 2 / structlog (`uv.lock` 고정본) |
| 사전 검증 | `2bde1c6` 레포 전체 스크래치 복사본에 선행 커밋(`audio_format.py` 신설, `upload_service`·`test_upload_rules` import 교체)을 흉내 낸 뒤 이 문서의 코드·테스트를 그대로 넣어 확인함(레포 코드는 수정하지 않음). **기존 710 + 신규 79 = 789 통과**(Docker 켜짐 → 통합 포함, 수동 Drive 2 skip). `ruff check`·`ruff format --check`·`mypy .`(110파일, 선행 모듈 포함) 통과, `openapi.json` 재생성 후 `test_committed_openapi_is_up_to_date` 통과 |

---

## 1. 목표와 범위

### 1.1 목표
1. 웹 상세 화면의 `<audio src="/api/calls/{id}/audio">`가 **재생·탐색(seek)** 되도록, 삭제되지 않은 상담 건의 음성 사본을 **단일 바이트 범위 Range(206)** 와 전체(200)로 스트리밍한다.
2. 저장소 추상화(`AudioStorage.open(key, byte_range)`)만 사용한다. 파일 경로를 꺼내지 않는다(GCS 전환 X-02 대비).
3. 에러는 모두 §7.2 JSON 형식(416 포함). 응답·에러·로그에 `object_key`·`Range` 원문·파일명·클라이언트 IP를 남기지 않는다.
4. **음성 전송 중 DB 연결을 잡지 않는다.** 세션은 엔드포인트 함수가 끝날 때 닫히고, 그다음 스트리밍이 시작된다.
5. 재생 요청마다 감사용 `audio_access` 로그 1줄을 남긴다.

### 1.2 포함
- `app/core/http_range.py`(신규, 공용 Range 파서 — R-10도 쓸 수 있는 위치)
- `app/services/audio_service.py`(신규), `app/api/web/audio.py`(신규 라우터 + 서비스 의존성)
- 공용 파일 최소 변경: `app/core/errors.py`(코드 1개), `app/main.py`(import·`include_router` 각 1줄)
- 정규 MIME은 선행 커밋의 `app/core/audio_format.CANONICAL_MIME`을 import만 한다(이 계획에서 MIME 모듈을 새로 만들지 않음)
- `docs/api/openapi.json` 재생성
- 테스트: 단위(파서·서비스·라우터), 통합(실제 DB 조회 조건·세션 닫힘 시점)
- 공용 문서: `convention.md` §2.2 W-06 행 + §3.6 신설, `architecture.md` §8.1 시그니처 정정·§11 1줄

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| GCS 302 서명 URL | X-02(Phase 3). 지금은 `LocalStorage`뿐 |
| 다중 범위(`multipart/byteranges`)·`ETag`/`If-Range` 검증 | D6·D7. 미디어 플레이어가 쓰지 않음 |
| HEAD | D17. 브라우저 미디어 요청은 HEAD를 쓰지 않음(405) |
| 클라이언트 IP 기록, DB 감사 테이블 | 사용자 확정 D3: IP 미기록. 장기 보관은 §9 확인 필요 |
| R-10 로봇 다운로드 라우트 | A 담당. 파서만 공용 위치에 둠(D15) |
| W-02 상세에 `audio_available` 추가 | 프론트 요구 확정 후(§9.2 F1) |
| `call_repository.py`·`deps.py`·`calls.py` 수정 | 다른 작업과 충돌을 줄이기 위해 건드리지 않음(§3.3) |
| `BodySizeLimitMiddleware` 응답 시작 후 처리 | D14. 정상 브라우저 무관, W-11 때 함께 검토 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| Range 해석 | `app.core.http_range.parse_range(header: str \| None, size: int) -> tuple[int, int] \| None` | R-10(로봇 다운로드)에서 Range를 지원할 경우 |
| 416 신호 | `app.core.http_range.RangeNotSatisfiableError(size)` (`.size`) | 같음 |
| 정규 MIME | `app.core.audio_format.CANONICAL_MIME: dict[AudioExtension, str]` (선행 커밋 제공, 이 계획은 사용만) | W-07, W-06, R-10 |
| 에러 코드 | `ErrorCode.RANGE_NOT_SATISFIABLE` (416) | 같음 |
| 서비스 | `app.services.audio_service.AudioService.open_audio(call_id, range_header) -> AudioContent` | R-10이 같은 조회 규칙을 쓸 경우 |

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 항목 | 실제 (`2bde1c6`) | 이 계획의 반영 |
|---|---|---|
| 저장소 | `AudioStorage`(`save`·`open`·`size`·`delete`·`check`), `ByteRange = tuple[int, int \| None]`, `LocalStorage.open(key, (s, e))`는 끝을 파일 크기로 자름, 없는 파일 `AudioNotFoundError(key)`(메시지에 키 포함), 키 형식 오류 `InvalidKeyError("올바르지 않은 키")` | 그대로 사용. `AudioNotFoundError`는 `from None`으로 끊어 키가 남지 않게 함 |
| 저장소 주입 | `deps.get_audio_storage(request)` → `app.state.audio_storage` | 재사용(수정 없음) |
| 세션 | `deps.get_db`(yield), `DbSession = Annotated[Session, Depends(get_db)]` = request scope | 음성 라우트는 `DbSession`을 쓰지 않고 `Depends(get_db, scope="function")` |
| `Depends(scope=…)` | FastAPI 0.165 `param_functions.Depends`에 `scope` 인자 있음. `dependency_overrides[get_db]`로 바꿔도 scope 유지(실측: 아래 #47) | 테스트는 `get_db`를 오버라이드해 닫힘 시점 기록 |
| 키 | `robot_service`가 매직 바이트로 `.wav`/`.mp3`를 정해 `storage.save()` → `object_key` | `object_key` 확장자 → MIME |
| MIME 표 | `upload_service.CANONICAL_MIME`(`wav`→`audio/wav`, `mp3`→`audio/mpeg`) | 선행 커밋이 `HEAD_BYTES`·`CANONICAL_MIME`·`detect_audio_format`을 `app/core/audio_format.py`로 옮김(D13). W-06은 거기서 import |
| 에러 | `ErrorCode`에 416 없음. `error_response(code, headers=…, status_code=…)` 있음. `AppError`에는 헤더 수단 없음 | 코드 1개 추가. 416은 라우터가 `error_response(headers=…)` |
| 라우터 | `calls.py`: `APIRouter(prefix="/api/calls", tags=["calls"])`, `BIGINT_MAX`, `bind_call_id` | 별도 `audio.py` 라우터(같은 prefix·tag), `BIGINT_MAX`는 import |
| operationId | 라우트 함수 이름, 앱 전체 고유 | `get_call_audio` (R-10은 다른 이름 필요) |
| 팩토리 | `tests/integration/factories.make_call` 기본 `object_key="audio/{n}.wav"`(키 형식 아님) | 통합 테스트는 `storage.save()`로 만든 실제 키를 넘김 |
| 통합 `api` 픽스처 | `audio_storage_root` 기본값(`./data/audio`) | 별도 픽스처(`tmp_path`) |
| 로그 캡처 | `create_app()` 시 `configure_logging`이 그때의 `sys.stdout`에 핸들러를 담. 픽스처에서 앱을 만들면 `capsys`가 잡지 못함(실측) | 로그 테스트는 본문에서 `configure_logging("INFO")`를 다시 호출 |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| D1 | 구현 방식 | `StreamingResponse` + 자체 **단일 범위** Range 파서 + `AudioStorage.open`. `FileResponse` 미사용(경로 필요, 400/416 `text/plain`) |
| D2 | DB 세션 수명 | 서비스 의존성이 `Annotated[Session, Depends(get_db, scope="function")]`를 받는다 → 엔드포인트 반환 시 세션 닫힘, 그 뒤 스트리밍. 단위·통합 테스트로 "`db_close`가 첫 `read`보다 먼저"를 검증 |
| D3 | 접근 로그 | 로거 `app.audio`, 이벤트 `audio_access`: `call_id`·`range_start`·`range_end`(전체면 `null`)·`status`(200/206)·`bytes`(Content-Length). `request_id`는 기존 contextvars. **`Range` 원문·클라이언트 IP·키·파일명은 남기지 않음** |
| D4 | 416 | 새 `ErrorCode.RANGE_NOT_SATISFIABLE`(416, "요청한 범위를 제공할 수 없습니다.") + §7.2 JSON(`detail: null`) + `Content-Range: bytes */<크기>` |
| D15 | 파서 위치 | 공용 `app/core/http_range.py`(서비스·로봇 라우트 어디서나 import 가능, 순수 함수) |

### 3.2 리서치 §11 권장안 채택
| # | 항목 | 결정 |
|---|---|---|
| D5 | 무효 Range(문법 오류) | 무시하고 200 전체 (RFC 9110 §14.2 MAY, 브라우저 호환) |
| D6 | 다중 범위 | 무시하고 200 전체 |
| D7 | `If-Range`/`ETag` | 검증자 미발급. `If-Range`가 오면 Range 무시(일치할 수 없음 → RFC 9110 §13.1.5상 전체) |
| D8 | `Cache-Control` | `private, no-store` (PII 음성, 공유 PC·프록시 캐시 방지) |
| D9 | `Content-Disposition` | `inline; filename="call-{id}.{wav\|mp3}"` — 리서치 (b). `original_name`(담당자·고객사) 미사용 → 헤더 주입·PII 걱정 없음, 조회 컬럼도 줄어듦. 다운로드 파일명 요구가 생기면 (c)로 확장(§9.2 F4) |
| D10 | 레코드는 있으나 사본 없음 | 404 `NOT_FOUND` + `app.audio` `audio_missing` 경고(키 없이 `call_id`만) |
| D11 | `InvalidKeyError`(DB 값 손상) | 잡지 않음 → `UnhandledErrorMiddleware` 500. 응답에 키 없음(예외 메시지에도 키 없음) |
| D12 | 저장소 I/O 장애(`OSError` 등) | 잡지 않음 → 500. 503 신규 코드는 X-02 때 검토 |
| D13 | MIME 매핑 위치 | **확정**: 공용 모듈 `app/core/audio_format.py`(`HEAD_BYTES`, `CANONICAL_MIME`, `detect_audio_format`. `AudioExtension`은 `app/core/config.py`에 그대로). 선행 커밋으로 cyj에 먼저 들어가며 W-06은 import만 한다. 서비스끼리 import하지 않음 |
| D14 | chunked 본문 + 스트리밍 | 수용·문서화(비정상 GET만 해당) |
| D16 | 키 조회 쿼리 | `object_key`만 읽는 SELECT(`deleted_at IS NULL`). JOIN 없음 |
| D17 | HEAD | 미지원(405) |
| D18 | 청크 크기 | 64 KiB **[가정]** (`FileResponse`와 같음) |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| 파일 배치 | 라우터 `app/api/web/audio.py`(`prefix="/api/calls"`, `tags=["calls"]`), 서비스 `app/services/audio_service.py`, 서비스 의존성 `get_audio_service`는 **라우터 파일 안**에 둠 | 같은 시기 다른 작업이 `calls.py`·`call_service.py`·`call_repository.py`·`deps.py`·`schemas/call.py`를 수정 → 충돌 회피. R-10이 같은 서비스를 쓰게 되면 그때 `deps.py`로 옮김 |
| 키 조회 위치 | 서비스가 세션으로 직접 SELECT(`RobotService` 선례) | `call_repository.py`를 건드리지 않기 위함(D16을 저장소 계층 없이 충족) |
| 처리 순서 | ① `bind_call_id` ② `If-Range` 있으면 Range 무시 ③ 키 조회 → 없으면 404 ④ 확장자 → MIME(표에 없으면 `KeyError` → 500) ⑤ `size()` ⑥ `parse_range()` ⑦ `open()` ⑧ `audio_access` 로그 ⑨ 함수 반환(세션 닫힘) ⑩ 스트리밍 | 응답 헤더를 만들기 전에 `open()`까지 끝내야 404/416을 형식 응답으로 낼 수 있음. ⑤~⑦의 `AudioNotFoundError`는 모두 404(`size()`와 `open()` 사이 삭제 포함) |
| 파서 반환값 | `(시작, 끝)` **끝 포함·보정 완료**(`min(end, size-1)`), suffix도 절대 위치로 바꿔 반환 | 라우터가 그대로 `Content-Range`·`Content-Length` 계산. `storage.open`의 보정과 일치 |
| 숫자 검사 | `isascii() and isdigit()` 후 `int()`, `ValueError`(4,300자리 초과)는 무효 | `" 5"`·`"+5"`·`"٥"` 거절. `BodySizeLimitMiddleware`와 같은 방식 |
| 공백 | 단위 이름은 대소문자만 무시(`BYTES=`), `=` 뒤 범위 목록의 앞뒤 공백만 허용 | RFC 문법(`1#range-spec`의 OWS). 범위 안 공백(`0 -1`)은 무효 |
| 빈 파일(S=0) | Range 있으면 416, 없으면 200 빈 본문 | 등록 시 빈 파일은 415라 실제로는 없음 |
| 416 응답 | 서비스는 `RangeNotSatisfiableError`를 그대로 올리고 라우터가 `error_response(RANGE_NOT_SATISFIABLE, headers={"Content-Range": ...})`를 **반환** | `AppError`에 헤더를 실을 수단이 없음. `errors.py` 변경을 코드 1개로 제한(§3.4-2 예외로 규약에 명시, §5.9) |
| 응답 헤더 | `Accept-Ranges: bytes`, `Content-Length`, `Cache-Control: private, no-store`, `Content-Disposition`, `X-Content-Type-Options: nosniff`, 206이면 `Content-Range: bytes a-b/S` | 리서치 §6.2 |
| 스트림 닫기 | 제너레이터 안 `with stream:` | 전송 중 클라이언트가 끊어도 닫힘. 제너레이터가 한 번도 시작되지 않으면 참조 해제 시 닫힘(CPython) |
| 라우트 | `def`(동기) | 저장소 I/O가 블로킹. 청크 읽기는 Starlette가 스레드풀에서 실행 |
| OpenAPI | `response_class=StreamingResponse`, `response_model=None`, `responses`에 200·206 `audio/wav`·`audio/mpeg`(binary) + `error_responses(NOT_FOUND, RANGE_NOT_SATISFIABLE)` | 200 본문이 JSON으로 문서화되지 않음(실측: 200 content는 두 오디오 타입만) |
| `audio_access` 시점 | 서비스에서 `open()` 성공 직후(응답 시작 전) | 404·416은 남기지 않음 — `app.access`가 상태·`call_id`를 이미 남김. 실제 전송 완료 여부는 `app.access`의 `status`·`latency_ms`로 보완 |
| 로그 테스트 | 앱을 만든 뒤 테스트 본문에서 `configure_logging("INFO")` 재호출 | 픽스처에서 만든 앱의 핸들러는 `capsys` 이전 stdout을 가리킴(실측) |
| 테스트 공용 가짜 | `tests/audio_fakes.py`(`DATA`, `SIZE`, `FakeSession`, `ReadRecorder`) | 단위·통합 둘 다 사용. `test_*.py`가 아니라 수집되지 않음 |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준) | 내용 |
|---|---|---|
| 신규 | `app/core/http_range.py` | `RangeNotSatisfiableError`, `parse_range` |
| 수정 | `app/core/errors.py` | `RANGE_NOT_SATISFIABLE` enum 1줄 + `_ERROR_SPECS` 1줄 |
| 신규 | `app/services/audio_service.py` | `AudioContent`, `AudioService` |
| 신규 | `app/api/web/audio.py` | `router`, `get_audio_service`, `get_call_audio` |
| 수정 | `app/main.py` | import에 `audio` 추가, `app.include_router(audio.router)` |
| 재생성 | `docs/api/openapi.json` | `/api/calls/{call_id}/audio`, `ErrorCode` enum에 `RANGE_NOT_SATISFIABLE` |
| 신규 | `tests/audio_fakes.py` | 테스트 공용 가짜·데이터 |
| 신규 | `tests/unit/test_http_range.py` | 34건 |
| 신규 | `tests/unit/test_audio_service.py` | 10건 |
| 신규 | `tests/unit/test_audio_api.py` | 28건 |
| 신규 | `tests/integration/test_audio_api.py` | 7건 |
| 수정 | `docs/api/convention.md` | §2.2 W-06 행 에러 열 `404, 416`, §3.6 신설 |
| 수정 | `docs/architecture/architecture.md` | §8.1 시그니처 정정, §11 데이터 행 |

- **선행 커밋이 다루는 파일(이 계획 범위 밖)**: `app/core/audio_format.py`(신규), `app/services/upload_service.py`, `tests/unit/test_upload_rules.py`(import 경로).
- **변경하지 않는 파일**: `app/core/config.py`, `app/core/audio_format.py`, `app/services/upload_service.py`, `app/api/deps.py`, `app/api/web/calls.py`, `app/services/call_service.py`, `app/repositories/call_repository.py`, `app/schemas/*`, `app/core/middleware.py`, `app/core/logging.py`, `app/infra/storage/*`, 기존 테스트 파일 전부, `pyproject.toml`·`uv.lock`.

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_openapi.py` | `test_committed_openapi_is_up_to_date`가 재생성 전까지 실패(의도). `test_error_code_is_documented_as_enum`은 enum을 코드에서 읽어 자동 통과. `test_operation_ids_are_unique_in_real_app` 통과 |
| `tests/unit/test_upload_*.py` | 이 계획에서는 변경 없음(선행 커밋이 `test_upload_rules.py`의 `detect_audio_format` import를 `app.core.audio_format`으로 바꿈) |
| 그 밖 | 변경 없음 |

### 4.2 다른 작업과의 충돌 가능성

**선행 커밋과 작업 순서**: MIME 공용화 커밋(`app/core/audio_format.py` 신설 — `HEAD_BYTES`, `CANONICAL_MIME`, `detect_audio_format`을 `upload_service.py`에서 그대로 이동)이 **W-06보다 먼저 cyj에 들어간다.** W-06 구현 worktree는 그 커밋 위로 옮긴 뒤(rebase 또는 새 기준에서 시작) 진행한다. 그 전에 시작했다면 `audio_service.py`의 `from app.core.audio_format import CANONICAL_MIME`이 import 오류가 나므로, 임시 MIME 표를 따로 만들지 말고 기준을 먼저 옮긴다.

| 파일 | 이 계획의 변경 | 충돌 시 처리 |
|---|---|---|
| `app/main.py` | import 줄(`audio, calls, stats, uploads`)과 `include_router` 1줄 | 양쪽 줄을 모두 남김 |
| `app/core/errors.py` | `UNSUPPORTED_MEDIA` 바로 다음에 enum·spec 각 1줄 | 다른 코드 추가와 인접하면 양쪽 모두 남김 |
| `docs/api/openapi.json` | 생성물 | **손으로 병합하지 않는다.** 병합 후 `uv run python -m scripts.export_openapi`로 다시 생성 |
| `docs/api/convention.md` | §2.2 한 행, §3.6 신설 | 다른 작업이 §3.6을 먼저 쓰면 번호만 뒤로 |

---

## 5. 모듈별 코드

### 5.1 `app/core/http_range.py` (신규)
```python
"""HTTP `Range` 요청 헤더 해석 (RFC 9110 §14). 단일 바이트 범위만 지원한다.

음성 재생(`GET /api/calls/{id}/audio`)이 쓴다. 로봇 음성 다운로드도 같은 규칙을 쓸 수 있게
공용 위치에 둔다.
"""


class RangeNotSatisfiableError(Exception):
    """범위가 파일 크기를 벗어난다 (HTTP 416). `size`는 `Content-Range: bytes */<size>`에 쓴다."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__(f"size={size}")


def _to_int(text: str) -> int | None:
    # RFC의 1*DIGIT만 허용한다. int()는 " 5"·"+5"·"٥"(비ASCII 숫자)도 받아서 먼저 거른다.
    if not (text.isascii() and text.isdigit()):
        return None
    try:
        return int(text)
    except ValueError:  # 4,300자리 초과 (int 변환 자릿수 한도)
        return None


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """`Range` 헤더를 (시작, 끝) 바이트로 바꾼다. 끝은 포함이고 `size - 1`을 넘지 않게 맞춘다.

    None이면 Range를 무시하고 전체(200)를 보낸다: 헤더 없음, 모르는 단위, 문법 오류,
    다중 범위. 문법은 맞지만 파일 안에 들어오는 바이트가 없으면 RangeNotSatisfiableError.
    """
    if header is None:
        return None
    unit, sep, spec = header.partition("=")
    if not sep or unit.lower() != "bytes" or "," in spec:
        return None
    first, dash, last = spec.strip().partition("-")
    if not dash:
        return None
    if first == "":  # bytes=-N: 마지막 N바이트
        suffix = _to_int(last)
        if suffix is None:
            return None
        if suffix == 0 or size == 0:
            raise RangeNotSatisfiableError(size)
        return (max(size - suffix, 0), size - 1)
    start = _to_int(first)
    end = _to_int(last) if last else None
    if start is None or (last and end is None):
        return None
    if end is not None and end < start:
        return None
    if start >= size:
        raise RangeNotSatisfiableError(size)
    return (start, size - 1 if end is None else min(end, size - 1))
```

### 5.2 `app/core/errors.py` (수정)
```python
class ErrorCode(StrEnum):
    ...
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    RANGE_NOT_SATISFIABLE = "RANGE_NOT_SATISFIABLE"  # 추가
    UNAUTHORIZED = "UNAUTHORIZED"
    ...

_ERROR_SPECS: dict[ErrorCode, tuple[int, str]] = {
    ...
    ErrorCode.UNSUPPORTED_MEDIA: (415, "허용되지 않은 파일 형식입니다."),
    ErrorCode.RANGE_NOT_SATISFIABLE: (416, "요청한 범위를 제공할 수 없습니다."),  # 추가
    ...
}
```
- `_STATUS_TO_CODE`(HTTPException 매핑)는 바꾸지 않는다. 416은 `HTTPException`으로 나가지 않는다.

### 5.3 정규 MIME (선행 커밋 사용, D13)
- 이 계획은 `app/core/audio_format.py`를 만들거나 고치지 않는다. 선행 커밋이 제공하는 `CANONICAL_MIME: dict[AudioExtension, str]`을 `audio_service.py`에서 import해 키 확장자(`.wav`/`.mp3`) → MIME 표를 만든다(§5.4).

### 5.4 `app/services/audio_service.py` (신규)
```python
"""음성 재생 유스케이스 (W-06): 상담 건의 음성 사본을 찾아 요청 구간만 읽을 스트림을 연다."""

from dataclasses import dataclass
from typing import BinaryIO

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audio_format import CANONICAL_MIME
from app.core.errors import AppError, ErrorCode
from app.core.http_range import parse_range
from app.infra.storage import AudioNotFoundError, AudioStorage
from app.models import CallRecord

# 저장소 키 확장자 → 정규 MIME. 확장자는 등록 시 매직 바이트로 정한 실제 형식이다.
_MEDIA_TYPES: dict[str, str] = {f".{ext}": mime for ext, mime in CANONICAL_MIME.items()}

_log = structlog.stdlib.get_logger("app.audio")


@dataclass(frozen=True)
class AudioContent:
    """열린 음성 스트림과 응답 헤더 계산에 필요한 값. stream은 호출자가 닫는다."""

    stream: BinaryIO
    media_type: str
    extension: str  # ".wav" / ".mp3"
    size: int  # 파일 전체 크기
    byte_range: tuple[int, int] | None  # (시작, 끝) 끝 포함. None이면 전체

    @property
    def length(self) -> int:
        """보낼 바이트 수 (Content-Length)."""
        if self.byte_range is None:
            return self.size
        start, end = self.byte_range
        return end - start + 1


class AudioService:
    def __init__(self, db: Session, storage: AudioStorage) -> None:
        self._db = db
        self._storage = storage

    def open_audio(self, call_id: int, range_header: str | None) -> AudioContent:
        """삭제되지 않은 건의 음성을 연다.

        없는 건·삭제된 건·사본 파일이 없는 건은 404. 범위가 파일 밖이면 RangeNotSatisfiableError.
        키 형식 오류(InvalidKeyError)·디스크 오류(OSError)는 그대로 올려 500이 된다.
        """
        key = self._db.scalar(
            select(CallRecord.object_key).where(
                CallRecord.id == call_id, CallRecord.deleted_at.is_(None)
            )
        )
        if key is None:
            raise AppError(ErrorCode.NOT_FOUND)
        media_type = _MEDIA_TYPES[key[key.rfind(".") :]]  # 표에 없으면 KeyError → 500
        try:
            size = self._storage.size(key)
            byte_range = parse_range(range_header, size)
            stream = self._storage.open(key, byte_range)
        except AudioNotFoundError:
            # 레코드는 있는데 사본이 없다(정리 배치·운영 사고). 키는 로그에 남기지 않는다.
            _log.warning("audio_missing", call_id=call_id)
            raise AppError(ErrorCode.NOT_FOUND) from None
        audio = AudioContent(stream, media_type, key[key.rfind(".") :], size, byte_range)
        _log.info(
            "audio_access",
            call_id=call_id,
            range_start=byte_range[0] if byte_range else None,
            range_end=byte_range[1] if byte_range else None,
            status=206 if byte_range else 200,
            bytes=audio.length,
        )
        return audio
```
- `InvalidKeyError`는 `size()`에서 파일 접근 전에 난다(경로 탈출 차단). 잡지 않으므로 `app.error` 로그 + 500(D11).
- `RangeNotSatisfiableError`는 잡지 않는다(라우터가 416으로 바꿈). `open()`은 이미 연 파일이 없으므로 누수 없음.

### 5.5 `app/api/web/audio.py` (신규)
```python
"""웹 음성 재생 API: `GET /api/calls/{call_id}/audio` (HTTP Range)."""

from collections.abc import Iterator
from typing import Annotated, Any, BinaryIO

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_audio_storage, get_db
from app.api.web.calls import BIGINT_MAX
from app.core.errors import ErrorCode, error_response
from app.core.http_range import RangeNotSatisfiableError
from app.core.logging import bind_call_id
from app.infra.storage import AudioStorage
from app.schemas.common import error_responses
from app.services.audio_service import AudioService

CHUNK_SIZE = 64 * 1024  # Starlette FileResponse와 같은 크기

router = APIRouter(prefix="/api/calls", tags=["calls"])


def get_audio_service(
    # scope="function": 엔드포인트 함수가 끝나면 세션을 닫는다. 기본(request)이면 음성 전송이
    # 끝날 때까지(브라우저 재생 속도로 수 분) DB 연결을 붙잡는다.
    session: Annotated[Session, Depends(get_db, scope="function")],
    storage: Annotated[AudioStorage, Depends(get_audio_storage)],
) -> AudioService:
    return AudioService(session, storage)


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]

_BINARY = {"schema": {"type": "string", "format": "binary"}}
_AUDIO_CONTENT = {"audio/wav": _BINARY, "audio/mpeg": _BINARY}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "전체 음성 (Range 없음·무시)", "content": _AUDIO_CONTENT},
    206: {"description": "요청 구간 (단일 바이트 범위)", "content": _AUDIO_CONTENT},
    **error_responses(ErrorCode.NOT_FOUND, ErrorCode.RANGE_NOT_SATISFIABLE),
}


def _iter_chunks(stream: BinaryIO) -> Iterator[bytes]:
    # 제너레이터 안에서 닫아야 전송 중 클라이언트가 끊어도 파일 핸들이 남지 않는다.
    with stream:
        while chunk := stream.read(CHUNK_SIZE):
            yield chunk


@router.get(
    "/{call_id}/audio",
    response_class=StreamingResponse,
    response_model=None,
    responses=_RESPONSES,
)
def get_call_audio(
    call_id: Annotated[int, Path(ge=1, le=BIGINT_MAX)],
    request: Request,
    service: AudioServiceDep,
) -> Response:
    bind_call_id(request, call_id)
    # 검증자(ETag·Last-Modified)를 발급하지 않으므로 If-Range는 일치할 수 없다 → Range 무시.
    range_header = None if "if-range" in request.headers else request.headers.get("range")
    try:
        audio = service.open_audio(call_id, range_header)
    except RangeNotSatisfiableError as exc:
        # AppError는 응답 헤더를 실을 수 없어 Content-Range가 필요한 416은 여기서 만든다.
        return error_response(
            ErrorCode.RANGE_NOT_SATISFIABLE, headers={"Content-Range": f"bytes */{exc.size}"}
        )
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(audio.length),
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'inline; filename="call-{call_id}{audio.extension}"',
        "X-Content-Type-Options": "nosniff",
    }
    if audio.byte_range is not None:
        start, end = audio.byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{audio.size}"
    return StreamingResponse(
        _iter_chunks(audio.stream),
        status_code=200 if audio.byte_range is None else 206,
        media_type=audio.media_type,
        headers=headers,
    )
```
- `StreamingResponse`는 `Content-Length`를 자동으로 넣지 않으므로 직접 준 값이 나가고, Uvicorn은 chunked 대신 고정 길이로 보낸다. 값은 실제 전송 바이트와 정확히 같아야 한다(파서가 끝을 `size-1`로 보정, `storage.open`도 같은 보정).
- 함수 이름 `get_call_audio`는 operationId. R-10 라우트는 다른 이름(예: `download_call_audio`)이어야 한다.

### 5.6 `app/main.py` (수정)
```python
from app.api.web import audio, calls, stats, uploads   # audio 추가
...
    app.include_router(calls.router)
    app.include_router(audio.router)                   # 추가
    app.include_router(robot_calls.router)
```

### 5.7 `docs/api/openapi.json` (재생성)
`cd backend && uv run python -m scripts.export_openapi`. 기대 diff(사전 검증 확인):
- 경로 `/api/calls/{call_id}/audio` `get` 추가: `operationId: get_call_audio`, `tags: ["calls"]`, `call_id` 경로 파라미터(1 ~ 2^63-1), 응답 `200`·`206`(`audio/mpeg`·`audio/wav` binary), `404`·`416`(`ErrorResponse`), `422`(`ValidationErrorResponse`), `500`.
- `components.schemas.ErrorCode.enum`에 `RANGE_NOT_SATISFIABLE`.
- 새 스키마 없음.

### 5.8 테스트 공용 가짜 `tests/audio_fakes.py` (신규)
```python
"""음성 재생 테스트(단위·통합) 공용 가짜·데이터. `test_*.py`가 아니라 수집되지 않는다."""

import io
from typing import Any, BinaryIO

DATA = bytes(range(256)) * 40  # 10,240바이트. 위치마다 값이 달라 구간 검증이 쉽다
SIZE = len(DATA)


class FakeSession:
    """`scalar()`만 흉내 낸다. 조회 조건은 통합 테스트가 확인한다."""

    def __init__(self, key: str | None, events: list[str] | None = None) -> None:
        self.key = key
        self.events = events if events is not None else []

    def scalar(self, statement: Any) -> str | None:
        self.events.append("query")
        return self.key


class ReadRecorder(io.RawIOBase):
    """읽을 때마다 events에 "read"를 남기는 래퍼."""

    def __init__(self, inner: BinaryIO, events: list[str]) -> None:
        self._inner = inner
        self._events = events

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        self._events.append("read")
        return int(self._inner.readinto(buffer))  # type: ignore[attr-defined]

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            super().close()
```

### 5.9 공용 문서 보완 (중립 표현)

**`docs/api/convention.md` §2.2** — W-06 행 에러 열:
```markdown
| GET | `/api/calls/{id}/audio` | 200 / 206(Range) / 302(GCS 서명 URL) | 404, 416 |
```

**`docs/api/convention.md` §3.6 신설** (§3.5 다음):
```markdown
### 3.6 음성 재생 (`GET /api/calls/{id}/audio`)
- 단일 바이트 범위(`bytes=a-b`, `bytes=a-`, `bytes=-n`)만 206으로 응답한다(`Content-Range`, `Accept-Ranges: bytes`). 문법 오류·모르는 단위·다중 범위이거나 `If-Range`가 함께 오면 Range를 무시하고 200 전체를 보낸다.
- 범위가 파일 밖이면 416 `RANGE_NOT_SATISFIABLE`(§3.1 형식, `detail: null`)과 `Content-Range: bytes */<크기>` 헤더. 헤더가 필요해 라우터가 `error_response(..., headers=...)`를 직접 반환한다(§3.4-2의 예외).
- 없는 건·삭제된 건·음성 사본 파일이 없는 건은 모두 404 `NOT_FOUND`다. 응답은 `Cache-Control: private, no-store`.
```

**`docs/architecture/architecture.md` §8.1** — 코드 블록을 실제 Protocol로 교체:
```python
ByteRange = tuple[int, int | None]  # (시작, 끝) 끝 포함, None이면 파일 끝까지

class AudioStorage(Protocol):
    def save(self, stream: BinaryIO, *, extension: str) -> str: ...  # UUID 키 반환
    def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO: ...
    def size(self, key: str) -> int: ...
    def delete(self, key: str) -> None: ...
    def check(self) -> None: ...  # 헬스 체크
```
표 아래 1줄 추가: `GCSStorage`의 서명 URL 발급 메서드는 X-02에서 Protocol에 추가한다. `LocalStorage` 행의 재생 방식은 "API가 Range 응답으로 직접 스트리밍(`StreamingResponse` + `app/core/http_range.py`)".

**`docs/architecture/architecture.md` §11** — "데이터" 행:
```markdown
| 데이터 | 마스킹된 텍스트만 저장, 음성 재생·다운로드 접근 로그 기록(`app.audio` `audio_access`: `call_id`·구간·상태·바이트. `Range` 원문·클라이언트 IP는 남기지 않음) |
```

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 파서는 순수 함수 표 기반 parametrize(리서치 §4.1 경계 사례 전부).
- 서비스 단위: 실제 `LocalStorage(tmp_path)` + `FakeSession`(`scalar()`만). 조회 조건(`deleted_at`)은 통합 테스트가 검증.
- 라우터 단위: `build_app(audio_storage_root=tmp_path/"audio")` + `dependency_overrides[get_db]` = 이벤트를 남기는 제너레이터(실제 `get_audio_service`의 `scope="function"` 경로를 그대로 탄다).
- 통합: 실제 PostgreSQL(`db_session`) + `tmp_path` 저장소, `make_call(object_key=storage.save(...))`.
- 로그 단언은 본문에서 `configure_logging("INFO")`를 다시 부른 뒤 `capsys`로 읽는다.

### 6.2 케이스 목록 (구현 순서)
| # | 파일 | 케이스 | 기대 |
|---|---|---|---|
| 1 | `test_http_range` | `None`, `0-`, `0-0`, `100-`, `100-199`, `999-999`, 끝 초과, `-10`, `-1000`, suffix 초과, `BYTES=`, 앞뒤 OWS, 5,000자리 끝 | 표의 (시작, 끝) / None |
| 2 | 〃 | `5-2`, `abc`, `bytes=`, `-`, `1-2-3`, `--5`, `+5-`, `0-+5`, `0 -1`, `٥-`, `items=0-1`, `=` 없음, 다중 2종, 빈 문자열 | None(무시) |
| 3 | 〃 | `1000-`, `5000-6000`, `-0` | `RangeNotSatisfiableError(size=1000)` |
| 4 | 〃 | 빈 파일 + `0-`/`-1` | 416 예외 |
| 5 | 〃 | 빈 파일 + 헤더 없음 | None |
| 6 | `test_audio_service` | Range 없음 | 전체 스트림, `audio/wav`, `.wav`, `length = SIZE` |
| 7 | 〃 | `100-199` | 구간 스트림, `length = 100` |
| 8 | 〃 | `.mp3` 키 | `audio/mpeg` |
| 9 | 〃 | 레코드 없음 | `AppError(NOT_FOUND)` |
| 10 | 〃 | 파일 없음 | `AppError(NOT_FOUND)`, `__suppress_context__`, `audio_missing` 경고(키 없음) |
| 11 | 〃 | 손상 키 | `InvalidKeyError` 전파 |
| 12 | 〃 | `S-` | `RangeNotSatisfiableError.size == S` |
| 13 | 〃 | 무효 Range | `byte_range is None` |
| 14 | 〃 | `audio_access` (200 / 206 두 경우) | `logger`·`level`·`call_id`·`range_*`·`status`·`bytes`, 키 없음 |
| 15 | `test_audio_api` | Range 없음 | 200, 본문, `Content-Type`·`Content-Length`·`Accept-Ranges`·`Cache-Control`·`Content-Disposition`·`nosniff`, `Content-Range` 없음, `X-Request-Id` |
| 16 | 〃 | `0-`, `0-1`, `100-199`, `-10`, `5000-`, `0-99999999` | 206, 본문 구간, `Content-Range`·`Content-Length` |
| 17 | 〃 | `5-2`, `abc`, `items=0-1`, 다중 | 200 전체 |
| 18 | 〃 | `Range` + `If-Range` | 200 전체 |
| 19 | 〃 | mp3 | `audio/mpeg`, `filename="call-7.mp3"` |
| 20 | 〃 | 256 KiB 파일 `1-` | 206, 청크 여러 개로도 본문 일치 |
| 21 | 〃 | `S-` | 416, `Content-Range: bytes */S`, §7.2 본문 전체 일치 |
| 22 | 〃 | `error_status(RANGE_NOT_SATISFIABLE)` | 416 |
| 23 | 〃 | 레코드 없음 / 파일 없음 | 404 `NOT_FOUND`, 응답에 키 없음 |
| 24 | 〃 | 손상 키(`../secret.wav`) | 500 `INTERNAL_ERROR`, 응답에 키 없음 |
| 25 | 〃 | `id=0`, `abc`, `2**63` | 422 |
| 26 | 〃 | HEAD | 405 |
| 27 | 〃 | 206 응답 헤더·본문 | 키 없음 |
| 28 | 〃 | 로그 | `audio_access`(`call_id`·`request_id`·`range_*`·`status`·`bytes`), `app.access` `status=206`·`call_id`, 출력 어디에도 `Range` 원문·키·`testclient`(클라이언트 주소) 없음 |
| 29 | 〃 | 416·404 요청 | `audio_access` 없음, `app.access`는 2줄 |
| 30 | 〃 | **세션 수명** | 이벤트 `["db_open", "query", "db_close", "read", ...]` (D2) |
| 31 | 〃 | OpenAPI | `operationId`·`tags`·응답 집합 `{200,206,404,416,422,500}`·200/206 content 두 타입·416 description |
| 32 | `integration/test_audio_api` | `STORED` 건 `bytes=100-` | 206 end-to-end |
| 33 | 〃 | **세션 수명(실제 세션)** | `["db_open", "db_close", "read", ...]` |
| 34 | 〃 | `REGISTERED`·`FAILED`·`RETRY_REQUESTED` | 200 (상태 무관 재생) |
| 35 | 〃 | 소프트 삭제 건 | 404 |
| 36 | 〃 | 없는 id | 404 |
| 37 | — | `openapi.json` 재생성 | `test_committed_openapi_is_up_to_date` 통과 |

- #30 회귀 확인(사전 검증): `Depends(get_db)`(scope 없음)로 바꾸면 `['db_open', 'query', 'read']`로 실패한다.

### 6.3 케이스 수
| 파일 | 건수 |
|---|---|
| `tests/unit/test_http_range.py` | 34 |
| `tests/unit/test_audio_service.py` | 10 |
| `tests/unit/test_audio_api.py` | 28 |
| `tests/integration/test_audio_api.py` | 7 |
| 합계 | **79** (단위 72 + 통합 7) |

### 6.4 테스트 코드

#### `tests/unit/test_http_range.py` (신규)
```python
"""Range 헤더 해석 (RFC 9110 §14). 크기 S = 1000 기준 경계 사례 표."""

import pytest

from app.core.http_range import RangeNotSatisfiableError, parse_range

S = 1000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("bytes=0-", (0, S - 1)),
        ("bytes=0-0", (0, 0)),
        ("bytes=100-", (100, S - 1)),
        ("bytes=100-199", (100, 199)),
        ("bytes=999-999", (999, 999)),
        ("bytes=0-99999999", (0, S - 1)),  # 끝이 크기를 넘으면 마지막 바이트로 맞춤
        ("bytes=-10", (S - 10, S - 1)),
        ("bytes=-1000", (0, S - 1)),
        ("bytes=-99999999", (0, S - 1)),  # suffix가 크기보다 크면 전체
        ("BYTES=0-1", (0, 1)),  # 단위 이름은 대소문자 무시
        ("bytes= 0-1 ", (0, 1)),  # 범위 목록 앞뒤 공백(OWS)
        ("bytes=0-" + "9" * 5000, None),  # int 자릿수 한도 초과 → 무효
    ],
)
def test_parse_range(header: str | None, expected: tuple[int, int] | None) -> None:
    assert parse_range(header, S) == expected


@pytest.mark.parametrize(
    "header",
    [
        "bytes=5-2",  # 시작 > 끝
        "bytes=abc",
        "bytes=",
        "bytes=-",
        "bytes=1-2-3",
        "bytes=--5",
        "bytes=+5-",
        "bytes=0-+5",
        "bytes=0 -1",
        "bytes=٥-",  # 비ASCII 숫자
        "items=0-1",  # 모르는 단위 (RFC MUST 무시)
        "bytes 0-1",  # '=' 없음
        "bytes=0-1,5-6",  # 다중 범위
        "bytes=0-1, 5-6",
        "",
    ],
)
def test_invalid_or_multi_range_is_ignored(header: str) -> None:
    assert parse_range(header, S) is None


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=-0"])
def test_unsatisfiable_range_raises_with_size(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError) as exc_info:
        parse_range(header, S)

    assert exc_info.value.size == S


@pytest.mark.parametrize("header", ["bytes=0-", "bytes=-1"])
def test_empty_file_is_unsatisfiable(header: str) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range(header, 0)


def test_no_header_on_empty_file_is_full() -> None:
    assert parse_range(None, 0) is None
```

#### `tests/unit/test_audio_service.py` (신규)
```python
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.http_range import RangeNotSatisfiableError
from app.core.logging import configure_logging
from app.infra.storage import InvalidKeyError, LocalStorage
from app.services.audio_service import AudioService
from tests.audio_fakes import DATA, SIZE, FakeSession

MISSING_KEY = "00000000-0000-4000-8000-000000000000.wav"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "audio")


def _service(storage: LocalStorage, key: str | None) -> AudioService:
    return AudioService(cast(Session, FakeSession(key)), storage)


def _logs(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_full_audio_without_range(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    audio = _service(storage, key).open_audio(7, None)

    with audio.stream:
        assert audio.stream.read() == DATA
    assert (audio.media_type, audio.extension) == ("audio/wav", ".wav")
    assert (audio.size, audio.byte_range, audio.length) == (SIZE, None, SIZE)


def test_range_opens_only_that_part(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    audio = _service(storage, key).open_audio(7, "bytes=100-199")

    with audio.stream:
        assert audio.stream.read() == DATA[100:200]
    assert (audio.byte_range, audio.length) == ((100, 199), 100)


def test_mp3_key_is_audio_mpeg(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".mp3")

    audio = _service(storage, key).open_audio(7, None)
    audio.stream.close()

    assert (audio.media_type, audio.extension) == ("audio/mpeg", ".mp3")


def test_no_record_is_not_found(storage: LocalStorage) -> None:
    with pytest.raises(AppError) as exc_info:
        _service(storage, None).open_audio(7, None)

    assert exc_info.value.code == ErrorCode.NOT_FOUND


def test_missing_file_is_not_found_and_logs_without_key(
    storage: LocalStorage, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")

    with pytest.raises(AppError) as exc_info:
        _service(storage, MISSING_KEY).open_audio(7, None)

    assert exc_info.value.code == ErrorCode.NOT_FOUND
    assert exc_info.value.__suppress_context__  # from None: 키가 든 원인 예외를 끊는다
    (log,) = [line for line in _logs(capsys) if line["event"] == "audio_missing"]
    assert (log["logger"], log["level"], log["call_id"]) == ("app.audio", "warning", 7)
    assert MISSING_KEY not in json.dumps(log)


def test_corrupt_key_propagates(storage: LocalStorage) -> None:
    with pytest.raises(InvalidKeyError):
        _service(storage, "audio/1.wav").open_audio(7, None)


def test_unsatisfiable_range_raises_with_size(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    with pytest.raises(RangeNotSatisfiableError) as exc_info:
        _service(storage, key).open_audio(7, f"bytes={SIZE}-")

    assert exc_info.value.size == SIZE


def test_invalid_range_is_full(storage: LocalStorage) -> None:
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    audio = _service(storage, key).open_audio(7, "bytes=5-2")
    audio.stream.close()

    assert audio.byte_range is None


@pytest.mark.parametrize(
    ("header", "start", "end", "status", "sent"),
    [(None, None, None, 200, SIZE), ("bytes=-10", SIZE - 10, SIZE - 1, 206, 10)],
)
def test_access_log(
    storage: LocalStorage,
    capsys: pytest.CaptureFixture[str],
    header: str | None,
    start: int | None,
    end: int | None,
    status: int,
    sent: int,
) -> None:
    configure_logging("INFO")
    key = storage.save(io.BytesIO(DATA), extension=".wav")

    _service(storage, key).open_audio(7, header).stream.close()

    (log,) = [line for line in _logs(capsys) if line["event"] == "audio_access"]
    assert log["logger"] == "app.audio"
    assert log["level"] == "info"
    assert log["call_id"] == 7
    assert (log["range_start"], log["range_end"]) == (start, end)
    assert (log["status"], log["bytes"]) == (status, sent)
    assert key not in json.dumps(log)
```

#### `tests/unit/test_audio_api.py` (신규)
```python
"""음성 재생 라우터 단위 테스트: 실제 LocalStorage(tmp_path) + 가짜 세션(get_db 오버라이드)."""

import io
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_audio_storage, get_db
from app.core.errors import ErrorCode, error_status
from app.core.logging import configure_logging
from app.infra.storage import ByteRange, LocalStorage
from tests.audio_fakes import DATA, SIZE, FakeSession, ReadRecorder

_ABSENT_KEY = "00000000-0000-4000-8000-000000000000.wav"


@dataclass
class Env:
    app: FastAPI
    client: TestClient
    storage: LocalStorage
    events: list[str] = field(default_factory=list)
    key: str | None = None  # 가짜 세션이 돌려줄 object_key (None = 없는 건)

    def save(self, data: bytes = DATA, extension: str = ".wav") -> str:
        self.key = self.storage.save(io.BytesIO(data), extension=extension)
        return self.key


@pytest.fixture
def env(build_app: Callable[..., FastAPI], tmp_path: Path) -> Iterator[Env]:
    root = tmp_path / "audio"
    app = build_app(audio_storage_root=root)
    env = Env(app, TestClient(app), LocalStorage(root))

    def fake_db() -> Iterator[FakeSession]:
        env.events.append("db_open")
        try:
            yield FakeSession(env.key, env.events)
        finally:
            env.events.append("db_close")

    app.dependency_overrides[get_db] = fake_db
    with env.client:
        yield env


def _url(call_id: int | str = 7) -> str:
    return f"/api/calls/{call_id}/audio"


def _log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------- 200 / 206


def test_full_audio_without_range(env: Env) -> None:
    env.save()

    response = env.client.get(_url())

    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["content-length"] == str(SIZE)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-disposition"] == 'inline; filename="call-7.wav"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-range" not in response.headers
    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [
        ("bytes=0-", 0, SIZE - 1),  # Chrome·Firefox 재생 시작
        ("bytes=0-1", 0, 1),  # Safari 확인 요청
        ("bytes=100-199", 100, 199),
        ("bytes=-10", SIZE - 10, SIZE - 1),
        ("bytes=5000-", 5000, SIZE - 1),  # 탐색(seek)
        ("bytes=0-99999999", 0, SIZE - 1),
    ],
)
def test_single_range_is_partial_content(env: Env, header: str, start: int, end: int) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": header})

    assert response.status_code == 206
    assert response.content == DATA[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{SIZE}"
    assert response.headers["content-length"] == str(end - start + 1)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("header", ["bytes=5-2", "bytes=abc", "items=0-1", "bytes=0-1,5-6"])
def test_invalid_unknown_or_multi_range_is_full(env: Env, header: str) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": header})

    assert response.status_code == 200
    assert response.content == DATA
    assert "content-range" not in response.headers


def test_if_range_makes_range_ignored(env: Env) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": "bytes=0-1", "If-Range": '"abc"'})

    assert response.status_code == 200
    assert response.content == DATA


def test_mp3_is_audio_mpeg(env: Env) -> None:
    env.save(extension=".mp3")

    response = env.client.get(_url())

    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["content-disposition"] == 'inline; filename="call-7.mp3"'


def test_large_file_is_streamed_in_chunks(env: Env) -> None:
    big = bytes(range(256)) * 1024  # 256 KiB = 64 KiB 청크 4개
    env.save(big)

    response = env.client.get(_url(), headers={"Range": "bytes=1-"})

    assert response.status_code == 206
    assert response.content == big[1:]


# ---------------------------------------------------------------- 에러


def test_unsatisfiable_range_is_416_with_content_range(env: Env) -> None:
    env.save()

    response = env.client.get(_url(), headers={"Range": f"bytes={SIZE}-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{SIZE}"
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "code": "RANGE_NOT_SATISFIABLE",
        "message": "요청한 범위를 제공할 수 없습니다.",
        "detail": None,
    }


def test_range_not_satisfiable_code_is_416() -> None:
    assert error_status(ErrorCode.RANGE_NOT_SATISFIABLE) == 416


def test_no_record_is_404(env: Env) -> None:
    response = env.client.get(_url())

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_missing_file_is_404_without_key(env: Env) -> None:
    env.key = _ABSENT_KEY

    response = env.client.get(_url())

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert _ABSENT_KEY not in response.text


def test_corrupt_key_is_500_without_key(env: Env) -> None:
    env.key = "../secret.wav"

    response = env.client.get(_url())

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text


@pytest.mark.parametrize("call_id", [0, "abc", 2**63])
def test_invalid_id_is_422(env: Env, call_id: int | str) -> None:
    response = env.client.get(_url(call_id))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_head_is_not_allowed(env: Env) -> None:
    env.save()

    response = env.client.head(_url())

    assert response.status_code == 405


def test_object_key_is_not_exposed(env: Env) -> None:
    key = env.save()

    response = env.client.get(_url(), headers={"Range": "bytes=0-1"})

    assert key not in str(response.headers)
    assert key.encode() not in response.content


# ---------------------------------------------------------------- 로그


def test_access_logs(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    key = env.save()
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 연결

    env.client.get(_url(), headers={"Range": "bytes=100-199", "X-Request-Id": "rid-audio"})

    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    (audio,) = [line for line in lines if line.get("event") == "audio_access"]
    assert audio["logger"] == "app.audio"
    assert audio["call_id"] == 7
    assert audio["request_id"] == "rid-audio"
    assert (audio["range_start"], audio["range_end"]) == (100, 199)
    assert (audio["status"], audio["bytes"]) == (206, 100)
    (access,) = [line for line in lines if line.get("logger") == "app.access"]
    assert (access["status"], access["call_id"]) == (206, 7)
    # Range 원문·키·클라이언트 주소는 남기지 않는다
    assert "bytes=100-199" not in out
    assert key not in out
    assert "testclient" not in out


def test_rejected_requests_do_not_log_audio_access(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    env.save()
    configure_logging("INFO")
    env.client.get(_url(), headers={"Range": f"bytes={SIZE}-"})  # 416
    env.key = None
    env.client.get(_url())  # 404

    events = [line.get("event") for line in _log_lines(capsys)]

    assert "audio_access" not in events
    assert events.count("request") == 2  # app.access는 상태와 무관하게 남는다


# ---------------------------------------------------------------- 세션 수명


def test_db_session_is_closed_before_streaming(env: Env) -> None:
    env.save(bytes(range(256)) * 1024)  # 청크 4개
    real = env.storage

    class RecordingStorage:
        def size(self, key: str) -> int:
            return real.size(key)

        def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO:
            return cast(BinaryIO, ReadRecorder(real.open(key, byte_range), env.events))

    env.app.dependency_overrides[get_audio_storage] = RecordingStorage

    response = env.client.get(_url())

    assert response.status_code == 200
    assert env.events[:3] == ["db_open", "query", "db_close"]
    assert env.events[3:] and set(env.events[3:]) == {"read"}


# ---------------------------------------------------------------- OpenAPI


def test_openapi_get_call_audio(env: Env) -> None:
    operation = env.app.openapi()["paths"]["/api/calls/{call_id}/audio"]["get"]

    assert operation["operationId"] == "get_call_audio"
    assert operation["tags"] == ["calls"]
    assert set(operation["responses"]) == {"200", "206", "404", "416", "422", "500"}
    for status in ("200", "206"):
        assert set(operation["responses"][status]["content"]) == {"audio/wav", "audio/mpeg"}
    assert operation["responses"]["416"]["description"] == "RANGE_NOT_SATISFIABLE"
```

#### `tests/integration/test_audio_api.py` (신규)
```python
"""음성 재생 통합 테스트: 실제 DB 조회(삭제 제외 조건) + 실제 LocalStorage(tmp_path)."""

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_audio_storage, get_db
from app.core.config import Settings
from app.infra.storage import ByteRange, LocalStorage
from app.main import create_app
from tests.audio_fakes import DATA, SIZE, ReadRecorder
from tests.integration.factories import make_call

pytestmark = pytest.mark.integration


@dataclass
class AudioApi:
    client: TestClient
    storage: LocalStorage
    events: list[str] = field(default_factory=list)

    def save(self) -> str:
        return self.storage.save(io.BytesIO(DATA), extension=".wav")


@pytest.fixture
def audio_api(db_session: Session, tmp_path: Path) -> Iterator[AudioApi]:
    root = tmp_path / "audio"
    app = create_app(Settings(_env_file=None, audio_storage_root=root))
    storage = LocalStorage(root)
    env = AudioApi(TestClient(app), storage)

    def recording_db() -> Iterator[Session]:
        env.events.append("db_open")
        try:
            yield db_session
        finally:
            env.events.append("db_close")

    class RecordingStorage:
        def size(self, key: str) -> int:
            return storage.size(key)

        def open(self, key: str, byte_range: ByteRange | None = None) -> BinaryIO:
            return cast(BinaryIO, ReadRecorder(storage.open(key, byte_range), env.events))

    app.dependency_overrides[get_db] = recording_db
    app.dependency_overrides[get_audio_storage] = RecordingStorage
    with env.client:
        yield env


def test_partial_content_end_to_end(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(db_session, object_key=audio_api.save(), status="STORED")

    response = audio_api.client.get(f"/api/calls/{call.id}/audio", headers={"Range": "bytes=100-"})

    assert response.status_code == 206
    assert response.content == DATA[100:]
    assert response.headers["content-range"] == f"bytes 100-{SIZE - 1}/{SIZE}"
    assert response.headers["content-type"] == "audio/wav"


def test_session_closed_before_first_read(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(db_session, object_key=audio_api.save())

    response = audio_api.client.get(f"/api/calls/{call.id}/audio")

    assert response.status_code == 200
    assert audio_api.events[:2] == ["db_open", "db_close"]
    assert audio_api.events[2:] and set(audio_api.events[2:]) == {"read"}


@pytest.mark.parametrize("status", ["REGISTERED", "FAILED", "RETRY_REQUESTED"])
def test_any_status_is_playable(audio_api: AudioApi, db_session: Session, status: str) -> None:
    call = make_call(db_session, object_key=audio_api.save(), status=status)

    response = audio_api.client.get(f"/api/calls/{call.id}/audio")

    assert response.status_code == 200
    assert response.content == DATA


def test_soft_deleted_call_is_404(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(
        db_session, object_key=audio_api.save(), deleted_at=datetime(2026, 11, 24, tzinfo=UTC)
    )

    response = audio_api.client.get(f"/api/calls/{call.id}/audio")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_unknown_call_is_404(audio_api: AudioApi, db_session: Session) -> None:
    call = make_call(db_session, object_key=audio_api.save())

    response = audio_api.client.get(f"/api/calls/{call.id + 1000}/audio")

    assert response.status_code == 404
```
- 통합 테스트의 세션 오버라이드는 실제 `db_session`을 넘기므로 "세션 객체가 닫혔는지"가 아니라 **`get_db` 정리 시점**을 본다. 운영의 `get_db`는 그 시점에 `with session_factory() as session`을 빠져나와 연결을 풀에 돌려준다.

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 0 | 작업 트리 확인(리서치·계획 문서 외 미커밋 변경 없음) | `git status` |
| 1 | `test_http_range.py`(#1~5) 작성(Red) → `app/core/http_range.py`(Green) | `uv run pytest tests/unit/test_http_range.py` |
| 2 | 기준이 선행 커밋(`app/core/audio_format.py`) 위인지 확인 | `python -c "from app.core.audio_format import CANONICAL_MIME"` (`uv run`) |
| 3 | `tests/audio_fakes.py`, `test_audio_service.py`(#6~14) → `errors.py` 코드 추가, `audio_service.py` | `uv run pytest tests/unit/test_audio_service.py` |
| 4 | `test_audio_api.py`(#15~31) → `api/web/audio.py`, `main.py` | `uv run pytest tests/unit` (이 시점에 `test_committed_openapi_is_up_to_date`만 실패) |
| 5 | #30 회귀 확인: `scope="function"`을 잠시 빼면 실패하는지 본 뒤 되돌림 | 실패 메시지 `['db_open', 'query', 'read']` |
| 6 | `integration/test_audio_api.py`(#32~36) | `uv run pytest tests/integration/test_audio_api.py` (Docker 필요) |
| 7 | `openapi.json` 재생성, diff가 §5.7뿐인지 확인 | `uv run pytest -m "not integration"` 전부 통과 |
| 8 | 공용 문서(§5.9) | 리뷰 |
| 9 | 전체 검증(§8) + 수동 확인(§8.1) | |

---

## 8. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (Docker 없으면 통합 skip, drive는 항상 skip)
uv run pytest -m "not integration"   # 단위만
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
- 기대(사전 검증 시점, `2bde1c6` 기준, Docker 켜짐): **710 → 789 통과**(신규 79), 2 skip(수동 Drive).
- Windows Git Bash에서 testcontainers가 Docker CLI를 못 찾으면 `export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin"`.

### 8.1 수동 확인
- `uv run uvicorn app.main:app` 후 `curl -i -r 0-99 http://localhost:8000/api/calls/{id}/audio` → `206`, `Content-Range: bytes 0-99/<크기>`, `Content-Length: 100`.
- `curl -i -r 999999999- ...` → `416`, `Content-Range: bytes */<크기>`, JSON 본문.
- 브라우저 상세 화면에서 재생·탐색 → 개발자 도구 Network에서 `Range: bytes=0-` → 206, 탐색 시 `bytes=N-` → 206.
- 재생 중 DB 연결 수가 늘지 않는지(`SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction'`가 0).

---

## 9. 확인 필요

### 9.1 A (R-03·R-10·O-05, 공용 파일)
| # | 항목 | 내용 |
|---|---|---|
| A1 | **R-10 공유** | `parse_range`·`RangeNotSatisfiableError`(`app/core/http_range.py`)와 `AudioService`를 R-10이 쓸지. 쓰면 `get_audio_service`를 `deps.py`로 옮기고, 로봇 다운로드도 `audio_access` 대상인지(`architecture.md` §11 "재생·다운로드") 정함 |
| A2 | **O-05 사본 삭제 방식** | 보존 기간 경과 건의 사본만 지우고 레코드를 남기는지, 그때 `object_key` 처리. 현재는 "사본 없음 = 404 + `audio_missing` 경고"(D10) |
| A3 | `app/core/audio_format.py` | 형식 판정·정규 MIME 공용 모듈(선행 커밋). R-04의 매직 바이트 판정(`filetype`)을 이 모듈로 맞출지는 A와 별도 합의(웹 업로드 계획 §9.1 A1) |
| A4 | `errors.py`·`main.py` | 공용 파일에 각 1~2줄. 다른 작업과 병합 시 양쪽 줄 모두 유지 |
| A5 | 감사 로그 보관 | `audio_access`는 stdout(Docker 로그 로테이션)에만 남는다. 장기 보관이 필요하면 DB 테이블(마이그레이션은 A 담당) 또는 별도 수집 |

### 9.2 프론트
| # | 항목 | 내용 |
|---|---|---|
| F1 | 에러 표시 | `<audio>`는 404·416 JSON을 읽지 못하고 `error` 이벤트만 받는다. "음성 없음" 문구가 필요하면 상세 API(W-02)에 `audio_available` 같은 필드 추가 검토 |
| F2 | 목(mock) | 실제 서버는 `bytes=0-`에 206을 준다. 목은 200만 줘서 탐색 동작 차이는 목에서 재현되지 않음(문제는 아님) |
| F3 | `fetch`·Web Audio 전환 시 | `Content-Range`·`Accept-Ranges`를 CORS `expose_headers`에 추가해야 함(현재는 `X-Request-Id`만) |
| F4 | 다운로드 파일명 | 지금은 `call-{id}.wav`. 원래 파일명이 필요하면 `filename*=UTF-8''…`(RFC 8187)로 확장(D9 (c)) |
| F5 | 캐시 | `Cache-Control: private, no-store`라 같은 구간을 다시 들으면 다시 받는다 |

### 9.3 팀 / 관리자
| # | 항목 | 내용 |
|---|---|---|
| T1 | 클라이언트 IP | 이번에는 남기지 않음(D3). 로그인 없는 환경에서 "누가"를 남길 유일한 수단이므로 필요 여부를 개인정보 처리 방침과 함께 결정 |
| T2 | 음성 보존 기간(E-07) | "사본 없음" 빈도가 여기에 달림 |

### 9.4 미확인·가정
| # | 항목 | 내용 |
|---|---|---|
| U1 | 청크 64 KiB | [가정]. 운영 측정 후 조정 가능 |
| U2 | Safari 동작 | `bytes=0-1` 확인 요청 → 206 2바이트는 단위 테스트로 확인. 실제 Safari 재생은 미확인 |

### 9.5 알려진 제한
| # | 항목 | 내용 |
|---|---|---|
| L1 | chunked 본문 GET | `MAX_UPLOAD_MB`를 넘는 chunked 본문을 붙인 GET은 206 헤더 전송 후 끊기고 `app.access` `status=500`(D14). 정상 브라우저 무관 |
| L2 | 스트리밍 중 디스크 오류 | 응답 시작 후라 형식 응답 불가, 연결 중단 + 서버 로그 |
| L3 | 시작 전 끊김 | 응답 본문 제너레이터가 한 번도 시작되지 않으면 스트림은 제너레이터가 해제될 때 닫힌다(CPython 참조 카운트로 즉시) |
| L4 | `audio_access`와 실제 전송 | 로그는 응답 시작 전에 남긴다. 실제로 끝까지 보냈는지는 `app.access`의 `status`·`latency_ms`로 판단 |
| L5 | HEAD | 405. 미디어 요소는 HEAD를 쓰지 않음 |

---

## 10. 구현 시 주의
1. 음성 라우트에서는 `DbSession`(request scope)을 **어떤 의존성에서도** 쓰지 않는다. 하나라도 쓰면 그 세션이 전송 끝까지 열린다.
2. `Content-Length`는 실제 전송 바이트와 정확히 같아야 한다. 파서 반환값(보정된 끝)으로만 계산한다.
3. `storage.open()`까지 엔드포인트 안(응답 시작 전)에서 끝낸다. 그래야 404/416을 형식 응답으로 낸다.
4. 스트림은 `_iter_chunks` 안 `with stream:`으로 닫는다.
5. 라우트는 `def`(동기)로 둔다.
6. `AudioNotFoundError`는 `raise AppError(NOT_FOUND) from None`(메시지에 키가 있음). `InvalidKeyError`·`OSError`는 잡지 않는다(500).
7. 로그·에러 `detail`·응답 헤더에 `object_key`·`Range` 원문·`original_name`·클라이언트 IP를 넣지 않는다.
8. `RangeNotSatisfiableError`를 `AppError`로 바꾸지 않는다. 416 응답의 `Content-Range` 헤더는 라우터가 붙인다.
9. 라우트를 추가·변경하면 `openapi.json`을 재생성해 같은 커밋에 넣는다. 병합 충돌 시 손으로 고치지 말고 재생성한다.
10. 로그 테스트는 앱 생성 후 `configure_logging("INFO")`를 다시 호출한 뒤 `capsys`로 읽는다.

---

## 11. 커밋 분할안

작업 단위 ID(W-06 등)는 커밋 메시지에 넣지 않는다.

| 순서 | 커밋 메시지 | 포함 파일 |
|---|---|---|
| 1 | `docs: 음성 재생 리서치·구현 계획 추가` | `docs/researchs/audio-playback.md`, `docs/plans/audio-playback.md` |
| 2 | `feat: HTTP Range 헤더 파서 공용 모듈 추가 — 단일 바이트 범위·416 판정` | `app/core/http_range.py`, `tests/unit/test_http_range.py` |
| 3 | `feat: 음성 재생 API(GET /api/calls/{id}/audio) 추가 — Range 스트리밍·416·접근 로그` | `app/core/errors.py`, `app/services/audio_service.py`, `app/api/web/audio.py`, `app/main.py`, `docs/api/openapi.json`, `tests/audio_fakes.py`, `tests/unit/{test_audio_service,test_audio_api}.py`, `tests/integration/test_audio_api.py` |
| 4 | `docs: 음성 재생 Range·416 규칙과 AudioStorage 시그니처를 규약·아키텍처 문서에 반영` | `docs/api/convention.md`, `docs/architecture/architecture.md` |

- 형식 판정·정규 MIME 공용 모듈(`app/core/audio_format.py`) 커밋은 이 표에 없다. 별도로 **먼저** cyj에 들어가고 이 작업은 그 위에서 시작한다(§4.2).
- 2는 3의 준비 단계라 리뷰에서 3에 합쳐도 된다. 따로 두면 R-10이 2만 보고 재사용 여부를 판단하기 쉽다.
- 4를 3에 합칠지는 리뷰에서 정한다(규약 문구가 API 동작과 같은 PR에 들어가면 된다).
