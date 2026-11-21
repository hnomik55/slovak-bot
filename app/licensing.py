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

import io
import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app import db
from app.config import CONFIG

log = logging.getLogger("licensing")

# Алфавит ключа: 20 символов — буквы, цифры и знаки.
# Убраны похожие символы (O/0, I/1) — покупатель не перепутает при переписывании.
# Знака «#» в новых ключах нет: строка, начинающаяся с него, читается как
# комментарий в txt-файле, и ключ терялся при копировании партии в файл.
ALPHABET = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ"   # буквы без O и I
    "23456789"                    # цифры без 0 и 1
    "-_!@$%&*+=?."                # знаки (без #)
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
    snapshot()
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
    snapshot()
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
            return True, "✅ Этот ключ уже активирован на твоём аккаунте — доступ открыт."
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
    snapshot()
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


# --------------------------------------------------------------------------- #
# Перенос ключей между базами и резервная копия
#
# База на сервере и база на домашнем ПК — разные файлы. Ключи, созданные
# локально, не появляются на хостинге сами: получается «ключ не найден».
# Поэтому партию можно импортировать из txt/csv, а состояние лицензий
# сохраняется рядом с базой (data/keys/licenses.json) и подхватывается
# при старте, даже если базу пересоздали.
# --------------------------------------------------------------------------- #
_SKIP_TOKENS = {
    "key", "keys", "code", "codes", "ключ", "ключи", "batch", "план", "plan",
}


def _valid_code(token: str) -> str:
    """Возвращает канонический ключ или пустую строку, если это не ключ."""
    raw = "".join(ch for ch in str(token) if ch.isprintable() and ch not in " \t\u200b\u00a0")
    upper = raw.upper()
    if NEW_CODE_RE.match(upper) or CODE_RE.match(upper):
        return upper
    return ""


def parse_codes(text: str) -> List[str]:
    """Достаёт ключи из txt/csv/сообщения.

    Понимает: один ключ на строку, CSV с колонками key,batch,...,
    ключи через пробел или запятую, строки-комментарии (# ...).
    """
    found: List[str] = []
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("//", ";")):
            continue
        # Комментарий — это «# текст». Одиночный ключ тоже может начинаться
        # с «#» (старые партии), поэтому сначала проверяем, ключ ли это.
        if line.startswith("#") and not _valid_code(line.split()[0]):
            continue
        for token in re.split(r"[,;\t ]+", line):
            token = token.strip().strip('"').strip("'")
            if not token or token.lower() in _SKIP_TOKENS:
                continue
            code = _valid_code(token)
            if code:
                found.append(code)
    seen: set = set()
    out: List[str] = []
    for code in found:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def import_codes(
    codes: Iterable[str], days: int = 0, note: str = "", batch: str = ""
) -> Dict[str, int]:
    """Добавляет ключи в текущую базу. Повторный импорт безопасен."""
    received = imported = existing = invalid = 0
    for raw in codes:
        code = _valid_code(raw)
        if not code:
            invalid += 1
            continue
        received += 1
        if db.query_one("SELECT id FROM licenses WHERE code = ?", (code,)):
            existing += 1
            continue
        db.execute(
            """INSERT INTO licenses(code, days, note, batch, created_at, revoked)
               VALUES(?,?,?,?,?,0)""",
            (code, int(days), note or "", batch or "", db.now()),
        )
        imported += 1
    if imported:
        snapshot()
    return {
        "received": received,
        "imported": imported,
        "existing": existing,
        "invalid": invalid,
    }


def delete_codes(codes: Iterable[str]) -> Dict[str, int]:
    """Удаляет ключи (например, тестовые или ошибочно залитую партию).

    Вместе с ключом удаляется подписка, которая на нём висит.
    """
    removed = 0
    subs = 0
    for raw in codes:
        code = _valid_code(raw)
        if not code:
            continue
        row = db.query_one("SELECT id FROM licenses WHERE code = ?", (code,))
        if not row:
            continue
        linked = db.query_one(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE license_id = ?", (row["id"],)
        ) or {"n": 0}
        db.execute("DELETE FROM subscriptions WHERE license_id = ?", (row["id"],))
        db.execute("DELETE FROM licenses WHERE id = ?", (row["id"],))
        removed += 1
        subs += int(linked["n"])
    if removed:
        snapshot()
    return {"removed": removed, "subscriptions": subs}


