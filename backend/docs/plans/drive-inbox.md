# Drive 연동 모듈 상세 구현 계획 — `InboxWriter` (`DriveInboxWriter` / `LocalInboxWriter`)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-08 Drive 연동 모듈 (사용처: W-07 웹 업로드, O-02 헬스 체크) |
| 작업 브랜치 | `cyj` (기준 `ad131f6`, W-10 통계 작업이 작업 트리에 있는 상태) |
| 근거 | `docs/researchs/drive-inbox.md` v0.1(이하 "리서치"), `architecture.md` v0.3 §3·§8.2·§10·§11·§12·§13, `docs/input_flow.md` v0.2 §4.3, `features.md` W-07·W-08·O-02·E-01, `research.md` §2.3·§2.4·§7, `app/core/{config,errors,logging}.py`, `app/main.py`, `app/api/deps.py`, `app/infra/inbox/`, `.env.example`, `deploy/docker-compose.dev.yml`, `pyproject.toml`, `tests/unit/{conftest,test_config,test_app_smoke}.py`, `tests/integration/conftest.py`, `scripts/export_openapi.py` |
| 기준 버전 | google-api-python-client 2.202.0 / google-auth 2.63.1 / google-auth-httplib2 0.4.4 / httplib2 0.32.1 / pydantic-settings(설치본) / FastAPI 0.165.0 |
| 사전 검증 | 이 문서의 코드·테스트를 작업 트리 스크래치 복사본에 그대로 넣어 확인함(레포 코드는 수정하지 않음). `pytest` 기존 227(단위 198 + 통합 29) + 신규 단위 52 = **279 통과, 수동 Drive 2 skip**(리뷰 반영 후 신규 61, 288 통과). `ruff check`·`ruff format --check`·`mypy .`(74파일) 통과. `uv lock --offline`으로 `uv.lock` 갱신 시 버전 변경 없이 직접 의존성 2줄만 추가됨 확인. `build("drive","v3")` 1회 약 2 ms(네트워크 없음) |

---

## 1. 목표와 범위

### 1.1 목표
1. 웹 업로드 파일을 입력 폴더 `inbox/`에 쓰는 어댑터 `InboxWriter`와 구현체 두 개(`DriveInboxWriter`, 개발용 `LocalInboxWriter`)를 제공한다.
2. 재시도(지수 백오프 2회)와 실패 분류를 어댑터 안에서 끝내고, 호출자에게는 전용 예외 `InboxUnavailableError` 하나만 보낸다. HTTP 503 변환은 W-07 서비스가 한다.
3. O-02가 쓸 **가벼운 접근 확인 함수**(`check()`, 파일을 만들지 않음)를 제공한다.
4. 설정(`INBOX_BACKEND` 등)과 앱 주입(`app.state.inbox_writer`, `get_inbox_writer`)까지 연결해 W-07이 바로 쓸 수 있게 한다.
5. E-01(서비스 계정·공유 드라이브 권한) 승인 전에 끝낼 수 있는 범위만 구현한다. 실제 Drive 확인은 `drive` 마커 수동 테스트로 남긴다.

### 1.2 포함
- `app/infra/inbox/{base,local,drive,__init__}.py`
- `app/core/config.py` 필드 3개와 검증 1개, `app/api/deps.py` `get_inbox_writer`, `app/main.py` 주입 2줄
- `pyproject.toml`: 직접 의존성 2개, mypy override 2개, pytest 마커 `drive` / `uv.lock` 갱신
- `.env.example` 주석 1줄, `README.md` 수동 Drive 테스트 안내
- 테스트: 단위 4파일(신규 3 + `test_config.py` 수정), 수동 `tests/drive/test_drive_inbox.py`
- 공용 문서 수정: 출처 표시를 `appProperties` → 공개 `properties`로(D1), `supportsAllDrives` 확인 결과 반영, `InboxWriter.check()` 추가, 서비스 계정 역할 표현 통일(§5.11)

### 1.3 제외
| 항목 | 이유 / 담당 |
|---|---|
| `POST /api/uploads` 라우트·`UploadService`, 형식 검증, 파일명 NFC 정규화, 부분 실패 정책 | W-07. 이 모듈은 받은 이름·형식을 그대로 쓴다 |
| `GET /health`, `check()` 결과 캐시·응답 노출 형식 | O-02 |
| `AppError(INBOX_UNAVAILABLE)` 변환 | W-07 서비스(D4). 변환 예시만 §1.4에 둔다 |
| 503 `Retry-After` 헤더 | 요청 없음(D10) |
| 실제 Drive 실측(스코프·역할·`properties` 가시성·미완료 업로드 비노출) | E-01 이후 수동 테스트(§9.3) |
| `docs/api/openapi.json` | 라우트가 없어 변하지 않는다 |
| `deploy/docker-compose.dev.yml` | 이미 `INBOX_BACKEND=local`, `INBOX_LOCAL_PATH=/data/inbox`, `./dev-data/inbox` 볼륨이 있어 변경 없음 |

### 1.4 다른 기능이 사용할 공개 인터페이스
| 용도 | 인터페이스 | 사용 예 |
|---|---|---|
| 어댑터 타입 | `app.infra.inbox.InboxWriter` (Protocol: `write(filename, stream, content_type) -> str`, `check() -> None`) | W-07 서비스 생성자 인자, 테스트 가짜 구현 |
| 실패 예외 | `app.infra.inbox.InboxUnavailableError` (`reason: str`) | W-07: `AppError(INBOX_UNAVAILABLE)`로 변환 / O-02: 비정상 + `reason` |
| 주입 | `app.api.deps.get_inbox_writer` → `InboxWriter \| None` (`None` = `INBOX_BACKEND=disabled`) | W-07·O-02 라우트 의존성. 테스트는 `app.state.inbox_writer = Fake()` 또는 `dependency_overrides` |
| 생성 | `app.infra.inbox.create_inbox_writer(settings)` | `create_app`이 호출. 외부 호출·디스크 쓰기 없음 |
| 로컬 파일명 검사 | `app.infra.inbox.local.validate_local_name(name)` (`ValueError`) | 필요하면 W-07이 같은 규칙을 재사용 |
| 반환값 | Drive: 생성된 파일 ID(Dispatcher가 `source_ref`로 보내는 값과 같음) / Local: 실제 저장된 파일명(충돌 시 접미사 포함) | W-07 응답·로그 |

W-07 서비스에서의 변환 예시(참고, W-07 계획에서 확정):
```python
try:
    file_id = writer.write(name, upload.file, content_type)
except InboxUnavailableError as exc:
    raise AppError(ErrorCode.INBOX_UNAVAILABLE) from exc  # message·detail에 reason을 넣지 않는다
```
- `writer is None`(disabled)도 W-07이 같은 503으로 응답한다(D8).
- `LocalInboxWriter.write`의 `ValueError`(경로 탈출·금지 문자)는 W-07 검증에서 먼저 막는 것이 원칙이다. 막지 못하면 500이 된다.

---

## 2. 현재 코드 확인 (리서치 이후 사실 확인)

| 항목 | 확인 결과 | 이 계획의 반영 |
|---|---|---|
| `app/infra/inbox/` | 빈 `__init__.py`만 있음 | `base.py`·`local.py`·`drive.py` 신규, `__init__.py`에 생성 함수 |
| `Settings` | inbox 필드 없음, `extra="ignore"`라 `.env`의 `INBOX_*`가 무시되는 중 | 필드 3개 추가(§5.1) |
| `.env.example` | `INBOX_BACKEND=local`, `INBOX_LOCAL_PATH=./data/inbox`, 주석 `DRIVE_INBOX_FOLDER_ID`·`GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/drive-sa.json` | 값은 그대로, 필수 조건 주석 1줄 |
| `backend/.env` | 작성 시점 없음 | `test_app_smoke`는 코드 기본값으로 동작 |
| `ErrorCode.INBOX_UNAVAILABLE` | 503 "업로드 저장소를 사용할 수 없습니다." | 변경 없음. W-07이 사용 |
| `main.py`·`deps.py` | W-10 작업으로 `stats` 라우터·`get_stats_service`가 작업 트리에 추가된 상태 | 이 계획은 **추가 줄만** 적는다. W-10 변경이 먼저 커밋된 뒤 적용 |
| mypy override | `googleapiclient.*`, `google.oauth2.*`만 | `google.auth`는 `py.typed`가 있어 불필요. `httplib2`(`import-untyped`), `google_auth_httplib2`(py.typed 없음)는 **실행해 보니 필요**(§5.8) |
| `HttpRequest` 백오프 | `self._sleep = time.sleep`을 요청 생성 시 잡음 | 테스트는 `monkeypatch.setattr("googleapiclient.http.time.sleep", ...)`로 대기 제거(요청 생성 전에 패치) |
| resumable PUT 본문 | `MediaIoBaseUpload.has_stream()`이 참이면 본문은 원본 스트림 조각(`_StreamSlice`) | 테스트는 `.read()`로 꺼내 비교. 파일 전체를 메모리에 올리지 않음 |
| `.gitignore` | `*service-account*.json`, `*-sa.json`, `secrets/`, `.env` 포함 | 키 파일 보호는 이미 됨 |

---

## 3. 결정 사항

### 3.1 사용자 확정
| # | 항목 | 결정 |
|---|---|---|
| D1 | `source=web` 기록 필드 | **공개 `properties`**(`{"source": "web"}`). `appProperties`는 요청한 앱 전용이라 Dispatcher가 못 읽을 수 있다. RPA 합의 필요(§9.2 X1), 공용 문서 문구 수정은 이번 구현 범위(§5.11) |
| D4 | 503 변환 위치 | 어댑터는 `InboxUnavailableError`만 던지고 W-07 서비스가 `AppError(INBOX_UNAVAILABLE)`로 변환 |
| D7 | 시작 시 오류 처리 | **설정 누락(`drive`인데 폴더 ID 없음)만 시작 실패.** 키 파일 없음·인증·네트워크 오류는 런타임에 `InboxUnavailableError`(→ 503, 헬스 비정상). 자격 증명은 첫 호출 때 읽는다. 로봇 API는 Drive 상태와 무관하게 뜬다 |
| 범위 | E-01 전 | 인터페이스·`LocalInboxWriter`·`DriveInboxWriter`(`HttpMockSequence` 단위 테스트)·설정·DI. 실연동은 `drive` 마커 수동 테스트 |

