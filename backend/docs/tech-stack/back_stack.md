# Tech Stack — 백엔드 / DB

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-23 |
| 근거 | `research.md` v0.2 §2, `architecture.md` v0.3, `input_flow.md` v0.2 |
| 범위 | 역할 ① 백엔드 / DB / 서버 인프라 |
| 전제 | 입력 위치는 클라우드 폴더(Google Drive [가정]), 로그인·챗봇 없음 |
| 제외 | RPA 파트(UiPath, STT, GenAI 등) 기술 스택은 이 문서에 포함하지 않음 |

> 버전은 **메이저(또는 마이너) 기준**으로 적었습니다. 프로젝트 시작 시 각 패키지의 최신 안정판을 확인해 `uv.lock`으로 고정하세요.

---

## 1. 한눈에 보기

| 영역 | 선택 | 버전 기준 |
|---|---|---|
| 언어 | Python | 3.12 |
| 웹 프레임워크 | FastAPI | 최신 안정판 |
| ASGI 서버 | Uvicorn | 최신 안정판 |
| 검증·설정 | Pydantic v2, pydantic-settings | 2.x |
| DB | PostgreSQL | 16 |
| ORM | SQLAlchemy | 2.0 |
| DB 드라이버 | psycopg | 3.x |
| 마이그레이션 | Alembic | 최신 안정판 |
| Google Drive 연동 | google-api-python-client, google-auth | 최신 안정판 |
| 엑셀 생성 | openpyxl | 3.x |
| 패키지 관리 | uv (`pyproject.toml` + `uv.lock`) | 최신 안정판 |
| 테스트 | pytest, httpx, testcontainers | — |
| 린트·포맷·타입 | Ruff, mypy | — |
| 컨테이너 | Docker, Docker Compose | — |
| 로그 | structlog (JSON) | — |

---

## 2. 애플리케이션

### 2.1 Python 3.12
- FastAPI·SQLAlchemy·Google 클라이언트가 모두 지원하는 안정 버전
- 팀원 로컬과 컨테이너 버전을 맞추기 위해 `.python-version` 파일로 고정

### 2.2 FastAPI + Uvicorn
| 이유 | 설명 |
|---|---|
| 스키마 검증 | 로봇이 보내는 GenAI 결과 JSON을 Pydantic 모델로 바로 검증 (422 자동 응답) |
| API 문서 | OpenAPI(`/docs`) 자동 생성 → 다른 파트와 API 계약서로 공유 |
| 파일 처리 | multipart 업로드(`UploadFile`), Range 스트리밍(`StreamingResponse`) 기본 지원 |
| 규모 적합성 | 백엔드는 등록·적재·조회·집계 중심의 가벼운 CRUD 서버면 충분 |

