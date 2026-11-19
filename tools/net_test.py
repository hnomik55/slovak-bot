"""Проверка связи с Telegram с хоста: через прокси и без него.

Запуск: python tools/net_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import CONFIG  # noqa: E402

URL = "https://api.telegram.org/bot%s/getMe" % CONFIG.bot_token
ROOT_URL = "https://api.telegram.org/"


def show_proxy_env() -> None:
    print("Прокси в окружении:")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        value = os.environ.get(key)
        if value:
            print("   %s = %s" % (key, value))
    print()


async def aiohttp_test(trust_env: bool) -> None:
    try:
        import aiohttp
    except ImportError:
        print("  aiohttp: не установлен")
        return
    try:
        async with aiohttp.ClientSession(trust_env=trust_env) as session:
            async with session.get(URL, timeout=aiohttp.ClientTimeout(total=20)) as response:
                text = (await response.text())[:70]
                print("  aiohttp trust_env=%-5s -> %s %s" % (trust_env, response.status, text))
    except Exception as exc:
        print("  aiohttp trust_env=%-5s -> %s: %s" % (trust_env, type(exc).__name__, str(exc)[:60]))


async def httpx_test(trust_env: bool) -> None:
    try:
        import httpx
    except ImportError:
        print("  httpx: не установлен")
        return
    try:
        async with httpx.AsyncClient(trust_env=trust_env, timeout=20) as client:
            response = await client.get(URL)
            print("  httpx   trust_env=%-5s -> %s %s" % (trust_env, response.status_code, response.text[:70]))
    except Exception as exc:
        print("  httpx   trust_env=%-5s -> %s: %s" % (trust_env, type(exc).__name__, str(exc)[:60]))


async def main() -> int:
    print("Токен: %s..." % (CONFIG.bot_token or "НЕТ")[:12])
    show_proxy_env()
    print("Проверяю корень api.telegram.org:")
    await aiohttp_test(False)
    print("Проверяю Bot API (с токеном):")
    await aiohttp_test(False)
    await httpx_test(True)
    await httpx_test(False)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
