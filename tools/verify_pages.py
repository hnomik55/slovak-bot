"""Финальная проверка: приложение на GitHub Pages тянет данные с API.

Проверяем цепочку: Pages -> config.json -> API (CORS) -> ответ.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import CONFIG  # noqa: E402

PAGES = "https://hnomik55.github.io/slovak-bot"

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s %s" % (name, detail))


def make_init_data(user_id: int = 8636653095) -> str:
    data = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHtest",
        "user": json.dumps({"id": user_id, "first_name": "Тест", "language_code": "ru"}),
    }
    data_check = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", CONFIG.bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def main() -> int:
    print("\n== Страница на Pages ==")
    r = httpx.get(PAGES + "/", timeout=40, follow_redirects=True)
    check("страница отдаётся", r.status_code == 200, str(r.status_code))
    check("это наше приложение", "Slovencina" in r.text or "Слова" in r.text, r.text[:100])

    print("\n== config.json ==")
    r = httpx.get(PAGES + "/config.json", timeout=40)
    check("config.json отдаётся", r.status_code == 200, str(r.status_code))
    cfg = r.json() if r.status_code == 200 else {}
    api_base = cfg.get("api_base", "")
    check("в конфиге есть адрес API", bool(api_base), str(cfg))
    check("адрес API доступен", api_base.startswith("https://"), api_base)

    print("\n== Запрос к API сorigin=Pagеs ==")
    origin = "https://hnomik55.github.io"
    headers = {"Origin": origin, "X-Telegram-Init-Data": make_init_data()}
    r = httpx.get(api_base + "/api/session", headers=headers, timeout=40)
    check("API отвечает", r.status_code == 200, str(r.status_code) + " " + r.text[:120])
    check(
        "CORS разрешает github.io",
        r.headers.get("access-control-allow-origin") == origin,
        str(r.headers.get("access-control-allow-origin")),
    )
    if r.status_code == 200:
        data = r.json()
        check("пришёл пользователь", data.get("user", {}).get("telegram_id") == 8636653095, str(data)[:120])
        check("лицензия видна", "license" in data, str(data)[:120])

    print("\n== Остальные эндпоинты через Pages-origin ==")
    for path in ("/api/home", "/api/units", "/api/progress"):
        rr = httpx.get(api_base + path, headers=headers, timeout=40)
        check("%s -> 200" % path, rr.status_code == 200, str(rr.status_code))

    print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
