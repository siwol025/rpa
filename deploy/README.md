# 운영 배포

운영 서버 한 대에 Docker Compose로 `api`(FastAPI, 8000)와 `db`(PostgreSQL 16)를 띄운다. 구조는 `backend/docs/architecture/architecture.md` §10.1.

## 1. 서버 준비

- Docker Engine과 Docker Compose v2
- 디스크: 음성 사본(`audio-data` 볼륨)과 DB(`pg-data` 볼륨), 백업 파일이 계속 쌓인다
- 이 저장소 클론(또는 `backend/`·`deploy/` 복사)

**접속 IP 주의:** 로봇 API의 IP 확인(`ROBOT_ALLOWED_IPS`)은 컨테이너가 보는 접속 IP로 판단한다. 서버 자신에서 호출하면 Docker 게이트웨이 주소(예: `172.18.0.1`)로 보이고, Windows + Docker Desktop에서는 다른 PC에서 온 요청도 게이트웨이 주소로 보일 수 있다. Linux(Docker Engine)는 보통 실제 IP가 보인다. 배포 후 로봇 PC에서 요청을 보내 `logs api`의 `client_ip`를 확인하고 값을 정한다(§5).

## 2. 설정

```sh
cp deploy/.env.example deploy/.env      # 값 채우기. .env 는 Git 에 올리지 않는다
mkdir -p deploy/secrets                  # Git 제외 폴더
```

- `POSTGRES_PASSWORD`, `ROBOT_API_KEYS`(쉼표로 최대 2개), `ROBOT_ALLOWED_IPS`(로봇 PC IP/CIDR)는 필수다. 비어 있으면 compose가 시작하지 않는다.
- `CORS_ORIGINS`: 웹 화면 주소(쉼표 구분).
- 웹 업로드를 쓰려면 `INBOX_BACKEND=drive`, `DRIVE_INBOX_FOLDER_ID`, 서비스 계정 키를 `deploy/secrets/drive-sa.json`에 둔다. 컨테이너에는 `/run/secrets`로 읽기 전용 마운트된다.
  - 컨테이너는 non-root(uid 10001)로 돈다. 키 파일을 읽을 수 있게 권한을 준다: `chmod 644 deploy/secrets/drive-sa.json`(서버 접근자가 제한된 경우) 또는 `chown 10001 deploy/secrets/drive-sa.json && chmod 400 ...`.
- `DOCS_ENABLED`는 기본 `false`(`/docs` 숨김).

## 3. 실행·갱신

```sh
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps      # api 가 healthy 인지
docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs -f api
```

- api 컨테이너는 시작할 때 `alembic upgrade head`를 적용한다. 실패하면 컨테이너가 뜨지 않으므로 로그를 본다.
- 갱신은 `git pull` 후 같은 `up -d --build`.
- `down -v`는 DB·음성 볼륨을 지운다. 운영에서는 쓰지 않는다.

## 4. 방화벽

인바운드는 8000 포트만 사내망(웹 사용 PC)과 로봇 PC에 연다. PostgreSQL 포트는 compose가 호스트에 열지 않는다. 아웃바운드는 웹 업로드를 쓰면 Google Drive API(HTTPS 443)가 필요하다.

Linux(ufw) 예시 — 대역은 실제 값으로 바꾼다:

```sh
sudo ufw default deny incoming
sudo ufw allow OpenSSH
sudo ufw allow from <사내망 CIDR> to any port 8000 proto tcp
sudo ufw allow from <로봇 PC IP> to any port 8000 proto tcp
sudo ufw enable
```

Docker가 공개한 포트는 ufw 규칙을 거치지 않을 수 있다(Docker가 iptables를 직접 씀). 이 경우 `DOCKER-USER` 체인에 같은 허용 규칙을 넣거나, `.env`의 `API_PORT`를 `<서버 사내망 IP>:8000`처럼 특정 주소에만 묶는다. 적용 후 §5의 외부 접속 확인으로 실제로 막히는지 본다.

Windows(관리자 PowerShell) 예시:

