"""Движок урока.

Один и тот же движок крутит:
  * обычные уроки из вашего тренажёра (choice / type / build / match);
  * «тренировку ошибок» — подборку конкретных заданий, где ученик уже ошибался.

У каждого задания — своя схема взаимодействия:

  choice — кнопки с вариантами (порядок случайный, правильный не всегда первый);
  type   — экранная «словацкая» клавиатура (á ä č ď ĺ ľ ň ô ŕ š ť ý ž), потому что
           на русской раскладке этих букв нет и ученик теряет диакритику;
  build  — собираешь фразу из кусочков;
  match  — по очереди переводишь каждое слово.

Каждый ответ сразу разбирается: верно / опечатка / потеряна диакритика / неверно,
с объяснением (из контента — бесплатно, от ИИ — по кнопке «Почему?»).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from app import db
from app.keyboards import build_keyboard, choice_keyboard, sk_keyboard
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
)
from app.services.ai import AI
from app.services.tts import TTS
from app.states import LessonFlow
from app.utils import (
    XP_LESSON,
    XP_PERFECT,
    XP_PER_TASK,
    add_stats,
    progress_bar,
    safe_answer,
    safe_edit,
    score_label,
    trim,
)

KIND_LABEL = {
    "choice": "🎯 Выбери ответ",
    "type": "⌨️ Напиши ответ",
    "build": "🧩 Собери фразу",
    "match": "🔗 Найди пары",
}


class Trainer:
    def __init__(self, fsm: FSMContext, user_id: int, bot: Bot) -> None:
        self.fsm = fsm
        self.user_id = user_id
        self.bot = bot

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #
    async def _data(self) -> Dict[str, Any]:
        data = await self.fsm.get_data()
        return data or {}

    async def _save(self, data: Dict[str, Any]) -> None:
        await self.fsm.update_data(**data)

    def _current_task(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        queue = data.get("queue") or []
        idx = int(data.get("idx") or 0)
        if idx >= len(queue):
            return None
        return queue[idx]

    # ------------------------------------------------------------------ #
    # Старт
    # ------------------------------------------------------------------ #
    async def start(
        self,
        message: Message,
        tasks: List[Dict[str, Any]],
        lesson_id: str,
        title: str,
        mode: str = "lesson",
    ) -> None:
        data = {
            "mode": mode,
            "lesson_id": lesson_id,
            "title": title,
            "queue": tasks,
            "idx": 0,
            "correct": 0,
            "total": 0,
            "mistakes": [],
            "buf": "",
            "built": [],
            "match_ok": {},
            "match_idx": 0,
            "answered": False,
            "started_at": time.time(),
            "task_msg_id": None,
        }
        await self._save(data)
        await self.fsm.set_state(LessonFlow.task)
        await self._send_task(message)

    # ------------------------------------------------------------------ #
    # Показ задания
    # ------------------------------------------------------------------ #
    async def _send_task(self, message: Message) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            await self.finish(message)
            return

        idx = int(data.get("idx") or 0)
        total = len(data.get("queue") or [])
        kind = task["kind"]

        head = "%s\n<i>%s</i>" % (KIND_LABEL.get(kind, kind), progress_bar(idx, total))
        prompt = trim(task.get("prompt") or "")

        if kind == "choice":
            options = list(task.get("options") or [])
            kb = choice_keyboard(options, int(task.get("answer", 0)), "tk:choice:%d" % idx)
            body = "%s\n%s" % (head, prompt)
            await message.answer(body, reply_markup=kb)
            await self._mark_msg(message)

        elif kind == "type":
            sk = (task.get("sk") or "").replace("___", "______")
            body = "%s\n%s\n\n<code>%s</code>" % (head, prompt, sk)
            kb = sk_keyboard("tk:key:%d" % idx)
            kb2 = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        {"text": "✅ Проверить", "callback_data": "tk:typecheck:%d" % idx},
                        {"text": "↩️ Очистить", "callback_data": "tk:typeclear:%d" % idx},
                    ]
                ]
            )
            # добавляем служебные кнопки под буквами
            kb.inline_keyboard.extend(kb2.inline_keyboard)
            await message.answer(body, reply_markup=kb)
            await self._mark_msg(message)

        elif kind == "build":
            words = list(task.get("words") or [])
            body = "%s\n%s" % (head, prompt)
            kb = build_keyboard(words, [], "tk:build:%d" % idx)
            await message.answer(body, reply_markup=kb)
            await self._mark_msg(message)

        elif kind == "match":
            await self._send_match_step(message)

    async def _mark_msg(self, message: Message) -> None:
        data = await self._data()
        data["task_msg_id"] = message.message_id
        data["chat_id"] = message.chat.id
        await self._save(data)

    async def _send_match_step(self, message: Message) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            await self.finish(message)
            return
        idx = int(data.get("idx") or 0)
        pairs = task.get("pairs") or []
        m_idx = int(data.get("match_idx") or 0)
        if m_idx >= len(pairs):
            await self._finish_match(message, task)
            return

        left, right = pairs[m_idx]
        rights = [p[1] for p in pairs]
        body = "🔗 <i>Найди пары (%d/%d)</i>\n\nЧто значит <b>%s</b>?" % (m_idx + 1, len(pairs), left)
        kb = choice_keyboard(rights, -1, "tk:match:%d:%d" % (idx, m_idx))
        await message.answer(body, reply_markup=kb)
        await self._mark_msg(message)

    # ------------------------------------------------------------------ #
    # Ответы
    # ------------------------------------------------------------------ #
    async def on_choice(self, cb: CallbackQuery, option_index: int) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return await cb.answer("Урок уже закончен", show_alert=True)

        idx = int(data.get("idx") or 0)
        options = list(task.get("options") or [])
        correct = int(task.get("answer", 0))
        result = grade_choice(option_index, correct)
        given = options[option_index] if option_index < len(options) else ""
        expected = options[correct] if correct < len(options) else ""
        await self._after_answer(cb, task, given, expected, result, kind="choice")

    async def on_type_text(self, message: Message, text: str) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        await self.check_type(message, text)

    async def check_type(self, message: Message, text: str) -> None:
        """Проверка набранного ответа (и с экранной клавиатуры, и обычным сообщением)."""
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        answers = task.get("answers") or []
        result, expected = grade_text(text, answers)
        await self._after_answer(None, task, text, expected or "", result, kind="type", message=message)

    async def on_key(self, cb: CallbackQuery, char: str) -> None:
        data = await self._data()
        buf = data.get("buf") or ""
        if char == "⌫":
            buf = buf[:-1]
        else:
            buf += char
        data["buf"] = buf
        await self._save(data)
        await self._redraw_type(cb)

    async def on_type_clear(self, cb: CallbackQuery) -> None:
        data = await self._data()
        data["buf"] = ""
        await self._save(data)
        await self._redraw_type(cb)

    async def _redraw_type(self, cb: CallbackQuery) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        idx = int(data.get("idx") or 0)
        buf = data.get("buf") or ""
        sk = (task.get("sk") or "").replace("___", "______")
        body = "%s\n%s\n\n<code>%s</code>\n\n<b>Твой ответ:</b> <code>%s</code>" % (
            KIND_LABEL["type"],
            trim(task.get("prompt") or ""),
            sk,
            buf or "…",
        )
        kb = sk_keyboard("tk:key:%d" % idx)
        kb.inline_keyboard.extend(
            [
                [
                    {"text": "✅ Проверить", "callback_data": "tk:typecheck:%d" % idx},
                    {"text": "↩️ Очистить", "callback_data": "tk:typeclear:%d" % idx},
                ]
            ]
        )
        await safe_answer(cb, body, kb)

    async def on_build_word(self, cb: CallbackQuery, word_index: int) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        words = list(task.get("words") or [])
        built = list(data.get("built") or [])
        if word_index < len(words) and words[word_index] not in built:
            built.append(words[word_index])
        data["built"] = built
        await self._save(data)
        await self._redraw_build(cb, task)

    async def on_build_clear(self, cb: CallbackQuery) -> None:
        data = await self._data()
        data["built"] = []
        await self._save(data)
        task = self._current_task(data)
        if task:
            await self._redraw_build(cb, task)

    async def _redraw_build(self, cb: CallbackQuery, task: Dict[str, Any]) -> None:
        data = await self._data()
        idx = int(data.get("idx") or 0)
        words = list(task.get("words") or [])
        built = list(data.get("built") or [])
        body = "%s\n%s\n\n<b>Собрано:</b> <code>%s</code>" % (
            KIND_LABEL["build"],
            trim(task.get("prompt") or ""),
            " ".join(built) or "…",
        )
        kb = build_keyboard(words, built, "tk:build:%d" % idx)
        await safe_answer(cb, body, kb)

    async def on_build_check(self, cb: CallbackQuery) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        built = list(data.get("built") or [])
        answer = task.get("answer") or ""
        result, expected = grade_build(built, answer)
        await self._after_answer(cb, task, " ".join(built), expected or answer, result, kind="build")

    async def on_match_option(self, cb: CallbackQuery, pair_index: int, option_index: int) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        pairs = task.get("pairs") or []
        rights = [p[1] for p in pairs]
        if pair_index >= len(pairs) or option_index >= len(rights):
            return
        left, right = pairs[pair_index]
        chosen = rights[option_index]
        ok = chosen.strip().lower() == right.strip().lower()

        data["match_ok"] = dict(data.get("match_ok") or {})
        data["match_ok"][str(pair_index)] = 1 if ok else 0
        data["match_idx"] = pair_index + 1
        await self._save(data)

        if ok:
            await cb.answer("Верно", show_alert=False)
        else:
            await cb.answer("Правильно: %s" % right, show_alert=True)

        if pair_index + 1 >= len(pairs):
            await self._finish_match(cb.message, task)
        else:
            await self._send_match_step(cb.message)

    async def _finish_match(self, message: Message, task: Dict[str, Any]) -> None:
        data = await self._data()
        pairs = task.get("pairs") or []
        marks = data.get("match_ok") or {}
        good = sum(1 for value in marks.values() if value)
        total = len(pairs)
        if good == total:
            result = RESULT_OK
        elif good >= total * 0.6:
            result = RESULT_TYPO
        else:
            result = RESULT_BAD
        expected = "; ".join("%s — %s" % (p[0], p[1]) for p in pairs)
        await self._after_answer(
            None,
            task,
            "%d/%d" % (good, total),
            expected,
            result,
            kind="match",
            message=message,
            edit_message=True,
        )

    # ------------------------------------------------------------------ #
    # Разбор ответа
    # ------------------------------------------------------------------ #
    async def _after_answer(
        self,
        cb: Optional[CallbackQuery],
        task: Dict[str, Any],
        given: str,
        expected: str,
        result: str,
        kind: str,
        message: Optional[Message] = None,
        edit_message: bool = False,
    ) -> None:
        data = await self._data()
        idx = int(data.get("idx") or 0)
        total = len(data.get("queue") or [])
        lesson_id = data.get("lesson_id") or ""

        correct_now = result == RESULT_OK
        data["correct"] = int(data.get("correct") or 0) + (1 if correct_now else 0)
        data["total"] = int(data.get("total") or 0) + 1
        data["answered"] = True

        tag = infer_tag(kind, result, given, expected, lesson_id)
        mistakes = list(data.get("mistakes") or [])
        if not correct_now:
            mistakes.append(
                {"i": idx, "given": given, "expected": expected, "tag": tag, "kind": kind}
            )
        data["mistakes"] = mistakes
        await self._save(data)

        db.log_attempt(self.user_id, lesson_id, idx, kind, given, expected, result, tag)
        add_stats(self.user_id, xp=XP_PER_TASK if correct_now else 0, tasks=1, correct=1 if correct_now else 0)

        body = self._feedback_text(task, given, expected, result, tag, idx, total)
        kb = self._feedback_kb(idx)

        if cb is not None:
            await safe_answer(cb, body, kb)
        elif message is not None:
            if edit_message:
                # Сообщение принадлежит боту — правим его на месте.
                await safe_edit(message, body, kb)
            else:
                # Ответ пришёл текстом от пользователя: править его сообщение нельзя
                # (Telegram запрещает), поэтому разбор уходит новым сообщением,
                # а кнопки задания убираем.
                await self._strip_task_keyboard()
                await message.answer(body, reply_markup=kb)

        await self.fsm.set_state(LessonFlow.typing)

    async def _strip_task_keyboard(self) -> None:
        """Убирает кнопки с сообщения-задания, когда ученик ответил текстом."""
        data = await self._data()
        message_id = data.get("task_msg_id")
        chat_id = data.get("chat_id")
        if not message_id or not chat_id:
            return
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
        except Exception:
            pass

    def _feedback_text(
        self,
        task: Dict[str, Any],
        given: str,
        expected: str,
        result: str,
        tag: str,
        idx: int,
        total: int,
    ) -> str:
        lines = [score_label(result), progress_bar(idx + 1, total)]
        if result != RESULT_OK:
            if expected:
                if task.get("kind") == "type":
                    lines.append("Правильно: <b>%s</b>" % expected)
                else:
                    lines.append("Правильно: <b>%s</b>" % expected)
            if given:
                lines.append("Твой ответ: <code>%s</code>" % trim(given, 120))
        if result == RESULT_ACCENTS:
            chars = missing_accents(given, expected)
            if chars:
                lines.append("Потерянные буквы: <b>%s</b> — это диакритика, на русской клавиатуре её нет." % " ".join(chars))
            else:
                lines.append("Диакритика потеряна — следи за á ä č ď ĺ ľ ň ô ŕ š ť ý ž.")
        if result == RESULT_TYPO and task.get("kind") == "build":
            lines.append("Слова те же, порядок другой — в словацком порядок слов гибче, чем в русском.")
        explain = task.get("explain")
        if explain and result != RESULT_OK:
            lines.append("💡 %s" % trim(explain, 400))
        lines.append("Нажми «Почему?» — объясню подробнее. 🔊 — озвучка по-словацки.")
        return "\n".join(lines)

    def _feedback_kb(self, idx: int) -> InlineKeyboardMarkup:
        from aiogram.types import InlineKeyboardButton

        rows = [
            [
                InlineKeyboardButton(text="➡️ Дальше", callback_data="tk:next:%d" % idx),
                InlineKeyboardButton(text="🔁 Ещё раз", callback_data="tk:retry:%d" % idx),
            ],
            [
                InlineKeyboardButton(text="❓ Почему?", callback_data="tk:why:%d" % idx),
                InlineKeyboardButton(text="🔊", callback_data="tk:speak:%d" % idx),
            ],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # ------------------------------------------------------------------ #
    # Управление потоком
    # ------------------------------------------------------------------ #
    async def on_next(self, cb: CallbackQuery) -> None:
        data = await self._data()
        idx = int(data.get("idx") or 0)
        if idx != int((cb.data or "").split(":")[-1]):
            return await cb.answer("Это задание уже закрыто", show_alert=True)
        data["idx"] = idx + 1
        data["buf"] = ""
        data["built"] = []
        data["match_ok"] = {}
        data["match_idx"] = 0
        data["answered"] = False
        await self._save(data)
        await cb.answer()
        if data["idx"] >= len(data.get("queue") or []):
            await self.finish(cb.message)
        else:
            await self._send_task(cb.message)

    async def on_retry(self, cb: CallbackQuery) -> None:
        data = await self._data()
        data["buf"] = ""
        data["built"] = []
        data["match_ok"] = {}
        data["match_idx"] = 0
        data["answered"] = False
        await self._save(data)
        await cb.answer("Ещё раз")
        await self._send_task(cb.message)

    async def on_why(self, cb: CallbackQuery) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        await cb.answer("Спрашиваю у ИИ…")
        explanation = await AI.explain_task(task, "", task.get("answer") or "")
        if not explanation or explanation.startswith("__error__"):
            fallback = task.get("explain") or "Правильный ответ: %s" % task.get("answer", "")
            await cb.message.answer("💡 %s" % fallback)
            return
        await cb.message.answer("💡 %s" % trim(explanation, 1200))

    async def on_speak(self, cb: CallbackQuery) -> None:
        data = await self._data()
        task = self._current_task(data)
        if not task:
            return
        text = task.get("sk") or task.get("answer") or ""
        if task.get("kind") == "choice":
            options = task.get("options") or []
            correct = int(task.get("answer", 0))
            text = options[correct] if correct < len(options) else ""
        text = (text or "").replace("___", "").strip()
        if not text:
            return await cb.answer("Нечего озвучивать", show_alert=True)
        path = await TTS.speech(text)
        if not path:
            return await cb.answer("Озвучка недоступна", show_alert=True)
        await cb.answer()
        await cb.message.answer_voice(FSInputFile(str(path)), caption="🔊 %s" % trim(text, 200))

    # ------------------------------------------------------------------ #
    # Финал
    # ------------------------------------------------------------------ #
    async def finish(self, message: Message) -> None:
        data = await self._data()
        correct = int(data.get("correct") or 0)
        total = int(data.get("total") or 0)
        mode = data.get("mode") or "lesson"
        lesson_id = data.get("lesson_id") or ""
        title = data.get("title") or "Урок"
        mistakes = data.get("mistakes") or []
        started = float(data.get("started_at") or time.time())
        minutes = max(1, int((time.time() - started) / 60))

        score = (correct / total) if total else 0.0
        xp = 0
        if mode == "lesson":
            db.bump_lesson(self.user_id, lesson_id, correct, total, score)
            xp = XP_LESSON + (XP_PERFECT if total and correct == total else 0)
            add_stats(self.user_id, xp=xp, tasks=0, correct=0, minutes=minutes)
        else:
            add_stats(self.user_id, xp=xp, tasks=0, correct=0, minutes=minutes)

        user = db.get_user(self.user_id) or {}
        streak = user.get("streak") or 0

        lines = [
            "🏁 <b>%s</b>" % title,
            "Правильно: <b>%d/%d</b> (%d%%)" % (correct, total, int(score * 100)),
            "⏱ %d мин · серия дней: %s 🔥" % (minutes, streak),
        ]
        if xp:
            lines.append("⭐ +%d XP за урок" % xp)
        if mistakes:
            lines.append("")
            lines.append("Ошибки (%d):" % len(mistakes))
            for m in mistakes[:8]:
                lines.append("• %s → <b>%s</b> <i>(%s)</i>" % (
                    trim(m.get("given", ""), 60) or "…",
                    trim(m.get("expected", ""), 60),
                    m.get("tag", "?"),
                ))
            lines.append("")
            lines.append("Эти задания добавлены в «Мои ошибки» — потренируем отдельно.")
        else:
            lines.append("")
            lines.append("Без ошибок. 🎯")

        from aiogram.types import InlineKeyboardButton

        rows = [[InlineKeyboardButton(text="🎯 Тренировать ошибки", callback_data="nav:drill")]]
        if mode == "lesson":
            rows.append(
                [
                    InlineKeyboardButton(text="➡️ Следующий урок", callback_data="nav:next_lesson"),
                    InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu"),
                ]
            )
        else:
            rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])

        await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await self.fsm.set_state(None)
        await self.fsm.update_data()
