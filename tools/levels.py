"""Курсы A1/A2/B1/B2 из словарей slova-*.txt.

Идея: словари уже разбиты на смысловые разделы. Каждый раздел (или пара
разделов) становится юнитом, слова делятся на уроки по 6–9 штук, а задания
строятся из самих слов: выбор перевода, набор по-словацки и пары.

Ничего не выдумывается: слова и переводы берутся из файлов slovar/*.txt.
Запускается из tools/build_content.py, отдельно запускать не нужно.
"""

from __future__ import annotations

import math
import random
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LEVELS = ("A1", "A2", "B1", "B2")
LEVEL_RANK = {level: i for i, level in enumerate(LEVELS)}
LEVEL_BASE = {"A1": 100, "A2": 0, "B1": 200, "B2": 300}
LEVEL_PREFIX = {"A1": "a1", "A2": "a2", "B1": "b1", "B2": "b2"}

# Краткие правила для юнитов A1/A2 — они показываются перед уроком.
RULES: Dict[str, Dict[str, Any]] = {
    "A1-1": {
        "title": "Ты или вы",
        "p": [
            "Ty — с друзьями, ровесниками и близкими. Vy — вежливо, со взрослыми и незнакомыми.",
            "Меняется и глагол: ty si → vy ste.",
        ],
        "rows": [["ty si", "ты (есть)"], ["vy ste", "вы (есть)"]],
        "ex": ["Ahoj, ako sa máš?", "Dobrý deň, ako sa máte?"],
    },
    "A1-2": {
        "title": "Личные местоимения",
        "p": ["Местоимение можно не говорить: форма глагола уже показывает лицо."],
        "rows": [
            ["ja", "я"], ["ty", "ты"], ["on / ona / ono", "он / она / оно"],
            ["my", "мы"], ["vy", "вы"], ["oni", "они"],
        ],
        "ex": ["Ja som študent. = Som študent."],
    },
    "A1-3": {
        "title": "Вопросы",
        "p": ["Вопросительное слово ставят в начало, порядок слов дальше не меняется."],
        "rows": [
            ["kto", "кто"], ["čo", "что"], ["kde", "где"], ["kam", "куда"],
            ["kedy", "когда"], ["ako", "как"], ["prečo", "почему"], ["koľko", "сколько"],
        ],
        "ex": ["Kde bývaš? — Где ты живёшь?"],
    },
    "A1-4": {
        "title": "Мой и твой",
        "p": ["Притяжательное слово согласуется с родом: môj brat, moja sestra, moje auto."],
        "rows": [
            ["môj / moja / moje", "мой / моя / моё"],
            ["tvoj / tvoja / tvoje", "твой / твоя / твоё"],
        ],
        "ex": ["To je moja rodina.", "To je tvoj brat."],
    },
    "A1-5": {
        "title": "Который час",
        "p": ["Один час — jedna hodina, два-четыре — hodiny, пять и больше — hodín."],
        "rows": [
            ["Je jedna hodina.", "Час."],
            ["Sú dve hodiny.", "Два часа."],
            ["Je päť hodín.", "Пять часов."],
        ],
        "ex": ["O koľkej? — Vo dvoch."],
    },
    "A1-6": {
        "title": "Винительный падеж",
        "p": ["После jesť и piť нужен винительный падеж: jem chlieb, pijem kávu.", "У женского рода -a → -u."],
        "rows": [["jem chlieb", "ем хлеб"], ["pijem kávu", "пью кофе"]],
        "ex": ["Dám si vodu, prosím."],
    },
    "A1-7": {
        "title": "Где? v и na",
        "p": ["«Где» — предложный падеж: v Bratislave, na stanici.", "v — внутри, na — на поверхности или в учреждении."],
        "rows": [["v meste", "в городе"], ["na stanici", "на станции"]],
        "ex": ["Bývam v Košiciach.", "Čakám na stanici."],
    },
    "A1-8": {
        "title": "Прилагательное и существительное",
        "p": ["Прилагательное согласуется с родом: dobrý deň, dobrá škola, dobré auto."],
        "rows": [["dobrý", "мужской род"], ["dobrá", "женский род"], ["dobré", "средний род"]],
        "ex": ["To je dobrá škola."],
    },
    "A1-9": {
        "title": "Твёрдые и мягкие",
        "p": ["Твёрдые: nový — nová — nové. Мягкие: cudzí — cudzia — cudzie."],
        "rows": [
            ["nový / nová / nové", "новый / новая / новое"],
            ["cudzí / cudzia / cudzie", "чужой / чужая / чужое"],
        ],
        "ex": ["Mám nový telefón."],
    },
    "A1-10": {
        "title": "Глаголы в настоящем",
        "p": ["byť: som, si, je, sme, ste, sú. mať: mám, máš, má, máme, máte, majú.", "Окончание показывает лицо, поэтому местоимение часто опускают."],
        "rows": [["som / si / je", "я / ты / он"], ["sme / ste / sú", "мы / вы / они"]],
        "ex": ["Mám čas.", "Sme doma."],
    },
    "A2-8": {
        "title": "Болит — bolí ma",
        "p": ["Часть тела ставят в винительный падеж: bolí ma hlava, bolí ma zub."],
        "rows": [["bolí ma hlava", "у меня болит голова"], ["bolí ma hrdlo", "у меня болит горло"]],
        "ex": ["Cítim sa dobre.", "Som unavený."],
    },
    "A2-9": {
        "title": "На работе и в учреждении",
        "p": ["Устойчивые сочетания: v práci, v škole, na úrade, na pošte."],
        "rows": [["v práci", "на работе"], ["na úrade", "в учреждении"]],
        "ex": ["Idem na úrad.", "Pracujem v škole."],
    },
    "A2-10": {
        "title": "Повторение",
        "p": ["Числа, время и связки — фундамент для уровня B1.", "В конце юнита — итоговый тест по всему A2."],
        "rows": [],
        "ex": [],
    },
}

