"""Админские команды: пересборка контента, генерация недостающих юнитов, рассылка."""

from __future__ import annotations

import asyncio
import io
import logging
import sys

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app import content as content_mod
from app import db
from app import licensing
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
        "Контент: %s уроков, %s заданий, %s слов"
        % (
            users["n"],
            active["n"],
            attempts["n"],
            stats["lessons"],
            stats["tasks"],
            stats["vocab"],
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


# --------------------------------------------------------------------------- #
# Ключи и подписки
# --------------------------------------------------------------------------- #
@router.message(Command("admin_key", "admin_keys"))
async def cmd_keys(message: Message) -> None:
    """Управление ключами доступа.

    /admin_key make 10 30 почта@пример   -> 10 ключей на 30 дней
    /admin_key make 5 0                  -> 5 бессрочных ключей
    /admin_key import                    -> импорт партии (ответом на .txt/.csv)
    /admin_key import КЛЮЧ1 КЛЮЧ2        -> импорт вставленных ключей
    /admin_key export                    -> выгрузить все ключи файлом
    /admin_key list                      -> список ключей
    /admin_key unused                    -> только неиспользованные
    /admin_key revoke SLOV-XXXXX-...     -> отозвать ключ
    /admin_key stats                     -> сводка
    """
    if not _guard(message):
        return
    args = message.text.split()
    action = args[1].lower() if len(args) > 1 else "stats"

    if action == "make":
        count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1
        days = int(args[3]) if len(args) > 3 and args[3].isdigit() else 0
        note = args[4] if len(args) > 4 else ""
        batch = args[5] if len(args) > 5 else ""
        codes = licensing.create_keys(count, days, note, batch)
        plan = "навсегда" if days <= 0 else "%d дней" % days
        await message.answer(
            "🔑 Создано ключей: <b>%d</b> (%s)\n\n<code>%s</code>\n\n"
            "Отправь их покупателям. Каждый ключ работает один раз."
            % (len(codes), plan, "\n".join(codes))
        )
        return

    if action == "import":
        text = ""
        document = message.reply_to_message.document if message.reply_to_message else None
        if document:
            buffer = io.BytesIO()
            try:
                await message.bot.download(document, destination=buffer)
                text = buffer.getvalue().decode("utf-8", "replace")
            except Exception as exc:
                await message.answer("Не удалось прочитать файл: %s" % exc)
                return
        else:
            parts = message.text.split(maxsplit=2)
            text = parts[2] if len(parts) > 2 else ""

        codes = licensing.parse_codes(text)
        if not codes:
            await message.answer(
                "Не вижу ключей.\n\n"
                "Пришли файл .txt/.csv ответом на команду:\n"
                "<code>/admin_key import</code> (реплай на файл)\n\n"
                "Или вставь ключи в сообщение:\n"
                "<code>/admin_key import КЛЮЧ1 КЛЮЧ2 ...</code>"
            )
            return

        added = licensing.import_codes(codes, 0, "", "import")
        await message.answer(
            "📥 <b>Импорт ключей</b>\n\n"
            "Найдено: <b>%d</b>\nДобавлено: <b>%d</b>\nУже были: <b>%d</b>\n\n"
            "Всего в базе: <b>%d</b>"
            % (
                added["received"],
                added["imported"],
                added["existing"],
                licensing.stats()["total"],
            )
        )
        return

    if action == "export":
        rows = licensing.list_licenses(5000)
        if not rows:
            await message.answer("Ключей в базе нет.")
            return
        header = [
            "# Ключи активации (выгрузка %s)" % db.now(),
            "# Строк: %d. Импорт: /admin_key import (ответом на этот файл)." % len(rows),
            "",
        ]
        payload = "\n".join(header + [row["code"] for row in rows]) + "\n"
        await message.answer_document(
            BufferedInputFile(payload.encode("utf-8"), filename="keys-export.txt"),
            caption="🔑 Ключей: <b>%d</b>" % len(rows),
        )
        return

    if action in ("list", "unused"):
        rows = licensing.list_licenses(30, unused_only=(action == "unused"))
        if not rows:
            await message.answer("Ключей нет.")
            return
        lines = ["<b>Ключи (последние %d)</b>" % len(rows)]
        for row in rows:
            state = "использован" if row.get("used_by") else ("отозван" if row.get("revoked") else "свободен")
            plan = "∞" if not row.get("days") else "%dд" % row["days"]
            lines.append(
                "<code>%s</code> · %s · %s%s"
                % (row["code"], plan, state, (" · " + str(row.get("used_by"))) if row.get("used_by") else "")
            )
        await message.answer("\n".join(lines))
        return

    if action == "revoke":
        if len(args) < 3:
            await message.answer("Формат: /admin_key revoke <код>")
            return
        ok = licensing.revoke(args[2])
        await message.answer("Ключ отозван." if ok else "Ключ не найден.")
        return

    if action == "delete":
        if len(args) < 3:
            await message.answer("Формат: /admin_key delete <код>")
            return
        result = licensing.delete_codes(args[2:])
        await message.answer(
            "Удалено ключей: %d, подписок: %d."
            % (result["removed"], result["subscriptions"])
            if result["removed"]
            else "Такого ключа нет."
        )
        return

    if action == "subs":
        rows = licensing.list_subscribers(30)
        if not rows:
            await message.answer("Подписок нет.")
            return
        lines = ["<b>Подписчики (%d)</b>" % len(rows)]
        for row in rows:
            name = row.get("first_name") or row.get("username") or "—"
            until = row.get("expires_at") or "бессрочно"
            lines.append("%s · id %s · до %s · %s" % (name, row["telegram_id"], until, row.get("status")))
        await message.answer("\n".join(lines))
        return

    if action == "extend":
        if len(args) < 3:
            await message.answer("Формат: /admin_key extend <telegram_id> <дней>")
            return
        try:
            tg_id = int(args[2])
            days = int(args[3]) if len(args) > 3 else 30
        except ValueError:
            await message.answer("Нужны telegram_id и число дней.")
            return
        new_until = licensing.extend(tg_id, days)
        await message.answer(
            "Продлено до %s" % new_until if new_until else "Подписку продлить нельзя (нет записи или бессрочная)."
        )
        return

    stats = licensing.stats()
    await message.answer(
        "🔑 <b>Ключи</b>\n\n"
        "Всего: <b>%d</b> · использовано: <b>%d</b> · активных подписок: <b>%d</b>\n\n"
        "Создать: <code>/admin_key make 10 30</code>\n"
        "Импорт: <code>/admin_key import</code> (ответом на файл)\n"
        "Выгрузить: <code>/admin_key export</code>\n"
        "Список: <code>/admin_key list</code>\n"
        "Подписчики: <code>/admin_key subs</code>"
        % (stats["total"], stats["used"], stats["active"])
    )


@router.message(Command("admin_user"))
async def cmd_user_info(message: Message) -> None:
    """Показывает подписку конкретного пользователя: /admin_user <telegram_id>"""
    if not _guard(message):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Формат: /admin_user <telegram_id>")
        return
    tg_id = int(args[1])
    sub = licensing.get_subscription(tg_id)
    user = db.get_user(tg_id) or {}
    if not sub:
        await message.answer("Подписки нет. Пользователь: %s" % (user.get("first_name") or "—"))
        return
    days = licensing.remaining_days(tg_id)
    await message.answer(
        "👤 <b>%s</b> (id %s)\n\n"
        "План: %s\nАктивна с: %s\nДействует до: %s\nОсталось: %s\nСтатус: %s\n\n"
        "Продлить: /admin_key extend %s 30"
        % (
            user.get("first_name") or "—",
            tg_id,
            sub.get("plan"),
            sub.get("activated_at"),
            sub.get("expires_at") or "бессрочно",
            "∞" if days is None else "%d дн." % days,
            sub.get("status"),
            tg_id,
        )
    )
