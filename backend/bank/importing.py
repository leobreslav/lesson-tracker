"""
Массовый импорт задач: таблицей, книгой или вставкой.

Вписывать книгу по одной странице никто не станет — задачники приходят
таблицами: выгрузка из чужой системы, набранный кем-то файл, лист Excel. Формат
поэтому один, а файлов, в которых он живёт, три (CSV, xlsx, вставка из буфера)
— ровно как у учебного плана, и по той же причине: разбор общий, различается
только чтение ячеек.

    Раздел          | Номер | Пункт | Условие              | Ответ
    ----------------+-------+-------+----------------------+------
    Квадратные ур-я | 14    |       | Дан треугольник ABC… |
    Квадратные ур-я | 14    | а)    | Найдите площадь      | 6
    Квадратные ур-я | 14    | б)    | Найдите радиус       | 1
    Квадратные ур-я | 15    | а)    | $x^2=4$              | ±2

Строка без пункта — **номер**: её условие становится сюжетом, а если условия
нет, номер остаётся чистым адресом. Строка с пунктом — вопрос под этим номером.
То же различение, что при вставке отступом, только выраженное колонкой: у
пятнадцатого номера сюжета нет, и его пункты самостоятельны.

**Вместо угадывания — отказ.** Шапка обязательна и сверяется по именам;
пункт, у которого номера нет ни в своей строке, ни выше, отклоняется с номером
строки. Молча пропущенная строка хуже отклонённого файла: половина
импортированной книги — это книга, в которой непонятно, чего не хватает.
"""

from config.errors import Codes, api_error

# Имена колонок сверяются без регистра и лишних пробелов. Порядок фиксирован —
# он и есть формат; читать «где-то тут был номер» мы не беремся.
COLUMNS = ["раздел", "номер", "пункт", "условие", "ответ"]
ENGLISH = ["section", "number", "part", "statement", "answer"]

LIMIT = 2000


def parse_table(rows) -> list[dict]:
    """
    Матрица ячеек → та же форма, что отдаёт разбор вставки отступом.

    Отдаёт список номеров, у каждого `section`, `label`, `text`, `answers` и
    `parts` — список пунктов такой же формы. Форма общая намеренно: писать
    заведённое в базу должен один код, иначе таблица и вставка разойдутся в
    первой же правке.
    """
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        api_error(Codes.OUTLINE_EMPTY, "There is nothing to read.", field="rows")

    if not _is_header(rows[0]):
        api_error(
            Codes.CSV_HEADER_INVALID,
            "The first row must name the columns: раздел, номер, пункт, "
            "условие, ответ.",
            field="rows",
        )

    if len(rows) - 1 > LIMIT:
        api_error(
            Codes.FILE_TOO_MANY_ROWS,
            f"Too many rows: {len(rows) - 1}, the limit is {LIMIT}.",
            field="rows",
        )

    numbers = []
    for line, row in enumerate(rows[1:], start=2):
        section, label, part, text, answer = _cells(row, line)

        if not part:
            numbers.append(
                {
                    "section": section,
                    "label": label,
                    "text": text,
                    "answers": [answer] if answer else [],
                    "parts": [],
                    "line": line,
                }
            )
            continue

        if not numbers or (label and label != numbers[-1]["label"]):
            # Пункт, у которого нет своего номера: либо строки-номера не было
            # вовсе, либо номер сменился в той же строке. Оба случая — ошибка
            # человека, и молча приписывать пункт предыдущему номеру нельзя.
            if not label:
                api_error(
                    Codes.PART_WITHOUT_NUMBER,
                    f"Line {line} has a part but no number above it.",
                    field="rows",
                    line=line,
                )
            numbers.append(
                {
                    "section": section,
                    "label": label,
                    "text": "",
                    "answers": [],
                    "parts": [],
                    "line": line,
                }
            )

        if not text:
            api_error(
                Codes.PROBLEM_TEXT_REQUIRED,
                f"Line {line} has a part but no statement.",
                field="rows",
                line=line,
            )

        numbers[-1]["parts"].append(
            {
                "label": part,
                "text": text,
                "answers": [answer] if answer else [],
                "line": line,
            }
        )

    for number in numbers:
        if not number["text"] and not number["parts"]:
            api_error(
                Codes.PROBLEM_TEXT_REQUIRED,
                f"Line {number['line']} has a number but no statement.",
                field="rows",
                line=number["line"],
            )

    return numbers


def _is_header(row) -> bool:
    names = [str(cell).strip().lower() for cell in row[: len(COLUMNS)]]
    return names == COLUMNS or names == ENGLISH


def _cells(row, line):
    if len(row) > len(COLUMNS) and any(str(cell).strip() for cell in row[len(COLUMNS):]):
        api_error(
            Codes.CSV_ROW_TOO_LONG,
            f"Line {line} has more columns than the format has.",
            field="rows",
            line=line,
        )

    filled = [str(cell).strip() if cell is not None else "" for cell in row]
    filled += [""] * (len(COLUMNS) - len(filled))
    return filled[:5]


def preview(rows) -> dict:
    """
    Что получится из таблицы — **ничего не записывая** и ни от чего не
    отказываясь: ошибки уезжают списком в теле, как у импорта плана. Иначе
    единственным следом отказа была бы ошибка в консоли.
    """
    try:
        numbers = parse_table(rows)
    except Exception as trouble:  # noqa: BLE001 — тело ошибки и есть ответ
        detail = getattr(trouble, "detail", None)
        return {"errors": [detail or str(trouble)], "numbers": 0, "problems": 0}

    return {
        "errors": [],
        "numbers": len(numbers),
        "sections": len({number["section"] for number in numbers if number["section"]}),
        # задач меньше, чем строк: сюжет задачей не считается
        "problems": sum(
            len(number["parts"]) or (1 if number["text"] else 0) for number in numbers
        ),
        "stems": sum(1 for number in numbers if number["text"] and number["parts"]),
    }
