"""Тесты API Mini App.

Проверяем: авторизация, выдача контента, оценка ответов на сервере,
что правильные ответы НЕ утекают в приложение, SRS, прогресс, ошибки.

Запуск: python tests/test_miniapp.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="slovak_ma_"))
os.environ["DB_PATH"] = str(TMP / "ma.db")
os.environ["AI_PROVIDER"] = "off"
os.environ["APP_DEV"] = "1"
os.environ["DEV_TELEGRAM_ID"] = "8636653095"
os.environ["TTS_ENABLED"] = "0"

from app import content as content_mod  # noqa: E402
from app import db  # noqa: E402
from app.miniapp_api import bp  # noqa: E402
from app.miniapp_auth import verify_init_data  # noqa: E402
from app.config import CONFIG  # noqa: E402
from flask import Flask  # noqa: E402

TOKEN = CONFIG.bot_token

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


def make_init_data(user_id: int = 8636653095, first_name: str = "Тест") -> str:
    """Настоящая подпись initData — как её делает Telegram."""
    data = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH_test",
        "user": json.dumps({"id": user_id, "first_name": first_name, "language_code": "ru"}),
    }
    data_check = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def main() -> int:
    db.init_db()
    content_mod.CONTENT.load(force=True)
    db.upsert_vocab(content_mod.CONTENT.vocab)

    # Тестовому пользователю нужен доступ (в CI нет ADMIN_IDS)
    from app import licensing

    license_code = licensing.create_keys(1, 0, "miniapp-test")[0]
    granted, _ = licensing.redeem(license_code, 8636653095)
    assert granted, "не удалось выдать тестовый ключ"

    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()
    init_data = make_init_data()
    headers = {"X-Telegram-Init-Data": init_data}

    print("\n== Подпись initData ==")
    check("верная подпись принимается", verify_init_data(init_data, TOKEN) is not None)
    check("испорченная подпись отклоняется", verify_init_data(init_data + "x", TOKEN) is None)
    check(
        "подпись чужого бота отклоняется",
        verify_init_data(init_data, "999:BBB") is None,
    )
    forged = init_data.replace("hash=", "hash=00")
    check("подмена хэша отклоняется", verify_init_data(forged, TOKEN) is None)

    print("\n== Авторизация API ==")
    response = client.get("/api/session", headers=headers)
    check("200 со статусом", response.status_code == 200, str(response.status_code))
    body = response.get_json()
    check("telegram_id верный", body["user"]["telegram_id"] == 8636653095, str(body))

    response = client.get("/api/session", headers={"X-Telegram-Init-Data": "broken=1"})
    check("битая подпись -> 401", response.status_code == 401, str(response.status_code))

    # Дальше проверяем уроки A2: у нового пользователя уровень по умолчанию A1.
    client.post("/api/level", json={"level": "A2"}, headers=headers)

    print("\n== Главный экран ==")
    body = client.get("/api/home", headers=headers).get_json()
    check("есть уровень", body.get("level") == "A2", str(body.get("level")))
    check("есть юниты", len(body["units"]) == 10, str(len(body["units"])))
    check("есть следующий урок", body["next_lesson"] is not None, str(body["next_lesson"]))
    check("счётчик слов есть", "words_due" in body)
    check(
        "уровни A1-B2",
        [x["code"] for x in body.get("levels", [])] == ["A1", "A2", "B1", "B2"],
        str(body.get("levels")),
    )

    print("\n== Юниты и уроки ==")
    body = client.get("/api/units", headers=headers).get_json()
    lessons = [l for u in body["units"] for l in u["lessons"]]
    check("уроков в A2 больше 50", len(lessons) >= 50, str(len(lessons)))
    check("все уроки доступны", all(not l["locked"] for l in lessons))

    print("\n== Урок и утечка ответов ==")
    body = client.get("/api/lesson/1a", headers=headers).get_json()
    check("есть правило", body.get("rule") is not None or body.get("rule") is None)
    check("есть задания", len(body["tasks"]) == 9, str(len(body["tasks"])))
    raw = json.dumps(body, ensure_ascii=False)
    check("в choice нет верного индекса", '"answer"' not in raw)
    check("в type нет списка ответов", '"answers"' not in raw)
    check("в build нет эталона", '"answer"' not in raw)

    print("\n== Ответ: верно ==")
    lesson = content_mod.CONTENT.lesson("1a")
    task = lesson["tasks"][0]
    correct_index = int(task["answer"])
    response = client.post(
        "/api/answer",
        json={"lesson_id": "1a", "task_i": 0, "answer": {"kind": "choice", "value": correct_index}},
        headers=headers,
    )
    check("200", response.status_code == 200, str(response.status_code))
    body = response.get_json()
    check("результат ok", body["result"] == "ok", str(body))
    check("эталон показан", bool(body["expected"]), str(body))
    check("счёт 1/1", body["score"]["correct"] == 1, str(body["score"]))
    check("finished = False", body["finished"] is False)

    print("\n== Ответ: неверно ==")
    wrong_index = (correct_index + 1) % len(task["options"])
    response = client.post(
        "/api/answer",
        json={"lesson_id": "1a", "task_i": 1, "answer": {"kind": "choice", "value": wrong_index}},
        headers=headers,
    )
    body = response.get_json()
    check("результат bad", body["result"] == "bad", str(body))
    check("тег ошибки есть", bool(body["tag"]), str(body))

    print("\n== Защита от переигрывания ==")
    response = client.post(
        "/api/answer",
        json={"lesson_id": "1a", "task_i": 0, "answer": {"kind": "choice", "value": correct_index}},
        headers=headers,
    )
    check("старый task_i -> 409", response.status_code == 409, str(response.status_code))

    print("\n== Завершение урока ==")
    body = client.post("/api/lesson/1a/finish", headers=headers).get_json()
    check("есть счёт", body["total"] == 2, str(body))
    check("есть процент", "percent" in body)
    check("ошибка попала в список", len(body["mistakes"]) == 1, str(body["mistakes"]))
    check("прогресс записан", content_mod.lesson_done(8636653095, "1a"))

    print("\n== Слова (SRS) ==")
    body = client.get("/api/vocab/new?count=5", headers=headers).get_json()
    check("новые слова выданы", len(body["cards"]) == 5, str(len(body["cards"])))
    card = body["cards"][0]
    check("есть sk/ru", bool(card["sk"]) and bool(card["ru"]), str(card))
    body = client.post(
        "/api/vocab/rate", json={"vocab_id": card["id"], "quality": 2}, headers=headers
    ).get_json()
    check("оценка принята", body.get("ok") is True, str(body))
    check("интервал вырос", body["interval"] >= 1, str(body))
    due = client.get("/api/vocab/due?count=10", headers=headers).get_json()
    check("новая карточка не попадает в повторение сразу", len(due["cards"]) == 0, str(len(due["cards"])))
    stored = db.query_one(
        "SELECT * FROM user_words WHERE user_id = ? AND vocab_id = ?", (8636653095, card["id"])
    )
    check("карточка сохранена в SRS", stored is not None, str(stored))
    check("интервал записан", int(stored["interval"]) >= 1, str(stored))
    check("дата следующего повторения впереди", stored["due"] > db.today(), str(stored["due"]))

    print("\n== Свои карточки и словари ==")
    body = client.post(
        "/api/vocab/custom",
        json={"sk": "skúška", "ru": "экзамен"},
        headers=headers,
    ).get_json()
    check("карточка добавлена", body.get("ok") is True, str(body))
    card_id = (body.get("card") or {}).get("id")
    mine = client.get("/api/vocab/mine", headers=headers).get_json()
    check("карточка в моих", any(c["sk"] == "skúška" for c in mine["cards"]), str(mine)[:200])
    check("счётчик своих карточек", mine["stats"]["custom"] >= 1, str(mine["stats"]))

    body = client.post(
        "/api/vocab/custom/bulk",
        json={"text": "čaj — чай\nkáva — кофе\nмусор\n"},
        headers=headers,
    ).get_json()
    check("список добавлен", body.get("added") == 2, str(body))
    check("плохая строка пропущена", body.get("skipped") == 1, str(body))

    body = client.get("/api/vocab/browse?level=B2", headers=headers).get_json()
    check("словарь B2 не пуст", len(body["cards"]) > 50, str(len(body["cards"])))
    check("есть счётчики уровней", len(body["levels"]) == 4, str(body["levels"]))
    first = body["cards"][0]["id"]
    added = client.post("/api/vocab/add", json={"ids": [first]}, headers=headers).get_json()
    check("слово из словаря добавлено", added.get("ok") is True, str(added))

    body = client.delete("/api/vocab/custom/%s" % card_id, headers=headers).get_json()
    check("своя карточка удалена", body.get("ok") is True, str(body))

    print("\n== Прогресс и ошибки ==")
    body = client.get("/api/progress", headers=headers).get_json()
    check("урок засчитан", body["lessons_done"] == 1, str(body["lessons_done"]))
    check("слова учтены", body["words_learned"] >= 1, str(body["words_learned"]))
    check("есть дни", isinstance(body["days"], list))
    check("есть юниты с прогрессом", len(body["units"]) == 10)
    body = client.get("/api/errors", headers=headers).get_json()
    check("есть тег ошибки", len(body["tags"]) >= 1, str(body["tags"]))
    check("есть человеческое название", bool(body["tags"][0]["title_ru"]))

    print("\n== Тренировка ошибок и тест ==")
    body = client.post("/api/drill", headers=headers).get_json()
    check("drill вернул задания", len(body.get("tasks", [])) >= 1, str(body)[:120])
    body = client.post("/api/quiz", headers=headers).get_json()
    check("тест вернул задания", len(body.get("tasks", [])) >= 1, str(body)[:120])
    check("в тесте тоже нет ответов", '"answer"' not in json.dumps(body, ensure_ascii=False))

    print("\n== ИИ-запросы без ключа ==")
    response = client.post("/api/writing", json={"text": "Som z Ruska"}, headers=headers)
    check("writing -> 503", response.status_code == 503, str(response.status_code))
    response = client.post("/api/speaking", json={"text": "Dobrý deň"}, headers=headers)
    check("speaking -> 503", response.status_code == 503, str(response.status_code))

    print("\n== Озвучка ==")
    response = client.get("/api/speech?text=Dobry%20den", headers=headers)
    check("озвучка отключена -> 404", response.status_code == 404, str(response.status_code))

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nИтого: %d ok, %d fail" % (PASSED, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