### 3.2 리서치 §10 권장안 채택
| # | 항목 | 결정 |
|---|---|---|
| D2 | 스코프 | 모듈 상수 `DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)`로 시작. E-01 후 수동 테스트에서 기존 `inbox/`에 대한 `files.get`·업로드가 404면 `.../auth/drive`로 **상수 한 줄 변경** + 공유 드라이브(또는 `inbox/` 폴더) **기여자** 역할. 설정 항목으로 빼지 않는다(최소안) |
| D3 | 자격 증명 | `google.auth.default(scopes=DRIVE_SCOPES)`(ADC). `GOOGLE_APPLICATION_CREDENTIALS`는 google-auth가 직접 읽으므로 **`Settings` 필드를 두지 않는다.** Phase 3 Workload Identity와 코드 변경 없이 호환 |
| D5 | 업로드 방식 | resumable, 청크 크기 라이브러리 기본(100 MiB). `MAX_UPLOAD_MB=100` 안에서는 정상 시 세션 POST 1회 + PUT 1회(PUT 실패 후 재시도 때는 상태 조회 PUT `Content-Range: bytes */N`이 1회 더 붙음). multipart는 재시도 중복 위험으로 쓰지 않음 |
| D6 | 타임아웃 | 업로드 30초, `check()` 5초(소켓 무응답 기준) **[가정, E-01 후 조정]** |
| D8 | `disabled` | `create_inbox_writer`가 `None` 반환. 사용처가 503(W-07) / `"disabled"` 표시(O-02) |
| D9 | 직접 의존성 | `google-auth-httplib2`, `httplib2`를 `pyproject.toml`에 명시(직접 import). C-01 공용 파일이라 §9.1 A1 |
| D10 | `Retry-After` | 넣지 않음 |
| D11 | 로컬 충돌·금지 문자 | 충돌은 ` (n)` 접미사, 금지 문자·경로 탈출은 `ValueError`로 거부 |
| D12 | 로그 파일명 | 기록하지 않음. Drive 파일 ID·크기·`request_id`(자동 바인딩)로 추적 |
| D13 | 수동 테스트 마커 | 새 마커 `drive`, `TEST_DRIVE_FOLDER_ID`가 없으면 skip(기존 `integration`과 섞지 않음) |
| D14 | 파일명 NFC 정규화 | W-07 서비스. 어댑터는 받은 이름 그대로 |
| D15 | `check()` 결과 | 예외 방식 + `reason` 분류 문자열만 제공. 캐시·응답 노출은 O-02 |

### 3.3 구현 세부 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| `InboxWriter` | `typing.Protocol`, `write` + `check` | `architecture.md` §8.2 원안에 `check()` 추가(W-08 요구 "헬스 체크용 접근 확인 함수"). 구현체는 상속하지 않고 구조적 타입으로 맞춤 |
| `InboxUnavailableError.reason` | `http_<상태>` / 예외 클래스 이름 / `not_folder`·`trashed`·`cannot_add_children`·`not_writable` | O-02가 원인을 구분할 최소 정보. 파일명·폴더 ID·키 경로·`str(HttpError)`(URI 포함)는 넣지 않음 |
| 잡는 예외 | `HttpError`(`ResumableUploadError` 포함), `GoogleAuthError`(`DefaultCredentialsError`·`RefreshError`·`TransportError`), `httplib2.HttpLib2Error`, `OSError`(소켓 타임아웃·연결 오류·SSL) | 그 밖(`KeyError` 등 버그)은 그대로 올려 `UnhandledErrorMiddleware` → 500 |
| 재시도 | 바깥 루프에서 `request.next_chunk(num_retries=0)`을 직접 재시도(`_upload`). 시도 간 `random.random() * 2**attempt`초 대기, 업로드 전체에서 최대 2회 | 5xx·429·403 `rateLimitExceeded`/`userRateLimitExceeded`·`OSError`·`httplib2.HttpLib2Error`만 재시도, 400·401(갱신 후)·403 권한·404·인증 오류는 즉시 실패(판정은 private `_should_retry_response`에 기대지 않고 직접 구현). 라이브러리 내장 재시도(`execute(num_retries=2)`)는 PUT 재시도 때 이미 읽은 `_StreamSlice`를 되감지 않아 **빈 본문**을 보내고 PUT 중 소켓 오류는 재시도하지 않아(리뷰 실측) 쓰지 않는다. 오류 뒤 다시 부르면 라이브러리가 `_in_error_state`로 상태 조회(`Content-Range: bytes */N`) 후 받은 위치부터 새 조각으로 재전송하고, 세션 POST 실패면 POST부터 다시 한다 |
| `check()` 재시도 | `num_retries=0` | 헬스 체크는 빠르게 |
| `check()` 판정 | `files.get(fields="id,mimeType,trashed,capabilities/canAddChildren", supportsAllDrives=True)` → 폴더이고 휴지통이 아니며 `canAddChildren`이 참 | 리서치 §3.7. 읽기 1회, 파일 생성 없음 |
| Http 생성 | 호출마다 `AuthorizedHttp(credentials, http=httplib2.Http(timeout=…))` + `build(..., cache_discovery=False)` | httplib2는 스레드 안전하지 않음. `build`는 동봉 discovery 문서로 약 2 ms |
| 자격 증명 캐시 | `_ServiceAccountHttp` 인스턴스 필드에 첫 성공 시 저장. 실패는 저장하지 않아 다음 호출에서 다시 시도 | D7. 키 파일을 나중에 넣어도 재시작 없이 회복. 스레드 경합 시 두 번 읽을 수 있으나 결과가 같음 |
| 테스트 주입점 | `DriveInboxWriter(folder_id, *, http_factory=None)` — `Callable[[float], httplib2.Http]` | `HttpMockSequence`를 넘기면 자격 증명·네트워크 없이 요청 형태·재시도 검증 |
| 로그 | 로거 `app.inbox`. 성공 `inbox_written`(info: `backend`, Drive는 `file_id`, `size_bytes`), 실패 `inbox_write_failed`/`inbox_check_failed`(warning: `backend`, `reason`, Drive는 `drive_reason` = `error_details[0].reason`) | D12. `check()` 판정 실패(폴더 아님 등)는 로그 없이 예외만(O-02가 기록) |
| `googleapiclient` 로거 레벨 | 바꾸지 않음(`logging.py` 미수정) | 재시도 경고는 운영에 유용하고, 업로드 URI에는 폴더 ID·세션 URI가 없음. `check()`는 재시도하지 않아 경고가 나지 않음. 소음이 문제되면 O-02에서 재검토 |
| `LocalInboxWriter` 디렉터리 | `write`·`check`에서 `mkdir(parents=True, exist_ok=True)`. 생성자·`create_app`은 디스크를 건드리지 않음 | D7(시작 시 I/O 없음), 개발 편의 |
| 로컬 쓰기 순서 | 이름 검사 → `.{uuid}.part`에 복사 → 비어 있는 최종 이름 탐색 → `os.replace` | 반쯤 쓴 파일이 `.wav/.mp3`로 보이지 않음. 존재 확인과 `replace` 사이 경쟁은 개발용이라 허용 **[가정]** |
| 로컬 금지 문자 | `\ / : * ? " < > \|`, 제어 문자(코드 < 32), 이름 `""`·`.`·`..` | 경로 탈출과 Windows 개발 PC 금지 문자. Windows 예약 이름(`CON` 등)은 다루지 않음(개발용) |
| `stream` 위치 | Local은 `seek(0)` 후 복사, Drive는 `MediaIoBaseUpload`가 오프셋 0부터 읽음 | 호출자가 매직 바이트를 읽고 되감지 않아도 전체가 올라감(테스트로 고정) |
| 설정 기본값 | `inbox_backend="disabled"` | `.env` 없는 테스트·`export_openapi`(`Settings(_env_file=None)`)가 외부 의존 없이 동작. `.env.example`·개발 compose는 `local` |
| 폴더 ID 빈 문자열 | `DRIVE_INBOX_FOLDER_ID=`(빈 값)도 누락으로 봄 | `.env`에서 값만 지운 경우 |

---

## 4. 파일별 변경 목록

| 구분 | 경로 (`backend/` 기준, 문서 1건은 레포 루트) | 내용 |
|---|---|---|
| 신규 | `app/infra/inbox/base.py` | `InboxUnavailableError`, `InboxWriter` |
| 신규 | `app/infra/inbox/local.py` | `validate_local_name`, `LocalInboxWriter` |
| 신규 | `app/infra/inbox/drive.py` | `DRIVE_SCOPES`, `SOURCE_PROPERTY`, `HttpFactory`, `DriveInboxWriter` |
| 수정 | `app/infra/inbox/__init__.py` | `create_inbox_writer`, 재노출 |
| 수정 | `app/core/config.py` | `inbox_backend`, `inbox_local_path`, `drive_inbox_folder_id`, `_require_drive_folder` |
| 수정 | `app/api/deps.py` | `get_inbox_writer` |
| 수정 | `app/main.py` | `app.state.inbox_writer = create_inbox_writer(settings)` |
| 수정 | `pyproject.toml` | 의존성 `google-auth-httplib2`·`httplib2`, mypy override `google_auth_httplib2.*`·`httplib2.*`, 마커 `drive` |
| 수정 | `uv.lock` | `uv lock` 재생성(버전 변경 없음) |
| 수정 | `.env.example` | 주석 1줄 |
| 수정 | `README.md` | 수동 Drive 테스트 안내 |
| 수정 | `tests/unit/test_config.py` | `_ENV_NAMES` 3개, 기본값·`.env.example` 단언, 새 케이스 4개 함수(5건) |
| 신규 | `tests/unit/test_inbox_local.py` | 21건 |
| 신규 | `tests/unit/test_inbox_drive.py` | 29건 |
| 신규 | `tests/unit/test_inbox_factory.py` | 6건 |
| 신규 | `tests/drive/__init__.py`, `tests/drive/test_drive_inbox.py` | 수동 2건(기본 skip) |
| 수정 | `docs/architecture/architecture.md` | §5 시퀀스, §8.2, §11 (§5.11) |
| 수정 | `docs/features/features.md` | W-07 설명 |
| 수정 | `docs/researchs/research.md` | §2.3 표, §7 위험 표 |
| 수정 | `../docs/input_flow.md` (레포 루트, 전 파트 공용) | §4.3 서버 인증·출처 표시 |

