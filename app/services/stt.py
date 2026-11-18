"""Распознавание речи (STT) — для говорения и проверки произношения.

faster-whisper локально: без API-ключей, без отправки голоса наружу.
Модель грузится лениво и в отдельном потоке (она тяжёлая), поэтому первый
запрос медленный — об этом честно предупреждаем в интерфейсе.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Tuple

from app.config import CONFIG

log = logging.getLogger("stt")


class STT:
    def __init__(self) -> None:
        self._model = None
        self._failed = False

    @property
    def available(self) -> bool:
        return bool(CONFIG.stt_enabled) and not self._failed

    def _load(self):
        if self._model is not None or self._failed:
            return self._model
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(CONFIG.stt_model, device="cpu", compute_type="int8")
        except Exception as exc:
            self._failed = True
            log.warning("STT недоступен: %s", exc)
            return None
        return self._model

    def _transcribe_sync(self, path: str, language: str) -> Tuple[str, float]:
        model = self._load()
        if model is None:
            return "", 0.0
        segments, info = model.transcribe(path, language=language, beam_size=5, vad_filter=True)
        parts = []
        probs = []
        for segment in segments:
            parts.append(segment.text)
            probs.append(getattr(segment, "avg_logprob", 0.0))
        text = " ".join(p.strip() for p in parts).strip()
        confidence = 0.0
        if probs:
            import math

            confidence = float(math.exp(sum(probs) / len(probs)))
        return text, confidence

    async def transcribe(self, path: Path, language: str = "sk") -> Tuple[str, float]:
        """Возвращает (текст, уверенность 0..1)."""
        if not self.available:
            return "", 0.0
        try:
            return await asyncio.to_thread(self._transcribe_sync, str(path), language)
        except Exception as exc:
            log.warning("STT ошибка: %s", exc)
            return "", 0.0


STT = STT()
