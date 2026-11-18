"""Хранилище: SQLite + thin-слой запросов.

Один файл БД, синхронный sqlite3 (запросы микросекундные, блокировать event loop
на миллисекунды — не страшно, зато нет лишних зависимостей).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.config import CONFIG

_LOCK = threading.Lock()

def _full_schema() -> str:
    return """
CREATE TABLE IF NOT EXISTS users (
    tg_id        INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    level        TEXT DEFAULT 'A1',
    goal_date    TEXT,
    created_at   TEXT,
    last_seen    TEXT,
    xp           INTEGER DEFAULT 0,
    streak       INTEGER DEFAULT 0,
    best_streak  INTEGER DEFAULT 0,
    last_day     TEXT,
    daily_minutes INTEGER DEFAULT 30,
    reminder_time TEXT DEFAULT '21:00',
    tts          INTEGER DEFAULT 1,
    voice        INTEGER DEFAULT 1,
    ai_mode      TEXT DEFAULT 'full',
    gen_enabled  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS vocab (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    level     TEXT,
    group_name TEXT,
    sk        TEXT,
    ru        TEXT,
    sk_alts   TEXT,
    ru_alts   TEXT,
    UNIQUE(level, sk)
);

CREATE TABLE IF NOT EXISTS user_words (
    user_id    INTEGER,
    vocab_id   INTEGER,
    ease       REAL DEFAULT 2.5,
    interval   INTEGER DEFAULT 0,
    due        TEXT,
    reps       INTEGER DEFAULT 0,
    lapses     INTEGER DEFAULT 0,
    state      TEXT DEFAULT 'new',
    last_result TEXT,
    PRIMARY KEY (user_id, vocab_id)
);

CREATE TABLE IF NOT EXISTS lesson_progress (
    user_id    INTEGER,
    lesson_id  TEXT,
    done       INTEGER DEFAULT 0,
    correct    INTEGER DEFAULT 0,
    total      INTEGER DEFAULT 0,
    best_score REAL DEFAULT 0,
    attempts   INTEGER DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (user_id, lesson_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    lesson_id  TEXT,
    task_i     INTEGER,
    kind       TEXT,
    given      TEXT,
    expected   TEXT,
    result     TEXT,
    tag        TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS error_tags (
    user_id INTEGER,
    tag     TEXT,
    count   INTEGER DEFAULT 0,
    last_at TEXT,
    PRIMARY KEY (user_id, tag)
);

CREATE TABLE IF NOT EXISTS daily_stats (
    user_id  INTEGER,
    day      TEXT,
    xp       INTEGER DEFAULT 0,
    tasks    INTEGER DEFAULT 0,
    correct  INTEGER DEFAULT 0,
    minutes  INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS sessions (
    user_id    INTEGER PRIMARY KEY,
    mode       TEXT,
    data       TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS writing (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    prompt_id  TEXT,
    text       TEXT,
    feedback   TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS generated (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    lesson_id  TEXT,
    unit       INTEGER,
    title      TEXT,
    payload    TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS licenses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT UNIQUE NOT NULL,
    days       INTEGER DEFAULT 0,
    note       TEXT DEFAULT '',
    batch      TEXT DEFAULT '',
    created_at TEXT,
    used_by    INTEGER,
    used_at    TEXT,
    revoked    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subscriptions (
    telegram_id   INTEGER PRIMARY KEY,
    license_id    INTEGER,
    plan          TEXT,
    activated_at  TEXT,
    expires_at    TEXT,
    status        TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_licenses_used ON licenses(used_by);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_user_words_due ON user_words(user_id, due);
CREATE INDEX IF NOT EXISTS idx_daily_stats_user ON daily_stats(user_id, day);
"""


def connect() -> sqlite3.Connection:
    CONFIG.ensure_dirs()
    con = sqlite3.connect(str(CONFIG.db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with _LOCK, connect() as con:
        con.executescript(_full_schema())
        # миграция: колонка дня последнего «пинка»
        columns = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "nudged_day" not in columns:
            con.execute("ALTER TABLE users ADD COLUMN nudged_day TEXT")
        con.commit()


def query(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    with _LOCK, connect() as con:
        rows = con.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Sequence[Any] = ()) -> None:
    with _LOCK, connect() as con:
        con.execute(sql, tuple(params))
        con.commit()


def executemany(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    with _LOCK, connect() as con:
        con.executemany(sql, [tuple(p) for p in seq])
        con.commit()


# --------------------------------------------------------------------------- #
# Вспомогательное
# --------------------------------------------------------------------------- #
def today() -> str:
    return date.today().isoformat()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_vocab(entries: List[Dict[str, Any]]) -> int:
    """Загружает словарь из content.json в таблицу vocab (id стабильный: UNIQUE(level, sk))."""
    rows = [
        (
            e["level"],
            e.get("group", ""),
            e["sk"],
            e["ru"],
            json.dumps(e.get("sk_alts", []), ensure_ascii=False),
            json.dumps(e.get("ru_alts", []), ensure_ascii=False),
        )
        for e in entries
    ]
    with _LOCK, connect() as con:
        con.executemany(
            """INSERT INTO vocab(level, group_name, sk, ru, sk_alts, ru_alts)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(level, sk) DO UPDATE SET
                   group_name=excluded.group_name,
                   ru=excluded.ru,
                   sk_alts=excluded.sk_alts,
                   ru_alts=excluded.ru_alts""",
            rows,
        )
        con.commit()
    return len(rows)


def get_user(tg_id: int) -> Optional[Dict[str, Any]]:
    return query_one("SELECT * FROM users WHERE tg_id = ?", (tg_id,))


def ensure_user(tg_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> Dict[str, Any]:
    user = get_user(tg_id)
    if user:
        execute(
            "UPDATE users SET username=?, first_name=?, last_seen=? WHERE tg_id=?",
            (username or user.get("username"), first_name or user.get("first_name"), now(), tg_id),
        )
        return get_user(tg_id) or user
    execute(
        """INSERT INTO users(tg_id, username, first_name, created_at, last_seen, level,
                            daily_minutes, reminder_time, tts, voice, ai_mode)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            tg_id,
            username,
            first_name,
            now(),
            now(),
            "A1",
            CONFIG.daily_minutes,
            CONFIG.reminder_time,
            1,
            1,
            "full",
        ),
    )
    return get_user(tg_id) or {}


def touch_day(tg_id: int, xp: int = 0, tasks: int = 0, correct: int = 0) -> None:
    """Обновляет дневную статистику и серию дней."""
    day = today()
    execute(
        """INSERT INTO daily_stats(user_id, day, xp, tasks, correct)
           VALUES(?,?,?,?,?)
           ON CONFLICT(user_id, day) DO UPDATE SET
               xp = xp + excluded.xp,
               tasks = tasks + excluded.tasks,
               correct = correct + excluded.correct""",
        (tg_id, day, xp, tasks, correct),
    )
    user = get_user(tg_id)
    if not user:
        return
    last_day = user.get("last_day")
    streak = int(user.get("streak") or 0)
    if last_day == day:
        pass
    elif last_day == (date.today() - timedelta(days=1)).isoformat():
        streak += 1
    else:
        streak = 1
    best = max(streak, int(user.get("best_streak") or 0))
    execute(
        "UPDATE users SET last_day=?, streak=?, best_streak=?, xp=xp+? WHERE tg_id=?",
        (day, streak, best, xp, tg_id),
    )


def add_xp(tg_id: int, amount: int) -> None:
    execute("UPDATE users SET xp = xp + ? WHERE tg_id = ?", (amount, tg_id))


def log_attempt(
    user_id: int,
    lesson_id: str,
    task_i: int,
    kind: str,
    given: str,
    expected: str,
    result: str,
    tag: str,
) -> None:
    execute(
        """INSERT INTO attempts(user_id, lesson_id, task_i, kind, given, expected, result, tag, created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (user_id, lesson_id, task_i, kind, given[:400], expected[:400], result, tag, now()),
    )
    if tag:
        execute(
            """INSERT INTO error_tags(user_id, tag, count, last_at) VALUES(?,?,1,?)
               ON CONFLICT(user_id, tag) DO UPDATE SET count = count + 1, last_at = excluded.last_at""",
            (user_id, tag, now()),
        )


def bump_lesson(user_id: int, lesson_id: str, correct: int, total: int, score: float) -> None:
    execute(
        """INSERT INTO lesson_progress(user_id, lesson_id, done, correct, total, best_score, attempts, updated_at)
           VALUES(?,?,1,?,?,?,1,?)
           ON CONFLICT(user_id, lesson_id) DO UPDATE SET
               done = 1,
               correct = lesson_progress.correct + excluded.correct,
               total = lesson_progress.total + excluded.total,
               best_score = MAX(lesson_progress.best_score, excluded.best_score),
               attempts = lesson_progress.attempts + 1,
               updated_at = excluded.updated_at""",
        (user_id, lesson_id, correct, total, score, now()),
    )


def set_session(user_id: int, mode: str, data: Dict[str, Any]) -> None:
    execute(
        """INSERT INTO sessions(user_id, mode, data, updated_at) VALUES(?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode, data=excluded.data, updated_at=excluded.updated_at""",
        (user_id, mode, json.dumps(data, ensure_ascii=False), now()),
    )


def get_session(user_id: int) -> Optional[Dict[str, Any]]:
    row = query_one("SELECT * FROM sessions WHERE user_id = ?", (user_id,))
    if not row:
        return None
    try:
        row["data"] = json.loads(row.get("data") or "{}")
    except json.JSONDecodeError:
        row["data"] = {}
    return row


def clear_session(user_id: int) -> None:
    execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
