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
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl

from app.config import CONFIG

log = logging.getLogger("miniapp.auth")

MAX_AGE_SECONDS = 24 * 3600


def _check_strings(data: Dict[str, str]) -> List[str]:
    """Варианты data_check_string.

    Telegram присылает в initData поля hash и (с недавних версий) signature.
    В документации описаны два способа исключать их, поэтому проверяем оба:
    без signature и с ним.
    """
    without_hash = {k: v for k, v in data.items() if k != "hash"}
    without_signature = {k: v for k, v in without_hash.items() if k != "signature"}
    variants = [without_hash, without_signature]
    out: List[str] = []
    for variant in variants:
        out.append("\n".join("%s=%s" % (k, variant[k]) for k in sorted(variant)))
    return out


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
    if not received_hash:
        log.warning("initData без поля hash")
        return None

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated = []
    for check_string in _check_strings(data):
        calculated.append(
            hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        )

    if not any(hmac.compare_digest(expected, received_hash) for expected in calculated):
        log.warning(
            "подпись initData не сошлась: поля=%s полученный=%s расчётные=%s",
            sorted(data.keys()),
            received_hash[:16],
            [c[:16] for c in calculated],
        )
        return None

    # Свежесть: чтобы украденную подпись нельзя было вечно использовать
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        auth_date = 0
    if auth_date and (time.time() - auth_date) > max_age:
        log.warning("initData устарел (auth_date=%s)", auth_date)
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
