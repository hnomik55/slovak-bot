"""Дёргает /cron/<секрет> — для ежедневной задачи хостинга.

Нужен там, где веб-приложение спит (PythonAnywhere, Render, Fly.io):
раз в день платформа будит бота, и он проверяет, не пора ли напомнить.

    python tools/cron.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import CONFIG  # noqa: E402


def main() -> int:
    base = CONFIG.webhook_base_url
    secret = CONFIG.webhook_secret
    if not base or not secret:
        print("НЕ НАСТРОЕНО: нужны WEBHOOK_BASE_URL и WEBHOOK_SECRET в .env")
        return 1
    url = "%s/cron/%s" % (base.rstrip("/"), secret)
    try:
        response = httpx.get(url, timeout=30)
        print("cron -> %s : %s" % (url.split("/cron/")[0] + "/cron/***", response.status_code))
        print(response.text[:200])
        return 0 if response.status_code == 200 else 1
    except Exception as exc:
        print("не получилось: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
