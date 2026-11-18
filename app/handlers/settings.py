"""Настройки: уровень, дневная норма, напоминания, голос, режим ИИ."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import db
from app.config import CONFIG
from app.utils import safe_edit

log = logging.getLogger("settings")
router = Router(name="settings")

LEVELS = [("A1", "Начальный"), ("A2", "Базовый"), ("B1", "Продвинутый")]
MINUTES = [15, 30, 45, 60]
REMINDERS = [("off", "Выключить"), ("19:00", "19:00"), ("21:00", "21:00"), ("23:00", "23:00")]


def _menu_kb(user: dict) -> InlineKeyboardMarkup:
    level = user.get("level", "A1")
    minutes = user.get("daily_minutes", 30)
    reminder = user.get("reminder_time", "21:00")
    ai_mode = user.get("ai_mode", "full")
    rows = [
        [
            InlineKeyboardButton(text="🎚 Уровень", callback_data="set:level"),
            InlineKeyboardButton(text="🎚 Уровень: %s" % level, callback_data="set:level"),
        ]
    ]
    rows = [
        [InlineKeyboardButton(text="📚 Уровень: %s" % level, callback_data="set:level")],
        [InlineKeyboardButton(text="⏱ Дневная норма: %d мин" % minutes, callback_data="set:minutes")],
        [InlineKeyboardButton(text="🔔 Напоминание: %s" % reminder, callback_data="set:reminder")],
        [
            InlineKeyboardButton(
                text="🧠 ИИ: %s" % ("включён" if ai_mode == "full" else "только проверка"),
                callback_data="set:ai",
            )
        ],
        [
            InlineKeyboardButton(text="♻️ Сбросить прогресс", callback_data="set:reset"),
            InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "nav:settings")
async def cb_settings(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    await safe_edit(
        cb.message,
        "⚙️ <b>Настройки</b>\n\n"
        "Уровень влияет на подбор слов и сложность текстов.\n"
        "Напоминание приходит в твоё местное время — не чаще одного раза в день.",
        _menu_kb(user),
    )


@router.callback_query(F.data == "set:level")
async def cb_level(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    rows = [[InlineKeyboardButton(text="%s — %s" % (code, title), callback_data="set:lvl:%s" % code)] for code, title in LEVELS]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:settings")])
    await safe_edit(cb.message, "Выбери уровень:", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("set:lvl:"))
async def cb_set_level(cb: CallbackQuery, bot: Bot) -> None:
    level = (cb.data or "").split(":")[-1]
    db.execute("UPDATE users SET level = ? WHERE tg_id = ?", (level, cb.from_user.id))
    await cb.answer("Уровень: %s" % level)
    user = db.get_user(cb.from_user.id) or {}
    await safe_edit(cb.message, "Уровень: <b>%s</b>" % level, _menu_kb(user))


@router.callback_query(F.data == "set:minutes")
async def cb_minutes(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    rows = [[InlineKeyboardButton(text="%d мин" % m, callback_data="set:min:%d" % m)] for m in MINUTES]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:settings")])
    await safe_edit(cb.message, "Сколько минут в день хочешь заниматься?", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("set:min:"))
async def cb_set_minutes(cb: CallbackQuery, bot: Bot) -> None:
    minutes = int((cb.data or "").split(":")[-1])
    db.execute("UPDATE users SET daily_minutes = ? WHERE tg_id = ?", (minutes, cb.from_user.id))
    await cb.answer("Норма: %d мин" % minutes)
    user = db.get_user(cb.from_user.id) or {}
    await safe_edit(cb.message, "Дневная норма: <b>%d мин</b>" % minutes, _menu_kb(user))


@router.callback_query(F.data == "set:reminder")
async def cb_reminder(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    rows = [[InlineKeyboardButton(text=title, callback_data="set:rem:%s" % value)] for value, title in REMINDERS]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:settings")])
    await safe_edit(cb.message, "Когда напоминать?", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("set:rem:"))
async def cb_set_reminder(cb: CallbackQuery, bot: Bot) -> None:
    value = (cb.data or "").split(":")[-1]
    db.execute("UPDATE users SET reminder_time = ? WHERE tg_id = ?", (value, cb.from_user.id))
    await cb.answer("Напоминание: %s" % value)
    user = db.get_user(cb.from_user.id) or {}
    await safe_edit(cb.message, "Напоминание: <b>%s</b>" % value, _menu_kb(user))


@router.callback_query(F.data == "set:ai")
async def cb_ai_mode(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    user = db.get_user(cb.from_user.id) or {}
    new_mode = "off" if user.get("ai_mode") == "full" else "full"
    db.execute("UPDATE users SET ai_mode = ? WHERE tg_id = ?", (new_mode, cb.from_user.id))
    if new_mode == "full" and not CONFIG.ai_enabled:
        await cb.message.answer(
            "⚠️ Включил, но ключа нет: пропиши AI_API_KEY в .env и перезапусти бота.",
            reply_markup=_menu_kb(db.get_user(cb.from_user.id) or {}),
        )
        return
    user = db.get_user(cb.from_user.id) or {}
    await safe_edit(cb.message, "Режим ИИ: <b>%s</b>" % ("включён" if new_mode == "full" else "только локальная проверка"), _menu_kb(user))


@router.callback_query(F.data == "set:reset")
async def cb_reset(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    rows = [
        [InlineKeyboardButton(text="🗑 Сбросить всё", callback_data="set:reset:yes")],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="nav:settings")],
    ]
    await safe_edit(cb.message, "Сбросить прогресс, слова и ошибки? Это необратимо.", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "set:reset:yes")
async def cb_reset_yes(cb: CallbackQuery, bot: Bot) -> None:
    db.execute("DELETE FROM user_words WHERE user_id = ?", (cb.from_user.id,))
    db.execute("DELETE FROM lesson_progress WHERE user_id = ?", (cb.from_user.id,))
    db.execute("DELETE FROM attempts WHERE user_id = ?", (cb.from_user.id,))
    db.execute("DELETE FROM error_tags WHERE user_id = ?", (cb.from_user.id,))
    db.execute("DELETE FROM daily_stats WHERE user_id = ?", (cb.from_user.id,))
    db.execute("UPDATE users SET xp = 0, streak = 0, best_streak = 0, last_day = NULL WHERE tg_id = ?", (cb.from_user.id,))
    await cb.answer("Сброшено")
    await safe_edit(cb.message, "Прогресс сброшен. Начинаем заново 🚀", _menu_kb(db.get_user(cb.from_user.id) or {}))


@router.message(Command("settings", "настройки"))
async def cmd_settings(message: Message, bot: Bot) -> None:
    user = db.get_user(message.from_user.id) or {}
    await message.answer("⚙️ <b>Настройки</b>", reply_markup=_menu_kb(user))