- **변경하지 않는 파일**: `app/core/errors.py`(코드 이미 있음), `app/core/logging.py`, `app/core/middleware.py`, `docs/api/convention.md`·`openapi.json`(라우트 없음), `deploy/docker-compose.dev.yml`, W-10 통계 파일.

### 4.1 기존 테스트 영향
| 파일 | 영향 |
|---|---|
| `tests/unit/test_config.py` | `_ENV_NAMES`에 `INBOX_BACKEND`·`INBOX_LOCAL_PATH`·`DRIVE_INBOX_FOLDER_ID` 추가(개발자 셸 환경 변수 차단). `test_defaults_without_env`·`test_env_example_is_compatible`에 단언 추가 |
| `tests/unit/test_app_smoke.py` | **변경 없음.** `create_app()`이 실제 `.env`를 읽지만 자격 증명을 시작 시 읽지 않으므로 `.env`가 `drive`여도(폴더 ID가 있으면) 통과. `drive`인데 폴더 ID가 없는 `.env`면 실패하는데, 이는 의도한 설정 오류 |
| `tests/unit/conftest.py`(`build_app`) | 변경 없음. `Settings(_env_file=None, **overrides)`라 기본 `disabled` → `inbox_writer is None` |
| `tests/unit/test_openapi.py`, `scripts/export_openapi.py` | 변경 없음(라우트 없음, 기본 `disabled`) |
| 통합 테스트 | 변경 없음 |

---

## 5. 모듈별 코드

> 아래 코드는 스크래치 복사본에서 `ruff check`·`ruff format --check`·`mypy .`(strict)와 전체 테스트를 통과한 그대로다.

### 5.1 `app/core/config.py` (수정)
import 2줄과 필드·검증만 바뀐다.
```python
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    ...
    database_url: str = "postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter"
    # 웹 업로드 대상. 기본 disabled라 .env 없는 테스트·OpenAPI 내보내기는 외부 의존이 없다.
    # 키 파일 경로(GOOGLE_APPLICATION_CREDENTIALS)는 google-auth가 직접 읽는다.
    inbox_backend: Literal["drive", "local", "disabled"] = "disabled"
    inbox_local_path: Path = Path("./data/inbox")
    drive_inbox_folder_id: str | None = None

    # (_split_comma, _upper_log_level 그대로)

    @model_validator(mode="after")
    def _require_drive_folder(self) -> Self:
        # 설정 누락만 시작을 막는다. 키·인증·네트워크 오류는 업로드·헬스 체크 때 드러난다.
        if self.inbox_backend == "drive" and not self.drive_inbox_folder_id:
            raise ValueError("INBOX_BACKEND=drive 이면 DRIVE_INBOX_FOLDER_ID가 필요합니다")
        return self

    @property
    def max_upload_bytes(self) -> int: ...
```

### 5.2 `app/infra/inbox/base.py` (신규)
```python
"""웹 업로드 파일을 입력 폴더 inbox/에 쓰는 어댑터 인터페이스 (architecture.md §8.2)."""

from typing import BinaryIO, Protocol


class InboxUnavailableError(Exception):
    """inbox/에 쓸 수 없다 (재시도 소진, 인증·권한·설정 문제, 로컬 I/O 오류).

    `reason`은 로그·헬스 체크용 짧은 분류 값이다(예: `http_404`, `RefreshError`, `trashed`).
    파일명·폴더 ID·키 경로·서비스 계정 정보는 넣지 않는다.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class InboxWriter(Protocol):
    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        """파일 하나를 inbox/에 쓰고 식별자(Drive 파일 ID / 로컬은 저장된 파일명)를 반환한다.

        stream은 seek 가능해야 하며 처음부터 끝까지 쓴다. 실패하면 InboxUnavailableError.
        """
        ...

    def check(self) -> None:
        """inbox/에 쓸 수 있는지 파일을 만들지 않고 확인한다. 불가하면 InboxUnavailableError."""
        ...
```

### 5.3 `app/infra/inbox/local.py` (신규)
```python
"""개발·테스트용 로컬 폴더 inbox (input_flow.md §4.4). 운영 입력 경로로 쓰지 않는다."""

import itertools
import os
import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import structlog

from app.infra.inbox.base import InboxUnavailableError

_log = structlog.stdlib.get_logger("app.inbox")

# Windows에서도 만들 수 없는 문자. 경로 구분자(/ \)와 드라이브 구분자(:)를 포함한다.
_FORBIDDEN_CHARS = frozenset('\\/:*?"<>|')


def validate_local_name(filename: str) -> None:
    """로컬 파일명으로 쓸 수 없으면 ValueError (경로 탈출·금지 문자·제어 문자)."""
    if filename in ("", ".", ".."):
        raise ValueError("파일명이 비어 있거나 경로입니다")
    if any(ch in _FORBIDDEN_CHARS or ord(ch) < 32 for ch in filename):
        raise ValueError("파일명에 사용할 수 없는 문자가 있습니다")


def _with_suffix(name: str, n: int) -> str:
    """`a.mp3` → `a (1).mp3`. 확장자가 없으면 끝에 붙인다."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return f"{name} ({n})"
    return f"{stem} ({n}).{ext}"


class LocalInboxWriter:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        # content_type은 로컬에서 쓰지 않는다(메타데이터 저장 없음). 파일명 검사는 W-07이 먼저 한다.
        validate_local_name(filename)
        tmp = self._root / f".{uuid4().hex}.part"  # .wav/.mp3가 아니라 로컬 Dispatcher가 집지 않음
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            stream.seek(0)
            with tmp.open("xb") as out:
                shutil.copyfileobj(stream, out)
                # replace 뒤에는 다른 프로세스가 파일을 옮겼을 수 있어 여기서 잰다.
                size = out.tell()
            final = self._root / filename
            for n in itertools.count(1):
                if not final.exists():
                    break
                final = self._root / _with_suffix(filename, n)
            # 존재 확인과 replace 사이 경쟁은 개발용이라 허용한다.
            os.replace(tmp, final)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            _log.warning("inbox_write_failed", backend="local", reason=type(exc).__name__)
            raise InboxUnavailableError(type(exc).__name__) from exc
        except BaseException:
            tmp.unlink(missing_ok=True)  # 버그 등 예상 밖 예외도 반쯤 쓴 파일을 남기지 않는다
            raise
        _log.info("inbox_written", backend="local", size_bytes=size)
        return final.name

    def check(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InboxUnavailableError(type(exc).__name__) from exc
        if not os.access(self._root, os.W_OK):
            raise InboxUnavailableError("not_writable")
```

