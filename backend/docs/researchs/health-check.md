# 리서치 — 헬스 체크 (`GET /health`)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-25 |
| 대상 기능 | `features.md` O-02 헬스 체크 — "`GET /health` — DB, 음성 저장소, Drive `inbox/` 접근 확인" (P1, Phase 2, 선행 R-03·W-08 — 둘 다 `main`에 있음) |
| 근거 | `features.md` v0.2 §2.4·§3·§5·§6, `architecture.md` §3·§7.1·§8·§10·§11·§12, `docs/prd.md` §7·§8.3, `api/convention.md` v0.1, `plans/drive-inbox.md` §2·§9.4(H1~H7), `researchs/drive-inbox.md` §3·§4, `plans/common-module.md` #17·#18, `plans/api-convention.md`, `back_stack.md` §2.2·§6, `app/main.py`, `app/api/deps.py`, `app/api/robot/auth.py`, `app/api/web/uploads.py`, `app/core/{config,db,errors,logging,middleware}.py`, `app/infra/inbox/*`, `app/infra/storage/*`, `app/services/upload_service.py`, `scripts/export_openapi.py`, `deploy/docker-compose.dev.yml`, `Dockerfile.dev`, `.env.example`, `tests/conftest.py`, `tests/unit/{conftest,test_openapi,test_logging,test_uploads_api,test_inbox_drive,upload_fakes}.py`, `tests/integration/conftest.py` |

---

## 0. 핵심 요약

