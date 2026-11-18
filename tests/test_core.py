"""Проверки ядра без Телеграма: контент, оценки, SRS, БД, markdown.

Запуск: python tests/test_core.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Временная БД, чтобы не трогать рабочую
TMP = Path(tempfile.mkdtemp(prefix="slovak_test_"))
os.environ["DB_PATH"] = str(TMP / "test.db")
os.environ["AI_PROVIDER"] = "off"

from app import db  # noqa: E402
from app import content as content_mod  # noqa: E402
from app.markdown import md_to_html  # noqa: E402
from app.scoring import (  # noqa: E402
    RESULT_ACCENTS,
    RESULT_BAD,
    RESULT_OK,
    RESULT_TYPO,
    grade_build,
    grade_text,
    infer_tag,
    missing_accents,
)
from app.srs import review  # noqa: E402

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


def section(title: str) -> None:
    print("\n== %s ==" % title)


# --------------------------------------------------------------------------- #
section("Контент")
content = content_mod.CONTENT.load(force=True)
stats = content.stats()
check("уроки загружены", stats["lessons"] >= 40, str(stats))
check("задания загружены", stats["tasks"] >= 300, str(stats))
check("слова загружены", stats["vocab"] >= 800, str(stats))
check("слабые места разобраны", len(content.weak_spots) >= 5, str(len(content.weak_spots)))
check("письма разобраны", len(content.writing) == 2, str(len(content.writing)))
check("методички по навыкам", len(content.skills) == 4, str(len(content.skills)))
check("конспекты уроков", len(content.lesson_docs) == 7, str(len(content.lesson_docs)))

for lesson in content.lessons:
    for task in lesson["tasks"]:
        if task["kind"] == "choice":
            assert 0 <= task["answer"] < len(task["options"]), task
            assert len(task["options"]) >= 2, task
        if task["kind"] == "type":
            assert task["answers"], task
        if task["kind"] == "build":
            assert task["answer"], task
check("все задания схемно корректны", True)

kinds = {}
for lesson in content.lessons:
    for task in lesson["tasks"]:
        kinds[task["kind"]] = kinds.get(task["kind"], 0) + 1
check("все 4 типа заданий представлены", set(kinds) == {"choice", "type", "build", "match"}, str(kinds))


# --------------------------------------------------------------------------- #
section("Оценка ответов")
check("точный ответ", grade_text("som", ["som"])[0] == RESULT_OK)
check("регистр не важен", grade_text("SOM", ["som"])[0] == RESULT_OK)
check("лишние пробелы", grade_text("  som ", ["som"])[0] == RESULT_OK)
check("без диакритики — 'почти'", grade_text("osemnast", ["osemnásť"])[0] == RESULT_ACCENTS)
check("опечатка — 'почти'", grade_text("mamau", ["mama"])[0] == RESULT_TYPO)
check("совсем другое — неверно", grade_text("kikiriki", ["som"])[0] == RESULT_BAD)
check("второй вариант ответа", grade_text("Nie sme z Prahy", ["Nie sme z Prahy"])[0] == RESULT_OK)
check("сборка фразы ок", grade_build(["Nie", "som", "unavený"], "Nie som unavený")[0] == RESULT_OK)
check("сборка — другой порядок", grade_build(["Som", "z", "Ruska"], "Som z Ruska")[0] == RESULT_OK)
check("сборка — лишнее слово", grade_build(["Nie", "som", "unavený", "je"], "Nie som unavený")[0] == RESULT_BAD)
check("потерянные буквы найдены", missing_accents("osemnast", "osemnásť") == ["á", "ť"], str(missing_accents("osemnast", "osemnásť")))
check("тег: диа_критика", infer_tag("type", RESULT_ACCENTS, "osemnast", "osemnásť") == "diacritics")
check("тег: падеж по уроку", infer_tag("type", RESULT_BAD, "mama", "mamu", "3a") == "accusative")
check("тег: глагол", infer_tag("type", RESULT_BAD, "sú", "som", "1b") == "verb_form")
check("тег: лишнее слово", infer_tag("type", RESULT_BAD, "som som", "som", "1b") == "extra_words")


# --------------------------------------------------------------------------- #
section("Интервальное повторение")
card = review(None, 3)
check("новое слово — интервал 1 день", card["interval"] == 1, str(card))
card = review(card, 2)
check("второй раз — длиннее", card["interval"] > 1, str(card))
card2 = review(card, 0)
check("забыл — сброс на 1 день", card2["interval"] == 1, str(card2))
check("забыл — счётчик lapses", card2["lapses"] == 1, str(card2))
check("ease не падает ниже 1.3", review({"ease": 1.3, "interval": 5, "reps": 3}, 0)["ease"] >= 1.3)


# --------------------------------------------------------------------------- #
section("База данных")
db.init_db()
db.upsert_vocab(content.vocab)
user = db.ensure_user(12345, "tester", "Тест")
check("пользователь создан", user["tg_id"] == 12345)
db.touch_day(12345, xp=10, tasks=2, correct=1)
again = db.get_user(12345)
check("XP начислен", again["xp"] == 10, str(again["xp"]))
check("серия дней = 1", again["streak"] == 1, str(again["streak"]))
db.log_attempt(12345, "1b", 0, "type", "somn", "som", RESULT_BAD, "verb_form")
tags = db.query("SELECT tag, count FROM error_tags WHERE user_id = 12345")
check("ошибка записана в блок ошибок", tags and tags[0]["tag"] == "verb_form", str(tags))
db.bump_lesson(12345, "1b", 5, 6, 0.83)
check("прогресс урока сохранён", content_mod.lesson_done(12345, "1b"))
check("mastery посчитан", abs(content_mod.mastery(12345, "1b") - 0.83) < 0.01)

# Разблокировка: отдельный пользователь, чтобы не мешать другим проверкам
db.ensure_user(999)
lessons = content.lessons
first, second = lessons[0]["id"], lessons[1]["id"]
check("первый урок открыт", content_mod.is_unlocked(999, first, lessons))
db.bump_lesson(999, first, 9, 10, 0.9)
check("второй урок открылся после 80%", content_mod.is_unlocked(999, second, lessons))
db.bump_lesson(999, second, 2, 10, 0.2)
check("третий урок закрыт при слабом результате", not content_mod.is_unlocked(999, lessons[2]["id"], lessons))

# Словарь
rows = db.query("SELECT COUNT(*) AS n FROM vocab")
check("словарь в БД", rows[0]["n"] >= 800, str(rows[0]["n"]))


# --------------------------------------------------------------------------- #
section("Markdown -> HTML")
html = md_to_html("# Заголовок\n\n**жирный** и *курсив*\n\n| a | b |\n|---|---|\n| 1 | 2 |")
check("заголовок", "<b>Заголовок</b>" in html, html)
check("жирный", "<b>жирный</b>" in html, html)
check("таблица", "a — b" in html, html)
check("экранирование", "&lt;" in md_to_html("<script>alert(1)</script>"), md_to_html("<script>alert(1)</script>"))


# --------------------------------------------------------------------------- #
section("Очистка")
shutil.rmtree(TMP, ignore_errors=True)
print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
sys.exit(1 if FAILED else 0)
