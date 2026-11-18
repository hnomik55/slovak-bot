"""WSGI-точка входа для бесплатных веб-хостингов.

    gunicorn --workers 1 --bind 0.0.0.0:8000 wsgi:app
    uwsgi --http :8000 --module wsgi:app

Один воркер: состояние бота (FSM, http-сессия) живёт в процессе.
"""

from app.webhook_app import build_wsgi_app

app = build_wsgi_app()
