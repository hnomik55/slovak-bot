"""Пишет боту от имени пользователя (для проверки ответа). Нужен user_id.

Использует токен бота и user_id ученика — Telegram позволяет боту писать
в чат только пользователю, который сам начинал диалог. Поэтому здесь мы
просто спрашиваем у Telegram, есть ли ожидающие апдейты, и печатаем их.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import CONFIG  # noqa: E402


def main() -> int:
    url = "https://api.telegram.org/bot%s/getUpdates" % CONFIG.bot_token
    try:
        r = httpx.get(url, params={"timeout": 5, "limit": 10}, timeout=30)
        data = r.json()
    except Exception as exc:
        print("не удалось обратиться к Telegram: %s" % type(exc).__name__)
        return 1
    if not data.get("ok"):
        print("Telegram ответил:", data)
        return 1
    updates = data.get("result") or []
    print("Ожидающих апдейтов: %d" % len(updates))
    for u in updates:
        msg = u.get("message") or u.get("callback_query") or {}
        text = msg.get("text") or (msg.get("message") or {}).get("text") or "(нажата кнопка)"
        who = (msg.get("from") or {}).get("first_name")
        print("  [%s] %s: %s" % (u.get("update_id"), who, str(text)[:80]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