1. **`/health` 라우트는 아직 없다.** 코드(`app/`)·테스트 어디에도 `/health`나 유사 엔드포인트가 없다. 재사용할 확인 함수는 모두 준비돼 있다: `AudioStorage.check()`(R-03), `InboxWriter.check()`(W-08), `app.state.session_factory`(DB).
2. **미들웨어 영향 없음.** `RobotAuthMiddleware`는 `/api/robot` 경로에만 적용되므로(`auth.py:30-31,45`) `/health`는 키·IP 검사를 받지 않는다. `RequestIdMiddleware`가 `X-Request-Id`를 붙이고 접근 로그를 남긴다(제외 규칙 없음, `common-module.md` #17).
3. **[핵심] 전체 판정 규칙이 정해져 있지 않다.** 문서는 "세 구성요소 접근 확인"만 말한다. Drive `inbox/`는 웹 업로드(W-07)에만 쓰이고 로봇 흐름(등록·적재)은 Drive와 무관하게 동작한다(`drive-inbox.md` D7). Drive 장애를 전체 503으로 볼지, 200 + "부분 장애"로 볼지 정해야 한다(§5, 결정 D1).
4. **[핵심] Drive `check()`는 느릴 수 있다.** 소켓 타임아웃 5초(`drive.py:30`), 자격 증명이 없으면 `google.auth.default`가 GCE 메타데이터 서버 확인을 시도해 호출마다 약 3초가 더 붙고 실패는 캐시되지 않는다(H5, `drive.py:50-53`). 결과 캐시(TTL)와 동시 호출 억제가 필요하다(§6, 결정 D3).
5. **DB 확인에 연결 타임아웃이 없다.** `create_engine(database_url, pool_pre_ping=True)`만 있고(`db.py:9`) `connect_timeout`이 없어, DB 호스트가 응답하지 않으면 OS TCP 타임아웃(수십 초~2분)까지 묶일 수 있다. 풀이 고갈되면 `pool_timeout` 기본 30초를 기다린다(§6.2, 결정 D4).
6. **에러 형식 예외가 생긴다.** 실패 시 503 본문을 §7.2 에러 형식(`{code,message,detail}`)이 아니라 헬스 응답 형식으로 돌려주는 것이 일반 관행이다. 규약 문서에 예외로 적어야 한다(결정 D2).
7. **음성 저장소 `check()`는 "쓰기 시도"가 아니라 권한 확인이다.** `mkdir` + `os.access(W_OK)`(`local.py:101-107`)라 디스크 가득 참은 잡지 못한다. `architecture.md` §12의 "음성 저장소 쓰기"와 표현이 다르다(§4.2, 결정 D9).
8. **Docker `HEALTHCHECK`는 아직 어디에도 없다.** `Dockerfile.dev`·`docker-compose.dev.yml`의 `api`에 healthcheck가 없고(`db`만 `pg_isready`), 운영 Dockerfile·compose는 O-01(A 담당) 몫이다. 베이스 이미지 `python:3.12-slim`에는 `curl`이 없어 `python -c` 방식이 필요하다(§9).

---

## 1. 요구사항 출처

| 출처 | 내용 |
|---|---|
| `features.md` O-02 (`:96`) | `GET /health` — DB, 음성 저장소, Drive `inbox/` 접근 확인. P1, Phase 2, 담당 B, 선행 R-03·W-08 |
| `features.md` §3 E-01 (`:115`) | 서비스 계정·공유 드라이브 권한 — W-08·W-07·**O-02**가 필요 |
| `features.md` §5 (`:144`) | O-02는 R-03 음성 사본 저장소 인터페이스를 사용 |
| `architecture.md` §7.1 (`:382`) | `/health` — 소비자 "모니터링", 인증 없음, "DB·음성 저장소·Drive `inbox/` 접근 확인" |
| `architecture.md` §12 (`:560`) | "`GET /health` → DB `SELECT 1`, 음성 저장소 쓰기, Drive `inbox/` 폴더 메타데이터 조회 가능 여부" |
| `architecture.md` §8.2 (`:436`) | `InboxWriter.check()` — 파일 생성 없이 쓰기 가능 여부 확인(헬스 체크). 실패는 `InboxUnavailableError` |
| `architecture.md` §10.1·§11 | 8000 포트는 VM 방화벽으로 사내망·로봇 PC만 허용. 리버스 프록시 없음. Uvicorn `workers=2~4` |
| `prd.md` §8.3 (`research.md:346`) | "헬스 체크: `GET /health` (DB 연결 포함)" |
| `prd.md` §7 | 가용성 수치 요구(SLA)는 없음. 신뢰성 항목은 처리 흐름(선등록·재시도·정체 표시) 위주 |
| `plans/drive-inbox.md` §1.2 (`:36`) | "`GET /health`, `check()` 결과 캐시·응답 노출 형식"은 O-02 범위 |
| `plans/drive-inbox.md` §9.4 | H1~H7 인계 사항(§4.3에 정리) |
| `plans/common-module.md` §1.3 (`:38`) | `GET /health`는 공통 모듈 범위 밖(별도 작업) |
| `plans/common-module.md` #17 (`:81`) | "`/health`는 아직 없으므로 (접근 로그) 제외 규칙 없음" — O-02에서 재검토 대상 |
| `plans/api-convention.md` (`:92`) | 앱 단위 `responses=error_responses(VALIDATION_ERROR, INTERNAL_ERROR)` 때문에 파라미터 없는 `/health`에도 422가 문서에 붙는 부정확은 감수하기로 함 |
| `plans/call-list-detail.md` (`:38`) | 엔진 `dispose()`(lifespan)는 "필요해지면 O-02(헬스 체크) 등에서 추가" |
| `plans/web-upload.md` (`:38`) | 업로드 전 사전 `writer.check()`는 하지 않음 — O-02 몫 |

정리: 범위는 **세 구성요소 확인 + 응답 형식 + 캐시·타임아웃**이다. 소비자("모니터링")가 구체적으로 무엇인지(Docker healthcheck, 외부 모니터, 사람이 curl, 로봇 사전 점검)는 문서에 없다(§12 팀 확인).

---

## 2. 현재 코드 상태

### 2.1 앱 구성 (`app/main.py`)

| 줄 | 내용 | O-02 관련 |
|---|---|---|
| `:37-45` | `FastAPI(openapi_url=... if docs_enabled, responses=error_responses(422, 500), generate_unique_id_function=route.name)` | `/health`를 스키마에 넣으면 422·500이 자동 문서화되고 operationId는 함수 이름 |
| `:48` | `app.state.settings` | |
| `:50` | `app.state.session_factory = create_session_factory(...)` — 엔진만 만들고 연결하지 않음 | DB 확인에 사용 |
| `:52` | `app.state.inbox_writer = create_inbox_writer(settings)` — `None`이면 disabled | Drive/로컬 inbox 확인 |
| `:54` | `app.state.audio_storage = create_audio_storage(settings)` | 음성 저장소 확인 |
| `:55-58` | 라우터 4개 등록(`calls`, `robot_calls`, `stats`, `uploads`) | `/health` 라우터 추가 위치 |
| `:61-77` | 미들웨어 순서(바깥→안): RequestId → CORS → UnhandledError → RobotAuth → BodySizeLimit → 라우터 | §2.4 |
| — | lifespan 없음, 엔진 `dispose()` 없음 | |

### 2.2 의존성 (`app/api/deps.py`)

| 함수 | 반환 | O-02 재사용 |
|---|---|---|
| `get_db(request)` (`:20-24`) | `session_factory()` 컨텍스트로 세션 하나 yield | DB 확인. 테스트는 `app.dependency_overrides[get_db]`로 교체 가능 |
| `get_inbox_writer(request)` (`:30-33`) | `InboxWriter \| None` | 그대로 사용 |
| `get_audio_storage(request)` (`:44-46`) | `AudioStorage` | 그대로 사용 |
| `get_settings_from_app(request)` (`:49-51`) | `Settings` | TTL 등 설정이 생기면 사용 |

### 2.3 DB (`app/core/db.py`, `config.py`)

- `create_engine(database_url, pool_pre_ping=True)`, `sessionmaker(expire_on_commit=False)` (`db.py:9-10`).
- `connect_args`(예: `connect_timeout`) 없음 → psycopg(libpq) 기본값은 **연결 타임아웃 없음**(OS TCP 타임아웃까지 대기).
- 풀 설정은 SQLAlchemy 기본(`QueuePool`, `pool_size=5`, `max_overflow=10`, `pool_timeout=30`). 풀이 고갈되면 체크아웃이 최대 30초 대기 후 `sqlalchemy.exc.TimeoutError`.
- `pool_pre_ping=True`라 체크아웃마다 가벼운 ping을 이미 수행한다. `SELECT 1`은 사실상 "체크아웃 + ping + 쿼리"다.
- 기본 `DATABASE_URL`은 `localhost:5433`(개발용). 단위 테스트에서 실제 DB에 붙지 않게 하려면 `get_db` 오버라이드나 가짜 세션 팩토리가 필요하다.
- 실패 예외: 연결 실패·서버 종료는 `sqlalchemy.exc.OperationalError`(psycopg `OperationalError` 래핑), 풀 대기 초과는 `sqlalchemy.exc.TimeoutError`, 둘 다 `SQLAlchemyError` 하위. `str(OperationalError)`에는 호스트·포트·DB 이름과 SQL이 들어간다 → 응답·로그에 원문 금지(§8).

### 2.4 미들웨어와 `/health`

| 미들웨어 | `/health`에 미치는 영향 |
|---|---|
| `RequestIdMiddleware` (`middleware.py:21-63`) | `X-Request-Id` 부여, 요청 종료 시 `app.access` 로거로 `request` 이벤트(info) 기록. `/health` 제외 규칙 없음 → 주기 호출마다 1줄 |
| `CORSMiddleware` | 브라우저 호출이 아니면 무관. 프론트가 `/health`를 부를 계획은 확인되지 않음 |
| `UnhandledErrorMiddleware` (`:66-91`) | 헬스 라우트에서 잡지 않은 예외는 §7.2 형식 500 + `app.error` exception 로그 |
| `RobotAuthMiddleware` (`auth.py:44-61`) | `_is_robot_path`가 `path == "/api/robot"` 또는 `startswith("/api/robot/")`일 때만 동작 → **`/health`는 인증·IP 검사 없음** |
| `BodySizeLimitMiddleware` | GET이라 무관 |

### 2.5 음성 저장소 (`app/infra/storage/`)

```python
# base.py:54-56
def check(self) -> None:
    """저장소에 쓸 수 있는지 확인한다 (헬스 체크, O-02). 불가하면 StorageError."""

# local.py:101-107
def check(self) -> None:
    try:
        self._root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"저장소 폴더를 만들 수 없습니다: {exc.__class__.__name__}") from exc
    if not os.access(self._root, os.W_OK):
        raise StorageError("저장소 폴더에 쓸 수 없습니다")
```

- 동작: 폴더가 없으면 만든다(첫 호출 부작용), 그 뒤 쓰기 권한만 확인. **실제 파일을 쓰지 않는다** → 디스크 가득 참·inode 고갈·쓰기 I/O 오류는 감지하지 못한다. 읽기 전용 마운트는 `access(2)`가 `EROFS`를 돌려주므로 감지된다.
- 컨테이너를 root로 실행하면 권한 비트와 관계없이 `W_OK`가 참이 되는 경우가 많다(읽기 전용 파일시스템 제외). 운영 이미지는 non-root 예정(O-01).
- 실패 예외 `StorageError`에는 `InboxUnavailableError.reason` 같은 **분류 속성이 없다**. 메시지는 한국어 문장(+ 예외 클래스 이름). 응답에 원인을 넣으려면 O-02가 고정 문자열로 바꾸거나, `type(exc.__cause__).__name__` 등을 써야 한다(결정 D6).
- 블로킹 I/O이지만 로컬 디스크라 빠르다. NFS 등 원격 볼륨이면 멈출 수 있으나 현재 구성(Docker 볼륨)에서는 고려 대상 아님.
- `create_audio_storage`는 디스크를 건드리지 않는다(`__init__.py:26-30`) → 앱 시작 시 저장소 문제는 첫 저장·헬스 체크 때 드러난다.

### 2.6 inbox (`app/infra/inbox/`)

| 구현 | `check()` 동작 | 실패 `reason` |
|---|---|---|
| `None` (`INBOX_BACKEND=disabled`, 기본값) | 호출하지 않음 | — (H1: O-02는 `"disabled"`, 실패 아님) |
| `LocalInboxWriter` (`local.py:68-74`) | `mkdir` + `os.access(W_OK)` | `OSError` 클래스 이름(예: `PermissionError`), `not_writable` |
| `DriveInboxWriter` (`drive.py:132-147`) | `files.get(fileId=folder, fields="id,mimeType,trashed,capabilities/canAddChildren", supportsAllDrives=True).execute(num_retries=0)`, 타임아웃 5초 | `http_<상태>`(예: `http_404`·`http_403`), 예외 클래스 이름(`DefaultCredentialsError`, `RefreshError`, `TimeoutError`, `ServerNotFoundError` 등), `not_folder`, `trashed`, `cannot_add_children` |

세부:
- `InboxUnavailableError(reason)` (`base.py:6-15`): `reason`은 "로그·헬스 체크용 짧은 분류 값". 파일명·폴더 ID·키 경로·서비스 계정 정보는 넣지 않는다.
- Drive 오류는 `_fail()`이 `inbox_check_failed`(warning, `backend`, `reason`, `drive_reason`)를 로그로 남긴다(`drive.py:149-152`). **판정 실패(`not_folder`·`trashed`·`cannot_add_children`)와 `LocalInboxWriter.check()` 실패는 로그 없이 예외만** 던진다 → 기록은 O-02 몫(`plans/drive-inbox.md:120`).
- 자격 증명은 첫 호출 때 `google.auth.default(scopes=...)`로 읽고 성공하면 인스턴스에 저장한다(`drive.py:47-53`). **실패하면 저장하지 않으므로 다음 호출에서 다시 시도한다** → 자격 증명이 없는 환경에서 매 헬스 체크마다 GCE 메타데이터 확인 지연(H5).
- 토큰 갱신(`oauth2.googleapis.com`)은 `AuthorizedHttp`가 같은 `Http(timeout=5)`로 수행하므로 갱신 요청도 5초 소켓 타임아웃을 받는다. 즉 Drive 확인 최악 시간 ≈ (자격 증명 탐색 지연) + 토큰 갱신(≤5초 무응답) + `files.get`(≤5초 무응답). 5초는 "소켓 무응답 시간"이라 전체 소요 상한이 아니다(`researchs/drive-inbox.md:192`).
- 스코프는 `drive.file`(`drive.py:23`). E-01 이후 실측에서 기존 `inbox/`에 `files.get`이 404면 `drive`로 바꾼다(`plans/drive-inbox.md` §9.3 E1). 그 전까지 **운영 Drive 헬스는 `http_404`로 실패할 가능성이 있다** — O-02 버그가 아니라 E1 미해결 신호다.
- `httplib2.Http`·`build()` 결과는 호출마다 새로 만든다(스레드 안전성, `drive.py:34`). 여러 스레드가 동시에 `check()`를 불러도 안전하다.

### 2.7 기존 라우트 작성 패턴 (`app/api/web/uploads.py`)

- `APIRouter(prefix="/api/uploads", tags=["uploads"])`, `responses=error_responses(...)`.
- 블로킹 호출은 `def`(동기) 라우트로 둬 워커 스레드풀에서 실행한다(`uploads.py:32` 주석, H3).
- 서비스는 `deps.py`의 팩토리 함수로 주입한다(`get_upload_service`).
- `InboxUnavailableError`는 서비스가 `reason`만 로그에 남기고 `exc_info`를 쓰지 않는다(`upload_service.py:123-125`, H7).

### 2.8 배포 파일

| 파일 | healthcheck |
|---|---|
| `deploy/docker-compose.dev.yml` | `db`: `pg_isready -U callcenter -d callcenter`, interval 5s, timeout 3s, retries 10. `api`: **없음**. `api.depends_on.db.condition: service_healthy` |
| `backend/Dockerfile.dev` | `HEALTHCHECK` 없음. `python:3.12-slim` → `curl`·`wget` 없음. 실행은 `uvicorn --reload`(단일 프로세스) |
| 운영 `Dockerfile`·`docker-compose.yml` | 아직 없음(O-01, A 담당). `architecture.md` §3.2에 `deploy/docker-compose.yml`(api, db) 예정 |

---

## 3. 외부 관행 (스펙·관례)

### 3.1 liveness vs readiness

| 구분 | 질문 | 의존 대상 확인 | 실패 시 조치(오케스트레이터) |
|---|---|---|---|
| liveness | "프로세스가 살아 응답하는가?" | **하지 않는 것이 관행**(의존 대상 장애로 앱을 재시작해도 낫지 않고, 연쇄 재시작을 부른다) | 컨테이너 재시작 |
| readiness | "지금 요청을 처리할 수 있는가?" | DB 등 필수 의존 대상 확인 | 트래픽에서 제외 |
| (deep/diagnostic) | "어느 구성요소가 문제인가?" | 선택 의존 대상까지 확인, 구성요소별 상태 | 사람·모니터링 경보 |

- Kubernetes 문서·Google SRE 관행 모두 liveness 프로브에 외부 의존을 넣지 말 것을 권한다. Spring Boot Actuator도 `/actuator/health/liveness`·`/readiness`를 나누고, 외부 시스템 확인은 readiness·전체 health에만 넣는다.
- 이 프로젝트 환경: 사내 VM 단일 호스트, Docker Compose, 로드밸런서·오케스트레이터 없음(`architecture.md` §10.1). **트래픽 제외(readiness)를 수행할 주체가 없다.** Docker Engine(비 Swarm)은 `unhealthy` 상태가 되어도 **컨테이너를 재시작하지 않는다**(`restart` 정책은 프로세스 종료에만 반응). `unhealthy`의 실질 효과는 `docker ps` 표시, `depends_on: condition: service_healthy`, autoheal 같은 별도 도구뿐이다.
- 따라서 이 프로젝트에서 `/health`는 사실상 **진단용(deep) 체크**다. liveness 전용 경로를 따로 둘지는 Docker healthcheck를 어떻게 쓰느냐에 달렸다(결정 D7).

### 3.2 응답 형식

| 관행 | 형식 | 상태 코드 |
|---|---|---|
| IETF draft `draft-inadarei-api-health-check` ("Health Check Response Format for HTTP APIs", 미표준 초안) | `Content-Type: application/health+json`, `{"status": "pass"\|"fail"\|"warn", "checks": {"<component>:<measurement>": [{"status": ..., "time": ..., "output": ...}]}}` | `pass`·`warn` → 2xx, `fail` → 4xx/5xx(보통 503) |
| Spring Boot Actuator | `{"status": "UP"\|"DOWN"\|"OUT_OF_SERVICE", "components": {"db": {"status": "UP"}, ...}}` (상세 노출은 `show-details` 설정) | `DOWN`·`OUT_OF_SERVICE` → 503 |
| 흔한 FastAPI 예제 | `{"status": "ok", "checks": {"db": "ok", ...}}` | 하나라도 실패하면 503 |

공통점: **구성요소별 상태 + 전체 상태**, 전체가 실패면 **503**, 부분 장애(`warn`·degraded)는 **200**. 503 본문도 같은 헬스 형식으로 돌려준다(어느 구성요소가 문제인지 보이게).

### 3.3 타임아웃·캐시

- 헬스 체크 자체가 모니터 타임아웃보다 오래 걸리면 안 된다. Docker `HEALTHCHECK` 기본값은 `interval=30s`, `timeout=30s`, `retries=3`, `start_period=0s`. 체크 전체 소요가 `timeout` 안이어야 한다.
- 의존 대상별 타임아웃을 짧게(수 초) 두고, 느린 외부 호출은 결과를 짧게 캐시하는 것이 관행(외부 API 할당량·지연 보호, 헬스 체크 폭주 시 외부 호출 증폭 방지).
- 캐시는 **프로세스 메모리**면 충분하다. Uvicorn `--workers 2~4`(`back_stack.md:52`)면 워커마다 따로 캐시된다(워커 수 × 주기만큼 호출) — Drive 할당량에 비해 무시할 수준(`researchs/drive-inbox.md:205`).
- 캐시 만료 순간 여러 요청이 동시에 외부 호출을 하지 않도록 잠금(또는 "하나만 갱신, 나머지는 직전 값")을 두는 것이 관행.

### 3.4 정보 노출

- OWASP·Spring Boot 기본값은 **인증 없는 호출자에게 전체 상태만** 보여 주고 상세(구성요소별 오류 메시지·버전·호스트)는 숨긴다.
- 이 프로젝트는 인증이 없고 접근 통제를 방화벽(사내망·로봇 PC)에 맡긴다(`architecture.md` §11). 사내망 사용자 누구나 `/health`를 볼 수 있다.
- `convention.md` §6: 응답에 음성 사본 내부 키, API Key, 서비스 계정 정보를 넣지 않는다. §3.4-4: 예외 원문·SQL·스택·내부 경로를 넣지 않는다.
- 구성요소 이름과 `ok/fail`은 일반적으로 공개해도 되는 수준이다. 원인 분류(`http_404`, `RefreshError`)는 비밀은 아니지만 공격 표면 정보(인증 방식 등)를 조금 드러낸다(H2: "값에는 비밀 정보가 없음").

### 3.5 동기 엔드포인트·스레드풀

- FastAPI는 `def` 라우트를 AnyIO 스레드풀(기본 토큰 40개)에서 실행한다. 의존성 함수도 `def`면 스레드풀에서 실행된다.
- 세 확인 모두 블로킹(SQLAlchemy 동기, 파일시스템, httplib2) → **`def` 라우트**가 자연스럽다(H3, `researchs/drive-inbox.md:209` 권장).
- 캐시 없이 Drive가 느려지면 헬스 요청마다 스레드 하나가 최대 수~십수 초 묶인다. 주기 호출이 겹치면 스레드풀을 소모해 다른 `def` 라우트(업로드·통계 등)까지 지연시킬 수 있다 → 캐시 + 잠금이 이 위험도 줄인다.
- 세 확인을 병렬(스레드)로 돌리면 최악 시간이 합이 아니라 최댓값이 되지만, 코드가 복잡해진다. DB·저장소는 정상이면 수 ms라 순차로도 충분하다.

### 3.6 OpenAPI 포함 여부

- FastAPI 라우트는 기본으로 스키마에 포함된다. `include_in_schema=False`로 뺄 수 있다.
- 포함하면: `docs/api/openapi.json` 재생성 필요(`test_committed_openapi_is_up_to_date`가 강제), 앱 단위 422·500이 자동으로 붙음(`plans/api-convention.md:92`에서 감수하기로 함), operationId는 함수 이름(고유성 테스트 `test_operation_ids_are_unique_in_real_app`), 태그 규칙(`convention.md` §7-4)에 `health` 태그가 없으므로 추가 필요.
- 소비자가 프론트(타입 생성)·로봇(계약)이 아니라 운영·모니터링이면 계약 파일에 넣을 실익이 작다. 반대로 RPA가 사전 점검으로 부를 계획이면 계약에 넣는 편이 맞다(§12).

---

## 4. 재사용 지점과 인계 사항

### 4.1 재사용 지점

| 대상 | 위치 | 쓰는 방법 |
|---|---|---|
| DB 세션 | `deps.get_db` / `app.state.session_factory` | `session.execute(text("SELECT 1"))` |
| 음성 저장소 | `deps.get_audio_storage` → `.check()` | `StorageError`면 실패 |
| inbox | `deps.get_inbox_writer` → `None`이면 disabled, 아니면 `.check()` | `InboxUnavailableError.reason` |
| 로거 | `structlog.stdlib.get_logger("app.<이름>")` | 기존 이름: `app.access`, `app.error`, `app.inbox`, `app.upload`, `app.auth` |
| 응답 모델 기반 | `pydantic.BaseModel`, `typing.Literal` | `schemas/`에 둠(규약 §5.5) |
| 테스트 앱 | `tests/unit/conftest.py` `build_app(**overrides)` | `app.state.inbox_writer = Fake()`, `app.state.audio_storage = Fake()`, `app.dependency_overrides[get_db]` |
| 로그 검증 | `tests/unit/test_logging.py` `_log_lines(capsys)` | JSON 한 줄씩 파싱 |
| 가짜 writer | `tests/unit/upload_fakes.py` `FakeWriter.check()` | 현재 항상 성공. 실패용 가짜는 헬스 테스트에서 새로 만들거나 확장 |
| 실제 DB | `tests/integration/conftest.py` `api` 픽스처(`get_db` 오버라이드) | 정상 경로 통합 테스트 |

### 4.2 계층 배치 후보

`architecture.md` §3.1: Router는 "DB 직접 접근 금지", Service는 "HTTP 객체 의존 금지", Infra는 "도메인 규칙 금지".

| 안 | 구성 | 평가 |
|---|---|---|
| (a) 라우터 + `HealthService` | `app/api/health.py`(라우터, `def`), `app/services/health_service.py`(세 확인·판정·캐시), `app/schemas/health.py`(응답 모델), `deps.get_health_service` | 계층 규칙과 일치. 판정 규칙을 단위 테스트하기 쉽다 |
| (b) 라우터 하나에 모두 | `app/api/health.py`에 `SELECT 1`·`check()` 직접 호출 | 짧지만 "Router에서 DB 직접 접근 금지"에 어긋남 |
| (c) DB 확인을 Repository에 | `CallRepository`에 `ping()` 추가 | 저장소 책임과 무관한 메서드가 섞임. `SELECT 1` 한 줄이면 서비스에서 세션으로 충분 |

캐시 상태는 요청을 넘어 유지돼야 하므로 서비스 인스턴스(요청마다 생성)가 아니라 **`app.state`에 둔 객체**(예: `app.state.inbox_health_cache`)나 `create_app`에서 만든 서비스 싱글턴에 둔다. 모듈 전역에 두면 테스트 간 상태가 샌다(`create_app`을 테스트마다 새로 만드는 패턴과 충돌).

라우터 위치: `/health`는 웹(`api/web/`)도 로봇(`api/robot/`)도 아니다. `app/api/health.py`(또는 `api/ops/`)가 자연스럽다. `architecture.md` §3.2 디렉터리 구조에는 아직 없음 → 반영 필요.

### 4.3 `plans/drive-inbox.md` §9.4 인계 사항 처리

| # | 인계 | O-02 처리 방향 |
|---|---|---|
| H1 | `writer is None` → O-02는 `"disabled"`(실패 아님) | 구성요소 상태 `DISABLED`(또는 `disabled`), 전체 판정에서 제외 |
| H2 | `reason` 노출 여부는 O-02에서 결정 | 결정 D6 |
| H3 | `check()`는 블로킹 → `def` 라우트 | `def` 라우트 |
| H5 | 자격 증명 없을 때 호출마다 약 3초 지연, 실패는 캐시 안 됨, 비 GCP는 `NO_GCE_CHECK=true` | 결과 캐시(실패 포함, 결정 D3) + 운영 `.env`에 `NO_GCE_CHECK=true` 권장(O-03과 함께, §12) |
| H7 | `InboxUnavailableError.__cause__`에 키 경로 등 가능 → `exc_info` 금지, `reason`만 | 로그에 `reason`만. DB·저장소 예외도 같은 원칙(§8) |
| (참고) `:120` | 판정 실패·로컬 실패는 로그 없이 예외만 → O-02가 기록 | O-02가 `health_check_failed` 류 로그를 남김(§7) |
| (참고) `:121` | `googleapiclient` 재시도 경고 소음이 문제면 O-02에서 재검토 | `check()`는 `num_retries=0`이라 경고 없음 → 변경 불필요 |

---

## 5. 응답 계약 후보

### 5.1 본문

**안 A — 구성요소별 상태 문자열(권장)**

```json
{
  "status": "OK",
  "checks": {
    "db": "OK",
    "audio_storage": "OK",
    "inbox": "DISABLED"
  }
}
```

```json
// Drive 장애 (D1 권장안 기준: 200)
{ "status": "DEGRADED", "checks": { "db": "OK", "audio_storage": "OK", "inbox": "FAIL" } }

// DB 장애: 503
{ "status": "FAIL", "checks": { "db": "FAIL", "audio_storage": "OK", "inbox": "OK" } }
```

**안 B — 구성요소별 객체(원인 포함)**

```json
{
  "status": "DEGRADED",
  "checks": {
    "db": { "status": "OK", "reason": null },
    "audio_storage": { "status": "OK", "reason": null },
    "inbox": { "status": "FAIL", "reason": "http_404" }
  }
}
```

**안 C — IETF draft 형식** (`application/health+json`, `pass/warn/fail`, `checks`에 배열). 표준 초안이지만 규약 §5.3(enum 대문자)과 맞지 않고 소비 도구가 이 형식을 요구하지 않는 한 실익이 작다.

참고 사항:
- 규약 §5.3은 응답 enum을 **영문 대문자 상수**로 정했다 → `OK`/`DEGRADED`/`FAIL`/`DISABLED`. 업계 관례(`ok`, `UP/DOWN`, `pass/fail`)와 다르지만 규약 일관성을 따르는 쪽을 권장(결정 D5).
- 규약 §2.3-3: 객체로 감싸 필드 추가가 호환 변경이 되게 → 안 A도 최상위 객체라 충족. 안 A→B 전환은 `checks` 값 타입이 바뀌는 **비호환 변경**이므로 처음에 정하는 것이 좋다.
- 규약 §5.2: 값 없는 필드는 `null`로 보냄 → 안 B의 `reason`은 정상일 때 `null`.
- 키 이름: `audio_storage`·`inbox`는 설정 이름(`AUDIO_STORAGE_*`, `INBOX_BACKEND`)과 맞춘 snake_case. `drive`로 쓰면 `INBOX_BACKEND=local` 개발 환경에서 이름이 틀린다.
- 응답 헤더 `Cache-Control: no-store` 권장(중간 캐시 없음이 전제지만 모니터 도구·브라우저 캐시 방지).
- `checked_at`(캐시된 결과의 확인 시각) 같은 추가 필드는 선택. 넣으면 규약 §5.1에 따라 `KstDatetime`.

### 5.2 상태 코드

| 전체 상태 | HTTP |
|---|---|
| `OK` | 200 |
| `DEGRADED` (선택 구성요소만 실패) | 200 (D1 권장안) |
| `FAIL` (필수 구성요소 실패) | 503 |

503 본문은 §7.2 에러 형식이 아니라 위 헬스 형식이다. `convention.md` §3에 "`/health`는 예외" 한 줄이 필요하다(결정 D2). `ErrorCode`에 새 코드를 추가하지 않는다(헬스 503은 에러 응답이 아님).

---

## 6. 구성요소별 판정 규칙·타임아웃·캐시

### 6.1 판정 규칙 (권장안)

| 구성요소 | 확인 | OK | FAIL | DISABLED | 전체 판정 영향 |
|---|---|---|---|---|---|
| `db` | `SELECT 1` (세션 하나, 결과 확인) | 성공 | `SQLAlchemyError`(연결 실패·풀 대기 초과·타임아웃) | — | **필수**: FAIL → 전체 `FAIL`(503). 로봇 등록·적재·모든 조회가 DB 의존 |
| `audio_storage` | `AudioStorage.check()` | 예외 없음 | `StorageError` | — | **필수**: FAIL → 전체 `FAIL`(503). 로봇 등록(R-04)이 사본 저장 실패로 깨짐 |
| `inbox` | `None`이면 확인 안 함, 아니면 `InboxWriter.check()` | 예외 없음 | `InboxUnavailableError` | `writer is None` (H1) | **선택**: FAIL → 전체 `DEGRADED`(200). DISABLED는 판정에서 제외(Phase 1 정상 구성, `architecture.md` §14) |

- 위 세 종류 외의 예외(버그)는 잡지 않고 500으로 올리는 안과, 구성요소 FAIL로 흡수하는 안이 있다. 헬스 엔드포인트가 버그로 500이 되면 모니터 입장에서는 "비정상"이라 결과는 같다. 다만 500이면 `UnhandledErrorMiddleware`가 스택을 `app.error`로 남겨 원인 파악이 쉽다 → **선언된 예외만 잡는 안** 권장(드라이브 어댑터의 `_DRIVE_ERRORS` 방침과 같음, `drive.py:37`).
- DB 확인은 `session.execute(text("SELECT 1"))` 뒤 세션을 닫는 것으로 충분하다(커밋 불필요, `get_db`가 닫음). `scalar_one() == 1`까지 확인해도 비용 차이 없음.

### 6.2 타임아웃

| 구성요소 | 현재 상한 | 문제 | 선택지 |
|---|---|---|---|
| DB 연결 | 없음(libpq 기본: OS TCP 타임아웃) | 호스트 무응답 시 수십 초~2분 | (a) 엔진 전체에 `connect_args={"connect_timeout": N}` (b) 헬스 전용 엔진 (c) 그대로 |
| DB 풀 체크아웃 | `pool_timeout=30`(기본) | 풀 고갈 시 30초 대기 | 풀 고갈 자체가 장애 신호라 그대로 두거나, 헬스 전용 엔진(`NullPool`)으로 분리 |
| DB 쿼리 | 없음 | `SELECT 1`은 사실상 즉시 끝남. 잠금 대기 없음 | `SET LOCAL statement_timeout`은 이득이 거의 없음 |
| 음성 저장소 | 없음 | 로컬 디스크라 사실상 즉시 | 그대로 |
| Drive | 소켓 무응답 5초(`_CHECK_TIMEOUT_SEC`) × (토큰 갱신 + `files.get`) + 자격 증명 탐색 지연(H5) | 최악 10초+ | 캐시로 빈도 억제(6.3). 상수 조정은 E-01 이후 실측(E5) |

- 운영 환경은 DB가 같은 Compose 네트워크의 컨테이너라, DB가 내려가면 보통 "connection refused"·DNS 실패로 **즉시** 실패한다. 무응답(패킷 유실)은 VM 네트워크 장애 같은 드문 경우다. 그래도 libpq 기본값이 무제한이므로 `connect_timeout`(예: 5초)을 엔진 전체에 주는 것이 다른 API에도 이롭다(결정 D4). `connect_timeout`은 libpq에서 2초 미만이면 2초로 올려 처리된다.
- 순차 실행 시 정상 최악 ≈ DB(≤5초, D4 적용 시) + 저장소(≈0) + Drive(캐시 히트 0 / 미스 시 ≤10초 남짓). Docker healthcheck `timeout`은 이보다 넉넉히(예: 15~20초) 잡거나, D7로 healthcheck에서 Drive를 빼야 한다.

### 6.3 캐시

| 항목 | 권장 | 이유 |
|---|---|---|
| 대상 | **inbox만** | DB·저장소는 수 ms. 캐시하면 장애 감지가 늦어질 뿐 |
| TTL | 성공·실패 모두 **30초** 내외(설정 변수 대신 상수로 시작) | 모니터 주기(30초 전후)와 비슷하게 두면 Drive 호출은 워커당 분당 2회 이하. 실패도 캐시해야 H5 지연이 매 요청 반복되지 않는다. 실패만 짧게(예: 10초) 두는 변형 가능 |
| 범위 | 프로세스(워커)별 메모리, `create_app` 안에서 만들어 `app.state`에 보관 | 테스트 격리, 다중 워커여도 문제 없음 |
| 동시성 | `threading.Lock`으로 갱신을 하나로 직렬화(잠금 중 다른 요청은 기다렸다가 갱신된 값 사용) | `def` 라우트는 스레드풀에서 동시 실행됨. 만료 순간 동시 Drive 호출 방지 |
| 시간원 | `time.monotonic` 주입 가능하게 | 테스트에서 TTL 경과를 가짜 시계로 검증 |
| 저장 내용 | `(상태, reason, 확인 시각)` | 로그는 실제 확인했을 때만(캐시 히트 때 반복 로그 방지) |

대안: 백그라운드 주기 작업으로 미리 확인해 두고 `/health`는 값만 읽기. 응답 지연이 0이지만 lifespan·스레드 관리가 생기고 앱 시작 시 Drive 호출이 발생해 D7(시작 경로에서 외부 접근 금지, `plans/drive-inbox.md` §10-1) 원칙과 충돌 → 비권장.

---

## 7. 로그

| 상황 | 현재 | 권장 |
|---|---|---|
| 모든 `/health` 요청 | `app.access` `request` info 1줄(`RequestIdMiddleware`) | 결정 D8. 30초 주기면 하루 2,880줄/모니터 — Docker 로그 로테이션(`architecture.md` §12)이 있어 감당 가능 |
| Drive 호출 오류 | `app.inbox` `inbox_check_failed` warning(`reason`, `drive_reason`) | 그대로(어댑터가 남김) |
| Drive 판정 실패·로컬 inbox 실패 | 로그 없음 | O-02가 남김 |
| DB·저장소 실패 | 해당 없음(아직 호출자 없음) | O-02가 남김 |

권장 이벤트: 로거 `app.health`, 이벤트 `health_check_failed`(warning), 필드 `component`(`db`/`audio_storage`/`inbox`), `reason`(분류 문자열). 규칙:
- `exc_info` 금지(H7). DB는 `type(exc).__name__`(예: `OperationalError`), 저장소는 고정 문자열 또는 원인 예외 클래스 이름, inbox는 `exc.reason`.
- `str(exc)` 금지: SQLAlchemy 메시지에 호스트·DB 이름·SQL, 저장소 메시지에 (현재는 없지만) 경로가 들어갈 수 있다.
- 캐시 히트 때는 남기지 않는다(같은 실패가 주기마다 반복 기록되는 것 방지). 상태 전이(OK→FAIL, FAIL→OK) 때만 남기는 변형도 가능하나 프로세스별 상태라 다중 워커에서 중복된다 — 단순히 "실제 확인해서 실패했을 때마다"가 무난.
- Drive 오류는 어댑터와 O-02가 둘 다 남겨 2줄이 된다. 중복이 싫으면 O-02는 inbox 실패 중 `_fail()`을 거치지 않은 경우(판정 실패)만 남기는 방법이 있으나, 구분 로직이 생긴다 → 중복 허용이 단순.

---

## 8. 보안·노출

| 항목 | 현황 | 권장 |
|---|---|---|
| 인증 | 없음(`architecture.md` §7.1). `RobotAuthMiddleware` 비적용 | 그대로. 접근 통제는 방화벽(O-03) |
| 노출 범위 | 사내망·로봇 PC (8000 포트) | 그대로 |
| 응답의 원인 문자열 | — | 결정 D6. 권장: **응답에는 상태만, 원인은 로그에만**(인증 없는 엔드포인트, 규약 §6 취지). 운영자는 `X-Request-Id`로 해당 요청의 `health_check_failed` 로그를 찾는다 |
| 응답에 넣지 않을 것 | 규약 §6·§3.4-4 | 폴더 ID, 키 경로, 서비스 계정 이메일, DB URL·호스트, 저장소 경로, 예외 원문, 버전·커밋 해시(필요해지면 별도 결정) |
| 부하 | 인증 없이 누구나 반복 호출 가능 | Drive 캐시로 외부 호출 증폭 차단. DB·저장소는 가벼움 |
| `DOCS_ENABLED=false` | `/docs`·`/openapi.json`만 끔 | `/health`는 영향 없음(라우트 자체는 항상 동작) |

---

## 9. Docker·Compose healthcheck

- `python:3.12-slim`에는 `curl`이 없다. 이미지에 `curl`을 설치하거나(이미지 크기·공격 표면 증가), 파이썬 표준 라이브러리로 호출한다:

  ```dockerfile
  HEALTHCHECK --interval=30s --timeout=20s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=15)"]
  ```

  `urlopen`은 503을 `HTTPError`로 던져 종료 코드가 1이 되므로 200/503 판정이 그대로 반영된다(200 `DEGRADED`는 healthy).

- compose에서도 같은 명령을 `healthcheck.test`에 쓸 수 있다(`db`의 `pg_isready`와 같은 위치).
- 앞서 본 대로 비 Swarm Docker는 `unhealthy`여도 재시작하지 않는다. 따라서 healthcheck에 Drive를 포함해도 "Drive 장애로 API가 재시작되는" 연쇄는 생기지 않는다. 다만 D1에서 Drive 실패를 503으로 정하면 Drive 장애 동안 컨테이너가 `unhealthy`로 표시되고, 향후 autoheal·Swarm 등을 붙이면 불필요한 재시작이 생길 수 있다 → D1 권장안(inbox 실패는 200)과 맞물린다.
- 개발용(`Dockerfile.dev`, `--reload`)에는 healthcheck가 꼭 필요하지 않다. 운영 `Dockerfile`·`docker-compose.yml`은 O-01(A) 소관이라 O-02는 **명령 예시를 제공**하고 반영은 O-01/O-03과 조율(§12).

---

## 10. 테스트 전략

### 10.1 단위 (Docker 없음, `tests/unit/`)

`build_app()`으로 앱을 만들고 `app.state.audio_storage`·`app.state.inbox_writer`를 가짜로 바꾸며, DB는 `app.dependency_overrides[get_db]`로 가짜 세션(정상: `execute`가 성공 / 실패: `OperationalError` 발생)을 넣는다. 서비스를 따로 만들면 판정 로직은 서비스 단위 테스트로도 검증한다.

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 세 구성요소 모두 정상(inbox 가짜 OK) | 200, `status=OK`, `checks` 세 키 모두 `OK` |
| 2 | inbox disabled(기본 설정) | 200, `inbox=DISABLED`, 전체 `OK` |
| 3 | DB 실패 | 503, `db=FAIL`, 전체 `FAIL`, 본문이 헬스 형식(에러 형식 아님) |
| 4 | 저장소 실패(`StorageError`) | 503, `audio_storage=FAIL` |
| 5 | inbox 실패(`InboxUnavailableError("http_404")`) | D1에 따라 200 `DEGRADED`(또는 503) |
| 6 | inbox 결과 캐시: TTL 안 두 번 호출 | `check()` 1회 |
| 7 | 캐시 만료(가짜 시계) | `check()` 2회 |
| 8 | 실패도 캐시 | 실패 후 TTL 안 재호출 시 `check()` 1회 |
| 9 | 응답에 원인·비밀 없음 | 본문에 `reason`(D6 권장안)·폴더 ID·예외 메시지(`"secret-key-path"` 류) 없음 |
| 10 | 실패 로그 | `app.health` `health_check_failed`에 `component`·`reason`, `exc_info`·원인 메시지 없음(`_log_lines(capsys)`) |
| 11 | 로봇 인증 비적용 | `X-API-Key` 없이 200(`robot_api_keys` 비어 있어도) |
| 12 | `X-Request-Id`·`Cache-Control: no-store` 헤더 | 존재 |
| 13 | 동시성(선택) | 여러 스레드 동시 호출 시 만료 순간 `check()` 1회 — 잠금 검증. 비결정적이면 생략하고 잠금은 리뷰로 확인 |
| 14 | OpenAPI | D10에 따라 `/health`가 스키마에 있음/없음. 있으면 `openapi.json` 재생성으로 `test_committed_openapi_is_up_to_date` 통과 |

실제 어댑터로도 확인 가능: `LocalStorage(tmp_path)`·`LocalInboxWriter(tmp_path)`를 써서 정상 경로, 읽기 전용 폴더는 Windows·root 환경에서 재현이 불안정하므로 가짜로 대체.

### 10.2 통합 (`tests/integration/`, 실제 PostgreSQL)

- `api` 픽스처(실제 DB 세션 오버라이드)로 `GET /health` → `db=OK`. `get_db` 오버라이드 대신 `session_factory`를 직접 쓰는 설계라면 `Settings(database_url=...)`로 앱을 만들어야 한다 → **`get_db` 의존성을 쓰는 설계가 테스트에 유리**.
- 잘못된 DB URL(닫힌 포트)로 앱을 만들어 503 확인 — 연결 거부라 빠르게 끝남. `connect_timeout`(D4) 적용 여부는 무응답 호스트(예: 라우팅 안 되는 IP)로 확인할 수 있으나 느리고 환경 의존적이라 수동 확인 권장.

### 10.3 수동

- 실제 Drive(`@pytest.mark.drive`, E-01 이후): 정상 폴더 OK, 서비스 계정 권한 제거 시 FAIL(`http_404`/`http_403`), 키 파일 없음 + `NO_GCE_CHECK` 유무에 따른 응답 시간 비교(H5 실측).
- Docker: 운영 compose에서 `docker inspect --format '{{.State.Health.Status}}'`로 healthy/unhealthy 전이 확인(O-01/O-03과 함께).

---

## 11. 결정 필요

| # | 항목 | 선택지 | 권장안 |
|---|---|---|---|
| **D1 [핵심]** | Drive(inbox) 실패 시 전체 판정 | (a) 하나라도 실패면 503 (b) DB·저장소만 필수, inbox 실패는 200 `DEGRADED` (c) inbox는 상태만 표시하고 판정 무관(항상 OK 취급) | **(b)**. 로봇 흐름은 Drive와 무관(D7). Docker healthcheck·향후 재시작 도구가 Drive 장애로 API를 내리지 않음. 본문으로 Drive 장애는 여전히 보임. 단 HTTP 코드만 보는 모니터는 Drive 장애를 놓친다(§12-1과 함께 확인) |
| **D2 [핵심]** | 응답 형식·503 본문 | (a) 안 A 상태 문자열 (b) 안 B 객체(+`reason`) (c) IETF draft. 503 본문은 헬스 형식 / §7.2 에러 형식 | **(a) + 503도 헬스 형식**. `convention.md` §2.2 표에 `/health` 행과 "에러 형식 예외" 한 줄 추가. A→B는 비호환이라 확장 여지가 필요하면 처음부터 B |
| **D3 [핵심]** | inbox `check()` 캐시 | (a) 캐시 없음 (b) 성공·실패 모두 TTL 30초 + 잠금 (c) 성공만 캐시 (d) 백그라운드 주기 확인 | **(b)**. H5 지연(실패 미캐시)과 스레드풀 점유를 막음. TTL은 상수로 시작, 필요 시 설정 변수화 |
| D4 | DB 연결 타임아웃 | (a) 엔진 전체 `connect_args={"connect_timeout": 5}` (b) 헬스 전용 엔진 (c) 그대로 | **(a)**. 한 줄 변경으로 다른 API도 무한 대기 방지. `db.py`는 C-01/C-04(A) 영역이 겹치므로 A 리뷰 |
| D5 | 상태 값 표기 | (a) 규약 §5.3 대문자 `OK/DEGRADED/FAIL/DISABLED` (b) 관례 소문자 `ok/...` (c) `UP/DOWN` | **(a)** 규약 일관성 |
| D6 | 원인(`reason`) 응답 노출 | (a) 응답 미노출, 로그만 (b) 응답에 분류 문자열 노출 (c) 개발 환경에서만 노출 | **(a)**. 인증 없는 엔드포인트, 규약 §6 취지. 운영자는 로그로 확인. 저장소 `StorageError`에 분류 속성이 없는 문제도 (a)면 로그용 문자열만 정하면 됨 |
| D7 | liveness 분리 | (a) `/health` 하나 (b) `/health`(deep) + `/health/live`(프로세스만, 항상 200) (c) 쿼리 파라미터로 구분 | **(a)**. 오케스트레이터가 없어 readiness/liveness 구분의 실익이 작고, D1(b)면 Docker healthcheck가 Drive 장애로 unhealthy가 되지 않음. 향후 Cloud Run(Phase 3) 등에서 필요해지면 (b) 추가 |
| D8 | `/health` 접근 로그 | (a) 그대로 남김 (b) 성공(200)만 제외, 실패는 남김 (c) 모두 제외 | **(a)**로 시작(양이 적고 규칙 추가가 공통 모듈 수정). 모니터 주기가 짧아지면 (b) — `common-module.md` #17 갱신 |
| D9 | 음성 저장소 확인 깊이 | (a) 현재 `check()`(권한 확인) 그대로 (b) 임시 파일 쓰기·삭제로 실제 쓰기 확인 (c) (a) + 여유 공간(`shutil.disk_usage`) 임계치 | **(a)**. `check()`는 R-03(A) 소관이고 문서(§12 "쓰기")와 표현만 맞추면 됨. 디스크 가득 참 감시는 VM 모니터링 몫으로 남기거나 (c)를 A와 협의 |
| D10 | OpenAPI 포함 | (a) 포함(`tags=["health"]`, 규약 §7-4에 태그 추가) (b) `include_in_schema=False` | 소비자에 따라. 운영·Docker만 쓰면 **(b)**, RPA·프론트가 부르면 **(a)**(§12-2 확인 후 확정) |
| D11 | 코드 배치 | (a) `api/health.py` + `services/health_service.py` + `schemas/health.py` (b) 라우터 하나 | **(a)**. 계층 규칙(Router에서 DB 직접 접근 금지) 준수, `architecture.md` §3.2 구조도에 추가 |
| D12 | 예상 밖 예외 처리 | (a) 선언된 예외만 잡고 나머지는 500 (b) 모든 `Exception`을 구성요소 FAIL로 | **(a)**. 버그가 `app.error` 스택 로그로 드러남 |
| D13 | 메서드 | (a) `GET`만 (b) `GET` + `HEAD` | **(a)**. Docker·일반 모니터는 GET 사용 |

---

## 12. 팀 확인 필요 (A·운영·RPA)

| # | 대상 | 확인할 내용 | 영향 |
|---|---|---|---|
| 1 | 운영(O-03)·팀 | `/health`를 실제로 부를 주체: Docker healthcheck만? 외부 업타임 모니터·알림(슬랙 등)? 사람이 수동 확인? HTTP 코드만 보는 도구인지 본문까지 보는지 | D1·D7·D10. HTTP 코드만 보는 외부 모니터가 Drive 장애도 잡아야 하면 D1(a) 또는 별도 경로 필요 |
| 2 | RPA 파트 | Dispatcher가 처리 전에 `/health`를 사전 점검으로 호출할 계획이 있는지. 있다면 로봇 PC에서 접근 가능해야 하고(방화벽은 이미 허용), 어떤 상태를 "진행 불가"로 볼지(Drive는 로봇 흐름과 무관) | D10(계약 포함), D1 |
| 3 | 백엔드 A (O-01) | 운영 `Dockerfile`/`docker-compose.yml`에 `HEALTHCHECK` 추가 여부와 명령(§9 `python -c` 예시), `interval`·`timeout`·`start_period` 값, non-root 실행(저장소 `os.access` 판정 신뢰성) | §9 |
| 4 | 백엔드 A (R-03) | 음성 저장소 확인 깊이(D9): 현재 권한 확인으로 충분한지, 실제 쓰기·여유 공간 확인이 필요한지. `StorageError`에 분류 속성(`reason`) 추가 의향(응답·로그용) | D6·D9 |
| 5 | 백엔드 A (C-01/C-04) | `create_session_factory`에 `connect_timeout` 추가(D4)가 로봇 API·마이그레이션에 영향 없는지 | D4 |
| 6 | 운영(O-03)·E-01 | 운영 `.env`에 `NO_GCE_CHECK=true` 설정(비 GCP VM, H5). 서비스 계정 키 배치 후 `drive.file` 스코프로 `files.get(inbox)`가 되는지(E1) — 안 되면 Drive 헬스가 `http_404`로 계속 FAIL | Drive 헬스 정상 동작 |
| 7 | 운영 | Uvicorn 워커 수(2~4)와 모니터 주기 → Drive 호출량(워커 수 × 60/TTL 회/분)이 문제 없는지(할당량 대비 무시 수준 예상) | D3 TTL |

---

## 13. 문서 반영 후보 (구현 시)

| 문서 | 위치 | 내용 |
|---|---|---|
| `api/convention.md` | §2.2 표, §3 | `GET /health` 행(200/503), 503 본문이 에러 형식이 아니라는 예외, (D10a면) §7-4 태그 `health` |
| `architecture.md` | §3.2 | `api/health.py`, `services/health_service.py`, `schemas/health.py` |
| `architecture.md` | §12 | 판정 규칙(필수/선택), 캐시 TTL, "음성 저장소 쓰기" → 실제 확인 방식에 맞춘 표현 |
| `architecture.md` | §10.3 / `.env.example` | (설정화하는 경우) TTL 변수, `NO_GCE_CHECK` 안내 |
| `plans/common-module.md` | #17 | D8 결과 |
| `docs/api/openapi.json` | — | D10(a)면 재생성 |
