# Drive 연동 모듈 리서치 — `InboxWriter` (`DriveInboxWriter` / `LocalInboxWriter`)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 대상 기능 | `features.md` W-08 Drive 연동 모듈 — 사용처: W-07 웹 업로드(`POST /api/uploads`), O-02 헬스 체크(`GET /health`) / 선행: C-01(완료), **E-01(서비스 계정·공유 드라이브 권한, 미완료)** / 요구: PRD IN-03 |
| 근거 | `docs/prd.md` §IN-03, `docs/input_flow.md` v0.2 §4·§7, `architecture.md` v0.3 §2·§3·§4.1·§7·§8.2·§10·§11·§12·§13·§14, `research.md` v0.2 §2.3·§2.4·§7·§8, `back_stack.md` v0.1 §2.2·§4·§6·§7, `api/convention.md` v0.1, `app/core/{config,errors,logging,middleware}.py`, `app/main.py`, `app/api/deps.py`, `pyproject.toml`, `.env.example`, `deploy/docker-compose.dev.yml`, `tests/unit/**`, 원격 브랜치 `origin/main`의 `stt/`(③), `origin/csj`의 `uipath/`(④, 미병합) |
| 외부 문서 | Google Drive API v3 공식 가이드(업로드·공유 드라이브·속성·오류·한도·스코프), google-api-python-client 문서(스레드 안전성·모킹), 설치된 라이브러리 소스(`.venv`) |
| 검증 방법 | 문서·코드 정독, `.venv` 설치 버전·소스 확인, 스크래치 폴더에서 `HttpMockSequence`로 업로드·재시도·오류 동작 실측 (레포 코드는 수정하지 않음) |

> 이 문서는 구현 계획이 아니라 **사실 조사와 선택지 정리**다. 코드 조각은 설명용 스케치다. **[확인 필요]**는 공식 문서로 확정하지 못했거나 실제 Drive 환경에서 검증해야 하는 항목이다.

---

## 0. 요약 (핵심 발견)

1. **코드는 비어 있다.** `app/infra/inbox/__init__.py`·`app/infra/storage/__init__.py`만 있고 내용이 없다. `Settings`에 inbox 관련 필드가 없다(`app/core/config.py:10-38`). 반면 `.env.example:13-16`에는 이미 `INBOX_BACKEND=local`, `INBOX_LOCAL_PATH=./data/inbox`, 주석 처리된 `DRIVE_INBOX_FOLDER_ID`·`GOOGLE_APPLICATION_CREDENTIALS`가 있고, `deploy/docker-compose.dev.yml`은 `INBOX_BACKEND=local`, `INBOX_LOCAL_PATH=/data/inbox`, `./dev-data/inbox` 볼륨을 이미 준비해 두었다.
2. **의존성은 설치돼 있다.** `google-api-python-client` 2.202.0, `google-auth` 2.63.1, `google-auth-httplib2` 0.4.4, `httplib2` 0.32.1. mypy는 `googleapiclient.*`·`google.oauth2.*`의 타입 누락을 무시하도록 설정돼 있다(`pyproject.toml` `[[tool.mypy.overrides]]`). `google.auth.*`·`google_auth_httplib2`·`httplib2`는 이 목록에 없어 import 방식에 따라 override 추가가 필요할 수 있다 **[확인 필요: mypy 실행으로 확인]**.
3. **에러 코드는 준비돼 있다.** `ErrorCode.INBOX_UNAVAILABLE` → 503 "업로드 저장소를 사용할 수 없습니다."(`app/core/errors.py:21`, `:37`). `convention.md` §2.2는 `POST /api/uploads`의 에러로 503을 이미 적어 두었다.
4. **[핵심] `appProperties`는 다른 앱이 읽을 수 없다.** Drive 공식 문서: `appProperties`는 "private to the requesting app", `properties`는 "visible to all applications". 백엔드(서버 서비스 계정의 Cloud 프로젝트)가 쓴 `appProperties.source=web`을 UiPath Dispatcher(다른 OAuth 클라이언트/프로젝트)가 읽지 못할 가능성이 높다. 문서들(`architecture.md:167`, `:446`, `input_flow.md` §4.3, `research.md:84`)은 모두 `appProperties`를 전제로 한다 → `properties.source=web`으로 바꾸거나 RPA와 같은 프로젝트·계정을 쓰는지 확인해야 한다(§3.4, 결정 D1).
5. **[핵심] 스코프 `drive.file`로는 기존 `inbox/` 폴더에 쓰지 못할 수 있다.** `drive.file`은 "앱이 만들었거나 사용자가 앱으로 연 파일"에만 접근한다. `inbox/` 폴더는 RPA·관리자가 만든 것이므로 `parents=[inbox]` 업로드와 헬스 체크용 `files.get(inbox)`가 404가 될 가능성이 크다 **[확인 필요: 실제 환경]**. 서비스 계정은 OAuth 동의 화면·앱 검증 대상이 아니고, 실질 접근 범위는 **공유 드라이브 멤버십**으로 제한되므로 `drive` 스코프 + 최소 역할(기여자)이 현실적 선택지다(§3.3, 결정 D2).
6. **서비스 계정은 저장 용량이 없어 공유 드라이브가 필수다.** 공식 문서: "Service accounts don't have storage quota and can't own files … they must upload files and folders into shared drives". 공유 드라이브 파일은 "belong to the organization". 모든 호출에 `supportsAllDrives=true`가 필요하다(공식 문서로 확인, `architecture.md:444`의 **[확인 필요]** 해소).
7. **라이브러리 내장 재시도가 요구사항과 맞는다.** `execute(num_retries=N)`/`next_chunk(num_retries=N)`는 5xx, 429, 403 중 `userRateLimitExceeded`·`rateLimitExceeded`, SSL·소켓 타임아웃·연결 오류를 `rand() * 2**n`초 대기로 재시도한다(`googleapiclient/http.py:80-147`, `:150-215`). `num_retries=2`면 `architecture.md:448` "지수 백오프로 2회 재시도"를 그대로 만족한다(실측: 503 3회 → 대기 2번 → `HttpError 503`).
8. **기본 HTTP 타임아웃이 60초다**(`googleapiclient/http.py:75` `DEFAULT_HTTP_TIMEOUT_SEC = 60`). 재시도 2회면 최악 3분 이상 요청 스레드를 붙잡는다. `httplib2.Http(timeout=…)`로 줄여야 한다(결정 D6).
9. **httplib2는 스레드 안전하지 않다.** 공식 문서: "each thread … must have its own instance of `httplib2.Http()`". 동기 엔드포인트는 스레드풀에서 동시에 실행되므로 **호출마다 `AuthorizedHttp(credentials, http=httplib2.Http(timeout=…))`를 새로 만든다**(§4.4).
10. **`build("drive", "v3")`는 네트워크 없이 동작한다.** 2.x는 `static_discovery` 기본 `True`(`discovery.py:288-292`)로 패키지에 동봉된 `drive.v3.json`(revision 20261106)을 쓴다. 따라서 `HttpMockSequence`에 API 응답만 넣으면 단위 테스트가 된다(실측, §7).
11. **업로드 방식: resumable 권장.** 공식 문서는 5 MB 이하를 simple/multipart, 그보다 큰 파일을 resumable로 안내하고 "resumable uploads are also a good choice for most applications"라고 한다. 녹취는 수 MB~수십 MB, 요청 한도 100 MiB(`MAX_UPLOAD_MB`)라 resumable이 맞다. resumable은 세션 시작 POST만 비멱등이라 재시도로 인한 **중복 파일 생성 위험이 multipart보다 작다**(§5.3).
12. **`call_id` `YYYYMMDD_HHMMSS_NNN`은 Drive 파일명 규칙이 아니다.** ③의 `stt/schema/call_schema.json`에서 "건별 고유 ID (수신일_수신시각_순번)"로 정의되며, `stt/step2/run_dummy.py:36`이 **처리 시각**으로 생성한다. 파일명 규칙은 `input_flow.md` §7의 `{yyyyMMdd_HHmmss}_{담당자}_{고객사}.{wav|mp3}` **[결정 필요]**이고, 파싱은 Dispatcher가 한다. W-08은 파일명을 **바꾸지 않고 그대로 전달**하면 된다.
13. **RPA 쪽은 아직 Drive를 읽지 않는다.** `origin/csj`의 `uipath/`는 로컬 폴더(`Runtime\out` → `processing`)만 다루고, Drive 감지는 `features_rpa.md` P-06(P1, Phase 2, "서비스 계정·보안 정책 확인 필요")으로 남아 있다. ③ `stt/`도 로컬 `calls\in|out|done|failed`를 쓴다. → `source` 표시 방식(4번)·파일명 규칙은 아직 합의 여지가 있다.
14. **E-01 승인 전에도 대부분 구현할 수 있다.** 인터페이스·`LocalInboxWriter`·설정·`DriveInboxWriter`(모킹 테스트)·W-07 연동까지 가능하고, 실제 Drive로 확인할 항목(§8.2)만 E-01 이후로 남는다.

