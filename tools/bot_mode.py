"""Переключатель: где живёт бот в чате.

    python tools\bot_mode.py local    # чат-бот на этом ПК (как сейчас)
    python tools\bot_mode.py cloud    # чат-бот в GitHub Actions, ПК только для Mini App
    python tools\bot_mode.py status

Почему важно: Telegram разрешает только один поток getUpdates на токен.
Если бот на ПК и бот в облаке работают одновременно — они будут драться
(в логах это «terminated by other getUpdates request»). Поэтому режим
переключается явно, и в облачном режиме автозапуск на ПК поднимает
только приложение.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENV_PATH = ROOT / ".env"
PYTHON = sys.executable


def set_mode(mode: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.strip().startswith("BOT_MODE="):
            lines.append("BOT_MODE=%s" % mode)
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append("BOT_MODE=%s" % mode)
    with io.open(ENV_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def install_autostart(cloud_mode: bool) -> None:
    """Переписывает ярлык автозагрузки под выбранный режим."""
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
    if not startup.exists():
        return
    if cloud_mode:
        content = (
            "@echo off\r\n"
            "cd /d \"%s\"\r\n"
            "\"%s\" \"%s\\tools\\miniapp_tunnel.py\" start\r\n"
            % (ROOT, PYTHON, ROOT)
        )
    else:
        content = (
            "@echo off\r\n"
            "cd /d \"%s\"\r\n"
            "\"%s\" \"%s\\tools\\botctl.py\" start\r\n"
            "\"%s\" \"%s\\tools\\miniapp_tunnel.py\" start\r\n"
            % (ROOT, PYTHON, ROOT, PYTHON, ROOT)
        )
    with io.open(startup, "w", encoding="ascii", newline="") as fh:
        fh.write(content)


def main() -> int:
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "status"

    if action == "local":
        set_mode("local")
        install_autostart(cloud_mode=False)
        subprocess.run([PYTHON, str(ROOT / "tools" / "botctl.py"), "start"], cwd=str(ROOT))
        print("Режим: бот в чате — на этом ПК.")
        return 0

    if action == "cloud":
        set_mode("cloud")
        install_autostart(cloud_mode=True)
        subprocess.run([PYTHON, str(ROOT / "tools" / "botctl.py"), "stop"], cwd=str(ROOT))
        print("Режим: бот в чате — в GitHub Actions.")
        print("Локальный бот остановлен, чтобы не драться за токен.")
        print("Не забудь добавить секрет BOT_TOKEN: Settings -> Secrets and variables -> Actions.")
        return 0

    from app.config import CONFIG

    print("Текущий режим:", CONFIG.bot_mode)
    print("Mini App:", CONFIG.webapp_base_url or "не настроен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
