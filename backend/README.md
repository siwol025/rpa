# Callcenter AI RPA — Backend

FastAPI + PostgreSQL 16. 설계 문서는 [`docs/`](docs/) 참조.

| 문서 | 위치 |
|---|---|
| 아키텍처 | `docs/architecture/architecture.md` |
| 기술 스택 | `docs/tech-stack/back_stack.md` |
| 리서치 | `docs/researchs/research.md` |
| 기능 목록·분담 | `docs/features/features.md` |
| API 규약 | `docs/api/convention.md` |
| OpenAPI (팀 간 계약) | `docs/api/openapi.json` |

## 준비물

- [uv](https://docs.astral.sh/uv/) (Python 3.12 은 uv 가 `.python-version` 기준으로 설치)
- Docker Desktop (개발용 DB·compose 실행, testcontainers)

## 로컬 개발

```bash
cd backend
uv sync                      # 가상환경 + 의존성 설치 (uv.lock 기준)
cp .env.example .env
uv run pre-commit install --config ../.pre-commit-config.yaml

uv run uvicorn app.main:app --reload    # http://localhost:8000/docs
```

### Docker Compose (api + db + adminer)

```bash
# 레포 루트에서
docker compose -f deploy/docker-compose.dev.yml up --build
```

| 서비스 | 주소 |
|---|---|
| API (hot reload) | http://localhost:8000/docs |
| PostgreSQL | localhost:5433 (callcenter / callcenter) |
| Adminer | http://localhost:8080 (서버: `db`) |

## 운영 실행 (컨테이너)

```bash
# 레포 루트에서
cp deploy/.env.example deploy/.env      # 비밀번호·로봇 키·허용 IP를 채운다 (Git에 커밋하지 않는다)
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

api는 시작할 때 `alembic upgrade head`를 적용한 뒤 뜬다(실패하면 시작하지 않는다). DB 포트는 호스트에 열지 않고,
DB·음성 사본은 볼륨(`pg-data`, `audio-data`)에 보관되어 컨테이너를 다시 만들어도 남는다.

### 환경 변수

전체 목록과 설명은 `.env.example`(개발)과 `deploy/.env.example`(운영)에 있다.

| 변수 | 설명 | 기본값 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 접속 URL (운영 compose는 `POSTGRES_PASSWORD`로 조립) | 개발 DB |
| `ROBOT_API_KEYS` | 로봇 API 키, 쉼표로 최대 2개(교체 기간용). **비어 있으면 로봇 API는 모두 401** | 없음 |
| `ROBOT_ALLOWED_IPS` | 로봇 PC의 IP·CIDR, 쉼표 구분. 비어 있으면 모두 403 | 없음 |
| `AUDIO_STORAGE_ROOT` | 음성 사본 저장 위치 | `./data/audio` |
| `STALE_THRESHOLD_MIN` | 처리 중 상태로 이 시간(분)을 넘으면 정체 | `30` |
| `MAX_UPLOAD_MB` | 요청 크기 한도(MiB) | `100` |
| `INBOX_BACKEND` | 웹 업로드 대상 `drive`·`local`·`disabled` | `disabled` |
| `DOCS_ENABLED` | `/docs` 노출. 운영 compose 기본은 `false` | `true` |

## 로봇 API (RPA 파트)

`/api/robot/*`는 `X-API-Key` 헤더와 허용 IP가 모두 맞아야 한다. 호출 순서·요청 예시·409 처리 표는
[`docs/api/robot-examples/README.md`](docs/api/robot-examples/README.md)에 있다.

UiPath 없이 서버에 흐름 전체를 점검하려면(실행마다 점검용 건이 등록되므로 운영 DB에는 쓰지 않는다):

```bash
uv run python -m scripts.simulate_robot --base-url http://localhost:8000 --api-key <키>
```

## 검사

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest                     # 전체
uv run pytest -m "not integration"   # Docker 없이 실행 가능한 테스트만
```

통합 테스트(`integration` 마커)의 DB는 다음 순서로 고른다. 스키마는 `alembic upgrade head`로 만든다.

1. `TEST_DATABASE_URL` 환경 변수 (예: `postgresql+psycopg://callcenter:callcenter@localhost:5433/callcenter_test`) — **테스트 전용 DB**여야 한다. 시작 시 `alembic downgrade base`로 모든 테이블을 지운다.
2. 없으면 testcontainers로 `postgres:16` 컨테이너 (Docker 필요)
3. 둘 다 불가하면 skip

수동 Drive 테스트(`drive` 마커)는 `TEST_DRIVE_FOLDER_ID`가 없으면 skip된다. E-01 이후 테스트용 공유 드라이브 폴더로 실행한다(운영 `inbox/` 금지, 올린 파일은 직접 정리).

    GOOGLE_APPLICATION_CREDENTIALS=<키 경로> TEST_DRIVE_FOLDER_ID=<폴더 ID> uv run pytest -m drive

### OpenAPI 갱신

요청·응답 스키마나 라우트를 바꾸면 다시 생성해 같은 커밋에 포함한다(최신이 아니면 `pytest`가 실패한다).

```bash
uv run python -m scripts.export_openapi
```
