"""Мини-конвертер markdown -> Telegram HTML.

Поддерживает: заголовки, **жирный**, *курсив*, `код`, списки, таблицы (превращаются
в строки «ячейка — ячейка»), ссылки. Экранирует HTML.
"""

from __future__ import annotations

import html
import re
from typing import List

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    return text


def _table_block(lines: List[str]) -> List[str]:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if all(set(c) <= set("-: ") for c in cells if c):
            continue  # разделитель
        rows.append(cells)

    out: List[str] = []
    for cells in rows:
        if len(cells) == 1:
            out.append(cells[0])
        else:
            out.append(" — ".join(cells))
    return out


def md_to_html(text: str, limit: int = 3500) -> str:
    """Конвертирует markdown-текст в HTML для send_message(parse_mode=HTML)."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Блок таблицы
        if line.strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            for row in _table_block(block):
                out.append(_inline(row))
            out.append("")
            continue

        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            out.append(("<b>" if level <= 2 else "<i>") + _inline(m.group(2)) + ("</b>" if level <= 2 else "</i>"))
            out.append("")
            i += 1
            continue

        if re.match(r"^\s*[-*]\s+", line):
            out.append("• " + _inline(re.sub(r"^\s*[-*]\s+", "", line)))
            i += 1
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            out.append(_inline(line.strip()))
            i += 1
            continue

        if line.strip() == "---":
            out.append("———")
            i += 1
            continue

        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            i += 1
            continue

        out.append(_inline(line))
        i += 1

    result = "\n".join(out).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    if len(result) > limit:
        result = result[:limit].rsplit("\n", 1)[0] + "\n…"
    return result