def apply_activation(code: str, telegram_id: int, activated_at: Optional[str] = None) -> bool:
    """Привязывает уже существующий ключ к аккаунту (восстановление покупки)."""
    row = get_license(code)
    if not row:
        return False
    tg_id = int(telegram_id)
    if row.get("used_by") and int(row["used_by"]) != tg_id:
        return False

    day = (activated_at or row.get("used_at") or date.today().isoformat())[:10]
    now = datetime.now()
    if not row.get("used_by"):
        db.execute(
            "UPDATE licenses SET used_by = ?, used_at = ? WHERE id = ?",
            (tg_id, day, row["id"]),
        )
    days = int(row.get("days") or 0)
    until = (date.fromisoformat(day) + timedelta(days=days)).isoformat() if days > 0 else None
    db.execute(
        """INSERT INTO subscriptions(telegram_id, license_id, plan, activated_at, expires_at, status)
           VALUES(?,?,?,?,?, 'active')
           ON CONFLICT(telegram_id) DO UPDATE SET
               license_id = excluded.license_id,
               plan = excluded.plan,
               activated_at = excluded.activated_at,
               expires_at = excluded.expires_at,
               status = 'active'""",
        (tg_id, row["id"], PLAN_LIFETIME if days <= 0 else "%dd" % days, day, until),
    )
    db.ensure_user(tg_id)
    return True


def export_state() -> Dict[str, Any]:
    """Всё состояние лицензий одним словарём (для файла и для API)."""
    licenses = db.query(
        """SELECT code, days, note, batch, created_at, used_by, used_at, revoked
           FROM licenses ORDER BY id"""
    )
    subscriptions = db.query(
        """SELECT telegram_id, license_id, plan, activated_at, expires_at, status
           FROM subscriptions ORDER BY telegram_id"""
    )
    return {
        "exported_at": db.now(),
        "count": len(licenses),
        "licenses": licenses,
        "subscriptions": subscriptions,
    }


def state_path() -> Path:
    """Файл-снимок лицензий: лежит рядом с базой, переживает пересоздание БД."""
    return Path(CONFIG.db_path).parent / "keys" / "licenses.json"


def snapshot() -> Optional[Path]:
    """Сохраняет состояние лицензий в файл. Ошибки не ломают активацию."""
    path = state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(export_state(), fh, ensure_ascii=False, indent=1)
        os.replace(str(tmp), str(path))
        return path
    except OSError as exc:
        log.warning("не удалось сохранить снимок лицензий: %s", exc)
        return None


def restore_state(path: Optional[Path] = None) -> Dict[str, int]:
    """Догружает ключи и активации из снимка."""
    source = Path(path) if path else state_path()
    result = {"imported": 0, "existing": 0, "activated": 0}
    if not source.exists():
        return result
    try:
        with io.open(source, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log.warning("снимок лицензий не прочитался: %s", exc)
        return result

    for record in data.get("licenses") or []:
        code = _valid_code(record.get("code") or "")
        if not code:
            continue
        if db.query_one("SELECT id FROM licenses WHERE code = ?", (code,)):
            result["existing"] += 1
        else:
            db.execute(
                """INSERT INTO licenses(code, days, note, batch, created_at, used_by, used_at, revoked)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    code,
                    int(record.get("days") or 0),
                    record.get("note") or "",
                    record.get("batch") or "",
                    record.get("created_at") or db.now(),
                    record.get("used_by"),
                    record.get("used_at"),
                    int(record.get("revoked") or 0),
                ),
            )
            result["imported"] += 1
        if record.get("used_by"):
            if apply_activation(code, int(record["used_by"]), record.get("used_at")):
                result["activated"] += 1

    for sub in data.get("subscriptions") or []:
        if not sub.get("telegram_id"):
            continue
        db.execute(
            """UPDATE subscriptions
               SET license_id = ?, plan = ?, activated_at = ?, expires_at = ?, status = ?
               WHERE telegram_id = ?""",
            (
                sub.get("license_id"),
                sub.get("plan"),
                sub.get("activated_at"),
                sub.get("expires_at"),
                sub.get("status") or "active",
                int(sub["telegram_id"]),
            ),
        )
    return result


_BOOTSTRAPPED = False


def bootstrap(force: bool = False) -> Dict[str, int]:
    """Подхватывает ключи из файлов рядом с базой при старте.

    Читает data/keys/licenses.json и data/keys/*.txt|csv. Так партия,
    загруженная на сервер файлом, начинает работать без ручных команд.
    """
    global _BOOTSTRAPPED
    result = {"imported": 0, "existing": 0, "activated": 0, "files": 0}
    if _BOOTSTRAPPED and not force:
        return result

    keys_dir = state_path().parent
    if not keys_dir.exists():
        _BOOTSTRAPPED = True
        return result

    restored = restore_state()
    for key in ("imported", "existing", "activated"):
        result[key] += restored[key]

    for path in sorted(keys_dir.iterdir()):
        if path.name.startswith(".") or path.suffix.lower() not in (".txt", ".csv"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("файл ключей не прочитался (%s): %s", path.name, exc)
            continue
        codes = parse_codes(text)
        if not codes:
            continue
        added = import_codes(codes, 0, "", path.stem)
        result["imported"] += added["imported"]
        result["existing"] += added["existing"]
        result["files"] += 1

    _BOOTSTRAPPED = True
    if result["imported"] or result["activated"]:
        log.info(
            "ключи подхвачены из файлов: +%d, активаций: %d",
            result["imported"],
            result["activated"],
        )
    return result
