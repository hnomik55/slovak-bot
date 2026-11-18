"""Интервальное повторение (SRS) для словаря.

Упрощённый SM-2: качество ответа 0..3 -> новый интервал в днях.
Отличия от классического SM-2: интервалы короче (1/3/7/16/35), потому что
цель — A2 за 10 недель, а не «навсегда».

  0 — не знаю      -> интервал 1 день, lapses+1, ease -0.2
  1 — с трудом      -> интервал *1.2, ease -0.15
  2 — нормально    -> 1, 3, 7, 16, 35 ... * ease
  3 — легко        -> интервал * ease * 1.3, ease +0.15
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

MIN_EASE = 1.3
MAX_EASE = 3.0
STEPS = (1, 3, 7, 16, 35)

QUALITY_TEXT = {
    0: "Не знаю",
    1: "С трудом",
    2: "Нормально",
    3: "Легко",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def next_interval(interval: int, reps: int, ease: float, quality: int) -> int:
    """Новый интервал в днях."""
    if quality <= 0:
        return 1
    if interval <= 0:
        return 1  # первое успешное повторение — завтра
    if quality == 1:
        return max(1, int(round(max(interval, 1) * 1.2)))
    if quality == 2:
        index = min(max(reps, 0), len(STEPS) - 1)
        if reps >= len(STEPS):
            return max(1, int(round(STEPS[-1] * ease)))
        return max(1, STEPS[index])
    # quality == 3 — легко: тянем интервал вверх
    return max(2, int(round(max(interval, 1) * ease * 1.3)))


def review(card: Optional[Dict[str, Any]], quality: int) -> Dict[str, Any]:
    """Обновляет карточку и возвращает новое состояние."""
    card = dict(card or {})
    ease = float(card.get("ease") or 2.5)
    interval = int(card.get("interval") or 0)
    reps = int(card.get("reps") or 0)
    lapses = int(card.get("lapses") or 0)

    quality = max(0, min(3, quality))

    if quality == 0:
        lapses += 1
        ease = _clamp(ease - 0.2, MIN_EASE, MAX_EASE)
        reps = 0
        interval = 1
        state = "learning"
    elif quality == 1:
        ease = _clamp(ease - 0.15, MIN_EASE, MAX_EASE)
        reps = max(1, reps)
        interval = next_interval(interval, reps, ease, 1)
        state = "learning"
    else:
        ease = _clamp(ease + (0.15 if quality == 3 else 0.0), MIN_EASE, MAX_EASE)
        reps += 1
        interval = next_interval(interval, reps, ease, quality)
        state = "review" if reps >= 2 else "learning"

    due = (date.today() + timedelta(days=interval)).isoformat()
    return {
        "ease": round(ease, 3),
        "interval": interval,
        "reps": reps,
        "lapses": lapses,
        "due": due,
        "state": state,
        "last_result": QUALITY_TEXT[quality],
    }
