"""Регистрация/снятие вебхука в Telegram.

    python tools/set_webhook.py set https://твой-домен.рф
    python tools/set_webhook.py delete
    python tools/set_webhook.py info

URL собирается так: <база>/bot/<WEBHOOK_SECRET из .env>.
Секрет нужен, чтобы посторонние не слали апдейты твоему боту.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import CONFIG  # noqa: E402


def ensure_secret() -> str:
    """Если WEBHOOK_SECRET не задан — сгенерировать и записать в .env."""
    if CONFIG.webhook_secret:
        return CONFIG.webhook_secret
    secret = secrets.token_urlsafe(24)
    path = ROOT / ".env"
    text = path.read_text(encoding="utf-8")
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.strip().startswith("WEBHOOK_SECRET="):
            lines.append("WEBHOOK_SECRET=%s" % secret)
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append("WEBHOOK_SECRET=%s" % secret)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Сгенерирован WEBHOOK_SECRET и записан в .env")
    return secret


async def api(method: str) -> None:
    url = "https://api.telegram.org/bot%s/%s" % (CONFIG.bot_token, method)
    # trust_env=False — не идём через системный прокси (хостинги с прокси режут /bot)
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.get(url)
        print(response.json())


async def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "info"

    if action == "info":
        await api("getWebhookInfo")
        return 0

    if action == "delete":
        await api("deleteWebhook")
        return 0

    if action == "set":
        if len(sys.argv) < 3:
            print("usage: python tools/set_webhook.py set <https://base-url>")
            return 1
        base = sys.argv[2].rstrip("/")
        secret = ensure_secret()
        url = "%s/bot/%s" % (base, secret)
        print("Регистрирую вебхук: %s" % url)
        await api("setWebhook?url=%s&secret_token=%s&allowed_updates=%s" % (
            url,
            secret,
            "message%2Cedited_message%2Ccallback_query",
        ))
        print("\nГотово. Проверка:")
        await api("getWebhookInfo")
        print("\nТеперь допиши в .env:")
        print("  MODE=webhook")
        print("  WEBHOOK_BASE_URL=%s" % base)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
