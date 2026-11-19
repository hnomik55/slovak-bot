"""Сторож: поднимает бота, если тот упал.

Сеть (особенно VPN) периодически рвётся, и бот падает с Bad Gateway.
Сторож просто перезапускает процесс — ученик этого не замечает.

    python tools/bot_supervisor.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT / "bot.py"
DELAY = 8


def _kill_strays() -> None:
    """Гасит все прочие экземпляры бота — иначе они дерут токен и воюют."""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='python3.9.exe'", "get", "processid,commandline"],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
    except Exception:
        return
    me = os.getpid()
    for line in out.splitlines():
        if "bot.py" not in line or "bot_supervisor" in line:
            continue
        for token in line.split():
            if token.strip().isdigit():
                pid = int(token.strip())
                if pid and pid != me:
                    try:
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                        print("убит лишний экземпляр бота (PID %d)" % pid, flush=True)
                    except Exception:
                        pass
                break


def main() -> int:
    restarts = 0
    log_path = ROOT / "data" / "bot.log"
    while True:
        try:
            _kill_strays()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_path, "a", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(
                [sys.executable, str(BOT)],
                cwd=str(ROOT),
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            handle.close()
        except Exception as exc:
            print("не удалось запустить бота: %s" % exc, flush=True)
            time.sleep(DELAY)
            continue

        code = proc.wait()
        restarts += 1
        print(
            "бот завершился (код %s), перезапуск через %d с (перезапусков: %d)" % (code, DELAY, restarts),
            flush=True,
        )
        time.sleep(DELAY)


if __name__ == "__main__":
    sys.exit(main())
