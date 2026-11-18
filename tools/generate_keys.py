"""Генерация и выгрузка ключей доступа.

    python tools\generate_keys.py 100            -> 100 бессрочных ключей
    python tools\generate_keys.py 50 30          -> 50 ключей на 30 дней
    python tools\generate_keys.py --export       -> выгрузить свободные ключи в файл

Файлы кладутся в data/keys/ (в git не попадают — это товар).
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app import licensing  # noqa: E402

KEYS_DIR = ROOT / "data" / "keys"


def generate(count: int, days: int, note: str, batch: str) -> None:
    db.init_db()
    batch = batch or ("sale-%s" % datetime.now().strftime("%Y%m%d"))
    codes = licensing.create_keys(count, days, note, batch)
    plan = "бессрочно" if days <= 0 else "%d дней" % days
    print("Создано ключей: %d (%s), партия %s" % (len(codes), plan, batch))

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    txt_path = KEYS_DIR / ("keys-%s-%d.txt" % (batch, len(codes)))
    csv_path = KEYS_DIR / ("keys-%s-%d.csv" % (batch, len(codes)))

    with io.open(txt_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Ключи активации бота. Каждый ключ работает ОДИН раз.\n")
        fh.write("# Партия: %s | План: %s | Создано: %s\n" % (batch, plan, datetime.now().isoformat(timespec="seconds")))
        fh.write("# Просто отдай покупателю один ключ — он введёт его в боте.\n\n")
        for code in codes:
            fh.write(code + "\n")

    with io.open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "batch", "plan_days", "note"])
        for code in codes:
            writer.writerow([code, batch, days, note])

    print("Текст: %s" % txt_path.name)
    print("CSV:   %s" % csv_path.name)
    print("Первые три:")
    for code in codes[:3]:
        print("  %s" % code)


def export_unused() -> None:
    db.init_db()
    rows = licensing.list_licenses(1000, unused_only=True)
    if not rows:
        print("Свободных ключей нет.")
        return
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    path = KEYS_DIR / ("free-%s.txt" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(row["code"] + "\n")
    print("Выгружено %d ключей: %s" % (len(rows), path.name))


def main() -> int:
    parser = argparse.ArgumentParser(description="Ключи доступа")
    parser.add_argument("count", nargs="?", type=int, default=100)
    parser.add_argument("days", nargs="?", type=int, default=0)
    parser.add_argument("--note", default="")
    parser.add_argument("--batch", default="")
    parser.add_argument("--export", action="store_true", help="только выгрузить свободные")
    args = parser.parse_args()

    if args.export:
        export_unused()
        return 0
    generate(args.count, args.days, args.note, args.batch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
