"""Прогресс и блок ошибок."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import content as content_mod
from app import db
from app.utils import level_progress, safe_edit, trim

log = logging.getLogger("progress")
router = Router(name="progress")

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
}


@router.callback_query(F.data == "nav:progress")
async def cb_progress(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    lessons = content_mod.all_lessons(cb.from_user.id)
    stats = content_mod.CONTENT.stats()

    done = content_mod.completed_count(cb.from_user.id)
    words_total = db.query_one(
        """SELECT COUNT(*) AS n FROM user_words uw JOIN vocab v ON v.id = uw.vocab_id
           WHERE uw.user_id = ? AND uw.state != 'new'""",
        (cb.from_user.id,),
    )
    words_learned = int(words_total["n"]) if words_total else 0
    words_due = db.query_one(
        "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?",
        (cb.from_user.id, db.today()),
    )
    due = int(words_due["n"]) if words_due else 0

    week = db.query(
        """SELECT day, xp, tasks, correct FROM daily_stats
           WHERE user_id = ? AND day >= date('now', '-7 day') ORDER BY day""",
        (cb.from_user.id,),
    )
    tasks_week = sum(r["tasks"] or 0 for r in week)
    correct_week = sum(r["correct"] or 0 for r in week)
    accuracy = int(round(100 * correct_week / tasks_week)) if tasks_week else 0

    progress = level_progress(cb.from_user.id, lessons)
    units = content_mod.CONTENT.units

    lines = [
        "📊 <b>Прогресс</b>",
        "",
        "⭐ XP: <b>%d</b> · 🔥 серия: <b>%s</b> (рекорд %s)"
        % (user.get("xp", 0), user.get("streak", 0), user.get("best_streak", 0)),
        "📘 Уроки: <b>%d/%d</b> · уровень: <b>%s</b>" % (done, len(lessons), user.get("level", "A1")),
        "🔤 Слов выучено: <b>%d</b> · к повторению: <b>%d</b>" % (words_learned, due),
        "🎯 Точность за 7 дней: <b>%d%%</b> (%d заданий)" % (accuracy, tasks_week),
    ]

    if progress:
        lines.append("")
        lines.append("<b>Юниты</b>")
        for unit in units:
            value = progress.get(str(unit.get("n")), 0.0)
            bar = "█" * int(round(value * 8)) + "░" * (8 - int(round(value * 8)))
            lines.append("%s %s — %s" % (bar, unit.get("n"), unit.get("title", "")))

    next_lesson = content_mod.next_lesson(cb.from_user.id)
    if next_lesson:
        lines.append("")
        lines.append("➡️ Следующий: <b>%s</b>" % next_lesson.get("title", next_lesson["id"]))

    lines.append("")
    lines.append("<i>Контент: %d уроков, %d заданий, %d слов (собрано %s)</i>" % (
        stats["lessons"], stats["tasks"], stats["vocab"], stats["built_at"][:10]
    ))

    await safe_edit(
        cb.message,
        "\n".join(lines),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Продолжить урок", callback_data="nav:next_lesson")],
                [
                    InlineKeyboardButton(text="⚠️ Мои ошибки", callback_data="nav:errors"),
                    InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu"),
                ],
            ]
        ),
    )


@router.callback_query(F.data == "nav:errors")
async def cb_errors(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    rows = db.query(
        "SELECT tag, count, last_at FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 12",
        (cb.from_user.id,),
    )
    lines = ["⚠️ <b>Мои ошибки</b>", ""]
    if not rows:
        lines.append("Пока чисто. Ошибки появятся здесь автоматически — и я буду предлагать их тренировать.")
    else:
        lines.append("Твои типовые ошибки (частота):")
        for row in rows:
            tag = row["tag"]
            lines.append("• %s — <b>%d</b> раз(а)" % (TAG_RU.get(tag, tag), row["count"]))
        lines.append("")
        lines.append("Исправь их — и они перестанут повторяться. Кнопка ниже собирает конкретные задания, где ты ошибался.")

    recent = db.query(
        """SELECT lesson_id, task_i, given, expected, tag, created_at FROM attempts
           WHERE user_id = ? AND result != 'ok' ORDER BY id DESC LIMIT 6""",
        (cb.from_user.id,),
    )
    if recent:
        lines.append("")
        lines.append("<b>Последние ошибки</b>")
        for row in recent:
            lines.append("• <code>%s</code> → <b>%s</b> <i>(%s)</i>" % (
                trim(row.get("given", ""), 50) or "…",
                trim(row.get("expected", ""), 50),
                TAG_RU.get(row.get("tag") or "", row.get("tag") or ""),
            ))

    await safe_edit(
        cb.message,
        "\n".join(lines),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Тренировать ошибки", callback_data="nav:drill")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


@router.message(Command("progress", "прогресс", "статистика"))
async def cmd_progress(message: Message, bot: Bot) -> None:
    await message.answer(
        "📊 <b>Прогресс</b>\n\nОткрывай раздел «Прогресс» в меню.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Показать", callback_data="nav:progress")],
                [InlineKeyboardButton(text="⚠️ Ошибки", callback_data="nav:errors")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


@router.message(Command("errors", "ошибки"))
async def cmd_errors(message: Message, bot: Bot) -> None:
    await message.answer(
        "⚠️ <b>Мои ошибки</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Показать", callback_data="nav:errors")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )
