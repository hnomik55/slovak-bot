"""Переключение на PythonAnywhere: бот, API и приложение — на одном хостинге.

    python tools\switch_to_pythonanywhere.py <домен>

Что делает:
  1) прописывает в .env: MODE=webhook, WEBAPP_BASE_URL=https://<домен>;
  2) ставит BOT_MODE=cloud — локальный бот в чате не запускается
     (иначе он и облачный будут драться за один токен);
  3) обновляет docs/config.json — адрес API для копии приложения на GitHub Pages;
  4) переписывает автозапуск ПК: поднимается только туннель (или ничего);
  5) останавливает локальный бот и мини-приложение;
  6) отправляет всем пользователям новую кнопку.

Запуск: python tools/switch_to_pythonanywhere.py hnomik55.pythonanywhere.com
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "docs" / "config.json"


def set_env(text: str, key: str, value: str) -> str:
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.strip().startswith(key + "="):
            lines.append("%s=%s" % (key, value))
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append("%s=%s" % (key, value))
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/switch_to_pythonanywhere.py <домен>")
        return 1
    domain = sys.argv[1].strip().replace("https://", "").replace("/", "")
    base = "https://%s" % domain

    text = ENV_PATH.read_text(encoding="utf-8")
    text = set_env(text, "MODE", "webhook")
    text = set_env(text, "WEBAPP_BASE_URL", base)
    text = set_env(text, "BOT_MODE", "cloud")
    with io.open(ENV_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("1) .env: MODE=webhook, WEBAPP_BASE_URL=%s, BOT_MODE=cloud" % base)

    # config.json для копии приложения на GitHub Pages
    payload = {"api_base": base, "updated_at": ""}
    from datetime import datetime

    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with io.open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print("2) docs/config.json: api_base=%s" % base)

    # останавливаем локальный бот и локальный сервер приложения
    for tool in ("botctl.py",):
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / tool), "stop"], cwd=str(ROOT), capture_output=True
        )
    print("3) локальный бот и сервер приложения остановлены")

    # автозапуск: в облачном режиме ПК ничего поднимать не нужно
    startup = (
        Path.home()
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "SlovakBot.cmd"
    )
    if startup.exists():
        with io.open(startup, "w", encoding="ascii", newline="") as fh:
            fh.write("@echo off\r\nrem Bot and app run on PythonAnywhere - nothing to start here.\r\n")
        print("4) автозапуск ПК отключён (бот и приложение — в облаке)")

    # коммит и пуш (config.json нужен для копии на Pages)
    git = r"C:\Program Files\Git\cmd\git.exe"
    if Path(git).exists():
        subprocess.run([git, "add", "docs/config.json"], cwd=str(ROOT), capture_output=True)
        subprocess.run(
            [git, "commit", "-m", "chore: API переехал на PythonAnywhere"],
            cwd=str(ROOT),
            capture_output=True,
        )
        push = subprocess.run(
            [git, "push", "origin", "main"], cwd=str(ROOT), capture_output=True, text=True
        )
        print("5) config.json отправлен в GitHub" if push.returncode == 0 else "5) пуш не прошёл — проверь вручную")

    # уведомляем пользователей новой кнопкой
    try:
        from app.services.notify import send_new_button

        sent = send_new_button(base)
        print("6) пользователям отправлена новая кнопка (%d шт.)" % sent)
    except Exception as exc:
        print("6) уведомить пользователей не вышло: %s" % exc)

    print()
    print("Готово. Бот и приложение теперь на %s" % base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
