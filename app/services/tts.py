"""Озвучивание словацкого (TTS).

Два источника, пробуем по очереди:

1. edge-tts — нейросетевые голоса Microsoft (sk-SK-LukasNeural, sk-SK-ViktoriaNeural).
   Важно: имя голоса должно существовать, иначе edge-tts молча отдаёт пустой файл.
2. Google Translate TTS — запасной вариант, работает там, где Microsoft недоступен.

Аудио кэшируется по хэшу текста, чтобы не синтезировать одно и то же дважды.
Если не сработал ни один источник — бот не падает, а честно говорит об этом.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import List, Optional

from app.config import CONFIG

log = logging.getLogger("tts")

# Словацкие голоса edge-tts, которые реально существуют
KNOWN_SK_VOICES = ["sk-SK-LukasNeural", "sk-SK-ViktoriaNeural"]


class TTS:
    # Словацкие голоса edge-tts, которые реально существуют.
    # Если задать несуществующий голос, edge-tts молча отдаёт файл без звука.
    KNOWN_SK_VOICES = ["sk-SK-LukasNeural", "sk-SK-ViktoriaNeural"]

    def __init__(self) -> None:
        self.cache_dir = CONFIG.data_dir / "tts"
        self._edge = None
        self._check()

    def _check(self) -> None:
        try:
            import edge_tts  # noqa: F401

            self._edge = True
        except Exception:
            self._edge = False
            log.warning("edge-tts не установлен — будет использован запасной источник")

    @property
    def available(self) -> bool:
        return bool(CONFIG.tts_enabled)

    def _voices(self) -> List[str]:
        """Список голосов для проб: настроенный, потом запасные, потом известные."""
        out: List[str] = []
        for voice in [CONFIG.tts_voice] + list(CONFIG.tts_fallback_voices) + KNOWN_SK_VOICES:
            if voice and voice not in out:
                out.append(voice)
        return out

    def _cache_path(self, text: str, voice: str) -> Path:
        key = hashlib.sha1(("%s|%s" % (voice, text)).encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / ("%s.mp3" % key)

    async def _edge_speech(self, text: str, voice: str) -> Optional[Path]:
        path = self._cache_path(text, voice)
        if path.exists() and path.stat().st_size > 1000:
            return path
        if not self._edge:
            return None
        try:
            import edge_tts

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            communicate = edge_tts.Communicate(text, voice)
            tmp = path.with_suffix(".tmp.mp3")
            await communicate.save(str(tmp))
            # edge-tts при несуществующем голосе создаёт файл без звука
            if tmp.exists() and tmp.stat().st_size > 1000:
                tmp.replace(path)
                return path
            if tmp.exists():
                tmp.unlink()
        except Exception as exc:
            log.info("edge-tts не сработал (%s): %s", voice, exc)
        return None

    async def _google_speech(self, text: str) -> Optional[Path]:
        path = self._cache_path(text, "google")
        if path.exists() and path.stat().st_size > 1000:
            return path
        try:
            import httpx

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
                response = await client.get(
                    "https://translate.google.com/translate_tts",
                    params={"ie": "UTF-8", "client": "tw-ob", "tl": "sk", "q": text},
                )
            if response.status_code == 200 and len(response.content) > 1000:
                path.write_bytes(response.content)
                return path
        except Exception as exc:
            log.info("Google TTS не сработал: %s", exc)
        return None

    async def speech(self, text: str, voice: Optional[str] = None) -> Optional[Path]:
        """Возвращает путь к mp3 с озвучкой или None."""
        if not self.available or not (text or "").strip():
            return None
        text = text.strip()

        if voice:
            result = await self._edge_speech(text, voice)
            if result:
                return result

        for candidate in self._voices():
            result = await self._edge_speech(text, candidate)
            if result:
                return result

        return await self._google_speech(text)


TTS = TTS()
