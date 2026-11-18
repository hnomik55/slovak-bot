"""Интеграционный тест: прогон бота через aiogram без сети.

Используется фейковая сессия вместо HTTP — бот отвечает, но в Telegram ничего
не уходит. Проверяем весь путь: /start -> меню -> урок -> ответ -> разбор ->
слова -> прогресс.

Запуск: python tests/test_flow.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="slovak_flow_"))
os.environ["DB_PATH"] = str(TMP / "flow.db")
os.environ["AI_PROVIDER"] = "off"
os.environ["TTS_ENABLED"] = "0"
os.environ["STT_ENABLED"] = "0"

from aiogram import Dispatcher  # noqa: E402
from aiogram.client.bot import Bot  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, SendVoice  # noqa: E402
from aiogram.methods.base import Response  # noqa: E402
from aiogram.types import Chat, Message, Update  # noqa: E402

from app import db  # noqa: E402
from app import content as content_mod  # noqa: E402
from app.handlers import (  # noqa: E402
    admin,
    lessons,
    progress,
    quiz,
    settings,
    skills,
    speaking,
    start,
    vocab,
    writing,
)

TOKEN = "123456789:AAEhBOweik6ad9r_QXvcS7SFvlG1234567890"
CHAT_ID = 424242
USER_ID = 424242


class FakeSession:
    """Сессия вместо HTTP: запоминает все вызовы и возвращает заглушки."""

    def __init__(self) -> None:
        self.calls: List[Any] = []

    async def __call__(self, bot: Bot, method: Any, timeout: Optional[int] = None) -> Any:
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            result: Any = True
        elif isinstance(method, (SendMessage, EditMessageText, SendVoice)):
            result = Message(
                message_id=1000 + len(self.calls),
                date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="private"),
                text=getattr(method, "text", None),
            )
        else:
            result = None
        return Response[method.__returning__](ok=True, result=result)

    async def close(self) -> None:
        pass

    # --- удобные выборки ---
    def texts(self) -> List[str]:
        return [c.text for c in self.calls if isinstance(c, (SendMessage, EditMessageText)) and c.text]

    def sent_texts(self) -> List[str]:
        """Только НОВЫЕ сообщения (ответы бота), без правок существующих."""
        return [c.text for c in self.calls if isinstance(c, SendMessage) and c.text]

    def last_sent_text(self) -> str:
        texts = self.sent_texts()
        return texts[-1] if texts else ""

    def last_text(self) -> str:
        texts = self.texts()
        return texts[-1] if texts else ""

    def keyboards(self) -> List[Any]:
        out = []
        for call in self.calls:
            markup = getattr(call, "reply_markup", None)
            if markup is not None and getattr(markup, "inline_keyboard", None):
                out.append(markup.inline_keyboard)
        return out

    def find_button(self, text_contains: str) -> Optional[str]:
        """Ищет callback_data кнопки по подстроке её текста."""
        for keyboard in self.keyboards():
            for row in keyboard:
                for button in row:
                    if text_contains.lower() in button.text.lower():
                        return button.callback_data
        return None


PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s %s" % (name, detail))


def make_update(update_id: int, payload: Dict[str, Any]) -> Update:
    return Update.model_validate(payload, context={"bot": BOT})


async def main() -> int:
    global BOT
    session = FakeSession()
    BOT = Bot(token=TOKEN, session=session)
    db.init_db()
    content_mod.CONTENT.load(force=True)
    db.upsert_vocab(content_mod.CONTENT.vocab)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(lessons.router)
    dp.include_router(vocab.router)
    dp.include_router(skills.router)
    dp.include_router(writing.router)
    dp.include_router(speaking.router)
    dp.include_router(quiz.router)
    dp.include_router(progress.router)
    dp.include_router(settings.router)
    dp.include_router(admin.router)

    uid = 1
    chat = {"id": CHAT_ID, "type": "private"}
    user = {"id": USER_ID, "is_bot": False, "first_name": "Тест", "username": "tester"}

    async def send(text: str) -> None:
        nonlocal uid
        uid += 1
        await dp.feed_update(
            BOT,
            make_update(
                uid,
                {
                    "update_id": uid,
                    "message": {"message_id": uid, "date": int(datetime.now().timestamp()), "chat": chat, "from": user, "text": text},
                },
            ),
        )

    async def press(callback_data: str, message_id: int = 1) -> None:
        nonlocal uid
        uid += 1
        await dp.feed_update(
            BOT,
            make_update(
                uid,
                {
                    "update_id": uid,
                    "callback_query": {
                        "id": str(uid),
                        "from": user,
                        "chat_instance": "ci",
                        "data": callback_data,
                        "message": {"message_id": message_id, "date": int(datetime.now().timestamp()), "chat": chat, "text": "..."},
                    },
                },
            ),
        )

    print("\n== /start и меню ==")
    await send("/start")
    check("бот поздоровался", "Словацкого" in session.last_text() or "словацкого" in session.last_text(), session.last_text()[:80])
    check("есть кнопка «Уроки»", session.find_button("Уроки") == "nav:lessons")

    print("\n== Список юнитов ==")
    await press("nav:lessons")
    check("показаны юниты", "Пройдено" in session.last_text(), session.last_text()[:100])
    check("есть кнопка юнита 1", session.find_button("1. Знакомство") is not None)

    print("\n== Уроки юнита 1 ==")
    await press("nav:unit:1")
    check("список уроков", "Юнит 1" in session.last_text(), session.last_text()[:100])
    check("кнопка урока 1a", session.find_button("1a") is not None)

    print("\n== Карточка урока ==")
    await press("nav:lesson:1a")
    check("карточка урока", "Урок" in session.last_text() or "Знакомство" in session.last_text(), session.last_text()[:100])
    check("кнопка «Начать урок»", session.find_button("Начать урок") is not None)

    print("\n== Задание choice ==")
    await press("nav:start:1a")
    check("пришло первое задание", "Выбери" in session.last_text() or "🎯" in session.last_text(), session.last_text()[:120])
    check("есть варианты ответа", session.find_button("SLO-vensko") is not None or session.find_button("Ударение") is not None)

    print("\n== Ответ на choice ==")
    # Правильный вариант в тренажёре — первый в исходном массиве (для 1a это 'SLO-vensko').
    # Кнопки показываются в случайном порядке, поэтому ищем их по тексту.
    def find_by_text(needle: str) -> Optional[str]:
        for keyboard in session.keyboards():
            for row in keyboard:
                for button in row:
                    if button.text.strip() == needle:
                        return button.callback_data
        return None

    right = find_by_text("SLO-vensko")
    wrong = None
    for keyboard in session.keyboards():
        for row in keyboard:
            for button in row:
                if button.callback_data.startswith("tk:choice:") and button.text.strip() != "SLO-vensko":
                    wrong = button.callback_data
    check("правильный вариант найден", right is not None)
    check("неправильный вариант найден", wrong is not None)

    if wrong:
        await press(wrong)
        check("неверный ответ помечен", "Неверно" in session.last_text(), session.last_text()[:120])
        check("показан правильный ответ", "SLO-vensko" in session.last_text(), session.last_text()[:160])
        check("ошибка записана в блок ошибок", db.query("SELECT 1 FROM error_tags WHERE user_id = ?", (USER_ID,)) != [])

    await press("tk:retry:0")
    if right:
        await press(right)
        check("правильный ответ засчитан", "Верно" in session.last_text(), session.last_text()[:120])

    print("\n== Разбор и переход дальше ==")
    check("есть кнопка «Дальше»", session.find_button("Дальше") is not None)
    check("есть кнопка «Почему?»", session.find_button("Почему") is not None)
    await press("tk:next:0")
    check("перешли к следующему заданию", "Выбери" in session.last_text() or "⌨️" in session.last_text(), session.last_text()[:120])

    print("\n== Задание type (ввод текстом) ==")
    # 1b — ввод глагола byť
    await press("nav:menu")
    await press("nav:start:1b")
    check("пришло задание на ввод", "⌨️" in session.last_text() or "Напиши" in session.last_text(), session.last_text()[:120])
    await send("som")
    check("ответ разобран", "Верно" in session.last_text() or "Почти" in session.last_text(), session.last_text()[:120])
    # Регрессия: ответ текстом нельзя разбирать правкой сообщения ученика —
    # Telegram это запрещает, и разбор молча пропадал. Нужен НОВОЕ сообщение.
    check(
        "разбор пришёл новым сообщением, а не правкой",
        "Верно" in session.last_sent_text() or "Почти" in session.last_sent_text(),
        session.last_sent_text()[:120],
    )

    print("\n== Слова (SRS) ==")
    await press("nav:vocab")
    check("меню слов", "Слова" in session.last_text(), session.last_text()[:100])
    check("кнопка новых слов", session.find_button("Новые слова") is not None)
    await press("vc:mode:new")
    check("карточка слова", "🔤" in session.last_text(), session.last_text()[:100])
    check("есть «Показать перевод»", session.find_button("Показать перевод") is not None)
    await press("vc:reveal:0")
    check("перевод показан", "перевод" not in session.last_text().lower() and len(session.last_text()) > 10, session.last_text()[:100])
    await press("vc:rate:2:0")
    check("оценка принята", "Готово" in session.last_text() or "🔤" in session.last_text(), session.last_text()[:100])
    cards = db.query("SELECT * FROM user_words WHERE user_id = ?", (USER_ID,))
    check("карточка в SRS обновилась", cards and cards[0]["interval"] >= 1, str(cards[:1]))

    print("\n== Прогресс и ошибки ==")
    await press("nav:progress")
    check("статистика", "XP" in session.last_text(), session.last_text()[:120])
    await press("nav:errors")
    check("блок ошибок", "ошибк" in session.last_text().lower(), session.last_text()[:120])

    print("\n== Тренировка ошибок ==")
    await press("nav:drill")
    check("тренажер ошибок собрал задания", any(k in session.last_text() for k in ("🎯", "Выбери", "⌨️", "Напиши", "🧩", "🔗")), session.last_text()[:120])

    print("\n== Настройки ==")
    await press("nav:settings")
    check("меню настроек", "Настройки" in session.last_text(), session.last_text()[:100])
    await press("set:level")
    await press("set:lvl:A2")
    check("уровень сохранён", "A2" in session.last_text(), session.last_text()[:120])

    print("\n== Мини-тест ==")
    await press("nav:menu")
    await press("nav:quiz")
    check("тест собрался", any(k in session.last_text() for k in ("🎯", "Выбери", "⌨️", "Напиши", "🧩", "🔗")), session.last_text()[:120])

    print("\n== Уборка ==")
    await BOT.session.close()
    shutil.rmtree(TMP, ignore_errors=True)
    print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
