"""Вписать токен и id админа в .env, не трогая остальные настройки.

    python tools/set_token.py <BOT_TOKEN> [ADMIN_ID]

Пустое значение означает «не менять».
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def set_value(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(key + "="):
            lines[i] = "%s=%s" % (key, value)
            return "\n".join(lines) + "\n"
    lines.append("%s=%s" % (key, value))
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/set_token.py <BOT_TOKEN> [ADMIN_ID]")
        return 1
    token = sys.argv[1].strip()
    admin = sys.argv[2].strip() if len(sys.argv) > 2 else ""

    if not ENV_PATH.exists():
        print("нет файла .env — скопируй .env.example в .env")
        return 1

    text = ENV_PATH.read_text(encoding="utf-8")
    text = set_value(text, "BOT_TOKEN", token)
    if admin:
        text = set_value(text, "ADMIN_IDS", admin)
    with io.open(ENV_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    # показываем только факт записи, сам токен не печатаем
    for line in text.splitlines():
        if line.startswith("BOT_TOKEN="):
            value = line.split("=", 1)[1]
            print("BOT_TOKEN записан, длина %d, начало %s..." % (len(value), value[:8]))
        if line.startswith("ADMIN_IDS="):
            print("ADMIN_IDS =", line.split("=", 1)[1] or "(пусто)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
