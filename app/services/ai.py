"""Слой ИИ.

Провайдер-agnostic: работает с любым OpenAI-совместимым endpoint (OpenAI,
DeepSeek, Qwen, Mistral, Ollama, LM Studio, GigaChat) и с нативным Anthropic API.
Ключи и модель — в .env.

ИИ в боте делает ровно четыре вещи:
  1) проверяет свободный текст (письмо) и объясняет ошибки;
  2) объясняет конкретное задание, если ученик спросил «почему?»;
  3) генерирует недостающие юниты/задания в том же формате, что и ваш контент;
  4) ведёт диалог и проверяет устную речь.
Всё остальное (проверка ответов, SRS, статистика) считается локально — бесплатно и мгновенно.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import httpx

from app.config import CONFIG

SYSTEM_BASE = """Ты — Словčina, учитель словацкого языка для русскоязычного ученика
(взрослый, цель — A2/B1 и поступление в вуз в Словакии).

Жесткие правила:
1. Объясняешь по-русски, примеры и целевые фразы — по-словацки (с диакритикой!).
2. Не упрощаешь язык: учишь разговорный и письменный словацкий, а не «детский».
3. Ошибку называешь прямо, без заискивания, но без унижения: «вот как надо — и почему».
4. Проверяешь грамматику: согласование лица (som/si/je/sme/ste/sú), sa-конструкцию,
   падежи (винительный: -a -> -u у женского рода, +a у живого мужского),
   предложный (v/na/o/po), родительный (2-4 -> roky, 5+ -> rokov),
   один глагол в предложении, порядок слов (подлежащее -> глагол -> дополнение).
