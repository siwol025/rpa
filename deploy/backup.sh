#!/usr/bin/env bash
# 운영 백업: DB(pg_dump 사용자 지정 형식) + 음성 사본 볼륨(tar.gz). 보관 기간이 지난 파일은 지운다.
# 실행: deploy/backup.sh          (저장소 루트에서, 운영 compose 가 떠 있어야 한다)
# cron: 0 3 * * * cd /opt/rpa && deploy/backup.sh >> /var/log/callcenter-backup.log 2>&1
#
# 환경 변수(선택)
#   BACKUP_DIR        백업 위치 (기본: deploy/backups)
#   BACKUP_KEEP_DAYS  보관 일수 (기본: 14)
#   BACKUP_AUDIO      0 이면 음성 백업을 건너뛴다 (기본: 1)
#   ENV_FILE          compose 환경 파일 (기본: deploy/.env)
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$DEPLOY_DIR/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
ENV_FILE="${ENV_FILE:-$DEPLOY_DIR/.env}"
STAMP="$(date +%Y%m%d_%H%M%S)"

# Windows Git Bash가 /data/... 인자를 Windows 경로로 바꾸지 않게 한다(Linux에서는 영향 없음).
export MSYS_NO_PATHCONV=1
compose() { docker compose -f "$DEPLOY_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }
log() { echo "[$(date '+%F %T')] $*"; }

mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/audio"

# 다 쓴 뒤에만 최종 이름으로 바꾼다. 중간에 실패하면 .partial 이 남고 보관 정리 대상이 아니다.
db_file="$BACKUP_DIR/db/callcenter_$STAMP.dump"
compose exec -T db pg_dump -U callcenter -d callcenter -Fc > "$db_file.partial"
mv "$db_file.partial" "$db_file"
log "DB 백업: $db_file ($(du -h "$db_file" | cut -f1))"

if [ "${BACKUP_AUDIO:-1}" != "0" ]; then
  audio_file="$BACKUP_DIR/audio/audio_$STAMP.tar.gz"
  compose exec -T api tar -czf - -C /data/audio . > "$audio_file.partial"
  mv "$audio_file.partial" "$audio_file"
  log "음성 백업: $audio_file ($(du -h "$audio_file" | cut -f1))"
fi

find "$BACKUP_DIR/db" -name 'callcenter_*.dump' -mtime +"$KEEP_DAYS" -print -delete
find "$BACKUP_DIR/audio" -name 'audio_*.tar.gz' -mtime +"$KEEP_DAYS" -print -delete
log "완료 (보관 ${KEEP_DAYS}일)"