- 운영 실행: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2~4` (리버스 프록시 없이 Uvicorn 직접 노출, §6.1)
- 동기/비동기: **동기(def) 엔드포인트 + 동기 SQLAlchemy 세션**을 기본으로 한다. 트래픽이 작고 구현·디버깅이 단순함. Drive 업로드처럼 오래 걸리는 I/O도 FastAPI가 스레드풀에서 처리

### 2.3 Pydantic v2 / pydantic-settings
- 요청·응답 스키마, GenAI 결과 스키마(`category`는 5대 유형 `Enum`)
- 환경 변수는 `Settings` 클래스 하나로 로드 (`.env` 지원)

### 2.4 structlog
- JSON 구조화 로그, 요청마다 `request_id`·`call_id` 바인딩
- 로봇 로그와 `X-Request-Id`로 연결

---

## 3. 데이터베이스

### 3.1 PostgreSQL 16
| 이유 | 설명 |
|---|---|
| JSONB | 화자별 전사(`segments`), 개체명(`entities`), GenAI 원본 응답(`raw_json`)을 구조 그대로 저장·조회 |
| 한글 검색 | `pg_trgm` 확장 + GIN 인덱스로 요약·전사 부분 일치 검색 |
| 집계 | 기간별 추이·유형별 통계를 SQL로 바로 계산 (`date_trunc`, `GROUP BY`, `FILTER`) |
| 동시성 | 로봇·웹 동시 쓰기, 상태 전이 시 `SELECT ... FOR UPDATE` 행 잠금 |
| 비용 | 무료, Docker로 로컬·운영 환경 동일하게 구성. 클라우드 전환 시 Cloud SQL로 이전 쉬움 |

비교 후 제외: MySQL(JSON 인덱싱·검색 불편), SQLite(동시 쓰기 약함, 운영 부적합)

### 3.2 사용 확장
| 확장 | 용도 |
|---|---|
| `pg_trgm` | 한글 키워드 부분 일치 검색 |

### 3.3 DB 규칙
| 항목 | 규칙 |
|---|---|
| 테이블·컬럼명 | `snake_case`, 테이블은 단수형 (`call_record`, `analysis`) |
| PK | `BIGSERIAL` (`id`) |
| 시간 | 모두 `TIMESTAMPTZ`, 서버 저장은 UTC, API 응답은 `+09:00` |
| 상태·유형 값 | `VARCHAR` + `CHECK` 제약 (PostgreSQL `ENUM` 타입은 값 추가 시 마이그레이션이 번거로워 사용하지 않음) |
| 삭제 | 소프트 삭제 (`deleted_at`), 조회 기본 필터 적용 |
| 공통 컬럼 | `created_at`, `updated_at` (ORM에서 자동 갱신) |
| 스키마 변경 | **Alembic 마이그레이션으로만** 수행, 수동 DDL 금지 |
| 계정 | 앱 계정(DML만) / 마이그레이션 계정(DDL) 분리 |

테이블 정의는 `research.md` §4.1, ERD는 `architecture.md` §6 참조.

### 3.4 SQLAlchemy 2.0 + psycopg 3 + Alembic
- SQLAlchemy 2.0 스타일(`Mapped[]`, `select()`)로 ORM 모델 작성
- 드라이버는 psycopg 3 (`postgresql+psycopg://`)
- Alembic `--autogenerate`로 초안 생성 후 **사람이 검토**하고 커밋
- 집계 쿼리처럼 복잡한 SQL은 SQLAlchemy Core 또는 `text()` 사용 허용

---

## 4. 외부 연동 / 파일

| 대상 | 라이브러리 | 용도 |
|---|---|---|
| Google Drive | `google-api-python-client`, `google-auth` | 웹 업로드 파일을 클라우드 `inbox/`에 업로드 (서비스 계정, 공유 드라이브) |
| 음성 사본 저장 | 표준 라이브러리 (로컬 디스크) | `AudioStorage` 인터페이스의 `LocalStorage` 구현. 클라우드 전환 시 `google-cloud-storage`로 `GCSStorage` 추가 |
| 파일 형식 검증 | `python-magic` 또는 `filetype` | 확장자 외에 파일 시그니처(매직 바이트)로 wav/mp3 확인 |
| 해시 | 표준 라이브러리 `hashlib` | SHA-256 중복 검사 (로봇이 보낸 값 재검증) |
| 엑셀 | `openpyxl` | 역할 ④ 템플릿에 데이터 시트 채워 다운로드 제공 |

**사용하지 않는 것**
| 항목 | 이유 |
|---|---|
| Celery / Redis / 메시지 큐 | 백그라운드 작업이 거의 없어 FastAPI 기본 기능으로 충분 |
| 인증 라이브러리(JWT 등) | 로그인 없음. 로봇용 API는 단순 API Key 헤더 검증 |

---

## 5. 개발 도구

| 영역 | 도구 | 비고 |
|---|---|---|
| 패키지·가상환경 | uv | `uv sync`로 동일 환경 재현, `uv.lock` 커밋 |
| 린트·포맷 | Ruff | 린트 + 포맷을 하나로 처리, `pyproject.toml`에 설정 |
| 타입 체크 | mypy | `app/` 대상, SQLAlchemy 2.0 타입 힌트 활용 |
| 커밋 전 검사 | pre-commit | Ruff, mypy, 비밀 파일 커밋 차단 |
| 테스트 | pytest, httpx(TestClient) | 단위·API 테스트 |
| DB 통합 테스트 | testcontainers (PostgreSQL) | 실제 PostgreSQL 컨테이너로 테스트 |
| DB 관리 GUI | Adminer 또는 pgAdmin | 개발용 docker-compose에만 포함 |
| API 수동 테스트 | `/docs` (Swagger UI), Bruno 또는 Postman | API 요청 예시 컬렉션을 다른 파트와 공유 |

