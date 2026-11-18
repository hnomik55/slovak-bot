"""Проверка подписи Telegram WebApp (initData).

Mini App — это обычная веб-страница, открытая внутри Telegram. Чтобы бот знал,
кто именно её открыл, Telegram подписывает данные пользователя ключом,
который знает только бот.

Алгоритм (документация Telegram):
  secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  data_check_string = "\\n".join(sorted("key=value")) без поля hash и signature
  hash = HMAC_SHA256(key=secret_key, msg=data_check_string)

Для проверки в обычном браузере (без Telegram) есть dev-режим:
если initData пуст и APP_DEV=1, берётся DEV_TELEGRAM_ID.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

from app.config import CONFIG

MAX_AGE_SECONDS = 24 * 3600


def verify_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE_SECONDS) -> Optional[Dict[str, Any]]:
    """Возвращает распарсенного пользователя или None, если подпись не сошлась."""
    if not init_data:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except ValueError:
        return None
    if not pairs:
        return None

    data = dict(pairs)
    received_hash = data.pop("hash", None)
    data.pop("signature", None)
    if not received_hash:
        return None

    data_check_string = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None

    # Свежесть: чтобы украденную подпись нельзя было вечно использовать
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        auth_date = 0
    if auth_date and (time.time() - auth_date) > max_age:
        return None

    user: Dict[str, Any] = {}
    raw_user = data.get("user")
    if raw_user:
        try:
            user = json.loads(raw_user)
        except json.JSONDecodeError:
            user = {}
    user["_auth_date"] = auth_date
    return user


def telegram_id_from_init_data(init_data: str) -> Optional[int]:
    """Идентификатор пользователя по initData (None — если подпись не сошлась)."""
    user = verify_init_data(init_data, CONFIG.bot_token)
    if not user:
        return None
    try:
        return int(user.get("id"))
    except (TypeError, ValueError):
        return None


def dev_user() -> Optional[int]:
    """Пользователь для браузера без Telegram (режим разработки)."""
    if not CONFIG.app_dev:
        return None
    return CONFIG.dev_telegram_id or None
