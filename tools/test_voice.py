"""Отправляет тестовое голосовое сообщение в чат пользователя.

Проверяет весь путь целиком: синтез -> mp3 -> загрузка в Telegram -> доставка.
Запуск: python tools/test_voice.py [текст]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.types import FSInputFile  # noqa: E402

from app.config import CONFIG  # noqa: E402
from app.services.tts import TTS  # noqa: E402

TEXT = sys.argv[1] if len(sys.argv) > 1 else "Dobrý deň! Som Slovenčina. Toto je test hlasu."
USER_ID = 8636653095


async def main() -> int:
    path = await TTS.speech(TEXT)
    if not path:
        print("озвучка не получилась")
        return 1
    print("файл: %s (%d байт)" % (path.name, path.stat().st_size))

    bot = Bot(token=CONFIG.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        await bot.send_voice(
            chat_id=USER_ID,
            voice=FSInputFile(str(path)),
            caption="🔊 Тест озвучки: %s" % TEXT,
        )
        print("отправлено в чат %s" % USER_ID)
    finally:
        await bot.session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
