"""Конфигурация бота.

Всё читается из .env рядом с проектом (или из переменных окружения).
Секреты (токен, ключ ИИ) в .env, .env в .gitignore.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    """Минимальный парсер .env (python-dotenv в проекте нет, а тянуть его ради этого не надо)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on", "да"):
        return True
    if raw in ("0", "false", "no", "off", "нет"):
        return False
    return default


def _list(name: str) -> List[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    out: List[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            out.append(int(chunk))
    return out


def _path(name: str, default: Path) -> Path:
    """Путь из окружения. Относительный разрешаем от корня проекта.

    Иначе бот и Mini App, запущенные из разных папок, писали бы в разные базы.
    """
    raw = os.environ.get(name, "").strip()
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = ROOT / path
    return path


@dataclass
class Config:
    # --- Telegram ---
    bot_token: str = field(default_factory=lambda: os.environ.get("BOT_TOKEN", "").strip())
    admin_ids: List[int] = field(default_factory=lambda: _list("ADMIN_IDS"))

    # --- Пути ---
    root: Path = ROOT
    source_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("SOURCE_DIR", r"D:\Slovakia"))
    )
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", ROOT / "data"))
    db_path: Path = field(default_factory=lambda: _path("DB_PATH", ROOT / "data" / "slovak.db"))

    # --- ИИ ---
    ai_provider: str = field(default_factory=lambda: os.environ.get("AI_PROVIDER", "openai").strip().lower())
    ai_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "AI_BASE_URL", "https://api.openai.com/v1"
        ).strip().rstrip("/")
    )
    ai_api_key: str = field(default_factory=lambda: os.environ.get("AI_API_KEY", "").strip())
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", "gpt-4o-mini").strip())
    ai_model_fast: str = field(default_factory=lambda: os.environ.get("AI_MODEL_FAST", "").strip())
    ai_timeout: int = field(default_factory=lambda: _int("AI_TIMEOUT", 90))
    ai_temperature: float = field(
        default_factory=lambda: float(os.environ.get("AI_TEMPERATURE", "0.3") or 0.3)
    )

    # --- Голос ---
    tts_enabled: bool = field(default_factory=lambda: _bool("TTS_ENABLED", True))
    tts_voice: str = field(
        default_factory=lambda: os.environ.get("TTS_VOICE", "sk-SK-LukasNeural").strip()
    )
    # Запасные голоса и источники: если основной недоступен — пробуем следующие.
    tts_fallback_voices: List[str] = field(
        default_factory=lambda: [
            v.strip()
            for v in os.environ.get(
                "TTS_FALLBACK_VOICES", "sk-SK-ViktoriaNeural,sk-SK-LukasNeural"
            ).split(",")
            if v.strip()
        ]
    )
    stt_enabled: bool = field(default_factory=lambda: _bool("STT_ENABLED", True))
    stt_model: str = field(default_factory=lambda: os.environ.get("STT_MODEL", "small").strip())

    # --- Прочее ---
    # Строгие гейты (урок открыт после 80% на предыдущем). По умолчанию выключено:
    # все уроки доступны сразу.
    strict_gating: bool = field(default_factory=lambda: _bool("STRICT_GATING", False))
    daily_minutes: int = field(default_factory=lambda: _int("DAILY_MINUTES", 30))
    reminder_time: str = field(default_factory=lambda: os.environ.get("REMINDER_TIME", "21:00").strip())
    reminder_tz: str = field(default_factory=lambda: os.environ.get("REMINDER_TZ", "Europe/Bratislava").strip())
    max_daily_tasks: int = field(default_factory=lambda: _int("MAX_DAILY_TASKS", 40))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").strip().upper())

    # --- Лицензии ---
    # Владелец (ADMIN_IDS) работает без ключа. Выключи, чтобы проверить
    # сценарий с ключом и на своём аккаунте.
    owner_bypass_license: bool = field(default_factory=lambda: _bool("OWNER_BYPASS_LICENSE", True))
    license_welcome: str = field(
        default_factory=lambda: os.environ.get(
            "LICENSE_WELCOME",
            "Этот бот — платный тренажёр словацкого. Доступ открывается по ключу.\n\n"
            "Введи ключ сюда. Он сработает один раз и привяжет доступ к твоему аккаунту навсегда.",
        ).strip()
    )

    # --- Режим запуска ---
    # polling — бот сам спрашивает Telegram (нужен постоянный процесс: ПК или VPS)
    # webhook — Telegram сам шлёт апдейты на твой URL (подходит для бесплатных
    #           веб-хостингов: PythonAnywhere, Render, Railway, Fly.io)
    mode: str = field(default_factory=lambda: os.environ.get("MODE", "polling").strip().lower())
    # Где живёт бот в чате: local — на этом ПК, cloud — в GitHub Actions.
    # В режиме cloud автозапуск на ПК поднимает только Mini App, а чат-бот
    # работает в облаке (чтобы два экземпляра не дрались за один токен).
    bot_mode: str = field(default_factory=lambda: os.environ.get("BOT_MODE", "local").strip().lower())
    webhook_base_url: str = field(
        default_factory=lambda: os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    )
    webhook_secret: str = field(
        default_factory=lambda: os.environ.get("WEBHOOK_SECRET", "").strip()
    )
    webhook_port: int = field(default_factory=lambda: _int("WEBHOOK_PORT", 8000))
    # Сколько секунд работать в режиме polling и выйти. 0 = работать вечно.
    # Нужно для GitHub Actions: каждый запуск живёт несколько минут и выключается.
    run_seconds: int = field(default_factory=lambda: _int("RUN_SECONDS", 0))

    # --- Mini App ---
    # Базовый публичный HTTPS-адрес, где живёт приложение.
    # Примеры: https://xxx.trycloudflare.com или https://username.pythonanywhere.com
    webapp_base_url: str = field(
        default_factory=lambda: os.environ.get("WEBAPP_BASE_URL", "").strip().rstrip("/")
    )
    # Постоянный адрес на GitHub Pages (если он включён).
    # Тогда кнопка в боте ведёт на Pages, а адрес API берётся из miniapp/config.json.
    pages_url: str = field(
        default_factory=lambda: os.environ.get("PAGES_URL", "").strip().rstrip("/")
    )
    # Режим разработки: разрешает заходить в приложение из обычного браузера
    app_dev: bool = field(default_factory=lambda: _bool("APP_DEV", False))
    dev_telegram_id: int = field(default_factory=lambda: _int("DEV_TELEGRAM_ID", 8636653095))

    @property
    def webhook_url(self) -> str:
        """Полный URL вебхука: база + путь + секрет."""
        if not self.webhook_base_url:
            return ""
        return "%s/bot/%s" % (self.webhook_base_url, self.webhook_secret or "changeme")

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "off" and bool(self.ai_api_key)

    @property
    def content_path(self) -> Path:
        return self.data_dir / "content.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


CONFIG = Config()
