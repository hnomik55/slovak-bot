"""Лицензии и подписки.

Модель продажи: админ генерирует ключи (например, 30 штук на месяц) и продаёт
их. Ключ **одноразовый**: при первом вводе он погашается и привязывается к
Telegram-аккаунту покупателя. Дальше доступ работает автоматически, ключ больше
не нужен.

Ключи бывают:
  * бессрочные (days = 0) — «доступ навсегда»;
  * сроком на N дней — подписка с ограничением по времени.

Прогресс ученика и так привязан к telegram_id (см. app/db.py), поэтому у каждого
своя история, свои карточки слов и свои ошибки.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app import db
from app.config import CONFIG

# Алфавит ключа: 20 символов — буквы, цифры и знаки.
# Убраны похожие символы (O/0, I/1) — покупатель не перепутает при переписывании.
ALPHABET = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ"   # буквы без O и I
    "23456789"                    # цифры без 0 и 1
    "-_!@#$%&*+=?."               # знаки
)
KEY_LENGTH = 20
KEY_PREFIX = "SLOV"
CODE_RE = re.compile(r"^SLOV(-[A-Z0-9]{5}){3}$")
NEW_CODE_RE = re.compile(r"^[A-Z0-9\-_!@#$%&*+=?.]{20}$")

PLAN_LIFETIME = "lifetime"
PLAN_TRIAL = "trial"


def normalize_code(raw: str) -> str:
    """Приводит ключ к каноническому виду.

    Новый формат — 20 случайных символов: сохраняем как есть (регистр не важен,
    потому что в алфавите нет строчных букв).
    Старый формат SLOV-XXXXX-XXXXX-XXXXX — приводим к каноническому.
    """
    if not raw:
        return ""
    text = raw.strip()
    # Убираем пробелы и невидимые символы, которые могли прилипнуть при копировании
    text = "".join(ch for ch in text if ch.isprintable() and ch not in " \t\u200b\u00a0")
    if NEW_CODE_RE.match(text.upper()):
        return text.upper()

    cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    while cleaned.startswith(KEY_PREFIX) and len(cleaned) > 15:
        cleaned = cleaned[len(KEY_PREFIX):]
    body = cleaned[:15].ljust(15, "X")
    return "%s-%s-%s-%s" % (KEY_PREFIX, body[0:5], body[5:10], body[10:15])


def generate_code() -> str:
    """20 случайных символов: буквы, цифры, знаки."""
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(KEY_LENGTH))
        if not db.query_one("SELECT id FROM licenses WHERE code = ?", (code,)):
            return code


def create_keys(count: int = 1, days: int = 0, note: str = "", batch: str = "") -> List[str]:
    """Создаёт ключи. days=0 — бессрочный доступ."""
    codes: List[str] = []
    for _ in range(max(1, count)):
        code = generate_code()
        db.execute(
            """INSERT INTO licenses(code, days, note, batch, created_at, revoked)
               VALUES(?,?,?,?,?,0)""",
            (code, int(days), note or "", batch or "", db.now()),
        )
        codes.append(code)
    return codes


def get_license(code: str) -> Optional[Dict[str, Any]]:
    return db.query_one("SELECT * FROM licenses WHERE code = ?", (normalize_code(code),))


def revoke(code: str) -> bool:
    row = get_license(code)
    if not row:
        return False
    db.execute("UPDATE licenses SET revoked = 1 WHERE id = ?", (row["id"],))
    if row.get("used_by"):
        db.execute(
            "UPDATE subscriptions SET status = 'revoked' WHERE telegram_id = ?", (row["used_by"],)
        )
    return True


def get_subscription(telegram_id: int) -> Optional[Dict[str, Any]]:
    return db.query_one("SELECT * FROM subscriptions WHERE telegram_id = ?", (telegram_id,))


def expires_at(telegram_id: int) -> Optional[date]:
    sub = get_subscription(telegram_id)
    if not sub or not sub.get("expires_at"):
        return None
    try:
        return date.fromisoformat(sub["expires_at"])
    except ValueError:
        return None


def remaining_days(telegram_id: int) -> Optional[int]:
    """Сколько дней осталось. None — бессрочно."""
    until = expires_at(telegram_id)
    if until is None:
        return None
    return (until - date.today()).days


def is_active(telegram_id: int) -> bool:
    """Есть ли действующий доступ."""
    if is_owner(telegram_id) and CONFIG.owner_bypass_license:
        return True
    sub = get_subscription(telegram_id)
    if not sub:
        return False
    if sub.get("status") not in (None, "", "active"):
        return False
    until = expires_at(telegram_id)
    if until is None:
        return True  # бессрочно
    return until >= date.today()


def is_owner(telegram_id: int) -> bool:
    """Владелец бота (его id в ADMIN_IDS)."""
    return telegram_id in CONFIG.admin_ids


def redeem(code: str, telegram_id: int) -> Tuple[bool, str]:
    """Погашает ключ. Возвращает (ok, сообщение для пользователя)."""
    canonical = normalize_code(code)
    row = get_license(canonical)
    if not row:
        return False, "Ключ не найден. Проверь раскладку и попробуй ещё раз."
    if row.get("revoked"):
        return False, "Этот ключ отозван. Напиши в поддержку."
    if row.get("used_by"):
        if int(row["used_by"]) == int(telegram_id):
            return False, "Этот ключ уже активирован на твоём аккаунте."
        return False, "Этот ключ уже использован другим человеком."

    days = int(row.get("days") or 0)
    now = datetime.now()
    if days > 0:
        until = (now + timedelta(days=days)).date().isoformat()
        plan = "%dd" % days
    else:
        until = None
        plan = PLAN_LIFETIME

    db.execute(
        "UPDATE licenses SET used_by = ?, used_at = ? WHERE id = ?",
        (telegram_id, db.now(), row["id"]),
    )
    db.execute(
        """INSERT INTO subscriptions(telegram_id, license_id, plan, activated_at, expires_at, status)
           VALUES(?,?,?,?,?, 'active')
           ON CONFLICT(telegram_id) DO UPDATE SET
               license_id = excluded.license_id,
               plan = excluded.plan,
               activated_at = excluded.activated_at,
               expires_at = excluded.expires_at,
               status = 'active'""",
        (telegram_id, row["id"], plan, now.date().isoformat(), until),
    )
    db.execute(
        "INSERT OR REPLACE INTO users(tg_id, created_at, last_seen) VALUES(?,?,?)",
        (telegram_id, db.now(), db.now()),
    )
    if days > 0:
        message = "✅ Доступ открыт на %d дней (до %s)." % (days, until)
    else:
        message = "✅ Доступ открыт навсегда. Пользуйся ботом!"
    return True, message


def extend(telegram_id: int, days: int) -> Optional[str]:
    """Продлевает подписку. Возвращает новую дату окончания (None — бессрочно)."""
    sub = get_subscription(telegram_id)
    if not sub:
        return None
    current = expires_at(telegram_id)
    if current is None:
        return None  # уже бессрочная
    base = max(current, date.today())
    new_until = (base + timedelta(days=days)).isoformat()
    db.execute(
        "UPDATE subscriptions SET expires_at = ?, status = 'active' WHERE telegram_id = ?",
        (new_until, telegram_id),
    )
    return new_until


def list_licenses(limit: int = 50, unused_only: bool = False) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM licenses"
    if unused_only:
        sql += " WHERE used_by IS NULL"
    sql += " ORDER BY id DESC LIMIT ?"
    return db.query(sql, (limit,))


def list_subscribers(limit: int = 50) -> List[Dict[str, Any]]:
    return db.query(
        """SELECT s.*, u.username, u.first_name, u.last_seen FROM subscriptions s
           LEFT JOIN users u ON u.tg_id = s.telegram_id
           ORDER BY s.activated_at DESC LIMIT ?""",
        (limit,),
    )


def stats() -> Dict[str, int]:
    total = db.query_one("SELECT COUNT(*) AS n FROM licenses") or {"n": 0}
    used = db.query_one("SELECT COUNT(*) AS n FROM licenses WHERE used_by IS NOT NULL") or {"n": 0}
    active = db.query_one(
        """SELECT COUNT(*) AS n FROM subscriptions
           WHERE status = 'active' AND (expires_at IS NULL OR expires_at >= date('now'))"""
    ) or {"n": 0}
    return {"total": int(total["n"]), "used": int(used["n"]), "active": int(active["n"])}
