"""Тесты лицензий: одноразовый ключ, привязка к аккаунту, изоляция прогресса.

Запуск: python tests/test_license.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="slovak_lic_"))
os.environ["DB_PATH"] = str(TMP / "lic.db")
os.environ["AI_PROVIDER"] = "off"
os.environ["APP_DEV"] = "0"
os.environ["OWNER_BYPASS_LICENSE"] = "0"
os.environ["ADMIN_IDS"] = "111"

from app import db  # noqa: E402
from app import content as content_mod  # noqa: E402
from app import licensing  # noqa: E402
from app.config import CONFIG  # noqa: E402

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s %s" % (name, detail))


def main() -> int:
    db.init_db()

    print("\n== Генерация ключей ==")
    codes = licensing.create_keys(3, 0, "тест", "batch-1")
    check("создано 3 ключа", len(codes) == 3, str(codes))
    check("длина ключа 20 символов", all(len(c) == 20 for c in codes), str(codes))
    check(
        "формат: буквы, цифры и знаки",
        all(licensing.NEW_CODE_RE.match(c) for c in codes),
        str(codes),
    )
    check("в каждом ключе есть буквы", all(any(ch.isalpha() for ch in c) for c in codes))
    check("в каждом ключе есть цифры", all(any(ch.isdigit() for ch in c) for c in codes))
    check("в каждом ключе есть знаки", all(any(not ch.isalnum() for ch in c) for c in codes))
    check("ключи разные", len(set(codes)) == 3)
    check(
        "ключ есть в БД",
        db.query_one("SELECT id FROM licenses WHERE code = ?", (codes[0],)) is not None,
    )

    print("\n== Погашение ключа ==")
    ok, message = licensing.redeem(codes[0], 500)
    check("первый ввод принимается", ok, message)
    check("подписка создана", licensing.get_subscription(500) is not None)
    check("доступ активен", licensing.is_active(500))
    check("бессрочный доступ", licensing.remaining_days(500) is None)
    check("ключ помечен использованным", licensing.get_license(codes[0])["used_by"] == 500)

    print("\n== Ключ одноразовый ==")
    ok, message = licensing.redeem(codes[0], 500)
    check("повторный ввод отклонён", not ok, message)
    ok, message = licensing.redeem(codes[0], 501)
    check("другой человек не может использовать", not ok, message)
    check("у второго нет доступа", not licensing.is_active(501))

    print("\n== Владелец ==")
    check("владелец помечен как owner", licensing.is_owner(111))
    CONFIG.owner_bypass_license = True
    check("с байпасом владелец работает без ключа", licensing.is_active(111))
    CONFIG.owner_bypass_license = False
    check("без байпаса владелец тоже требует ключ", not licensing.is_active(111))
    CONFIG.owner_bypass_license = True

    print("\n== Срок подписки ==")
    timed = licensing.create_keys(1, 30, "месяц")[0]
    ok, message = licensing.redeem(timed, 600)
    check("ключ на 30 дней принят", ok, message)
    days = licensing.remaining_days(600)
    check("осталось ~30 дней", days is not None and 28 <= days <= 30, str(days))
    check("подписка активна", licensing.is_active(600))
    check("есть дата окончания", licensing.get_subscription(600)["expires_at"] is not None)

    print("\n== Продление и отзыв ==")
    new_until = licensing.extend(600, 30)
    check("продление увеличивает срок", new_until is not None)
    days_after = licensing.remaining_days(600)
    check("стало больше дней", days_after is not None and days_after > days, "%s -> %s" % (days, days_after))

    revocable = licensing.create_keys(1, 0)[0]
    licensing.redeem(revocable, 700)
    check("доступ был", licensing.is_active(700))
    licensing.revoke(revocable)
    check("после отзыва доступа нет", not licensing.is_active(700))

    print("\n== Нормализация кода ==")
    weird = " " + codes[1][:10] + " " + codes[1][10:] + " "
    canonical = licensing.normalize_code(weird)
    check("мусорный ввод нормализуется", canonical == codes[1], "%s vs %s" % (canonical, codes[1]))
    ok, message = licensing.redeem(weird, 800)
    check("нормализованный ключ работает", ok, message)
    check("регистр не важен", licensing.normalize_code(codes[1].lower()) == codes[1])

    print("\n== Изоляция прогресса ==")
    db.ensure_user(500)
    db.ensure_user(900)
    db.bump_lesson(500, "1a", 8, 10, 0.8)
    db.bump_lesson(900, "1b", 3, 10, 0.3)
    db.add_xp(500, 50)
    db.add_xp(900, 10)
    db.log_attempt(500, "1a", 0, "type", "sú", "som", "bad", "verb_form")

    check(
        "прогресс пользователя 500 записан",
        content_mod.lesson_done(500, "1a") and not content_mod.lesson_done(500, "1b"),
    )
    check(
        "прогресс пользователя 900 другой",
        content_mod.lesson_done(900, "1b") and not content_mod.lesson_done(900, "1a"),
    )
    check("XP раздельный", db.get_user(500)["xp"] == 50 and db.get_user(900)["xp"] == 10)
    tags_500 = db.query("SELECT tag FROM error_tags WHERE user_id = 500")
    tags_900 = db.query("SELECT tag FROM error_tags WHERE user_id = 900")
    check("ошибки не смешиваются", len(tags_500) == 1 and len(tags_900) == 0)
    words_500 = db.query("SELECT COUNT(*) AS n FROM user_words WHERE user_id = 500")
    words_900 = db.query("SELECT COUNT(*) AS n FROM user_words WHERE user_id = 900")
    check("карточки слов раздельные", words_500[0]["n"] == 0 and words_900[0]["n"] == 0)

    print("\n== Сводка ==")
    stats = licensing.stats()
    check("счётчики считаются", stats["total"] >= 5 and stats["used"] >= 4, str(stats))
    check("активных подписок 3 (отозванная не считается)", stats["active"] == 3, str(stats))
    check("список подписчиков не пуст", len(licensing.list_subscribers(50)) >= 4)

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