```powershell
New-NetFirewallRule -DisplayName "callcenter-api" -Direction Inbound -Protocol TCP -LocalPort 8000 -RemoteAddress <사내망 CIDR>,<로봇 PC IP> -Action Allow
```

## 5. 배포 후 확인

서버 주소를 `$API`(예: `http://10.0.0.5:8000`)라 할 때:

| 확인 | 명령 | 기대 |
|---|---|---|
| 헬스 | `curl -s $API/health` | 200, `"status":"OK"`(웹 업로드 끈 경우 `inbox` `DISABLED`) |
| 요청 크기 제한 | `MAX_UPLOAD_MB`보다 큰 본문으로 `POST $API/api/uploads` | 413 `PAYLOAD_TOO_LARGE` |
| 로봇 키 | 로봇 PC에서 키 없이 `GET $API/api/robot/calls/1/audio` | 401 `UNAUTHORIZED` |
| 로봇 IP | 로봇 PC가 아닌 PC에서 키를 넣고 같은 요청 | 403 `FORBIDDEN_IP` |
| 방화벽 | 허용 대역 밖 PC에서 `curl $API/health` | 연결 실패(타임아웃) |
| DB 비공개 | 다른 PC에서 서버의 5432 접속 | 연결 실패 |

## 6. 백업·복구

`deploy/backup.sh`가 DB(`pg_dump -Fc`)와 음성 사본 볼륨(tar.gz)을 `deploy/backups/`(Git 제외)에 남기고, 14일이 지난 파일을 지운다. 저장소 루트에서 실행하며 운영 compose가 떠 있어야 한다.

```sh
deploy/backup.sh                                   # 수동 실행
crontab -e                                         # 매일 03:00 (경로는 실제 클론 위치)
0 3 * * * cd /opt/rpa && deploy/backup.sh >> /var/log/callcenter-backup.log 2>&1
```

- 환경 변수: `BACKUP_DIR`(위치), `BACKUP_KEEP_DAYS`(보관 일수, 기본 14), `BACKUP_AUDIO=0`(음성 제외)
- 음성은 매번 전체를 묶으므로 사본이 쌓일수록 커진다. 디스크가 빠듯하면 음성은 주 1회 별도 cron(`BACKUP_AUDIO=0`인 일일 DB 백업 + 주간 전체)으로 나눈다.
- 같은 디스크에만 두면 디스크 장애 때 함께 잃는다. 가능하면 `BACKUP_DIR`을 다른 디스크·NAS로 두거나 주기적으로 다른 곳에 복사한다.
- 실패하면 `.partial` 파일이 남고 cron 로그에 오류가 찍힌다. 로그를 주기적으로 확인한다.

복구(현재 데이터를 덮어쓴다. 실행 전에 확인을 묻는다):

```sh
deploy/restore.sh db    deploy/backups/db/callcenter_20261125_030000.dump     # api 를 멈췄다가 다시 띄운다
deploy/restore.sh audio deploy/backups/audio/audio_20261125_030000.tar.gz
curl -s $API/health                                                           # 복구 후 확인
```

- DB와 음성은 같은 시각의 백업 쌍으로 복구한다(DB에 있는 건의 음성이 없으면 재생·재처리가 404).
- 새 서버로 옮길 때: §2·§3으로 빈 상태를 띄운 뒤(마이그레이션 적용됨) 같은 순서로 복구한다.

## 7. 문제 해결

로봇 IP가 403으로 잘못 막히면 `logs api`의 접근 로그에서 `client_ip`를 보고 `ROBOT_ALLOWED_IPS`를 맞춘다(§1 주의). 게이트웨이 주소로만 보인다면 그 주소를 허용하는 것은 모든 PC를 허용하는 것과 같으므로, 이때는 방화벽(§4)에서 로봇 PC만 열거나 Linux 서버를 쓴다.

웹 업로드를 켠 경우(`INBOX_BACKEND=drive`) Drive 접근이 실패하면 `/health`는 200 `DEGRADED`(`inbox` `FAIL`)로 응답하고 서버는 계속 동작한다. 업로드만 503이 된다.
