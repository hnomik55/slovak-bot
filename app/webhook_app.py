"""Flask-приложение для режима вебхука.

Схема работы:
  Telegram --POST--> /bot/<секрет>  -->  dp.feed_update()  -->  бот отвечает

Почему Flask: он предустановлен на бесплатных хостингах (PythonAnywhere, Render,
Railway, Fly.io) и поднимается там как WSGI-приложение без ручной настройки.

Требования к хостингу:
  * постоянный адрес с HTTPS (все бесплатные платформы дают его сразу);
  * веб-приложение (не «скрипт»), живёт постоянно;
  * чтобы бот просыпался по расписанию — ежедневная задача, дёргающая /cron/<секрет>.

Важно: event loop один и тот же на весь процесс. aiohttp-сессия aiogram
привязана к циклу, поэтому новый цикл на каждый запрос ломает отправку.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from app.telegram_session import ProxyAwareSession
from aiogram.types import Update
from flask import Flask, jsonify, request, send_file

from app.config import CONFIG

log = logging.getLogger("webhook")

# Один loop на процесс
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _secret_ok(candidate: str) -> bool:
    secret = CONFIG.webhook_secret
    if not secret:
        return True  # секрет не задан — пропускаем (но это небезопасно)
    return candidate == secret


def create_app(bot: Bot, dp: Dispatcher) -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    # --- CORS ---
    # Приложение может лежать на GitHub Pages (https://user.github.io/...),
    # а API — на другом домене (туннель). Разрешаем запросы с этих адресов.
    allowed_hosts = ("github.io", "trycloudflare.com", "pythonanywhere.com", "localhost")

    @app.before_request
    def handle_options():
        if request.method == "OPTIONS":
            return ("", 204)
        return None

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin", "")
        if origin and any(host in origin for host in allowed_hosts):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "X-Telegram-Init-Data, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "3600"
            response.headers["Vary"] = "Origin"
        return response

    @app.route("/bot/<secret>", methods=["POST"])
    def telegram_webhook(secret: str):
        if not _secret_ok(secret):
            log.warning("запрос с неверным секретом — отклонён")
            return jsonify({"ok": False}), 403
        try:
            data = request.get_json(force=True, silent=True) or {}
            update = Update.model_validate(data, context={"bot": bot})
            _run(dp.feed_update(bot, update))
            return jsonify({"ok": True})
        except Exception as exc:
            log.exception("ошибка обработки апдейта: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/cron/<secret>", methods=["GET"])
    def cron(secret: str):
        """Точка для внешнего крона: проверяет, не пора ли напомнить."""
        if not _secret_ok(secret):
            return jsonify({"ok": False}), 403
        try:
            from app.services.reminders import catch_up

            _run(catch_up(bot))
            return jsonify({"ok": True})
        except Exception as exc:
            log.exception("cron-ошибка: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "mode": CONFIG.mode})

    # --- Mini App ---
    try:
        from app.miniapp_api import bp as miniapp_bp

        app.register_blueprint(miniapp_bp)
    except Exception as exc:  # не ломаем основной бот из-за Mini App
        log.warning("Mini App API не подключился: %s", exc)

    miniapp_dir = Path(__file__).resolve().parent.parent / "docs"

    @app.route("/", methods=["GET"])
    def miniapp_index():
        index = miniapp_dir / "index.html"
        if not index.exists():
            return jsonify({"error": "miniapp_not_built"}), 404
        return index.read_text(encoding="utf-8")

    @app.route("/app", methods=["GET"])
    def miniapp_open():
        return miniapp_index()

    @app.route("/config.json", methods=["GET"])
    def miniapp_config():
        """Адрес API для приложения (на GitHub Pages лежит рядом с index.html)."""
        config = miniapp_dir / "config.json"
        if not config.exists():
            return jsonify({"api_base": ""})
        return config.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}

    @app.route("/static/<path:filename>")
    def miniapp_static(filename: str):
        target = (miniapp_dir / filename).resolve()
        if not str(target).startswith(str(miniapp_dir.resolve())) or not target.exists():
            return jsonify({"error": "not_found"}), 404
        return send_file(str(target))

    return app


def build_wsgi_app() -> Flask:
    """Собирает приложение для gunicorn/uWSGI.

    Точка входа лежит в файле wsgi.py в корне проекта:
        gunicorn --workers 1 --bind 0.0.0.0:8000 wsgi:app
    Один воркер обязателен: состояние бота (FSM, сессия) живёт в процессе.
    """
    from bot import build_dispatcher, startup

    bot = Bot(
        token=CONFIG.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
        session=ProxyAwareSession(trust_env=CONFIG.use_system_proxy),
    )
    dp = build_dispatcher()
    try:
        _run(startup(bot))
    except Exception as exc:
        log.warning("инициализация не завершилась: %s", exc)
    return create_app(bot, dp)
