"""Рассылка сообщений пользователям (например, новая кнопка приложения)."""

from __future__ import annotations

import asyncio
from typing import List

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app import db
from app.config import CONFIG


def send_new_button(url: str, text: str = "") -> int:
    """Шлёт всем пользователям кнопку открытия приложения. Возвращает число доставленных."""
    if not CONFIG.bot_token:
        return 0
    message = text or (
        "🔄 Приложение переехало на новый адрес — вот свежая кнопка.\n"
        "Старые кнопки в чате больше не работают."
    )

    async def run() -> int:
        db.init_db()
        rows = db.query("SELECT tg_id FROM users")
        bot = Bot(token=CONFIG.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
        sent = 0
        try:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📱 Открыть приложение", web_app=WebAppInfo(url=url)
                        )
                    ]
                ]
            )
            for row in rows:
                try:
                    await bot.send_message(row["tg_id"], message, reply_markup=kb)
                    sent += 1
                except Exception:
                    pass
        finally:
            await bot.session.close()
        return sent

    try:
        return asyncio.run(run())
    except Exception:
        return 0
