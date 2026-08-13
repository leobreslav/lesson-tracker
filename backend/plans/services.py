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
from django.db.models import Count

from config.errors import Codes, error_payload

from .content import CONTENT_FIELDS

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

# первая ячейка шапки, если в файле есть столбец id
ID_CELLS = {"id", "ид", "№"}
CSV_HEADER_WITH_IDS = ("id",) + CSV_HEADER


class PlanImportError(Exception):
    """Файл целиком непригоден: пользователю показывается как есть."""


@dataclass(frozen=True)
class ImportedRow:
    """
    Строка файла, уже понятая: заголовок темы или урок.

    Та же форма служит и библиотеке, поэтому кроме названия она умеет нести
    содержание урока и его вложения. CSV ни того, ни другого не выражает и
    оставляет пустыми — способ заполнить план от этого не меняется.

    `attachments` — существующие объекты `files.Attachment`, а не их копии:
    перенос делает `files.services.copy_attachments`, и он не трогает байты.

    `node_id` заполняется только при разборе файла со столбцом id: это
    заявка «эта строка — вот тот узел плана», и проверяет её `plan_sync`.
    """

    is_section: bool
    title: str
    note: str = ""
    content: dict | None = None
    attachments: Sequence = ()
    node_id: int | None = None
    # номер строки в файле — нужен, чтобы ошибка синхронизации могла
    # показать, где именно смотреть
    row_number: int = 0
    # «этот урок не внутри предыдущей темы». Ставит только разбор файла со
    # столбцом id: там тема написана в каждой строке урока, и пустая ячейка
    # темы — это утверждение, а не умолчание
    at_top_level: bool = False


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


def header_with_ids(cells: Sequence[str]) -> bool:
    """Шапка вида `id,Тема,Урок,Заметка` — та, что выдаёт экспорт."""
    return bool(cells) and cells[0].strip().lower() in ID_CELLS and (
        looks_like_header(cells[1:]) or not any(cell.strip() for cell in cells[1:])
    )


def detect_ids(raw_rows: Sequence[Sequence[str]]) -> bool:
    """
    Есть ли в файле столбец id — решается по файлу целиком, а не по строке.

    Обычно отвечает шапка: экспорт всегда её пишет. Но шапку часто удаляют,
    поэтому есть и второй признак: столбцов не меньше четырёх, в первом
    только числа или пустота, и хотя бы одно число там есть. Без последнего
    условия трёхстолбцовый файл, у которого Excel дописал пустую колонку, а
    все темы протянуты пустыми ячейками, был бы разобран со сдвигом — то
    есть темы уехали бы в уроки.
    """
    filled = [row for row in raw_rows if any(cell.strip() for cell in row)]
    if not filled:
        return False

    if header_with_ids(filled[0]):
        return True

    if max(len(row) for row in filled) < 4:
        return False

    first = [row[0].strip() for row in filled]
    return any(first) and all(cell == "" or cell.isdigit() for cell in first)


class ParsedPlan(NamedTuple):
    """Разобранный файл: строки, предупреждения и был ли в нём столбец id."""

    rows: list
    warnings: list
    has_ids: bool


def parse_plan_csv(text: str, *, max_rows: int = CSV_MAX_ROWS) -> ParsedPlan:
    """
    Разбор плана построчно.

    Тема в первом столбце, урок во втором, заметка в третьем. Если тема
    указана в каждой строке урока («протягивание»), новый заголовок
    создаётся при её смене. Уроки до первого заголовка остаются вне темы.

    Со столбцом id всё то же самое, только сдвинуто на колонку вправо: сам
    id ничего в разборе не меняет и просто едет с строкой дальше.
    """
    raw_rows = []
    for number, raw in enumerate(csv.reader(io.StringIO(text),
                                            delimiter=sniff_delimiter(text)), start=1):
        if number > max_rows:
            raise PlanImportError(
                f"The file has more than {max_rows} rows — split it into parts."
            )
        raw_rows.append(raw)

    has_ids = detect_ids(raw_rows)
    shift = 1 if has_ids else 0
    width = 3 + shift

    rows: list[ImportedRow] = []
    warnings: list[dict] = []
    current_theme: str | None = None

    for number, raw in enumerate(raw_rows, start=1):
        # лишние столбцы справа игнорируем, недостающие дополняем
        cells = [cell.strip() for cell in raw[:width]] + [""] * max(0, width - len(raw))
        node_id, theme, lesson, note = (
            (cells[0], *cells[1:]) if has_ids else ("", *cells)
        )

        if number == 1 and (
            header_with_ids(cells) if has_ids else looks_like_header(cells)
        ):
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

        pk = int(node_id) if node_id.isdigit() else None

        if theme and not lesson:
            current_theme = theme
            rows.append(
                ImportedRow(
                    is_section=True, title=theme, note=note,
                    node_id=pk, row_number=number,
                )
            )
            continue

        if theme and theme != current_theme:
            # формат с протягиванием: тема сменилась — сначала заголовок.
            # id у такого заголовка нет и быть не может: он принадлежит
            # строке урока, а заголовок здесь выведен из неё
            current_theme = theme
            rows.append(ImportedRow(is_section=True, title=theme, row_number=number))

        rows.append(
            ImportedRow(
                is_section=False, title=lesson, note=note,
                node_id=pk, row_number=number,
                # без id пустая ячейка темы значит «внутри предыдущей темы»:
                # так пишут руками и так выглядит экспорт без id
                at_top_level=has_ids and not theme,
            )
        )

    return ParsedPlan(rows, warnings, has_ids)


