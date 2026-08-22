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
            "values": {
                "type": "array",
                "description": (
                    "exactly 16 values in order Q1..Q15 then the last cell "
                    "(sum for the page); null for an empty cell"
                ),
                "items": {"type": ["integer", "null"]},
            },
        },
        "required": ["first_name", "surname", "values"],
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


def _system_prompt(max_mark: int | None) -> str:
    limit = (
        f" A mark for a question is between 0 and {max_mark}; a larger number is "
        f"almost certainly a misread digit, look again."
        if max_mark
        else ""
    )
    return (
        "You are given a straightened strip cut from the top of a school answer "
        "sheet. The strip has two rows. The upper row has printed labels "
        "'First name:', 'Surname:', 'Grade:', 'Date:' with handwriting on the "
        "rules after them. The lower row is a table of 16 cells labelled Q1..Q15 "
        "and a last cell for the page total; a cell holds at most one handwritten "
        "digit, in pen of any colour, and most cells are empty.\n"
        "Report the handwritten First name and Surname SEPARATELY, letter by "
        "letter, EXACTLY as written — do not correct them into a more plausible "
        "name. If a field is not filled in, return an EMPTY string for it; never "
        "invent a name. The handwriting varies: sometimes the teacher fills it in, "
        "not the student. Ignore Grade.\n"
        "Report the 16 cell values in order. A cell you can see is empty is null."
        + limit
        + " The last cell is a sum for the page and may be larger than a single "
        "question mark; it is often left blank, and that is fine."
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
    max_mark: int | None = None,
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
                "text": _system_prompt(max_mark),
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

    values = list(data.get("values") or [])
    # Модель может вернуть меньше или больше шестнадцати: приводим к длине, а
    # не отказываем — половина прочитанного лучше отказа, а недостающее видно
    # как пустая клетка и попадёт в сомнения.
    values = (values + [None] * CELLS)[:CELLS]
    values = [v if isinstance(v, int) else None for v in values]

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
