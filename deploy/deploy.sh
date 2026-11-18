#!/usr/bin/env bash
# Деплой бота на VPS одной командой (из папки проекта).
#
#   bash deploy/deploy.sh user@server
#
# Что делает: копирует код + свежий content.json на сервер, перезапускает сервис,
# показывает последние строки логов.

set -euo pipefail

TARGET="${1:-}"
APP_DIR="${APP_DIR:-/opt/slovak-bot}"
SERVICE="slovak-bot"

if [ -z "$TARGET" ]; then
  echo "usage: bash deploy/deploy.sh user@server" >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

echo "==> Собираем свежий контент"
if [ -d "${SOURCE_DIR:-/mnt/slovakia}" ]; then
  python3 tools/build_content.py --source "${SOURCE_DIR:-/mnt/slovakia}" --out data
else
  echo "   исходников нет — едет текущий data/content.json"
fi

echo "==> Копируем на $TARGET"
rsync -az --delete \
  --exclude '.git' \
  --exclude '.env' \
  --exclude 'data/*.db*' \
  --exclude 'data/tts' \
  --exclude '__pycache__' \
  "$HERE/" "$TARGET:$APP_DIR/"

echo "==> Перезапускаем сервис"
ssh "$TARGET" "sudo systemctl restart $SERVICE && sleep 3 && sudo journalctl -u $SERVICE --no-pager --lines=15"

echo ""
echo "Готово. Бот работает: systemctl status $SERVICE"
