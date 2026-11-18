"""Админские команды: пересборка контента, генерация недостающих юнитов, рассылка."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app import content as content_mod
from app import db
from app.config import CONFIG
from app.services.ai import AI

log = logging.getLogger("admin")
router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    return user_id in CONFIG.admin_ids


def _guard(message: Message) -> bool:
    if _is_admin(message.from_user.id):
        return True
    message.answer("Эта команда только для администратора.")
    return False


@router.message(Command("admin_reload", "reload"))
async def cmd_reload(message: Message) -> None:
    """Пересобирает content.json из папки с контентом и обновляет словарь в БД."""
    if not _guard(message):
        return
    source = CONFIG.source_dir
    if not source.exists():
        await message.answer(
            "⚠️ Папка с контентом не найдена на этой машине: <code>%s</code>\n\n"
            "Значит, бот запущен на сервере без исходников. Тут контент не пересобирается —\n"
            "загрузи новый <code>data/content.json</code> на сервер и перезапусти бота.\n"
            "Локально (на твоём ПК) команда работает как обычно." % source
        )
        return
    await message.answer("Пересобираю контент… ⏳")
    script = CONFIG.root / "tools" / "build_content.py"
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--source",
        str(CONFIG.source_dir),
        "--out",
        str(CONFIG.data_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = (stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        await message.answer("❌ Не собралось:\n<code>%s</code>" % output[-1500:])
        return
    content_mod.CONTENT.load(force=True)
    db.upsert_vocab(content_mod.CONTENT.vocab)
    stats = content_mod.CONTENT.stats()
    await message.answer(
        "✅ Контент пересобран\n<code>%s</code>\n\nСлов в БД: %d"
        % (output.strip()[-800:], stats["vocab"])
    )


@router.message(Command("admin_gen"))
async def cmd_gen(message: Message) -> None:
    """Генерирует ИИ-урок для отсутствующего юнита: /admin_gen 8 <тема>"""
    if not _guard(message):
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Формат: /admin_gen <номер юнита> <тема>\nПример: /admin_gen 8 Дательный и творительный падеж")
        return
    unit_no = int(args[1])
    topic = args[2]
    if not AI.enabled:
        await message.answer("Нужен ИИ-ключ (AI_API_KEY в .env).")
        return
    await message.answer("Генерирую юнит %s «%s»… ⏳" % (unit_no, topic))
    payload = await AI.generate_lesson(unit_no, topic, "A2", 14)
    if not payload:
        await message.answer("❌ Модель не вернула нормальный урок. Попробуй ещё раз.")
        return
    lesson_id = "u%s-ai" % unit_no
    content_mod.save_generated_lesson(message.from_user.id, lesson_id, unit_no, topic, payload)
    await message.answer(
        "✅ Урок сохранён как <b>%s</b>.\nЗадания: %d\nОн появится в списке уроков."
        % (lesson_id, len(payload.get("tasks") or []))
    )


@router.message(Command("admin_stats"))
async def cmd_stats(message: Message) -> None:
    if not _guard(message):
        return
    users = db.query_one("SELECT COUNT(*) AS n FROM users") or {"n": 0}
    active = db.query_one(
        "SELECT COUNT(*) AS n FROM users WHERE last_seen >= date('now','-7 day')"
    ) or {"n": 0}
    attempts = db.query_one("SELECT COUNT(*) AS n FROM attempts") or {"n": 0}
    stats = content_mod.CONTENT.stats()
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        "Юзеров: %s (активных за 7 дней: %s)\n"
        "Попыток: %s\n"
        "Контент: %s уроков, %s заданий, %s слов\n"
        "Сборка: %s"
        % (
            users["n"],
            active["n"],
            attempts["n"],
            stats["lessons"],
            stats["tasks"],
            stats["vocab"],
            stats["built_at"],
        )
    )


@router.message(Command("admin_broadcast"))
async def cmd_broadcast(message: Message) -> None:
    if not _guard(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Формат: /admin_broadcast <текст>")
        return
    text = args[1]
    rows = db.query("SELECT tg_id FROM users")
    sent = failed = 0
    for row in rows:
        try:
            await message.bot.send_message(row["tg_id"], text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await message.answer("Отправлено: %d, ошибок: %d" % (sent, failed))
