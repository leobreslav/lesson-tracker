"""
Единственное место, знающее про anthropic.

Всё остальное приложение говорит с моделью через две функции этого модуля и
получает разобранный ответ вместе с числом токенов. Причина та же, по которой
`files/storage.py` один знает про boto3: библиотека меняется, ключ секретен, а
цену вызова надо считать в одном месте, иначе счёт разъедется с журналом.

Ответ берётся инструментом (`tool_choice`), а не свободным текстом: схема
описывает ровно то, что нам нужно, и разбирать текст не приходится.
"""

from __future__ import annotations

import base64

from django.conf import settings

from config.errors import Codes, api_error

from . import prices

# Сколько клеток в сетке бланка. Пятнадцать заданий и сумма за страницу.
CELLS = 16

def cell_index(label: str) -> int | None:
    """
    Подпись над клеткой -> её место в списке из шестнадцати. Неизвестная — None.

    Принимаем щедро: `Q14`, `q14`, `14`, `Q 14`. Последняя клетка — сумма за
    страницу, и зовут её по-разному: на бланке напечатана сигма, модель пишет
    то `sum`, то `total`, то `Σ pg`. Отказать из-за формы подписи значит
    потерять прочитанный балл там, где всё было прочитано верно.
    """
    text = (label or "").strip().lower().replace(" ", "")
    if not text:
        return None
    if text.startswith("q"):
        text = text[1:]
    if text.isdigit():
        number = int(text)
        return number - 1 if 1 <= number <= CELLS - 1 else None
    return CELLS - 1 if any(
        # подпись уже приведена к нижнему регистру, поэтому сигма одна
        word in text for word in ("sum", "total", "σ", "pg")
    ) else None


def values_from_marks(marks) -> list:
    """
    Названные клетки -> шестнадцать значений по местам.

    **Модель называет клетку подписью, а не местом в списке, и это выведено
    опытом.** Список из шестнадцати значений требует от неё считать клетки
    слева, а счёт сбивается: на живой странице баллы стояли в Q14, Q15 и в
    сумме, а приехали в Q13, Q14, Q15 — сдвиг на одну, — да ещё и сумма попала
    разом в Q15 и в свою клетку. Ошибка при этом молчаливая: пятнадцать чисел
    выглядят одинаково правдоподобно, где бы они ни стояли.

    Подпись над клеткой на бланке напечатана для каждой (`Q1`…`Q15` и сигма),
    поэтому «прочти подпись» — это чтение, а не счёт, и ошибиться в нём можно
    только там, где подпись не видна.

    Пустые клетки не называются вовсе: их отсутствие и есть пустота.
    """
    values: list = [None] * CELLS
    for one in marks or []:
        if not isinstance(one, dict):
            continue
        place = cell_index(one.get("cell"))
        value = one.get("value")
        if place is None or not isinstance(value, int) or isinstance(value, bool):
            continue
        values[place] = value
    return values


_HEADER_TOOL = {
    "name": "record_header",
    "description": "Record the handwritten name and the marks grid from the header.",
    "input_schema": {
        "type": "object",
        "properties": {
            "first_name": {
                "type": "string",
                "description": "handwritten First name; EMPTY string if the field is blank",
            },
            "surname": {
                "type": "string",
                "description": "handwritten Surname; EMPTY string if the field is blank",
            },
            "date": {
                "type": "string",
                "description": "handwritten Date exactly as written, e.g. '3.05.26'; empty if blank",
            },
            "guess": {
                "type": "string",
                "description": (
                    "the name from the class list this most likely is, copied "
                    "verbatim from the list; EMPTY if none of them fits"
                ),
            },
            "marks": {
                "type": "array",
                "description": (
                    "one entry per tile whose cell has a handwritten digit in "
                    "it. Empty cells are simply left out. Order does not matter."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "cell": {
                            "type": "string",
                            "description": (
                                "the RED label of the tile this digit is in, "
                                "copied as printed: 'Q1'..'Q15', or 'SUM' for "
                                "the page total"
                            ),
                        },
                        "value": {
                            "type": "integer",
                            "description": "the handwritten digit in that cell",
                        },
                    },
                    "required": ["cell", "value"],
                },
            },
        },
        "required": ["first_name", "surname", "marks"],
    },
}


