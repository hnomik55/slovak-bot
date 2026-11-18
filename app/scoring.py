"""Проверка ответов.

Строгие правила словацкого боту нужны, но жёсткость убивает мотивацию, поэтому
оценка трёхступенчатая:

  ok      — ответ верный
  typo    — верно по сути, но опечатка (1–2 символа)
  accents — верно, но потеряна/заменена диакритика (ě/ä/ô/ť/ď/ľ/ĺ/ŕ)
  bad     — неверно

"accents" отдельно от "bad" — это ровно та ошибка, что повторяется у ученика
(osemnást вместо osemnásť, ahoj без ä), и её надо называть, а не прятать.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

PUNCT = re.compile(r"[,.;:!?\"'«»()\[\]—\-…]")
SPACES = re.compile(r"\s+")

RESULT_OK = "ok"
RESULT_TYPO = "typo"
RESULT_ACCENTS = "accents"
RESULT_BAD = "bad"

ACCENT_CHARS = "áäčďéíĺľňóôŕšťúýžÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ"


def norm(text: str) -> str:
    """Нормализация для сравнения: нижний регистр, без пунктуации, единые пробелы."""
    text = (text or "").lower().replace(" ", " ")
    text = PUNCT.sub(" ", text)
    return SPACES.sub(" ", text).strip()


def strip_accents(text: str) -> str:
    """Убирает диакритику: 'osemnásť' -> 'osemnast'."""
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def grade_text(given: str, answers: Sequence[str]) -> Tuple[str, Optional[str]]:
    """Возвращает (результат, эталонный ответ). Эталон — первый подходящий вариант."""
    g = norm(given)
    if not g:
        return RESULT_BAD, None

    norms = [(norm(a), a) for a in answers if a]
    for n, original in norms:
        if n == g:
            return RESULT_OK, original

    # Диакритика: потеряна или заменена (é->e, ch->č и т.п.)
    g_strip = strip_accents(g)
    for n, original in norms:
        if strip_accents(n) == g_strip:
            return RESULT_ACCENTS, original

    # Опечатка: 1–2 символа при длине от 4
    if len(g) >= 4:
        for n, original in norms:
            distance = levenshtein(g, n)
            if distance <= 1 or (distance <= 2 and len(n) >= 8):
                return RESULT_TYPO, original

    # Порядок слов (частая ошибка: «Mám mama» вместо «Mám mamu» не ловится, но «som z» vs «z som» — ловится)
    for n, original in norms:
        if sorted(g.split()) == sorted(n.split()):
            return RESULT_TYPO, original

    return RESULT_BAD, (norms[0][1] if norms else None)


def grade_choice(given_index: int, correct_index: int) -> str:
    return RESULT_OK if given_index == correct_index else RESULT_BAD


def grade_build(given_words: Sequence[str], answer: str) -> Tuple[str, Optional[str]]:
    """Сборка фразы: слова должны идти в нужном порядке."""
    g = norm(" ".join(given_words))
    a = norm(answer)
    if not g:
        return RESULT_BAD, answer
    if g == a:
        return RESULT_OK, answer
    if strip_accents(g) == strip_accents(a):
        return RESULT_ACCENTS, answer
    if sorted(g.split()) == sorted(a.split()):
        # те же слова, другой порядок
        return RESULT_TYPO, answer
    # сколько слов на месте
    a_words = a.split()
    g_words = g.split()
    if len(g_words) == len(a_words):
        same = sum(1 for x, y in zip(g_words, a_words) if x == y)
        if same >= len(a_words) - 1:
            return RESULT_TYPO, answer
    return RESULT_BAD, answer


def grade_match(given: Dict[str, str], pairs: Sequence[Sequence[str]]) -> Tuple[str, int, int]:
    """Сопоставление пар. Возвращает (результат, угадано, всего)."""
    total = len(pairs)
    good = 0
    for left, right in pairs:
        if norm(given.get(left, "")) == norm(right):
            good += 1
    if good == total:
        return RESULT_OK, good, total
    if good >= total * 0.6:
        return RESULT_TYPO, good, total
    return RESULT_BAD, good, total


def result_text(result: str) -> str:
    return {
        RESULT_OK: "Верно",
        RESULT_TYPO: "Почти — есть опечатка",
        RESULT_ACCENTS: "Почти — потеряна диакритика",
        RESULT_BAD: "Неверно",
    }.get(result, result)


def missing_accents(given: str, expected: str) -> List[str]:
    """Какие диакритические буквы стоят в эталоне, но отсутствуют в ответе.

    Сравниваем посимвольно: если на одной позиции в эталоне стоит á, а в ответе
    обычная a — значит буква потеряна (osemnast -> osemnásť).
    """
    g = norm(given).split()
    e = norm(expected).split()
    out: List[str] = []
    for i, word in enumerate(e):
        got = g[i] if i < len(g) else ""
        if len(got) != len(word):
            continue
        for a, b in zip(word, got):
            if a in ACCENT_CHARS and a != b and strip_accents(a) == b:
                out.append(a)
    return sorted(set(out))


def infer_tag(kind: str, result: str, given: str, expected: str, lesson_id: str = "") -> str:
    """Грубый тег ошибки — по нему потом собираются «мои ошибки» и целевые задания."""
    if result == RESULT_OK:
        return ""
    if result == RESULT_ACCENTS:
        return "diacritics"
    if kind == "build":
        return "order"
    if kind == "match":
        return "pairs"
    if kind == "choice":
        return "grammar"
    if result == RESULT_TYPO:
        return "spelling"

    # type: разбираем, что именно не так со словом/фразой
    g = norm(given)
    e = norm(expected or "")
    if not g:
        return "empty"

    got_list = g.split()
    exp_list = e.split()
    if exp_list and len(got_list) > len(exp_list) and all(w in got_list for w in exp_list):
        return "extra_words"
    if got_list and len(got_list) < len(exp_list) and all(w in exp_list for w in got_list):
        return "missing_words"

    # иначе — замена: определяем тему по номеру урока
    lesson_no = "".join(ch for ch in (lesson_id or "") if ch.isdigit())
    if lesson_no.isdigit():
        n = int(lesson_no)
        if n <= 2:
            return "verb_form"
        if n == 3:
            return "accusative"
        if n == 4:
            return "locative"
        if n == 5:
            return "past_tense"
        if n == 6:
            return "genitive"
        if n == 7:
            return "future"
    return "grammar"
