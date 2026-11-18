"""Загрузчик контента.

Единый источник истины — data/content.json, который собирается из вашей папки
D:\\Slovakia скриптом tools/build_content.py. Ничего не дублируется в коде:
бот не хранит «свой» список слов и уроков, а читает ваш.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app import db
from app.config import CONFIG


class Content:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
        self.lessons: List[Dict[str, Any]] = []
        self.units: List[Dict[str, Any]] = []
        self.lesson_docs: List[Dict[str, Any]] = []
        self.vocab: List[Dict[str, Any]] = []
        self.writing: List[Dict[str, Any]] = []
        self.skills: List[Dict[str, Any]] = []
        self.weak_spots: List[Dict[str, str]] = []
        self.loaded_at: str = ""

    # ------------------------------------------------------------------ #
    def load(self, force: bool = False) -> "Content":
        path = CONFIG.content_path
        if not force and self.data:
            return self
        if not path.exists():
            self.data = {}
            return self
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.data = raw
        self.units = raw.get("units") or []
        self.lessons = raw.get("lessons") or []
        self.lesson_docs = raw.get("lesson_docs") or []
        self.vocab = raw.get("vocab") or []
        self.writing = raw.get("writing") or []
        self.skills = raw.get("skills") or []
        self.weak_spots = raw.get("weak_spots") or []
        self.loaded_at = (raw.get("meta") or {}).get("built_at", "")
        return self

    def stats(self) -> Dict[str, Any]:
        return {
            "units": len(self.units),
            "lessons": len(self.lessons),
            "tasks": sum(len(l.get("tasks") or []) for l in self.lessons),
            "vocab": len(self.vocab),
            "writing": len(self.writing),
            "built_at": self.loaded_at,
        }

    # ------------------------------------------------------------------ #
    def lesson(self, lesson_id: str) -> Optional[Dict[str, Any]]:
        for lesson in self.lessons:
            if lesson.get("id") == lesson_id:
                return lesson
        return None

    def lesson_doc(self, doc_id: str) -> Optional[Dict[str, Any]]:
        for doc in self.lesson_docs:
            if doc.get("id") == doc_id:
                return doc
        return None

    def lesson_order(self) -> List[str]:
        return [l["id"] for l in self.lessons if l.get("id")]

    def unit_of(self, lesson_id: str) -> Optional[Dict[str, Any]]:
        for unit in self.units:
            if lesson_id in (unit.get("lessons") or []):
                return unit
        return None

    def vocab_by_level(self, level: str) -> List[Dict[str, Any]]:
        return [v for v in self.vocab if v.get("level") == level]

    def vocab_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.vocab:
            counts[entry.get("level", "?")] = counts.get(entry.get("level", "?"), 0) + 1
        return counts

    def writing_prompt(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        for prompt in self.writing:
            if prompt.get("id") == prompt_id:
                return prompt
        return None

    def skill(self, skill_id: str) -> Optional[Dict[str, Any]]:
        for skill in self.skills:
            if skill.get("id") == skill_id:
                return skill
        return None


CONTENT = Content()


# --------------------------------------------------------------------------- #
# ИИ-уроки (сгенерированные и сохранённые в БД)
# --------------------------------------------------------------------------- #
def generated_lessons(user_id: int) -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT lesson_id, unit, title, payload FROM generated WHERE user_id = ? ORDER BY id",
        (user_id,),
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        out.append(
            {
                "id": row["lesson_id"],
                "unit": row["unit"],
                "title": row["title"],
                "sub": payload.get("sub", ""),
                "rule": payload.get("rule"),
                "tasks": payload.get("tasks") or [],
                "generated": True,
            }
        )
    return out


def all_lessons(user_id: int) -> List[Dict[str, Any]]:
    """Базовые уроки из контента + сгенерированные ИИ."""
    lessons = list(CONTENT.lessons) + generated_lessons(user_id)
    order = {lid: i for i, lid in enumerate(CONTENT.lesson_order())}
    lessons.sort(key=lambda l: (order.get(l["id"], 10_000), l["id"]))
    return lessons


def save_generated_lesson(
    user_id: int, lesson_id: str, unit: int, title: str, payload: Dict[str, Any]
) -> None:
    db.execute(
        """INSERT INTO generated(user_id, lesson_id, unit, title, payload, created_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT DO NOTHING""",
        (user_id, lesson_id, unit, title, json.dumps(payload, ensure_ascii=False), db.now()),
    )


# --------------------------------------------------------------------------- #
# Прогресс и разблокировка
# --------------------------------------------------------------------------- #
MASTERY_THRESHOLD = 0.8


def mastery(user_id: int, lesson_id: str) -> float:
    row = db.query_one(
        "SELECT best_score FROM lesson_progress WHERE user_id = ? AND lesson_id = ?",
        (user_id, lesson_id),
    )
    if not row:
        return 0.0
    return float(row.get("best_score") or 0.0)


def lesson_done(user_id: int, lesson_id: str) -> bool:
    row = db.query_one(
        "SELECT done FROM lesson_progress WHERE user_id = ? AND lesson_id = ?",
        (user_id, lesson_id),
    )
    return bool(row and row.get("done"))


def is_unlocked(user_id: int, lesson_id: str, lessons: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Доступен ли урок.

    По умолчанию доступны все уроки — учиться можно с любого места.
    Строгий режим (урок открывается после 80% на предыдущем) включается
    переменной STRICT_GATING=1 в .env.
    """
    lessons = lessons or all_lessons(user_id)
    ids = [l["id"] for l in lessons if l.get("id")]
    if lesson_id not in ids:
        return False
    if not CONFIG.strict_gating:
        return True
    idx = ids.index(lesson_id)
    if idx == 0:
        return True
    prev = ids[idx - 1]
    if lesson_done(user_id, prev):
        return mastery(user_id, prev) >= MASTERY_THRESHOLD
    return False


def next_lesson(user_id: int) -> Optional[Dict[str, Any]]:
    lessons = all_lessons(user_id)
    for lesson in lessons:
        if not lesson_done(user_id, lesson["id"]) and is_unlocked(user_id, lesson["id"], lessons):
            return lesson
    return None


def completed_count(user_id: int) -> int:
    rows = db.query(
        "SELECT lesson_id FROM lesson_progress WHERE user_id = ? AND done = 1", (user_id,)
    )
    return len(rows)
