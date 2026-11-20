"""Импорт партии ключей в базу.

    python tools\\import_keys.py data\\keys\\keys-sale-20261118-100.txt
    python tools\\import_keys.py keys.txt --db C:\\путь\\к\\slovak.db --batch sale-1
    python tools\\import_keys.py --export free-keys.txt

Зачем: база на сервере и база на домашнем ПК — разные файлы. Ключи,
созданные локально, не появляются на хостинге сами, поэтому покупатель
видит «Ключ не найден». Этой командой партия переносится в нужную базу.

Файл может быть .txt (ключ на строку) или .csv (колонка key).
Строки-комментарии (# ...) пропускаются.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_app(db_path: str = ""):
    """Импортирует приложение уже с нужным DB_PATH."""
    if db_path:
        os.environ["DB_PATH"] = str(Path(db_path).resolve())
    from app import db  # noqa: E402
    from app import licensing  # noqa: E402

    db.init_db()
    return db, licensing


def main() -> int:
    parser = argparse.ArgumentParser(description="Перенос ключей доступа")
    parser.add_argument("file", nargs="?", help="txt/csv с ключами")
    parser.add_argument("--db", default="", help="путь к базе (по умолчанию DB_PATH)")
    parser.add_argument("--days", type=int, default=0, help="срок новых ключей (0 = бессрочно)")
    parser.add_argument("--batch", default="", help="метка партии")
    parser.add_argument("--text", default="", help="ключи строкой вместо файла")
    parser.add_argument("--export", default="", help="выгрузить все ключи в файл")
    parser.add_argument("--stats", action="store_true", help="только показать сводку")
    args = parser.parse_args()

    db, licensing = _load_app(args.db)

    if args.export:
        rows = licensing.list_licenses(10000)
        if not rows:
            print("В базе нет ключей.")
            return 1
        target = Path(args.export)
        target.parent.mkdir(parents=True, exist_ok=True)
        with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# Ключи активации (выгрузка %s)\n\n" % db.now())
            for row in rows:
                fh.write(row["code"] + "\n")
        print("Выгружено %d ключей: %s" % (len(rows), target))
        return 0

    if args.stats or (not args.file and not args.text):
        stats = licensing.stats()
        print("Ключей: %d, использовано: %d, активных подписок: %d"
              % (stats["total"], stats["used"], stats["active"]))
        if not args.stats and not args.file and not args.text:
            print("Укажи файл или --text. Пример: python tools\\import_keys.py keys.txt")
        return 0

    text = args.text
    if args.file:
        source = Path(args.file)
        if not source.exists():
            print("Файл не найден: %s" % source)
            return 2
        text = source.read_text(encoding="utf-8", errors="replace")
        args.batch = args.batch or source.stem

    codes = licensing.parse_codes(text)
    if not codes:
        print("Ключей в источнике не найдено.")
        return 2

    result = licensing.import_codes(codes, args.days, "", args.batch)
    print("Найдено: %d, добавлено: %d, уже были: %d, мусор: %d"
          % (result["received"], result["imported"], result["existing"], result["invalid"]))
    stats = licensing.stats()
    print("Теперь в базе: %d ключей (%d свободных)"
          % (stats["total"], stats["total"] - stats["used"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
