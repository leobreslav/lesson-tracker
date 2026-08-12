"""
Учебный план: дерево ровно из двух уровней.

На верхнем уровне вперемешку лежат папки и уроки, внутри папки — только
уроки. Сквозная нумерация уроков нигде не хранится: её даёт обход в глубину,
папки в нумерации не участвуют.

Ядро (`build_tree`, `number_lessons`, `counts`, `structure_problems`) работает
над любыми объектами с полями `pk`/`parent_id`/`position`/`is_section`,
поэтому проверяется без базы. Ниже — обёртки, которые подставляют выборку из
ORM и переписывают позиции.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, NamedTuple, Sequence

from calendars.services import find_term

from config.errors import Codes, error_payload

SECTION_INSIDE_SECTION = Codes.SECTION_INSIDE_SECTION
PARENT_NOT_SECTION = Codes.PARENT_NOT_SECTION
PARENT_OTHER_CLASS = Codes.PARENT_OTHER_CLASS

UP = "up"
DOWN = "down"
DIRECTIONS = (UP, DOWN)


@dataclass(frozen=True)
class Branch:
    """Узел верхнего уровня вместе с его уроками (у урока детей нет)."""

    node: object
    children: Sequence[object] = ()


@dataclass(frozen=True)
class Lesson:
    """Урок со сквозным номером и папкой, в которой он лежит."""

    number: int
    node: object
    section: object | None = None


def _order_key(node):
    # id как второй ключ: пока позиции не переписаны, порядок должен быть
    # предсказуемым, а не зависеть от того, как легли строки в базе
    return (node.position, node.pk or 0)


def build_tree(nodes: Iterable) -> list[Branch]:
    """Дерево верхнего уровня с вложенными детьми, всё по position."""
    ordered = sorted(nodes, key=_order_key)

    children = defaultdict(list)
    for node in ordered:
        if node.parent_id is not None:
            children[node.parent_id].append(node)

    return [
        Branch(node, tuple(children.get(node.pk, ())))
        for node in ordered
        if node.parent_id is None
    ]


def number_lessons(tree: Iterable[Branch]) -> list[Lesson]:
    """
    Уроки в порядке обхода в глубину со сквозными номерами.

    Уровней ровно два, поэтому «обход» — это цикл по верхнему уровню с
    заходом в детей папки; папки сами номеров не получают.
    """
    lessons: list[Lesson] = []

    for branch in tree:
        if branch.node.is_section:
            for child in branch.children:
                lessons.append(Lesson(len(lessons) + 1, child, branch.node))
        else:
            lessons.append(Lesson(len(lessons) + 1, branch.node))

    return lessons


def lesson_numbers(tree: Iterable[Branch]) -> dict[int, int]:
    return {lesson.node.pk: lesson.number for lesson in number_lessons(tree)}


def counts(tree: Iterable[Branch]) -> dict:
    branches = list(tree)
    lessons = number_lessons(branches)

    return {
        "lessons": len(lessons),
        "sections": sum(1 for branch in branches if branch.node.is_section),
    }


# статусы записи раскладки
STATUS_MATCHED = "matched"
STATUS_NO_SLOT = "no_slot"
STATUS_NO_PLAN = "no_plan"


@dataclass(frozen=True)
class LayoutEntry:
    """Одна строка раскладки: слот и урок плана, которые встретились."""

    status: str
    slot: object | None = None
    lesson: Lesson | None = None
    # терм, в который попала дата слота; у записей без слота его нет
    term: object | None = None


def build_layout(
    lessons: Sequence[Lesson], slots: Sequence, terms: Iterable = ()
) -> list[LayoutEntry]:
    """
    Позиционное сопоставление плана и расписания: i-й урок в i-й слот.

    Ничего не хранит и не создаёт: несовпадение длин — это пометки.
    Лишние слоты идут как `no_plan` на своих местах, лишние уроки плана —
    как `no_slot` в конце. Прошлое и будущее в расчёте не различаются:
    правка задним числом честно двигает всю раскладку.

    `lessons` — уроки плана по порядку (заголовки отфильтрованы),
    `slots` — неотменённые слоты по (дате, номеру). Запросы делаются
    снаружи, функция чистая.
    """
    terms = list(terms)

    entries = [
        LayoutEntry(
            status=STATUS_MATCHED if index < len(lessons) else STATUS_NO_PLAN,
            slot=slot,
            lesson=lessons[index] if index < len(lessons) else None,
            term=find_term(slot.date, terms),
        )
        for index, slot in enumerate(slots)
    ]

    entries.extend(
        LayoutEntry(status=STATUS_NO_SLOT, lesson=lesson)
        for lesson in lessons[len(slots) :]
    )

    return entries


def summary_by_term(entries: Sequence[LayoutEntry], terms: Iterable = ()) -> list[dict]:
    """
    Слоты и уроки плана по термам плюс отдельная запись «вне термов».

    Баланс терма — `slots - lessons`. Раскладка позиционная, поэтому внутри
    заполненного терма он нулевой; минус появляется там, где плану не хватило
    слотов (такие уроки дат не имеют и попадают в «вне термов»), плюс — там,
    где слоты остались свободными.
    """
    def bucket(name, items, term=None):
        slots = sum(1 for entry in items if entry.slot is not None)
        lessons = sum(1 for entry in items if entry.lesson is not None)
        return {
            "id": term.pk if term is not None else None,
            "name": name,
            "start": term.start_date if term is not None else None,
            "end": term.end_date if term is not None else None,
            "slots": slots,
            "lessons": lessons,
            "balance": slots - lessons,
        }

    rows = [
        bucket(
            term.name,
            [e for e in entries if e.term is not None and e.term.pk == term.pk],
            term,
        )
        for term in terms
    ]

    outside = [entry for entry in entries if entry.term is None]
    if outside:
        rows.append(bucket("вне термов", outside))

    return rows


def layout_summary(
    entries: Iterable[LayoutEntry],
    today,
    cancelled_count: int = 0,
    terms: Iterable = (),
) -> dict:
    """
    Итоги раскладки. `today` влияет только на счётчики «прошло/осталось»,
    но не на само сопоставление.
    """
    entries = list(entries)
    with_slot = [entry for entry in entries if entry.slot is not None]
    with_lesson = [entry for entry in entries if entry.lesson is not None]
    matched = [entry for entry in entries if entry.status == STATUS_MATCHED]

    past_slots = [entry for entry in with_slot if entry.slot.date < today]
    past_lessons = [entry for entry in matched if entry.slot.date < today]

    # план не помещается — последнего урока в году просто нет
    fits = len(matched) == len(with_lesson)
    last_lesson_date = matched[-1].slot.date if fits and matched else None

    return {
        "lessons_total": len(with_lesson),
        "slots_total": len(with_slot),
        "balance": len(with_slot) - len(with_lesson),
        "past_slots": len(past_slots),
        "remaining_slots": len(with_slot) - len(past_slots),
        "past_lessons": len(past_lessons),
        "remaining_lessons": len(with_lesson) - len(past_lessons),
        "last_lesson_date": last_lesson_date,
        "cancelled_count": cancelled_count,
        "extra_count": sum(1 for entry in with_slot if entry.slot.is_extra),
        "terms": summary_by_term(entries, terms),
    }


def structure_problems(*, course_id, parent, is_section) -> dict:
    """
    Tree rule violations as ``{field: (code, message)}``; empty means fine.

    One check for everybody: both ``PlanNode.clean`` and the serializers call
    it, so the admin and the API always agree.
    """
    if parent is None:
        return {}

    if is_section:
        return {
            "parent": (SECTION_INSIDE_SECTION, "A section can only live at the top level.")
        }

    if not parent.is_section:
        return {"parent": (PARENT_NOT_SECTION, "A node can only be nested into a section.")}

    if parent.course_id != course_id:
        return {"parent": (PARENT_OTHER_CLASS, "That section belongs to another course.")}

    return {}


# --- CSV: разбор и выгрузка, тоже без ORM ---

CSV_HEADER = ("Тема", "Урок", "Заметка")
CSV_MAX_ROWS = 2000
TITLE_LIMIT = 200

# слова шапки: строка считается шапкой, только если ВСЕ её ячейки такие
HEADER_CELLS = {
    "тема", "темы", "раздел", "topic", "section",
    "урок", "уроки", "название", "тема урока", "lesson",
    "заметка", "заметки", "примечание", "комментарий", "note",
}


class PlanImportError(Exception):
    """Файл целиком непригоден: пользователю показывается как есть."""


@dataclass(frozen=True)
class ImportedRow:
    """Строка файла, уже понятая: заголовок темы или урок."""

    is_section: bool
    title: str
    note: str = ""


def decode_csv(data: bytes) -> str:
    """
    Текст файла независимо от того, чем его сохранили.

    UTF-8 (в том числе с BOM) пробуем первым: cp1251 «читает» почти любые
    байты и молча превратил бы кириллицу в кракозябры.
    """
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue

        # cp1251 «читает» и двоичный мусор: нулевые байты выдают его с головой
        # (Postgres такую строку всё равно не примет)
        if "\x00" in text:
            break

        return text

    raise PlanImportError(
        "The file could not be read: a plain CSV in UTF-8 or Windows-1251 "
        "is expected."
    )


def sniff_delimiter(text: str) -> str:
    """
    Русский Excel сохраняет с точкой с запятой, остальные — с запятой.

    Считать вхождения бесполезно: запятые бывают внутри названий. Смотрим,
    какой разделитель даёт одинаковое число столбцов в строках.
    """
    head = [line for line in text.splitlines()[:5] if line.strip()]
    if not head:
        return ","

    def score(candidate):
        widths = [len(row) for row in csv.reader(head, delimiter=candidate)]
        return (len(set(widths)) == 1 and min(widths) > 1, min(widths))

    return ";" if score(";") > score(",") else ","


def looks_like_header(cells: Sequence[str]) -> bool:
    filled = [cell.strip().lower() for cell in cells if cell.strip()]
    return bool(filled) and all(cell in HEADER_CELLS for cell in filled)


def parse_plan_csv(text: str, *, max_rows: int = CSV_MAX_ROWS):
    """
    Разбор плана построчно. Возвращает (строки, предупреждения).

    Тема в первом столбце, урок во втором, заметка в третьем. Если тема
    указана в каждой строке урока («протягивание»), новый заголовок
    создаётся при её смене. Уроки до первого заголовка остаются вне темы.
    """
    reader = csv.reader(io.StringIO(text), delimiter=sniff_delimiter(text))

    rows: list[ImportedRow] = []
    warnings: list[dict] = []
    current_theme: str | None = None

    for number, raw in enumerate(reader, start=1):
        if number > max_rows:
            raise PlanImportError(
                f"The file has more than {max_rows} rows — split it into parts."
            )

        # лишние столбцы справа игнорируем, недостающие дополняем
        cells = [cell.strip() for cell in raw[:3]] + [""] * max(0, 3 - len(raw))
        theme, lesson, note = cells[0], cells[1], cells[2]

        if number == 1 and looks_like_header(cells):
            continue

        if not theme and not lesson:
            if any(cell.strip() for cell in raw):
                warnings.append(
                    error_payload(
                        Codes.CSV_ROW_EMPTY,
                        f"Row {number}: neither a section nor a lesson — skipped.",
                        row=number,
                    )
                )
            continue

        if max(len(theme), len(lesson)) > TITLE_LIMIT:
            warnings.append(
                error_payload(
                    Codes.CSV_ROW_TOO_LONG,
                    f"Row {number}: the title is longer than {TITLE_LIMIT} characters — skipped.",
                    row=number,
                    limit=TITLE_LIMIT,
                )
            )
            continue

        if theme and not lesson:
            current_theme = theme
            rows.append(ImportedRow(is_section=True, title=theme, note=note))
            continue

        if theme and theme != current_theme:
            # формат с протягиванием: тема сменилась — сначала заголовок
            current_theme = theme
            rows.append(ImportedRow(is_section=True, title=theme))

        rows.append(ImportedRow(is_section=False, title=lesson, note=note))

    return rows, warnings


def build_plan_csv(tree: Iterable[Branch]) -> str:
    """
    План в CSV, симметрично разбору.

    BOM в начале — чтобы Excel открыл файл как UTF-8, а не как cp1251.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", lineterminator="\r\n")
    writer.writerow(CSV_HEADER)

    for branch in tree:
        if branch.node.is_section:
            writer.writerow([branch.node.title, "", branch.node.note])
            for child in branch.children:
                writer.writerow(["", child.title, child.note])
        else:
            writer.writerow(["", branch.node.title, branch.node.note])

    # \ufeff — тот самый BOM, в исходнике он невидим, поэтому кодом
    return "\ufeff" + buffer.getvalue()