### 5.4 `app/infra/inbox/drive.py` (신규)
```python
"""Google Drive 공유 드라이브 inbox/ 업로드 (서비스 계정, Drive API v3)."""

import random
import time
from collections.abc import Callable
from typing import Any, BinaryIO, NoReturn

import google.auth
import httplib2
import structlog
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from app.infra.inbox.base import InboxUnavailableError

_log = structlog.stdlib.get_logger("app.inbox")

# drive.file로 기존 inbox/ 폴더에 쓸 수 있는지는 E-01 이후 실측한다. 안 되면 drive로 바꾼다.
DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)
# Dispatcher가 source_type=WEB 판정에 쓰는 공개 속성 (모든 앱이 읽을 수 있는 properties).
SOURCE_PROPERTY = {"source": "web"}

_RETRIES = 2  # 지수 백오프 재시도 횟수 (architecture.md §8.2)
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
_UPLOAD_TIMEOUT_SEC = 30.0  # 소켓 무응답 한도. 라이브러리 기본 60초는 재시도와 겹치면 너무 길다
_CHECK_TIMEOUT_SEC = 5.0
_FOLDER_MIME = "application/vnd.google-apps.folder"
_CHECK_FIELDS = "id,mimeType,trashed,capabilities/canAddChildren"

# 요청 타임아웃(초) → 새 Http. httplib2는 스레드 안전하지 않아 호출마다 새로 만든다.
HttpFactory = Callable[[float], httplib2.Http]

# 라이브러리·인증·네트워크 오류. 그 밖의 예외(버그)는 그대로 올려 500이 되게 한다.
_DRIVE_ERRORS = (HttpError, GoogleAuthError, httplib2.HttpLib2Error, OSError)


class _ServiceAccountHttp:
    """ADC(GOOGLE_APPLICATION_CREDENTIALS 또는 GCP 메타데이터)로 인증된 Http를 만든다.

    자격 증명은 첫 호출 때 읽는다: 키 파일 문제로 앱 시작이 막히지 않게 한다.
    """

    def __init__(self) -> None:
        self._credentials: Credentials | None = None

    def __call__(self, timeout: float) -> httplib2.Http:
        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=DRIVE_SCOPES)
        return AuthorizedHttp(self._credentials, http=httplib2.Http(timeout=timeout))


def _reason(exc: Exception) -> str:
    # HttpError 원문(str)·uri에는 폴더 ID·업로드 세션 URI가 들어갈 수 있어 상태 코드만 쓴다.
    if isinstance(exc, HttpError):
        return f"http_{exc.status_code}"
    return type(exc).__name__


def _drive_reason(exc: Exception) -> str | None:
    if isinstance(exc, HttpError) and exc.error_details:
        detail = exc.error_details[0]
        if isinstance(detail, dict):
            value = detail.get("reason")
            return str(value) if value is not None else None
    return None


def _is_retryable(exc: Exception) -> bool:
    # 5xx·429·403 rate limit·네트워크 오류만 재시도. 권한·404·400·인증 오류는 즉시 실패.
    if isinstance(exc, HttpError):
        status = exc.status_code
        return bool(
            status >= 500
            or status == 429
            or (status == 403 and _drive_reason(exc) in _RATE_LIMIT_REASONS)
        )
    return isinstance(exc, OSError | httplib2.HttpLib2Error)


def _upload(request: Any) -> Any:
    """resumable 업로드를 끝까지 진행한다. 실패한 단계는 지수 백오프로 최대 _RETRIES회 재시도한다.

    라이브러리 내장 재시도(execute(num_retries=...))는 PUT 재시도 때 이미 읽은 스트림 조각을
    되감지 않아 빈 본문을 보내고, PUT 중 소켓 오류는 재시도하지 않는다. 그래서 next_chunk를
    한 번씩 직접 다시 부른다: 오류 뒤 다시 부르면 서버가 받은 위치를 조회
    (Content-Range: bytes */N)한 뒤 그 위치부터 새 조각으로 재전송한다.
    세션 POST 실패도 같은 루프에서 POST부터 다시 한다.
    """
    attempt = 0
    while True:
        try:
            _, response = request.next_chunk(num_retries=0)
        except (HttpError, httplib2.HttpLib2Error, OSError) as exc:
            if attempt >= _RETRIES or not _is_retryable(exc):
                raise
            attempt += 1
            time.sleep(random.random() * 2**attempt)
            continue
        if response is not None:
            return response


class DriveInboxWriter:
    def __init__(self, folder_id: str, *, http_factory: HttpFactory | None = None) -> None:
        self._folder_id = folder_id
        self._http_factory: HttpFactory = http_factory or _ServiceAccountHttp()

    def _service(self, timeout: float) -> Any:
        # 동봉된 discovery 문서를 쓰므로 네트워크 호출이 없다.
        return build("drive", "v3", http=self._http_factory(timeout), cache_discovery=False)

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        body = {"name": filename, "parents": [self._folder_id], "properties": SOURCE_PROPERTY}
        try:
            media = MediaIoBaseUpload(stream, mimetype=content_type, resumable=True)
            request = (
                self._service(_UPLOAD_TIMEOUT_SEC)
                .files()
                .create(body=body, media_body=media, fields="id", supportsAllDrives=True)
            )
            response = _upload(request)
        except _DRIVE_ERRORS as exc:
            self._fail("inbox_write_failed", exc)
        file_id = str(response["id"])
        _log.info("inbox_written", backend="drive", file_id=file_id, size_bytes=media.size())
        return file_id

    def check(self) -> None:
        try:
            meta = (
                self._service(_CHECK_TIMEOUT_SEC)
                .files()
                .get(fileId=self._folder_id, fields=_CHECK_FIELDS, supportsAllDrives=True)
                .execute(num_retries=0)
            )
        except _DRIVE_ERRORS as exc:
            self._fail("inbox_check_failed", exc)
        if meta.get("mimeType") != _FOLDER_MIME:
            raise InboxUnavailableError("not_folder")
        if meta.get("trashed"):
            raise InboxUnavailableError("trashed")
        if not meta.get("capabilities", {}).get("canAddChildren"):
            raise InboxUnavailableError("cannot_add_children")

    def _fail(self, event: str, exc: Exception) -> NoReturn:
        reason = _reason(exc)
        _log.warning(event, backend="drive", reason=reason, drive_reason=_drive_reason(exc))
        raise InboxUnavailableError(reason) from exc
```
- `_fail`은 `NoReturn`이라 mypy가 `except` 뒤 `response`·`meta`를 항상 정의된 것으로 본다.
- `httplib2`·`google_auth_httplib2`는 mypy에서 `Any`로 취급된다(override). `HttpError.status_code`·`error_details`도 `Any`.

### 5.5 `app/infra/inbox/__init__.py` (수정)
```python
"""웹 업로드 대상 inbox/ 어댑터. 설정(INBOX_BACKEND)에 따라 구현체를 고른다."""

from app.core.config import Settings
from app.infra.inbox.base import InboxUnavailableError, InboxWriter
from app.infra.inbox.drive import DriveInboxWriter
from app.infra.inbox.local import LocalInboxWriter

__all__ = ["InboxUnavailableError", "InboxWriter", "create_inbox_writer"]


def create_inbox_writer(settings: Settings) -> InboxWriter | None:
    """disabled면 None (사용처가 503 / 헬스 체크 "disabled"). 외부 호출·파일 생성은 하지 않는다."""
    match settings.inbox_backend:
        case "drive":
            assert settings.drive_inbox_folder_id  # Settings 검증에서 보장
            return DriveInboxWriter(settings.drive_inbox_folder_id)
        case "local":
            return LocalInboxWriter(settings.inbox_local_path)
        case "disabled":
            return None
```
- `match`가 `Literal` 세 값을 모두 다루므로 mypy strict(`warn_unreachable`)가 누락 반환을 지적하지 않는다(실행 확인).

### 5.6 `app/api/deps.py` (수정)
모듈 docstring을 `"""라우터 공용 의존성: DB 세션, 서비스·어댑터 주입."""`으로 바꾸고 아래를 추가한다(`DbSession` 정의 뒤).
```python
from app.infra.inbox import InboxWriter


def get_inbox_writer(request: Request) -> InboxWriter | None:
    """None이면 웹 업로드 비활성(INBOX_BACKEND=disabled)."""
    writer: InboxWriter | None = request.app.state.inbox_writer
    return writer
```

### 5.7 `app/main.py` (수정)
```python
from app.core.middleware import (
    ...
)
from app.infra.inbox import create_inbox_writer   # 추가 (isort 순서: app.core.* 다음)
from app.schemas.common import error_responses

...
    app.state.session_factory = create_session_factory(settings.database_url)
    # 키 파일·Drive 접근은 첫 업로드·헬스 체크 때 확인한다 (Drive 문제로 시작이 막히지 않음).
    app.state.inbox_writer = create_inbox_writer(settings)
    app.include_router(calls.router)
    ...
```

### 5.8 `pyproject.toml` (수정, C-01 공용 파일 — §9.1 A1)
```toml
dependencies = [
  ...
  "google-api-python-client",
  "google-auth",
  "google-auth-httplib2",
  "httplib2",
  ...
]

[[tool.mypy.overrides]]
module = ["googleapiclient.*", "google.oauth2.*", "google_auth_httplib2.*", "httplib2.*", "openpyxl.*", "filetype.*", "testcontainers.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
markers = [
  "integration: 실제 PostgreSQL(testcontainers)이 필요한 테스트",
  "drive: 실제 Google Drive(테스트용 공유 드라이브 폴더)가 필요한 수동 테스트",
]
```
- override를 빼고 실행하면 `httplib2`는 `import-untyped`(stub 없음), `google_auth_httplib2`는 "missing library stubs or py.typed marker"로 실패한다(실측). `google.auth.*`는 `py.typed`가 있어 추가하지 않는다.
- 이어서 `uv lock`(→ `uv.lock`의 프로젝트 의존성 목록 2곳에 두 줄씩 추가, 버전 변경 없음)과 `uv sync`(이미 설치돼 있어 변경 없음).

### 5.9 `.env.example` (수정)
```dotenv
# --- 웹 업로드 대상 (drive | local | disabled) ---
# drive 이면 DRIVE_INBOX_FOLDER_ID 필수(없으면 시작 실패). 키 파일은 GOOGLE_APPLICATION_CREDENTIALS 로 지정
INBOX_BACKEND=local
INBOX_LOCAL_PATH=./data/inbox
# DRIVE_INBOX_FOLDER_ID=
# GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/drive-sa.json
```

### 5.10 `README.md` (수정, "검사" 절 통합 테스트 안내 뒤)
```markdown
수동 Drive 테스트(`drive` 마커)는 `TEST_DRIVE_FOLDER_ID`가 없으면 skip된다. E-01 이후 테스트용 공유 드라이브 폴더로 실행한다(운영 `inbox/` 금지, 올린 파일은 직접 정리).

    GOOGLE_APPLICATION_CREDENTIALS=<키 경로> TEST_DRIVE_FOLDER_ID=<폴더 ID> uv run pytest -m drive
```

### 5.11 공용 문서 수정 (D1 등, 구현 범위)
모두 중립 표현으로 쓴다. 레포 루트 `docs/input_flow.md`는 전 파트 공용 문서라 RPA 합의(§9.2 X1)와 같은 PR에서 알린다.

| 문서 | 위치 | 현재 | 변경 |
|---|---|---|---|
| `architecture.md` | §5 시퀀스(167행) | `A->>I: Drive API 업로드 (appProperties.source=web)` | `A->>I: Drive API 업로드 (properties.source=web)` |
| `architecture.md` | §8.2 Protocol | `write(...)`만 | `def check(self) -> None: ...  # 파일 생성 없이 쓰기 가능 여부 확인 (헬스 체크)` 추가, 실패는 `InboxUnavailableError`라는 문장 1줄 |
| `architecture.md` | §8.2 444행 | `supportsAllDrives=true` **[확인 필요]** | `[확인 필요]` 삭제(공식 문서로 확인: 공유 드라이브 항목을 다루는 호출에 필수) |
| `architecture.md` | §8.2 446행 | `appProperties.source=web` 기록 | `공개 파일 속성 properties.source=web 기록(appProperties는 요청한 앱만 읽을 수 있어 Dispatcher가 읽지 못할 수 있음)` |
| `architecture.md` | §8.2 448행 | 실패 시 2회 재시도 후 503 | 뒤에 "(어댑터는 `InboxUnavailableError`, 서비스가 503으로 변환)" |
| `architecture.md` | §11 539행 | 공유 드라이브 최소 권한(업로드 가능한 최소 역할) **[확인 필요]** | "공유 드라이브(또는 `inbox/` 폴더) **기여자** 역할 **[확인 필요: E-01]**" |
| `features.md` | W-07(84행) | `(appProperties.source=web)` | `(properties.source=web)` |
| `research.md` | §2.3 표(84행) | 업로드 시 `appProperties.source=web` 기록 | `properties.source=web` 기록. 같은 칸의 공유 드라이브 **[확인 필요]**는 삭제(서비스 계정은 저장 용량이 없어 공유 드라이브 필수 — 공식 문서) |
| `research.md` | §7 위험 표(319행) | 공유 드라이브 "기여자" 등 **[확인 필요]** | 유지(E-01 후 확정) — 변경 없음 |
| `../docs/input_flow.md` | §4.3 서버 인증(124행) | "콘텐츠 관리자" 이하 권한 | "기여자" 권한(파일 추가만, 이동·삭제 불가) **[확인 필요]** |
| `../docs/input_flow.md` | §4.3 출처 표시(126행) | Drive 파일 속성(`appProperties`)에 `source=web` | Drive 공개 파일 속성(`properties`)에 `source=web` — Dispatcher는 파일 메타데이터의 `properties.source`로 판정 |

