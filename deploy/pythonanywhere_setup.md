# Всё на PythonAnywhere: бот + API + приложение

Один бесплатный веб-хостинг вместо трёх костылей (ПК + туннель + Actions).
Бот отвечает **мгновенно**, приложение работает **всегда**, твой ПК не нужен.

Тариф Free: без карты, постоянно работающее веб-приложение, 512 МБ RAM.
Бот в режиме webhook почти не ест ресурсов — он просыпается только на сообщения.

---

## 1. Регистрация (2 минуты)

**pythonanywhere.com** → Sign up (e-mail + пароль) → Free.

## 2. Загрузи код

В консоли **Bash** на pythonanywhere:

```bash
cd ~
git clone https://github.com/hnomik55/slovak-bot.git
cd slovak-bot
```

Создай виртуальное окружение и поставь зависимости:

```bash
~/.virtualenvs/slovak-bot/bin/pip install -r requirements.txt
```

> Имя venv (`slovak-bot`) придумай сам — его потом надо будет указать в панели.

## 3. Переменные окружения

В панели: **Account → Environment variables** (или файл `~/slovak-bot/.env`):

```
BOT_TOKEN=9076534418:AAGU97JIP-D4UHEy-TcNtNGjbQ7dqPr-w0k
ADMIN_IDS=8636653095
MODE=webhook
WEBHOOK_BASE_URL=https://<твой-логин>.pythonanywhere.com
WEBHOOK_SECRET=<любая длинная строка>
AI_PROVIDER=off
```

И на той же странице создай **Web app**:
* Domain: `hnomik55.pythonanywhere.com`
* Framework: Flask
* Edit WSGI file → впиши:

```python
import os, sys
PROJECT = "/home/<твой-логин>/slovak-bot"
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
os.environ.setdefault("MODE", "webhook")

from wsgi import app  # noqa: E402
```

> Замени `<твой-логин>` на свой (это часть адреса pythonanywhere.com).

## 4. Регистрация вебхука (один раз)

В Bash-консоли:

```bash
cd ~/slovak-bot
~/.virtualenvs/slovak-bot/bin/python tools/set_webhook.py set https://<твой-логин>.pythonanywhere.com
```

Скрипт сгенерирует `WEBHOOK_SECRET`, запишет его в `.env` и покажет `getWebhookInfo`.

## 5. Приложение

Тут два варианта:

**А. Оставить на GitHub Pages** (уже работает) — тогда `docs/config.json` должен
содержать адрес API:

```json
{"api_base": "https://<твой-логин>.pythonanywhere.com"}
```

**Б. Отдавать с самого PythonAnywhere** — тогда в `wsgi.py` добавь раздачу папки `docs`
и положи `docs/config.json` с `"api_base": ""` (пустым — значит «тот же домен»).

## 6. Напоминания

Бот в webhook-режиме не крутит планировщик. Для ежедневного напоминания создай
**Scheduled task** (панель → Tasks → daily):

```
/home/<твой-логин>/.virtualenvs/slovak-bot/bin/python /home/<твой-логин>/slovak-bot/tools/cron.py
```
время: 21:00, часовой пояс Europe/Bratislava.

## 7. Отключи старые схемы

Когда всё заработает:

```bash
cd D:\Slovakia\bot
python tools\bot_mode.py local   # локальный бот в чате — выключить
```

и удали workflow `slovak bot` в GitHub (Actions → slovak bot → ⋮ → Delete),
чтобы два бота не дрались за один токен.

---

## Проверка

```bash
python tools\check_telegram.py          # с твоего ПК: Bot API доступен?
curl -s https://<твой-логин>.pythonanywhere.com/health
```

Должно быть `{"mode":"webhook","ok":true}`.