# --- from here on the database is involved: node order has to be stored ---


class PlanOwner(NamedTuple):
    """
    Whose plan, in which course.

    A course now holds the plans of everyone teaching it, so neither key
    alone identifies a tree. A `PlanNode` carries both fields and can be
    passed wherever an owner is expected.
    """

    teacher_id: int
    course_id: int


def _parent_id(parent):
    return parent.pk if hasattr(parent, "pk") else parent


def level(owner, parent=None) -> list:
    """
    Siblings of one level, in order.

    `owner` is the (teacher, course) pair, not the course alone: one course
    holds the plans of everyone teaching it, and a level must never mix them.
    Any node carries both keys, so a node can stand in for the pair.
    """
    from .models import PlanNode

    return sorted(
        PlanNode.objects.filter(
            teacher_id=owner.teacher_id,
            course_id=owner.course_id,
            parent_id=_parent_id(parent),
        ),
        key=_order_key,
    )


def reindex(owner, parent=None) -> list:
    """Renumber a level without gaps: 0, 1, 2, …"""
    from .models import PlanNode

    nodes = level(owner, parent)
    changed = []

    for position, node in enumerate(nodes):
        if node.position != position:
            node.position = position
            changed.append(node)

    if changed:
        PlanNode.objects.bulk_update(changed, ["position"])

    return nodes


def place(node, parent, index: int) -> None:
    """Put a node onto the given level at the given position."""
    from .models import PlanNode

    parent_id = _parent_id(parent)
    previous_parent_id = node.parent_id

    siblings = [item for item in level(node, parent_id) if item.pk != node.pk]
    index = max(0, min(index, len(siblings)))

    node.parent_id = parent_id
    siblings.insert(index, node)

    for position, item in enumerate(siblings):
        item.position = position

    PlanNode.objects.bulk_update(siblings, ["position", "parent"])

    if previous_parent_id != parent_id:
        # the level just left behind now has a gap
        reindex(node, previous_parent_id)


def move(node, direction: str) -> bool:
    """
    One step among siblings — entering sections and leaving them.

    A top-level lesson running into a section enters it as the outermost
    element; a lesson that reached the edge of a section comes out and stands
    next to it. Two buttons therefore walk a lesson through the whole tree.

    Returns False when there is nowhere to go: the edge of the tree.
    """
    step = -1 if direction == UP else 1
    siblings = level(node, node.parent_id)
    index = next(i for i, item in enumerate(siblings) if item.pk == node.pk)
    target = index + step

    if node.parent_id is None:
        if not 0 <= target < len(siblings):
            return False

        neighbour = siblings[target]
        if neighbour.is_section and not node.is_section:
            # from above we enter first, from below last
            inside = level(node, neighbour)
            place(node, neighbour, 0 if step > 0 else len(inside))
            return True

        place(node, None, target)
        return True

    if 0 <= target < len(siblings):
        place(node, node.parent, target)
        return True

    # the edge of a section — surface to the top level next to it
    top = level(node, None)
    section_index = next(i for i, item in enumerate(top) if item.pk == node.parent_id)
    place(node, None, section_index + (1 if step > 0 else 0))
    return True


def dissolve_section(section) -> None:
    """Delete a section, lifting its lessons to its place on the top level."""
    from .models import PlanNode

    children = level(section, section)
    top = level(section, None)

    order = []
    for item in top:
        if item.pk == section.pk:
            order.extend(children)
        else:
            order.append(item)

    for child in children:
        child.parent_id = None
    for position, item in enumerate(order):
        item.position = position

    PlanNode.objects.bulk_update(order, ["position", "parent"])
    # the children are detached already, the cascade will not reach them
    section.delete()


def apply_import(owner: PlanOwner, rows: Iterable[ImportedRow], *, append: bool) -> dict:
    """
    Create nodes from the parsed rows. Called inside a transaction.

    A lesson lands in the last header seen; until a header appears it stays
    on the top level.
    """
    from .models import PlanNode

    top_position = len(level(owner, None)) if append else 0
    section = None
    section_position = 0
    created = {"headers": 0, "lessons": 0}

    for row in rows:
        if row.is_section:
            section = PlanNode.objects.create(
                teacher_id=owner.teacher_id,
                course_id=owner.course_id,
                parent=None,
                position=top_position,
                is_section=True,
                title=row.title,
                note=row.note,
            )
            top_position += 1
            section_position = 0
            created["headers"] += 1
            continue

        PlanNode.objects.create(
            teacher_id=owner.teacher_id,
            course_id=owner.course_id,
            parent=section,
            position=section_position if section else top_position,
            is_section=False,
            title=row.title,
            note=row.note,
        )
        if section:
            section_position += 1
        else:
            top_position += 1
        created["lessons"] += 1

    return created


def get_tree(owner: PlanOwner) -> list[Branch]:
    from .models import PlanNode

    return build_tree(
        PlanNode.objects.filter(
            teacher_id=owner.teacher_id, course_id=owner.course_id
        )
    )


def flatten_lessons(owner: PlanOwner) -> list[Lesson]:
    """The flat lesson sequence — the one that later lands on the slots."""
    return number_lessons(get_tree(owner))
