"""Словарь с интервальным повторением (SRS).

Слова берутся из твоих файлов slovar/slova-A1|A2|B1.txt — это те же 847 слов,
что и в тренажёре. Карточки живут в SQLite, повторение — по SM-2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import db
from app.keyboards import back_to
from app.services.tts import TTS
from app.srs import review
from app.utils import add_stats, safe_edit, trim

log = logging.getLogger("vocab")
router = Router(name="vocab")


class VocabFlow(StatesGroup):
    card = State()


NEW_PER_DAY = 10
REVIEW_BATCH = 20


def _due_words(user_id: int, limit: int = REVIEW_BATCH) -> List[Dict[str, Any]]:
    return db.query(
        """SELECT v.*, uw.ease, uw.interval, uw.reps, uw.lapses, uw.due, uw.state
           FROM user_words uw JOIN vocab v ON v.id = uw.vocab_id
           WHERE uw.user_id = ? AND uw.due <= ?
           ORDER BY uw.due ASC, uw.lapses DESC LIMIT ?""",
        (user_id, db.today(), limit),
    )


def _new_words(user_id: int, level: str, limit: int = NEW_PER_DAY) -> List[Dict[str, Any]]:
    return db.query(
        """SELECT v.* FROM vocab v
           WHERE v.level = ?
             AND v.id NOT IN (SELECT vocab_id FROM user_words WHERE user_id = ?)
           ORDER BY v.id LIMIT ?""",
        (level, user_id, limit),
    )


def _due_count(user_id: int) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?",
        (user_id, db.today()),
    )
    return int(row["n"]) if row else 0


def _new_count(user_id: int, level: str) -> int:
    row = db.query_one(
        """SELECT COUNT(*) AS n FROM vocab v WHERE v.level = ?
           AND v.id NOT IN (SELECT vocab_id FROM user_words WHERE user_id = ?)""",
        (level, user_id),
    )
    return int(row["n"]) if row else 0


def _card_text(word: Dict[str, Any], revealed: bool) -> str:
    lines = ["🔤 <b>%s</b>" % word["sk"]]
    if revealed:
        lines.append("")
        lines.append("<b>%s</b>" % word["ru"])
        alts = word.get("ru_alts")
        if alts:
            try:
                import json

                extra = json.loads(alts)
                if extra and len(extra) > 1:
                    lines.append("<i>%s</i>" % ", ".join(extra))
            except Exception:
                pass
    else:
        lines.append("\n<i>Переведи и нажми «Показать перевод»</i>")
    return "\n".join(lines)


def _card_kb(idx: int, revealed: bool, with_speak: bool = True) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    if with_speak:
        rows.append([InlineKeyboardButton(text="🔊 Послушать", callback_data="vc:speak:%d" % idx)])
    if not revealed:
        rows.append([InlineKeyboardButton(text="👁 Показать перевод", callback_data="vc:reveal:%d" % idx)])
    else:
        rows.append(
            [
                InlineKeyboardButton(text="😵 Не знаю", callback_data="vc:rate:0:%d" % idx),
                InlineKeyboardButton(text="🤔 С трудом", callback_data="vc:rate:1:%d" % idx),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="🙂 Нормально", callback_data="vc:rate:2:%d" % idx),
                InlineKeyboardButton(text="😃 Легко", callback_data="vc:rate:3:%d" % idx),
            ]
        )
    rows.append([InlineKeyboardButton(text="⏹️ Стоп", callback_data="vc:stop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "nav:vocab")
async def cb_vocab_menu(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    level = user.get("level", "A1")
    due = _due_count(cb.from_user.id)
    new = _new_count(cb.from_user.id, level)
    rows = [
        [InlineKeyboardButton(text="🔁 Повторение — %d" % due, callback_data="vc:mode:due")],
        [InlineKeyboardButton(text="🆕 Новые слова (%s) — %d" % (level, new), callback_data="vc:mode:new")],
        [InlineKeyboardButton(text="📤 Экспорт в Anki", callback_data="vc:export")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
    ]
    await safe_edit(
        cb.message,
        "🔤 <b>Слова</b>\n\nНа повторении: <b>%d</b> · новых для уровня %s: <b>%d</b>\n"
        "Повторение по методу SM-2: не знал — завтра, знал — через 3, 7, 16, 35 дней."
        % (due, level, new),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("vc:mode:"))
async def cb_vocab_mode(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    mode = (cb.data or "").split(":")[-1]
    user = db.get_user(cb.from_user.id) or {}
    if mode == "due":
        cards = _due_words(cb.from_user.id)
        title = "🔁 Повторение"
    else:
        cards = _new_words(cb.from_user.id, user.get("level", "A1"))
        title = "🆕 Новые слова"
    if not cards:
        await cb.message.answer(
            "Слов на этот заход нет. Новые слова появятся, когда доберёшься до следующего уровня.",
            reply_markup=back_to(),
        )
        return
    await state.set_state(VocabFlow.card)
    await state.update_data(cards=[c["id"] for c in cards], i=0, revealed=False, mode=mode, title=title)
    word = cards[0]
    await cb.message.answer(
        "%s\n\n%s" % (title, _card_text(word, False)),
        reply_markup=_card_kb(0, False),
    )


@router.callback_query(F.data.startswith("vc:reveal:"))
async def cb_reveal(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    ids = data.get("cards") or []
    i = int(data.get("i") or 0)
    if i >= len(ids):
        return
    row = db.query_one("SELECT * FROM vocab WHERE id = ?", (ids[i],))
    if not row:
        return
    data["revealed"] = True
    await state.update_data(revealed=True)
    await safe_edit(cb.message, _card_text(row, True), _card_kb(i, True))


@router.callback_query(F.data.startswith("vc:rate:"))
async def cb_rate(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    quality = int(parts[2])
    idx = int(parts[3])
    await cb.answer()
    data = await state.get_data()
    ids = data.get("cards") or []
    i = int(data.get("i") or 0)
    if i >= len(ids):
        return

    vocab_id = ids[i]
    row = db.query_one("SELECT * FROM vocab WHERE id = ?", (vocab_id,))
    card = db.query_one(
        "SELECT * FROM user_words WHERE user_id = ? AND vocab_id = ?", (cb.from_user.id, vocab_id)
    )
    new_state = review(card, quality)
    db.execute(
        """INSERT INTO user_words(user_id, vocab_id, ease, interval, due, reps, lapses, state, last_result)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id, vocab_id) DO UPDATE SET
               ease=excluded.ease, interval=excluded.interval, due=excluded.due,
               reps=excluded.reps, lapses=excluded.lapses, state=excluded.state,
               last_result=excluded.last_result""",
        (
            cb.from_user.id,
            vocab_id,
            new_state["ease"],
            new_state["interval"],
            new_state["due"],
            new_state["reps"],
            new_state["lapses"],
            new_state["state"],
            new_state["last_result"],
        ),
    )
    add_stats(cb.from_user.id, xp=1, tasks=1, correct=1 if quality >= 2 else 0)

    next_i = i + 1
    if next_i >= len(ids):
        await state.set_state(None)
        await state.update_data(cards=[], i=0, revealed=False)
        await cb.message.answer(
            "✅ Готово. Следующий подход — через %d дн. (повтори то, что не знал).\n"
            "Продолжить: /vocab" % new_state["interval"],
            reply_markup=back_to(),
        )
        return

    await state.update_data(i=next_i, revealed=False)
    next_row = db.query_one("SELECT * FROM vocab WHERE id = ?", (ids[next_i],))
    await safe_edit(
        cb.message,
        "%s\n\n%s" % (data.get("title", "Слова"), _card_text(next_row, False)),
        _card_kb(next_i, False),
    )


@router.callback_query(F.data.startswith("vc:speak:"))
async def cb_speak_word(cb: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    ids = data.get("cards") or []
    i = int(data.get("i") or 0)
    if i >= len(ids):
        return
    row = db.query_one("SELECT * FROM vocab WHERE id = ?", (ids[i],))
    if not row:
        return
    path = await TTS.speech(row["sk"])
    if not path:
        return await cb.answer("Озвучка недоступна", show_alert=True)
    await cb.message.answer_voice(str(path), caption="🔊 %s" % row["sk"])


@router.callback_query(F.data == "vc:stop")
async def cb_stop(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer("Стоп")
    await state.set_state(None)
    await state.update_data(cards=[], i=0, revealed=False)
    await cb.message.answer("Остановились. Прогресс сохранён.", reply_markup=back_to())


@router.callback_query(F.data == "vc:export")
async def cb_export(cb: CallbackQuery, bot: Bot) -> None:
    """Выгружает твои слова в TSV — импортируется в Anki (разделитель табуляция)."""
    await cb.answer()
    rows = db.query(
        """SELECT v.sk, v.ru FROM user_words uw JOIN vocab v ON v.id = uw.vocab_id
           WHERE uw.user_id = ? AND uw.state != 'new' ORDER BY uw.due""",
        (cb.from_user.id,),
    )
    if not rows:
        await cb.message.answer("Пока нет выученных слов — начни с /vocab.", reply_markup=back_to())
        return
    lines = ["#separator:tab", "#html:false", "# Словацкий\tРусский"]
    lines.extend("%s\t%s" % (r["sk"], r["ru"]) for r in rows)
    text = "\n".join(lines)
    await cb.message.answer(
        "📤 Твои слова (%d). Сохрани файл и импортируй в Anki:\n\n<code>%s</code>"
        % (len(rows), trim(text, 3500)),
        reply_markup=back_to(),
    )


@router.message(Command("vocab", "слова"))
async def cmd_vocab(message: Message, bot: Bot) -> None:
    await message.answer(
        "🔤 <b>Слова</b>\n\nКоманды: повторение, новые слова, экспорт в Anki.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Повторение", callback_data="vc:mode:due")],
                [InlineKeyboardButton(text="🆕 Новые слова", callback_data="vc:mode:new")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")],
            ]
        ),
    )
