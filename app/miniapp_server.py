"""Сервер Mini App (Flask).

Запуск:
    python app/miniapp_server.py            # http://127.0.0.1:8000
    python app/miniapp_server.py --port 8080

Отдаёт:
    /            — само приложение (miniapp/index.html)
    /api/*       — API для приложения
    /bot/<secret> — вебхук Telegram (если MODE=webhook)
    /health      — проверка живости
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("miniapp-server")

from app.webhook_app import build_wsgi_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Сервер Mini App")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = build_wsgi_app()
    log.info("Mini App: http://%s:%d", args.host, args.port)
    log.info("Проверка: http://%s:%d/health", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
