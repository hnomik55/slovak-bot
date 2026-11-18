"""Напоминания.

Раз в минуту бот смотрит, кому сейчас пора напомнить (время в .env: REMINDER_TIME,
REMINDER_TZ) и кто сегодня ещё не занимался. Напоминание приходит максимум один
раз в день и только если ученик не отвечал.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app import db
from app.config import CONFIG

log = logging.getLogger("reminders")


def _now_local() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(CONFIG.reminder_tz))
    except Exception:
        return datetime.now()


def _due_users() -> List[Dict[str, Any]]:
    now = _now_local()
    stamp = now.strftime("%H:%M")
    today = db.today()
    rows = db.query(
        "SELECT * FROM users WHERE reminder_time != 'off' AND reminder_time = ?",
        (stamp,),
    )
    out = []
    for row in rows:
        if row.get("last_day") == today:
            continue  # сегодня уже занимался
        out.append(row)
    return out


async def tick(bot: Bot) -> None:
    """Одна итерация планировщика."""
    for user in _due_users():
        due = db.query_one(
            "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?",
            (user["tg_id"], db.today()),
        )
        due_count = int(due["n"]) if due else 0
        streak = user.get("streak") or 0
        minutes = user.get("daily_minutes") or CONFIG.daily_minutes

        if due_count:
            headline = "🔔 Сегодня на повторение %d слов. Это %d минут — и всё." % (due_count, minutes)
        else:
            headline = "🔔 План на сегодня: %d минут. Урок + слова — и серия растёт." % minutes

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔤 Слова", callback_data="vc:mode:due"),
                    InlineKeyboardButton(text="📚 Урок", callback_data="nav:next_lesson"),
                ],
                [InlineKeyboardButton(text="⏰ Напомнить позже", callback_data="nav:menu")],
            ]
        )
        try:
            await bot.send_message(user["tg_id"], headline + "\n🔥 Серия дней: %d" % streak, reply_markup=kb)
        except Exception as exc:
            log.debug("напоминание не доставлено %s: %s", user["tg_id"], exc)


async def catch_up(bot: Bot) -> None:
    """Если бот стоял выключенным и пропустил время напоминания — догоняем один раз в день.

    Это спасает сценарий "бот на домашнем ПК": комп выключили вечером, включили
    утром — ученик получает напоминание, что вчера не занимался.
    """
    now = _now_local()
    stamp = now.strftime("%H:%M")
    today = db.today()
    rows = db.query(
        "SELECT * FROM users WHERE reminder_time != 'off' AND reminder_time != '' AND (last_day IS NULL OR last_day != ?)",
        (today,),
    )
    for user in rows:
        if (user.get("nudged_day") or "") == today:
            continue
        if stamp < (user.get("reminder_time") or "21:00"):
            continue
        due = db.query_one(
            "SELECT COUNT(*) AS n FROM user_words WHERE user_id = ? AND due <= ?",
            (user["tg_id"], today),
        )
        due_count = int(due["n"]) if due else 0
        headline = (
            "🔔 Ты вчера не занимался — не отставай от графика.\n"
            "Серия дней: %s. План: %d мин."
            % (user.get("streak") or 0, user.get("daily_minutes") or CONFIG.daily_minutes)
        )
        if due_count:
            headline = "🔔 На повторение ждут %d слов — это %d минут.\n%s" % (
                due_count,
                user.get("daily_minutes") or CONFIG.daily_minutes,
                headline,
            )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔤 Слова", callback_data="vc:mode:due"),
                    InlineKeyboardButton(text="📚 Урок", callback_data="nav:next_lesson"),
                ]
            ]
        )
        try:
            await bot.send_message(user["tg_id"], headline, reply_markup=kb)
            db.execute("UPDATE users SET nudged_day = ? WHERE tg_id = ?", (today, user["tg_id"]))
        except Exception as exc:
            log.debug("догоняющее напоминание не доставлено %s: %s", user["tg_id"], exc)


def start_scheduler(bot: Bot) -> Optional[Any]:
    """Запускает APScheduler. None — если apscheduler не установлен."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        log.warning("APScheduler не установлен — напоминания выключены")
        return None

    scheduler = AsyncIOScheduler(timezone=CONFIG.reminder_tz)
    scheduler.add_job(tick, "cron", second=0, id="reminders", kwargs={"bot": bot})
    scheduler.start()
    log.info("планировщик напоминаний запущен (%s)", CONFIG.reminder_tz)
    return scheduler
