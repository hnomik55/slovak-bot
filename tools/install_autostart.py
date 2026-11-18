"""Ставит/снимает автозапуск бота при входе в Windows (Планировщик задач).

    python tools/install_autostart.py install
    python tools/install_autostart.py uninstall
    python tools/install_autostart.py status
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "SlovakBot"
RUNNER = ROOT / "run-bot.cmd"
STARTUP_DIR = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)
STARTUP_ITEM = STARTUP_DIR / "SlovakBot.cmd"


def _python() -> str:
    return sys.executable


def _cmd(action: str) -> str:
    return "%s \"%s\\tools\\botctl.py\" %s" % (_python(), ROOT, action)


def _write_runner() -> None:
    """Готовим .cmd без кавычек-ловушек — его и кладём в автозагрузку."""
    content = (
        "@echo off\r\n"
        "cd /d \"%s\"\r\n"
        "\"%s\" \"%s\\tools\\botctl.py\" start\r\n"
        % (ROOT, _python(), ROOT)
    )
    with open(RUNNER, "w", encoding="ascii", newline="") as fh:
        fh.write(content)
    return content


def run(args: list) -> str:
    proc = subprocess.run(args, capture_output=True)
    out = (proc.stdout or b"") + (proc.stderr or b"")
    for enc in ("utf-16-le", "cp1251", "utf-8"):
        try:
            return out.decode(enc)
        except UnicodeDecodeError:
            continue
    return out.decode("utf-8", errors="replace")


def install() -> int:
    content = _write_runner()
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    with open(STARTUP_ITEM, "w", encoding="ascii", newline="") as fh:
        fh.write(content)
    print("Автозапуск установлен: %s" % STARTUP_ITEM)
    print("Бот будет подниматься сам при входе в Windows.")
    return 0


def uninstall() -> int:
    if STARTUP_ITEM.exists():
        STARTUP_ITEM.unlink()
        print("Ярлык автозапуска удалён: %s" % STARTUP_ITEM)
    else:
        print("Ярлыка автозапуска не было")
    return 0


def status() -> int:
    if STARTUP_ITEM.exists():
        print("Автозапуск: включён (%s)" % STARTUP_ITEM)
    else:
        print("Автозапуск: выключен")
    return 0


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "install":
        return install()
    if action == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    sys.exit(main())