---

## 1. 현재 상태

### 1.1 코드
| 위치 | 상태 | 비고 |
|---|---|---|
| `app/infra/inbox/` | 빈 `__init__.py` | `architecture.md` §3.2: `base.py`, `drive.py`, `local.py(개발용)` |
| `app/infra/storage/` | 빈 `__init__.py` | R-03(A 소유) 미착수. O-02가 같이 쓴다 |
| `app/core/config.py` | `max_upload_mb`, `cors_origins`, `log_level`, `docs_enabled`, `database_url` | inbox 필드 없음. `extra="ignore"`라 `.env`의 `INBOX_*`는 지금 무시됨 |
| `app/core/errors.py` | `INBOX_UNAVAILABLE`(503) 있음. `AppError(code, message, detail)` | `AppError` 핸들러는 헤더를 붙이지 않는다(`Retry-After` 불가, `error_response(headers=…)`는 가능) |
| `app/main.py` | `create_app(settings)`에서 `app.state.session_factory` 준비 → 라우터 등록 | 같은 방식으로 `app.state.inbox_writer`를 둘 수 있다. (W-10 작업으로 `stats` 라우터 등록이 진행 중) |
| `app/api/deps.py` | `get_db`, `get_call_service` | `get_inbox_writer` 추가 위치 |
| `app/api/web/` | `calls.py`(W-01·W-02) | W-07이 `uploads.py` 추가 예정 |
| `tests/unit/test_app_smoke.py` | `create_app()`(개발자 `.env` 반영) | **앱 시작 시 Drive 키를 읽어 실패하면 이 테스트가 개발자 환경에 따라 깨진다** → 시작 시점 처리 방식에 영향(결정 D7) |
| `tests/unit/test_config.py` | `_ENV_NAMES` 환경 변수 비우기, `.env.example` 호환 테스트 | 새 필드 추가 시 `_ENV_NAMES`·`.env.example` 테스트 갱신 필요. `.env.example`은 `INBOX_BACKEND=local`, `INBOX_LOCAL_PATH=./data/inbox` |

### 1.2 의존성 (`.venv` 실측)
| 패키지 | 버전 | 사용 |
|---|---|---|
| google-api-python-client | 2.202.0 | `googleapiclient.discovery.build`, `http.MediaIoBaseUpload`, `http.HttpMockSequence`, `errors.HttpError` |
| google-auth | 2.63.1 | `google.oauth2.service_account.Credentials`, `google.auth.default`, `google.auth.exceptions` |
| google-auth-httplib2 | 0.4.4 | `AuthorizedHttp` (google-api-python-client 의존성으로 설치됨, `pyproject.toml`에 직접 명시는 없음) |
| httplib2 | 0.32.1 | `httplib2.Http(timeout=…)` (간접 의존성) |
| starlette / fastapi / anyio | 1.10.0 / 0.165.0 / 4.16.0 | `UploadFile.file`은 `SpooledTemporaryFile`(1 MB 초과 시 디스크, `starlette/formparsers.py:135`) → seek 가능 |

`google-auth-httplib2`·`httplib2`를 코드에서 직접 import하면 `pyproject.toml`에 직접 의존성으로 올릴지 정해야 한다(결정 D9).

---

## 2. 요구사항 정리

### 2.1 원문
| 출처 | 원문 |
|---|---|
| PRD IN-03 | "웹 대시보드에서 음성 파일을 업로드할 수 있다 (다중 파일). 서버는 파일을 클라우드 `inbox/`에 대신 업로드만 하고 처리는 IN-01 경로를 따른다" (P1) |
| `features.md` W-08 | "`DriveInboxWriter`(서비스 계정, 공유 드라이브), 개발용 `LocalInboxWriter`, 재시도·503 처리, 헬스 체크용 접근 확인 함수" — P1, Phase 2, 선행 C-01·E-01 |
| `features.md` W-07 | "다중 파일, 형식 검증(크기 제한은 C-02), `DriveInboxWriter`로 클라우드 `inbox/` 업로드(`appProperties.source=web`), DB 등록 없음, 202 응답" — 선행 C-02, W-08 |
| `features.md` O-02 | "`GET /health` — DB, 음성 저장소, Drive `inbox/` 접근 확인" — 선행 R-03, W-08 |
| `features.md` E-01 | "Google 서비스 계정 발급 + 공유 드라이브 멤버 추가" — 요청 담당 B, 1주차 |
| `architecture.md` §8.2 | `InboxWriter.write(filename, stream, content_type) -> str  # 생성된 파일 ID 반환` / resumable 업로드 / `supportsAllDrives=true` **[확인 필요]** / 원래 파일명 유지, 접미사 불필요 / `appProperties.source=web` / DB 등록 없음 / "실패 시 지수 백오프로 2회 재시도 후 `503 INBOX_UNAVAILABLE`" |
| `architecture.md` §10.3 | `INBOX_BACKEND` = `drive` \| `local`(개발) \| `disabled`(Phase 1), `DRIVE_INBOX_FOLDER_ID` / `INBOX_LOCAL_PATH`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `architecture.md` §10.1 | 키(JSON)는 Docker secret 또는 읽기 전용 볼륨, 이미지·Git 포함 금지. 아웃바운드는 Drive API(HTTPS)만. Phase 1은 `INBOX_BACKEND=disabled` |
| `architecture.md` §11 | 서비스 계정은 공유 드라이브 최소 권한(업로드 가능한 최소 역할) **[확인 필요]**, 키 반출 금지·주기적 교체 |
| `architecture.md` §12 | 헬스 체크: "Drive `inbox/` 폴더 메타데이터 조회 가능 여부" |
| `architecture.md` §13 | 통합: "LocalInboxWriter(임시 폴더), DriveInboxWriter(테스트용 Drive 폴더, 수동 실행)" |
| `input_flow.md` §4.3 | 서비스 계정을 공유 드라이브에 "콘텐츠 관리자" 이하 권한으로 추가 **[확인 필요]**. `research.md` §7은 "기여자" 등 |
| `input_flow.md` §4.2 | Dispatcher는 `inbox/` 폴링, "Drive는 업로드가 끝난 파일만 목록에 나타나므로 별도 대기 불필요", Drive 파일 ID를 `source_ref`로 전송, `.wav`·`.mp3` 외는 `failed/` |
| `back_stack.md` §2.2 | "동기(def) 엔드포인트 … Drive 업로드처럼 오래 걸리는 I/O도 FastAPI가 스레드풀에서 처리" |
| `convention.md` §6 | 응답에 서비스 계정 정보를 넣지 않는다. 로그에 요청·응답 본문·헤더 값을 남기지 않는다 |

### 2.2 해석
- W-08의 산출물은 **어댑터 + 설정 + 생성 함수 + 접근 확인 함수**다. HTTP 라우트는 없다(W-07·O-02 몫). 따라서 W-08 단독으로는 `openapi.json`이 바뀌지 않는다.
- "재시도·503 처리"는 어댑터가 재시도하고, 끝내 실패하면 **호출자가 `INBOX_UNAVAILABLE`로 응답할 수 있는 예외**를 던지는 것까지로 본다. HTTP 503 변환을 어댑터에서 할지 서비스에서 할지는 결정 D4.
- "헬스 체크용 접근 확인 함수"는 O-02가 호출할 **가벼운 확인**이다(파일을 쓰지 않음). `architecture.md` §12의 "폴더 메타데이터 조회"와 일치시킨다.
- 파일명·형식 검증은 W-07(업로드 서비스) 책임이다(`architecture.md` §4.1 "확장자·MIME·크기 검증"). W-08은 받은 이름·형식을 그대로 쓰되, 로컬 경로 안전성만은 `LocalInboxWriter`가 책임진다(§5.1).
- "개발용 `LocalInboxWriter`"는 `input_flow.md` §4.4의 로컬 `inbox/` 구조와 같은 폴더(개발 compose의 `./dev-data/inbox`)에 쓴다.