---

## 6. 테스트 계획 (TDD 순서)

### 6.1 원칙
- 단위 테스트는 네트워크·자격 증명·Docker 없이 돈다. Drive는 `HttpMockSequence`를 `http_factory`로 주입하고, 백오프 대기는 `googleapiclient.http.time.sleep` 패치로 없앤다.
- 로컬은 `tmp_path`만 쓴다.
- 실제 Drive는 `tests/drive/`의 `drive` 마커 테스트(환경 변수 없으면 skip)로만 확인한다.
- `mypy .`가 테스트도 검사한다. google-auth 예외 생성자는 타입이 없어(`no-untyped-call`) `type[Exception]` 매개변수로 받거나 한 곳만 `# type: ignore[no-untyped-call]`.

### 6.2 케이스 목록 (구현 순서)
| # | 파일 | 케이스 | 고정하는 것 |
|---|---|---|---|
| 1 | `test_config.py` | 기본값: `disabled`, `Path("data/inbox")`, 폴더 ID `None` | D8, 기본 disabled |
| 2 | `test_config.py` | `.env.example` → `local`, `data/inbox` | 예시 파일 호환 |
| 3 | `test_config.py` | `drive` + 폴더 ID 없음/빈 문자열 → `ValidationError`(메시지에 `DRIVE_INBOX_FOLDER_ID`) ×2 | D7 설정 누락 시 시작 실패 |
| 4 | `test_config.py` | `drive` + 폴더 ID → 통과 | |
| 5 | `test_config.py` | 알 수 없는 backend → `ValidationError` | |
| 6 | `test_config.py` | `INBOX_LOCAL_PATH` 환경 변수 | |
| 7 | `test_inbox_local.py` | 원래 이름으로 저장, `.part` 남지 않음 | |
| 8 | `test_inbox_local.py` | 없는 루트 생성 | |
| 9 | `test_inbox_local.py` | 스트림을 처음부터 씀 | |
| 10 | `test_inbox_local.py` | 같은 이름 3번 → `이름.mp3`, `이름 (1).mp3`, `이름 (2).mp3` | D11 |
| 11 | `test_inbox_local.py` | 확장자 없는 이름 접미사 | |
| 12 | `test_inbox_local.py` | 위험한 이름 9종 → `ValueError`, 아무것도 만들지 않음 | D11, 경로 탈출 |
| 13 | `test_inbox_local.py` | 루트 자리에 파일 → `InboxUnavailableError` | I/O 오류 매핑 |
| 14 | `test_inbox_local.py` | `check()` 통과, 파일 생성 없음 | |
| 15 | `test_inbox_local.py` | `check()` 루트가 파일 → 실패 | |
| 16 | `test_inbox_drive.py` | resumable 세션 POST: 경로 `/upload/drive/v3/files`, `uploadType=resumable`, `supportsAllDrives=true`, `fields=id`, 본문 `name`·`parents`·`properties` / PUT 세션 URI·본문 | D1, D5, 공유 드라이브 |
| 17 | `test_inbox_drive.py` | `X-Upload-Content-Type` = 전달한 MIME | |
| 18 | `test_inbox_drive.py` | 읽던 스트림도 처음부터 업로드 | |
| 19 | `test_inbox_drive.py` | 업로드 타임아웃 30초 | D6 |
| 20 | `test_inbox_drive.py` | PUT 503 → 1회 대기, 상태 조회(`bytes */8`) 후 재전송 PUT 본문이 **전체 바이트**와 같음(본문을 요청 시점에 실제로 읽는 mock). 추가: PUT 중 `ConnectionResetError` → 상태 조회 후 재전송 성공 / PUT 403 권한·404 → 즉시 실패 ×2 / PUT 503 ×3 → 재시도 2회 후 실패 | 재시도(바깥 루프) |
| 21 | `test_inbox_drive.py` | 429, 403 `userRateLimitExceeded` → 재시도 성공 ×2 | |
| 22 | `test_inbox_drive.py` | 503 ×3 → 요청 3회, 대기 2회, `reason="http_503"` | "2회 재시도 후 실패" |
| 23 | `test_inbox_drive.py` | 404·403 권한·403 저장 용량·400 → 즉시 실패(요청 1회) ×4 | 비재시도 |
| 24 | `test_inbox_drive.py` | 실패 로그에 `inbox_write_failed`·`notFound`는 있고 파일명·폴더 ID는 없음 | D12, 보안 |
| 25 | `test_inbox_drive.py` | 네트워크 오류(`ConnectionResetError`) → `InboxUnavailableError` | |
| 26 | `test_inbox_drive.py` | 예상 밖 예외(`KeyError`)는 변환하지 않음 | 버그는 500 |
| 27 | `test_inbox_drive.py` | 생성 시 `google.auth.default`를 부르지 않음 | D7 |
| 28 | `test_inbox_drive.py` | `DefaultCredentialsError`·`RefreshError` → `InboxUnavailableError(reason=클래스명)`, 스코프 `DRIVE_SCOPES`로 요청 ×2 | D3, D7 |
| 29 | `test_inbox_drive.py` | 기본 Http: 자격 증명 1회만 로드, 호출마다 새 `Http(timeout=5.0)` | 스레드 안전, 캐시 |
| 30 | `test_inbox_drive.py` | `check()` GET 경로·`supportsAllDrives`·`fields`, 타임아웃 5초 | 리서치 §3.7 |
| 31 | `test_inbox_drive.py` | 폴더 아님·휴지통·`canAddChildren` false → reason별 실패 ×3 | |
| 32 | `test_inbox_drive.py` | `check()` 503 → 재시도 없이 실패 | |
| 33 | `test_inbox_factory.py` | `disabled` → `None` | D8 |
| 34 | `test_inbox_factory.py` | `local` → `LocalInboxWriter`, 디스크 미접촉 | |
| 35 | `test_inbox_factory.py` | `drive` → 자격 증명 없이 `DriveInboxWriter` 생성 | D7 |
| 36 | `test_inbox_factory.py` | 앱 기본 주입 `None` | |
| 37 | `test_inbox_factory.py` | 앱에 `local` 주입 | |
| 38 | `test_inbox_factory.py` | `drive` 설정으로 자격 증명 없이 앱 시작 | D7, 로봇 API 보호 |
| M1 | `tests/drive/test_drive_inbox.py` | 실제 `check()` 통과 | E-01 후 수동 |
| M2 | `tests/drive/test_drive_inbox.py` | 실제 업로드 → `name`·`parents`·`properties.source=web`·`mimeType` 확인 | D1, D2 |

### 6.3 케이스 수
단위 신규 61건(`test_config` +5, `test_inbox_local` 21, `test_inbox_drive` 29, `test_inbox_factory` 6), 수동 2건(기본 skip).

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
)

# test_defaults_without_env 끝에 추가
    assert settings.inbox_backend == "disabled"
    assert settings.inbox_local_path == Path("data/inbox")
    assert settings.drive_inbox_folder_id is None

# test_env_example_is_compatible 끝에 추가
    assert settings.inbox_backend == "local"
    assert settings.inbox_local_path == Path("data/inbox")


# 파일 끝에 추가
@pytest.mark.parametrize("folder_id", [None, ""])
def test_drive_backend_requires_folder_id(
    monkeypatch: pytest.MonkeyPatch, folder_id: str | None
) -> None:
    monkeypatch.setenv("INBOX_BACKEND", "drive")
    if folder_id is not None:
        monkeypatch.setenv("DRIVE_INBOX_FOLDER_ID", folder_id)

    with pytest.raises(ValidationError, match="DRIVE_INBOX_FOLDER_ID"):
        Settings(_env_file=None)


def test_drive_backend_with_folder_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INBOX_BACKEND", "drive")
    monkeypatch.setenv("DRIVE_INBOX_FOLDER_ID", "1AbC")

    settings = Settings(_env_file=None)

    assert settings.inbox_backend == "drive"
    assert settings.drive_inbox_folder_id == "1AbC"


def test_invalid_inbox_backend_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INBOX_BACKEND", "gdrive")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_inbox_local_path_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INBOX_LOCAL_PATH", "/data/inbox")

    assert Settings(_env_file=None).inbox_local_path == Path("/data/inbox")
```

#### `tests/unit/test_inbox_local.py` (신규)
```python
"""LocalInboxWriter — 개발용 로컬 inbox 폴더."""

import io
import os
from pathlib import Path
from typing import Any

import pytest

from app.core.logging import configure_logging
from app.infra.inbox import InboxUnavailableError
from app.infra.inbox.local import LocalInboxWriter

_NAME = "20261124_101500_김상담_A산업.mp3"


def _files(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in root.iterdir()}


def test_write_saves_file_with_original_name(tmp_path: Path) -> None:
    name = LocalInboxWriter(tmp_path).write(_NAME, io.BytesIO(b"ID3data"), "audio/mpeg")

    assert name == _NAME
    assert _files(tmp_path) == {_NAME: b"ID3data"}  # 임시 .part 파일이 남지 않음


def test_write_creates_missing_root(tmp_path: Path) -> None:
    root = tmp_path / "data" / "inbox"

    LocalInboxWriter(root).write(_NAME, io.BytesIO(b"x"), "audio/mpeg")

    assert (root / _NAME).read_bytes() == b"x"