_QUESTIONS_TOOL = {
    "name": "record_questions",
    "description": "Record every numbered question printed on this sheet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "one entry per numbered question, in the order printed",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {
                            "type": "integer",
                            "description": "the number printed next to the question",
                        },
                        "text": {
                            "type": "string",
                            "description": (
                                "the question itself, as printed. Write mathematics "
                                "in LaTeX between single dollar signs, e.g. "
                                "$\\frac{2}{5}\\times\\frac{5}{6}$. Keep the "
                                "wording; do not solve anything and do not explain."
                            ),
                        },
                        "marks": {
                            "type": ["integer", "null"],
                            "description": (
                                "the top mark printed for this question ('1 mark', "
                                "'2 marks'); null if the sheet does not say"
                            ),
                        },
                    },
                    "required": ["number", "text"],
                },
            }
        },
        "required": ["questions"],
    },
}

QUESTIONS_PROMPT = (
    "You are given a scanned sheet with the questions of a school test. Copy "
    "every numbered question as printed, keeping its number. Write mathematics "
    "in LaTeX between single dollar signs. Do NOT solve anything, do not add "
    "explanations, and do not invent questions that are not on the sheet: a "
    "sheet with none is an empty list. Ignore anything a student wrote by hand."
)


def read_questions(
    image: bytes,
    *,
    media_type: str = "image/jpeg",
    model: str = prices.SONNET,
) -> tuple[list, int, int]:
    """
    Лист условий -> список задач с номерами.

    Модель тут дороже, чем при чтении шапок, и это не расточительность:
    страниц условий две-три на всю пачку, а работа у них другая —
    транскрипция формул, а не цифра в клетке. Ошибка в условии переезжает в
    работу и остаётся там навсегда, ошибка в клетке видна человеку на шаге
    проверки.
    """
    message = _client().messages.create(
        model=model,
        max_tokens=4000,
        system=[
            {
                "type": "text",
                "text": QUESTIONS_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_QUESTIONS_TOOL],
        tool_choice={"type": "tool", "name": _QUESTIONS_TOOL["name"]},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Copy the questions from this sheet."},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image).decode(),
                        },
                    },
                ],
            }
        ],
    )

    data: dict = {}
    for block in message.content:
        if block.type == "tool_use":
            data = block.input

    out = []
    for item in data.get("questions") or []:
        try:
            number = int(item["number"])
        except (KeyError, TypeError, ValueError):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        marks = item.get("marks")
        out.append(
            {
                "number": number,
                "text": text,
                "marks": marks if isinstance(marks, int) else None,
            }
        )

    return out, message.usage.input_tokens, message.usage.output_tokens


def _system_prompt() -> str:
    """
    Что модель знает о листе — и чего ей знать не следует.

    **Максимум за задачу ей больше не сообщается, и это выведено опытом.**
    Стояла фраза «оценка от 0 до N; большее число почти наверняка неверно
    прочитанная цифра, посмотри ещё раз» — и на живой пачке она работала ровно
    так, как написана: у работы со шкалой «4 задачи по 1 баллу» лист с
    выставленными «1 2 0 3 2» прочитался как «1 2 0 3 0». Модель не ошиблась,
    она послушалась.

    Это тот же капкан, что и со списком класса, который однажды подменил
    фамилию: **всё, что подсказывает ожидаемый ответ, будет подставлено вместо
    увиденного.** Поэтому спрашиваем только «что написано», а «бывает ли такое
    число вообще» проверяет сервер — `troubles` ставит `mark_too_big`, и
    человек видит и цифру, и лист. Проверка на месте, а чтение не искажено.
    """
    return (
        "You are given a picture assembled from one school answer sheet. At the "
        "top is the name row, with printed labels 'First name:', 'Surname:', "
        "'Grade:', 'Date:' and handwriting on the rules after them. Below it are "
        "16 tiles, one per cell of the marks grid. Each tile shows a RED label we "
        "printed — 'Q1' to 'Q15', and 'SUM' for the page total — and, next to it, "
        "that cell cut out of the sheet. A cell holds at most one handwritten "
        "digit, in pen of any colour, and most cells are empty.\n"
        "Report the handwritten First name and Surname SEPARATELY, letter by "
        "letter, EXACTLY as written — do not correct them into a more plausible "
        "name. If a field is not filled in, return an EMPTY string for it; never "
        "invent a name. The handwriting varies: sometimes the teacher fills it in, "
        "not the student. Ignore Grade.\n"
        "For every tile whose cell has a handwritten digit, report the red label "
        "of that tile and the digit. The tiles are already cut apart, so a digit "
        "belongs to the tile it is drawn in and to no other — do not look for it "
        "in a row or count anything. Leave empty tiles out entirely. Report the "
        "digit you actually see: never adjust a mark to fit a range you expect, "
        "and never turn an unexpected digit into a more likely one. 'SUM' is the "
        "page total, not a question: it may be larger than any single mark, and "
        "it is often left blank."
    )