### 2.3 W-07·O-02가 이 모듈을 쓰는 방식 (예상)
```
W-07  POST /api/uploads (def 엔드포인트, 스레드풀)
      → UploadService.upload(files)
          for f in files: 확장자·MIME·매직 바이트 검증 (W-07)
          for f in files: writer.write(name, f.file, content_type) → file_id
          실패 → AppError(INBOX_UNAVAILABLE) → 503
      → 202 {items: [{name, file_id?}]}  (응답 형식은 W-07에서 결정)

O-02  GET /health
      → DB SELECT 1, AudioStorage 쓰기 확인(R-03), writer.check()
      → disabled 이면 "disabled"로 표시(실패 아님)
```

---

## 3. Google Drive API v3 분석

### 3.1 인증 — 서비스 계정
| 항목 | 내용 | 근거 |
|---|---|---|
| 키 파일 로드 | `google.oauth2.service_account.Credentials.from_service_account_file(path, scopes=[…])` | google-auth (`service_account.py:261`) |
| ADC | `google.auth.default(scopes=[…])`는 `GOOGLE_APPLICATION_CREDENTIALS` 경로의 키를 자동으로 읽고, GCP 런타임에서는 메타데이터 서버(Workload Identity)를 쓴다 | google-auth ADC. Phase 3 "Workload Identity로 키 파일 제거"(`architecture.md` §10.2)와 코드 변경 없이 호환 |
| 토큰 갱신 | `AuthorizedHttp`가 요청 시 만료된 토큰을 자동 갱신. 실패 시 `google.auth.exceptions.RefreshError`(키 폐기·시계 오차 등), 네트워크 문제는 `TransportError` | google-auth |
| 도메인 전체 위임 | 불필요. 공유 드라이브 멤버로 추가된 서비스 계정 자신으로 호출한다 (`with_subject` 쓰지 않음) | 공식 문서(공유 드라이브) |
| 저장 용량 | "Service accounts don't have storage quota and can't own files. Instead, they must upload files and folders into shared drives" | Drive 공유 드라이브 가이드 |
| 소유 | "Files in a shared drive belong to the organization, not an individual user." → 서비스 계정이 올린 파일도 RPA 계정이 이동(`processing/`)할 수 있다(RPA 계정 역할에 따름) | 같은 문서 |

### 3.2 공유 드라이브 파라미터
- 공식: 공유 드라이브를 다루는 `files`·`changes`·`permissions` 호출에는 "must include the `supportsAllDrives=true` query parameter". `files.get`이 404를 내면 우선 `supportsAllDrives=true` 누락을 의심하라고 오류 가이드가 안내한다.
- `files.create`에는 `driveId` 파라미터가 **없다**(동봉 discovery 문서의 `create` 파라미터: `enforceSingleParent, ignoreDefaultVisibility, includeLabels, includePermissionsForView, keepRevisionForever, ocrLanguage, supportsAllDrives, supportsTeamDrives, useContentAsIndexableText`). 위치는 본문 `parents=[<inbox 폴더 ID>]`로만 정한다 → 설정에 공유 드라이브 ID는 필요 없다.
- `parents`: "A file can only have one parent folder". 값은 공유 드라이브 **안의 폴더 ID**여야 한다(커뮤니티 사례: 공유 드라이브 ID 자체를 넣어 404가 난 경우 보고 **[확인 필요]**). 우리 구조는 `[공유 드라이브] 콜센터_녹취/inbox/`라서 `inbox/` 폴더 ID를 쓰면 된다.
- `includeItemsFromAllDrives`·`corpora`·`driveId`는 `files.list`용이다. W-08은 목록 조회를 하지 않으므로 쓰지 않는다.

### 3.3 스코프
| 스코프 | 공식 설명 | 분류 | 이 기능에서 |
|---|---|---|---|
| `drive.file` | "Create new Drive files, or modify existing files, that you open with an app or that the user shares with an app" | Non-sensitive, 권장 | 새 파일 생성은 가능. **기존 `inbox/` 폴더를 부모로 지정·조회할 권한이 있는지 불명확** — 문서는 사용자가 앱으로 열거나 Picker로 공유한 파일에 한정된다고 설명 **[확인 필요: E-01 후 실측]** |
| `drive` | "View and manage all your Drive files." | Restricted | 동작 보장. 실제 범위는 서비스 계정이 멤버인 공유 드라이브로 한정 |
| `drive.metadata.readonly` | 메타데이터 조회 | Restricted | 헬스 체크만 하면 충분하지만 업로드에 못 씀 |

- Restricted/sensitive 분류는 **사용자 OAuth 동의 화면의 앱 검증** 기준이다. 서비스 계정 자기 자신으로 호출하는 방식에는 동의 화면이 없다(일반적 이해, **[확인 필요]**).
- 최소 권한의 실질적 경계는 스코프보다 **공유 드라이브 역할**이다. 서비스 계정을 다른 공유 드라이브·폴더에 추가하지 않는 운영 규칙과 함께 쓴다.
- 권장안(결정 D2): `drive.file`로 먼저 시도해 E-01 환경에서 업로드·`files.get(inbox)`가 되면 유지, 404면 `drive`. 상수 하나로 두어 바꾸기 쉽게 한다.

### 3.4 파일 속성 — `appProperties` vs `properties`
| 필드 | 공식 설명 |
|---|---|
| `appProperties` | "A collection of arbitrary key-value pairs which are **private to the requesting app**. … can only be retrieved using an authenticated request … obtained with a OAuth 2 client ID." 가이드: "To add properties restricted to your app, use the `appProperties` field" |
| `properties` | "A collection of arbitrary key-value pairs which are **visible to all apps**." |

한도(공식): 파일당 사용자 정의 속성 최대 100개, 공개 속성 최대 30개, 한 앱의 비공개 속성 최대 30개, **키+값 합계 124바이트(UTF-8)**. `source=web`은 문제없다.

- Dispatcher는 UiPath Google Workspace 액티비티(UiPath 또는 조직의 OAuth 앱)나 별도 계정으로 Drive를 읽는다(`input_flow.md` §4.2, `features_rpa.md` P-06). 백엔드 서비스 계정의 Cloud 프로젝트와 다르면 **`appProperties`가 보이지 않는다.** "앱"이 Cloud 프로젝트 단위인지 OAuth 클라이언트 단위인지는 문서에 명시되지 않았다 **[확인 필요]**.
- 선택지(결정 D1): (a) `properties.source=web`으로 변경(권장, RPA가 어떤 방식으로 읽든 보임) (b) 둘 다 기록 (c) `appProperties` 유지 + RPA가 같은 프로젝트의 서비스 계정을 쓰도록 합의. (a)면 `architecture.md` §8.2·§4.1, `input_flow.md` §4.3, `features.md` W-07, `research.md` §2.4 문구 수정이 필요하고 RPA(④)와 합의해야 한다.
- 보조 수단: 업로드한 파일의 생성자(`owners`가 아니라 공유 드라이브에서는 `lastModifyingUser`/`sharingUser`) 이메일이 서비스 계정이면 웹 업로드로 판단할 수도 있다 **[확인 필요]**. 속성 방식이 더 명확하다.

### 3.5 업로드 방식
| 방식 | `uploadType` | 공식 기준 | 메타데이터 |
|---|---|---|---|
| simple | `media` | "small media file (5 MB or less) without supplying metadata" | 불가 → `parents`·`properties` 지정 불가 |
| multipart | `multipart` | 메타데이터 + 5 MB 이하 파일 한 요청 | 가능 |
| resumable | `resumable` | "large files (greater than 5 MB)", 네트워크 중단 가능성이 높을 때, "also a good choice for most applications" (요청 1회 추가) | 가능 |

