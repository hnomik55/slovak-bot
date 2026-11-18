"""Клавиатуры.

Все меню — инлайн (кнопки под сообщением): в Телеграме они работают лучше
реплаев, их можно редактировать, и одна кнопка = одно действие.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAIN_MENU = [
    ("📚 Уроки", "lessons"),
    ("🔤 Слова", "vocab"),
    ("🎧 Аудирование", "listening"),
    ("📖 Чтение", "reading"),
    ("✍️ Письмо", "writing"),
    ("🗣 Говорить", "speaking"),
    ("📝 Мини-тест", "quiz"),
    ("📊 Прогресс", "progress"),
    ("⚠️ Мои ошибки", "errors"),
    ("⚙️ Настройки", "settings"),
]


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for label, action in MAIN_MENU:
        kb.button(text=label, callback_data=f"nav:{action}")
    kb.adjust(2, 2, 2, 2, 2)
    return kb.as_markup()


def back_to(label: str = "⬅️ В меню", action: str = "menu") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=label, callback_data=f"nav:{action}")
    return kb.as_markup()


def units_menu(units: List[Dict[str, Any]], progress: Dict[str, float]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for unit in units:
        n = unit.get("n")
        done = progress.get(str(n), 0.0)
        mark = "✅" if done >= 0.8 else ("🟡" if done > 0 else "🔒")
        kb.button(
            text="%s %s. %s" % (mark, n, unit.get("title", "")),
            callback_data=f"nav:unit:{n}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu"))
    return kb.as_markup()


def lessons_menu(unit_no: int, lessons: List[Dict[str, Any]], states: Dict[str, str]) -> InlineKeyboardMarkup:
    """states: lesson_id -> 'done' | 'open' | 'locked'."""
    kb = InlineKeyboardBuilder()
    for lesson in lessons:
        lid = lesson["id"]
        state = states.get(lid, "locked")
        icon = {"done": "✅", "open": "▶️", "locked": "🔒"}.get(state, "🔒")
        kb.button(text="%s %s. %s" % (icon, lid, lesson.get("title", "")), callback_data=f"nav:lesson:{lid}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="⬅️ К юнитам", callback_data="nav:units"))
    return kb.as_markup()


def choice_keyboard(options: Sequence[str], correct_index: int, prefix: str) -> InlineKeyboardMarkup:
    """Варианты в случайном порядке (чтобы не запоминать позицию кнопки)."""
    order = list(range(len(options)))
    random.shuffle(order)
    kb = InlineKeyboardBuilder()
    for i in order:
        kb.button(text=options[i], callback_data="%s:%d" % (prefix, i))
    kb.adjust(1)
    return kb.as_markup()


# Буквы, которых нет на русской раскладке — частая беда при вводе по-славацки
SK_KEYS = list("áäčďéíĺľňóôŕšťúýž")


def sk_keyboard(prefix: str = "sk") -> InlineKeyboardMarkup:
    """Экранная клавиатура со словацкими буквами (в Telegram максимум 8 кнопок в ряду)."""
    rows = []
    for i in range(0, len(SK_KEYS), 6):
        chunk = SK_KEYS[i : i + 6]
        rows.append(
            [InlineKeyboardButton(text=ch, callback_data="%s:%s" % (prefix, ch)) for ch in chunk]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_keyboard(words: Sequence[str], used: Sequence[str], prefix: str = "bw") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, word in enumerate(words):
        label = word if word not in used else "· %s ·" % word
        kb.button(text=label, callback_data="%s:%d" % (prefix, i))
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text="✅ Проверить", callback_data=f"{prefix}:check"))
    kb.row(InlineKeyboardButton(text="↩️ Очистить", callback_data=f"{prefix}:clear"))
    return kb.as_markup()


def confirm_keyboard(prefix: str = "ans") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Проверить", callback_data=f"{prefix}:check")
    kb.row(InlineKeyboardButton(text="↩️ Очистить", callback_data=f"{prefix}:clear"))
    return kb.as_markup()


def feedback_keyboard(prefix: str = "fb", extra: Optional[List[tuple]] = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if extra:
        for label, data in extra:
            kb.button(text=label, callback_data=data)
    kb.button(text="Дальше ➡️", callback_data=f"{prefix}:next")
    kb.row(InlineKeyboardButton(text="🔁 Ещё раз", callback_data=f"{prefix}:retry"))
    kb.row(InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu"))
    return kb.as_markup()
