"""Проверка связи с Telegram Bot API.

Запуск: python tools/check_telegram.py

Покажет, проходит ли трафик к Telegram и, если нет, где именно обрыв.
"""

from __future__ import annotations

import socket
import ssl
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import CONFIG  # noqa: E402

OK = "\033[32mок\033[0m"
BAD = "\033[31mплохо\033[0m"


def check_root() -> bool:
    """Корень api.telegram.org — работает, даже если Bot API заблокирован."""
    try:
        r = httpx.get("https://api.telegram.org/", timeout=15)
        return r.status_code in (200, 302)
    except Exception:
        return False


def check_bot_api() -> bool:
    """Собственно Bot API с токеном."""
    if not CONFIG.bot_token:
        return False
    try:
        r = httpx.get("https://api.telegram.org/bot%s/getMe" % CONFIG.bot_token, timeout=15)
        return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False


def check_tls() -> bool:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("api.telegram.org", 443), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname="api.telegram.org"):
                return True
    except Exception:
        return False


def main() -> int:
    print("Проверяю связь с Telegram…\n")
    tls_ok = check_tls()
    root_ok = check_root()
    bot_ok = check_bot_api()

    print("  TLS до api.telegram.org .... %s" % (OK if tls_ok else BAD))
    print("  корень api.telegram.org ... %s" % (OK if root_ok else BAD))
    print("  Bot API (с токеном) ....... %s" % (OK if bot_ok else BAD))
    print()

    if bot_ok:
        print("Всё отлично: бот ходит в Telegram, можно работать.")
        return 0

    if root_ok and not bot_ok:
        print("Проблема найдена: обычный сайт Telegram открывается, а Bot API — нет.")
        print("Значит, трафик к /bot... режет VPN (или его сервер).")
        print()
        print("Что делать:")
        print("  1. В клиенте VPN добавь api.telegram.org и *.telegram.org в правило")
        print("     «напрямую / без туннеля» (split tunneling).")
        print("  2. Или выключи VPN на время, пока работаешь с ботом.")
        print("  3. Проверь: python tools\\check_telegram.py")
        print()
        print("Если VPN трогать не хочешь — перенеси бота в GitHub Actions:")
        print("  (там связь с Telegram всегда есть)")
        return 1

    print("Telegram недоступен вообще — проверь интернет или VPN.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