resumable 세부(공식): 세션 URI는 1주일 후 만료, 청크는 256 KB(256×1024) 배수(마지막 제외), 5xx는 이어서 재시도, `404`는 "upload session has expired and the upload must be restarted from the beginning", 4xx는 새 세션으로 다시 시작. 최대 크기 5,497,558,138,880 바이트(discovery `mediaUpload.maxSize`).

라이브러리 동작(`.venv` 소스):
- `MediaIoBaseUpload(fd, mimetype, chunksize=DEFAULT_CHUNK_SIZE, resumable=False)` — `DEFAULT_CHUNK_SIZE = 100 * 1024 * 1024`(`http.py:67`). 생성 시 `fd.seek(0, SEEK_END)`로 크기를 재고 **오프셋 0부터** 읽는다 → fd는 seek 가능해야 한다(`UploadFile.file` 충족). 호출자가 매직 바이트를 읽은 뒤 되감지 않아도 Drive 쪽은 안전하다(로컬 쪽은 §5.1 참고).
- `resumable=True`이면 `request.next_chunk(num_retries=N)`를 응답이 나올 때까지 반복한다. 청크 하나가 `MAX_UPLOAD_MB`(100 MiB) 이상이면 사실상 1회 PUT. 청크를 작게(예: 8 MiB) 하면 메모리·재시도 단위가 줄지만 왕복이 늘어난다(결정 D5).
- `request.execute(num_retries=N)`로 resumable을 실행해도 내부에서 `next_chunk`를 반복한다.

실측(스크래치, `HttpMockSequence`):
```
multipart : POST …/upload/drive/v3/files?fields=id&supportsAllDrives=true&alt=json&uploadType=multipart → {'id': 'FILE123'}
resumable : 세션 POST(200, location) → PUT(200) → {'id': 'FILE123'}
resumable : 세션 POST → PUT 503 → (대기 0.89s) → PUT 200 → 성공
세션 POST 404(notFound) → ResumableUploadError(HttpError 하위) status_code=404, reason='File not found: P.', error_details=[{'reason': 'notFound', …}]
세션 POST 503 ×3 (num_retries=2) → 대기 2회 → HttpError 503
```

### 3.6 오류 코드와 재시도
공식 오류 가이드 요약:

| 상태 / reason | 공식 권장 | W-08 처리 (후보) | 라이브러리 자동 재시도 |
|---|---|---|---|
| 400 `badRequest` | `message` 확인 후 코드 수정 | 재시도 없음 → 실패 | 아니오 |
| 401 `authError` | 토큰 갱신 | `AuthorizedHttp`가 갱신 시도. 그래도 실패 → 실패 | 갱신 1회(google-auth-httplib2) |
| 403 `userRateLimitExceeded` / `rateLimitExceeded` | 지수 백오프 | 재시도 | **예** (`http.py:143`) |
| 403 `dailyLimitExceeded` | 할당량 상한 제거 | 실패 | 아니오 |
| 403 `storageQuotaExceeded` | 저장 용량 확보 ("Service accounts have no storage quota") → 공유 드라이브가 아닌 곳에 쓰면 발생 | 실패 (설정 오류) | 아니오 |
| 403 `teamDriveFileLimitExceeded` | 항목 수 줄이기 (공유 드라이브 최대 500,000개, 휴지통 포함) | 실패 | 아니오 |
| 403 `insufficientFilePermissions` / `teamDriveMembershipRequired` / `domainPolicy` / `appNotAuthorizedToFile` | 권한·관리자 정책 | 실패 (E-01 설정 문제) | 아니오 |
| 404 `notFound` | `supportsAllDrives=true` 확인, 접근 권한 확인 | 실패 (폴더 ID 오류·멤버 아님·`drive.file` 스코프) | 아니오 |
| 429 `rateLimitExceeded` | 지수 백오프 | 재시도 | **예** |
| 500 / 502 / 503 / 504 | 지수 백오프 | 재시도 | **예** |
| SSL 오류, `socket.timeout`, `ConnectionError`, `ETIMEDOUT`·`ECONNRESET` 등 | — | 재시도 | **예** (`http.py:190-215`) |

백오프 공식(Drive 한도 가이드): `min((2^n) + random_number_milliseconds, maximum_backoff)`, 무작위값 ≤ 1,000 ms, `maximum_backoff`는 보통 32 또는 64초. 라이브러리는 `rand() * 2**n`초(n=1, 2 → 최대 2초, 4초)로, 공식 공식과 모양은 다르지만 지터 있는 지수 백오프다. `num_retries=2`면 추가 대기는 최대 약 6초.

할당량(공식): 프로젝트당 분당 1,000,000 quota unit, 프로젝트·사용자당 분당 325,000. 사용자당 하루 업로드 750 GB. 일 수십~백여 건(`prd.md`) 규모에서는 문제되지 않는다.

**타임아웃**: `build_http()` 기본 60초(`socket.getdefaulttimeout()`이 있으면 그 값). 자동 재시도가 타임아웃에도 적용되므로 `Http(timeout=60)`이면 최악 `60 × 3 + 6`초 이상 요청이 묶인다. 업로드 연결 타임아웃을 30초 안팎, 헬스 체크는 5초 안팎으로 별도 지정하는 것을 권장(결정 D6). 이 값은 "소켓 무응답 시간"이라 큰 파일 전송 시간 전체를 자르지는 않는다 **[확인 필요: httplib2 timeout 의미]**.

**`Retry-After`**: 503 응답에 `Retry-After`를 붙이려면 `AppError` 핸들러가 헤더를 지원해야 한다(현재 미지원, `errors.py` `_handle_app_error`). 필수는 아니다(결정 D10).

### 3.7 접근 확인용 가벼운 호출
```
GET https://www.googleapis.com/drive/v3/files/{inbox_id}
    ?fields=id,mimeType,trashed,capabilities/canAddChildren&supportsAllDrives=true
```
(실측 URL 동일). 판정: 200이고 `mimeType == "application/vnd.google-apps.folder"`, `trashed == false`, `capabilities.canAddChildren == true`("Whether the current user can add children to this folder" — 공식 필드 설명)이면 정상. 이 조합은 "폴더가 존재하고 서비스 계정이 쓸 수 있다"까지 확인하며, 파일을 만들지 않는다. 비용은 읽기 1회.

- 헬스 체크에는 자동 재시도를 쓰지 않거나 0~1회로 줄이고(빠른 응답), 타임아웃을 짧게 둔다.
- 토큰 갱신 실패(`RefreshError`)·키 파일 없음도 여기서 드러난다.
- 헬스 체크 주기가 짧으면 호출 수가 늘지만 할당량에 비해 무시할 수준이다. 결과를 수십 초 캐시할지는 O-02에서 정한다.

### 3.8 동기 라이브러리 ↔ FastAPI
- 프로젝트 기본은 **동기 `def` 엔드포인트**(`back_stack.md` §2.2). FastAPI는 `def` 엔드포인트·의존성을 anyio 스레드풀(기본 토큰 40개)에서 실행하므로 W-07 라우트를 `def`로 쓰면 `DriveInboxWriter.write()`를 그대로 호출해도 이벤트 루프를 막지 않는다.
- `async def`에서 부를 일이 생기면(예: O-02를 `async`로 쓰는 경우) `fastapi.concurrency.run_in_threadpool(writer.check)` 또는 `anyio.to_thread.run_sync`로 감싼다. 권장은 O-02도 `def`.
- 업로드 1건이 수 초~수십 초 걸리면 스레드 하나를 그만큼 점유한다. 3명이 쓰는 규모에서는 40개 스레드로 충분하다. 다중 파일은 **순차 업로드**가 단순하고 할당량·스레드 측면에서도 안전하다(병렬화는 불필요).
- 스레드 안전성(공식): "httplib2 … is not thread-safe", 스레드마다 `httplib2.Http()`를 따로 둬야 한다. 권장 패턴 둘 중 **호출마다 `AuthorizedHttp(credentials, http=httplib2.Http(timeout=…))`를 만들어 `build(…, http=…)` 또는 `execute(http=…)`에 넘기는 방식**이 단순하다. `Credentials` 객체는 앱 시작 시 한 번 만들어 공유한다(토큰 갱신 경쟁은 드물고 결과가 같다 **[확인 필요: google-auth 스레드 안전성 공식 언급 없음]**).
- `build("drive", "v3", http=…, cache_discovery=False)`는 동봉 discovery JSON을 파싱하므로 네트워크 호출이 없다. 매 호출 build 비용은 수~수십 ms 수준 **[가정]**. 거슬리면 `service` 객체는 한 번 만들고 `execute(http=새 AuthorizedHttp)`만 바꾸는 방법도 있다.

