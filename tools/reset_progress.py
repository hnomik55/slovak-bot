"""Сброс прогресса (после тестов). Бэкап делается сам."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import CONFIG  # noqa: E402


def main() -> int:
    backup = CONFIG.db_path.with_name(
        "slovak.db.bak-%s" % datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    shutil.copy2(CONFIG.db_path, backup)
    print("бэкап: %s" % backup.name)

    db.execute("DELETE FROM attempts")
    db.execute("DELETE FROM lesson_progress")
    db.execute("DELETE FROM error_tags")
    db.execute("DELETE FROM daily_stats")
    db.execute("DELETE FROM user_words")
    db.execute("DELETE FROM sessions")
    db.execute("DELETE FROM writing")
    db.execute("UPDATE users SET xp = 0, streak = 0, best_streak = 0, last_day = NULL")
    print("прогресс сброшен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