def _client():
    key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not key:
        raise api_error(
            Codes.AI_KEY_MISSING,
            "Reading scans is not set up: the service has no Anthropic API key.",
        )
    try:
        import anthropic
    except ImportError:  # pragma: no cover - библиотека стоит в образе
        raise api_error(Codes.AI_UNAVAILABLE, "The anthropic library is not installed.")
    # Ретраи на 429/5xx/сеть берёт на себя SDK: наш вызов и так один на страницу.
    return anthropic.Anthropic(api_key=key, max_retries=3)


def read_header(
    image: bytes,
    *,
    media_type: str = "image/jpeg",
    candidates: list[str] | None = None,
    model: str = prices.HAIKU,
) -> tuple[dict, int, int]:
    """
    Полоска шапки -> (данные, входных токенов, выходных).

    **Список класса и прочитанное имя — разные поля, и это выведено опытом.**
    Сперва список отдавался просто подсказкой к чтению, и на живом скане он
    подменил фамилию: «Lape» превратилась в «Jerbi», потому что Jerbi в списке
    был, а Lape не было. Ошибка при этом молчаливая и худшая из возможных —
    страница уходит не тому ученику. Убрали список вовсе — почерк стал
    читаться заметно хуже: «Shahar Jerbi» превращается в «Shalene Dorah», и
    такая страница уезжает к человеку, хотя решить её можно было машиной.

    Поэтому вопросов теперь два. `first_name`/`surname` — что написано на
    бумаге, буква за буквой; по ним и идёт сопоставление с составом курса.
    `guess` — кого модель тут видит из списка; это **мнение**, и живёт оно
    ровно там, где мнению место: первым кандидатом в карточке, которую решает
    человек. Молча по нему ничего не назначается.
    """
    hint = ""
    if candidates:
        names = "\n".join(f"- {name}" for name in candidates)
        hint = (
            "\n\nThe class list is below. Use it ONLY to resolve unclear letters, "
            "and put your opinion in `guess`. Never copy a name from the list into "
            "first_name or surname: those must stay exactly as written on paper.\n"
            + names
        )

    message = _client().messages.create(
        model=model,
        max_tokens=500,
        system=[
            {
                "type": "text",
                "text": _system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_HEADER_TOOL],
        tool_choice={"type": "tool", "name": _HEADER_TOOL["name"]},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read the name and the marks grid." + hint},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image).decode(),
                        },
                    },
                ],
            }
        ],
    )

    data: dict = {}
    for block in message.content:
        if block.type == "tool_use":
            data = block.input

    values = values_from_marks(data.get("marks"))

    return (
        {
            "first_name": (data.get("first_name") or "").strip(),
            "surname": (data.get("surname") or "").strip(),
            "date": (data.get("date") or "").strip(),
            "guess": (data.get("guess") or "").strip(),
            "values": values,
        },
        message.usage.input_tokens,
        message.usage.output_tokens,
    )