---

## 4. 인터페이스 초안

### 4.1 `architecture.md` §8.2 원안과 확장
원안은 `write()` 하나다. W-08 요구("헬스 체크용 접근 확인 함수")를 위해 `check()`를 추가하는 안을 권장한다.

```python
# app/infra/inbox/base.py (스케치)
from typing import BinaryIO, Protocol


class InboxUnavailableError(Exception):
    """inbox에 쓸 수 없음 (재시도 소진, 권한·설정 오류, 비활성). 메시지에 파일명·키 경로를 넣지 않는다."""


class InboxWriter(Protocol):
    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        """inbox/에 파일 하나를 쓴다. 생성된 파일 ID(Drive file id / 로컬은 저장된 파일명)를 반환.
        stream은 seek 가능해야 하며 처음부터 끝까지 쓴다. 실패 시 InboxUnavailableError."""
        ...

    def check(self) -> None:
        """inbox/에 쓸 수 있는지 가볍게 확인한다(파일 생성 없음). 불가하면 InboxUnavailableError."""
        ...
```

| 항목 | 후보 | 비고 |
|---|---|---|
| 반환값 | `str` (Drive 파일 ID / 로컬은 실제 저장 파일명) | 원안 유지. W-07 응답·로그에 쓸 수 있다. Drive 파일 ID는 Dispatcher가 `source_ref`로 쓰는 값과 같다 |
| `source=web` | 어댑터 내부 상수로 항상 기록 | inbox writer는 웹 업로드 전용이라 인자로 받을 필요 없음. 키 이름·필드(`properties`/`appProperties`)는 결정 D1 |
| `check()` 반환 | `None` + 예외 / `bool` / 상태 객체 | 예외 방식이면 원인 분류(설정·권한·네트워크)를 예외 속성으로 줄 수 있다. O-02 응답에 원인 문자열을 노출할지는 O-02 결정 |
| 비활성(`disabled`) | (a) `None` 주입 (b) `DisabledInboxWriter`(write·check 모두 예외) | 결정 D8 |

### 4.2 예외 → `ErrorCode` 매핑
| 상황 | 어댑터 | 호출자(W-07) 응답 |
|---|---|---|
| 재시도 대상 오류가 `num_retries` 소진 | `InboxUnavailableError` | `503 INBOX_UNAVAILABLE` |
| 재시도 비대상 HttpError(400·401·403·404) | `InboxUnavailableError` (즉시) | `503 INBOX_UNAVAILABLE` — 클라이언트가 고칠 수 없는 서버 측 설정 문제이므로 4xx로 돌려주지 않는다 |
| `RefreshError`·`DefaultCredentialsError`·키 파일 없음/손상 | `InboxUnavailableError` | 503 |
| 네트워크(`OSError`, `httplib2.HttpLib2Error`, 타임아웃) 재시도 소진 | `InboxUnavailableError` | 503 |
| `disabled` | (D8에 따름) | 503 |
| 로컬: 디렉터리 없음·권한 없음·디스크 가득 | `InboxUnavailableError` | 503 |
| 로컬: 파일명이 경로 탈출(`..`, 구분자) | (D11) `ValueError` 또는 정리 후 저장 | W-07 검증에서 먼저 막는 것이 원칙 |
| 그 밖의 예외(버그) | 그대로 전파 | `UnhandledErrorMiddleware` → 500 |

- `AppError`는 HTTP 객체에 의존하지 않으므로(`errors.py:58`) 어댑터가 `AppError(ErrorCode.INBOX_UNAVAILABLE)`를 직접 던질 수도 있다. 다만 `architecture.md` §3.1이 Infra 어댑터에 "도메인 규칙 금지"를 두고 있고, O-02가 결과를 상태로 바꿔야 하므로 **전용 예외 + 서비스에서 변환**을 권장한다(결정 D4).
- 응답 `message`는 기본 문구 "업로드 저장소를 사용할 수 없습니다." 그대로, `detail`은 `null` 또는 업로드 결과 요약(W-07 결정). Drive 오류 원문·폴더 ID·서비스 계정 이메일은 응답에 넣지 않는다(`convention.md` §3.4-4, §6).

### 4.3 다중 파일과 부분 실패 (W-07 결정, 인터페이스 영향)
W-08은 파일 1건 단위로 쓰므로 부분 실패 정책은 W-07이 정한다. 참고용 선택지:
- (a) 순차 업로드, 하나라도 실패하면 즉시 503. 이미 올라간 파일은 그대로 둔다(Dispatcher가 처리, 재업로드 시 해시 중복 409로 정리됨). 응답에 성공분을 알릴 방법이 없다.
- (b) 모두 시도하고 202에 파일별 결과(`accepted`/`failed`) — 전부 실패면 503.
- (c) 업로드 전에 `check()`로 사전 확인 후 (a).
→ W-07 리서치에서 프론트(②)와 정한다. W-08은 어느 쪽이든 지원한다.

### 4.4 `DriveInboxWriter` 스케치 (설명용)
```python
# app/infra/inbox/drive.py (스케치)
_SCOPES = ["https://www.googleapis.com/auth/drive"]   # 또는 drive.file (결정 D2)
_FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveInboxWriter:
    def __init__(self, folder_id: str, credentials: Credentials, *, retries: int = 2,
                 timeout_sec: float = 30, chunk_size: int = 8 * 1024 * 1024) -> None: ...

    def _service(self, timeout: float) -> Any:
        http = AuthorizedHttp(self._credentials, http=httplib2.Http(timeout=timeout))
        return build("drive", "v3", http=http, cache_discovery=False)

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        body = {"name": filename, "parents": [self._folder_id], "properties": {"source": "web"}}
        media = MediaIoBaseUpload(stream, mimetype=content_type, chunksize=self._chunk, resumable=True)
        try:
            request = self._service(self._timeout).files().create(
                body=body, media_body=media, fields="id", supportsAllDrives=True)
            response = None
            while response is None:
                _, response = request.next_chunk(num_retries=self._retries)
        except (HttpError, GoogleAuthError, httplib2.HttpLib2Error, OSError) as exc:
            _log.warning("inbox_write_failed", backend="drive", **_error_fields(exc))
            raise InboxUnavailableError from exc
        return str(response["id"])

    def check(self) -> None:
        meta = self._service(5).files().get(
            fileId=self._folder_id, fields="id,mimeType,trashed,capabilities/canAddChildren",
            supportsAllDrives=True).execute(num_retries=0)
        # mimeType == 폴더, trashed False, canAddChildren True 가 아니면 InboxUnavailableError
```
- `_error_fields(exc)`: `HttpError`면 `status_code`·`error_details[0]["reason"]`만, 그 외는 예외 클래스 이름만 기록한다(§6).
- 자격 증명 생성은 별도 함수(`load_credentials(settings)`)로 두어 테스트에서 가짜 자격 증명을 주입한다.

### 4.5 `LocalInboxWriter` 스케치 (설명용)
```python
class LocalInboxWriter:
    def __init__(self, root: Path) -> None: ...

    def write(self, filename: str, stream: BinaryIO, content_type: str) -> str:
        name = _safe_name(filename)               # 경로 성분 제거·금지 문자 검사 (§5.1)
        stream.seek(0)
        tmp = self._root / f".{uuid4().hex}.part"  # 확장자가 .wav/.mp3가 아니어서 로컬 Dispatcher가 집지 않음
        with tmp.open("xb") as out:
            shutil.copyfileobj(stream, out)
        final = _unique_path(self._root, name)     # 같은 이름 있으면 접미사 (§5.2)
        os.replace(tmp, final)                     # 같은 볼륨 내 원자적 이동  (경쟁 처리는 §5.2)
        return final.name

    def check(self) -> None:
        # root가 존재하는 디렉터리이고 os.access(root, os.W_OK) 인지 확인
```
- `content_type`은 로컬에서 쓰지 않는다(메타데이터 저장 안 함). `source=web` 표시가 로컬에서도 필요하면 사이드카 파일(`name.meta.json`) 등이 필요하나, 로컬은 개발용이므로 **생략 권장**.
- 시작 시 디렉터리를 만들지(`mkdir(parents=True, exist_ok=True)`) 여부: 개발 편의상 만드는 쪽을 권장(compose 볼륨 경로는 이미 존재).

