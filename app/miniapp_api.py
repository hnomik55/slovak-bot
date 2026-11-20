"""API для Telegram Mini App.

Тот же функционал, что и у бота в чате, но через HTTP: приложение открывается
внутри Telegram по кнопке «Открыть😄» и работает как обычное приложение.

Оценка ответов делается на сервере (правильные ответы в приложение не уходят),
прогресс пишется в ту же базу, что и у бота, — поэтому чат и приложение
виден один и тот же результат.
"""

from __future__ import annotations

import logging
import random
import re
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from app import content as content_mod
from app import db
from app import licensing
from app.config import CONFIG
from app.miniapp_auth import dev_user, verify_init_data
from app.scoring import (
    RESULT_ACCENTS,
    RESULT_BAD,
    RESULT_OK,
    RESULT_TYPO,
    grade_build,
    grade_choice,
    grade_text,
    infer_tag,
    missing_accents,
    norm,
)
from app.services.ai import AI
from app.services.lexicon import add_words, enroll
from app.services.tts import TTS
from app.srs import review
from app.utils import XP_LESSON, XP_PERFECT, XP_PER_TASK, add_stats

log = logging.getLogger("miniapp")
bp = Blueprint("miniapp", __name__, url_prefix="/api")

TAG_RU = {
    "diacritics": "потерянная диакритика",
    "verb_form": "форма глагола",
    "accusative": "винительный падеж",
    "locative": "предложный падеж",
    "genitive": "родительный падеж",
    "future": "будущее время",
    "past_tense": "прошедшее время",
    "spelling": "орфография",
    "extra_words": "лишние слова",
    "missing_words": "пропущены слова",
    "agreement": "согласование",
    "sa_verb": "конструкция sa",
    "case": "падеж",
    "order": "порядок слов",
    "pairs": "пары",
    "grammar": "грамматика",
    "empty": "пустой ответ",
    "misc": "разное",
}


