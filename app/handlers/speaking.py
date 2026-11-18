"""Говорение: диалог голосом + тренажёр произношения.

Диалог: ИИ говорит по-словацки, ты отвечаешь голосом (бот распознаёт речь
локально, faster-whisper), ИИ отвечает, мягко поправляя ошибки.
Повтор: бот произносит фразу — ты повторяешь голосом, он сравнивает тексты.
"""

from __future__ import annotations

import difflib
import logging
import os
import tempfile
from typing import List

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Voice,
)

from app import content as content_mod
from app import db
from app.keyboards import back_to
from app.scoring import norm
from app.services.ai import AI
from app.services.stt import STT
from app.services.tts import TTS
from app.states import SpeakingFlow
from app.utils import add_stats, safe_edit, trim

log = logging.getLogger("speaking")
router = Router(name="speaking")

TOPICS = [
    ("👋 Знакомство", "знакомство, представление себя, откуда ты"),
    ("🛒 В магазине", "покупки, цены, что спрашивать"),
    ("☕ В кафе", "заказ еды и напитков"),
    ("🚌 Дорога и транспорт", "спросить дорогу, куда ехать, расписание"),
    ("🏫 Учёба и документы", "университет, заявление, документы"),
    ("💼 Работа", "рассказать о работе, спросить о вакансии"),
]

OPENERS = {
    "👋 Знакомство": ("Dobrý deň! Volám sa Slovenčina. A ty? Odkiaľ si?", "Здравствуйте! Меня зовут Словчина. А ты? Откуда ты?"),
    "🛒 В магазине": ("Vitajte v obchode! Čo si želáte kúpiť?", "Добро пожаловать в магазин! Что хотите купить?"),
    "☕ В кафе": ("Dobrý deň, čo si dáte?", "Добрый день, что будете заказывать?"),
    "🚌 Дорога и транспорт": ("Odkiaľ ideš? Kam chceš ísť?", "Откуда ты идёшь? Куда хочешь пойти?"),
    "🏫 Учёба и документы": ("Študuješ na univerzite? Aký odbor?", "Ты учишься в университете? На какой специальности?"),
    "💼 Работа": ("Čo robíš? Kde pracuješ?", "Кем ты работаешь? Где работаешь?"),
}


