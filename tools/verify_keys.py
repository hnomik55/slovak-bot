"""Проверка партии ключей: формат, уникальность, одноразовость."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, licensing  # noqa: E402

PATTERN = re.compile(r"^[A-Z0-9\-_!@#$%&*+=?.]{20}$")

db.init_db()
rows = licensing.list_licenses(1000, unused_only=True)
codes = [r["code"] for r in rows]

bad_len = [c for c in codes if len(c) != 20]
bad_fmt = [c for c in codes if not PATTERN.match(c)]
dupes = len(codes) - len(set(codes))

print("Свободных ключей: %d" % len(codes))
print("Неверная длина: %d" % len(bad_len))
print("Неверный формат: %d %s" % (len(bad_fmt), bad_fmt[:3]))
print("Дубликатов: %d" % dupes)

# состав символов
letters = sum(1 for c in codes if any(ch.isalpha() for ch in c))
digits = sum(1 for c in codes if any(ch.isdigit() for ch in c))
symbols = sum(1 for c in codes if any(not ch.isalnum() for ch in c))
print("С буквами: %d, с цифрами: %d, со знаками: %d" % (letters, digits, symbols))

# одноразовость на реальном ключе
test = codes[0]
ok1, msg1 = licensing.redeem(test, 700001)
ok2, msg2 = licensing.redeem(test, 700001)
ok3, msg3 = licensing.redeem(test, 700002)
print("Первый ввод: %s (%s)" % (ok1, msg1))
print("Повторный: %s (%s)" % (ok2, msg2))
print("Чужой: %s (%s)" % (ok3, msg3))
db.execute("UPDATE licenses SET used_by = NULL, used_at = NULL WHERE code = ?", (test,))
db.execute("DELETE FROM subscriptions WHERE telegram_id = 700001")
print("Активация откачена для продажи.")

good = not bad_len and not bad_fmt and dupes == 0 and ok1 and not ok2 and not ok3
print("\nИТОГ: %s" % ("ок" if good else "есть проблемы"))
sys.exit(0 if good else 1)