# --------------------------------------------------------------------------- #
# Авторизация
# --------------------------------------------------------------------------- #
def current_user() -> Optional[int]:
    """Telegram id пользователя по initData (или dev-режим)."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        user = verify_init_data(init_data, CONFIG.bot_token)
        if user:
            try:
                return int(user.get("id"))
            except (TypeError, ValueError):
                return None
        return None
    return dev_user()


def require_user():
    """Возвращает (user_id, error_response)."""
    user_id = current_user()
    if not user_id:
        return None, (jsonify({"error": "unauthorized"}), 401)
    if not licensing.is_active(user_id):
        return None, (jsonify({"error": "license_required"}), 403)
    db.ensure_user(user_id)
    return user_id, None


def require_user_soft():
    """Как require_user, но без проверки лицензии (для /session и /license)."""
    user_id = current_user()
    if not user_id:
        return None, (jsonify({"error": "unauthorized"}), 401)
    db.ensure_user(user_id)
    return user_id, None


def license_info(user_id: int) -> Dict[str, Any]:
    days = licensing.remaining_days(user_id)
    sub = licensing.get_subscription(user_id)
    return {
        "active": licensing.is_active(user_id),
        "owner": licensing.is_owner(user_id),
        "plan": (sub or {}).get("plan"),
        "expires_at": (sub or {}).get("expires_at"),
        "days_left": days,
    }


@bp.post("/redeem")
def api_redeem():
    """Активация ключа доступа."""
    user_id, error = require_user_soft()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"error": "no_code"}), 400
    ok, message = licensing.redeem(code, user_id)
    return jsonify({"ok": ok, "message": message, "license": license_info(user_id)}), (
        200 if ok else 400
    )


# --------------------------------------------------------------------------- #
# Преобразование заданий (без правильных ответов)
# --------------------------------------------------------------------------- #
def public_task(task: Dict[str, Any], index: int) -> Dict[str, Any]:
    kind = task.get("kind")
    out: Dict[str, Any] = {"i": index, "kind": kind, "prompt": task.get("prompt", "")}
    if kind == "choice":
        out["options"] = list(task.get("options") or [])
    elif kind == "type":
        out["sk"] = task.get("sk", "")
    elif kind == "build":
        out["words"] = list(task.get("words") or [])
    elif kind == "match":
        out["pairs"] = [list(p) for p in (task.get("pairs") or [])]
    return out


def public_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [public_task(t, i) for i, t in enumerate(tasks)]


def grade_task(task: Dict[str, Any], value: Any) -> Dict[str, Any]:
    """Оценивает ответ. Возвращает результат, эталон, тег и объяснение."""
    kind = task.get("kind")
    result = RESULT_BAD
    expected = ""
    given = ""

    if kind == "choice":
        try:
            index = int(value)
        except (TypeError, ValueError):
            index = -1
        options = task.get("options") or []
        correct = int(task.get("answer", 0))
        result = grade_choice(index, correct)
        expected = options[correct] if 0 <= correct < len(options) else ""
        given = options[index] if 0 <= index < len(options) else ""
    elif kind == "type":
        given = str(value or "")
        result, expected = grade_text(given, task.get("answers") or [])
        expected = expected or ""
    elif kind == "build":
        words = value if isinstance(value, list) else []
        given = " ".join(str(w) for w in words)
        result, expected = grade_build(words, task.get("answer") or "")
        expected = expected or task.get("answer") or ""
    elif kind == "match":
        mapping = value if isinstance(value, dict) else {}
        pairs = task.get("pairs") or []
        good = 0
        for left, right in pairs:
            if norm(mapping.get(left, "")) == norm(right):
                good += 1
        total = len(pairs) or 1
        result = RESULT_OK if good == total else (RESULT_TYPO if good >= total * 0.6 else RESULT_BAD)
        given = "%d/%d" % (good, total)
        expected = "; ".join("%s — %s" % (p[0], p[1]) for p in pairs)

    tag = infer_tag(kind, result, given, expected, task.get("lesson", "") or "")
    return {
        "result": result,
        "result_ru": {
            RESULT_OK: "Верно",
            RESULT_TYPO: "Почти (опечатка)",
            RESULT_ACCENTS: "Почти (диакритика)",
            RESULT_BAD: "Неверно",
        }.get(result, result),
        "expected": expected,
        "given": given,
        "explanation": task.get("explain"),
        "missing_accents": missing_accents(given, expected) if result == RESULT_ACCENTS else [],
        "tag": tag,
    }


# --------------------------------------------------------------------------- #
# Сессия урока (серверное состояние)
# --------------------------------------------------------------------------- #
def get_session(user_id: int) -> Dict[str, Any]:
    row = db.get_session(user_id)
    data = (row or {}).get("data") or {}
    if row and row.get("mode", "").startswith("miniapp"):
        return data
    return {}


def save_session(user_id: int, data: Dict[str, Any]) -> None:
    db.set_session(user_id, "miniapp", data)


def clear_session(user_id: int) -> None:
    db.clear_session(user_id)


# --------------------------------------------------------------------------- #
# Эндпоинты
# --------------------------------------------------------------------------- #
@bp.get("/session")
def api_session():
    user_id, error = require_user_soft()
    if error:
        return error
    user = db.get_user(user_id) or {}
    return jsonify(
        {
            "user": {
                "telegram_id": user_id,
                "first_name": user.get("first_name") or "Ученик",
                "level": user.get("level", "A1"),
                "xp": user.get("xp", 0),
                "streak": user.get("streak", 0),
                "best_streak": user.get("best_streak", 0),
            },
            "license": license_info(user_id),
            "app": {"title": "Slovencina", "version": "1.0"},
        }
    )


@bp.get("/home")
def api_home():
    user_id, error = require_user()
    if error:
        return error
    user = db.get_user(user_id) or {}
    level = content_mod.user_level(user_id)
    lessons = content_mod.all_lessons(user_id)
    level_lessons = [l for l in lessons if (l.get("level") or "A2") == level]
    stats = content_mod.CONTENT.stats()

    done_rows = db.query(
        "SELECT correct, total FROM lesson_progress WHERE user_id = ? AND done = 1", (user_id,)
    )
    tasks_done = sum(int(r.get("total") or 0) for r in done_rows)
    tasks_correct = sum(int(r.get("correct") or 0) for r in done_rows)

    words_learned = db.query_one(
        """SELECT COUNT(*) AS n FROM user_words uw JOIN vocab v ON v.id = uw.vocab_id
           WHERE uw.user_id = ? AND uw.state != 'new'""",
        (user_id,),
    )
    words_due = db.query_one(
        "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?", (user_id, db.today())
    )
    week = db.query(
        """SELECT tasks, correct FROM daily_stats
           WHERE user_id = ? AND day >= date('now', '-7 day')""",
        (user_id,),
    )
    tasks_week = sum(r["tasks"] or 0 for r in week)
    correct_week = sum(r["correct"] or 0 for r in week)

    units = []
    for unit in content_mod.units_for_level(level):
        unit_lessons = [l for l in lessons if str(l.get("unit")) == str(unit.get("n"))]
        done = sum(1 for l in unit_lessons if content_mod.lesson_done(user_id, l["id"]))
        units.append(
            {
                "n": unit.get("n"),
                "num": unit.get("num") or unit.get("n"),
                "level": unit.get("level", "A2"),
                "title": unit.get("title", ""),
                "desc": unit.get("desc", ""),
                "lessons_done": done,
                "lessons_total": len(unit_lessons),
            }
        )

    levels = []
    for code in content_mod.LEVELS:
        code_lessons = [l for l in lessons if (l.get("level") or "A2") == code]
        levels.append({"code": code, "lessons": len(code_lessons)})

    weak = db.query(
        "SELECT tag, count FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 6", (user_id,)
    )
    next_lesson = content_mod.next_lesson(user_id)

    return jsonify(
        {
            "level": level,
            "levels": levels,
            "xp": user.get("xp", 0),
            "streak": user.get("streak", 0),
            "best_streak": user.get("best_streak", 0),
            "lessons_done": sum(1 for l in level_lessons if content_mod.lesson_done(user_id, l["id"])),
            "lessons_total": len(level_lessons),
            "tasks_done": tasks_done,
            "tasks_total": sum(len(l.get("tasks") or []) for l in level_lessons),
            "accuracy": int(round(100 * correct_week / tasks_week)) if tasks_week else 0,
            "words_learned": int(words_learned["n"]) if words_learned else 0,
            "words_due": int(words_due["n"]) if words_due else 0,
            "units": units,
            "next_lesson": (
                {"id": next_lesson["id"], "title": next_lesson.get("title", ""), "unit": next_lesson.get("unit")}
                if next_lesson
                else None
            ),
            "weak_tags": [
                {"tag": r["tag"], "count": r["count"], "title_ru": TAG_RU.get(r["tag"], r["tag"])}
                for r in weak
            ],
        }
    )


@bp.get("/units")
def api_units():
    user_id, error = require_user()
    if error:
        return error
    level = (request.args.get("level") or content_mod.user_level(user_id)).upper()
    if level not in content_mod.LEVELS:
        level = content_mod.user_level(user_id)
    lessons = content_mod.all_lessons(user_id)
    out = []
    for unit in content_mod.units_for_level(level):
        unit_lessons = []
        for lesson in lessons:
            if str(lesson.get("unit")) != str(unit.get("n")):
                continue
            if (lesson.get("level") or "A2") != level:
                continue
            unit_lessons.append(
                {
                    "id": lesson["id"],
                    "title": lesson.get("title", ""),
                    "sub": lesson.get("sub", ""),
                    "done": content_mod.lesson_done(user_id, lesson["id"]),
                    "tasks": len(lesson.get("tasks") or []),
                    "locked": not content_mod.is_unlocked(user_id, lesson["id"], lessons),
                }
            )
        out.append(
            {
                "n": unit.get("n"),
                "num": unit.get("num") or unit.get("n"),
                "level": unit.get("level", "A2"),
                "title": unit.get("title", ""),
                "desc": unit.get("desc", ""),
                "lessons": unit_lessons,
            }
        )
    levels = []
    for code in content_mod.LEVELS:
        code_lessons = [l for l in lessons if (l.get("level") or "A2") == code]
        levels.append({"code": code, "lessons": len(code_lessons)})
    return jsonify({"level": level, "levels": levels, "units": out})


@bp.post("/level")
def api_level():
    """Переключение уровня: от него зависят уроки, юниты и новые слова."""
    user_id, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    level = str(data.get("level") or "").upper()
    if level not in content_mod.LEVELS:
        return jsonify({"error": "bad_level"}), 400
    db.execute("UPDATE users SET level = ? WHERE tg_id = ?", (level, user_id))
    return jsonify({"ok": True, "level": level})


@bp.get("/lesson/<lesson_id>")
def api_lesson(lesson_id: str):
    """Карточка урока + задания. Открытие урока начинает сессию."""
    user_id, error = require_user()
    if error:
        return error
    lessons = content_mod.all_lessons(user_id)
    lesson = next((l for l in lessons if l["id"] == lesson_id), None)
    if not lesson:
        return jsonify({"error": "not_found"}), 404

    tasks = lesson.get("tasks") or []
    save_session(
        user_id,
        {
            "kind": "lesson",
            "lesson_id": lesson_id,
            "title": lesson.get("title", lesson_id),
            "queue": tasks,
            "idx": 0,
            "correct": 0,
            "total": 0,
            "mistakes": [],
        },
    )
    return jsonify(
        {
            "id": lesson["id"],
            "title": lesson.get("title", ""),
            "sub": lesson.get("sub", ""),
            "unit": lesson.get("unit"),
            "rule": lesson.get("rule"),
            "tasks": public_tasks(tasks),
        }
    )


@bp.post("/answer")
def api_answer():
    user_id, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    session = get_session(user_id)
    queue = session.get("queue") or []
    idx = int(session.get("idx") or 0)
    if not queue or idx >= len(queue):
        return jsonify({"error": "no_session"}), 404

    task = queue[idx]
    task_i = int(data.get("task_i", idx))
    if task_i != idx:
        return jsonify({"error": "stale"}), 409

    answer = data.get("answer") or {}
    value = answer.get("value")
    graded = grade_task(task, value)

    correct_now = graded["result"] == RESULT_OK
    session["correct"] = int(session.get("correct") or 0) + (1 if correct_now else 0)
    session["total"] = int(session.get("total") or 0) + 1
    if not correct_now:
        mistakes = list(session.get("mistakes") or [])
        mistakes.append(
            {
                "given": graded["given"],
                "expected": graded["expected"],
                "tag": graded["tag"],
                "task_i": idx,
            }
        )
        session["mistakes"] = mistakes
    session["idx"] = idx + 1
    save_session(user_id, session)

    db.log_attempt(
        user_id,
        session.get("lesson_id") or "drill",
        idx,
        task.get("kind", ""),
        str(graded["given"])[:400],
        str(graded["expected"])[:400],
        graded["result"],
        graded["tag"],
    )
    add_stats(
        user_id,
        xp=XP_PER_TASK if correct_now else 0,
        tasks=1,
        correct=1 if correct_now else 0,
    )

    graded["score"] = {"correct": session["correct"], "total": session["total"]}
    graded["xp"] = XP_PER_TASK if correct_now else 0
    graded["finished"] = session["idx"] >= len(queue)
    return jsonify(graded)


@bp.post("/lesson/<lesson_id>/finish")
def api_lesson_finish(lesson_id: str):
    user_id, error = require_user()
    if error:
        return error
    session = get_session(user_id)
    correct = int(session.get("correct") or 0)
    total = int(session.get("total") or 0)
    percent = int(round(100 * correct / total)) if total else 0

    xp = 0
    if session.get("kind") == "lesson":
        db.bump_lesson(user_id, lesson_id, correct, total, (correct / total) if total else 0.0)
        xp = XP_LESSON + (XP_PERFECT if total and correct == total else 0)
        add_stats(user_id, xp=xp, tasks=0, correct=0)

    user = db.get_user(user_id) or {}
    next_lesson = content_mod.next_lesson(user_id)
    clear_session(user_id)

    return jsonify(
        {
            "correct": correct,
            "total": total,
            "percent": percent,
            "xp": xp,
            "streak": user.get("streak", 0),
            "mistakes": session.get("mistakes") or [],
            "next_lesson": (
                {"id": next_lesson["id"], "title": next_lesson.get("title", ""), "unit": next_lesson.get("unit")}
                if next_lesson
                else None
            ),
        }
    )


# --------------------------------------------------------------------------- #
# Слова (SRS)
# --------------------------------------------------------------------------- #
def _vocab_card(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "sk": row["sk"],
        "ru": row["ru"],
        "level": row.get("level", "A1"),
        "group": row.get("group_name", ""),
        "state": row.get("state", "new"),
        "interval": row.get("interval", 0),
    }


@bp.get("/vocab/due")
def api_vocab_due():
    user_id, error = require_user()
    if error:
        return error
    count = int(request.args.get("count", 20))
    rows = db.query(
        """SELECT v.*, uw.interval, uw.state FROM user_words uw JOIN vocab v ON v.id = uw.vocab_id
           WHERE uw.user_id = ? AND uw.due <= ? ORDER BY uw.due LIMIT ?""",
        (user_id, db.today(), count),
    )
    return jsonify({"cards": [_vocab_card(r) for r in rows]})


@bp.get("/vocab/new")
def api_vocab_new():
    user_id, error = require_user()
    if error:
        return error
    count = int(request.args.get("count", 10))
    user = db.get_user(user_id) or {}
    rows = db.query(
        """SELECT v.* FROM vocab v WHERE v.level = ?
           AND v.id NOT IN (SELECT vocab_id FROM user_words WHERE user_id = ?)
           ORDER BY v.id LIMIT ?""",
        (user.get("level", "A1"), user_id, count),
    )
    return jsonify({"cards": [_vocab_card(r) for r in rows]})


@bp.post("/vocab/rate")
def api_vocab_rate():
    user_id, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        vocab_id = int(data.get("vocab_id"))
        quality = int(data.get("quality"))
    except (TypeError, ValueError):
        return jsonify({"error": "bad_request"}), 400

    card = db.query_one(
        "SELECT * FROM user_words WHERE user_id = ? AND vocab_id = ?", (user_id, vocab_id)
    )
    state = review(card, quality)
    db.execute(
        """INSERT INTO user_words(user_id, vocab_id, ease, interval, due, reps, lapses, state, last_result)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id, vocab_id) DO UPDATE SET
               ease=excluded.ease, interval=excluded.interval, due=excluded.due,
               reps=excluded.reps, lapses=excluded.lapses, state=excluded.state,
               last_result=excluded.last_result""",
        (
            user_id,
            vocab_id,
            state["ease"],
            state["interval"],
            state["due"],
            state["reps"],
            state["lapses"],
            state["state"],
            state["last_result"],
        ),
    )
    add_stats(user_id, xp=1, tasks=1, correct=1 if quality >= 2 else 0)
    remaining = db.query_one(
        "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?", (user_id, db.today())
    )
    return jsonify(
        {
            "ok": True,
            "interval": state["interval"],
            "due": state["due"],
            "remaining": int(remaining["n"]) if remaining else 0,
        }
    )


# --------------------------------------------------------------------------- #
# Свои карточки и словари по уровням
# --------------------------------------------------------------------------- #
MAX_CARD_LEN = 120


def _pair_from_line(line: str):
    """«slovo — перевод», «slovo - перевод», «slovo<TAB>перевод» -> (sk, ru)."""
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    if "\t" in line:
        sk, ru = line.split("\t", 1)
        return sk.strip(), ru.strip()
    for sep in (" — ", " – ", " - ", " = ", ";"):
        if sep in line:
            sk, ru = line.split(sep, 1)
            return sk.strip(), ru.strip()
    return None


def _add_custom_card(user_id: int, level: str, sk: str, ru: str):
    sk = (sk or "").strip()
    ru = (ru or "").strip()
    if not sk or not ru or len(sk) > MAX_CARD_LEN or len(ru) > MAX_CARD_LEN:
        return None
    ids = add_words(level, [(sk, ru)], group="мои карточки")
    vocab_id = ids[0] if ids else None
    row = db.query_one(
        "SELECT id FROM user_cards WHERE user_id = ? AND lower(sk) = lower(?)", (user_id, sk)
    )
    if row:
        db.execute(
            "UPDATE user_cards SET ru = ?, vocab_id = ? WHERE id = ?", (ru, vocab_id, row["id"])
        )
        card_id = int(row["id"])
    else:
        db.execute(
            "INSERT INTO user_cards(user_id, sk, ru, vocab_id, created_at) VALUES(?,?,?,?,?)",
            (user_id, sk, ru, vocab_id, db.now()),
        )
        created = db.query_one(
            "SELECT id FROM user_cards WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        )
        card_id = int(created["id"]) if created else 0
    if vocab_id:
        enroll(user_id, [vocab_id])
    return {"id": card_id, "sk": sk, "ru": ru, "vocab_id": vocab_id}


def _vocab_stats(user_id: int) -> Dict[str, int]:
    total = db.query_one("SELECT COUNT(*) AS n FROM user_words WHERE user_id = ?", (user_id,))
    due = db.query_one(
        "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?",
        (user_id, db.today()),
    )
    custom = db.query_one("SELECT COUNT(*) AS n FROM user_cards WHERE user_id = ?", (user_id,))
    return {
        "in_train": int(total["n"]) if total else 0,
        "due": int(due["n"]) if due else 0,
        "custom": int(custom["n"]) if custom else 0,
    }


@bp.get("/vocab/mine")
def api_vocab_mine():
    user_id, error = require_user()
    if error:
        return error
    rows = db.query(
        """SELECT c.id, c.sk, c.ru, c.vocab_id, uw.state, uw.interval
           FROM user_cards c
           LEFT JOIN user_words uw
             ON uw.user_id = c.user_id AND uw.vocab_id = c.vocab_id
           WHERE c.user_id = ? ORDER BY c.id DESC""",
        (user_id,),
    )
    return jsonify(
        {
            "cards": [
                {
                    "id": r["id"],
                    "sk": r["sk"],
                    "ru": r["ru"],
                    "vocab_id": r["vocab_id"],
                    "state": r.get("state") or "new",
                    "interval": r.get("interval") or 0,
                }
                for r in rows
            ],
            "stats": _vocab_stats(user_id),
        }
    )


@bp.post("/vocab/custom")
def api_vocab_custom():
    user_id, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    level = content_mod.user_level(user_id)
    card = _add_custom_card(user_id, level, data.get("sk") or "", data.get("ru") or "")
    if not card:
        return jsonify({"error": "bad_card"}), 400
    return jsonify({"ok": True, "card": card, "stats": _vocab_stats(user_id)})


@bp.post("/vocab/custom/bulk")
def api_vocab_custom_bulk():
    user_id, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "")
    level = content_mod.user_level(user_id)
    added = 0
    skipped = 0
    for line in text.splitlines():
        pair = _pair_from_line(line)
        if not pair:
            if line.strip() and not line.strip().startswith("#"):
                skipped += 1
            continue
        card = _add_custom_card(user_id, level, pair[0], pair[1])
        if card:
            added += 1
        else:
            skipped += 1
    return jsonify({"ok": True, "added": added, "skipped": skipped, "stats": _vocab_stats(user_id)})


@bp.delete("/vocab/custom/<int:card_id>")
def api_vocab_custom_delete(card_id: int):
    user_id, error = require_user()
    if error:
        return error
    row = db.query_one(
        "SELECT * FROM user_cards WHERE id = ? AND user_id = ?", (card_id, user_id)
    )
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row.get("vocab_id"):
        db.execute(
            "DELETE FROM user_words WHERE user_id = ? AND vocab_id = ?",
            (user_id, row["vocab_id"]),
        )
    db.execute("DELETE FROM user_cards WHERE id = ? AND user_id = ?", (card_id, user_id))
    return jsonify({"ok": True, "stats": _vocab_stats(user_id)})


@bp.get("/vocab/browse")
def api_vocab_browse():
    user_id, error = require_user()
    if error:
        return error
    level = (request.args.get("level") or content_mod.user_level(user_id)).upper()
    if level not in content_mod.LEVELS:
        level = content_mod.user_level(user_id)
    query = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 200)), 500)

    sql = """
        SELECT v.id, v.sk, v.ru, v.group_name,
               CASE WHEN uw.vocab_id IS NULL THEN 0 ELSE 1 END AS added
        FROM vocab v
        LEFT JOIN user_words uw ON uw.vocab_id = v.id AND uw.user_id = ?
        WHERE v.level = ?
    """
    params: List[Any] = [user_id, level]
    if query:
        sql += " AND (v.sk LIKE ? OR v.ru LIKE ?)"
        like = "%" + query + "%"
        params.extend([like, like])
    sql += " ORDER BY v.group_name, v.id LIMIT ?"
    params.append(limit)
    rows = db.query(sql, params)

    counts = {r["level"]: int(r["n"]) for r in db.query("SELECT level, COUNT(*) AS n FROM vocab GROUP BY level")}
    enrolled = {
        r["level"]: int(r["n"])
        for r in db.query(
            """SELECT v.level, COUNT(*) AS n FROM user_words uw
               JOIN vocab v ON v.id = uw.vocab_id WHERE uw.user_id = ? GROUP BY v.level""",
            (user_id,),
        )
    }
    return jsonify(
        {
            "level": level,
            "levels": [
                {
                    "code": code,
                    "total": counts.get(code, 0),
                    "enrolled": enrolled.get(code, 0),
                }
                for code in content_mod.LEVELS
            ],
            "cards": [
                {
                    "id": r["id"],
                    "sk": r["sk"],
                    "ru": r["ru"],
                    "group": r.get("group_name") or "",
                    "added": bool(r["added"]),
                }
                for r in rows
            ],
            "stats": _vocab_stats(user_id),
        }
    )


@bp.post("/vocab/add")
def api_vocab_add():
    user_id, error = require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    ids: List[int] = []
    if data.get("all"):
        level = str(data.get("level") or content_mod.user_level(user_id)).upper()
        if level not in content_mod.LEVELS:
            return jsonify({"error": "bad_level"}), 400
        rows = db.query("SELECT id FROM vocab WHERE level = ?", (level,))
        ids = [int(r["id"]) for r in rows]
    else:
        for value in data.get("ids") or []:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
    if not ids:
        return jsonify({"error": "no_ids"}), 400

    before = _vocab_stats(user_id)["in_train"]
    enroll(user_id, ids)
    stats = _vocab_stats(user_id)
    return jsonify({"ok": True, "added": max(0, stats["in_train"] - before), "stats": stats})


# --------------------------------------------------------------------------- #
# Прогресс и ошибки
# --------------------------------------------------------------------------- #
@bp.get("/progress")
def api_progress():
    user_id, error = require_user()
    if error:
        return error
    user = db.get_user(user_id) or {}
    level = content_mod.user_level(user_id)
    lessons = content_mod.all_lessons(user_id)
    level_lessons = [l for l in lessons if (l.get("level") or "A2") == level]

    done_rows = db.query(
        "SELECT correct, total FROM lesson_progress WHERE user_id = ? AND done = 1", (user_id,)
    )
    tasks_done = sum(int(r.get("total") or 0) for r in done_rows)
    tasks_correct = sum(int(r.get("correct") or 0) for r in done_rows)

    words_learned = db.query_one(
        """SELECT COUNT(*) AS n FROM user_words uw JOIN vocab v ON v.id = uw.vocab_id
           WHERE uw.user_id = ? AND uw.state != 'new'""",
        (user_id,),
    )
    words_due = db.query_one(
        "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?", (user_id, db.today())
    )
    days = db.query(
        """SELECT day, xp, tasks, correct FROM daily_stats
           WHERE user_id = ? AND day >= date('now', '-7 day') ORDER BY day""",
        (user_id,),
    )
    units = []
    for unit in content_mod.units_for_level(level):
        unit_lessons = [l for l in lessons if str(l.get("unit")) == str(unit.get("n"))]
        done = sum(1 for l in unit_lessons if content_mod.lesson_done(user_id, l["id"]))
        units.append(
            {
                "n": unit.get("n"),
                "num": unit.get("num") or unit.get("n"),
                "title": unit.get("title", ""),
                "done": done,
                "total": len(unit_lessons),
            }
        )
    errors = db.query(
        "SELECT tag, count FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 12", (user_id,)
    )

    return jsonify(
        {
            "xp": user.get("xp", 0),
            "level": level,
            "streak": user.get("streak", 0),
            "best_streak": user.get("best_streak", 0),
            "lessons_done": sum(1 for l in level_lessons if content_mod.lesson_done(user_id, l["id"])),
            "lessons_total": len(level_lessons),
            "tasks_done": tasks_done,
            "accuracy": int(round(100 * tasks_correct / tasks_done)) if tasks_done else 0,
            "words_learned": int(words_learned["n"]) if words_learned else 0,
            "words_due": int(words_due["n"]) if words_due else 0,
            "days": [
                {"day": r["day"], "xp": r["xp"], "tasks": r["tasks"], "correct": r["correct"]} for r in days
            ],
            "units": units,
            "errors": [
                {"tag": r["tag"], "count": r["count"], "title_ru": TAG_RU.get(r["tag"], r["tag"])}
                for r in errors
            ],
        }
    )


@bp.get("/errors")
def api_errors():
    user_id, error = require_user()
    if error:
        return error
    tags = db.query(
        "SELECT tag, count FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 12", (user_id,)
    )
    recent = db.query(
        """SELECT lesson_id, task_i, given, expected, tag, created_at FROM attempts
           WHERE user_id = ? AND result != 'ok' ORDER BY id DESC LIMIT 20""",
        (user_id,),
    )
    return jsonify(
        {
            "tags": [
                {"tag": r["tag"], "count": r["count"], "title_ru": TAG_RU.get(r["tag"], r["tag"])}
                for r in tags
            ],
            "recent": [
                {
                    "lesson_id": r.get("lesson_id"),
                    "task_i": r.get("task_i"),
                    "given": r.get("given"),
                    "expected": r.get("expected"),
                    "tag": r.get("tag"),
                    "title_ru": TAG_RU.get(r.get("tag") or "", r.get("tag") or ""),
                    "created_at": r.get("created_at"),
                }
                for r in recent
            ],
        }
    )


@bp.post("/drill")
def api_drill():
    """Тренировка ошибок: конкретные задания, где ученик уже ошибался."""
    user_id, error = require_user()
    if error:
        return error
    rows = db.query(
        """SELECT lesson_id, task_i, COUNT(*) AS n FROM attempts
           WHERE user_id = ? AND result != 'ok' AND lesson_id != ''
           GROUP BY lesson_id, task_i ORDER BY n DESC LIMIT 20""",
        (user_id,),
    )
    tasks: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (row["lesson_id"], row["task_i"])
        if key in seen:
            continue
        seen.add(key)
        lesson = content_mod.CONTENT.lesson(row["lesson_id"])
        if not lesson:
            continue
        task = next((t for t in (lesson.get("tasks") or []) if t.get("i") == row["task_i"]), None)
        if task:
            tasks.append(task)
    if not tasks:
        return jsonify({"error": "no_mistakes"}), 404

    save_session(
        user_id,
        {
            "kind": "drill",
            "lesson_id": "drill",
            "title": "Тренировка ошибок",
            "queue": tasks,
            "idx": 0,
            "correct": 0,
            "total": 0,
            "mistakes": [],
        },
    )
    return jsonify(
        {
            "id": "drill",
            "title": "Тренировка ошибок",
            "sub": "Задания, где ты ошибался",
            "unit": None,
            "rule": None,
            "tasks": public_tasks(tasks),
        }
    )


@bp.post("/quiz")
def api_quiz():
    """Мини-тест: задания из пройденных уроков + вопросы по слабым местам."""
    user_id, error = require_user()
    if error:
        return error
    user = db.get_user(user_id) or {}
    done_rows = db.query(
        "SELECT lesson_id FROM lesson_progress WHERE user_id = ? AND done = 1", (user_id,)
    )
    pool: List[Dict[str, Any]] = []
    for row in done_rows:
        lesson = content_mod.CONTENT.lesson(row["lesson_id"])
        if not lesson:
            continue
        pool.extend(t for t in (lesson.get("tasks") or []) if t.get("kind") in ("choice", "type"))
    if not pool:
        for lesson in content_mod.CONTENT.lessons[:3]:
            pool.extend(t for t in (lesson.get("tasks") or []) if t.get("kind") in ("choice", "type"))
    random.shuffle(pool)
    tasks = pool[:10]
    if not tasks:
        return jsonify({"error": "no_tasks"}), 404

    save_session(
        user_id,
        {
            "kind": "quiz",
            "lesson_id": "test",
            "title": "Мини-тест",
            "queue": tasks,
            "idx": 0,
            "correct": 0,
            "total": 0,
            "mistakes": [],
        },
    )
    return jsonify({"title": "Мини-тест", "total": len(tasks), "tasks": public_tasks(tasks)})


# --------------------------------------------------------------------------- #
# Озвучка
# --------------------------------------------------------------------------- #
@bp.get("/speech")
def api_speech():
    user_id, error = require_user()
    if error:
        return error
    text = (request.args.get("text") or "").strip()
    if not text:
        return jsonify({"error": "no_text"}), 400
    path = _tts_sync(text)
    if not path:
        return jsonify({"error": "no_tts"}), 404
    return _send_file(path)


def _tts_sync(text: str):
    """Синтез озвучки (edge-tts + запасные источники)."""
    return run_async(TTS.speech(text))


def _send_file(path):
    from flask import send_file

    return send_file(str(path), mimetype="audio/mpeg")


# --------------------------------------------------------------------------- #
# Письмо и разговор (нужен ИИ)
# --------------------------------------------------------------------------- #
@bp.post("/writing")
def api_writing():
    user_id, error = require_user()
    if error:
        return error
    if not AI.enabled:
        return jsonify({"error": "ai_disabled"}), 503
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "no_text"}), 400

    user = db.get_user(user_id) or {}
    weak = [r["tag"] for r in db.query(
        "SELECT tag FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 6", (user_id,)
    )]
    result = _ai_call(
        AI.check_writing(text, user.get("level", "A1"), data.get("task") or "", weak)
    )
    if not result:
        return jsonify({"error": "ai_failed"}), 502

    new_words = result.get("new_words") or []
    pairs = [(w.get("sk", ""), w.get("ru", "")) for w in new_words if isinstance(w, dict)]
    if pairs:
        ids = add_words(user.get("level", "A1"), pairs, group="из приложения")
        enroll(user_id, ids)
    for error_item in result.get("errors") or []:
        tag = error_item.get("tag")
        if tag:
            db.execute(
                """INSERT INTO error_tags(user_id, tag, count, last_at) VALUES(?,?,1,?)
                   ON CONFLICT(user_id, tag) DO UPDATE SET count = count + 1, last_at = excluded.last_at""",
                (user_id, tag, db.now()),
            )
    db.execute(
        "INSERT INTO writing(user_id, prompt_id, text, feedback, created_at) VALUES(?,?,?,?,?)",
        (user_id, "app", text, "", db.now()),
    )
    add_stats(user_id, xp=8, tasks=1, correct=1 if not result.get("errors") else 0)
    result["new_words_added"] = len(pairs)
    return jsonify(result)


@bp.post("/speaking")
def api_speaking():
    user_id, error = require_user()
    if error:
        return error
    if not AI.enabled:
        return jsonify({"error": "ai_disabled"}), 503
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "no_text"}), 400
    user = db.get_user(user_id) or {}
    history = data.get("history") or []
    result = _ai_call(
        AI.dialogue_turn(history, text, user.get("level", "A1"), data.get("topic") or "")
    )
    if not result:
        return jsonify({"error": "ai_failed"}), 502
    return jsonify(result)


def _ai_call(coro):
    """Вызывает корутину ИИ из синхронного Flask-обработчика."""
    return run_async(coro)


def run_async(coro):
    """Выполняет корутину из синхронного кода.

    Если внутри уже есть event loop (async-сервер), выполняем в отдельном потоке.
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
