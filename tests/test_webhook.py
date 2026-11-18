"""Проверка режима вебхука: Flask-приложение принимает апдейт и бот отвечает.

Сеть не используется: подменяем http-сессию бота на заглушку.

Запуск: python tests/test_webhook.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="slovak_wh_"))
os.environ["DB_PATH"] = str(TMP / "wh.db")
os.environ["AI_PROVIDER"] = "off"
os.environ["TTS_ENABLED"] = "0"
os.environ["STT_ENABLED"] = "0"
os.environ["WEBHOOK_SECRET"] = "testsecret123"

from aiogram.client.bot import Bot  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, SendVoice  # noqa: E402
from aiogram.methods.base import Response  # noqa: E402
from aiogram.types import Chat, Message  # noqa: E402

from app import content as content_mod  # noqa: E402
from app import db  # noqa: E402
from app.webhook_app import create_app  # noqa: E402
from bot import build_dispatcher  # noqa: E402

TOKEN = "123456789:AAEhBOweik6ad9r_QXvcS7SFvlG1234567890"
CHAT_ID = 777
USER_ID = 777


class FakeSession:
    def __init__(self) -> None:
        self.calls: List[Any] = []

    async def __call__(self, bot: Bot, method: Any, timeout: Optional[int] = None) -> Any:
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            result: Any = True
        elif isinstance(method, (SendMessage, EditMessageText, SendVoice)):
            result = Message(
                message_id=100 + len(self.calls),
                date=datetime.now(),
                chat=Chat(id=CHAT_ID, type="private"),
                text=getattr(method, "text", None),
            )
        else:
            result = None
        return Response[method.__returning__](ok=True, result=result)

    async def close(self) -> None:
        pass

    def texts(self) -> List[str]:
        return [c.text for c in self.calls if isinstance(c, (SendMessage, EditMessageText)) and c.text]


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


def main() -> int:
    session = FakeSession()
    bot = Bot(token=TOKEN, session=session)
    db.init_db()
    content_mod.CONTENT.load(force=True)
    db.upsert_vocab(content_mod.CONTENT.vocab)

    dp = build_dispatcher()
    app = create_app(bot, dp)
    client = app.test_client()

    print("\n== Вебхук принимает апдейт ==")
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": int(datetime.now().timestamp()),
            "chat": {"id": CHAT_ID, "type": "private"},
            "from": {"id": USER_ID, "is_bot": False, "first_name": "Тест"},
            "text": "/start",
        },
    }
    response = client.post("/bot/testsecret123", json=payload)
    check("ответ 200", response.status_code == 200, str(response.status_code) + " " + response.get_data(as_text=True))
    check("бот обработал апдейт", bool(session.texts()), str(session.texts()[:1]))
    check("бот поздоровался", any("словацкого" in t.lower() for t in session.texts()), str(session.texts()[:1]))

    print("\n== Неверный секрет отклоняется ==")
    response = client.post("/bot/wrongsecret", json=payload)
    check("ответ 403", response.status_code == 403, str(response.status_code))

    print("\n== Callback-апдейт ==")
    before = len(session.calls)
    payload_cb = {
        "update_id": 2,
        "callback_query": {
            "id": "2",
            "from": {"id": USER_ID, "is_bot": False, "first_name": "Тест"},
            "chat_instance": "ci",
            "data": "nav:lessons",
            "message": {
                "message_id": 2,
                "date": int(datetime.now().timestamp()),
                "chat": {"id": CHAT_ID, "type": "private"},
                "text": "меню",
            },
        },
    }
    response = client.post("/bot/testsecret123", json=payload_cb)
    check("ответ 200", response.status_code == 200, str(response.status_code))
    check("меню отрисовано", len(session.calls) > before, "%d -> %d" % (before, len(session.calls)))

    print("\n== Health и cron ==")
    response = client.get("/health")
    check("health отвечает", response.status_code == 200 and response.get_json().get("ok") is True)
    response = client.get("/cron/testsecret123")
    check("cron отвечает", response.status_code == 200, str(response.status_code))
    response = client.get("/cron/wrong")
    check("cron с чужим секретом отклонён", response.status_code == 403, str(response.status_code))

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
