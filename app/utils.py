"""Мелкие помощники: безопасное редактирование, форматирование, счётчики."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import db
from app.scoring import RESULT_ACCENTS, RESULT_BAD, RESULT_OK, RESULT_TYPO

XP_PER_TASK = 2
XP_LESSON = 10
XP_PERFECT = 5


async def safe_edit(message: Message, text: str, kb: Optional[InlineKeyboardMarkup] = None, **kwargs) -> None:
    """Редактирует сообщение, молча переживая «message is not modified»."""
    try:
        if kb is None:
            await message.edit_text(text, **kwargs)
        else:
            await message.edit_text(text, reply_markup=kb, **kwargs)
    except TelegramBadRequest:
        pass


async def safe_answer(
    callback: CallbackQuery, text: Optional[str] = None, kb: Optional[InlineKeyboardMarkup] = None, **kwargs
) -> None:
    try:
        if text is None:
            await callback.message.edit_reply_markup(reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb, **kwargs)
    except TelegramBadRequest:
        pass


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русские склонения: 1 задание, 2 задания, 5 заданий."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def progress_bar(done: int, total: int, width: int = 12) -> str:
    if total <= 0:
        return "░" * width
    filled = int(width * done / total)
    return "█" * filled + "░" * (width - filled)


def shuffle(items: Sequence[Any]) -> List[Any]:
    out = list(items)
    random.shuffle(out)
    return out


def trim(text: str, limit: int = 3500) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def score_label(result: str) -> str:
    return {
        RESULT_OK: "✅ Верно",
        RESULT_TYPO: "🟡 Почти (опечатка)",
        RESULT_ACCENTS: "🟡 Почти (диакритика)",
        RESULT_BAD: "❌ Неверно",
    }.get(result, result)


def result_is_ok(result: str) -> bool:
    return result == RESULT_OK


def add_stats(user_id: int, xp: int = 0, tasks: int = 0, correct: int = 0, minutes: int = 0) -> None:
    db.touch_day(user_id, xp=xp, tasks=tasks, correct=correct)
    if minutes:
        db.execute(
            """INSERT INTO daily_stats(user_id, day, minutes) VALUES(?,?,?)
               ON CONFLICT(user_id, day) DO UPDATE SET minutes = minutes + excluded.minutes""",
            (user_id, db.today(), minutes),
        )
    if xp:
        db.add_xp(user_id, xp)


def level_progress(user_id: int, lessons: List[Dict[str, Any]]) -> Dict[str, float]:
    """Доля пройденных уроков по юнитам: {unit_no: 0..1}."""
    from app import content as content_mod

    out: Dict[str, float] = {}
    buckets: Dict[Any, List[int]] = {}
    for lesson in lessons:
        unit = lesson.get("unit")
        buckets.setdefault(unit, [0, 0])
        buckets[unit][1] += 1
        if content_mod.lesson_done(user_id, lesson["id"]):
            buckets[unit][0] += 1
    for unit, (done, total) in buckets.items():
        out[str(unit)] = done / total if total else 0.0
    return out