### 4.6 생성·주입
```python
# app/infra/inbox/__init__.py 또는 factory (스케치)
def create_inbox_writer(settings: Settings) -> InboxWriter | None:
    match settings.inbox_backend:
        case "drive":    return DriveInboxWriter(settings.drive_inbox_folder_id, load_credentials(settings))
        case "local":    return LocalInboxWriter(settings.inbox_local_path)
        case "disabled": return None
```
- `create_app()`에서 `app.state.inbox_writer = create_inbox_writer(settings)` → `deps.get_inbox_writer(request)`. `session_factory`와 같은 방식이라 기존 구조와 맞다.
- 테스트는 `app.dependency_overrides[get_inbox_writer]` 또는 `app.state.inbox_writer = FakeInboxWriter()`로 교체한다.

---

## 5. 파일명·중복·동시성

### 5.1 파일명
- **원래 이름을 그대로 쓴다**(`architecture.md` §8.2). Dispatcher가 `{yyyyMMdd_HHmmss}_{담당자}_{고객사}.{wav|mp3}`(`input_flow.md` §7, **[결정 필요]**)를 파싱해 담당자·통화 일시·고객사를 뽑고, 실패하면 `metadata_incomplete=true`로 등록된다. 접두사·접미사를 붙이면 고객사 값이 오염된다.
- `call_id` `YYYYMMDD_HHMMSS_NNN`(③ 스키마)은 파이프라인이 수신 시각으로 생성하는 값이라 파일명과 무관하다. 백엔드 `call_record.id`(bigint)와도 다르다(`features_rpa.md` §4가 ①에 "`call_id`(문자열) vs 서버 id 키"를 질의 중).
- 브라우저가 보내는 `UploadFile.filename` 처리(W-07에서 할 일로 권장):
  - 경로 성분 제거(`PurePosixPath`/`PureWindowsPath`의 마지막 성분). 빈 이름·`.`·`..` 거부.
  - **유니코드 NFC 정규화**: macOS 브라우저는 한글 파일명을 NFD(자모 분리)로 보낼 수 있다. Dispatcher의 담당자 매칭(3명 이름 비교)이 NFD에서 실패할 수 있어 `unicodedata.normalize("NFC", name)`를 권장 **[확인 필요: 실제 브라우저·UiPath 비교 동작]**.
  - 확장자 소문자 비교(`.WAV` 허용 여부)는 W-07 검증 규칙.
- Drive는 이름에 `/` 등 거의 모든 문자를 허용하고 같은 폴더에 같은 이름을 허용한다. 로컬(특히 Windows 개발 PC)은 `\ / : * ? " < > |`, 예약 이름(`CON` 등)이 불가하다 → `LocalInboxWriter`는 최소한 경로 탈출을 막고, 나머지 금지 문자는 거부(예외) 또는 `_` 치환 중 선택(결정 D11).

### 5.2 중복
| 경우 | Drive | Local |
|---|---|---|
| 같은 이름, 다른 내용 | 둘 다 생성(별도 파일 ID). Dispatcher는 각각 처리 | 덮어쓰기 금지 필요 → 접미사 또는 실패 (결정 D11) |
| 같은 파일을 두 번 업로드 | 두 파일 생성 → Dispatcher 등록 시 해시 중복 `409 DUPLICATE_FILE` → 기존 상태에 따라 `done/` 등으로 정리 (`input_flow.md` §6.2) | 접미사로 두 파일 → 동일하게 409로 정리 |
| 재시도로 인한 중복 생성 | multipart: 요청은 서버에 도달했는데 응답이 유실되면 재시도가 두 번째 파일을 만든다. resumable: 세션 시작 POST가 재시도돼도 미완료 세션만 늘고, 파일은 최종 PUT 성공 시 하나만 생긴다 → **resumable이 유리** | 해당 없음 |

- 백엔드는 업로드 시 해시 중복을 검사하지 않는다(DB 등록 없음, 등록은 Dispatcher 단일 경로 — `architecture.md` §8.2). 업로드 전에 DB 해시로 "이미 등록된 파일" 경고를 줄 수는 있으나 W-07 범위 밖의 추가 기능이다(언급만).
- 로컬 접미사 예: `이름 (1).mp3` → 고객사 파싱 값이 `A산업 (1)`이 된다. 개발용이므로 허용 가능하나, `O_EXCL` 실패 시 예외로 끝내는 쪽이 더 단순하다.

### 5.3 동시성
- Drive: 파일 생성은 서버 측에서 독립적이라 동시 업로드끼리 충돌하지 않는다. 클라이언트 측 위험은 httplib2 공유뿐 → 호출마다 새 `Http`(§3.8).
- Dispatcher와의 경합: Drive는 업로드가 완료된 파일만 목록에 나타난다(`input_flow.md` §4.2, `architecture.md` §8.2) → 전송 중 파일을 Dispatcher가 집지 않는다 **[확인 필요: resumable 미완료 세션이 목록에 안 보이는지 E-01 후 확인]**.
- Local: 임시 파일(`.xxx.part`)에 다 쓴 뒤 `os.replace`로 최종 이름을 부여하면, 로컬 Dispatcher 흉내 스크립트가 반쯤 쓴 파일을 집지 않는다. 같은 이름 동시 업로드는 `os.replace`가 덮어쓰므로, 덮어쓰기를 막으려면 최종 이름을 `open(final, "xb")`로 선점한 뒤 복사하거나 `os.link`+삭제 방식이 필요하다. 개발용이므로 "존재 확인 후 replace"의 작은 경쟁은 허용 가능 **[가정]**.
- uvicorn workers 2~4(`architecture.md` §10.1): 워커 간 공유 상태가 없으므로 문제없다. 로컬 모드도 파일 시스템 원자성에만 의존한다.

---

## 6. 보안·PII·로그

- 녹취 파일명에 **담당자 이름·고객사**가 들어간다(`input_flow.md` §7). 내부 사용자 정보라 고객 PII는 아니지만, `convention.md` §6("요청·응답 본문을 로그에 남기지 않는다")의 취지에 따라 **로그에는 파일명을 남기지 않는 것을 기본**으로 권장한다. 추적은 `request_id`(자동 바인딩)와 Drive 파일 ID·크기·소요 시간으로 한다. 파일명 기록이 운영상 필요하면 팀 합의 후 추가(결정 D12).
- Drive 오류 로그: `HttpError.status_code`, `error_details[0].reason`만 남긴다. `HttpError.uri`·`str(exc)`에는 폴더 ID·업로드 세션 URI(`upload_id` 포함, 세션 소유자 인증 없이 이어쓰기 가능한 값) 가 들어갈 수 있으므로 기록하지 않는다 **[확인 필요: 세션 URI 노출 위험 정도]**.
- 라이브러리 로거: `googleapiclient.http`는 재시도마다 `WARNING`으로 메서드·요청 URI·상태를 찍는다(`http.py:176-186`, `next_chunk` 재시도 로그는 `self.uri` — 세션 URI가 아니라 최초 요청 URI라 비밀값은 없다). 403 응답 본문이 JSON이 아니면 본문을 그대로 경고로 찍고(`http.py:136`), 403 reason도 경고로 남긴다. 구조화 로그(JSON)와 형식이 달라질 뿐 PII 위험은 낮다. → 우리 쪽 `inbox_write_failed` 로그로 충분하면 `configure_logging`에서 `logging.getLogger("googleapiclient")`를 `ERROR`로 올리는 것을 검토(`app/core/logging.py`가 `httpx`를 WARNING으로 올린 선례 있음).
- 키 파일: Docker secret(`/run/secrets/drive-sa.json`, `.env.example:16`)·읽기 전용 볼륨. 경로·키 내용·서비스 계정 이메일을 로그·응답·헬스 체크 응답에 넣지 않는다(`convention.md` §6). `.gitignore`에 키 파일 패턴이 있는지 O-03에서 확인.
- `GOOGLE_APPLICATION_CREDENTIALS`는 google-auth 표준 변수라 `google.auth.default()`가 자동으로 읽는다. 다른 Google 라이브러리도 같은 키를 쓰게 되므로 프로세스 안에서 다른 용도가 없다는 전제(현재 없음).
- 공유 드라이브 쪽: 서비스 계정에 **기여자(Contributor)** 역할이면 파일 추가가 가능하다. API 역할명으로 `writer`가 "add files to shared drives"(공식). 기여자는 이동·삭제 권한이 없어 최소 권한에 맞다. "콘텐츠 관리자"(`fileOrganizer`)는 이동·휴지통까지 가능해 과하다. UI 역할명 ↔ API 역할 대응(기여자=`writer`, 콘텐츠 관리자=`fileOrganizer`, 관리자=`organizer`)은 일반적 이해 **[확인 필요]**. 문서 간 표현이 다르다(`input_flow.md` "콘텐츠 관리자 이하", `research.md` "기여자 등").
- 폴더 수준 권한: 공유 드라이브는 하위 폴더에 멤버를 따로 추가할 수 있으나 상위 권한을 줄일 수는 없다(일반적 이해 **[확인 필요]**). `inbox/`에만 쓰게 하려면 공유 드라이브 멤버가 아니라 `inbox/` 폴더에만 기여자로 추가하는 방식을 E-01에서 검토.

---

## 7. 테스트 전략

### 7.1 수준별
| 수준 | 대상 | 방법 | Docker/E-01 필요 |
|---|---|---|---|
| 단위 | `LocalInboxWriter` 쓰기·임시 파일·중복·경로 탈출·`check()` | `tmp_path` | 없음 |
| 단위 | `DriveInboxWriter.write()` 요청 형태(`uploadType=resumable`, `supportsAllDrives=true`, 본문 `parents`·`properties`·`name`) | `HttpMockSequence`에 `echo_request_body`/`echo_request_uri` 또는 시퀀스 응답, `build(..., http=mock)` 주입 | 없음 |
| 단위 | 재시도: 503→200 성공, 503×3 → `InboxUnavailableError`, 429·403 rateLimit 재시도, 404·403 권한 즉시 실패 | `HttpMockSequence` + `monkeypatch.setattr("googleapiclient.http.time.sleep", lambda s: None)` (실측: 모듈의 `time.sleep`을 바꾸면 대기 제거) | 없음 |
| 단위 | `check()`: 폴더·휴지통·`canAddChildren` false·404 | `HttpMockSequence` | 없음 |
| 단위 | 자격 증명 오류(`RefreshError`)·키 파일 없음 → `InboxUnavailableError` | 가짜 자격 증명/예외를 던지는 `Http` | 없음 |
| 단위 | `create_inbox_writer(settings)` 분기, 설정 검증(`drive`인데 폴더 ID 없음) | `Settings(_env_file=None, …)` | 없음 |
| 단위 | W-07 라우트: 성공 202, `InboxUnavailableError` → 503 형식 | `FakeInboxWriter`(메모리에 기록, 실패 주입) + `TestClient` | 없음 |
| 수동 통합 | 실제 테스트용 공유 드라이브 폴더 업로드·조회·삭제 | `@pytest.mark.drive`(신규 마커, 기본 skip) + 환경 변수가 있을 때만 실행 | **E-01 필요** |

- `pyproject.toml`의 `--strict-markers` 때문에 새 마커는 `markers`에 등록해야 한다. 기존 `integration` 마커는 "실제 PostgreSQL" 의미라 Drive 수동 테스트와 섞지 않는 편이 명확하다(결정 D13).
- 인증 우회: `HttpMockSequence`를 `build(http=…)`에 직접 넘기면 자격 증명이 없어도 된다(실측). 따라서 어댑터가 `http`(또는 `service`) 생성 함수를 주입받도록 설계하면 테스트가 쉽다. 예: 생성자 인자 `http_factory: Callable[[float], httplib2.Http]`.
- `HttpMock`/`HttpMockSequence`는 공식 문서에 있는 모킹 도구다. `RequestMockBuilder`는 응답 본문만 흉내 내고 HTTP 상태별 재시도 경로를 타지 않아 이 용도에는 덜 적합하다 **[가정]**.
- `HttpMockSequence`는 요청 순서대로 응답을 소비한다. resumable은 "세션 POST(200 + `location` 헤더) → PUT(200 + JSON)" 2개가 필요하다(실측).
- 업로드 오류는 `ResumableUploadError`(HttpError 하위)로 올 수 있으므로 `HttpError`로 잡으면 된다(실측).

### 7.2 기존 테스트 영향
- `tests/unit/test_config.py`: 새 환경 변수 이름을 `_ENV_NAMES`에 추가해야 개발자 환경 변수 영향이 없다. `test_env_example_is_compatible`에 inbox 값 단언 추가 가능.
- `tests/unit/test_app_smoke.py`: `create_app()`이 실제 `.env`를 읽는다. 시작 시 키 파일을 읽어 예외를 내도록 만들면 개발자 `.env`가 `drive`일 때 실패한다 → 결정 D7.
- W-08만으로는 라우트가 없어 `openapi.json` 변화 없음.

---

## 8. E-01 승인 전 개발 범위

### 8.1 지금 할 수 있는 것
1. `InboxWriter` Protocol, `InboxUnavailableError`, `create_inbox_writer()`.
2. `Settings` 필드·검증, `.env.example` 정리, `test_config.py` 갱신.
3. `LocalInboxWriter` 전부(개발 compose의 `./dev-data/inbox`로 수동 확인 가능).
4. `DriveInboxWriter` 전부 — `HttpMockSequence` 단위 테스트로 요청 형태·재시도·오류 매핑 검증.
5. `deps.get_inbox_writer`, `app.state.inbox_writer` 연결(W-07과 같이 들어가도 됨).
6. 로그 정리(`googleapiclient` 로거 레벨).
7. 수동 Drive 테스트 스크립트/마커 뼈대(실행은 E-01 후).

개인 Google 계정으로 테스트용 서비스 계정을 만들어 개인 공유 드라이브(Workspace 필요)에 붙여 미리 검증하는 방법도 있으나, 조직 정책(도메인 외부 멤버 차단 등)이 달라 결과가 운영과 다를 수 있다 **[가정]**.

### 8.2 E-01 이후 확인할 것
| 항목 | 확인 방법 |
|---|---|
| `drive.file` 스코프로 `inbox/`에 업로드·`files.get` 가능 여부 (D2) | 수동 테스트 |
| 서비스 계정 역할(기여자로 충분한지, 폴더 단위 추가 가능 여부) | 공유 드라이브 설정 + 업로드 |
| `properties`/`appProperties`를 RPA(UiPath 액티비티)가 읽을 수 있는지 (D1) | RPA 파트와 같이 확인 |
| resumable 미완료 파일이 `inbox/` 목록에 안 보이는지 | 큰 파일 업로드 중 목록 조회 |
| 조직 정책: 외부 공유 차단·서비스 계정 멤버 추가 허용, VM에서 `www.googleapis.com`·`oauth2.googleapis.com` 아웃바운드 허용 | 관리자·인프라 확인 (O-03) |
| 업로드 파일의 MIME(`audio/mpeg`, `audio/wav`/`audio/x-wav`)가 Dispatcher 필터와 맞는지 | 업로드 후 메타데이터 확인 |

---

## 9. 설정 항목 (후보)

