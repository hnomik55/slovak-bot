# Образ для деплоя бота (Docker / Railway / Fly.io / любой VPS с Docker).
#
#   docker build -t slovak-bot .
#   docker run -d --name slovak-bot --restart always \
#       --env-file .env -v slovak-data:/app/data slovak-bot

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg нужен faster-whisper для декодирования голоса
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/data

VOLUME ["/app/data"]
CMD ["python", "bot.py"]
