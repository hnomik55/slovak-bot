"""Мини-тест: смесь заданий из пройденных уроков + свежие вопросы от ИИ."""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import content as content_mod
from app import db
from app.keyboards import back_to
from app.services.ai import AI
from app.trainer import Trainer

log = logging.getLogger("quiz")
router = Router(name="quiz")

QUIZ_SIZE = 10


def _ai_task(question: Dict[str, Any], index: int) -> Dict[str, Any]:
    options = list(question.get("o") or [])
    answer = question.get("a", 0)
    if isinstance(answer, str):
        answer = options.index(answer) if answer in options else 0
    return {
        "kind": "choice",
        "prompt": question.get("q", ""),
        "options": options,
        "answer": int(answer),
        "shuffle": True,
        "explain": question.get("x"),
        "i": index,
        "source": "ai",
    }


@router.callback_query(F.data == "nav:quiz")
async def cb_quiz(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    await cb.message.answer("Собираю тест… ⏳")

    user = db.get_user(cb.from_user.id) or {}
    level = user.get("level", "A1")

    # 1) задания из пройденных уроков
    done_rows = db.query(
        "SELECT lesson_id FROM lesson_progress WHERE user_id = ? AND done = 1", (cb.from_user.id,)
    )
    pool: List[Dict[str, Any]] = []
    for row in done_rows:
        lesson = content_mod.CONTENT.lesson(row["lesson_id"])
        if not lesson:
            continue
        pool.extend(t for t in (lesson.get("tasks") or []) if t.get("kind") in ("choice", "type"))

    # Если уроков ещё нет — берём первые уроки курса, чтобы тест был доступен сразу
    if not pool:
        for lesson in content_mod.CONTENT.lessons[:3]:
            pool.extend(t for t in (lesson.get("tasks") or []) if t.get("kind") in ("choice", "type"))
    random.shuffle(pool)

    tasks: List[Dict[str, Any]] = pool[:QUIZ_SIZE]
    if len(tasks) < QUIZ_SIZE and AI.enabled:
        weak_rows = db.query(
            "SELECT tag FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 5", (cb.from_user.id,)
        )
        questions = await AI.quiz_questions(level, [r["tag"] for r in weak_rows], QUIZ_SIZE - len(tasks))
        for i, question in enumerate(questions):
            task = _ai_task(question, i)
            task["lesson"] = "test"
            tasks.append(task)

    if not tasks:
        await cb.message.answer(
            "Тест собирается из пройденных уроков — пройди хотя бы один.\n"
            "Потом тест будет учитывать твои слабые места.",
            reply_markup=back_to(),
        )
        return

    trainer = Trainer(state, cb.from_user.id, bot)
    await trainer.start(cb.message, tasks, "test", "Мини-тест", mode="quiz")


@router.message(Command("quiz", "тест"))
async def cmd_quiz(message: Message, bot: Bot) -> None:
    await message.answer(
        "📝 <b>Мини-тест</b>\n\nСоберётся из твоих пройденных уроков + твои слабые места.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Начать тест", callback_data="nav:quiz")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )
