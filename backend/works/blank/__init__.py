"""
Бланк с подписями задач: тот же лист, что лежит в кабинете, плюс имена
вопросов в полосах над клетками.

**Лист не рисуется заново, а надпечатывается.** Подложка — готовый
`blank_form.pdf`, собранный из `blank/blank_form.tex`, и поверх него ложится
прозрачная страница с одними подписями. Второй рисовальщик того же листа
(LaTeX на сервере или повтор сетки здесь) разошёлся бы с первым в первой же
правке шаблона, а разошедшийся лист — это кроп мимо клеток.

**Индивидуального на листе по-прежнему нет.** Подписи — про работу, а не про
ученика: весь класс получает одинаковую пачку, QR не меняется, и правило
«взял сверху чистый» остаётся в силе.

**Чтение подписей не видит**, и это условие, а не удача: плитка клетки режется
ниже полосы подписи (`cellRect` в `blankGeometry.js`), так что напечатанное
«2c» на модель не уезжает и за балл не принимается.

Копия PDF лежит здесь, а не читается из `blank/`, потому что образ бэкенда
собирается только из `./backend`. Что копия не отстала от шаблона и что
миллиметры ниже те же, что у кода чтения, стережёт узловой
`blankCopy.test.js`.
"""

from io import BytesIO
from pathlib import Path

from config.errors import Codes, api_error
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "blank_form.pdf"
MARK_TEMPLATE = HERE / "mark_sheet.pdf"
FONT = HERE / "DejaVuSans.ttf"

# Геометрия сетки баллов, миллиметры от левого верхнего угла листа. Те же
# числа, что `GRID` в frontend/src/blankGeometry.js; сверяет их узловой тест.
GRID_X = 12.5
GRID_Y = 19.3
CELL_WIDTH = 11.5625
LABEL_HEIGHT = 11.5
QUESTIONS = 15

# Лист баллов (маркгрид): шесть линеек той же сетки, по шестнадцать клеток,
# нумерация сквозная, последняя клетка последней линейки — сумма. Те же числа,
# что `MARKS` в blankGeometry.js; сверяет их тот же узловой тест.
MARK_ROW_Y = 57
MARK_ROW_PITCH = 37
MARK_ROWS = 6
MARK_QUESTIONS = 95
PER_ROW = 16

# Какие бывают листы. Ключ приходит из запроса (`sheet`), поэтому список
# закрытый: незнакомое имя — отказ, а не молча бланк ответов.
ANSWER = "answer"
MARKS = "marks"
SHEETS = {
    ANSWER: {"template": TEMPLATE, "questions": QUESTIONS, "file": "blank.pdf"},
    MARKS: {"template": MARK_TEMPLATE, "questions": MARK_QUESTIONS, "file": "mark-sheet.pdf"},
}


def cell_origin(sheet, index):
    """Левый верхний угол полосы подписи клетки `index` (с нуля) на листе."""
    if sheet == MARKS:
        row, column = divmod(index, PER_ROW)
        return GRID_X + column * CELL_WIDTH, MARK_ROW_Y + row * MARK_ROW_PITCH
    return GRID_X + index * CELL_WIDTH, GRID_Y

# Длина подписи — та же, что у `Task.label`: подпись на бумаге и имя вопроса в
# системе — одно и то же, и влезать должно одно и то же.
MAX_LABEL = 16

# Поля внутри полосы. Сверху больше: в левом верхнем углу стоит мелкий номер
# клетки (5 pt), и подпись не должна на него наезжать.
SIDE = 0.8
TOP = 2.6
BOTTOM = 0.6

# Кегли, которые пробуются по очереди: крупнее — читается через парту, мельче
# 5 pt печать уже не держит.
SIZES = [size / 2 for size in range(28, 9, -1)]  # 14 … 5 pt
PT = 25.4 / 72
LEADING = 1.15


def _lines(pdf, text, width):
    """Жадный перенос по словам; None — если одно слово шире строки."""
    lines = []
    for word in text.split():
        if pdf.get_string_width(word) > width:
            return None
        if lines and pdf.get_string_width(f"{lines[-1]} {word}") <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def fit(pdf, text):
    """
    Самый крупный кегль, при котором подпись встаёт в полосу, и её строки.

    Сперва одна строка, потом две — перенос лучше мелкого шрифта, пока строки
    помещаются по высоте. Не встала и так — None: обрезать молча нельзя,
    на бумаге оказалось бы не то, что просили.
    """
    width = CELL_WIDTH - 2 * SIDE
    height = LABEL_HEIGHT - TOP - BOTTOM
    for size in SIZES:
        pdf.set_font("DejaVu", size=size)
        lines = _lines(pdf, text, width)
        if lines and len(lines) * size * PT * LEADING <= height:
            return size, lines
    return None


def sheet_of(sheet):
    """Имя листа из запроса -> само имя; пустое — бланк ответов, чужое — отказ."""
    sheet = sheet or ANSWER
    if sheet not in SHEETS:
        api_error(
            Codes.BLANK_LABELS_INVALID,
            f"Unknown sheet «{sheet}».",
            field="sheet",
            count=QUESTIONS,
        )
    return sheet


def clean(labels, questions=QUESTIONS):
    """Строки подписей из присланного; отказ — с кодом и названной подписью."""
    if not isinstance(labels, list) or len(labels) > questions:
        api_error(
            Codes.BLANK_LABELS_INVALID,
            f"Labels must be a list of at most {questions} strings.",
            field="labels",
            count=questions,
        )
    cleaned = []
    for label in labels:
        if label is None:
            label = ""
        if not isinstance(label, str):
            api_error(
                Codes.BLANK_LABELS_INVALID,
                f"Labels must be a list of at most {questions} strings.",
                field="labels",
                count=questions,
            )
        cleaned.append(" ".join(label.split()))
    return cleaned + [""] * (questions - len(cleaned))


def overlay(labels, sheet=ANSWER):
    """Прозрачная страница A4 с подписями на своих местах."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(0, 0, 0)
    pdf.add_font("DejaVu", fname=str(FONT))
    pdf.add_page()

    for index, label in enumerate(labels):
        if not label:
            continue
        fitted = fit(pdf, label) if len(label) <= MAX_LABEL else None
        if fitted is None:
            api_error(
                Codes.BLANK_LABEL_TOO_LONG,
                f"«{label}» does not fit into a cell of the blank.",
                field="labels",
                label=label,
                cell=index + 1,
            )
        size, lines = fitted
        pdf.set_font("DejaVu", size=size)
        line = size * PT * LEADING
        left, band = cell_origin(sheet, index)
        top = band + TOP + (LABEL_HEIGHT - TOP - BOTTOM - line * len(lines)) / 2
        for number, text in enumerate(lines):
            pdf.set_xy(left + SIDE, top + number * line)
            pdf.cell(CELL_WIDTH - 2 * SIDE, line, text, align="C")

    return bytes(pdf.output())


def file_name(sheet=ANSWER):
    """Как назвать скачанный файл: по листу, а не одним именем на оба."""
    return SHEETS[sheet_of(sheet)]["file"]


def render(labels, sheet=ANSWER):
    """
    Лист целиком с подписями: у бланка ответов обе страницы (лицо и оборот),
    у листа баллов одна.

    Подложка у каждого своя, а надпечатка одна: полоса подписи у маркгрида та
    же, что в шапке бланка, отличается только то, где стоит линейка.
    """
    sheet = sheet_of(sheet)
    labels = clean(labels, SHEETS[sheet]["questions"])
    layer = PdfReader(BytesIO(overlay(labels, sheet))).pages[0]

    writer = PdfWriter(clone_from=PdfReader(SHEETS[sheet]["template"]))
    for page in writer.pages:
        page.merge_page(layer)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