def _speaking_kb(extra: List[List[InlineKeyboardButton]] = None) -> InlineKeyboardMarkup:
    rows = extra or []
    rows.append([InlineKeyboardButton(text="🔁 Повторить фразу", callback_data="sp:repeat")])
    rows.append([InlineKeyboardButton(text="⏹️ Закончить", callback_data="sp:stop")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "nav:speaking")
async def cb_speaking_menu(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    rows = [[InlineKeyboardButton(text="%s" % label, callback_data="sp:topic:%d" % i)] for i, (label, _) in enumerate(TOPICS)]
    rows.append([InlineKeyboardButton(text="🔁 Повторить фразу", callback_data="sp:repeat")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    await safe_edit(
        cb.message,
        "🗣 <b>Говорить</b>\n\n"
        "Диалог на словацки голосом или текстом. ИИ отвечает, слушает и поправляет мягко.\n"
        "Твой уровень: %s. Отвечай голосом — так ближе к реальной речи."
        % ((db.get_user(cb.from_user.id) or {}).get("level", "A1")),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("sp:topic:"))
async def cb_speaking_topic(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    idx = int((cb.data or "").split(":")[-1])
    label, topic = TOPICS[idx]
    opener, translation = OPENERS.get(label, ("Dobrý deň! Čo sa máme?", "Здравствуйте! О чём поговорим?"))

    await state.set_state(SpeakingFlow.turn)
    await state.update_data(topic=topic, history=[], turns=0, corrections=0, opener=opener)

    path = await TTS.speech(opener)
    if path:
        await cb.message.answer_voice(FSInputFile(str(path)), caption="🗣 %s" % opener)
    await cb.message.answer(
        "<b>ИИ:</b> %s\n<i>%s</i>\n\nОтветь голосом или текстом." % (opener, translation),
        reply_markup=_speaking_kb(),
    )


@router.message(SpeakingFlow.turn)
async def msg_speaking_turn(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    history = list(data.get("history") or [])
    topic = data.get("topic") or ""

    transcript = ""
    if message.voice:
        transcript = await _transcribe_voice(message, bot)
        if not transcript:
            await message.answer(
                "Не разобрал речь 😕 Попробуй ещё раз или напиши текстом.\n"
                "Если это повторяется — проверь, что микрофон работает, и говори чётче.",
                reply_markup=_speaking_kb(),
            )
            return
    elif message.text:
        transcript = message.text
    else:
        return

    if not AI.enabled:
        await message.answer(
            "Для диалога нужен ИИ-ключ (AI_API_KEY в .env).\n"
            "Твой ответ: <code>%s</code>" % trim(transcript, 300),
            reply_markup=_speaking_kb(),
        )
        return

    await message.answer("Слушаю… ⏳")
    user = db.get_user(message.from_user.id) or {}
    reply = await AI.dialogue_turn(history, transcript, user.get("level", "A1"), topic)
    if not reply:
        await message.answer("ИИ не ответил. Попробуй ещё раз.", reply_markup=_speaking_kb())
        return

    history = history + [{"role": "user", "content": transcript}, {"role": "assistant", "content": reply.get("reply", "")}]
    corrections = int(data.get("corrections") or 0)
    if reply.get("correction"):
        corrections += 1

    await state.update_data(history=history, turns=int(data.get("turns") or 0) + 1, corrections=corrections)

    lines = []
    if message.voice:
        lines.append("🎤 <b>Ты сказал:</b> %s" % trim(transcript, 300))
    lines.append("<b>ИИ:</b> %s" % reply.get("reply", ""))
    if reply.get("translation"):
        lines.append("<i>%s</i>" % reply["translation"])
    if reply.get("correction"):
        lines.append("")
        lines.append("✏️ %s" % reply["correction"])
    if reply.get("hint"):
        lines.append("")
        lines.append("💡 %s" % reply["hint"])

    path = await TTS.speech(reply.get("reply", ""))
    if path:
        await message.answer_voice(FSInputFile(str(path)), caption="🗣 ИИ")
    await message.answer("\n".join(lines), reply_markup=_speaking_kb())


async def _transcribe_voice(message: Message, bot: Bot) -> str:
    """Скачивает голос и распознаёт речь (словацкий)."""
    voice: Voice = message.voice
    path = os.path.join(tempfile.gettempdir(), "sl_%d_%s.ogg" % (message.message_id, voice.file_id[-6:]))
    try:
        await bot.download(voice.file_id, destination=path)
    except Exception as exc:
        log.warning("не удалось скачать голос: %s", exc)
        return ""
    try:
        text, confidence = await STT.transcribe(path, language="sk")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return text


# --------------------------------------------------------------------------- #
# Повторение фразы
# --------------------------------------------------------------------------- #
def _practice_phrases() -> List[str]:
    out: List[str] = []
    for lesson in content_mod.CONTENT.lessons:
        rule = lesson.get("rule") or {}
        for example in rule.get("ex") or []:
            text = example.split(" - ")[0].strip()
            if 10 < len(text) < 90 and text not in out:
                out.append(text)
    return out


@router.callback_query(F.data == "sp:repeat")
async def cb_repeat_pick(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    phrases = _practice_phrases()
    if not phrases:
        await cb.message.answer("Фраз для повторения пока нет — пройди пару уроков.", reply_markup=back_to())
        return
    import random

    phrase = random.choice(phrases)
    await state.set_state(SpeakingFlow.repeat)
    await state.update_data(phrase=phrase)
    path = await TTS.speech(phrase)
    if path:
        await cb.message.answer_voice(FSInputFile(str(path)), caption="🔊 Повтори эту фразу голосом")
    await cb.message.answer(
        "🎤 <b>Повтори фразу голосом</b>\n\n<code>%s</code>\n\nСкажи её вслух — сравню, что услышал." % phrase,
        reply_markup=back_to("⬅️ В меню", "nav:menu"),
    )


@router.message(SpeakingFlow.repeat, F.voice)
async def msg_repeat_voice(message: Message, bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    phrase = data.get("phrase") or ""
    transcript = await _transcribe_voice(message, bot)
    if not transcript:
        await message.answer("Не разобрал речь 😕 Попробуй ещё раз.", reply_markup=back_to())
        return

    similarity = difflib.SequenceMatcher(None, norm(phrase), norm(transcript)).ratio()
    percent = int(round(similarity * 100))
    if percent >= 85:
        verdict = "🎯 Отлично! %d%% совпадения." % percent
    elif percent >= 60:
        verdict = "🟡 Похоже, но не то. %d%% совпадения." % percent
    else:
        verdict = "❌ Сильно отличается. %d%% совпадения." % percent

    lines = [
        verdict,
        "",
        "<b>Эталон:</b> <code>%s</code>" % phrase,
        "<b>Я услышал:</b> <code>%s</code>" % transcript,
    ]
    if AI.enabled:
        hint = await AI.chat(
            "Ученик повторял словацкую фразу и ошибся. Скажи по-русски, что он сказал не так "
            "и как надо (1-2 предложения).\n\nЭталон: %s\nЧто услышали: %s" % (phrase, transcript),
            model=AI.fast_model,
            max_tokens=300,
        )
        if hint and not hint.startswith("__error__"):
            lines.append("")
            lines.append("💡 %s" % trim(hint, 500))
    add_stats(message.from_user.id, xp=4 if percent >= 85 else 1, tasks=1, correct=1 if percent >= 85 else 0)
    await state.set_state(None)
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Ещё фраза", callback_data="sp:repeat")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )


@router.callback_query(F.data == "sp:stop")
async def cb_speaking_stop(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer("Стоп")
    data = await state.get_data()
    turns = int(data.get("turns") or 0)
    corrections = int(data.get("corrections") or 0)
    await state.set_state(None)
    await state.update_data(history=[], turns=0, corrections=0)
    await cb.message.answer(
        "🏁 Разговор окончен.\nРеплик: %d · исправлений: %d\n\nПродолжить: /speak" % (turns, corrections),
        reply_markup=back_to(),
    )


@router.message(Command("speak", "говорить"))
async def cmd_speak(message: Message, bot: Bot) -> None:
    await message.answer(
        "🗣 <b>Говорить</b>\n\nВыбери тему:", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="%s" % label, callback_data="sp:topic:%d" % i)] for i, (label, _) in enumerate(TOPICS)
            ]
            + [[InlineKeyboardButton(text="🔁 Повторить фразу", callback_data="sp:repeat")],
               [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")]]
        ),
    )
