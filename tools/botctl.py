"""Управление ботом без окна терминала.

    python tools/botctl.py start    # запустить в фоне
    python tools/botctl.py stop     # остановить
    python tools/botctl.py status   # что сейчас
    python tools/botctl.py log      # последние строки журнала
    python tools/botctl.py restart
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / "data" / "bot.pid"
LOG_FILE = ROOT / "data" / "bot.log"
sys.path.insert(0, str(ROOT))

from app.config import CONFIG  # noqa: E402

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def _python() -> str:
    return sys.executable


def _alive(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
            capture_output=True,
            text=True,
        ).stdout
        return str(pid) in out
    except Exception:
        return False


def read_pid() -> int:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except ValueError:
            return 0
    return 0


def do_start() -> int:
    pid = read_pid()
    if pid and _alive(pid):
        print("Бот уже запущен (PID %d)" % pid)
        return 0
    if not CONFIG.bot_token or "XXXXTOKENXXXX" in CONFIG.bot_token:
        print("BOT_TOKEN не задан — впиши его в .env")
        return 1

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
    flags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "bot.py")],
        cwd=str(ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )
    PID_FILE.write_text(str(proc.pid))
    time.sleep(2.5)
    if _alive(proc.pid):
        print("Бот запущен (PID %d). Лог: %s" % (proc.pid, LOG_FILE))
        return 0
    print("Бот не поднялся. Последние строки лога:")
    print(tail(25))
    return 1


def _bot_processes() -> List[int]:
    """Все процессы, запущенные с bot.py (нужно, чтобы не оставались двойники)."""
    pids: List[int] = []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='python3.9.exe'", "get", "processid,commandline"],
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        out = ""
    for line in out.splitlines():
        if "bot.py" in line and "botctl.py" not in line:
            for token in line.split():
                if token.strip().isdigit():
                    pids.append(int(token.strip()))
                    break
    return pids


def do_stop() -> int:
    pid = read_pid()
    if pid and _alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
    PID_FILE.unlink(missing_ok=True)

    # добиваем всё, что осталось (вторые экземпляры дают конфликт в Telegram)
    time.sleep(1)
    for other in _bot_processes():
        if other != pid:
            subprocess.run(["taskkill", "/PID", str(other), "/T", "/F"], capture_output=True, text=True)
            print("Убит лишний экземпляр бота (PID %d)" % other)
    print("Бот остановлен")
    return 0


def do_status() -> int:
    pid = read_pid()
    if pid and _alive(pid):
        print("Бот работает (PID %d)" % pid)
    else:
        print("Бот не запущен")
    print("Журнал: %s" % LOG_FILE)
    print(tail(12))
    return 0


def tail(lines: int = 20) -> str:
    if not LOG_FILE.exists():
        return "(журнала нет)"
    content = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "start":
        return do_start()
    if command == "stop":
        return do_stop()
    if command == "restart":
        do_stop()
        time.sleep(1)
        return do_start()
    if command == "log":
        print(tail(int(sys.argv[2]) if len(sys.argv) > 2 else 40))
        return 0
    print(__doc__)
    return do_status()


if __name__ == "__main__":
    sys.exit(main())