# План курсов. У A2 заполняются только пустые юниты 8–10: уроки 1a–7f
# уже собраны из HTML-тренажёра и получают уровень A2 в build_content.py.
PLANS: Dict[str, List[Dict[str, Any]]] = {
    "A1": [
        {"num": 1, "title": "Основное", "desc": "Приветствия, да и нет, вежливые слова", "sections": ["ОСНОВНОЕ"]},
        {"num": 2, "title": "Местоимения", "desc": "Я, ты, он, она — и когда их опускают", "sections": ["МЕСТОИМЕНИЯ"]},
        {"num": 3, "title": "Вопросы и маленькие слова", "desc": "Кто, что, где, когда — и служебные слова", "sections": ["ВОПРОСЫ И МАЛЕНЬКИЕ СЛОВА"]},
        {"num": 4, "title": "Семья и люди", "desc": "Родные, профессии, знакомства", "sections": ["СЕМЬЯ И ЛЮДИ", "ПРОФЕССИИ"]},
        {"num": 5, "title": "Время", "desc": "Дни, часы, части дня", "sections": ["ВРЕМЯ"]},
        {"num": 6, "title": "Еда и напитки", "desc": "Что заказать и что купить", "sections": ["ЕДА И НАПИТКИ"]},
        {"num": 7, "title": "Дом и город", "desc": "Комнаты, улицы, транспорт", "sections": ["ДОМ", "ГОРОД"]},
        {"num": 8, "title": "Школа и цвета", "desc": "Учёба и базовые цвета", "sections": ["ШКОЛА", "ЦВЕТА"]},
        {"num": 9, "title": "Прилагательные", "desc": "Какой? Большой, новый, хороший", "sections": ["ПРИЛАГАТЕЛЬНЫЕ"]},
        {"num": 10, "title": "Глаголы", "desc": "Самые нужные действия на каждый день", "sections": ["ГЛАГОЛЫ"]},
    ],
    "A2": [
        {"n": 8, "num": 8, "title": "Здоровье и хобби", "desc": "Тело, самочувствие, свободное время", "sections": ["ТЕЛО", "ЗДОРОВЬЕ", "СВОБОДНОЕ ВРЕМЯ"]},
        {"n": 9, "num": 9, "title": "Учёба и документы", "desc": "Учёба, работа, покупки и чувства", "sections": ["УЧЁБА", "РАБОТА", "ПОКУПКИ И ДЕНЬГИ", "ЧУВСТВА", "ПРИЛАГАТЕЛЬНЫЕ"]},
        {"n": 10, "num": 10, "title": "Повторение и тест A2", "desc": "Числа, время, связки и итоговый тест", "sections": ["ПОРЯДКОВЫЕ ЧИСЛА", "ВРЕМЯ И ЧАСТОТА", "СВЯЗКИ", "ГЛАГОЛЫ ПАРАМИ"], "test": True},
    ],
    "B1": [
        {"num": 1, "title": "Мнение и рассуждение", "desc": "Как сказать «я думаю» и «по-моему»", "sections": ["МНЕНИЕ И РАССУЖДЕНИЕ"]},
        {"num": 2, "title": "Образование и поступление", "desc": "Университет, документы, экзамены", "sections": ["ОБРАЗОВАНИЕ И ПОСТУПЛЕНИЕ"]},
        {"num": 3, "title": "Математика", "desc": "Числа, действия, геометрия", "sections": ["МАТЕМАТИКА"]},
        {"num": 4, "title": "Физика", "desc": "Величины, явления, опыты", "sections": ["ФИЗИКА"]},
        {"num": 5, "title": "Машиностроение и техника", "desc": "Детали, станки, производство", "sections": ["МАШИНОСТРОЕНИЕ И ТЕХНИКА"]},
        {"num": 6, "title": "Сварка", "desc": "Материалы, швы, техника безопасности", "sections": ["СВАРКА"]},
        {"num": 7, "title": "Работа и карьера", "desc": "Вакансии, обязанности, зарплата", "sections": ["РАБОТА И КАРЬЕРА"]},
        {"num": 8, "title": "Документы и государство", "desc": "Визы, справки, учреждения", "sections": ["ДОКУМЕНТЫ И ГОСУДАРСТВО"]},
        {"num": 9, "title": "Технологии и медиа", "desc": "Интернет, устройства, новости", "sections": ["ТЕХНОЛОГИИ И МЕДИА"]},
        {"num": 10, "title": "Окружающая среда", "desc": "Природа, климат, экология", "sections": ["ОКРУЖАЮЩАЯ СРЕДА"]},
        {"num": 11, "title": "Люди и отношения", "desc": "Характер, общение, конфликты", "sections": ["ЛЮДИ И ОТНОШЕНИЯ"]},
        {"num": 12, "title": "Связки для текстов", "desc": "Чтобы говорить и писать связно", "sections": ["СВЯЗКИ ДЛЯ ТЕКСТОВ"]},
    ],
    "B2": [
        {"num": 1, "title": "Общество и политика", "desc": "Гражданин, законы, выборы", "sections": ["ОБЩЕСТВО И ПОЛИТИКА", "ПРАВО И ДОКУМЕНТЫ"]},
        {"num": 2, "title": "Экономика и финансы", "desc": "Рынок, налоги, бюджет", "sections": ["ЭКОНОМИКА И ФИНАНСЫ"]},
        {"num": 3, "title": "Экология", "desc": "Климат, отходы, устойчивое развитие", "sections": ["ЭКОЛОГИЯ"]},
        {"num": 4, "title": "Наука и технологии", "desc": "Исследования, опыты, устройства", "sections": ["НАУКА И ТЕХНОЛОГИИ"]},
        {"num": 5, "title": "Медицина и здоровье", "desc": "Диагноз, лечение, профилактика", "sections": ["МЕДИЦИНА И ЗДОРОВЬЕ"]},
        {"num": 6, "title": "Работа и карьера", "desc": "Собеседование, навыки, проекты", "sections": ["РАБОТА И КАРЬЕРА"]},
        {"num": 7, "title": "Образование", "desc": "Университет, экзамены, диплом", "sections": ["ОБРАЗОВАНИЕ"]},
        {"num": 8, "title": "Абстрактные понятия", "desc": "Причина, цель, условие, влияние", "sections": ["АБСТРАКТНЫЕ ПОНЯТИЯ"]},
        {"num": 9, "title": "Связки и выражения", "desc": "Что касается, несмотря на, кроме того", "sections": ["СВЯЗКИ И ВЫРАЖЕНИЯ"]},
        {"num": 10, "title": "Глаголы", "desc": "Влиять, обеспечить, учитывать", "sections": ["ГЛАГОЛЫ"]},
        {"num": 11, "title": "Прилагательные", "desc": "Существенный, сложный, необходимый", "sections": ["ПРИЛАГАТЕЛЬНЫЕ"]},
    ],
}


