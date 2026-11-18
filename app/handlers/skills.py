"""Аудирование и чтение.

Аудирование: бот озвучивает словацкую фразу (TTS) и ждёт, что ты напишешь
её по памяти. Оценка — с толерантностью к опечаткам, как в тренажёре.
Чтение: короткий текст уровня с переводом и вопросом на понимание.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import content as content_mod
from app import db
from app.keyboards import back_to
from app.scoring import RESULT_ACCENTS, RESULT_OK, RESULT_TYPO, grade_text, result_text
from app.services.ai import AI
from app.services.tts import TTS
from app.utils import add_stats, safe_answer, safe_edit, trim

log = logging.getLogger("skills")
router = Router(name="skills")


class SkillFlow(StatesGroup):
    listen = State()
    read_quiz = State()


# --------------------------------------------------------------------------- #
# Аудирование
# --------------------------------------------------------------------------- #
def _example_sentences(limit: int = 20) -> List[str]:
    """Примеры из правил уроков: реальные словацкие фразы, уже в твоём контенте."""
    out: List[str] = []
    for lesson in content_mod.CONTENT.lessons:
        rule = lesson.get("rule") or {}
        for example in rule.get("ex") or []:
            text = example.split(" - ")[0].strip()
            if 8 < len(text) < 120 and text not in out:
                out.append(text)
    return out[:limit]


@router.callback_query(F.data == "nav:listening")
async def cb_listening_menu(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    rows = [
        [InlineKeyboardButton(text="🎧 Слово за словом", callback_data="sk:listen:1")],
        [InlineKeyboardButton(text="🗣 Мини-диалог", callback_data="sk:listen:2")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ]
    await safe_edit(
        cb.message,
        "🎧 <b>Аудирование</b> (уровень %s)\n\n"
        "Я озвучу словацкую фразу — напиши, что услышал. Оценим по смыслу: опечатка простит,\n"
        "а потерянная диакритика — нет, её надо возвращать в текст.\n\n"
        "Методичка: %s"
        % (user.get("level", "A1"), "navyky/3-listening.txt"),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("sk:listen:"))
async def cb_listen_start(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    mode = (cb.data or "").split(":")[-1]
    user = db.get_user(cb.from_user.id) or {}
    level = user.get("level", "A1")

    sentence = ""
    if mode == "2":
        sentences = await AI.listening_sentences(level, "бытовая ситуация", 4)
        sentence = sentences[0] if sentences else ""
    if not sentence:
        pool = _example_sentences()
        if not pool:
            await cb.message.answer("Нет материала для аудирования. Пройди пару уроков.", reply_markup=back_to())
            return
        import random

        sentence = random.choice(pool)

    await state.set_state(SkillFlow.listen)
    await state.update_data(source=sentence, mode=mode)

    path = await TTS.speech(sentence)
    text = "🎧 <b>Послушай и напиши, что услышал</b>\n\n"
    if path:
        await cb.message.answer_voice(
            FSInputFile(str(path)),
            caption="🔊 Словацкий текст",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✍️ Написать ответ", callback_data="sk:listen:again")],
                    [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
                ]
            ),
        )
    await cb.message.answer(
        text + "Пришли ответ текстом — проверю.", reply_markup=back_to("⬅️ В меню", "nav:menu")
    )


@router.callback_query(F.data == "sk:listen:again")
async def cb_listen_again(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    source = data.get("source") or ""
    path = await TTS.speech(source)
    if path:
        await cb.message.answer_voice(FSInputFile(str(path)), caption="🔊 %s" % source)


@router.message(SkillFlow.listen, F.text)
async def msg_listen_answer(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    source = data.get("source") or ""
    result, expected = grade_text(message.text, [source])
    if result == RESULT_OK:
        verdict = "✅ Услышал идеально."
    elif result in (RESULT_TYPO, RESULT_ACCENTS):
        verdict = "🟡 %s" % result_text(result)
    else:
        verdict = "❌ Не то, что я произнёс."

    lines = [verdict, "", "<b>Оригинал:</b> <code>%s</code>" % source]
    if expected and result != RESULT_OK:
        lines.append("<b>Твой ответ:</b> <code>%s</code>" % trim(message.text, 200))

    # Перевод и разбор — только если ИИ доступен
    if AI.enabled:
        translation = await AI.chat(
            "Переведи на русский и объясни коротко, что здесь трудного для русскоязычного. "
            "Одна-две фразы.\n\nФраза: %s" % source,
            model=AI.fast_model,
            max_tokens=300,
        )
        if translation and not translation.startswith("__error__"):
            lines.append("")
            lines.append("💡 %s" % trim(translation, 600))

    add_stats(message.from_user.id, xp=3 if result == RESULT_OK else 1, tasks=1, correct=1 if result == RESULT_OK else 0)
    await state.set_state(None)
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Ещё фраза", callback_data="sk:listen:1")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


# --------------------------------------------------------------------------- #
# Чтение
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "nav:reading")
async def cb_reading_menu(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    level = user.get("level", "A1")
    if not AI.enabled:
        await cb.message.answer(
            "📖 <b>Чтение</b>\n\n"
            "Для чтения нужен ИИ-ключ (AI_API_KEY в .env) — он готовит текст под твой уровень.\n"
            "Пока почитай конспекты уроков: /lesson или папка уроков.\n\n"
            "Что почитать самому:\n"
            "• slovake.eu — курс с аудио и переводом\n"
            "• sk.wikipedia.org — статьи на знакомые темы\n"
            "• spravy.stvr.sk — новости (с января, уровень B1)",
            reply_markup=back_to(),
        )
        return
    await cb.message.answer("Готовлю текст под твой уровень %s… ⏳" % level)
    material = await AI.reading_material(level, "")
    if not material:
        await cb.message.answer("Не получилось сгенерировать текст. Попробуй позже.", reply_markup=back_to())
        return
    await state.set_state(SkillFlow.read_quiz)
    await state.update_data(material=material)
    text = "📖 <b>%s</b>\n\n%s" % (material.get("title", ""), material.get("text", ""))
    await cb.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👁 Показать перевод", callback_data="sk:read:trans")],
                [InlineKeyboardButton(text="➡️ Вопросы", callback_data="sk:read:quiz")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


@router.callback_query(F.data == "sk:read:trans")
async def cb_read_translation(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    material = data.get("material") or {}
    translation = material.get("translation") or ""
    words = material.get("new_words") or []
    lines = ["👁 <b>Перевод</b>", translation] if translation else ["Перевода нет."]
    if words:
        lines.append("")
        lines.append("<b>Новые слова:</b>")
        for word in words[:8]:
            if isinstance(word, dict):
                lines.append("• %s — %s" % (word.get("sk", ""), word.get("ru", "")))
    await cb.message.answer("\n".join(lines), reply_markup=back_to())


@router.callback_query(F.data == "sk:read:quiz")
async def cb_read_quiz(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    material = data.get("material") or {}
    questions = material.get("questions") or []
    if not questions:
        await cb.message.answer("Вопросов к тексту нет.", reply_markup=back_to())
        return
    await state.update_data(quiz_idx=0, quiz_correct=0)
    await _ask_question(cb.message, questions, 0)


async def _ask_question(message: Message, questions: List[Dict[str, Any]], idx: int) -> None:
    q = questions[idx]
    options = list(q.get("o") or [])
    correct = int(q.get("a") or 0)
    import random

    order = list(range(len(options)))
    random.shuffle(order)
    rows = [
        [InlineKeyboardButton(text=options[i], callback_data="sk:ans:%d:%d" % (idx, i))]
        for i in order
    ]
    await message.answer(
        "❓ <b>%s</b>" % q.get("q", ""), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


@router.callback_query(F.data.startswith("sk:ans:"))
async def cb_read_answer(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    idx = int(parts[2])
    option = int(parts[3])
    data = await state.get_data()
    material = data.get("material") or {}
    questions = material.get("questions") or []
    if idx >= len(questions):
        return
    q = questions[idx]
    correct = int(q.get("a") or 0)
    ok = option == correct
    data["quiz_correct"] = int(data.get("quiz_correct") or 0) + (1 if ok else 0)
    await state.update_data(quiz_correct=data["quiz_correct"])

    options = list(q.get("o") or [])
    lines = ["✅ Верно" if ok else "❌ Неверно"]
    lines.append("Правильный ответ: <b>%s</b>" % (options[correct] if correct < len(options) else ""))
    if q.get("x"):
        lines.append("💡 %s" % q["x"])
    add_stats(cb.from_user.id, xp=2 if ok else 0, tasks=1, correct=1 if ok else 0)
    await safe_answer(cb, "\n".join(lines))
    if idx + 1 < len(questions):
        await _ask_question(cb.message, questions, idx + 1)
    else:
        score = data["quiz_correct"]
        await state.set_state(None)
        await cb.message.answer(
            "🏁 Вопросы к тексту: <b>%d/%d</b>" % (score, len(questions)),
            reply_markup=back_to(),
        )


@router.message(Command("listen", "аудирование"))
async def cmd_listen(message: Message, bot: Bot) -> None:
    await message.answer(
        "🎧 <b>Аудирование</b>\n\nСкоро: озвучка и проверка на слух.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎧 Начать", callback_data="sk:listen:1")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )
