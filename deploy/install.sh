#!/usr/bin/env bash
# Установка бота на Linux-сервере (VPS).
#
#   scp -r bot user@server:/tmp/slovak-bot
#   ssh user@server 'bash /tmp/slovak-bot/deploy/install.sh'
#
# Скрипт: создаёт пользователя, ставит venv, копирует .env, включает systemd.

set -euo pipefail

APP_DIR=/opt/slovak-bot
APP_USER=slovak

echo "==> Проверяем систему"
python3 --version
if ! command -v python3 >/dev/null; then
  echo "Нужен Python 3.9+ (Ubuntu 22.04 / Debian 12 — подходит)" >&2
  exit 1
fi

echo "==> Создаём пользователя $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /bin/bash "$APP_USER"

echo "==> Готовим папку $APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$(dirname "$0")/.."/* "$APP_DIR"/ 2>/dev/null || true
mkdir -p "$APP_DIR/data"

echo "==> Ставим зависимости"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Настраиваем .env"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ""
  echo "!! Впиши BOT_TOKEN и ADMIN_IDS в $APP_DIR/.env, потом запусти:"
  echo "   nano $APP_DIR/.env"
  echo "   bash $APP_DIR/deploy/install.sh   # повторно, чтобы включить сервис"
  exit 0
fi
grep -q "BOT_TOKEN=XXXXTOKENXXXX" "$APP_DIR/.env" && {
  echo "!! BOT_TOKEN всё ещё заглушка — впиши его в $APP_DIR/.env и запусти скрипт снова."
  exit 0
}

echo "==> Собираем контент (если нет content.json)"
if [ ! -f "$APP_DIR/data/content.json" ]; then
  if [ -d /mnt/slovakia ]; then
    .venv/bin/python tools/build_content.py --source /mnt/slovakia --out "$APP_DIR/data"
  else
    echo "   content.json не найден и папки с контентом нет — скопируй data/content.json с ПК"
  fi
fi

echo "==> Включаем systemd"
cp "$APP_DIR/deploy/slovak-bot.service" /etc/systemd/system/slovak-bot.service
sed -i "s#WorkingDirectory=/opt/slovak-bot#WorkingDirectory=$APP_DIR#" /etc/systemd/system/slovak-bot.service
systemctl daemon-reload
systemctl enable slovak-bot
systemctl restart slovak-bot
sleep 3
systemctl --no-pager --lines=20 status slovak-bot

echo ""
echo "Готово. Бот работает 24/7."
echo "Логи:   journalctl -u slovak-bot -f"
echo "Перезапуск: systemctl restart slovak-bot"