# --------------------------------------------------------------------------- #
# Разбор словарей
# --------------------------------------------------------------------------- #
def parse_sections(path: Path) -> "OrderedDict[str, List[Tuple[str, str]]]":
    """slova-A1.txt -> {раздел: [(sk, ru), ...]} в порядке файла."""
    groups: "OrderedDict[str, List[Tuple[str, str]]]" = OrderedDict()
    if not path.exists():
        return groups
    current = "БЕЗ РАЗДЕЛА"
    seen = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            m = re.match(r"^#\s*=+\s*(.+?)\s*=+\s*$", line.strip())
            if m:
                current = m.group(1).strip()
                groups.setdefault(current, [])
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sk = parts[0].strip()
        ru = parts[1].strip()
        if not sk or not ru:
            continue
        key = sk.lower()
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault(current, []).append((sk, ru))
    return groups


def _find_section(groups: Dict[str, List[Tuple[str, str]]], name: str) -> List[Tuple[str, str]]:
    """Ищет раздел по точному имени или по началу (в файлах бывают длинные хвосты)."""
    if name in groups:
        return groups[name]
    for key, words in groups.items():
        if key.upper().startswith(name.upper()):
            return words
    return []


# --------------------------------------------------------------------------- #
# Задания
# --------------------------------------------------------------------------- #
def _split_variants(sk: str) -> List[str]:
    return [x.strip() for x in sk.split("/") if x.strip()]


