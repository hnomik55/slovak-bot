"""Точка входа бота.

Два режима (переключается переменной MODE в .env):

  polling  — бот сам спрашивает Telegram. Нужен постоянно живущий процесс:
             твой ПК (автозапуск уже настроен) или VPS. По умолчанию.

  webhook  — Telegram сам присылает апдейты на твой URL. Подходит для
             бесплатных веб-хостингов (PythonAnywhere, Render, Railway, Fly.io):
             процесс живёт только пока есть запросы.

Запуск в режиме polling:
    python bot.py

Запуск в режиме webhook (локально, для проверки):
    MODE=webhook WEBHOOK_BASE_URL=https://example.com python bot.py

Ключи — в .env: BOT_TOKEN (обязательно), WEBHOOK_BASE_URL и WEBHOOK_SECRET.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from app.telegram_session import ProxyAwareSession
from aiogram.exceptions import (
    TelegramConflictError,
    TelegramNetworkError,
    TelegramServerError,
)
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import CONFIG
from app.handlers import (
    admin,
    lessons,
    progress,
    quiz,
    settings,
    skills,
    speaking,
    start,
    vocab,
    writing,
)
from app.services.ai import AI
from app.services.reminders import start_scheduler
from app.services.tts import TTS

logging.basicConfig(
    level=getattr(logging, CONFIG.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


def build_dispatcher() -> Dispatcher:
    """Собирает роутеры. Порядок важен: первый подходящий забирает апдейт."""
    dp = Dispatcher(storage=MemoryStorage())

    # Шлюз лицензии: без ключа доступно только введение ключа
    from app.middleware import LicenseGate

    dp.message.outer_middleware(LicenseGate())
    dp.callback_query.outer_middleware(LicenseGate())

    dp.include_router(start.router)
    dp.include_router(lessons.router)
    dp.include_router(vocab.router)
    dp.include_router(skills.router)
    dp.include_router(writing.router)
    dp.include_router(speaking.router)
    dp.include_router(quiz.router)
    dp.include_router(progress.router)
    dp.include_router(settings.router)
    dp.include_router(admin.router)
    return dp


async def startup(bot: Bot) -> None:
    """Инициализация БД и контента. Вызывается в обоих режимах."""
    from app import content as content_mod
    from app import db

    db.init_db()
    if not CONFIG.content_path.exists():
        log.warning("content.json не найден — запусти python tools/build_content.py")
    else:
        content_mod.CONTENT.load(force=True)
        stats = content_mod.CONTENT.stats()
        log.info(
            "контент: %d уроков, %d заданий, %d слов",
            stats["lessons"],
            stats["tasks"],
            stats["vocab"],
        )
        db.upsert_vocab(content_mod.CONTENT.vocab)

    log.info("ИИ: %s", "включён (%s)" % CONFIG.ai_model if CONFIG.ai_enabled else "выключен")
    log.info("озвучка: %s", "доступна" if TTS.available else "недоступна")
    log.info("админы: %s", CONFIG.admin_ids)


async def _watchdog(seconds: int) -> None:
    """Страховка: если бот не завершился за отведённое время — убиваем процесс.

    Нужна для GitHub Actions: зависший процесс съедает минуты и не даёт
    workflow дойти до шага сохранения состояния.
    """
    await asyncio.sleep(seconds)
    log.error("watchdog: процесс не завершился за %d с — выхожу жёстко", seconds)
    os._exit(0)


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    scheduler = start_scheduler(bot)
    try:
        await startup(bot)
        # Бот мог стоять выключенным — догоняем пропущенное напоминание
        try:
            from app.services.reminders import catch_up

            await catch_up(bot)
        except Exception as exc:
            log.warning("не удалось разослать догоняющие напоминания: %s", exc)

        while True:
            try:
                if CONFIG.run_seconds > 0:
                    # Режим "пожил несколько минут и выключился" — для GitHub Actions.
                    # Telegram хранит непрочитанные апдейты 24 часа, поэтому накопленное
                    # не теряется: сообщения придут в следующем запуске.
                    log.info("работаю %d секунд, потом выключусь", CONFIG.run_seconds)
                    watchdog = asyncio.create_task(_watchdog(CONFIG.run_seconds + 90))
                    polling = asyncio.create_task(dp.start_polling(bot))
                    try:
                        await asyncio.wait_for(asyncio.shield(polling), timeout=CONFIG.run_seconds)
                    except asyncio.TimeoutError:
                        log.info("время вышло, останавливаюсь")
                        polling.cancel()
                        try:
                            await asyncio.wait_for(polling, timeout=15)
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            pass
                    finally:
                        watchdog.cancel()
                    if not polling.done():
                        # процесс не завершился — выходим жёстко, иначе workflow зависнет
                        log.warning("завершаю процесс принудительно")
                        await AI.close()
                        os._exit(0)
                    return
                await dp.start_polling(bot)
                return
            except TelegramConflictError:
                # Токен держит другой экземпляр (например, облачный в Actions).
                # Не ругаемся и не выходим — подождём и перехватим токен.
                log.warning(
                    "токен занят другим экземпляром — жду 60 секунд и пробую снова"
                )
                await asyncio.sleep(60)
                continue
            except (TelegramServerError, TelegramNetworkError) as exc:
                log.warning("сбой связи с Telegram (%s) — перезапускаю через 10 секунд", exc)
                await asyncio.sleep(10)
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
        await AI.close()


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    """Режим вебхука: поднимаем Flask-приложение и говорим Telegram наш URL."""
    from app.webhook_app import create_app

    await startup(bot)
    if CONFIG.webhook_url:
        await bot.set_webhook(CONFIG.webhook_url, secret_token=CONFIG.webhook_secret or None)
        log.info("вебхук установлен: %s", CONFIG.webhook_url)
    else:
        log.warning("WEBHOOK_BASE_URL не задан — Telegram не сможет достучаться")

    app = create_app(bot, dp)
    # На хостинге процесс поднимает gunicorn/uWSGI, локально — Flask сам
    app.run(host="0.0.0.0", port=CONFIG.webhook_port)


async def main() -> int:
    token = (CONFIG.bot_token or "").strip()
    if not token or "XXXXTOKENXXXX" in token or "xxxx" in token.lower():
        log.error(
            "BOT_TOKEN не задан.\n"
            "  1) Открой @BotFather в Telegram -> /newbot (или /token для существующего бота)\n"
            "  2) Скопируй токен в D:\\Slovakia\\bot\\.env -> BOT_TOKEN=...\n"
            "  3) Запусти python bot.py заново"
        )
        return 1

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode="HTML"),
        session=ProxyAwareSession(trust_env=CONFIG.use_system_proxy),
    )
    dp = build_dispatcher()

    if CONFIG.bot_mode == "cloud":
        # Чат-бот живёт в GitHub Actions. Локально поднимается только Mini App,
        # иначе два экземпляра будут драться за один токен.
        log.info(
            "режим cloud: чат-бот работает в GitHub Actions, локальный запуск отменён"
        )
        return 0

    if CONFIG.mode == "webhook":
        await run_webhook(bot, dp)
    else:
        await run_polling(bot, dp)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
