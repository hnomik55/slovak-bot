"""Озвучивание словацкого (TTS).

edge-tts — бесплатные нейросетевые голоса Microsoft, включая sk-SK (словацкий).
Аудио кэшируется по хэшу текста, чтобы не генерировать одно и то же дважды.
Если edge-tts недоступен — бот деградирует до текста, ничего не ломая.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from app.config import CONFIG

log = logging.getLogger("tts")


class TTS:
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
            log.warning("edge-tts не установлен — озвучка недоступна")

    @property
    def available(self) -> bool:
        return bool(CONFIG.tts_enabled and self._edge)

    def _cache_path(self, text: str, voice: str) -> Path:
        key = hashlib.sha1(("%s|%s" % (voice, text)).encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / ("%s.mp3" % key)

    async def speech(self, text: str, voice: Optional[str] = None) -> Optional[Path]:
        """Возвращает путь к mp3 с озвучкой или None."""
        if not self.available or not text.strip():
            return None
        voice = voice or CONFIG.tts_voice
        path = self._cache_path(text, voice)
        if path.exists() and path.stat().st_size > 100:
            return path

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            import edge_tts

            communicate = edge_tts.Communicate(text, voice)
            tmp = path.with_suffix(".tmp.mp3")
            await communicate.save(str(tmp))
            if tmp.exists() and tmp.stat().st_size > 100:
                tmp.replace(path)
                return path
        except Exception as exc:  # сеть, лимиты, сломанный голос
            log.warning("TTS не удался: %s", exc)
        return None


TTS = TTS()
