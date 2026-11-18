"""Сторож: поднимает бота, если тот упал.

Сеть (особенно VPN) периодически рвётся, и бот падает с Bad Gateway.
Сторож просто перезапускает процесс — ученик этого не замечает.

    python tools/bot_supervisor.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT / "bot.py"
DELAY = 8


def main() -> int:
    restarts = 0
    while True:
        try:
            proc = subprocess.Popen([sys.executable, str(BOT)], cwd=str(ROOT))
        except Exception as exc:
            print("не удалось запустить бота: %s" % exc, flush=True)
            time.sleep(DELAY)
            continue

        code = proc.wait()
        restarts += 1
        print("бот завершился (код %s), перезапуск через %d с (перезапусков: %d)" % (code, DELAY, restarts), flush=True)
        time.sleep(DELAY)


if __name__ == "__main__":
    sys.exit(main())
