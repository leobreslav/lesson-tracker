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

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

# виды узлов-уроков
KIND_LESSON = "lesson"
KIND_CONTROL = "control"
KIND_RESERVE = "reserve"

KIND_CHOICES = (
    (KIND_LESSON, "урок"),
    (KIND_CONTROL, "контрольная"),
    (KIND_RESERVE, "резерв"),
)

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
        "control": sum(1 for item in lessons if item.node.kind == KIND_CONTROL),
        "reserve": sum(1 for item in lessons if item.node.kind == KIND_RESERVE),
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


def build_layout(lessons: Sequence[Lesson], slots: Sequence) -> list[LayoutEntry]:
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
    entries = [
        LayoutEntry(
            status=STATUS_MATCHED if index < len(lessons) else STATUS_NO_PLAN,
            slot=slot,
            lesson=lessons[index] if index < len(lessons) else None,
        )
        for index, slot in enumerate(slots)
    ]

    entries.extend(
        LayoutEntry(status=STATUS_NO_SLOT, lesson=lesson)
        for lesson in lessons[len(slots) :]
    )

    return entries


def layout_summary(entries: Iterable[LayoutEntry], today, cancelled_count: int = 0) -> dict:
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
    }


def structure_problems(*, school_class_id, parent, is_section) -> dict[str, str]:
    """
    Нарушения правил дерева. Пустой словарь — всё в порядке.

    Одна проверка на всех: её зовут и `PlanNode.clean`, и сериализаторы.
    """
    if parent is None:
        return {}

    if is_section:
        return {"parent": "Папка может лежать только на верхнем уровне."}

    if not parent.is_section:
        return {"parent": "Вложить узел можно только в папку."}

    if parent.school_class_id != school_class_id:
        return {"parent": "Папка принадлежит другому классу."}

    return {}


# --- дальше работа с базой: порядок узлов приходится хранить ---


def _parent_id(parent):
    return parent.pk if hasattr(parent, "pk") else parent


def level(school_class, parent=None) -> list:
    """Сиблинги одного уровня по порядку."""
    from .models import PlanNode

    return sorted(
        PlanNode.objects.filter(
            school_class=school_class, parent_id=_parent_id(parent)
        ),
        key=_order_key,
    )


def reindex(school_class, parent=None) -> list:
    """Перенумеровать уровень без дыр: 0, 1, 2, …"""
    from .models import PlanNode

    nodes = level(school_class, parent)
    changed = []

    for position, node in enumerate(nodes):
        if node.position != position:
            node.position = position
            changed.append(node)

    if changed:
        PlanNode.objects.bulk_update(changed, ["position"])

    return nodes


def place(node, parent, index: int) -> None:
    """Поставить узел на указанный уровень в указанное место."""
    from .models import PlanNode

    parent_id = _parent_id(parent)
    previous_parent_id = node.parent_id

    siblings = [item for item in level(node.school_class, parent_id) if item.pk != node.pk]
    index = max(0, min(index, len(siblings)))

    node.parent_id = parent_id
    siblings.insert(index, node)

    for position, item in enumerate(siblings):
        item.position = position

    PlanNode.objects.bulk_update(siblings, ["position", "parent"])

    if previous_parent_id != parent_id:
        # на покинутом уровне осталась дыра
        reindex(node.school_class, previous_parent_id)


def move(node, direction: str) -> bool:
    """
    Шаг узла среди сиблингов — с заходом в папки и выходом из них.

    Урок верхнего уровня, упирающийся в папку, входит в неё крайним
    элементом; урок, дошедший до края папки, выходит наружу и встаёт рядом
    с ней. Так кнопками можно провести урок через всё дерево.

    Возвращает False, если двигаться некуда: край дерева.
    """
    step = -1 if direction == UP else 1
    siblings = level(node.school_class, node.parent_id)
    index = next(i for i, item in enumerate(siblings) if item.pk == node.pk)
    target = index + step

    if node.parent_id is None:
        if not 0 <= target < len(siblings):
            return False

        neighbour = siblings[target]
        if neighbour.is_section and not node.is_section:
            # сверху заходим первым элементом, снизу — последним
            inside = level(node.school_class, neighbour)
            place(node, neighbour, 0 if step > 0 else len(inside))
            return True

        place(node, None, target)
        return True

    if 0 <= target < len(siblings):
        place(node, node.parent, target)
        return True

    # упёрлись в край папки — всплываем на верхний уровень рядом с ней
    top = level(node.school_class, None)
    section_index = next(i for i, item in enumerate(top) if item.pk == node.parent_id)
    place(node, None, section_index + (1 if step > 0 else 0))
    return True


def dissolve_section(section) -> None:
    """Удалить папку, подняв её уроки на верхний уровень на её место."""
    from .models import PlanNode

    children = level(section.school_class, section)
    top = level(section.school_class, None)

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
    # детей уже отвязали, каскад их не заденет
    section.delete()


def get_tree(school_class) -> list[Branch]:
    from .models import PlanNode

    return build_tree(PlanNode.objects.filter(school_class=school_class))


def flatten_lessons(school_class) -> list[Lesson]:
    """Плоская последовательность уроков — та, что позже ляжет на слоты."""
    return number_lessons(get_tree(school_class))
