"""Проверка запуска без Telegram: инициализация БД, контент, планировщик.

Запуск: python tools/dry_run.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="slovak_dry_"))
os.environ.setdefault("BOT_TOKEN", "123456789:AAEhBOweik6ad9r_QXvcS7SFvlG1234567890")
os.environ.setdefault("DB_PATH", str(TMP / "dry.db"))
os.environ.setdefault("AI_PROVIDER", "off")

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

from aiogram.client.bot import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402

import bot as bot_module  # noqa: E402
from app import content as content_mod  # noqa: E402
from app import db  # noqa: E402
from app.services.reminders import start_scheduler  # noqa: E402


async def main() -> int:
    tg_bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode="HTML"),
    )

    print("\n--- инициализация ---")
    await bot_module.on_startup(tg_bot)

    print("\n--- проверки ---")
    stats = content_mod.CONTENT.stats()
    assert stats["lessons"] > 0, "нет уроков"
    assert stats["vocab"] > 0, "нет слов"
    rows = db.query("SELECT COUNT(*) AS n FROM vocab")
    assert rows[0]["n"] == stats["vocab"], "словарь не залился в БД"
    print("контент и БД: ок (%d слов в БД)" % rows[0]["n"])

    # планировщик напоминаний
    scheduler = start_scheduler(tg_bot)
    print("планировщик: %s" % ("ок" if scheduler else "не запустился (нет apscheduler)"))
    if scheduler:
        scheduler.shutdown(wait=False)

    # ручной прогон напоминания (ничего не отправит — юзеров нет)
    from app.services.reminders import tick

    await tick(tg_bot)
    print("напоминания: отработали без ошибок")

    await tg_bot.session.close()
    print("\nЗапуск в порядке.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