| 환경 변수 | 필드 | 타입·기본값 | 근거 / 비고 |
|---|---|---|---|
| `INBOX_BACKEND` | `inbox_backend` | `Literal["drive", "local", "disabled"]`, 기본 **`"disabled"`** 권장 | `architecture.md` §10.3. 코드 기본값이 `disabled`면 `.env` 없는 테스트·OpenAPI 내보내기가 외부 의존 없이 동작. `.env.example`은 이미 `local` |
| `DRIVE_INBOX_FOLDER_ID` | `drive_inbox_folder_id` | `str \| None = None` | `drive`일 때 필수 → `model_validator`로 검증(누락 시 시작 실패는 "설정 오류"라 허용) |
| `INBOX_LOCAL_PATH` | `inbox_local_path` | `Path`, 기본 `Path("./data/inbox")` (`.env.example`과 같게) | 개발 compose는 `/data/inbox` |
| `GOOGLE_APPLICATION_CREDENTIALS` | (선택) `google_application_credentials` | `Path \| None` | google-auth가 직접 읽는 표준 변수. Settings에 둘지 결정 D3 |
| (상수) 재시도 횟수 | — | `2` | `architecture.md` §8.2. 설정으로 뺄 필요 없음(요청 없음) |
| (상수) 업로드 타임아웃 / 헬스 체크 타임아웃 | — | 예: 30초 / 5초 | 결정 D6 |
| (상수) 청크 크기 | — | 예: 8 MiB(256 KiB 배수) 또는 기본 100 MiB | 결정 D5 |

`ALLOWED_EXTENSIONS`(`.env.example`)는 W-07 검증용이라 W-08 범위가 아니다.

---

## 10. 미정 사항 (선택지와 권장안)

| ID | 항목 | 선택지 | 권장안 |
|---|---|---|---|
| **D1 [핵심]** | `source=web` 기록 필드 | (a) `properties` (모든 앱에 보임) (b) `properties`+`appProperties` 둘 다 (c) `appProperties` 유지, RPA가 같은 프로젝트 자격 증명 사용 | **(a)**. 공식 문서상 `appProperties`는 요청한 앱 전용이라 UiPath가 못 읽을 가능성이 크다. RPA(④)와 합의 후 `architecture.md`·`input_flow.md`·`features.md` W-07·`research.md` 문구 수정 필요 |
| **D2 [핵심]** | OAuth 스코프 | (a) `drive.file` (b) `drive` | E-01 환경에서 (a)를 먼저 실측, 기존 폴더 접근이 안 되면 **(b) + 공유 드라이브(또는 `inbox/` 폴더) 기여자 역할**. 상수 하나로 관리 |
| D3 | 자격 증명 로드 방식 | (a) `google.auth.default(scopes=…)` — `GOOGLE_APPLICATION_CREDENTIALS` 자동 사용, Phase 3 Workload Identity 호환 (b) `Credentials.from_service_account_file(settings.google_application_credentials)` 명시 | **(a)**. 단, 키 파일 경로 존재 여부를 헬스 체크에서 원인으로 구분하고 싶으면 (b). Settings 필드 추가는 (b)일 때만 |
| **D4 [핵심]** | 503 변환 위치 | (a) 어댑터가 `InboxUnavailableError`, W-07 서비스가 `AppError(INBOX_UNAVAILABLE)`로 변환 (b) 어댑터가 `AppError` 직접 | **(a)**. 계층 규칙(Infra는 도메인 무관)과 O-02의 상태 판정에 유리 |
| D5 | 업로드 방식·청크 | (a) resumable, 청크 기본(100 MiB, 사실상 1회 PUT) (b) resumable, 8 MiB 청크 (c) multipart | **(a) 또는 (b)**. 재시도 중복 위험 때문에 (c)는 비권장. 100 MiB 한도에서는 (a)가 단순, 느린 망에서 재시도 단위를 줄이려면 (b) |
| D6 | 타임아웃 | 라이브러리 기본 60초 / 명시 | **명시**: 업로드 30초, `check()` 5초 안팎 **[가정, 실측 후 조정]** |
| **D7 [핵심]** | 앱 시작 시 Drive 자격 증명 오류 처리 | (a) 시작 실패(fail-fast) (b) 시작은 하고 업로드·헬스 체크에서 503/비정상 | **설정 누락(폴더 ID 없음)은 (a), 키 파일·인증 오류는 (b)**. Drive 문제로 로봇 API까지 멈추지 않게 한다(`test_app_smoke.py`도 개발자 `.env`에 덜 민감) |
| D8 | `disabled` 표현 | (a) `None` 주입, 사용처가 503 (b) `DisabledInboxWriter` | **(a)**가 단순. O-02는 `None`이면 `"disabled"` 표시 |
| D9 | `google-auth-httplib2`·`httplib2` 직접 의존성 명시 | (a) `pyproject.toml`에 추가 (b) 간접 의존성 유지 | **(a)**: 직접 import하는 패키지는 명시. mypy override에 `google_auth_httplib2.*`, `httplib2.*`, `google.auth.*` 필요 여부는 mypy 실행으로 확인 (C-01 소유 파일이므로 A와 공유) |
| D10 | 503에 `Retry-After` | (a) 없음 (b) `AppError`에 헤더 지원 추가 | **(a)**. 요청 없음. 프론트는 재시도 버튼으로 충분 |
| D11 | 로컬 파일명 충돌·금지 문자 | 충돌: (a) ` (n)` 접미사 (b) 예외 / 금지 문자: (c) 거부 (d) `_` 치환 | **(a)+(c)**: 개발 중 같은 샘플을 반복 업로드하는 일이 많아 접미사가 편하다. 경로 탈출은 항상 거부 |
| D12 | 로그에 파일명 기록 | (a) 기록 안 함 (b) 기록 | **(a)**, 파일 ID·크기·소요 시간·`request_id`로 추적. 팀 합의 시 (b) |
| D13 | 수동 Drive 테스트 마커 | (a) 새 마커 `drive` (b) 기존 `integration` 재사용 | **(a)**, 환경 변수(`TEST_DRIVE_FOLDER_ID` 등) 없으면 skip |
| D14 | 파일명 NFC 정규화 위치 | (a) W-07 서비스 (b) 어댑터 | **(a)**. 어댑터는 받은 이름을 그대로 쓴다. Dispatcher 담당자 매칭과 함께 RPA와 확인 |
| D15 | `check()` 결과 형태·캐시 | 예외 / 상태 객체, 캐시 여부 | O-02에서 결정. W-08은 예외 방식 + 원인 분류 정도만 제공 |

외부 의존 미결(이 모듈이 영향받는 것):
- E-01 발급·역할·폴더 단위 권한 가능 여부.
- 파일명 규칙 확정(`input_flow.md` §7 **[결정 필요]**) — W-08 동작에는 영향 없음, W-07 검증·안내 문구에 영향.
- RPA의 Drive 접근 방식(UiPath 액티비티 OAuth 앱 vs 서비스 계정, `features_rpa.md` P-06) — D1에 직접 영향.

---

## 11. 참고 자료
- Drive API — 업로드: https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Drive API — 공유 드라이브 지원: https://developers.google.com/workspace/drive/api/guides/enable-shareddrives
- Drive API — 공유 드라이브 개요(서비스 계정 저장 용량·역할): https://developers.google.com/workspace/drive/api/guides/about-shareddrives
- Drive API — 사용자 정의 속성(`properties`/`appProperties`): https://developers.google.com/workspace/drive/api/guides/properties
- Drive API — 오류 처리: https://developers.google.com/workspace/drive/api/guides/handle-errors
- Drive API — 사용 한도·지수 백오프: https://developers.google.com/workspace/drive/api/guides/limits
- Drive API — 스코프: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- google-api-python-client — 스레드 안전성: https://googleapis.github.io/google-api-python-client/docs/thread_safety.html
- google-api-python-client — 모킹: https://googleapis.github.io/google-api-python-client/docs/mocks.html
- 설치 소스: `.venv/Lib/site-packages/googleapiclient/http.py`(재시도 `:80-215`, `DEFAULT_CHUNK_SIZE` `:67`, `DEFAULT_HTTP_TIMEOUT_SEC` `:75`), `discovery.py:194-292`, `discovery_cache/documents/drive.v3.json`
- 커뮤니티(참고, 비공식): 서비스 계정 + 공유 드라이브 업로드 404 사례 — https://community.latenode.com/t/google-drive-api-v3-uploading-files-to-shared-drive-throws-404-error/25915 , https://nango.dev/blog/fix-google-drive-api-404-file-not-found
