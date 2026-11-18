"""Чистка тестовых записей из баз (пользователи 700001/999111 — из автотестов)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_IDS = (700001, 999111, 999222, 424242, 424243, 8636653096)

TARGETS = [ROOT / "data" / "slovak.db", ROOT / "state" / "slovak.db"]


def clean(path: Path) -> None:
    if not path.exists():
        return
    con = sqlite3.connect(str(path))
    ids = ",".join(str(i) for i in TEST_IDS)
    for table, column in (
        ("attempts", "user_id"),
        ("lesson_progress", "user_id"),
        ("error_tags", "user_id"),
        ("daily_stats", "user_id"),
        ("user_words", "user_id"),
        ("writing", "user_id"),
        ("generated", "user_id"),
        ("users", "tg_id"),
        ("sessions", "user_id"),
    ):
        try:
            cur = con.execute("DELETE FROM %s WHERE %s IN (%s)" % (table, column, ids))
            if cur.rowcount:
                print("  %-16s удалено %d" % (table, cur.rowcount))
        except sqlite3.Error:
            pass
    con.commit()
    con.close()


for target in TARGETS:
    print("чищу %s" % target.name)
    clean(target)
print("готово")