def build_plan_csv(tree: Iterable[Branch], *, with_ids: bool = True) -> str:
    """
    План в CSV, симметрично разбору.

    Со столбцом id файл можно вернуть режимом sync: строки узнаются по id,
    и содержание уроков переживает обновление. Без него — прежний формат,
    годный для передачи другому человеку: чужие id ему ни о чём не говорят.

    Различаются они не только столбцом. В формате с id тема написана в
    **каждой** строке урока, и это не избыточность: иначе урок верхнего
    уровня, стоящий после темы, неотличим от урока внутри неё — известный
    предел трёхстолбцового формата. Синхронизация обязана возвращать план
    таким, каким он был, поэтому здесь пустая ячейка темы означает ровно
    «этот урок вне темы».

    BOM в начале — чтобы Excel открыл файл как UTF-8, а не как cp1251.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", lineterminator="\r\n")

    def put(node, theme, lesson):
        cells = [theme, lesson, node.note]
        writer.writerow([node.pk] + cells if with_ids else cells)

    writer.writerow(CSV_HEADER_WITH_IDS if with_ids else CSV_HEADER)

    for branch in tree:
        if branch.node.is_section:
            put(branch.node, branch.node.title, "")
            for child in branch.children:
                put(child, branch.node.title if with_ids else "", child.title)
        else:
            put(branch.node, "", branch.node.title)

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

    `pairs` in the result lines every row up with the node it became. The
    caller needs it to carry attachments across — those live in another app,
    and the plan does not have to know about it to write a plan.
    """
    from .models import PlanNode

    top_position = len(level(owner, None)) if append else 0
    section = None
    section_position = 0
    created = {"headers": 0, "lessons": 0, "pairs": []}

    for row in rows:
        content = row.content or {}

        if row.at_top_level:
            # файл сказал прямо: этот урок не в теме
            section = None

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
            created["pairs"].append((row, section))
            continue

        node = PlanNode.objects.create(
            teacher_id=owner.teacher_id,
            course_id=owner.course_id,
            parent=section,
            position=section_position if section else top_position,
            is_section=False,
            title=row.title,
            note=row.note,
            **{field: content.get(field, "") for field in CONTENT_FIELDS},
        )
        if section:
            section_position += 1
        else:
            top_position += 1
        created["lessons"] += 1
        created["pairs"].append((row, node))

    return created


# --- sync: the plan updated from a file rather than rebuilt from it ---------
#
# Replace and append both treat the file as the whole truth, and that costs
# the lesson content: a rewritten row is a new row, and a new row is empty.
# Sync reads the id column instead, so a row that was already there is
# *updated* — title, note and place in the tree — while everything the file
# cannot express (the four content fields, the attachments) is simply left
# alone.
#
# The whole file is checked before a single row is written. A half-applied
# plan is worse than a rejected one: the person would have to work out which
# half, and the file no longer matches either state.


class NewNode(NamedTuple):
    """A row that does not exist yet, named by its place in `SyncPlan.create`."""

    index: int


@dataclass(frozen=True)
class SyncPlan:
    """What sync would do, worked out before anything is written."""

    create: list          # ImportedRow without an id
    update: list          # (node, row, parent_id, position)
    delete: list          # nodes the file no longer mentions
    errors: list          # blocking: any one of these stops the import

    @property
    def ok(self) -> bool:
        return not self.errors


def _sync_errors(rows, known: dict) -> list:
    """Everything wrong with the file, all of it, before anything is written."""
    errors = []
    seen = set()

    for row in rows:
        if row.node_id is None:
            continue

        if row.node_id in seen:
            errors.append(
                error_payload(
                    Codes.CSV_ID_DUPLICATE,
                    f"Row {row.row_number}: id {row.node_id} is used twice.",
                    row=row.row_number, id=row.node_id,
                )
            )
            continue

        seen.add(row.node_id)
        node = known.get(row.node_id)

        if node is None:
            # чужой и несуществующий неразличимы намеренно: id чужого плана
            # не должен подтверждаться сообщением о том, что он существует
            errors.append(
                error_payload(
                    Codes.CSV_ID_UNKNOWN,
                    f"Row {row.row_number}: id {row.node_id} is not in this plan.",
                    row=row.row_number, id=row.node_id,
                )
            )
        elif node.is_section != row.is_section:
            # тема с уроками, ставшая уроком, осиротила бы своих детей;
            # разворачивать это молча нельзя, а угадывать нечего
            errors.append(
                error_payload(
                    Codes.CSV_ID_KIND_CHANGED,
                    f"Row {row.row_number}: id {row.node_id} is a "
                    f"{'section' if node.is_section else 'lesson'} in the plan.",
                    row=row.row_number, id=row.node_id, title=node.title,
                )
            )

    return errors


def plan_sync(owner: PlanOwner, rows: Iterable[ImportedRow]) -> SyncPlan:
    """
    Работает без записи: тем же расчётом пользуются и предпросмотр, и импорт.

    Порядок строк в файле и есть новый порядок плана, поэтому позиции
    считаются здесь же — сначала по файлу, а не переписыванием уже
    сдвинутого дерева.
    """
    rows = list(rows)
    known = {node.pk: node for node in plan_nodes(owner)}

    errors = _sync_errors(rows, known)
    if errors:
        # дальше считать нечего: план строится по id, а им нельзя верить
        return SyncPlan(create=[], update=[], delete=[], errors=errors)

    create, update, kept = [], [], set()
    section_ref = None
    top_position = 0
    section_position = 0

    for row in rows:
        if row.at_top_level:
            section_ref = None

        if row.is_section:
            parent_ref, position = None, top_position
            top_position += 1
            section_position = 0
        elif section_ref is not None:
            parent_ref, position = section_ref, section_position
            section_position += 1
        else:
            parent_ref, position = None, top_position
            top_position += 1

        if row.node_id is None:
            create.append((row, parent_ref, position))
            # у новой темы id появится только при записи, поэтому её уроки
            # ссылаются на место в списке создаваемых, а не на pk
            ref = NewNode(len(create) - 1)
        else:
            kept.add(row.node_id)
            update.append((known[row.node_id], row, parent_ref, position))
            ref = row.node_id

        if row.is_section:
            section_ref = ref

    delete = [node for pk, node in known.items() if pk not in kept]

    return SyncPlan(create=create, update=update, delete=delete, errors=[])


def apply_sync(owner: PlanOwner, plan: SyncPlan) -> dict:
    """Записать посчитанное. Вызывается внутри транзакции."""
    from .models import PlanNode

    if not plan.ok:
        raise ValueError("refusing to apply a sync plan with errors")

    fresh: dict[NewNode, int] = {}

    def pk_of(ref):
        """A parent reference into a real id: None, a pk, or a fresh section."""
        return fresh[ref] if isinstance(ref, NewNode) else ref

    def build(row, parent_ref, position):
        return PlanNode.objects.create(
            teacher_id=owner.teacher_id,
            course_id=owner.course_id,
            parent_id=pk_of(parent_ref),
            position=position,
            is_section=row.is_section,
            title=row.title,
            note=row.note,
        )

    # темы первыми: урок под новой темой должен знать её id
    for index, (row, parent_ref, position) in enumerate(plan.create):
        if row.is_section:
            fresh[NewNode(index)] = build(row, parent_ref, position).pk

    # обновляем до удаления: урок, ушедший из удаляемой темы, должен успеть
    # сменить родителя, иначе его унесёт каскадом
    changed = []
    for node, row, parent_ref, position in plan.update:
        node.title = row.title
        node.note = row.note
        node.parent_id = pk_of(parent_ref)
        node.position = position
        changed.append(node)

    if changed:
        PlanNode.objects.bulk_update(changed, ["title", "note", "parent", "position"])

    for index, (row, parent_ref, position) in enumerate(plan.create):
        if not row.is_section:
            build(row, parent_ref, position)

    created = len(plan.create)
    deleted = len(plan.delete)
    if deleted:
        PlanNode.objects.filter(pk__in=[node.pk for node in plan.delete]).delete()

    return {"created": created, "updated": len(plan.update), "deleted": deleted}


def plan_nodes(owner: PlanOwner):
    """
    A teacher's nodes in a course, with the attachment count alongside.

    Counting here rather than per row: the plan page draws a paperclip on
    every lesson that has one, and asking the database once beats asking it
    two hundred times.
    """
    from .models import PlanNode

    return PlanNode.objects.filter(
        teacher_id=owner.teacher_id, course_id=owner.course_id
    ).annotate(attachment_count=Count("attachments"))


def get_tree(owner: PlanOwner) -> list[Branch]:
    return build_tree(plan_nodes(owner))


def flatten_lessons(owner: PlanOwner) -> list[Lesson]:
    """The flat lesson sequence — the one that later lands on the slots."""
    return number_lessons(get_tree(owner))
