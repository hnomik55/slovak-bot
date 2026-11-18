"""Уроки: список юнитов, запуск урока, обработка ответов, тренировка ошибок."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import content as content_mod
from app import db
from app.keyboards import back_to, lessons_menu, units_menu
from app.states import LessonFlow
from app.trainer import Trainer
from app.utils import level_progress, safe_edit, trim

log = logging.getLogger("lessons")
router = Router(name="lessons")


def _trainer(cb: CallbackQuery, state: FSMContext, bot: Bot) -> Trainer:
    return Trainer(state, cb.from_user.id, bot)


# --------------------------------------------------------------------------- #
# Списки
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:lessons")
@router.callback_query(F.data == "nav:units")
async def cb_units(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    content_mod.CONTENT.load()
    lessons = content_mod.all_lessons(cb.from_user.id)
    if not lessons:
        await cb.message.answer(
            "Контент не собран. Запусти: python tools/build_content.py",
            reply_markup=back_to(),
        )
        return
    progress = level_progress(cb.from_user.id, lessons)
    stats = content_mod.CONTENT.stats()
    await safe_edit(
        cb.message,
        "📚 <b>Уроки</b>\n\nПройдено: %d из %d · заданий в контенте: %d\n"
        "Открыт следующий урок, если предыдущий сдан на 80%%.\n\n"
        "Генератор: %s"
        % (
            content_mod.completed_count(cb.from_user.id),
            len(lessons),
            stats["tasks"],
            stats["built_at"][:16].replace("T", " "),
        ),
        reply_markup=units_menu(content_mod.CONTENT.units, progress),
    )


@router.callback_query(F.data.startswith("nav:unit:"))
async def cb_unit(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    unit_no = int((cb.data or "").split(":")[-1])
    lessons = content_mod.all_lessons(cb.from_user.id)
    unit_lessons = [l for l in lessons if str(l.get("unit")) == str(unit_no)]
    if not unit_lessons:
        await cb.message.answer("В этом юните пока нет уроков.", reply_markup=back_to("⬅️ К юнитам", "nav:units"))
        return

    states: Dict[str, str] = {}
    for lesson in unit_lessons:
        lid = lesson["id"]
        if content_mod.lesson_done(cb.from_user.id, lid):
            states[lid] = "done"
        elif content_mod.is_unlocked(cb.from_user.id, lid, lessons):
            states[lid] = "open"
        else:
            states[lid] = "locked"

    unit = next((u for u in content_mod.CONTENT.units if str(u.get("n")) == str(unit_no)), None)
    title = unit.get("title", "") if unit else ""
    desc = unit.get("desc", "") if unit else ""
    header = "🧩 <b>Юнит %s. %s</b>" % (unit_no, title)
    if desc:
        header += "\n<i>%s</i>" % trim(desc, 200)
    await safe_edit(cb.message, header, reply_markup=lessons_menu(unit_no, unit_lessons, states))


# --------------------------------------------------------------------------- #
# Карточка урока
# --------------------------------------------------------------------------- #
def _lesson_card(lesson: Dict[str, Any]) -> str:
    lines = ["📘 <b>%s</b>" % (lesson.get("title") or lesson.get("id"))]
    sub = lesson.get("sub")
    if sub:
        lines.append("<i>%s</i>" % sub)
    unit = content_mod.CONTENT.unit_of(lesson["id"])
    if unit:
        lines.append("Юнит %s · %s" % (unit.get("n"), unit.get("title", "")))
    lines.append("Заданий: %d" % len(lesson.get("tasks") or []))

    rule = lesson.get("rule")
    if rule:
        lines.append("")
        lines.append("<b>%s</b>" % rule.get("title", "Правило"))
        for paragraph in rule.get("p") or []:
            lines.append(paragraph)
        rows = rule.get("rows") or []
        if rows:
            lines.append("")
            for row in rows:
                lines.append(" | ".join(str(c) for c in row))
        examples = rule.get("ex") or []
        if examples:
            lines.append("")
            for example in examples:
                lines.append("• %s" % example)
    return "\n".join(lines)


@router.callback_query(F.data.startswith("nav:lesson:"))
async def cb_lesson(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    lesson_id = (cb.data or "").split(":")[-1]
    lessons = content_mod.all_lessons(cb.from_user.id)
    lesson = next((l for l in lessons if l["id"] == lesson_id), None)
    if not lesson:
        await cb.message.answer("Урок не найден. Обнови контент: /admin_reload", reply_markup=back_to())
        return
    if not content_mod.is_unlocked(cb.from_user.id, lesson_id, lessons):
        await cb.message.answer(
            "🔒 Этот урок пока закрыт. Сдай предыдущий на 80%% — и он откроется.",
            reply_markup=back_to(),
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать урок", callback_data="nav:start:%s" % lesson_id)],
            [InlineKeyboardButton(text="⬅️ К урокам", callback_data="nav:units")],
        ]
    )
    await safe_edit(cb.message, _lesson_card(lesson), kb)


@router.callback_query(F.data.startswith("nav:start:"))
async def cb_start_lesson(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    lesson_id = (cb.data or "").split(":")[-1]
    lesson = content_mod.CONTENT.lesson(lesson_id) or next(
        (l for l in content_mod.all_lessons(cb.from_user.id) if l["id"] == lesson_id), None
    )
    if not lesson:
        await cb.message.answer("Урок не найден.", reply_markup=back_to())
        return
    tasks = lesson.get("tasks") or []
    if not tasks:
        await cb.message.answer("В уроке нет заданий.", reply_markup=back_to())
        return
    trainer = Trainer(state, cb.from_user.id, bot)
    await trainer.start(cb.message, tasks, lesson_id, lesson.get("title") or lesson_id, mode="lesson")


@router.callback_query(F.data == "nav:next_lesson")
async def cb_next_lesson(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    lesson = content_mod.next_lesson(cb.from_user.id)
    if not lesson:
        await cb.message.answer(
            "Базовые уроки пройдены 🎉 Можно потренировать ошибки или взять мини-тест.",
            reply_markup=back_to(),
        )
        return
    tasks = lesson.get("tasks") or []
    trainer = Trainer(state, cb.from_user.id, bot)
    await trainer.start(cb.message, tasks, lesson["id"], lesson.get("title") or lesson["id"], mode="lesson")


@router.message(Command("lesson", "урок"))
async def cmd_lesson(message: Message, bot: Bot, state: FSMContext) -> None:
    lesson = content_mod.next_lesson(message.from_user.id)
    if not lesson:
        await message.answer("Все уроки пройдены — попробуй мини-тест или потренируй ошибки.")
        return
    tasks = lesson.get("tasks") or []
    trainer = Trainer(state, message.from_user.id, bot)
    await trainer.start(message, tasks, lesson["id"], lesson.get("title") or lesson["id"], mode="lesson")


# --------------------------------------------------------------------------- #
# Тренировка ошибок
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:drill")
async def cb_drill(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    rows = db.query(
        """SELECT lesson_id, task_i, COUNT(*) AS n FROM attempts
           WHERE user_id = ? AND result != 'ok' AND lesson_id != ''
           GROUP BY lesson_id, task_i
           ORDER BY n DESC LIMIT 25""",
        (cb.from_user.id,),
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
        task = next((t for t in lesson.get("tasks") or [] if t.get("i") == row["task_i"]), None)
        if task:
            tasks.append(task)
    if not tasks:
        await cb.message.answer(
            "Ошибок пока нет — или ты их ещё не накопил.\n"
            "Ошибки появятся здесь автоматически после первых заданий.",
            reply_markup=back_to(),
        )
        return
    trainer = Trainer(state, cb.from_user.id, bot)
    await trainer.start(cb.message, tasks[:15], "drill", "Тренировка ошибок", mode="drill")


# --------------------------------------------------------------------------- #
# Ответы тренажёра
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("tk:choice:"))
async def cb_choice(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    idx = int(parts[2])
    option = int(parts[3])
    data = await state.get_data()
    if int(data.get("idx") or 0) != idx:
        return await cb.answer("Это задание уже закрыто", show_alert=True)
    await _trainer(cb, state, bot).on_choice(cb, option)


@router.callback_query(F.data.startswith("tk:key:"))
async def cb_key(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    idx = int(parts[2])
    char = parts[3] if len(parts) > 3 else ""
    data = await state.get_data()
    if int(data.get("idx") or 0) != idx:
        return await cb.answer("Это задание уже закрыто", show_alert=True)
    await _trainer(cb, state, bot).on_key(cb, char)


@router.callback_query(F.data.startswith("tk:typecheck:"))
async def cb_typecheck(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    buf = (data.get("buf") or "").strip()
    if not buf:
        return await cb.answer("Сначала набери ответ", show_alert=True)
    trainer = _trainer(cb, state, bot)
    await trainer.check_type(cb.message, buf)


@router.callback_query(F.data.startswith("tk:typeclear:"))
async def cb_typeclear(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await _trainer(cb, state, bot).on_type_clear(cb)


@router.callback_query(F.data.startswith("tk:build:"))
async def cb_build(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    idx = int(parts[2])
    data = await state.get_data()
    if int(data.get("idx") or 0) != idx:
        return await cb.answer("Это задание уже закрыто", show_alert=True)
    trainer = _trainer(cb, state, bot)
    if len(parts) > 3 and parts[3] == "check":
        await trainer.on_build_check(cb)
    elif len(parts) > 3 and parts[3] == "clear":
        await trainer.on_build_clear(cb)
    else:
        await trainer.on_build_word(cb, int(parts[3]))


@router.callback_query(F.data.startswith("tk:match:"))
async def cb_match(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    task_idx = int(parts[2])
    pair_index = int(parts[3])
    option_index = int(parts[4])
    data = await state.get_data()
    if int(data.get("idx") or 0) != task_idx:
        return await cb.answer("Это задание уже закрыто", show_alert=True)
    await _trainer(cb, state, bot).on_match_option(cb, pair_index, option_index)


@router.callback_query(F.data.startswith("tk:next:"))
async def cb_next(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await _trainer(cb, state, bot).on_next(cb)


@router.callback_query(F.data.startswith("tk:retry:"))
async def cb_retry(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await _trainer(cb, state, bot).on_retry(cb)


@router.callback_query(F.data.startswith("tk:why:"))
async def cb_why(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await _trainer(cb, state, bot).on_why(cb)


@router.callback_query(F.data.startswith("tk:speak:"))
async def cb_speak(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await _trainer(cb, state, bot).on_speak(cb)


@router.message(LessonFlow.task, F.text)
@router.message(LessonFlow.typing, F.text)
async def msg_type_answer(message: Message, bot: Bot, state: FSMContext) -> None:
    """Текстовый ответ на задание типа «напиши ответ».

    Работает и когда задание только показано (уже введённый текст), и после
    разбора — но второй раз одно и то же задание не переоценивается.
    """
    data = await state.get_data()
    queue = data.get("queue") or []
    idx = int(data.get("idx") or 0)
    task = queue[idx] if idx < len(queue) else None
    if not task or task.get("kind") != "type":
        return
    if data.get("answered"):
        return  # задание уже разобрано
    trainer = Trainer(state, message.from_user.id, bot)
    await trainer.on_type_text(message, message.text)