def _typable(sk: str) -> bool:
    """Годится ли слово для набора с клавиатуры."""
    if not sk or any(ch in sk for ch in "…()[]"):
        return False
    variants = _split_variants(sk)
    if not variants:
        return False
    return all(len(v) <= 28 for v in variants)


def _make_choice(word: Tuple[str, str], pool: List[str], rng: random.Random) -> Dict[str, Any]:
    sk, ru = word
    options = [ru]
    candidates = [x for x in pool if x and x != ru]
    rng.shuffle(candidates)
    for candidate in candidates:
        if candidate not in options:
            options.append(candidate)
        if len(options) >= 4:
            break
    rng.shuffle(options)
    return {
        "kind": "choice",
        "prompt": "Что значит «%s»?" % sk,
        "options": options,
        "answer": options.index(ru),
        "shuffle": True,
        "explain": None,
    }


def _make_type(word: Tuple[str, str]) -> Optional[Dict[str, Any]]:
    sk, ru = word
    if not _typable(sk):
        return None
    return {
        "kind": "type",
        "prompt": "Напиши по-словацки: «%s»" % ru,
        "sk": "",
        "answers": _split_variants(sk),
        "explain": None,
    }


def _make_match(words: List[Tuple[str, str]]) -> Optional[Dict[str, Any]]:
    pairs = [[sk, ru] for sk, ru in words[:5]]
    if len(pairs) < 5:
        return None
    return {"kind": "match", "prompt": "Найди пары", "pairs": pairs, "explain": None}


def _split_chunks(words: List[Tuple[str, str]], size: int = 9) -> List[List[Tuple[str, str]]]:
    """Делит слова на ровные куски не больше size."""
    if len(words) <= size:
        return [words] if words else []
    count = max(1, math.ceil(len(words) / size))
    base, extra = divmod(len(words), count)
    chunks: List[List[Tuple[str, str]]] = []
    start = 0
    for index in range(count):
        take = base + (1 if index < extra else 0)
        chunks.append(words[start:start + take])
        start += take
    return chunks


def _lesson_tasks(words: List[Tuple[str, str]], pool: List[str], seed: str) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    if not words:
        return []

    choice_words = words[:4]
    type_source = words[4:7]
    type_words = [w for w in type_source if _typable(w[0])]
    # если набирать нечего — добираем выбором из оставшихся слов
    spare = [w for w in words[4:] if w not in type_words]

    tasks: List[Dict[str, Any]] = []
    choices = [_make_choice(w, pool, rng) for w in choice_words]
    types = [_make_type(w) for w in type_words]
    types = [t for t in types if t]

    # чередуем: выбор → набор → выбор → набор...
    for index in range(max(len(choices), len(types))):
        if index < len(choices):
            tasks.append(choices[index])
        if index < len(types):
            tasks.append(types[index])

    for word in spare:
        if len(tasks) >= 8:
            break
        tasks.append(_make_choice(word, pool, rng))

    if len(words) >= 5 and len(tasks) < 9:
        match = _make_match(words)
        if match:
            tasks.append(match)

    for index, task in enumerate(tasks):
        task["i"] = index
    return tasks


