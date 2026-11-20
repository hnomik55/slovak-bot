# Бесплатный хостинг: PythonAnywhere (веб-приложение + вебхуки)

Почему именно так: бесплатные тарифы PythonAnywhere дают **постоянно работающее
веб-приложение**, а наш бот в режиме `webhook` отвечает именно через веб.
Платить не нужно.

Проверено на логике, которую уже реализовано и протестировано:
`tests/test_webhook.py` — 9 проверок режима webhook.

---

## 1. Залей код на GitHub

На бесплатном тарифе PythonAnywhere нет SSH и rsync — код туда попадает
через `git clone` прямо в консоли.

```bash
# на твоём ПК: создай пустой репозиторий на github.com и выполни
cd D:\Slovakia\bot
git init
git add .
git commit -m "Slovencina: telegram-бот для словацкого"
git remote add origin https://github.com/<твой-логин>/<репозиторий>.git
git branch -M main
git push -u origin main
```

`.env` в репозиторий не попадёт (он в `.gitignore`) — токен останется только у тебя.

## 2. Создай веб-приложение на PythonAnywhere

1. Регистрация: **pythonanywhere.com** → Free.
2. Dashboard → **Web** → **Add a new web app** → Python 3.11 → **Next**.
3. В поле **Static files** / **Working directory** укажи папку с кодом.
4. Открой **Bash console** и выполни:

```bash
cd ~
git clone https://github.com/<твой-логин>/<репозиторий>.git slovak-bot
cd slovak-bot
~/.virtualenvs/<имя-venv>/bin/pip install -r requirements.txt
```

> Имя venv видно в Dashboard → Web → «Virtualenv».

## 3. WSGI-файл

PythonAnywhere по умолчанию запускает `flask_app.py`. Замени его содержимое:

```python
import os
import sys

PROJECT = "/home/<твой-логин>/slovak-bot"
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from wsgi import app  # noqa: E402
```

## 4. Переменные окружения

Dashboard → **Web** → **Environment variables** (или просто положи `.env` в папку проекта — наш конфиг читает `.env` сам):

```
BOT_TOKEN=9076534418:AAGU...
ADMIN_IDS=8636653095
MODE=webhook
WEBHOOK_BASE_URL=https://<твой-логин>.pythonanywhere.com
WEBHOOK_SECRET=<любая длинная строка>
AI_PROVIDER=off
```

## 5. Зарегистрируй вебхук

В Bash console:

```bash
cd ~/slovak-bot
~/.virtualenvs/<venv>/bin/python tools/set_webhook.py set https://<твой-логин>.pythonanywhere.com
```

Скрипт сам сгенерирует `WEBHOOK_SECRET`, запишет его в `.env` и покажет
`getWebhookInfo` для проверки.

## 6. Проверь

Открой в браузере `https://<твой-логин>.pythonanywhere.com/health` — должен быть JSON `{"ok": true}`.
Потом открой бота в Telegram и нажми `/start`.

## 7. Напоминания (cron)

Чтобы напоминание в 21:00 приходило, даже когда ты весь день не писал боту,
добавь **Scheduled task** (Dashboard → Tasks):

```
Command:  /home/<твой-логин>/.virtualenvs/<venv>/bin/python /home/<твой-логин>/slovak-bot/tools/cron.py
Time:     21:00 (Europe/Bratislava), раз в день
```

`tools/cron.py` дёргает `/cron/<секрет>` и бот отправляет напоминание, если
ты сегодня ещё не занимался.

## 8. Ключи доступа: почему «ключ не найден»

База бота на сервере и база на домашнем ПК — **разные файлы**.
`data/slovak.db` в git не попадает, поэтому ключи, созданные на ПК
(`python tools\generate_keys.py 100`), на PythonAnywhere не появляются:
сервер отвечает «Ключ не найден».

Перенести партию на сервер можно тремя способами:

1. **Из бота** (проще всего): пришли файл `keys-*.txt` или `keys-*.csv`
   ответом на команду `/admin_key import`. Ключи добавятся, повторный
   импорт безопасен.
2. **Файлом через Files**: загрузи `data/keys/licenses.json` (снимок
   состояния лицензий) в папку `data/keys/` на PythonAnywhere и нажми
   **Reload** — при старте бот сам подхватит ключи и активации.
3. **С ПК по HTTP**, если на сервере задан `WEBHOOK_SECRET`:

   ```
   curl -X POST https://<логин>.pythonanywhere.com/admin/keys \
        -H "X-Admin-Token: <WEBHOOK_SECRET>" \
        -H "Content-Type: application/json" \
        -d '{"action":"import","text":"<ключи>"}'
   ```

Проверить, что видит сервер: `/admin_key stats` в боте.
Выгрузить все ключи из серверной базы: `/admin_key export`.

При каждом создании и погашении ключа состояние сохраняется в
`data/keys/licenses.json` рядом с базой, поэтому пересоздание базы
больше не теряет партию.

---

## Другие бесплатные варианты

| Платформа | Что сделать | Нюанс |
|---|---|---|
| **Render** | Web Service, `pip install -r requirements.txt`, Start: `gunicorn --workers 1 --bind 0.0.0.0:$PORT wsgi:app` | Бесплатный инстанс засыпает через 15 мин простоя, просыпается за 30–60 сек |
| **Railway** | То же + Dockerfile из `deploy/` | Даёт $5/мес кредита, хватает с запасом |
| **Fly.io** | То же + Dockerfile | Нужна карта; инстансы засыпают при простое |
| **Oracle Cloud Always Free** | Обычный VPS + `deploy/install.sh` | Полностью бесплатно, но регистрация с капчами |

## Чего НЕ делать

Не ставь бот в GitHub Actions на постоянную работу: лимит 2 000 минут в месяц
против 43 200 нужных, и непрерывные jobs нарушают правила GitHub.
