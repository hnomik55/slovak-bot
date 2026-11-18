"""Проверка озвучки: голоса существуют, аудио синтезируется и кэшируется.

Запуск: python tests/test_tts.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="slovak_tts_"))
os.environ["DATA_DIR"] = str(TMP)

from app.config import CONFIG  # noqa: E402
from app.services import tts as tts_module  # noqa: E402

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s %s" % (name, detail))


async def main() -> int:
    tts = tts_module.TTS
    print("\n== Голоса ==")
    print("   настроенный: %s" % CONFIG.tts_voice)
    print("   запасные:    %s" % ", ".join(CONFIG.tts_fallback_voices))
    check("голос по умолчанию существует", CONFIG.tts_voice in tts_module.TTS.KNOWN_SK_VOICES, CONFIG.tts_voice)
    check(
        "все запасные голоса существуют",
        all(v in tts_module.TTS.KNOWN_SK_VOICES for v in CONFIG.tts_fallback_voices),
        str(CONFIG.tts_fallback_voices),
    )

    print("\n== Синтез ==")
    text = "Dobrý deň, volám sa Peter."
    path = await tts.speech(text)
    check("аудио получено", path is not None and path.exists(), "path=%s" % path)
    if path and path.exists():
        size = path.stat().st_size
        check("файл не пустой (>1 КБ)", size > 1000, "%d байт" % size)
        head = path.read_bytes()[:2]
        check("это mp3 (сигнатура)", head in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), str(head))

    print("\n== Кэш ==")
    path2 = await tts.speech(text)
    check("повтор отдаёт из кэша", path2 == path, "%s vs %s" % (path, path2))

    print("\n== Защита от плохих данных ==")
    check("пустой текст не озвучивается", await tts.speech("") is None)
    check("пробелы не озвучиваются", await tts.speech("   ") is None)

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
