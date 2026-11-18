"""Состояния диалога (FSM)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class LessonFlow(StatesGroup):
    """Внутри урока или тренировки ошибок."""

    task = State()  # активное задание (choice/type/build/match)
    typing = State()  # ждём текстовый ответ (ввод по-русской/словацкой раскладкой)


class WritingFlow(StatesGroup):
    text = State()  # ждём текст работы


class SpeakingFlow(StatesGroup):
    turn = State()  # ждём реплику (голос или текст) в диалоге
    repeat = State()  # ждём голос для повторения фразы


class SettingsFlow(StatesGroup):
    pick = State()  # ждём выбор значения настройки


class LicenseFlow(StatesGroup):
    key = State()  # ждём ключ доступа