### 의존성 예시 (`pyproject.toml`)
```toml
[project]
name = "callcenter-backend"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi",
  "uvicorn[standard]",
  "pydantic>=2",
  "pydantic-settings",
  "sqlalchemy>=2.0,<2.1",
  "psycopg[binary]>=3",
  "alembic",
  "python-multipart",          # multipart 업로드
  "google-api-python-client",
  "google-auth",
  "openpyxl",
  "structlog",
]

[dependency-groups]
dev = [
  "pytest",
  "httpx",
  "testcontainers[postgres]",
  "ruff",
  "mypy",
  "pre-commit",
]
```

---

## 6. 인프라

| 영역 | 선택 | 비고 |
|---|---|---|
| 컨테이너 | Docker + Docker Compose | `api`, `db` 2개 서비스. 개발용 compose에 `adminer` 추가 |
| 베이스 이미지 | `python:3.12-slim` | 멀티 스테이지 빌드, non-root 사용자 실행 |
| DB 이미지 | `postgres:16` | 데이터는 named volume, 포트 외부 미노출 |
| 리버스 프록시 | 사용하지 않음 | 역할 대체는 §6.1 |
| 비밀 관리 | `.env` + Docker secret | 서비스 계정 키(JSON)·로봇 API Key·DB 비밀번호. Git 커밋 금지 |
| 백업 | `pg_dump` cron (일 1회) | 음성 사본 볼륨도 함께 백업 |
| 배포 대상 | 사내 VM 1대 | 클라우드 전환(선택) 시 Cloud Run + Cloud SQL + GCS |

### 6.1 Nginx 없이 처리하는 방법

| Nginx가 하던 역할 | 대체 방법 |
|---|---|
| IP 허용 목록 | VM 방화벽(ufw / Windows 방화벽)에서 8000 포트를 사내망 대역·로봇 PC IP에만 개방. `/api/robot/*`는 앱 미들웨어에서 로봇 PC IP를 한 번 더 확인 |
| 업로드 용량 제한 | 앱에서 `Content-Length` 확인 + 수신 중 누적 크기 검사로 `MAX_UPLOAD_MB`(기본 100) 초과 시 413 반환 |
| HTTPS | 사내망 HTTP 사용을 기본으로 하고, 필요 시 Uvicorn `--ssl-certfile`/`--ssl-keyfile`로 직접 적용 **[결정 필요]** |
| 다중 워커·안정성 | Uvicorn `--workers`, Docker `restart: unless-stopped` |
| 프론트 정적 파일 | 프론트 파트 배포 방식에 따름. 별도 서버면 백엔드는 `CORS_ORIGINS`만 설정 |

나중에 외부 공개·도메인 여러 개·인증서 자동 갱신이 필요해지면 그때 리버스 프록시를 앞단에 추가한다 (앱 코드 변경 없음).

---

## 7. 환경별 구성

| 항목 | 로컬 개발 | 시연·운영 (사내 VM) |
|---|---|---|
| 실행 | `docker compose -f docker-compose.dev.yml up` (hot reload) | `docker compose up -d` |
| DB | 컨테이너 PostgreSQL | 컨테이너 PostgreSQL (볼륨 백업) |
| 웹 업로드 대상 | 로컬 폴더 (`INBOX_BACKEND=local`) 또는 테스트용 Drive 폴더 | Google Drive 공유 드라이브 (`INBOX_BACKEND=drive`) |
| 음성 사본 | 로컬 디렉터리 | Docker 볼륨 `/data/audio` |
| HTTPS | 없음 | 사내망 HTTP 기본, 필요 시 Uvicorn SSL 옵션 |
| 접근 통제 | 없음 | VM 방화벽 IP 제한 + 로봇 API IP 확인 미들웨어 |
| `/docs` | 활성 | 비활성 또는 IP 제한 |

환경 변수 목록은 `architecture.md` §10.3 참조.

---

## 8. 확정 필요 사항

1. 클라우드 서비스 확정 (Google Drive 가정) → 확정되면 §4 Drive 라이브러리 유지/교체
2. 사내 VM 사양·OS, Docker 사용 가능 여부
3. HTTPS 적용 여부 (사내망 HTTP로 충분한지), 적용 시 사내 인증서 발급 방법
4. 팀 내 Python 3.12 / uv 사용 합의 (pip + venv로 대체 가능)
