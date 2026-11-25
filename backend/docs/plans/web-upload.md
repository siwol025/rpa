# 웹 업로드 상세 구현 계획 — `POST /api/uploads`

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` W-07 웹 업로드 (P1, Phase 2, 선행 C-02·W-08) — 요구: PRD IN-03 |
| 작업 브랜치 | `cyj` (기준 `d9429d5`, W-08 Drive 연동 모듈·W-10 통계 구현 이후) |
| 근거 | `docs/researchs/web-upload.md` v0.1(이하 "리서치"), `plans/drive-inbox.md` §9.4(H1~H7), `api/convention.md` v0.1, `app/**`(`core/config.py`·`core/errors.py`·`core/middleware.py`·`api/deps.py`·`main.py`·`api/web/*.py`·`infra/inbox/*`·`schemas/common.py`), `tests/unit/{conftest,test_calls_api,test_openapi,test_config,test_inbox_local}.py`, `.env.example`, `scripts/export_openapi.py`, `pyproject.toml` |
| 기준 버전 | FastAPI 0.165.0 / Starlette 1.10.0 / python-multipart 0.0.34 / pydantic 2 / structlog (`.venv` 설치본) |
| 사전 검증 | 이 문서의 코드·테스트를 `d9429d5` 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). **단위 기존 259 + 신규 99 = 358 통과**(통합 38건은 Docker 없음으로 skip, 수동 Drive 2건 skip). `ruff check`·`ruff format --check`·`mypy .`(84파일) 통과, `openapi.json` 재생성 후 `test_committed_openapi_is_up_to_date` 통과 |

---

## 1. 목표와 범위

### 1.1 목표
1. 웹 대시보드가 음성 파일(1개 이상)을 `POST /api/uploads`(multipart 필드 `files`)로 올리면, 서버가 **파일명·형식을 검증한 뒤 `InboxWriter`로 클라우드 `inbox/`에 올리고 202**로 접수 결과를 돌려준다.
2. **DB에는 아무것도 쓰지 않는다.** 등록(`call_record` 생성)은 Dispatcher → R-04 단일 경로다(`architecture.md` §8.2, `input_flow.md` §4.3).
3. 하류(Dispatcher·로봇 PC Windows·STT)가 깨지지 않도록 **확장자와 내용(매직 바이트)이 일치하는 wav·mp3만** 받고, 파일명은 원래 이름을 유지하되 정규화(경로 성분 제거·NFC)하고 Windows에서 쓸 수 없는 이름은 거절한다.
4. 응답·에러·로그에 파일명(담당자·고객사 = PII)과 저장소 오류 원인(`reason`·원인 예외)을 노출하지 않는다.

### 1.2 포함
- `app/core/config.py`: `AudioExtension`, `allowed_extensions` 설정(`ALLOWED_EXTENSIONS`)
- `app/schemas/upload.py`(응답 모델), `app/services/upload_service.py`(검증 규칙·서비스), `app/api/web/uploads.py`(라우트)
- `app/api/deps.py`(`get_upload_service`), `app/main.py`(`app.state.settings`, 라우터 등록)
- `.env.example` 주석 1줄, `docs/api/openapi.json` 재생성
- 테스트: 단위만(DB 불필요). 실제 `LocalInboxWriter`(`tmp_path`)를 쓰는 라우터 테스트 포함
- 공용 문서 보완: `convention.md` §3.5 신설, `architecture.md` §8.2·§10.3·§11 각 1줄

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| 업로드 시 메타데이터(담당자·고객사·통화 일시) 입력, 규칙 파일명 생성 | 리서치 D4: 요구 범위 밖. 메타데이터는 Dispatcher가 파일명 규칙으로 추출, 누락은 W-12 보정 |
| 해시 중복 검사 | 같은 파일 재업로드는 Dispatcher 등록 시 `409 DUPLICATE_FILE`로 정리(`input_flow.md` §6.2) |
| m4a 등 추가 형식 | PRD IN-02 [결정 필요]·Dispatcher·STT 변경과 함께. 이번에는 판정 규칙이 있는 wav·mp3만 |
| 파일별 결과(부분 성공 202) | 사용자 확정 D2: 첫 실패에서 중단, 503 |
| 사전 `writer.check()` 호출 | 리서치 §8.3 (c): 요청마다 Drive 호출 1회 추가. O-02(헬스 체크) 몫 |
| R-04 로봇 등록의 형식 검증 | A 담당. 이번 검증 함수를 공유할지는 §9.1 A1 |
| `app/infra/inbox/*` 수정 | W-08 산출물을 사용만 한다 |
| `filetype` 의존성 정리 | 자체 판정 함수를 쓰므로 계속 미사용. 유지 여부는 C-01 소유자 판단(§9.1 A3) |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| 형식 판정 | `app.services.upload_service.detect_audio_format(head: bytes) -> AudioExtension \| None` | R-04 형식 검증(공유 합의 시) |
| 파일명 정규화·검사 | `app.services.upload_service.normalize_filename(raw: str \| None) -> str \| None` | R-04(필요 시) |
| 정규 MIME | `app.services.upload_service.CANONICAL_MIME` | R-04 사본 저장 시 MIME |
| 허용 확장자 | `Settings.allowed_extensions: list[AudioExtension]`, `app.core.config.AudioExtension` | R-04 |
| 앱 설정 접근 | `request.app.state.settings` (`create_app`에 넘긴 `Settings`) | 다른 의존성 함수 |
| 서비스 주입 | `app.api.deps.get_upload_service` | — |

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 항목 | 실제 (`d9429d5`) | 이 계획의 반영 |
|---|---|---|
| inbox 어댑터 | `InboxWriter.write(filename, stream, content_type) -> str`, `check()`, `InboxUnavailableError(reason)` / `create_inbox_writer` → `app.state.inbox_writer` / `deps.get_inbox_writer` → `InboxWriter \| None` | 그대로 사용. `None`이면 503 |
| 로컬 이름 검사 | `validate_local_name`(`""`·`.`·`..`, `\ / : * ? " < > \|`, 코드 < 32 → `ValueError`). `LocalInboxWriter.write`가 먼저 호출 | 서비스의 `normalize_filename`이 **이 함수를 그대로 호출**해 규칙을 맞춘다(H4). 통과한 이름은 로컬 writer에서 `ValueError`(→ 500)가 나지 않음 |
| 에러 코드 | `BAD_REQUEST` 400, `PAYLOAD_TOO_LARGE` 413, `UNSUPPORTED_MEDIA` 415, `VALIDATION_ERROR` 422, `INBOX_UNAVAILABLE` 503 모두 있음 | 새 코드 없음 |
| 크기 제한 | `BodySizeLimitMiddleware`(요청 전체, `MAX_UPLOAD_MB`) | 별도 처리 없음. 413 테스트 1건으로 경로만 확인 |
| 설정 | `ALLOWED_EXTENSIONS`는 `.env.example`에만 있고 `Settings` 필드 없음(`extra="ignore"`로 무시) | 필드 추가. `cors_origins`와 같은 `NoDecode` + `mode="before"` 쉼표 분리 방식 |
| 설정 접근 | 의존성 함수가 설정을 읽을 경로가 없음(`app.state`에는 `session_factory`·`inbox_writer`만). `get_settings()`는 `.env`를 읽어 테스트 앱(`Settings(_env_file=None, …)`)과 어긋남 | `create_app`에서 `app.state.settings = settings`. `get_upload_service`가 `request.app.state.settings`를 읽음 |
| 422 `detail` 형식 | `{"errors": [{"loc", "msg", "type"}]}`. 서비스 422 선례: 통계 `range_too_large`(`msg` 고정 한국어 문구) | 같은 형식으로 `filename_invalid`·`too_many_files` |
| operationId | 라우트 함수 이름, 앱 전체 고유. 테스트 앱의 `/upload` 라우트 함수 이름은 `upload` | 함수 이름 `upload_files`(충돌 없음) |
| 로그 | structlog JSON(stdout, `JSONRenderer` 기본 `ensure_ascii` → 한글은 `\uXXXX`) | 로그 누출 테스트는 **ASCII 파일명**으로 확인(§6.4) |
| multipart 실측 | 빈 파일명: 원시 요청은 `loc ["body","files"]` `missing`, httpx `TestClient`는 텍스트 필드로 보내 `["body","files",0]` `value_error` | 테스트는 `loc[:2] == ["body","files"]`로 단언 |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| D1 | 요청 형식 | `files: Annotated[list[UploadFile], File()]` — multipart 필드 이름 **`files`**, 1개 이상. 1개도 목록으로 받는다 |
| D2 | 부분 실패 | **모든 파일을 먼저 검증** → 순차 업로드 중 **첫 실패에서 중단**, 503 `INBOX_UNAVAILABLE`(`detail: null`). 앞서 올라간 파일은 그대로 둔다(재업로드 중복은 Dispatcher 409로 정리) |
| D4 | 파일명 | 원래 이름 유지 + 정규화: `/`·`\` 기준 **마지막 성분만**, **NFC**. Windows 금지 문자·제어 문자·앞뒤 공백·끝 점·255자 초과는 **치환하지 않고 422**. 규칙은 `validate_local_name`을 호출해 맞춘다 |
| D5 | 허용 형식 | `Settings.allowed_extensions`(env `ALLOWED_EXTENSIONS`, 기본 `wav,mp3`). 값은 판정 규칙이 있는 형식(`AudioExtension = Literal["wav","mp3"]`)만 허용 → **m4a 등은 시작 실패** |
| D6 | 형식 판정 | 확장자(대소문자 무시)와 매직 바이트(자체 함수: WAV = `RIFF`…`WAVE`, MP3 = `ID3` 또는 MPEG Layer III 프레임 동기)가 **일치해야 통과**. 클라이언트 MIME은 거절 근거로 쓰지 않음. Drive에는 정규 MIME(`audio/wav`·`audio/mpeg`) |
| H1 | writer `None` | 서비스 검증보다 **먼저** 503 |
| H2 | `reason` | 응답 `message`·`detail`에 넣지 않음 |
| H3 | 라우트 | `def`(동기). `write`가 블로킹이라 워커 스레드에서 실행 |
| H7 | 예외 로그 | `InboxUnavailableError`를 `exc_info`로 남기지 않고 `reason`만. `AppError`는 `from None`으로 원인 체인 단절 |
| 규약 §3.4 | 입력값 비노출 | 에러 `message`·`detail`·로그에 파일명을 넣지 않음 |

### 3.2 리서치 §14 권장안 채택
| # | 항목 | 결정 |
|---|---|---|
| D3 | 파일 수 상한 | 서비스 검사, **최대 10개**, 넘으면 422 `too_many_files`(`loc: ["body","files"]`) **[가정]**. 최악 응답 시간(10 × 약 3분)을 제한. 파서 기본 한도(1000)는 그대로(넘으면 400) |
| D7 | Drive MIME | 판정 형식의 정규값: `wav` → `audio/wav`, `mp3` → `audio/mpeg` |
| D8 | 확장자 대소문자 | 대소문자 무시로 허용하고 **확장자만 소문자로 바꿔 저장**(`REC.WAV` → `REC.wav`). Dispatcher 필터가 대소문자를 구분해도 안전 |
| D9 | 415 `detail` | `{"index": i}` — 요청의 몇 번째 파일인지(0부터). 이름은 넣지 않음 |
| D10 | disabled 503 위치 | 서비스 검증보다 먼저(H1과 같음) |
| D11 | 경로 성분 | 마지막 성분만 취함(거절하지 않음). 결과 이름은 나머지 검사를 거침 |
| D12 | 금지 문자·공백 | 거절(422). `validate_local_name` 집합 + 앞뒤 공백(유니코드 공백 포함)·끝 점 |
| D13 | 길이 상한 | **255 UTF-16 코드 단위**(NTFS 성분 한도와 같은 단위). 한글은 1자 = 1단위, 이모지는 2단위 **[가정: Drive 상한 미확인]** |
| D14 | 응답 본문 | `{"items": [{"name": "<정규화된 이름>"}]}` (`UploadResponse`). 객체라 이후 필드 추가가 호환 변경 |
| D15 | 빈 파일 | 415(매직 바이트 판정 실패와 같은 경로) |
| D16 | 서비스 입력 타입 | 값 객체 `IncomingFile(filename: str \| None, stream: BinaryIO)`. 서비스는 FastAPI 타입(`UploadFile`)에 의존하지 않고, 라우트가 `UploadFile.filename`·`.file`로 만든다 |
| D17 | 검증 함수 위치 | `app/services/upload_service.py` 모듈 함수(통계의 `bucket_*`처럼 공개 함수). R-04와 공유 합의 시 공용 모듈로 이동(§9.1 A1) |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| 처리 순서 | ① writer `None` → 503 ② 파일 수 > 10 → 422 ③ 파일마다(앞에서부터, 첫 오류에서 중단): 이름 → 422 / 확장자 없음·불허 → 415 / `.wav`처럼 확장자만 있는 이름 → 422 / 매직 바이트 → 415 ④ 전부 통과하면 순차 `write` ⑤ 202 | D2·D10. ③에서 오류가 나면 `write`는 한 번도 호출되지 않음 |
| 서비스 밖에서 먼저 나는 에러 | 413(미들웨어), 400(multipart 파서), 422(`files` 없음·빈 파일명, FastAPI)는 writer가 `None`이어도 먼저 난다 | 본문 파싱·파라미터 검증은 의존성·엔드포인트보다 앞. 요청 자체가 잘못된 경우라 문제없음 |
| 확장자 분리 | `stem, dot, ext = name.rpartition(".")` — `dot` 없으면 415(확장자 없음), `stem` 빈 값(`.wav`)이면 422 `filename_invalid` | `.wav`는 "확장자만 있는 이름"으로 보고 이름 오류로 처리 |
| 매직 바이트 읽기 | `seek(0)` → `read(12)` → `seek(0)` | 12바이트면 WAV·ID3·프레임 동기 판정에 충분. 어댑터도 처음부터 읽지만 의도를 분명히 함 |
| MP3 프레임 동기 | `b0 == 0xFF`, `b1 & 0xE0 == 0xE0`, 버전 비트 `(b1>>3)&3 != 01`(예약값 제외), 레이어 비트 `(b1>>1)&3 == 01`(Layer III) | `FF FB/FA`(MPEG-1), `FF F3/F2`(MPEG-2), `FF E3/E2`(MPEG-2.5) 통과, ADTS AAC(`FF F1/F9`)·Layer I/II 거절 |
| 판정하지 않는 것 | ID3 태그 뒤 내용, 비트레이트·샘플레이트 비트, WAV 코덱, `RF64`/`RIFX` | 실수 방지 수준(리서치 §10). `RF64`는 거절됨(4 GiB 초과용, 한도 100 MiB) |
| `IncomingFile.stream` | `UploadFile.file`(Starlette `SpooledTemporaryFile`, 1 MiB 넘으면 디스크) | `def` 엔드포인트라 동기 파일 객체를 직접 쓴다. 응답 후 FastAPI가 닫음 |
| 응답 이름 | 서비스가 `write`에 넘긴 이름(정규화 + 소문자 확장자). `write()` 반환값(Drive 파일 ID / Local 접미사 이름)은 쓰지 않음 | 백엔드마다 의미가 달라 섞이지 않게(리서치 §7.2) |
| 로그 | 로거 `app.upload`. 성공 `upload_accepted`(info: `files`), 업로드 중단 `upload_aborted`(warning: `reason`, `written`, `files`). 파일명 없음, `exc_info` 없음. 검증 거절은 로그 없음(접근 로그의 상태 코드로 충분) | 어댑터가 `inbox_written`·`inbox_write_failed`를 이미 남김. 서비스는 "몇 개 중 몇 개가 올라갔는지"만 보탬. `request_id`는 자동 바인딩 |
| 422 `msg` | 고정 한국어 문구: `"사용할 수 없는 파일명입니다"`, `"파일은 한 번에 최대 10개까지 올릴 수 있습니다"` | 통계 `range_too_large` 선례. 입력값 미포함 |
| `allowed_extensions` 파싱 | 쉼표 분리, 앞뒤 공백 제거, 소문자화, 앞 점 제거(`".mp3"` → `"mp3"`), 빈 항목 무시. 결과가 빈 목록이면 `min_length=1`로 시작 실패 | 빈 값이면 모든 업로드가 415가 되는 조용한 설정 오류를 막음 |
| `allowed_extensions` 기본값 | `list(get_args(AudioExtension))` = `["wav", "mp3"]` | `default_factory=lambda: ["wav","mp3"]`는 mypy가 `list[str]`로 추론해 `arg-type` 오류(사전 검증 실측) |
| `AudioExtension` 위치 | `app/core/config.py` | 설정 검증에 필요하고 `core`가 `services`를 import하지 않게 하기 위함. 서비스는 `core`에서 가져다 씀 |
| 테스트 공용 가짜 | `tests/unit/upload_fakes.py`(`FakeWriter`, `WAV`, `MP3`). `test_*.py`가 아니라 수집되지 않음 | 서비스·라우터 테스트가 같은 가짜를 씀. 테스트 모듈끼리 import하지 않음 |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준) | 내용 |
|---|---|---|
| 수정 | `app/core/config.py` | `AudioExtension`, `allowed_extensions`, `_split_extensions` |
| 신규 | `app/schemas/upload.py` | `UploadedFile`, `UploadResponse` |
| 신규 | `app/services/upload_service.py` | `MAX_FILES_PER_REQUEST`, `MAX_NAME_LENGTH`, `HEAD_BYTES`, `CANONICAL_MIME`, `IncomingFile`, `normalize_filename`, `detect_audio_format`, `UploadService` |
| 신규 | `app/api/web/uploads.py` | `router`, `upload_files` |
| 수정 | `app/api/deps.py` | `get_upload_service` |
| 수정 | `app/main.py` | `app.state.settings = settings`, `uploads.router` 등록 |
| 수정 | `.env.example` | `ALLOWED_EXTENSIONS` 위 주석 1줄 |
| 재생성 | `docs/api/openapi.json` | `/api/uploads`, `Body_upload_files`, `UploadResponse`, `UploadedFile` |
| 수정 | `tests/unit/test_config.py` | `_ENV_NAMES`에 `ALLOWED_EXTENSIONS`, 기본값·`.env.example` 단언, 신규 6건 |
| 신규 | `tests/unit/upload_fakes.py` | 테스트 공용 가짜 |
| 신규 | `tests/unit/test_upload_rules.py` | 52건 |
| 신규 | `tests/unit/test_upload_service.py` | 23건 |
| 신규 | `tests/unit/test_uploads_api.py` | 18건 |
| 수정 | `docs/api/convention.md` | §3.5 신설 |
| 수정 | `docs/architecture/architecture.md` | §8.2, §10.3, §11 각 1줄 |

- **변경하지 않는 파일**: `app/core/errors.py`, `app/core/middleware.py`, `app/infra/inbox/*`, `app/schemas/common.py`, `pyproject.toml`·`uv.lock`(새 의존성 없음), `tests/unit/conftest.py`, `docs/features/features.md`.

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_config.py` | `_ENV_NAMES`에 `ALLOWED_EXTENSIONS` 추가(개발자 셸 환경 변수 차단). `test_defaults_without_env`·`test_env_example_is_compatible`에 단언 1줄씩 |
| `tests/unit/test_openapi.py` | `test_committed_openapi_is_up_to_date`가 재생성 전까지 실패(의도). `test_every_operation_documents_422_and_500_in_error_format`·`test_operation_ids_are_unique_in_real_app`은 그대로 통과 |
| `tests/unit/test_app_smoke.py` | 변경 없음. 실제 `.env`를 읽으므로 개발자 `.env`의 `ALLOWED_EXTENSIONS`가 `m4a` 등이면 실패하는데, 이는 의도한 설정 오류 |
| `tests/unit/conftest.py` | 변경 없음. `build_app(**overrides)`로 `allowed_extensions`·`inbox_backend` 등을 넘긴다 |
| 통합 테스트 | 변경 없음(DB 미사용) |

---

## 5. 모듈별 코드

### 5.1 `app/core/config.py` (수정)
```python
from typing import Annotated, Literal, Self, get_args   # get_args 추가

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 내용(매직 바이트) 판정 규칙이 있는 음성 형식. 형식을 늘릴 때는 판정 규칙과 함께 추가한다.
AudioExtension = Literal["wav", "mp3"]


class Settings(BaseSettings):
    ...
    drive_inbox_folder_id: str | None = None
    # 웹 업로드 허용 확장자(쉼표 구분, 대소문자·앞 점 무시). 판정 규칙이 없는 값이면 시작 실패.
    allowed_extensions: Annotated[list[AudioExtension], NoDecode] = Field(
        default_factory=lambda: list(get_args(AudioExtension)), min_length=1
    )

    @field_validator("cors_origins", mode="before")
    ...

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _split_extensions(cls, value: object) -> object:
        if isinstance(value, str):
            items = (item.strip().lower().removeprefix(".") for item in value.split(","))
            return [item for item in items if item]
        return value

    @field_validator("log_level", mode="before")
    ...
```
- 필드는 `drive_inbox_folder_id` 다음, 검증 함수는 `_split_comma`와 `_upper_log_level` 사이에 둔다.

### 5.2 `.env.example` (수정)
```dotenv
# 요청 전체 크기 한도(MiB, 1024²바이트). 모든 API 공통, 초과 시 413 PAYLOAD_TOO_LARGE
MAX_UPLOAD_MB=100
# 웹 업로드 허용 확장자(쉼표 구분). 내용 판정 규칙이 있는 wav, mp3만 가능(그 밖의 값은 시작 실패)
ALLOWED_EXTENSIONS=wav,mp3
```

### 5.3 `app/schemas/upload.py` (신규)
```python
"""웹 업로드 API 스키마 (W-07)."""

from pydantic import BaseModel


class UploadedFile(BaseModel):
    name: str  # inbox/에 쓴 이름(정규화 후). Dispatcher 등록 시 목록의 original_name이 된다


class UploadResponse(BaseModel):
    """접수 결과. 202 시점에 파일은 이미 inbox/에 있고, 등록·처리는 이후 Dispatcher가 한다."""

    items: list[UploadedFile]
```

### 5.4 `app/services/upload_service.py` (신규)
```python
"""웹 업로드 유스케이스 (W-07): 파일명·형식 검증 후 inbox/에 쓴다. DB는 쓰지 않는다."""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO

import structlog

from app.core.config import AudioExtension
from app.core.errors import AppError, ErrorCode
from app.infra.inbox import InboxUnavailableError, InboxWriter
from app.infra.inbox.local import validate_local_name
from app.schemas.upload import UploadedFile, UploadResponse

MAX_FILES_PER_REQUEST = 10
MAX_NAME_LENGTH = 255  # NTFS 경로 성분 한도(UTF-16 코드 단위)
HEAD_BYTES = 12  # 매직 바이트 판정에 읽는 앞부분 길이
_TOO_MANY_FILES_MSG = f"파일은 한 번에 최대 {MAX_FILES_PER_REQUEST}개까지 올릴 수 있습니다"

# Drive mimeType으로 넘기는 정규 MIME. 클라이언트가 보낸 Content-Type은 쓰지 않는다.
CANONICAL_MIME: dict[AudioExtension, str] = {"wav": "audio/wav", "mp3": "audio/mpeg"}

_log = structlog.stdlib.get_logger("app.upload")


@dataclass(frozen=True)
class IncomingFile:
    """라우터가 넘기는 업로드 파일 하나. stream은 seek 가능한 원본(UploadFile.file)."""

    filename: str | None
    stream: BinaryIO


@dataclass(frozen=True)
class _CheckedFile:
    name: str
    stream: BinaryIO
    content_type: str


def normalize_filename(raw: str | None) -> str | None:
    """경로 성분을 떼고 NFC로 정규화한다. inbox/·로봇 PC(Windows)에 쓸 수 없는 이름이면 None.

    금지 문자·제어 문자·앞뒤 공백·끝 점·255자 초과는 치환하지 않고 거절한다.
    """
    if not raw:
        return None
    name = unicodedata.normalize("NFC", raw.replace("\\", "/").rsplit("/", 1)[-1])
    try:
        validate_local_name(name)  # "", ".", "..", \ / : * ? " < > |, 제어 문자(< 32)
    except ValueError:
        return None
    if name != name.strip() or name.endswith("."):
        return None
    if len(name.encode("utf-16-le")) // 2 > MAX_NAME_LENGTH:
        return None
    return name


def detect_audio_format(head: bytes) -> AudioExtension | None:
    """앞부분으로 형식을 판정한다. WAV = RIFF…WAVE, MP3 = ID3 태그 또는 Layer III 프레임 동기."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        version = (head[1] >> 3) & 0b11  # 01은 예약값
        layer = (head[1] >> 1) & 0b11  # 01 = Layer III (00이면 ADTS AAC)
        if version != 0b01 and layer == 0b01:
            return "mp3"
    return None


def _filename_error(index: int) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        detail={
            "errors": [
                {
                    "loc": ["body", "files", index],
                    "msg": "사용할 수 없는 파일명입니다",
                    "type": "filename_invalid",
                }
            ]
        },
    )


def _unsupported(index: int) -> AppError:
    return AppError(ErrorCode.UNSUPPORTED_MEDIA, detail={"index": index})


class UploadService:
    def __init__(
        self, writer: InboxWriter | None, allowed_extensions: Sequence[AudioExtension]
    ) -> None:
        self._writer = writer
        self._allowed = frozenset(allowed_extensions)

    def upload(self, files: Sequence[IncomingFile]) -> UploadResponse:
        if self._writer is None:  # INBOX_BACKEND=disabled: 무엇을 올려도 소용없으므로 검증보다 먼저
            raise AppError(ErrorCode.INBOX_UNAVAILABLE)
        if len(files) > MAX_FILES_PER_REQUEST:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                detail={
                    "errors": [
                        {
                            "loc": ["body", "files"],
                            "msg": _TOO_MANY_FILES_MSG,
                            "type": "too_many_files",
                        }
                    ]
                },
            )
        # 전부 검증한 뒤에 올린다: 검증 실패로 일부만 inbox/에 들어가는 일이 없다.
        checked = [self._check(index, file) for index, file in enumerate(files)]
        for written, item in enumerate(checked):
            try:
                self._writer.write(item.name, item.stream, item.content_type)
            except InboxUnavailableError as exc:
                # 원인 예외(__cause__)에 키 경로 등이 있을 수 있어 exc_info 없이 reason만 남긴다.
                _log.warning(
                    "upload_aborted", reason=exc.reason, written=written, files=len(checked)
                )
                raise AppError(ErrorCode.INBOX_UNAVAILABLE) from None
        _log.info("upload_accepted", files=len(checked))
        return UploadResponse(items=[UploadedFile(name=item.name) for item in checked])

    def _check(self, index: int, file: IncomingFile) -> _CheckedFile:
        name = normalize_filename(file.filename)
        if name is None:
            raise _filename_error(index)
        stem, dot, ext = name.rpartition(".")
        if not dot:
            raise _unsupported(index)  # 확장자 없음
        if not stem:
            raise _filename_error(index)  # ".wav"처럼 확장자만 있는 이름
        ext = ext.lower()
        if ext not in self._allowed:
            raise _unsupported(index)
        file.stream.seek(0)
        head = file.stream.read(HEAD_BYTES)
        file.stream.seek(0)
        detected = detect_audio_format(head)
        if detected is None or detected != ext:
            raise _unsupported(index)  # 빈 파일·다른 형식·확장자와 내용 불일치
        return _CheckedFile(f"{stem}.{detected}", file.stream, CANONICAL_MIME[detected])
```
- `detected is None or detected != ext`에서 `is None`을 빼면 mypy가 `CANONICAL_MIME[detected]`의 `None`을 좁히지 못한다. 그대로 둔다.
- `except` 대상은 `InboxUnavailableError`만. 그 밖의 예외(버그, 로컬 writer의 `ValueError` 등)는 그대로 올려 `UnhandledErrorMiddleware` → 500.

### 5.5 `app/api/web/uploads.py` (신규)
```python
"""웹 업로드 API: `POST /api/uploads`."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_upload_service
from app.core.errors import ErrorCode
from app.schemas.common import error_responses
from app.schemas.upload import UploadResponse
from app.services.upload_service import IncomingFile, UploadService

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]


@router.post(
    "",
    status_code=202,
    responses=error_responses(
        ErrorCode.BAD_REQUEST,
        ErrorCode.PAYLOAD_TOO_LARGE,
        ErrorCode.UNSUPPORTED_MEDIA,
        ErrorCode.INBOX_UNAVAILABLE,
    ),
)
def upload_files(
    files: Annotated[list[UploadFile], File()],
    service: UploadServiceDep,
) -> UploadResponse:
    # def(동기): InboxWriter.write는 블로킹(Drive 최악 약 3분)이라 워커 스레드에서 돌린다.
    return service.upload([IncomingFile(file.filename, file.file) for file in files])
```
- `async def`로 바꾸지 않는다(H3). `UploadFile.read()`(async) 대신 `UploadFile.file`(동기)을 쓴다.

### 5.6 `app/api/deps.py` (수정)
```python
from app.core.config import Settings
from app.infra.inbox import InboxWriter
...
from app.services.upload_service import UploadService


def get_inbox_writer(request: Request) -> InboxWriter | None:
    ...  # 기존 그대로


def get_upload_service(
    request: Request,
    writer: Annotated[InboxWriter | None, Depends(get_inbox_writer)],
) -> UploadService:
    settings: Settings = request.app.state.settings
    return UploadService(writer, settings.allowed_extensions)


def get_call_service(session: DbSession) -> CallService:
    ...
```
- DB 세션을 받지 않는다(W-07은 DB를 쓰지 않음).

### 5.7 `app/main.py` (수정)
```python
from app.api.web import calls, stats, uploads
...
    register_exception_handlers(app)
    # 의존성이 요청마다 읽는 설정. get_settings()(.env)가 아니라 create_app에 넘긴 값을 쓴다.
    app.state.settings = settings
    # 엔진 생성만으로는 DB에 연결하지 않는다 ...
    app.state.session_factory = create_session_factory(settings.database_url)
    ...
    app.include_router(calls.router)
    app.include_router(stats.router)
    app.include_router(uploads.router)
```

### 5.8 `docs/api/openapi.json` (재생성)
```bash
cd backend && uv run python -m scripts.export_openapi
```
생성 결과 요점(실측, 기존 대비 추가만 138줄)
- `paths./api/uploads.post`: `operationId` `upload_files`, 태그 `uploads`, `requestBody` `multipart/form-data` → `Body_upload_files`(`files: array of string(contentMediaType application/octet-stream)`, `required: ["files"]`)
- 응답: `202`(`UploadResponse`), `400` BAD_REQUEST, `413` PAYLOAD_TOO_LARGE, `415` UNSUPPORTED_MEDIA, `422`(`ValidationErrorResponse`), `500`, `503` INBOX_UNAVAILABLE — `convention.md` §2.2의 400·413·415·422·503과 일치
- 추가 스키마: `Body_upload_files`, `UploadResponse`(설명 = 클래스 docstring), `UploadedFile`
- 재생성은 구현 마지막에 한 번 하고, diff가 위 추가뿐인지 확인한다.

### 5.9 공용 문서 보완 (중립 표현)

`docs/api/convention.md` — §3.4 뒤에 신설
```markdown
### 3.5 웹 업로드 (`POST /api/uploads`)
- 한 요청에 여러 파일을 보낼 수 있다(multipart 필드 `files`, 최대 10개). 모든 파일을 검증한 뒤 순서대로 올리므로, 4xx 응답이면 어떤 파일도 올라가지 않았다.
- 422 `VALIDATION_ERROR`의 서비스 검증 `type`: `filename_invalid`(`loc: ["body", "files", i]`, 사용할 수 없는 파일명), `too_many_files`(`loc: ["body", "files"]`).
- 415 `UNSUPPORTED_MEDIA`의 `detail`은 `{"index": i}`(요청에서 몇 번째 파일인지, 0부터). 확장자가 허용 목록(`ALLOWED_EXTENSIONS`)에 없거나, 내용이 확장자와 다른 형식이거나, 빈 파일이면 415다.
- 503 `INBOX_UNAVAILABLE`은 업로드 저장소가 꺼져 있거나(`INBOX_BACKEND=disabled`) 업로드 중 실패한 경우다. 업로드 중 실패면 앞 순서의 파일은 이미 올라갔을 수 있다(다시 올리면 등록 단계에서 중복으로 정리된다). `detail`은 `null`.
- 202 본문은 `{"items": [{"name": ...}]}`이고, `name`은 저장된 이름(경로 성분 제거, NFC 정규화, 확장자 소문자)이다.
```

`docs/architecture/architecture.md`
| 위치 | 현재 | 변경 |
|---|---|---|
| §8.2 업로드 규칙 "원래 파일명 유지(…)" 줄 | `원래 파일명 유지(파일명 규칙으로 메타데이터 추출). Drive는 …` | `원래 파일명 유지(파일명 규칙으로 메타데이터 추출, 경로 성분 제거·NFC 정규화·확장자 소문자, Windows에서 쓸 수 없는 이름은 거절). Drive는 …` |
| §10.3 `ALLOWED_EXTENSIONS` 행 | `` `wav,mp3` `` | `` 웹 업로드 허용 확장자(쉼표 구분, 기본 `wav,mp3`). 내용 판정 규칙이 있는 형식만 가능(그 밖의 값은 시작 실패) `` |
| §11 "업로드 파일 (웹·로봇)" 행 | `확장자 + MIME + 매직 바이트 검증, …` | `확장자 + 매직 바이트 검증(둘이 같은 형식이어야 함, 클라이언트 MIME은 판정에 쓰지 않고 판정 형식의 정규 MIME 사용), …` — 로봇(R-04)에도 걸리는 문구라 §9.1 A1 합의 후 반영. 합의 전이면 "(웹 업로드 기준)"을 덧붙인다 |

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 모두 단위 테스트다. DB·네트워크·자격 증명 없이 돈다(W-07은 DB를 쓰지 않으므로 `integration` 마커 불필요).
- 서비스 테스트는 `FakeWriter`(Protocol을 구조적으로 만족, 받은 이름·바이트·MIME 기록, N번째 호출에서 `InboxUnavailableError` 주입)를 쓴다.
- 라우터 테스트는 `build_app(**overrides)`로 앱을 만들고 `app.state.inbox_writer = FakeWriter()`로 교체한다(`get_inbox_writer`가 `app.state`를 읽으므로 `dependency_overrides` 불필요). disabled 경로는 `build_app()` 기본값(`inbox_writer is None`)을 그대로 쓴다.
- 실제 어댑터 경로는 `build_app(inbox_backend="local", inbox_local_path=tmp_path)`로 확인한다(NFC 이름·원본 바이트·1 MiB 넘는 디스크 스풀·같은 이름 접미사).
- 로그 누출 확인은 `configure_logging("INFO")` 후 `capsys`. JSON 로그는 한글을 `\uXXXX`로 내므로 **ASCII 파일명**으로 단언한다.
- 매직 바이트 테스트 데이터는 최소 헤더 바이트로 만든다(실제 음성 파일 불필요).

### 6.2 케이스 목록 (구현 순서)

**1단계 — 설정 (`test_config.py`)** → `config.py`
| # | 테스트 | 기대 |
|---|---|---|
| 1 | `test_defaults_without_env`(단언 추가) | `allowed_extensions == ["wav", "mp3"]` |
| 2 | `test_env_example_is_compatible`(단언 추가) | `.env.example` → `["wav", "mp3"]` |
| 3 | `test_allowed_extensions_parsed_as_comma_list` ×3 | `"wav"` → `["wav"]`, `"WAV, .mp3 ,"` → `["wav","mp3"]`, `"mp3,wav"` → 순서 유지 |
| 4 | `test_allowed_extensions_without_detection_rule_rejected` ×3 | `"wav,m4a"`, `""`, `" , "` → `ValidationError`(D5, 빈 목록 금지) |

**2단계 — 순수 규칙 (`test_upload_rules.py`)** → `normalize_filename`, `detect_audio_format`
| # | 테스트 | 기대 |
|---|---|---|
| 5 | `test_keeps_original_name` | 규칙 파일명 그대로 |
| 6 | `test_nfd_name_becomes_nfc` | NFD → NFC |
| 7 | `test_keeps_only_last_path_component` ×4 | `../../etc/a b.wav` → `a b.wav`, `dir/sub/a.wav`, `C:\Users\x\a.wav`, `..\a.wav` → `a.wav` (D11) |
| 8 | `test_rejects_unusable_name` ×19 | `None`, `""`, `.`, `..`, `dir/`, `a/..`, 금지 문자 `: * ? " < > \|` 7종, `\x00`, `\x1f`, `\t`, 앞 공백, 끝 공백, 끝 점, 끝 전각 공백(`\u3000`) → `None` (D4, D12) |
| 9 | `test_length_limit_is_255_utf16_units` | 한글 251자+`.wav`(255) 통과, 256 거절, 이모지 126개+`.wav`(256단위) 거절 (D13) |
| 10 | `test_accepted_names_pass_local_writer_check` | 통과한 이름은 `validate_local_name`도 통과 (H4) |
| 11 | `test_detects_supported_format` ×9 | WAV 2종, ID3, `FF FB`·`FF FA`·`FF F3`·`FF F2`·`FF E3`·`FF E2` (D6) |
| 12 | `test_rejects_other_content` ×15 | 빈 값, 1바이트 2종, RIFF+AVI, 11바이트 WAV, `RF64`, ADTS `FF F1`·`FF F9`, Layer II `FF FD`, Layer I `FF FF`, 버전 예약 `FF EB`, M4A `ftypM4A`, `OggS`, `fLaC`, `%PDF` |

**3단계 — 서비스 (`test_upload_service.py`)** → `UploadService`
| # | 테스트 | 기대 |
|---|---|---|
| 13 | `test_disabled_writer_is_503_before_validation` | writer `None` + 잘못된 파일(`a.txt`) → 503, `detail None` (H1, D10) |
| 14 | `test_uploads_single_file_with_canonical_mime` | 응답 `{"items":[{"name":…}]}`, writer가 `(이름, 전체 바이트, "audio/mpeg")` 수신 (D7, D14) |
| 15 | `test_uploads_multiple_files_in_order` | 순서대로 기록, wav는 `audio/wav` |
| 16 | `test_upper_case_extension_is_saved_lower_case` | `REC.WAV` → `REC.wav` (D8) |
| 17 | `test_writes_whole_stream_even_after_reading_head` | 읽던 스트림도 처음부터 전달 |
| 18 | `test_too_many_files_is_422` | 11개 → 422 `too_many_files` 본문 전체 일치, `write` 0회 (D3) |
| 19 | `test_max_files_is_allowed` | 10개 통과 |
| 20 | `test_bad_filename_is_422_with_index_and_no_name` ×5 | `None`, `""`, `a:b.mp3`, `a.mp3.`, `.mp3`를 2번째로 → `loc ["body","files",1]` `filename_invalid`, 앞 파일도 `write` 0회 (D2) |
| 21 | `test_unsupported_media_is_415_with_index` ×8 | 확장자 없음, `.m4a`, `.txt`, 빈 파일, mp3↔wav 불일치 2종, AAC, 텍스트 → 415 `{"index": 1}`, `write` 0회 (D6, D9, D15) |
| 22 | `test_allowed_extensions_setting_limits_formats` | `("wav",)`이면 mp3 415, wav 통과 (D5) |
| 23 | `test_write_failure_stops_and_is_503_without_reason` | 3개 중 2번째 실패 → 503 `detail None`, 메시지에 `reason` 없음, `__cause__ None`·`__suppress_context__ True`, `write` 2회(3번째 미시도), 1번째는 기록됨 (D2, H2, H7) |
| 24 | `test_logs_have_no_file_name_or_cause` | `upload_accepted`·`upload_aborted`·`http_503`은 있고, 파일명·원인 예외 문구·`Traceback`은 없음 (H7, 규약 §6) |

**4단계 — 라우터 (`test_uploads_api.py`)** → `uploads.py`, `deps.py`, `main.py`
| # | 테스트 | 기대 |
|---|---|---|
| 25 | `test_upload_returns_202_with_names` | 2개 업로드 202, 본문 이름(`b.WAV` → `b.wav`), writer 기록, `X-Request-Id` 헤더 |
| 26 | `test_client_content_type_is_ignored` | 부분 `Content-Type: text/plain`이어도 202, writer에는 `audio/mpeg` (D6) |
| 27 | `test_nfd_and_path_names_are_normalized` | `../` + NFD 이름 → 응답 이름 NFC |
| 28 | `test_disabled_backend_is_503` | 기본 앱(disabled) → 503 본문 전체 일치 (H1) |
| 29 | `test_write_failure_is_503` | 응답에 `http_503` 없음 (H2) |
| 30 | `test_unsupported_media_is_415` | 415 본문 전체 일치(`detail: {"index": 0}`) |
| 31 | `test_bad_filename_is_422_without_name` | `김상담?.mp3` → 422 `loc ["body","files",0]`, 응답에 이름 없음 (규약 §3.4) |
| 32 | `test_too_many_files_is_422` | 11개 → `too_many_files` |
| 33 | `test_missing_files_is_422` ×3 | 텍스트 필드만, 다른 필드 이름(`file`), 빈 파일명 → 422, `loc[:2] == ["body","files"]` |
| 34 | `test_broken_multipart_is_400` | 경계 없는 multipart → 400 `BAD_REQUEST` |
| 35 | `test_too_large_request_is_413` | `max_upload_mb=1`, 1 MiB 넘는 파일 → 413, `write` 0회 |
| 36 | `test_local_backend_writes_nfc_name_and_bytes` | 실제 `LocalInboxWriter`: 파일이 NFC 이름·원본 바이트로 생김 |
| 37 | `test_local_backend_handles_spooled_large_file` | 2 MiB 넘는 WAV(디스크 스풀) 바이트 일치 |
| 38 | `test_local_backend_same_name_twice_gets_suffix` | `a.mp3`, `a (1).mp3` |
| 39 | `test_allowed_extensions_setting_is_applied` | `build_app(allowed_extensions=["wav"])` → mp3 415, wav 202 (설정 → `app.state.settings` → 의존성 경로) |
| 40 | `test_openapi_upload_files` | operationId·태그, 응답 `{202,400,413,415,422,500,503}`, `requestBody` `multipart/form-data` `files` 배열 필수, 202 `$ref` `UploadResponse` |

**5단계 — OpenAPI 재생성** → `test_committed_openapi_is_up_to_date` 통과

### 6.3 케이스 수
단위 신규 99건: `test_config` +6(기존 2건은 단언 추가), `test_upload_rules` 52, `test_upload_service` 23, `test_uploads_api` 18.

### 6.4 테스트 코드

#### `tests/unit/test_config.py` (수정)
```python
_ENV_NAMES = (
    "MAX_UPLOAD_MB",
    "CORS_ORIGINS",
    "LOG_LEVEL",
    "DOCS_ENABLED",
    "DATABASE_URL",
    "INBOX_BACKEND",
    "INBOX_LOCAL_PATH",
    "DRIVE_INBOX_FOLDER_ID",
    "ALLOWED_EXTENSIONS",
)

# test_defaults_without_env 끝에 추가
    assert settings.allowed_extensions == ["wav", "mp3"]

# test_env_example_is_compatible 끝에 추가
    assert settings.allowed_extensions == ["wav", "mp3"]


# 파일 끝에 추가
@pytest.mark.parametrize(
    ("value", "expected"),
    [("wav", ["wav"]), ("WAV, .mp3 ,", ["wav", "mp3"]), ("mp3,wav", ["mp3", "wav"])],
)
def test_allowed_extensions_parsed_as_comma_list(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: list[str]
) -> None:
    monkeypatch.setenv("ALLOWED_EXTENSIONS", value)

    assert Settings(_env_file=None).allowed_extensions == expected


@pytest.mark.parametrize("value", ["wav,m4a", "", " , "])
def test_allowed_extensions_without_detection_rule_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ALLOWED_EXTENSIONS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

#### `tests/unit/upload_fakes.py` (신규)
```python
"""웹 업로드 테스트 공용: 최소 음성 헤더와 가짜 InboxWriter."""

from typing import BinaryIO

from app.infra.inbox import InboxUnavailableError

WAV = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 20
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 20


class FakeWriter:
    """받은 (이름, 바이트, MIME)을 기록한다. fail_at번째(0부터) 호출에서 InboxUnavailableError."""

    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.written: list[tuple[str, bytes, str]] = []
        self.calls = 0

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        index = self.calls
        self.calls += 1
        if index == self.fail_at:
            raise InboxUnavailableError("http_503") from OSError("secret-key-path")
        stream.seek(0)
        self.written.append((filename, stream.read(), content_type))
        return f"id-{index}"

    def check(self) -> None:
        return None
```

#### `tests/unit/test_upload_rules.py` (신규)
```python
"""웹 업로드 순수 규칙: 파일명 정규화(normalize_filename), 내용 형식 판정(detect_audio_format)."""

import unicodedata

import pytest

from app.infra.inbox.local import validate_local_name
from app.services.upload_service import detect_audio_format, normalize_filename

_NAME = "20261124_101500_김상담_A산업.mp3"

# ---------------------------------------------------------------- 파일명


def test_keeps_original_name() -> None:
    assert normalize_filename(_NAME) == _NAME


def test_nfd_name_becomes_nfc() -> None:
    nfd = unicodedata.normalize("NFD", _NAME)
    assert nfd != _NAME

    assert normalize_filename(nfd) == _NAME


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/a b.wav", "a b.wav"),
        ("dir/sub/a.wav", "a.wav"),
        ("C:\\Users\\x\\a.wav", "a.wav"),
        ("..\\a.wav", "a.wav"),
    ],
)
def test_keeps_only_last_path_component(raw: str, expected: str) -> None:
    assert normalize_filename(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        ".",
        "..",
        "dir/",
        "a/..",
        *(f"a{ch}b.wav" for ch in ':*?"<>|'),
        "a\x00b.wav",
        "a\x1fb.wav",
        "a\tb.wav",
        " a.wav",
        "a.wav ",
        "a.wav.",
        "a.wav\u3000",
    ],
)
def test_rejects_unusable_name(raw: str | None) -> None:
    assert normalize_filename(raw) is None


def test_length_limit_is_255_utf16_units() -> None:
    assert normalize_filename("가" * 251 + ".wav") == "가" * 251 + ".wav"  # 255
    assert normalize_filename("가" * 252 + ".wav") is None  # 256
    assert normalize_filename("😀" * 126 + ".wav") is None  # 252 + 4 = 256 (이모지는 2단위)


def test_accepted_names_pass_local_writer_check() -> None:
    for raw in (_NAME, "../../etc/a b.wav", "C:\\x\\a.wav", unicodedata.normalize("NFD", _NAME)):
        name = normalize_filename(raw)
        assert name is not None
        validate_local_name(name)  # LocalInboxWriter가 ValueError(→ 500)를 내지 않음


# ---------------------------------------------------------------- 형식 판정


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"RIFF\x24\x08\x00\x00WAVEfmt ", "wav"),
        (b"RIFF\x00\x00\x00\x00WAVE", "wav"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00", "mp3"),
        (b"\xff\xfb\x90\x64", "mp3"),  # MPEG-1 Layer III
        (b"\xff\xfa\x90\x64", "mp3"),  # MPEG-1 Layer III, CRC 보호
        (b"\xff\xf3\x90\x64", "mp3"),  # MPEG-2 Layer III
        (b"\xff\xf2\x90\x64", "mp3"),
        (b"\xff\xe3\x90\x64", "mp3"),  # MPEG-2.5 Layer III
        (b"\xff\xe2\x90\x64", "mp3"),
    ],
)
def test_detects_supported_format(head: bytes, expected: str) -> None:
    assert detect_audio_format(head) == expected


@pytest.mark.parametrize(
    "head",
    [
        b"",
        b"R",
        b"\xff",
        b"RIFF\x00\x00\x00\x00AVI ",  # RIFF지만 WAVE 아님
        b"RIFF\x00\x00\x00\x00WAV",  # 11바이트
        b"RF64\x00\x00\x00\x00WAVE",
        b"\xff\xf1\x50\x80",  # ADTS AAC (레이어 00)
        b"\xff\xf9\x50\x80",
        b"\xff\xfd\x90\x64",  # MPEG-1 Layer II
        b"\xff\xff\x90\x64",  # MPEG-1 Layer I
        b"\xff\xeb\x90\x64",  # 버전 예약값(01)
        b"\x00\x00\x00\x20ftypM4A ",  # M4A
        b"OggS\x00\x02",
        b"fLaC\x00\x00",
        b"%PDF-1.7",
    ],
)
def test_rejects_other_content(head: bytes) -> None:
    assert detect_audio_format(head) is None
```

#### `tests/unit/test_upload_service.py` (신규)
```python
"""UploadService — 가짜 InboxWriter로 검증 순서·업로드·실패 변환을 확인한다."""

import io
from typing import Any

import pytest

from app.core.config import AudioExtension
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.services.upload_service import MAX_FILES_PER_REQUEST, IncomingFile, UploadService
from tests.unit.upload_fakes import MP3, WAV, FakeWriter

_NAME = "20261124_101500_김상담_A산업.mp3"


def _service(
    writer: FakeWriter | None, allowed: tuple[AudioExtension, ...] = ("wav", "mp3")
) -> UploadService:
    return UploadService(writer, allowed)


def _file(name: str | None, data: bytes) -> IncomingFile:
    return IncomingFile(name, io.BytesIO(data))


def _raises(code: ErrorCode, fn: Any, *args: Any) -> AppError:
    with pytest.raises(AppError) as info:
        fn(*args)
    assert info.value.code == code
    return info.value


def test_disabled_writer_is_503_before_validation() -> None:
    error = _raises(ErrorCode.INBOX_UNAVAILABLE, _service(None).upload, [_file("a.txt", b"x")])

    assert error.detail is None


def test_uploads_single_file_with_canonical_mime() -> None:
    writer = FakeWriter()

    response = _service(writer).upload([_file(_NAME, MP3)])

    assert response.model_dump() == {"items": [{"name": _NAME}]}
    assert writer.written == [(_NAME, MP3, "audio/mpeg")]


def test_uploads_multiple_files_in_order() -> None:
    writer = FakeWriter()

    response = _service(writer).upload([_file("b.wav", WAV), _file("a.mp3", MP3)])

    assert [item.name for item in response.items] == ["b.wav", "a.mp3"]
    assert writer.written == [("b.wav", WAV, "audio/wav"), ("a.mp3", MP3, "audio/mpeg")]


def test_upper_case_extension_is_saved_lower_case() -> None:
    writer = FakeWriter()

    response = _service(writer).upload([_file("REC.WAV", WAV)])

    assert response.items[0].name == "REC.wav"
    assert writer.written[0][0] == "REC.wav"


def test_writes_whole_stream_even_after_reading_head() -> None:
    writer = FakeWriter()
    stream = io.BytesIO(MP3)
    stream.read(5)

    _service(writer).upload([IncomingFile("a.mp3", stream)])

    assert writer.written[0][1] == MP3


def test_too_many_files_is_422() -> None:
    writer = FakeWriter()
    files = [_file(f"{i}.mp3", MP3) for i in range(MAX_FILES_PER_REQUEST + 1)]

    error = _raises(ErrorCode.VALIDATION_ERROR, _service(writer).upload, files)

    assert error.detail == {
        "errors": [
            {
                "loc": ["body", "files"],
                "msg": "파일은 한 번에 최대 10개까지 올릴 수 있습니다",
                "type": "too_many_files",
            }
        ]
    }
    assert writer.calls == 0


def test_max_files_is_allowed() -> None:
    writer = FakeWriter()
    files = [_file(f"{i}.mp3", MP3) for i in range(MAX_FILES_PER_REQUEST)]

    _service(writer).upload(files)

    assert writer.calls == MAX_FILES_PER_REQUEST


@pytest.mark.parametrize("name", [None, "", "a:b.mp3", "a.mp3.", ".mp3"])
def test_bad_filename_is_422_with_index_and_no_name(name: str | None) -> None:
    writer = FakeWriter()

    error = _raises(
        ErrorCode.VALIDATION_ERROR,
        _service(writer).upload,
        [_file("ok.mp3", MP3), _file(name, MP3)],
    )

    assert error.detail == {
        "errors": [
            {
                "loc": ["body", "files", 1],
                "msg": "사용할 수 없는 파일명입니다",
                "type": "filename_invalid",
            }
        ]
    }
    assert writer.calls == 0  # 앞 파일도 올리지 않음


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a", MP3),  # 확장자 없음
        ("a.m4a", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 8),  # 허용 목록 밖
        ("a.txt", MP3),
        ("a.mp3", b""),  # 빈 파일
        ("a.mp3", WAV),  # 확장자와 내용 불일치
        ("a.wav", MP3),
        ("a.mp3", b"\xff\xf1\x50\x80" + b"\x00" * 8),  # AAC
        ("a.wav", b"hello world, not audio"),
    ],
)
def test_unsupported_media_is_415_with_index(name: str, data: bytes) -> None:
    writer = FakeWriter()

    error = _raises(
        ErrorCode.UNSUPPORTED_MEDIA,
        _service(writer).upload,
        [_file("ok.wav", WAV), _file(name, data)],
    )

    assert error.detail == {"index": 1}
    assert writer.calls == 0


def test_allowed_extensions_setting_limits_formats() -> None:
    writer = FakeWriter()

    _raises(ErrorCode.UNSUPPORTED_MEDIA, _service(writer, ("wav",)).upload, [_file("a.mp3", MP3)])
    _service(writer, ("wav",)).upload([_file("a.wav", WAV)])

    assert [w[0] for w in writer.written] == ["a.wav"]


def test_write_failure_stops_and_is_503_without_reason() -> None:
    writer = FakeWriter(fail_at=1)
    files = [_file("a.mp3", MP3), _file("b.mp3", MP3), _file("c.mp3", MP3)]

    error = _raises(ErrorCode.INBOX_UNAVAILABLE, _service(writer).upload, files)

    assert error.detail is None
    assert "http_503" not in error.message
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert writer.calls == 2  # 실패한 b 이후(c)는 시도하지 않음
    assert [w[0] for w in writer.written] == ["a.mp3"]  # 앞서 올린 파일은 그대로


def test_logs_have_no_file_name_or_cause(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 단다
    name = "leak-check_agent_client.mp3"  # JSON 로그는 한글을 \uXXXX로 내므로 ASCII 이름으로 확인

    _service(FakeWriter()).upload([_file(name, MP3)])
    with pytest.raises(AppError):
        _service(FakeWriter(fail_at=0)).upload([_file(name, MP3)])

    out = capsys.readouterr().out
    assert "upload_accepted" in out
    assert "upload_aborted" in out
    assert "http_503" in out  # reason은 남긴다
    assert "leak-check" not in out
    assert "secret-key-path" not in out
    assert "Traceback" not in out
```

#### `tests/unit/test_uploads_api.py` (신규)
```python
"""`POST /api/uploads` 라우터 — 가짜 writer·실제 LocalInboxWriter로 multipart 경로를 확인한다."""

import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.upload_fakes import MP3, WAV, FakeWriter

_URL = "/api/uploads"
_NAME = "20261124_101500_김상담_A산업.mp3"


def _api(build_app: Callable[..., FastAPI], writer: Any, **overrides: Any) -> TestClient:
    app = build_app(**overrides)
    app.state.inbox_writer = writer
    return TestClient(app)


def _files(*items: tuple[str, bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, data, "application/octet-stream")) for name, data in items]


def test_upload_returns_202_with_names(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()

    response = _api(build_app, writer).post(_URL, files=_files((_NAME, MP3), ("b.WAV", WAV)))

    assert response.status_code == 202
    assert response.json() == {"items": [{"name": _NAME}, {"name": "b.wav"}]}
    assert writer.written == [(_NAME, MP3, "audio/mpeg"), ("b.wav", WAV, "audio/wav")]
    assert response.headers["X-Request-Id"]


def test_client_content_type_is_ignored(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()

    response = _api(build_app, writer).post(_URL, files=[("files", ("a.mp3", MP3, "text/plain"))])

    assert response.status_code == 202
    assert writer.written[0][2] == "audio/mpeg"


def test_nfd_and_path_names_are_normalized(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()
    nfd = "../" + unicodedata.normalize("NFD", _NAME)

    response = _api(build_app, writer).post(_URL, files=_files((nfd, MP3)))

    assert response.json() == {"items": [{"name": _NAME}]}


def test_disabled_backend_is_503(build_app: Callable[..., FastAPI]) -> None:
    response = TestClient(build_app()).post(_URL, files=_files(("a.txt", b"x")))

    assert response.status_code == 503
    assert response.json() == {
        "code": "INBOX_UNAVAILABLE",
        "message": "업로드 저장소를 사용할 수 없습니다.",
        "detail": None,
    }


def test_write_failure_is_503(build_app: Callable[..., FastAPI]) -> None:
    response = _api(build_app, FakeWriter(fail_at=0)).post(_URL, files=_files(("a.mp3", MP3)))

    assert response.status_code == 503
    assert response.json()["detail"] is None
    assert "http_503" not in response.text


def test_unsupported_media_is_415(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()

    response = _api(build_app, writer).post(_URL, files=_files(("a.mp3", WAV)))

    assert response.status_code == 415
    assert response.json() == {
        "code": "UNSUPPORTED_MEDIA",
        "message": "허용되지 않은 파일 형식입니다.",
        "detail": {"index": 0},
    }
    assert writer.calls == 0


def test_bad_filename_is_422_without_name(build_app: Callable[..., FastAPI]) -> None:
    response = _api(build_app, FakeWriter()).post(_URL, files=_files(("김상담?.mp3", MP3)))

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["errors"][0]["loc"] == ["body", "files", 0]
    assert "김상담" not in response.text


def test_too_many_files_is_422(build_app: Callable[..., FastAPI]) -> None:
    files = _files(*((f"{i}.mp3", MP3) for i in range(11)))

    response = _api(build_app, FakeWriter()).post(_URL, files=files)

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["type"] == "too_many_files"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data": {"note": "x"}},  # files 필드 없음 (multipart, 텍스트만)
        {"files": [("file", ("a.mp3", MP3, "audio/mpeg"))]},  # 다른 필드 이름
        {"files": [("files", ("", b"", "application/octet-stream"))]},  # 파일 미선택
    ],
)
def test_missing_files_is_422(build_app: Callable[..., FastAPI], kwargs: dict[str, Any]) -> None:
    response = _api(build_app, FakeWriter()).post(_URL, **kwargs)

    assert response.status_code == 422
    # 필드 없음: ["body", "files"] missing / 빈 파일명(httpx는 텍스트 필드로 보냄): [.., 0]
    assert response.json()["detail"]["errors"][0]["loc"][:2] == ["body", "files"]


def test_broken_multipart_is_400(build_app: Callable[..., FastAPI]) -> None:
    response = _api(build_app, FakeWriter()).post(
        _URL, content=b"garbage", headers={"Content-Type": "multipart/form-data"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "BAD_REQUEST"


def test_too_large_request_is_413(build_app: Callable[..., FastAPI]) -> None:
    writer = FakeWriter()
    big = MP3 + b"\x00" * (1024 * 1024)

    response = _api(build_app, writer, max_upload_mb=1).post(_URL, files=_files(("a.mp3", big)))

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert writer.calls == 0


# ---------------------------------------------------------------- 실제 LocalInboxWriter


def _local_api(build_app: Callable[..., FastAPI], root: Path) -> TestClient:
    return TestClient(build_app(inbox_backend="local", inbox_local_path=root))


def test_local_backend_writes_nfc_name_and_bytes(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    nfd = unicodedata.normalize("NFD", _NAME)

    response = _local_api(build_app, tmp_path).post(_URL, files=_files((nfd, MP3)))

    assert response.status_code == 202
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {_NAME: MP3}


def test_local_backend_handles_spooled_large_file(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    big = WAV + bytes(range(256)) * 8192  # 2 MiB 넘음 → 디스크 임시 파일로 넘어감

    response = _local_api(build_app, tmp_path).post(_URL, files=_files(("big.wav", big)))

    assert response.status_code == 202
    assert (tmp_path / "big.wav").read_bytes() == big


def test_local_backend_same_name_twice_gets_suffix(
    build_app: Callable[..., FastAPI], tmp_path: Path
) -> None:
    client = _local_api(build_app, tmp_path)

    for _ in range(2):
        assert client.post(_URL, files=_files(("a.mp3", MP3))).status_code == 202

    assert sorted(p.name for p in tmp_path.iterdir()) == ["a (1).mp3", "a.mp3"]


def test_allowed_extensions_setting_is_applied(build_app: Callable[..., FastAPI]) -> None:
    client = _api(build_app, FakeWriter(), allowed_extensions=["wav"])

    assert client.post(_URL, files=_files(("a.mp3", MP3))).status_code == 415
    assert client.post(_URL, files=_files(("a.wav", WAV))).status_code == 202


# ---------------------------------------------------------------- OpenAPI


def test_openapi_upload_files(build_app: Callable[..., FastAPI]) -> None:
    spec = build_app().openapi()
    operation = spec["paths"][_URL]["post"]
    body_ref = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    body = spec["components"]["schemas"][body_ref.rsplit("/", 1)[-1]]

    assert operation["operationId"] == "upload_files"
    assert operation["tags"] == ["uploads"]
    assert set(operation["responses"]) == {"202", "400", "413", "415", "422", "500", "503"}
    assert body["required"] == ["files"]
    assert body["properties"]["files"]["type"] == "array"
    ok = operation["responses"]["202"]["content"]["application/json"]["schema"]["$ref"]
    assert ok.endswith("/UploadResponse")
```

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 0 | 작업 트리 확인(리서치·계획 문서 외 미커밋 변경 없음) | `git status` |
| 1 | §6.2 #1~4 작성(Red) → `config.py` 필드·검증, `.env.example` 주석(Green) | `uv run pytest tests/unit/test_config.py` |
| 2 | `upload_fakes.py`, #5~12 작성 → `schemas/upload.py`, `upload_service.py`의 상수·`normalize_filename`·`detect_audio_format` | `uv run pytest tests/unit/test_upload_rules.py` |
| 3 | #13~24 작성 → `IncomingFile`, `UploadService` | `uv run pytest tests/unit/test_upload_service.py` |
| 4 | #25~40 작성 → `api/web/uploads.py`, `deps.get_upload_service`, `main.py`(`app.state.settings`, 라우터 등록) | `uv run pytest tests/unit` (이 시점에 `test_committed_openapi_is_up_to_date`만 실패) |
| 5 | `openapi.json` 재생성, diff가 §5.8 추가뿐인지 확인 | `uv run pytest -m "not integration"` 전부 통과 |
| 6 | 공용 문서(§5.9) | 리뷰 |
| 7 | 전체 검증(§8) | |

---

## 8. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (DB 없으면 통합 skip, drive는 항상 skip)
uv run pytest -m "not integration"   # 단위만
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
- 기대(사전 검증 시점, `d9429d5` 기준): 단위 259 → **358 통과**(신규 99), 통합 38건은 Docker/`TEST_DATABASE_URL` 유무에 따라 통과 또는 skip, 수동 Drive 2 skip.

---

## 9. 확인 필요

### 9.1 A (C-01·C-02 공용 파일, R-04)
| # | 항목 | 내용 |
|---|---|---|
| A1 | **형식 검증 공유** | R-04도 "확장자 + 매직 바이트" 검증이 필요하다. `detect_audio_format`·`normalize_filename`·`CANONICAL_MIME`을 그대로 쓸지, 공용 모듈(예: `app/core/audio_format.py`)로 옮길지 합의. 합의되면 이동 + `architecture.md` §11 문구 반영(§5.9) |
| A2 | `ALLOWED_EXTENSIONS` 공유 | R-04가 같은 설정(`Settings.allowed_extensions`)을 쓰는지 |
| A3 | `filetype` 의존성 | 자체 판정을 쓰므로 계속 미사용(`pyproject.toml` 직접 의존성·mypy override 유지). 제거 여부는 C-01 소유자 판단 |
| A4 | `app.state.settings` | `main.py`(공용)에 한 줄 추가. 의존성 함수가 설정을 읽는 공통 경로로 써도 되는지 |
| A5 | 임시 디렉터리 | 업로드 요청 하나가 임시 디스크를 최대 약 `MAX_UPLOAD_MB` 쓴다. 컨테이너 임시 디렉터리 용량·non-root 쓰기 가능 여부(O-01) |

### 9.2 프론트 (②)
| # | 항목 | 내용 |
|---|---|---|
| F1 | 필드·전송 방식 | 필드 이름 `files` 확정. 초안처럼 파일마다 요청 1개도, 한 요청에 최대 10개도 가능 |
| F2 | 응답 본문 | 202 `{"items": [{"name}]}`. 초안 목(mock)은 빈 본문이지만 본문을 읽지 않으므로 호환. `name`은 저장된 이름(NFC, 확장자 소문자) |
| F3 | 에러 표시 | 415 `detail.index`, 422 `type`(`filename_invalid`·`too_many_files`)와 `loc[2]`(파일 인덱스). 503 문구는 disabled·저장소 장애 공통 |
| F4 | 확장자 대소문자 | `.WAV` 허용, 저장 시 `.wav`로 바뀜 |
| F5 | 크기 경계 | 프론트는 파일 크기, 서버는 요청 전체 바이트 → 100 MiB에 아주 가까운 파일은 413 가능 |
| F6 | 사전 검사 | 서버가 거절하는 이름(`: * ? " < > \|`, 앞뒤 공백, 끝 점, 255자 초과)을 프론트에서도 미리 알려 줄지 |

### 9.3 RPA (④, Dispatcher)
| # | 항목 | 내용 |
|---|---|---|
| X1 | `properties.source=web` | W-08 §9.2 X1 그대로(미합의) |
| X2 | MIME | Drive `mimeType`은 `audio/wav`·`audio/mpeg`로 고정. Dispatcher 필터가 확장자·MIME 중 무엇을 보는지 |
| X3 | 파일명 | NFC 정규화, 확장자 소문자화, Windows 금지 문자·끝 점/공백·255자 거절이 로봇 PC 다운로드·파일명 규칙 파싱과 맞는지 |
| X5 | `original_name` | Dispatcher가 등록 시 보내는 파일명 = `inbox/` 파일 이름(= 202 응답 `name`)인지 |

### 9.4 ③ STT
| # | 항목 | 내용 |
|---|---|---|
| S1 | 형식·코덱 | m4a 등 추가 형식 여부(PRD IN-02 [결정 필요]), WAV 코덱(PCM 외) 지원 범위, 확장자로 형식을 정하는지 |

### 9.5 미확인·가정
| # | 항목 | 내용 |
|---|---|---|
| U1 | 파일 수 상한 10 | [가정]. 프론트가 한 번에 여러 개를 보내기로 바꾸면 재검토 |
| U2 | Drive 이름 길이 상한 | 공식 문서에서 찾지 못함. NTFS 255 단위로 제한 |
| U3 | 브라우저 퍼센트 인코딩 | 브라우저가 파일명의 `"`를 `%22`로 보내면 `%22`가 그대로 이름이 된다(되돌리지 않음) [확인 필요: 브라우저별] |

### 9.6 알려진 제한
| # | 항목 | 내용 |
|---|---|---|
| L1 | 판정 깊이 | ID3 태그 뒤 내용이 정말 MP3인지 확인하지 않는다. 앞에 0 패딩·잡음이 있는 MP3, `RF64`·`RIFX` WAV는 거절된다 |
| L2 | Windows 예약 이름 | `CON`, `NUL`, `COM1` 등은 거절하지 않는다(녹취 파일명일 가능성 낮음 [가정]). DEL(0x7F)도 허용(Windows에서 사용 가능) |
| L3 | 끊긴 요청 | 동기 엔드포인트는 클라이언트 연결 끊김을 감지하지 못해, 프론트 타임아웃 후에도 업로드를 끝까지 진행한다(재업로드 중복은 Dispatcher 409로 정리) |
| L4 | 부분 업로드 정보 | 업로드 중 실패 시 몇 개가 올라갔는지는 응답에 없고 로그(`upload_aborted.written`)에만 있다. 다중 파일 클라이언트가 생기면 `detail: {"accepted": k}`(개수만) 호환 추가 검토 |

---

## 10. 구현 시 주의
1. 라우트는 `def`로 둔다. `async def`에서 `writer.write()`를 부르면 이벤트 루프가 최대 수 분 막힌다(H3).
2. **모든 파일 검증이 끝난 뒤** 업로드한다. 검증 루프 안에서 `write`를 부르지 않는다.
3. `InboxUnavailableError`는 `raise AppError(ErrorCode.INBOX_UNAVAILABLE) from None`. 로그는 `reason`만, `exc_info`·`_log.exception` 금지(H7). `reason`을 `message`·`detail`에 넣지 않는다(H2).
4. 422 `msg`·415 `detail`·로그에 파일명을 넣지 않는다(규약 §3.4.3). 위치는 인덱스로만 알린다.
5. 클라이언트 `UploadFile.content_type`은 읽지 않는다. writer에는 `CANONICAL_MIME` 값을 넘긴다.
6. 파일명 검사는 `validate_local_name`을 호출해 로컬 writer 규칙과 어긋나지 않게 한다. 규칙을 복사해 따로 두지 않는다(H4).
7. 매직 바이트를 읽은 뒤 `seek(0)`.
8. 서비스에 DB 세션을 주입하지 않는다.
9. `except`는 `InboxUnavailableError`만 잡는다. `Exception`을 잡으면 버그가 503으로 숨는다.
10. 라우트를 추가·변경하면 `openapi.json`을 재생성해 같은 커밋에 넣는다(`convention.md` §7-1). 함수 이름 `upload_files`는 앱 전체에서 고유해야 한다.

---

## 11. 커밋 분할안

작업 단위 ID(W-07 등)는 커밋 메시지에 넣지 않는다.

| 순서 | 커밋 메시지 | 포함 파일 |
|---|---|---|
| 1 | `docs: 웹 업로드 리서치·구현 계획 추가` | `docs/researchs/web-upload.md`, `docs/plans/web-upload.md` |
| 2 | `feat: 웹 업로드 API(POST /api/uploads) 추가 — 파일명·형식 검증 후 inbox 업로드` | `app/core/config.py`, `.env.example`, `app/schemas/upload.py`, `app/services/upload_service.py`, `app/api/web/uploads.py`, `app/api/deps.py`, `app/main.py`, `docs/api/openapi.json`, `tests/unit/{test_config,upload_fakes,test_upload_rules,test_upload_service,test_uploads_api}.py` |
| 3 | `docs: 웹 업로드 에러 규칙·허용 확장자 설정을 규약·아키텍처 문서에 반영` | `docs/api/convention.md`, `docs/architecture/architecture.md` |

- 허용 확장자 설정(`allowed_extensions`)은 웹 업로드에서만 쓰므로 2번에 함께 넣는다. 리뷰에서 R-04 공유(§9.1 A2)가 먼저 정해지면 설정만 별도 커밋(`feat: 업로드 허용 확장자 설정(ALLOWED_EXTENSIONS) 추가`)으로 앞에 뺄 수 있다.
- 3번을 2번에 합칠지는 리뷰에서 정한다(규약 문구가 API 동작과 같은 PR에 들어가면 된다).
