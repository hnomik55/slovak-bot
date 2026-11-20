"""Сборка единого контента для бота из папки D:\\Slovakia.

Источники (правда одна — человек правит их, бот только читает):
  app/slovencina.html  -> уроки, правила, задания (choice/type/build/match)
  slovar/slova-*.txt   -> словари A1/A2/B1 (TSV: словацкий <TAB> русский)
  урок-NN.md|.txt      -> конспекты уроков (markdown)
  pisma/*.md           -> письма: словацкий оригинал + перевод + новые слова
  navyky/*.txt         -> методички по навыкам (чтение/говорение/аудирование/письмо)
  progress.md          -> "слабые места" -> приоритет ошибок

Результат: data/content.json + data/vocab.tsv (для Anki).

Запуск:  python tools/build_content.py [--source D:\\Slovakia] [--out data]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:  # при запуске файлом и при импорте как tools.build_content
    from levels import LEVEL_RANK, build_level_courses
except ImportError:  # pragma: no cover
    from tools.levels import LEVEL_RANK, build_level_courses  # type: ignore

DEFAULT_SOURCE = Path(r"D:\Slovakia")
DEFAULT_OUT = ROOT / "data"

TASK_KINDS = ("choice", "type", "build", "match")


# --------------------------------------------------------------------------- #
# HTML-тренажёр -> уроки
# --------------------------------------------------------------------------- #
def extract_units(html_path: Path) -> List[Dict[str, Any]]:
    """Достаёт UNITS из HTML через node (в JS валидный литерал с одинарными кавычками)."""
    if not html_path.exists():
        return []
    script = HERE / "extract_units.mjs"
    proc = subprocess.run(
        ["node", str(script), str(html_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        print("[warn] не удалось распарсить HTML-тренажёр: " + proc.stderr.strip(), file=sys.stderr)
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print("[warn] битый JSON из HTML: %s" % exc, file=sys.stderr)
        return []


def normalize_task(task: Dict[str, Any], lesson_id: str, index: int) -> Optional[Dict[str, Any]]:
    """Приводит задание к единой схеме, отбрасывая мусор."""
    kind = task.get("t")
    if kind not in TASK_KINDS:
        return None

    out: Dict[str, Any] = {"kind": kind, "lesson": lesson_id, "i": index}

    if kind == "choice":
        options = list(task.get("o") or [])
        if len(options) < 2:
            return None
        # В тренажёре правильный вариант всегда первый в массиве (при показе — shuffle),
        # явного поля с индексом нет. Приводим к индексу и помечаем, что порядок надо тасовать.
        answer = task.get("a")
        if answer is None:
            answer_idx = 0
        elif isinstance(answer, int):
            answer_idx = answer
        else:
            answer_idx = options.index(answer)
        out.update(
            {
                "prompt": task.get("q", ""),
                "options": options,
                "answer": answer_idx,
                "shuffle": True,
                "explain": task.get("x"),
            }
        )

    elif kind == "type":
        answers = task.get("a")
        if isinstance(answers, str):
            answers = [answers]
        if not answers:
            return None
        out.update(
            {
                "prompt": task.get("q", ""),
                "sk": task.get("sk", ""),
                "answers": [str(a) for a in answers],
                "explain": task.get("x"),
            }
        )

    elif kind == "build":
        words = list(task.get("w") or [])
        answer = task.get("a")
        if not words or not answer:
            return None
        out.update(
            {
                "prompt": task.get("q", ""),
                "words": words,
                "answer": answer if isinstance(answer, str) else " ".join(answer),
                "explain": task.get("x"),
            }
        )

    elif kind == "match":
        pairs = task.get("p") or []
        if len(pairs) < 2:
            return None
        out.update(
            {
                "prompt": task.get("q", ""),
                "pairs": [[str(a), str(b)] for a, b in pairs],
                "explain": task.get("x"),
            }
        )

    return out


def build_lessons(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """units -> плоский список уроков с заданиями (id, title, sub, rule, tasks)."""
    lessons: List[Dict[str, Any]] = []
    for unit in units:
        unit_no = unit.get("n")
        unit_title = unit.get("title", "")
        for raw in unit.get("lessons") or []:
            tasks = []
            for idx, task in enumerate(raw.get("tasks") or []):
                norm = normalize_task(task, raw.get("id", ""), idx)
                if norm:
                    tasks.append(norm)
            lessons.append(
                {
                    "id": raw.get("id"),
                    "unit": unit_no,
                    "unit_title": unit_title,
                    "title": raw.get("title", ""),
                    "sub": raw.get("sub", ""),
                    "rule": raw.get("rule"),
                    "tasks": tasks,
                }
            )
    return lessons


# --------------------------------------------------------------------------- #
# Словари TSV
# --------------------------------------------------------------------------- #
def parse_vocab(path: Path, level: str) -> List[Dict[str, Any]]:
    """slova-A1.txt -> [{sk, ru, group, alts}]"""
    entries: List[Dict[str, Any]] = []
    seen = set()
    if not path.exists():
        return entries

    group = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            head = line.lstrip("# ").strip()
            m = re.match(r"^=+\s*(.+?)\s*=+$", head)
            if m:
                group = m.group(1)
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sk = parts[0].strip()
        ru = parts[1].strip()
        if not sk or not ru:
            continue
        key = (level, sk.lower())
        if key in seen:
            continue  # одно слово может стоять в двух разделах
        seen.add(key)
        entries.append(
            {
                "level": level,
                "group": group,
                "sk": sk,
                "ru": ru,
                "sk_alts": [x.strip() for x in sk.split("/") if x.strip()],
                "ru_alts": [x.strip() for x in ru.split("/") if x.strip()],
            }
        )
    return entries


# --------------------------------------------------------------------------- #
# Конспекты уроков
# --------------------------------------------------------------------------- #
def parse_lesson_docs(source: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for path in sorted(source.glob("урок-*")):
        text = path.read_text(encoding="utf-8")
        title = ""
        for line in text.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break
        if not title:
            title = path.stem
        # Убираем служебные поля с путями к тренажёру
        body = text
        docs.append(
            {
                "id": path.stem,
                "file": path.name,
                "title": title,
                "text": body,
            }
        )
    return docs


# --------------------------------------------------------------------------- #
# Письма (pisma)
# --------------------------------------------------------------------------- #
def parse_writing(source: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted((source / "pisma").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = ""
        for line in text.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break
        recipient = ""
        subject = ""
        m = re.search(r"\*\*Кому:\*\*\s*(.+)", text)
        if m:
            recipient = m.group(1).strip()
        m = re.search(r"\*\*Тема[^:]*:\*\*\s*(.+)", text)
        if m:
            subject = m.group(1).strip()

        # Оригинал: между первым '---' и '## Перевод'
        letter = ""
        m = re.search(r"---\s*\n(.*?)\n---\s*\n(.*?)(?:\n## |\Z)", text, re.S)
        if m:
            letter = m.group(2).strip()
        else:
            letter = text

        # Перевод
        translation = ""
        m = re.search(r"##\s*Перевод.*?\n(.*?)(?:\n## |\Z)", text, re.S)
        if m:
            translation = m.group(1).strip()

        # Новые слова
        new_words: List[List[str]] = []
        m = re.search(r"##\s*Новые слова.*?\n(\|.*)", text, re.S)
        if m:
            for row in m.group(1).splitlines():
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                if len(cells) >= 2 and cells[0] and cells[1] and cells[0] not in ("Словацкий", "---"):
                    if set(cells[0]) <= set("-: "):
                        continue
                    new_words.append([cells[0], cells[1]])

        out.append(
            {
                "id": path.stem,
                "title": title,
                "recipient": recipient,
                "subject": subject,
                "letter": letter,
                "translation": translation,
                "new_words": new_words,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Методички по навыкам (navyky)
# --------------------------------------------------------------------------- #
SKILL_TITLES = {
    "1-reading": ("Чтение", "čítanie"),
    "2-speaking": ("Говорение", "hovorenie"),
    "3-listening": ("Аудирование", "počúvanie"),
    "4-writing": ("Письмо", "písanie"),
}


def parse_skills(source: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted((source / "navyky").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        ru, sk = SKILL_TITLES.get(path.stem, (path.stem, path.stem))
        out.append({"id": path.stem, "title_ru": ru, "title_sk": sk, "text": text})
    return out


# --------------------------------------------------------------------------- #
# Слабые места из progress.md
# --------------------------------------------------------------------------- #
def parse_weak_spots(source: Path) -> List[Dict[str, str]]:
    path = source / "progress.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"##\s*Слабые места\s*\n(.*?)(?:\n## |\Z)", text, re.S)
    if not m:
        return []
    spots: List[Dict[str, str]] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        item = line.lstrip("- ").strip()
        if not item:
            continue
        # Первое слово-маркер -> тег; остальное -> описание
        tag = re.sub(r"[^a-zA-Zа-яА-Я_]+", "_", item.split(":")[0].split("(")[0].strip())[:32]
        spots.append({"tag": tag or "misc", "text": item})
    return spots


# --------------------------------------------------------------------------- #
# Сборка
# --------------------------------------------------------------------------- #
def build(source: Path, out: Path) -> Dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)

    units = extract_units(source / "app" / "slovencina.html")
    # Основной курс из HTML-тренажёра — уровень A2.
    for unit in units:
        unit["level"] = "A2"
        unit["num"] = unit.get("n")
    lessons = build_lessons(units)
    for lesson in lessons:
        lesson["level"] = "A2"

    # Курсы A1, B1, B2 и пустые юниты A2 (8–10) собираются из словарей.
    level_units, level_lessons = build_level_courses(source)
    units = units + level_units
    lessons = lessons + level_lessons

    # Юниты с одинаковым n (A2 8–10: каркас из HTML + план из словаря) сливаем:
    # заголовок и описание берём из плана, уроки — из общего списка ниже.
    merged: Dict[str, Dict[str, Any]] = {}
    for unit in units:
        key = str(unit.get("n"))
        if key in merged:
            merged[key]["title"] = unit.get("title") or merged[key].get("title", "")
            merged[key]["desc"] = unit.get("desc") or merged[key].get("desc", "")
            merged[key]["level"] = unit.get("level") or merged[key].get("level", "A2")
            merged[key]["num"] = unit.get("num") or merged[key].get("num")
        else:
            merged[key] = dict(unit)
    units = list(merged.values())

    # Списки уроков в юнитах собираем из самих уроков: так в пустые каркасы
    # A2 (8–10) попадают сгенерированные уроки, а не остаются пустые юниты.
    by_unit: Dict[str, List[str]] = {}
    for lesson in lessons:
        by_unit.setdefault(str(lesson.get("unit")), []).append(lesson["id"])
    for unit in units:
        ids = by_unit.get(str(unit.get("n")))
        if ids:
            unit["lessons"] = ids

    units.sort(key=lambda u: (LEVEL_RANK.get(u.get("level", "A2"), 99), u.get("num") or u.get("n") or 0))
    lessons.sort(
        key=lambda l: (
            LEVEL_RANK.get(l.get("level", "A2"), 99),
            str(l.get("unit")),
            str(l.get("id")),
        )
    )

    vocab: List[Dict[str, Any]] = []
    for level in ("A1", "A2", "B1", "B2"):
        vocab.extend(parse_vocab(source / "slovar" / ("slova-%s.txt" % level), level))

    content = {
        "meta": {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": str(source),
            "units": len(units),
            "lessons": len(lessons),
            "tasks": sum(len(l["tasks"]) for l in lessons),
            "vocab": len(vocab),
        },
        "units": [
            {
                "n": u.get("n"),
                "num": u.get("num") or u.get("n"),
                "level": u.get("level", "A2"),
                "title": u.get("title", ""),
                "desc": u.get("desc", ""),
                "lessons": [
                    l["id"] if isinstance(l, dict) else l for l in (u.get("lessons") or [])
                ],
            }
            for u in units
        ],
        "lessons": lessons,
        "lesson_docs": parse_lesson_docs(source),
        "vocab": vocab,
        "writing": parse_writing(source),
        "skills": parse_skills(source),
        "weak_spots": parse_weak_spots(source),
    }

    (out / "content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # Anki-совместимый TSV всех слов
    with (out / "vocab.tsv").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("#separator:tab\n#html:false\n# Словацкий\tРусский\n")
        for entry in vocab:
            fh.write("%s\t%s\n" % (entry["sk"], entry["ru"]))

    return content


def main() -> int:
    ap = argparse.ArgumentParser(description="Собрать контент для Telegram-бота")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="корень с контентом")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="куда сложить content.json")
    args = ap.parse_args()

    source = Path(args.source)
    if not source.exists():
        print("нет папки с контентом: %s" % source, file=sys.stderr)
        return 1

    content = build(source, Path(args.out))
    meta = content["meta"]
    print("units=%(units)s lessons=%(lessons)s tasks=%(tasks)s vocab=%(vocab)s" % meta)
    print("weak_spots=%d writing=%d skills=%d lesson_docs=%d" % (
        len(content["weak_spots"]),
        len(content["writing"]),
        len(content["skills"]),
        len(content["lesson_docs"]),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
