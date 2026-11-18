"""Письмо: ученик пишет текст по-словацки — ИИ проверяет по чек-листу.

Источники заданий: твои письма из pisma/*.md (письмо в TUKE, письмо в UNIZA)
и генерация ИИ под текущую тему. Проверка возвращает исправленный текст,
список ошибок с тегами и новые слова — они сразу попадают в SRS.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import content as content_mod
from app import db
from app.keyboards import back_to
from app.services.ai import AI
from app.services.lexicon import add_words, enroll
from app.states import WritingFlow
from app.utils import add_stats, safe_edit, trim

log = logging.getLogger("writing")
router = Router(name="writing")


def _writing_menu_kb() -> InlineKeyboardMarkup:
    rows = []
    for prompt in content_mod.CONTENT.writing:
        rows.append(
            [InlineKeyboardButton(text="✉️ %s" % trim(prompt.get("title", prompt["id"]), 40), callback_data="wr:open:%s" % prompt["id"])]
        )
    rows.append([InlineKeyboardButton(text="✨ Новое письмо от ИИ", callback_data="wr:gen")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "nav:writing")
async def cb_writing_menu(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    history = db.query(
        "SELECT COUNT(*) AS n FROM writing WHERE user_id = ?", (cb.from_user.id,)
    )
    count = int(history[0]["n"]) if history else 0
    await safe_edit(
        cb.message,
        "✍️ <b>Письмо</b>\n\n"
        "Пишешь текст по-словацки — ИИ проверяет грамматику, показывает исправленный вариант\n"
        "и объясняет каждую ошибку. Новые слова из текста сразу попадают в твои карточки.\n\n"
        "Написано работ: %d · уровень: %s" % (count, user.get("level", "A1")),
        _writing_menu_kb(),
    )


@router.callback_query(F.data.startswith("wr:open:"))
async def cb_writing_open(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    prompt_id = (cb.data or "").split(":")[-1]
    prompt = content_mod.CONTENT.writing_prompt(prompt_id)
    if not prompt:
        await cb.message.answer("Задание не найдено.", reply_markup=back_to())
        return
    await state.set_state(WritingFlow.text)
    await state.update_data(prompt_id=prompt_id, prompt_title=prompt.get("title", ""), task=prompt.get("letter", ""))

    lines = ["✍️ <b>%s</b>" % prompt.get("title", prompt_id), ""]
    if prompt.get("recipient"):
        lines.append("Кому: %s" % prompt["recipient"])
    if prompt.get("subject"):
        lines.append("Тема: %s" % prompt["subject"])
    lines.append("")
    lines.append("<b>Задание</b>")
    lines.append("Напиши письмо по-словацки по этому образцу. Своими словами, но по-словацки.")
    lines.append("")
    lines.append("<b>Образец</b>")
    lines.append(trim(prompt.get("letter", ""), 2500))
    if prompt.get("translation"):
        lines.append("")
        lines.append("<i>Перевод образца — нажми, чтобы посмотреть</i>")
    await cb.message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👁 Перевод образца", callback_data="wr:trans:%s" % prompt_id)],
                [InlineKeyboardButton(text="⬅️ К письмам", callback_data="nav:writing")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("wr:trans:"))
async def cb_writing_translation(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    prompt_id = (cb.data or "").split(":")[-1]
    prompt = content_mod.CONTENT.writing_prompt(prompt_id)
    if not prompt or not prompt.get("translation"):
        await cb.message.answer("Перевода нет.", reply_markup=back_to())
        return
    await cb.message.answer(
        "👁 <b>Перевод образца</b>\n\n%s" % trim(prompt.get("translation", ""), 2500),
        reply_markup=back_to(),
    )


@router.callback_query(F.data == "wr:gen")
async def cb_writing_gen(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer("Готовлю тему…")
    user = db.get_user(cb.from_user.id) or {}
    if not AI.enabled:
        await cb.message.answer(
            "Для генерации писем нужен ИИ-ключ (AI_API_KEY в .env).\n"
            "Пока доступны твои письма из pisma/.",
            reply_markup=_writing_menu_kb(),
        )
        return
    level = user.get("level", "A1")
    topics = [
        "Письмо в университет: запрос информации о поступлении",
        "Письмо в общежитие: вопрос о заселении",
        "Письмо работодателю: отклик на вакансию",
        "Письмо врачу: жалоба на самочувствие",
    ]
    import random

    topic = random.choice(topics)
    await state.set_state(WritingFlow.text)
    await state.update_data(prompt_id="generated", prompt_title=topic, task=topic)
    await cb.message.answer(
        "✍️ <b>%s</b>\n\nНапиши письмо на словацком (8–15 предложений). Проверю по правилам и по твоим слабым местам."
        % topic,
        reply_markup=back_to("⬅️ К письмам", "nav:writing"),
    )


@router.message(WritingFlow.text, F.text)
async def msg_writing_text(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    text = message.text
    user = db.get_user(message.from_user.id) or {}
    level = user.get("level", "A1")
    task = data.get("task") or ""

    if not AI.enabled:
        await message.answer(
            "Проверка текста требует ИИ-ключа (AI_API_KEY в .env).\n"
            "Текст сохранён — как только ключ появится, пришли его ещё раз.",
            reply_markup=back_to(),
        )
        return

    await message.answer("Проверяю… ⏳")

    weak_rows = db.query(
        "SELECT tag, count FROM error_tags WHERE user_id = ? ORDER BY count DESC LIMIT 6", (message.from_user.id,)
    )
    weak_tags = [r["tag"] for r in weak_rows]

    feedback = await AI.check_writing(text, level, task, weak_tags)
    if not feedback:
        await message.answer("ИИ не ответил. Попробуй ещё раз чуть позже.", reply_markup=back_to())
        return

    await state.set_state(None)

    errors = feedback.get("errors") or []
    lines = []
    score = feedback.get("score")
    if score is not None:
        lines.append("📝 <b>Оценка: %s/100</b>" % score)
    if feedback.get("comment"):
        lines.append(feedback["comment"])
    if errors:
        lines.append("")
        lines.append("<b>Ошибки (%d)</b>" % len(errors))
        for error in errors[:10]:
            wrong = error.get("wrong", "")
            right = error.get("right", "")
            rule = error.get("rule", "")
            lines.append("• <code>%s</code> → <b>%s</b>" % (trim(wrong, 80), trim(right, 80)))
            if rule:
                lines.append("   <i>%s</i>" % trim(rule, 220))
    if feedback.get("corrected"):
        lines.append("")
        lines.append("<b>Исправленный вариант</b>")
        lines.append(trim(feedback.get("corrected"), 1500))
    if feedback.get("next_task"):
        lines.append("")
        lines.append("➡️ <b>Дальше:</b> %s" % trim(feedback.get("next_task"), 300))

    new_words = feedback.get("new_words") or []
    if new_words:
        pairs = [(w.get("sk", ""), w.get("ru", "")) for w in new_words if isinstance(w, dict)]
        ids = add_words(level, pairs, group="из письма")
        added = enroll(message.from_user.id, ids)
        lines.append("")
        lines.append("📚 Новых слов в карточки: %d" % added)
        for sk, ru in pairs[:8]:
            lines.append("• %s — %s" % (sk, ru))

    # теги ошибок -> блок «мои ошибки»
    for error in errors:
        tag = error.get("tag")
        if tag:
            db.execute(
                """INSERT INTO error_tags(user_id, tag, count, last_at) VALUES(?,?,1,?)
                   ON CONFLICT(user_id, tag) DO UPDATE SET count = count + 1, last_at = excluded.last_at""",
                (message.from_user.id, tag, db.now()),
            )

    db.execute(
        "INSERT INTO writing(user_id, prompt_id, text, feedback, created_at) VALUES(?,?,?,?,?)",
        (
            message.from_user.id,
            data.get("prompt_id", ""),
            text,
            lines[0] if lines else "",
            db.now(),
        ),
    )
    add_stats(message.from_user.id, xp=8, tasks=1, correct=1 if not errors else 0)

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Ещё текст", callback_data="nav:writing")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


@router.message(Command("write", "письмо"))
async def cmd_write(message: Message, bot: Bot) -> None:
    await message.answer(
        "✍️ <b>Письмо</b>\n\nВыбери задание:", reply_markup=_writing_menu_kb()
    )
