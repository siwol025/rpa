#!/usr/bin/env bash
# 백업에서 복구한다. 현재 데이터를 백업 내용으로 덮어쓰므로 실행 전에 확인을 받는다.
# 실행: deploy/restore.sh db    deploy/backups/db/callcenter_YYYYMMDD_HHMMSS.dump
#       deploy/restore.sh audio deploy/backups/audio/audio_YYYYMMDD_HHMMSS.tar.gz
# 확인 없이 실행(자동화·연습용): RESTORE_YES=1 deploy/restore.sh ...
set -euo pipefail

# Git Bash에서는 C:/... 형식으로 구한다. 아래 MSYS_NO_PATHCONV 때문에 /c/... 를 넘기면
# docker가 C:\c\... 로 읽어 파일을 못 찾는다. Linux bash에는 pwd -W가 없어 pwd를 쓴다.
DEPLOY_DIR="$(cd "$(dirname "$0")" && { pwd -W 2>/dev/null || pwd; })"
ENV_FILE="${ENV_FILE:-$DEPLOY_DIR/.env}"
# Windows Git Bash가 /data/... 인자를 Windows 경로로 바꾸지 않게 한다(Linux에서는 영향 없음).
export MSYS_NO_PATHCONV=1
compose() { docker compose -f "$DEPLOY_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }

kind="${1:-}"
file="${2:-}"
if [ -z "$kind" ] || [ ! -f "$file" ]; then
  echo "사용법: $0 db|audio <백업 파일>" >&2
  exit 2
fi

if [ "${RESTORE_YES:-0}" != "1" ]; then
  read -r -p "$kind 데이터를 $file 내용으로 덮어씁니다. 계속할까요? (yes 입력) " answer
  [ "$answer" = "yes" ] || { echo "취소했습니다."; exit 1; }
fi

case "$kind" in
  db)
    # 복구 중 API가 쓰지 않도록 멈춘다. 끝나면(실패해도) 다시 띄운다.
    compose stop api
    trap 'compose start api' EXIT
    compose exec -T db pg_restore -U callcenter -d callcenter --clean --if-exists --no-owner < "$file"
    ;;
  audio)
    compose exec -T api sh -c 'find /data/audio -mindepth 1 -delete && tar -xzf - -C /data/audio' < "$file"
    ;;
  *)
    echo "알 수 없는 종류: $kind (db|audio)" >&2
    exit 2
    ;;
esac
echo "복구 완료: $kind ← $file"