def test_write_reads_stream_from_start(tmp_path: Path) -> None:
    stream = io.BytesIO(b"ID3data")
    stream.read(3)

    LocalInboxWriter(tmp_path).write(_NAME, stream, "audio/mpeg")

    assert (tmp_path / _NAME).read_bytes() == b"ID3data"


def test_write_adds_suffix_instead_of_overwriting(tmp_path: Path) -> None:
    writer = LocalInboxWriter(tmp_path)

    names = [writer.write(_NAME, io.BytesIO(data), "audio/mpeg") for data in (b"1", b"2", b"3")]

    stem = _NAME.removesuffix(".mp3")
    assert names == [_NAME, f"{stem} (1).mp3", f"{stem} (2).mp3"]
    assert _files(tmp_path) == {_NAME: b"1", f"{stem} (1).mp3": b"2", f"{stem} (2).mp3": b"3"}


def test_suffix_for_name_without_extension(tmp_path: Path) -> None:
    writer = LocalInboxWriter(tmp_path)
    writer.write("noext", io.BytesIO(b"1"), "audio/mpeg")

    assert writer.write("noext", io.BytesIO(b"2"), "audio/mpeg") == "noext (1)"


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../x.mp3", "a/b.mp3", "a\\b.mp3", "C:x.mp3", "a?.mp3", "a\x00.mp3"],
)
def test_write_rejects_unsafe_name(tmp_path: Path, name: str) -> None:
    root = tmp_path / "inbox"

    with pytest.raises(ValueError):
        LocalInboxWriter(root).write(name, io.BytesIO(b"x"), "audio/mpeg")

    assert not root.exists()  # 검사 실패 시 아무것도 만들지 않음


def test_write_io_error_becomes_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_bytes(b"")  # 디렉터리 자리에 파일이 있음

    with pytest.raises(InboxUnavailableError):
        LocalInboxWriter(root).write(_NAME, io.BytesIO(b"x"), "audio/mpeg")


def test_check_passes_for_writable_dir(tmp_path: Path) -> None:
    LocalInboxWriter(tmp_path).check()

    assert list(tmp_path.iterdir()) == []  # 파일을 만들지 않음


def test_check_fails_when_root_is_not_dir(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_bytes(b"")

    with pytest.raises(InboxUnavailableError):
        LocalInboxWriter(root).check()


class _BrokenStream(io.BytesIO):
    """첫 조각을 준 뒤 읽기에서 error를 던진다 (복사 도중 실패)."""

    def __init__(self, error: Exception) -> None:
        super().__init__(b"ID3data")
        self._error = error
        self._reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise self._error
        return super().read(3)


def test_write_removes_part_file_when_copy_fails(tmp_path: Path) -> None:
    with pytest.raises(InboxUnavailableError):
        LocalInboxWriter(tmp_path).write(_NAME, _BrokenStream(OSError("disk")), "audio/mpeg")

    assert list(tmp_path.iterdir()) == []


def test_write_removes_part_file_on_unexpected_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        LocalInboxWriter(tmp_path).write(_NAME, _BrokenStream(RuntimeError("bug")), "audio/mpeg")

    assert list(tmp_path.iterdir()) == []


def test_write_succeeds_when_file_is_moved_right_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    picked = tmp_path / "picked"
    picked.mkdir()
    root = tmp_path / "inbox"
    real_replace = os.replace

    def replace_then_pick_up(src: Any, dst: Any) -> None:
        real_replace(src, dst)
        real_replace(dst, picked / Path(dst).name)  # 로컬 Dispatcher가 곧바로 옮겨 감

    monkeypatch.setattr("app.infra.inbox.local.os.replace", replace_then_pick_up)

    name = LocalInboxWriter(root).write(_NAME, io.BytesIO(b"ID3data"), "audio/mpeg")

    assert name == _NAME
    assert (picked / _NAME).read_bytes() == b"ID3data"


def test_write_success_log_has_size_but_no_file_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 단다

    LocalInboxWriter(tmp_path).write(_NAME, io.BytesIO(b"ID3data"), "audio/mpeg")

    out = capsys.readouterr().out
    assert "inbox_written" in out
    assert '"size_bytes": 7' in out
    assert "김상담" not in out
```

#### `tests/unit/test_inbox_drive.py` (신규)
```python
"""DriveInboxWriter — HttpMockSequence로 Drive API 응답을 흉내 낸다 (네트워크·자격 증명 없음)."""

import io
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httplib2
import pytest
from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from googleapiclient.http import HttpMockSequence

from app.core.logging import configure_logging
from app.infra.inbox import InboxUnavailableError
from app.infra.inbox.drive import DRIVE_SCOPES, DriveInboxWriter

_FOLDER_ID = "FOLDER123"
_SESSION = {"status": "200", "location": "https://upload.example/session-1"}
_CREATED = ({"status": "200"}, json.dumps({"id": "FILE123"}))
_NOT_RECEIVED = ({"status": "308"}, "")  # 상태 조회 응답: 받은 바이트 없음 (range 헤더 없음)
_FOLDER_OK = {
    "id": _FOLDER_ID,
    "mimeType": "application/vnd.google-apps.folder",
    "trashed": False,
    "capabilities": {"canAddChildren": True},
}


def _error(status: int, reason: str) -> tuple[dict[str, str], str]:
    body = {"error": {"code": status, "message": "m", "errors": [{"reason": reason}]}}
    return {"status": str(status)}, json.dumps(body)


_Response = tuple[dict[str, str], str] | Exception


class _RecordingHttp(HttpMockSequence):  # type: ignore[misc]
    """실제 소켓처럼 요청 시점에 본문 스트림을 읽어 기록한다. 응답 자리에 예외를 두면 던진다."""

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: Any = None,
        headers: Any = None,
        redirections: int = 1,
        connection_type: Any = None,
    ) -> tuple[httplib2.Response, bytes]:
        data = body.read() if hasattr(body, "read") else body
        self.request_sequence.append((uri, method, data, headers))
        item = self._iterable.pop(0)
        if isinstance(item, Exception):
            raise item
        resp, content = item
        return httplib2.Response(resp), content.encode("utf-8")


class _Factory:
    """http_factory 대역. 넘겨받은 타임아웃을 기록하고 준비한 _RecordingHttp를 돌려준다."""

    def __init__(self, responses: list[_Response]) -> None:
        self.http = _RecordingHttp(responses)
        self.timeouts: list[float] = []

    def __call__(self, timeout: float) -> Any:
        self.timeouts.append(timeout)
        return self.http

    @property
    def requests(self) -> list[tuple[str, str, Any, Any]]:
        return list(self.http.request_sequence)


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr("app.infra.inbox.drive.time.sleep", slept.append)
    return slept


def _writer(factory: _Factory) -> DriveInboxWriter:
    return DriveInboxWriter(_FOLDER_ID, http_factory=factory)


def _write(writer: DriveInboxWriter, data: bytes = b"RIFF....") -> str:
    return writer.write("20261124_101500_김상담_A산업.wav", io.BytesIO(data), "audio/wav")


# ---------------------------------------------------------------- write


def test_write_uses_resumable_upload_to_shared_drive_folder() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])

    file_id = _write(_writer(factory))

    assert file_id == "FILE123"
    (start_uri, start_method, start_body, _), (put_uri, put_method, put_body, _) = factory.requests
    query = parse_qs(urlsplit(start_uri).query)
    assert start_method == "POST"
    assert urlsplit(start_uri).path == "/upload/drive/v3/files"
    assert query["uploadType"] == ["resumable"]
    assert query["supportsAllDrives"] == ["true"]
    assert query["fields"] == ["id"]
    assert json.loads(start_body) == {
        "name": "20261124_101500_김상담_A산업.wav",
        "parents": [_FOLDER_ID],
        "properties": {"source": "web"},
    }
    assert (put_uri, put_method) == ("https://upload.example/session-1", "PUT")
    assert put_body == b"RIFF...."


def test_write_sends_content_type_of_media() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])

    _write(_writer(factory))

    start_headers = factory.requests[0][3]
    assert start_headers["X-Upload-Content-Type"] == "audio/wav"


def test_write_reads_stream_from_start() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])
    stream = io.BytesIO(b"RIFF....")
    stream.read(4)  # 호출자가 매직 바이트를 읽고 되감지 않은 경우

    _writer(factory).write("a.wav", stream, "audio/wav")

    assert factory.requests[1][2] == b"RIFF...."


def test_write_uses_upload_timeout() -> None:
    factory = _Factory([(_SESSION, ""), _CREATED])

    _write(_writer(factory))

    assert factory.timeouts == [30.0]


def _puts(factory: _Factory) -> list[tuple[Any, Any]]:
    return [(body, headers) for _, method, body, headers in factory.requests if method == "PUT"]


def test_write_retries_server_error_then_succeeds(_no_backoff_sleep: list[float]) -> None:
    factory = _Factory([(_SESSION, ""), ({"status": "503"}, ""), _NOT_RECEIVED, _CREATED])

    assert _write(_writer(factory)) == "FILE123"
    first, status_query, retried = _puts(factory)
    assert first[0] == b"RIFF...."
    assert status_query[1]["Content-Range"] == "bytes */8"  # 서버가 받은 위치를 먼저 묻는다
    assert retried[0] == b"RIFF...."  # 재전송 본문이 비지 않고 전체 바이트
    assert len(_no_backoff_sleep) == 1


def test_write_resends_after_network_error_during_put(_no_backoff_sleep: list[float]) -> None:
    factory = _Factory([(_SESSION, ""), ConnectionResetError(), _NOT_RECEIVED, _CREATED])

    assert _write(_writer(factory)) == "FILE123"
    _, status_query, retried = _puts(factory)
    assert status_query[1]["Content-Range"] == "bytes */8"
    assert retried[0] == b"RIFF...."
    assert len(_no_backoff_sleep) == 1


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (_error(403, "insufficientFilePermissions"), "http_403"),
        (_error(404, "notFound"), "http_404"),
    ],
)
def test_write_fails_immediately_on_non_retryable_put_error(
    error: tuple[dict[str, str], str], reason: str, _no_backoff_sleep: list[float]
) -> None:
    factory = _Factory([(_SESSION, ""), error])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == reason
    assert len(factory.requests) == 2
    assert _no_backoff_sleep == []


