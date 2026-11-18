"""Лексика: добавление новых слов в словарь и зачисление их в SRS ученика."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Tuple

from app import db


def add_words(level: str, words: Iterable[Tuple[str, str]], group: str = "из письма") -> List[int]:
    """Добавляет слова в vocab (если их ещё нет) и возвращает их id."""
    ids: List[int] = []
    for sk, ru in words:
        sk = (sk or "").strip()
        ru = (ru or "").strip()
        if not sk or not ru:
            continue
        row = db.query_one("SELECT id FROM vocab WHERE level = ? AND sk = ?", (level, sk))
        if row:
            ids.append(int(row["id"]))
            continue
        db.execute(
            """INSERT INTO vocab(level, group_name, sk, ru, sk_alts, ru_alts) VALUES(?,?,?,?,?,?)
               ON CONFLICT(level, sk) DO NOTHING""",
            (level, group, sk, ru, json.dumps([], ensure_ascii=False), json.dumps([], ensure_ascii=False)),
        )
        row = db.query_one("SELECT id FROM vocab WHERE level = ? AND sk = ?", (level, sk))
        if row:
            ids.append(int(row["id"]))
    return ids


def enroll(user_id: int, vocab_ids: Iterable[int]) -> int:
    """Добавляет слова в карточки ученика (state=new, due=сегодня)."""
    count = 0
    for vocab_id in vocab_ids:
        db.execute(
            """INSERT INTO user_words(user_id, vocab_id, due, state) VALUES(?,?,?, 'new')
               ON CONFLICT(user_id, vocab_id) DO NOTHING""",
            (user_id, vocab_id, db.today()),
        )
        count += 1
    return count


def search(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """Ищет слово в словаре ученика (и в общем словаре)."""
    rows = db.query(
        """SELECT v.sk, v.ru, uw.state FROM vocab v
           LEFT JOIN user_words uw ON uw.vocab_id = v.id AND uw.user_id = ?
           WHERE uw.vocab_id IS NOT NULL
           ORDER BY uw.due LIMIT ?""",
        (user_id, limit),
    )
    return rows
