# Контракт API для Mini App (Telegram Web App)

Бэкенд: Flask, префикс `/api`. Фронтенд: `miniapp/index.html` (один файл).

## Авторизация

Каждый запрос несёт заголовок:

```
X-Telegram-Init-Data: <строка initData из Telegram WebApp>
```

Бэкенд проверяет подпись HMAC-SHA256 (ключ — токен бота) и достаёт
`telegram_id`. Неверная подпись → `401 {"error": "unauthorized"}`.
В режиме разработки (`APP_DEV=1` в `.env`) допускается запрос без initData —
тогда берётся `DEV_TELEGRAM_ID` (по умолчанию 8636653095). Это нужно, чтобы
открывать приложение в обычном браузере.

## Эндпоинты

### GET /api/session
```json
{"user": {"telegram_id": 8636653095, "first_name": "Ученик", "level": "A1",
          "xp": 120, "streak": 3, "best_streak": 5},
 "app": {"title": "Slovencina", "version": "1.0"}}
```

### GET /api/home
```json
{"level": "A1", "xp": 120, "streak": 3, "best_streak": 5,
 "lessons_done": 4, "lessons_total": 41,
 "tasks_done": 57, "tasks_total": 350, "accuracy": 82,
 "words_learned": 120, "words_due": 8,
 "units": [{"n": 1, "title": "Знакомство", "desc": "...", "lessons_done": 2, "lessons_total": 5}],
 "next_lesson": {"id": "1a", "title": "Знакомство с Slovak_is_easy", "unit": 1},
 "weak_tags": [{"tag": "diacritics", "count": 5, "title_ru": "потерянная диакритика"}]}
```

### GET /api/units
```json
{"units": [{"n": 1, "title": "Знакомство", "desc": "...",
  "lessons": [{"id": "1a", "title": "...", "sub": "...", "done": false,
               "tasks": 8, "locked": false}]}]}
```

### GET /api/lesson/<lesson_id>
```json
{"id": "1a", "title": "...", "sub": "...", "unit": 1,
 "rule": {"title": "Глагол byť (быть)", "p": ["абзац по-русски"],
          "rows": [["ja (я)", "som"], ["ty (ты)", "si"]],
          "ex": ["Som z Ruska. - Я из России."]},
 "tasks": [
   {"i": 0, "kind": "choice", "prompt": "Вопрос по-русски", "options": ["a", "b", "c"]},
   {"i": 1, "kind": "type",   "prompt": "Вставь нужную форму", "sk": "Ja ___ z Ruska."},
   {"i": 2, "kind": "build",  "prompt": "Собери: «Меня зовут Петер.»", "words": ["Volám", "sa", "Peter", "som"]},
   {"i": 3, "kind": "match",  "prompt": "Найди пары", "pairs": [["Dobrý deň", "Здравствуйте"]]}
 ]}
```
**Важно:** правильные ответы в ответе НЕ присылаются (choice — без индекса
верного, type — без списка ответов, build — без эталонной фразы). Оценка
происходит на сервере.

### POST /api/answer
Запрос:
```json
{"lesson_id": "1a", "task_i": 0,
 "answer": {"kind": "choice", "value": 1}}
```
Значения `value` по типам:
* `choice` → индекс выбранного варианта (number)
* `type` → строка с ответом
* `build` → массив слов в выбранном порядке `["Nie", "som", "unavený"]`
* `match` → объект соответствий `{"Dobrý deň": "Здравствуйте"}`

Ответ:
```json
{"result": "ok", "result_ru": "Верно", "expected": "sú", "given": "som",
 "explanation": "Текст объяснения по-русски или null",
 "missing_accents": ["á", "ť"], "tag": "diacritics",
 "score": {"correct": 3, "total": 7}, "xp": 2, "finished": false}
```
`result`: `ok` | `typo` | `accents` | `bad`.
`result_ru`: «Верно» | «Почти (опечатка)» | «Почти (диакритика)» | «Неверно».
`missing_accents` — массив букв, которые потерялись (для `accents`).
`explanation` — если в контенте у задания есть поле `x`, иначе null.
`finished` — true, если это было последнее задание урока.

### POST /api/lesson/<lesson_id>/finish
```json
{"correct": 5, "total": 7, "percent": 71, "xp": 12, "streak": 3,
 "mistakes": [{"given": "sú", "expected": "som", "tag": "verb_form"}],
 "next_lesson": {"id": "1b", "title": "...", "unit": 1}}
```

### GET /api/vocab/due?count=20 и GET /api/vocab/new?count=10
```json
{"cards": [{"id": 12, "sk": "dobrý deň", "ru": "здравствуйте",
            "level": "A1", "group": "ОСНОВНОЕ", "state": "review", "interval": 3}]}
```

### POST /api/vocab/rate
Запрос `{"vocab_id": 12, "quality": 2}` (quality: 0 не знаю, 1 с трудом, 2 нормально, 3 легко).
Ответ `{"ok": true, "interval": 7, "due": "2026-11-25", "remaining": 5}`.

### GET /api/progress
```json
{"xp": 120, "streak": 3, "best_streak": 5,
 "lessons_done": 4, "lessons_total": 41, "tasks_done": 57, "accuracy": 82,
 "words_learned": 120, "words_due": 8,
 "days": [{"day": "2026-11-18", "xp": 30, "tasks": 12, "correct": 10}],
 "units": [{"n": 1, "title": "Знакомство", "done": 2, "total": 5}],
 "errors": [{"tag": "diacritics", "count": 5, "title_ru": "потерянная диакритика"}]}
```

### GET /api/errors
```json
{"tags": [{"tag": "diacritics", "count": 5, "title_ru": "потерянная диакритика"}],
 "recent": [{"lesson_id": "1b", "task_i": 3, "given": "sú", "expected": "som",
             "tag": "verb_form", "created_at": "2026-11-18T19:47:00"}]}
```

### POST /api/drill
Возвращает как `GET /api/lesson/<id>`, но `id` = `"drill"` и `title` = «Тренировка ошибок».

### POST /api/quiz
Возвращает `{"title": "Мини-тест", "tasks": [<такие же задания, как в lesson>], "total": 10}`.

### GET /api/speech?text=<urlencoded>
Отдаёт mp3 (`audio/mpeg`). Если озвучка недоступна — `404 {"error": "no_tts"}`.

### POST /api/writing
Запрос `{"text": "..."}` → разбор текста ИИ:
```json
{"score": 82, "comment": "...", "errors": [{"wrong": "...", "right": "...", "rule": "..."}],
 "corrected": "...", "next_task": "...", "new_words": [{"sk": "...", "ru": "..."}]}
```
Если ИИ выключен — `{"error": "ai_disabled"}`.

### POST /api/speaking
Запрос `{"text": "..."}` → реплика ИИ:
```json
{"reply": "...", "translation": "...", "correction": "...", "hint": "..."}
```
Если ИИ выключен — `{"error": "ai_disabled"}`.

## Коды ответов

* `200` — успех
* `401` — невалидный initData
* `404` — не найдено (`{"error": "not_found"}`)
* `500` — ошибка (`{"error": "..."}`)