def test_write_gives_up_put_after_two_retries(_no_backoff_sleep: list[float]) -> None:
    unavailable = ({"status": "503"}, "")
    factory = _Factory(
        [(_SESSION, ""), unavailable, _NOT_RECEIVED, unavailable, _NOT_RECEIVED, unavailable]
    )

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == "http_503"
    assert len(factory.requests) == 6
    assert len(_no_backoff_sleep) == 2


@pytest.mark.parametrize(
    "error",
    [_error(429, "rateLimitExceeded"), _error(403, "userRateLimitExceeded")],
    ids=["429", "403-rate-limit"],
)
def test_write_retries_rate_limit(error: tuple[dict[str, str], str]) -> None:
    factory = _Factory([error, (_SESSION, ""), _CREATED])

    assert _write(_writer(factory)) == "FILE123"


def test_write_gives_up_after_two_retries(_no_backoff_sleep: list[float]) -> None:
    factory = _Factory([({"status": "503"}, "")] * 3)

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == "http_503"
    assert len(factory.requests) == 3
    assert len(_no_backoff_sleep) == 2


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (_error(404, "notFound"), "http_404"),
        (_error(403, "insufficientFilePermissions"), "http_403"),
        (_error(403, "storageQuotaExceeded"), "http_403"),
        (_error(400, "badRequest"), "http_400"),
    ],
)
def test_write_fails_immediately_on_non_retryable_error(
    error: tuple[dict[str, str], str], reason: str
) -> None:
    factory = _Factory([error])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(_writer(factory))

    assert exc_info.value.reason == reason
    assert len(factory.requests) == 1


def test_write_failure_log_has_no_file_name_or_folder_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")  # 핸들러를 capsys의 stdout에 다시 단다
    factory = _Factory([_error(404, "notFound")])

    with pytest.raises(InboxUnavailableError):
        _write(_writer(factory))

    out = capsys.readouterr().out
    assert "inbox_write_failed" in out
    assert "notFound" in out
    assert "김상담" not in out
    assert _FOLDER_ID not in out


def test_write_success_log_has_file_id_but_no_file_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    factory = _Factory([(_SESSION, ""), _CREATED])

    _write(_writer(factory))

    out = capsys.readouterr().out
    assert "inbox_written" in out
    assert "FILE123" in out
    assert "김상담" not in out
    assert _FOLDER_ID not in out


def test_write_maps_network_error() -> None:
    def broken(timeout: float) -> Any:
        raise ConnectionResetError

    with pytest.raises(InboxUnavailableError) as exc_info:
        _write(DriveInboxWriter(_FOLDER_ID, http_factory=broken))

    assert exc_info.value.reason == "ConnectionResetError"


def test_unexpected_error_is_not_converted() -> None:
    def buggy(timeout: float) -> Any:
        raise KeyError("bug")

    with pytest.raises(KeyError):
        _write(DriveInboxWriter(_FOLDER_ID, http_factory=buggy))


# ---------------------------------------------------------------- 자격 증명


def test_credentials_are_not_loaded_on_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: Any) -> Any:
        raise AssertionError("시작 시 자격 증명을 읽으면 안 된다")

    monkeypatch.setattr("google.auth.default", fail)

    DriveInboxWriter(_FOLDER_ID)


@pytest.mark.parametrize("error_type", [DefaultCredentialsError, RefreshError])
def test_credential_error_becomes_unavailable(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    calls: list[dict[str, Any]] = []

    def fail(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise error_type("no key")

    monkeypatch.setattr("google.auth.default", fail)

    with pytest.raises(InboxUnavailableError) as exc_info:
        DriveInboxWriter(_FOLDER_ID).check()

    assert exc_info.value.reason == error_type.__name__
    assert calls == [{"scopes": DRIVE_SCOPES}]


def test_default_http_loads_credentials_once_and_sets_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads: list[Any] = []
    timeouts: list[float] = []
    http = HttpMockSequence([({"status": "200"}, json.dumps(_FOLDER_OK))] * 2)

    def fake_default(**kwargs: Any) -> Any:
        loads.append(kwargs)
        return AnonymousCredentials(), None  # type: ignore[no-untyped-call]

    def fake_http(timeout: float) -> Any:
        timeouts.append(timeout)
        return http

    monkeypatch.setattr("google.auth.default", fake_default)
    monkeypatch.setattr("httplib2.Http", fake_http)
    writer = DriveInboxWriter(_FOLDER_ID)

    writer.check()
    writer.check()

    assert loads == [{"scopes": DRIVE_SCOPES}]
    assert timeouts == [5.0, 5.0]  # 호출마다 새 Http


# ---------------------------------------------------------------- check


def test_check_reads_folder_metadata_only() -> None:
    factory = _Factory([({"status": "200"}, json.dumps(_FOLDER_OK))])

    _writer(factory).check()

    ((uri, method, _, _),) = factory.requests
    query = parse_qs(urlsplit(uri).query)
    assert method == "GET"
    assert urlsplit(uri).path == f"/drive/v3/files/{_FOLDER_ID}"
    assert query["supportsAllDrives"] == ["true"]
    assert query["fields"] == ["id,mimeType,trashed,capabilities/canAddChildren"]
    assert factory.timeouts == [5.0]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"mimeType": "audio/wav"}, "not_folder"),
        ({"trashed": True}, "trashed"),
        ({"capabilities": {"canAddChildren": False}}, "cannot_add_children"),
    ],
)
def test_check_rejects_unusable_folder(change: dict[str, Any], reason: str) -> None:
    factory = _Factory([({"status": "200"}, json.dumps(_FOLDER_OK | change))])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _writer(factory).check()

    assert exc_info.value.reason == reason


def test_check_does_not_retry() -> None:
    factory = _Factory([({"status": "503"}, "")])

    with pytest.raises(InboxUnavailableError) as exc_info:
        _writer(factory).check()

    assert exc_info.value.reason == "http_503"
    assert len(factory.requests) == 1
```

#### `tests/unit/test_inbox_factory.py` (신규)
```python
"""create_inbox_writer 분기와 앱 주입(app.state.inbox_writer, get_inbox_writer)."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_inbox_writer
from app.core.config import Settings
from app.infra.inbox import InboxWriter, create_inbox_writer
from app.infra.inbox.drive import DriveInboxWriter
from app.infra.inbox.local import LocalInboxWriter


def test_disabled_gives_none() -> None:
    assert create_inbox_writer(Settings(_env_file=None, inbox_backend="disabled")) is None


def test_local_gives_local_writer_without_touching_disk(tmp_path: Path) -> None:
    root = tmp_path / "inbox"

    writer = create_inbox_writer(
        Settings(_env_file=None, inbox_backend="local", inbox_local_path=root)
    )

    assert isinstance(writer, LocalInboxWriter)
    assert not root.exists()


def test_drive_gives_drive_writer_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    writer = create_inbox_writer(
        Settings(_env_file=None, inbox_backend="drive", drive_inbox_folder_id="F1")
    )

    assert isinstance(writer, DriveInboxWriter)


def _app_with_probe(build_app: Callable[..., FastAPI], **overrides: Any) -> TestClient:
    app = build_app(**overrides)

    @app.get("/probe-inbox")
    def probe(writer: Annotated[InboxWriter | None, Depends(get_inbox_writer)]) -> dict[str, str]:
        return {"writer": type(writer).__name__}

    return TestClient(app)


def test_app_injects_none_by_default(build_app: Callable[..., FastAPI]) -> None:
    client = _app_with_probe(build_app)

    assert client.get("/probe-inbox").json() == {"writer": "NoneType"}


def test_app_injects_configured_writer(build_app: Callable[..., FastAPI], tmp_path: Path) -> None:
    client = _app_with_probe(build_app, inbox_backend="local", inbox_local_path=tmp_path)

    assert client.get("/probe-inbox").json() == {"writer": "LocalInboxWriter"}


def test_app_starts_with_drive_backend_without_credentials(
    build_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    client = _app_with_probe(build_app, inbox_backend="drive", drive_inbox_folder_id="F1")

    assert client.get("/probe-inbox").json() == {"writer": "DriveInboxWriter"}
```

#### `tests/drive/__init__.py` (신규, 빈 파일), `tests/drive/test_drive_inbox.py` (신규)
```python
"""실제 Google Drive 수동 테스트 (E-01 이후). 기본 실행에서는 skip된다.

실행: GOOGLE_APPLICATION_CREDENTIALS=<키 경로> TEST_DRIVE_FOLDER_ID=<테스트용 폴더 ID> \\
      uv run pytest -m drive
