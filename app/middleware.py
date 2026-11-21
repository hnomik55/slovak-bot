"""Шлюз лицензии.

Пока у человека нет действующего ключа, бот отвечает только на /start (просит ключ)
и принимает сам ключ. Все остальные команды и кнопки закрыты.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from app import licensing
from app.config import CONFIG
from app.states import LicenseFlow

log = logging.getLogger("license")

ALLOWED_COMMANDS = ("/start", "/app", "/help", "/license", "/ключ")


def looks_like_key(text: str) -> bool:
    """Похоже ли сообщение на ключ доступа.

    Ключ нового формата — 20 символов, старого — SLOV-XXXXX-XXXXX-XXXXX.
    Нужно, чтобы ключ принимался и без предварительного /start: состояние
    диалога живёт в памяти и теряется при перезапуске сервера.
    """
    candidate = (text or "").strip()
    if not candidate or len(candidate) > 64:
        return False
    return bool(licensing.parse_codes(candidate)[:1])


class LicenseGate(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if licensing.is_active(user.id):
            return await handler(event, data)

        state: FSMContext = data.get("state")
        current_state = await state.get_state() if state else None
        if current_state == LicenseFlow.key:
            return await handler(event, data)

        if isinstance(event, Message):
            text = (event.text or "").strip().lower()
            if text.startswith(ALLOWED_COMMANDS):
                return await handler(event, data)
            # Ключ принимаем в любой момент, даже если человек не нажимал /start.
            if looks_like_key(event.text or ""):
                return await handler(event, data)
            await event.answer(
                "🔑 Нужен ключ доступа. Пришли его сообщением — или нажми /start.",
                reply_markup=None,
            )
            return None

        if isinstance(event, CallbackQuery):
            # Кнопки, связанные с получением ключа, должны работать
            if (event.data or "").startswith("nav:license"):
                return await handler(event, data)
            await event.answer("🔑 Сначала нужен ключ доступа (/start)", show_alert=True)
            return None

        return await handler(event, data)