# --------------------------------------------------------------------------- #
# Сборка курсов
# --------------------------------------------------------------------------- #
def build_level_courses(source: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Возвращает (units, lessons) для A1, A2 (юниты 8–10), B1 и B2."""
    dictionaries = {
        level: parse_sections(source / "slovar" / ("slova-%s.txt" % level))
        for level in LEVELS
    }

    units: List[Dict[str, Any]] = []
    lessons: List[Dict[str, Any]] = []

    for level in LEVELS:
        groups = dictionaries[level]
        pool = [ru for words in groups.values() for _, ru in words]
        plan = PLANS.get(level) or []
        seq = 0

        for unit_plan in plan:
            num = int(unit_plan["num"])
            n = int(unit_plan.get("n") or (LEVEL_BASE[level] + num))
            words: List[Tuple[str, str]] = []
            for section in unit_plan.get("sections") or []:
                words.extend(_find_section(groups, section))

            # убираем повторы внутри юнита
            seen = set()
            unique: List[Tuple[str, str]] = []
            for word in words:
                if word[0].lower() in seen:
                    continue
                seen.add(word[0].lower())
                unique.append(word)

            unit_lesson_ids: List[str] = []
            chunks = _split_chunks(unique)
            for part, chunk in enumerate(chunks, 1):
                seq += 1
                lesson_id = "%s-%02d" % (LEVEL_PREFIX[level], seq)
                tasks = _lesson_tasks(chunk, pool, "%s:%s" % (lesson_id, level))
                lesson = {
                    "id": lesson_id,
                    "unit": n,
                    "unit_title": unit_plan["title"],
                    "level": level,
                    "title": "%s · %d" % (unit_plan["title"], part),
                    "sub": "%d слов · выбор, набор, пары" % len(chunk),
                    "rule": RULES.get("%s-%d" % (level, num)),
                    "tasks": tasks,
                }
                lessons.append(lesson)
                unit_lesson_ids.append(lesson_id)

            if unit_plan.get("test") and unique:
                lesson_id = "%s-test" % LEVEL_PREFIX[level]
                all_words = [w for section in groups.values() for w in section]
                tasks = _test_tasks(all_words, pool, "%s:test" % level)
                lessons.append(
                    {
                        "id": lesson_id,
                        "unit": n,
                        "unit_title": unit_plan["title"],
                        "level": level,
                        "title": "Итоговый тест %s" % level,
                        "sub": "25 заданий по всему уровню",
                        "rule": RULES.get("%s-%d" % (level, num)),
                        "tasks": tasks,
                    }
                )
                unit_lesson_ids.append(lesson_id)

            # A2 юниты 8–10 уже есть в HTML-курсе пустыми каркасами: при сборке
            # они сольются по номеру, а заголовок и описание возьмутся из плана.
            units.append(
                {
                    "n": n,
                    "num": num,
                    "level": level,
                    "title": unit_plan["title"],
                    "desc": unit_plan.get("desc", ""),
                    "lessons": unit_lesson_ids,
                }
            )

    return units, lessons


def _test_tasks(words: List[Tuple[str, str]], pool: List[str], seed: str) -> List[Dict[str, Any]]:
    """Итоговый тест: 20 вопросов на перевод + 5 на набор."""
    rng = random.Random(seed)
    unique: List[Tuple[str, str]] = []
    seen = set()
    for word in words:
        if word[0].lower() in seen:
            continue
        seen.add(word[0].lower())
        unique.append(word)
    rng.shuffle(unique)

    picks = unique[:25]
    tasks: List[Dict[str, Any]] = []
    typed = 0
    for word in picks:
        if typed < 5:
            task = _make_type(word)
            if task:
                tasks.append(task)
                typed += 1
                continue
        tasks.append(_make_choice(word, pool, rng))

    for index, task in enumerate(tasks):
        task["i"] = index
    return tasks