운영 inbox/가 아닌 **테스트용 폴더**를 쓴다(Dispatcher가 집어 가지 않는 곳). 올린 파일은 남으므로
테스트 후 직접 지운다(기여자 역할은 삭제 권한이 없을 수 있다).
"""

import io
import os
from datetime import UTC, datetime
from typing import Any

import google.auth
import pytest
from googleapiclient.discovery import build

from app.infra.inbox.drive import DRIVE_SCOPES, DriveInboxWriter

pytestmark = pytest.mark.drive

_FOLDER_ID = os.environ.get("TEST_DRIVE_FOLDER_ID", "")


@pytest.fixture
def writer() -> DriveInboxWriter:
    if not _FOLDER_ID:
        pytest.skip("TEST_DRIVE_FOLDER_ID 없음 (실제 Drive 수동 테스트)")
    return DriveInboxWriter(_FOLDER_ID)


def _get(file_id: str) -> Any:
    credentials, _ = google.auth.default(scopes=DRIVE_SCOPES)
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return (
        service.files()
        .get(fileId=file_id, fields="id,name,parents,properties,mimeType", supportsAllDrives=True)
        .execute()
    )


def test_check_passes(writer: DriveInboxWriter) -> None:
    writer.check()


def test_write_creates_file_with_source_property(writer: DriveInboxWriter) -> None:
    name = f"pytest_{datetime.now(UTC):%Y%m%d_%H%M%S}_테스트_검증.mp3"

    file_id = writer.write(name, io.BytesIO(b"ID3" + b"\0" * 1024), "audio/mpeg")

    meta = _get(file_id)
    assert meta["name"] == name
    assert meta["parents"] == [_FOLDER_ID]
    assert meta["properties"] == {"source": "web"}
    assert meta["mimeType"] == "audio/mpeg"
```
- `TEST_DRIVE_FOLDER_ID`가 설정된 셸에서는 `uv run pytest`도 이 테스트를 실행한다(실제 업로드). 평소에는 설정하지 않는다.

---

## 7. 구현 순서 (TDD)

| 단계 | 할 일 | 확인 |
|---|---|---|
| 0 | W-10 통계 변경이 커밋된 뒤 시작(같은 `main.py`·`deps.py`를 고침) | `git status` |
| 1 | `pyproject.toml` 의존성·override·마커 → `uv lock` → `uv sync` | `uv run pytest --collect-only -q` |
| 2 | §6.2 #1~6 작성 → `config.py` 필드·검증, `.env.example` 주석 | `uv run pytest tests/unit/test_config.py` |
| 3 | #7~15 → `base.py`, `local.py` (`__init__.py`는 이 단계에서 재노출만) | `uv run pytest tests/unit/test_inbox_local.py` |
| 4 | #16~26 → `drive.py`의 `DriveInboxWriter.write`·오류 매핑 | `uv run pytest tests/unit/test_inbox_drive.py -k write` |
| 5 | #27~29 → `_ServiceAccountHttp` | `uv run pytest tests/unit/test_inbox_drive.py` (자격 증명 케이스) |
| 6 | #30~32 → `check()` | `uv run pytest tests/unit/test_inbox_drive.py` |
| 7 | #33~38 → `create_inbox_writer`, `deps.get_inbox_writer`, `main.py` | `uv run pytest tests/unit` |
| 8 | M1·M2 작성(실행은 E-01 후), `README.md` | `uv run pytest -m drive` → 2 skip |
| 9 | 공용 문서 수정(§5.11) | 리뷰 |
| 10 | 전체 검증(§8) | |

- 커밋 예: `feat: Drive 연동 모듈(InboxWriter) 추가` (코드·테스트·`pyproject.toml`·`uv.lock`·`.env.example`·`README.md`), `docs: 웹 업로드 출처 표시를 Drive 공개 속성(properties)으로 변경` (§5.11 문서). 문서 커밋을 기능 커밋에 합칠지는 리뷰에서 정한다.

---

## 8. 검증 명령
```bash
cd backend
uv run pytest                        # 전체 (DB 없으면 통합 skip, drive는 항상 skip)
uv run pytest -m "not integration"   # 단위만
uv run pytest -m drive               # 수동 Drive (환경 변수 없으면 2 skip)
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
- 기대(리뷰 반영 후): 기존 227 + 신규 단위 61 = 288 통과, 2 skip.

---

## 9. 확인 필요

### 9.1 A (C-01 공용 파일 소유)
| # | 항목 | 내용 |
|---|---|---|
| A1 | **`pyproject.toml`·`uv.lock` 변경** | 직접 의존성 `google-auth-httplib2`·`httplib2` 추가(이미 간접 설치, 버전 변경 없음), mypy override `google_auth_httplib2.*`·`httplib2.*`, pytest 마커 `drive`. 공용 파일이라 PR에서 확인 요청 |
| A2 | `tests/drive/` 위치 | C-05 테스트 기반 구성과 맞는지(별도 디렉터리 + 마커) |

### 9.2 RPA (④, Dispatcher)
| # | 항목 | 내용 |
|---|---|---|
| X1 | **출처 표시 필드(D1)** | 웹 업로드 파일은 공개 `properties.source = "web"`으로 표시한다(`appProperties` 아님). Dispatcher가 파일 메타데이터의 `properties`를 읽어 `source_type=WEB`/`DRIVE`를 정하는 방식으로 합의 필요. UiPath Google Drive 액티비티가 `properties`를 읽을 수 있는지(못 읽으면 Drive API 직접 호출 등) 확인 |
| X2 | MIME | 업로드 시 `mimeType`은 W-07이 넘긴 값(예: `audio/mpeg`, `audio/wav`). Dispatcher 필터가 확장자 기준인지 MIME 기준인지 |
| X3 | 파일명 정규화 | W-07에서 NFC 정규화 예정(D14). Dispatcher 담당자 이름 비교와 같은 형태인지 |
| X4 | 공용 문서 | `docs/input_flow.md` §4.3 문구 변경(§5.11) 공지 |

### 9.3 E-01 이후 실측 (수동 테스트 M1·M2)
| # | 항목 | 실패 시 조치 |
|---|---|---|
| E1 | **`drive.file` 스코프로 기존 `inbox/`에 `files.get`·업로드 가능한지(D2)** | 404면 `DRIVE_SCOPES`를 `https://www.googleapis.com/auth/drive`로 변경 + 공유 드라이브(또는 `inbox/` 폴더) 기여자 역할 유지 |
| E2 | 서비스 계정 역할: 기여자(`writer`)로 업로드·`canAddChildren=true`인지, `inbox/` 폴더 단위 멤버 추가가 가능한지 | 역할 조정, `architecture.md` §11·`input_flow.md` §4.3 확정 |
| E3 | 업로드 파일의 `properties.source`가 RPA 계정으로 보이는지 | X1과 함께 |
| E4 | resumable 미완료 업로드가 `inbox/` 목록에 보이지 않는지 | 보이면 Dispatcher 쪽 조건 추가 협의 |
| E5 | 타임아웃 30초/5초가 실제 망에서 적절한지(D6) | 상수 조정 |
| E6 | 조직 정책: 서비스 계정 멤버 추가 허용, 서버에서 `www.googleapis.com`·`oauth2.googleapis.com` 아웃바운드 | 관리자·인프라(O-03) |

### 9.4 W-07·O-02 인계
| # | 항목 | 내용 |
|---|---|---|
| H1 | `writer is None` | W-07은 503 `INBOX_UNAVAILABLE`, O-02는 `"disabled"`(실패 아님) |
| H2 | `reason` 노출 | 503 응답의 `message`·`detail`에는 넣지 않는다(규약 §6). O-02 응답에 넣을지는 O-02에서 정함(값에는 비밀 정보가 없음) |
| H3 | 동기 엔드포인트 | `write`·`check`는 블로킹. W-07·O-02 라우트는 `def`로 두거나 `run_in_threadpool`로 감싼다 |
| H4 | 파일명 검사 | 로컬 금지 문자 규칙(`validate_local_name`)을 W-07 검증과 맞출지 |
| H5 | 자격 증명 없을 때 지연 | 자격 증명이 없으면 `google.auth.default`가 GCE 메타데이터 서버 확인을 시도해 호출마다 약 3초 지연된다(실패는 캐시하지 않음). 비 GCP 배포는 `NO_GCE_CHECK=true`로 끈다. O-02에서 `check()` 결과 캐시를 검토 |
| H6 | 최악 업로드 소요 | 타임아웃 30초 × (요청 + 재시도·상태 조회) + 백오프로 파일 하나에 최악 약 3분. W-07 응답 시간·프록시 타임아웃 설계에 반영 |
| H7 | 예외 체인 | `InboxUnavailableError.__cause__`(원본 예외)에는 키 파일 경로 등이 들어갈 수 있다. W-07·O-02는 이 예외를 `exc_info`로 로그에 남기지 않고 `reason`만 쓴다 |

### 9.5 알려진 제한·후속 수정
| # | 항목 | 내용 |
|---|---|---|
| L1 | 로컬 이름 충돌 경쟁 | `LocalInboxWriter`는 존재 확인과 `os.replace` 사이에 같은 이름이 생기면 덮어쓴다. 개발용이라 허용. 필요하면 `os.link`(이미 있으면 실패) 후 임시 파일 삭제 방식으로 바꾼다 |
| L2 | Windows 끝 점·공백 이름 | `a.mp3.`·`a.mp3 ` 같은 이름은 Windows에서 끝 점·공백이 잘려 다른 이름으로 저장될 수 있다. 개발용이라 다루지 않음(H4와 함께 검토) |
| L3 | `architecture.md` §10.1 아웃바운드 | 서비스 계정 토큰 발급에 `oauth2.googleapis.com`도 필요하다. E-01 때 아웃바운드 허용 목록 문구를 수정한다 |

---

## 10. 구현 시 주의
1. 앱 시작 경로(`create_app`, `create_inbox_writer`, 생성자)에서 자격 증명을 읽거나 디스크·네트워크에 접근하지 않는다(D7). 테스트 #27·#34·#35·#38이 지킨다.
2. 로그·예외 메시지에 파일명, 폴더 ID, 키 경로, `str(HttpError)`, `HttpError.uri`를 넣지 않는다(업로드 세션 URI가 섞일 수 있음).
3. `httplib2.Http`·`AuthorizedHttp`·`build()` 결과를 인스턴스 필드에 저장해 재사용하지 않는다(스레드 안전성). 공유하는 것은 자격 증명뿐이다.
4. `properties`(공개)를 쓴다. `appProperties`로 되돌리지 않는다(D1).
5. 모든 Drive 호출에 `supportsAllDrives=True`를 붙인다. `files.create`에는 `driveId` 파라미터가 없다(위치는 `parents`로만).
6. 백오프 대기를 없애는 패치는 `app.infra.inbox.drive.time.sleep`에 건다(재시도 대기는 `_upload`가 `time.sleep`으로 한다. 라이브러리 호출은 `num_retries=0`이라 자체 대기가 없다). autouse 픽스처로 둔다.
7. `except` 대상은 §3.3의 네 가지로 한정한다. `Exception` 전체를 잡으면 버그가 503으로 숨는다.
8. 스코프를 `drive`로 바꾸게 되면 상수 한 줄과 `architecture.md` §11 문구만 바꾸고, 테스트는 `DRIVE_SCOPES`를 참조하므로 그대로 둔다.
