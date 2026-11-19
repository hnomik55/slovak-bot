#!/usr/bin/env bash
# Настройка бота + API + приложения на PythonAnywhere.
#
# Запуск в консоли Bash на pythonanywhere:
#   bash ~/slovak-bot-setup.sh
#
# Скрипт сам:
#   1) скачивает код из GitHub;
#   2) ставит зависимости (в venv, если он создан, иначе --user);
#   3) пишет .env с токеном и webhook-режимом;
#   4) правит WSGI-файл веб-приложения;
#   5) регистрирует вебхук в Telegram.

set -uo pipefail

REPO_URL="https://github.com/hnomik55/slovak-bot.git"
APP_DIR="$HOME/slovak-bot"
# Домен берём из имени пользователя (в контейнере hostname не совпадает с доменом)
DOMAIN="$(id -un).pythonanywhere.com"
BASE="https://${DOMAIN}"

echo "==========================================="
echo "  Установка Словчины на PythonAnywhere"
echo "  домен: $BASE"
echo "==========================================="
echo

read -r -p "BOT_TOKEN от @BotFather: " BOT_TOKEN
read -r -p "ADMIN_IDS (твой telegram id, можно пусто): " ADMIN_IDS
read -r -p "WEBHOOK_SECRET (любая длинная строка, Enter = сгенерирую): " SECRET
if [ -z "$SECRET" ]; then
  SECRET="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
fi

echo
echo "--- 1. Код ---"
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR" && git pull -q
  echo "    обновлён"
else
  git clone -q "$REPO_URL" "$APP_DIR"
  echo "    скачан в $APP_DIR"
fi
cd "$APP_DIR"

echo "--- 2. Зависимости ---"
VENV_PY=""
if [ -x "$HOME/.virtualenvs/slovak-bot/bin/python" ]; then
  VENV_PY="$HOME/.virtualenvs/slovak-bot/bin/python"
elif [ -x "$HOME/.virtualenvs/venv/bin/python" ]; then
  VENV_PY="$HOME/.virtualenvs/venv/bin/python"
fi

USER_SITE=""
if [ -n "$VENV_PY" ]; then
  echo "    использую venv: $VENV_PY"
  "$VENV_PY" -m pip install -q --upgrade pip
  "$VENV_PY" -m pip install -q -r requirements-lite.txt
else
  echo "    venv не найден — ставлю облегчённый набор в --user"
  python3 -m pip install -q --user -r requirements-lite.txt || python3 -m pip install -q -r requirements-lite.txt
  USER_SITE="$(python3 -c 'import site; print(site.getusersitepackages())')"
  echo "    пакеты в: $USER_SITE"
fi

echo "--- 3. Настройки (.env) ---"
cat > .env <<EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS
MODE=webhook
WEBHOOK_BASE_URL=$BASE
WEBAPP_BASE_URL=$BASE
PAGES_URL=https://hnomik55.github.io/slovak-bot
WEBHOOK_SECRET=$SECRET
APP_DEV=0
AI_PROVIDER=off
TTS_ENABLED=1
STT_ENABLED=1
EOF
echo "    записано"

echo "--- 4. WSGI-файл ---"
WSGI="/var/www/$(echo "$DOMAIN" | tr '.' '_')_wsgi.py"
if [ -f "$WSGI" ]; then
  cat > "$WSGI" <<EOF
import os
import sys

PROJECT = "$APP_DIR"
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
os.environ.setdefault("MODE", "webhook")
EOF
  if [ -n "$USER_SITE" ]; then
    echo "sys.path.insert(0, \"$USER_SITE\")" >> "$WSGI"
  fi
  echo "from wsgi import app  # noqa: E402" >> "$WSGI"
  echo "application = app  # PythonAnywhere ищет именно application" >> "$WSGI"
  echo "    записан: $WSGI"
else
  echo "    ВНИМАНИЕ: не нашёл WSGI-файл ($WSGI)"
  echo "    создай Web app в панели и впиши туда:"
  cat <<EOF
import os, sys
PROJECT = "$APP_DIR"
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
os.environ.setdefault("MODE", "webhook")
EOF
  if [ -n "$USER_SITE" ]; then
    echo "sys.path.insert(0, \"$USER_SITE\")"
  fi
  echo "from wsgi import app"
  echo "application = app"
fi

echo "--- 5. Регистрируем вебхук ---"
PY="python3"
[ -n "$VENV_PY" ] && PY="$VENV_PY"
"$PY" tools/set_webhook.py set "$BASE" || echo "    (пока не получилось — повтори после reload)"

echo
echo "==========================================="
echo "  Готово. Осталось:"
echo "  1) В панели PythonAnywhere нажми Reload на Web app"
echo "  2) Проверь:  $BASE/health"
echo "  3) Напиши боту в Telegram — он должен ответить сразу"
echo "==========================================="