5. Диакритика обязательна: á ä č ď é í ĺ ľ ň ó ô ŕ š ť ú ý ž.
6. Если попросили JSON — отвечай ТОЛЬКО валидным JSON без пояснений и без ``` .
"""


def _extract_json(text: str) -> Optional[Any]:
    """Достаёт JSON из ответа модели (терпит ```json ... ``` и болтовню вокруг)."""
    if not text:
        return None
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Ищем первый {...} или [...]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = raw.find(open_ch)
        while start >= 0:
            depth = 0
            for i in range(start, len(raw)):
                if raw[i] == open_ch:
                    depth += 1
                elif raw[i] == close_ch:
                    depth -= 1
                    if depth == 0:
                        candidate = raw[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
            start = raw.find(open_ch, start + 1)
    return None


class AIService:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def enabled(self) -> bool:
        return CONFIG.ai_enabled

    @property
    def fast_model(self) -> str:
        return CONFIG.ai_model_fast or CONFIG.ai_model

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=CONFIG.ai_timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    async def chat(
        self,
        user_prompt: str,
        system: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 1200,
    ) -> str:
        """Один запрос к модели. Возвращает текст ответа (или "" при ошибке)."""
        if not self.enabled:
            return ""
        messages: List[Dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": user_prompt})
        model = model or CONFIG.ai_model
        temperature = CONFIG.ai_temperature if temperature is None else temperature

        try:
            if CONFIG.ai_provider == "anthropic":
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system or SYSTEM_BASE,
                    "messages": [
                        {"role": m["role"], "content": m["content"]} for m in messages
                    ],
                }
                headers = {
                    "x-api-key": CONFIG.ai_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
                url = CONFIG.ai_base_url.rstrip("/") + "/messages"
            else:
                payload = {
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system or SYSTEM_BASE}] + messages,
                }
                headers = {
                    "Authorization": "Bearer " + CONFIG.ai_api_key,
                    "content-type": "application/json",
                }
                url = CONFIG.ai_base_url.rstrip("/") + "/chat/completions"

            client = await self.client()
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            if CONFIG.ai_provider == "anthropic":
                parts = data.get("content") or []
                return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            choices = data.get("choices") or []
            if not choices:
                return ""
            return (choices[0].get("message") or {}).get("content", "").strip()
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            return "__error__:%s" % exc

    async def json_call(
        self,
        user_prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        retries: int = 2,
    ) -> Optional[Any]:
        """Запрос с ожиданием JSON. None — если модель ответила мусором или ИИ выключен."""
        if not self.enabled:
            return None
        prompt = user_prompt + "\n\nОТВЕТ СТРОГО В JSON, без текста вокруг."
        for attempt in range(retries + 1):
            raw = await self.chat(prompt, system=system, model=model, max_tokens=max_tokens)
            if raw.startswith("__error__"):
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            parsed = _extract_json(raw)
            if parsed is not None:
                return parsed
        return None

    # ------------------------------------------------------------------ #
    # 1. Проверка письма
    # ------------------------------------------------------------------ #
    async def check_writing(
        self,
        text: str,
        level: str,
        task: str = "",
        weak_tags: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        weak = ", ".join(weak_tags or []) or "нет"
        prompt = f"""Проверь текст ученика на словацком.

Уровень: {level}
Задание: {task or "(свободный текст)"}
Известные слабые места ученика: {weak}

Текст ученика:
---
{text}
---

Верни JSON:
{{
  "score": 0-100,
  "corrected": "исправленный текст целиком (если ошибок нет — исходный текст)",
  "errors": [{{"wrong": "фрагмент как у ученика", "right": "правильный вариант", "rule": "объяснение по-русски, 1 предложение", "tag": "тег ошибки: diacritics|verb_form|accusative|locative|genitive|future|spelling|extra_words|missing_words|agreement|sa_verb|case|order|grammar"}}],
  "new_words": [{{"sk": "словацкое слово", "ru": "перевод"}}],
  "comment": "2-3 предложения: что удалось, что подтянуть. Без похвалы в пустоту.",
  "next_task": "одно конкретное задание на словацком (1 предложение) — что делать дальше"
}}
Слов на Slovak с диакритикой. Не выдумывай ошибки, которых нет."""
        data = await self.json_call(prompt, system=SYSTEM_BASE, model=CONFIG.ai_model, max_tokens=2500)
        if isinstance(data, dict):
            return data
        return None

    # ------------------------------------------------------------------ #
    # 2. Объяснение задания
    # ------------------------------------------------------------------ #
    async def explain_task(self, task: Dict[str, Any], given: str, expected: str) -> str:
        prompt = f"""Ученик не смог ответить на задание.

Тип задания: {task.get('kind')}
Вопрос: {task.get('prompt') or task.get('sk')}
Ответ ученика: {given or '(пусто)'}
Правильный ответ: {expected}

Объясни по-русски, коротко (2-4 предложения): что требовалось, почему правильный ответ такой,
и какое правило словацкого за этим стоит. Без воды."""
        return await self.chat(prompt, system=SYSTEM_BASE, model=self.fast_model, max_tokens=600)

    # ------------------------------------------------------------------ #
    # 3. Генерация урока (для юнитов 8-10, которых нет в тренажёре)
    # ------------------------------------------------------------------ #
    async def generate_lesson(
        self, unit_no: int, topic: str, level: str = "A1", task_count: int = 12
    ) -> Optional[Dict[str, Any]]:
        prompt = f"""Сгенерируй урок словацкого.

Юнит: {unit_no}
Тема: {topic}
Уровень: {level}

Верни JSON строго такого вида:
{{
  "sub": "подзаголовок в одно предложение по-русски",
  "rule": {{
     "title": "заголовок правила по-русски",
     "p": ["абзац правила по-русски", "..."],
     "rows": [["левая ячейка", "правая ячейка"]],
     "ex": ["пример по-словацки — перевод по-русски"]
  }},
  "tasks": [
     {{"t": "choice", "q": "вопрос по-русски", "o": ["вариант1", "вариант2", "вариант3"], "a": 0, "x": "объяснение по-русски"}},
     {{"t": "type", "q": "вопрос по-русски", "sk": "Я ___ из России.", "a": ["som"]}},
     {{"t": "build", "q": "Собери: «...»", "w": ["Som", "z", "Ruska"], "a": "Som z Ruska"}},
     {{"t": "match", "q": "Найди пары", "p": [["словацкое", "русское"]]}}
  ]
}}

Правила:
- {task_count} заданий, примерно поровну всех четырёх типов.
- В "choice" правильный вариант всегда a: 0, варианты перемешаны, 3 варианта.
- В "type" ответ — слово/фраза на словацком, a — массив допустимых вариантов.
- Все примеры с правильной диакритикой.
- Уровень сложности — {level}, грамматика темы «{topic}»."""
        data = await self.json_call(prompt, system=SYSTEM_BASE, model=CONFIG.ai_model, max_tokens=4000)
        if isinstance(data, dict) and data.get("tasks"):
            return data
        return None

    # ------------------------------------------------------------------ #
    # 4. Диалог (говорение)
    # ------------------------------------------------------------------ #
    async def dialogue_turn(
        self,
        history: List[Dict[str, str]],
        user_text: str,
        level: str = "A1",
        topic: str = "",
    ) -> Optional[Dict[str, Any]]:
        prompt = f"""Ты ведёшь диалог на словацком с учеником уровня {level}.
Тема: {topic or 'свободная беседа'}

Последняя реплика ученика:
{user_text}

Верни JSON:
{{
  "reply": "твоя реплика на словацком (1-2 предложения)",
  "translation": "перевод на русский",
  "correction": "если в реплике ученика есть ошибка — исправленный вариант и короткое объяснение по-русски; иначе пустая строка",
  "hint": "подсказка по-русски, что сказать дальше (одна фраза)"
}}
Уровень A1: простые фразы, короткие предложения. Ошибки ученика исправляй мягко и кратко."""
        data = await self.json_call(prompt, system=SYSTEM_BASE, model=self.fast_model, max_tokens=900)
        if isinstance(data, dict):
            return data
        return None

    # ------------------------------------------------------------------ #
    # 5. Текст для чтения + вопросы
    # ------------------------------------------------------------------ #
    async def reading_material(self, level: str = "A1", topic: str = "") -> Optional[Dict[str, Any]]:
        prompt = f"""Сделай текст для чтения на словацком.

Уровень: {level}
Тема: {topic or 'повседневная жизнь'}

Верни JSON:
{{
  "title": "заголовок по-словацки",
  "text": "текст на словацком, 80-120 слов, бытовая тема",
  "translation": "перевод на русский",
  "questions": [{{"q": "вопрос по-русски к тексту", "o": ["да", "нет", "не знаю"], "a": 0, "x": "ответ с цитатой из текста"}}],
  "new_words": [{{"sk": "слово", "ru": "перевод"}}]
}}
Текст — естественный словацкий, с диакритикой, без чешских слов."""
        data = await self.json_call(prompt, system=SYSTEM_BASE, model=CONFIG.ai_model, max_tokens=2500)
        if isinstance(data, dict) and data.get("text"):
            return data
        return None

    # ------------------------------------------------------------------ #
    # 6. Предложения для аудирования (бот озвучивает их через TTS)
    # ------------------------------------------------------------------ #
    async def listening_sentences(self, level: str = "A1", topic: str = "", count: int = 5) -> List[str]:
        prompt = f"""Дай {count} коротких предложений/микро-диалогов на словацком для аудирования.
Уровень: {level}. Тема: {topic or 'повседневность'}.

Верни JSON: {{"sentences": ["...","..."]}}
Каждое предложение — 1 строка, до 12 слов, с диакритикой. Без перевода."""
        data = await self.json_call(prompt, system=SYSTEM_BASE, model=self.fast_model, max_tokens=900)
        if isinstance(data, dict) and isinstance(data.get("sentences"), list):
            return [str(s) for s in data["sentences"]][:count]
        return []

    # ------------------------------------------------------------------ #
    # 7. Вопросы для мини-теста
    # ------------------------------------------------------------------ #
    async def quiz_questions(
        self, level: str = "A1", weak_tags: Optional[List[str]] = None, count: int = 8
    ) -> List[Dict[str, Any]]:
        weak = ", ".join(weak_tags or []) or "нет"
        prompt = f"""Собери мини-тест по словацкому.

Уровень: {level}
Слабые места ученика (сделай по ним 2-3 вопроса): {weak}

Верни JSON: {{"questions": [{{"q": "вопрос по-русски", "o": ["a","b","c"], "a": 0, "x": "объяснение"}}]}}
Ровно {count} вопросов, все на словацком, с диакритикой."""
        data = await self.json_call(prompt, system=SYSTEM_BASE, model=CONFIG.ai_model, max_tokens=2500)
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            return data["questions"][:count]
        return []


AI = AIService()
