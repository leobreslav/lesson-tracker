"""
Каталог банка: что видно, что правится, и как книга попадает внутрь.

Заводить книгу по одной задаче не станет никто, поэтому и оглавление, и список
задач **вставляются целиком** — тем же приёмом, каким в проект попадают состав
класса и учебный план. Разбор устроен по тем же правилам: вместо угадывания —
отказ, строка называет свой номер.
"""

from config.errors import Codes, api_error
from django.db import transaction

from .models import Entry, Problem, Section, Solution, Source, Tag


def refuse_unless_writable(user, item) -> None:
    """
    Право правки — по владению. Системное правит суперпользователь, школьное и
    личное — администратор школы (он школьный суперпользователь), личное — ещё
    и автор.
    """
    if type(item).objects.writable_by(user).filter(pk=item.pk).exists():
        return

    api_error(
        Codes.BANK_READ_ONLY,
        "This entry is read-only for you: make your own copy to change it.",
        field="id",
    )


def parse_outline(text: str) -> list[dict]:
    """
    Оглавление строками с отступом → плоский список с уровнями.

    Отступ задаёт вложенность: два пробела или таб — один уровень. Пустые
    строки пропускаются, «прыжок» глубины через уровень отклоняется: это почти
    всегда опечатка, а угадывать, что имелось в виду, мы не беремся.
    """
    rows = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue

        body = raw.replace("\t", "  ")
        depth = (len(body) - len(body.lstrip(" "))) // 2
        title = body.strip()

        if rows and depth > rows[-1]["depth"] + 1:
            api_error(
                Codes.OUTLINE_JUMP,
                f"Line {number} is indented more than one level deeper than the "
                f"line above it.",
                field="outline",
                line=number,
            )
        rows.append({"depth": depth, "title": title})

    if not rows:
        api_error(Codes.OUTLINE_EMPTY, "There is nothing to read.", field="outline")
    return rows


def set_outline(source, text: str) -> int:
    """
    Заменить оглавление источника целиком.

    Целиком, а не построчно, по той же причине, что у шкалы и строк шаблона:
    порядок — это индекс в присланном, и ни дыры, ни дубля возникнуть не может.
    Разделы с задачами при этом не выбрасываются молча: если задачи уже
    расставлены, они остаются у источника, потеряв раздел.
    """
    rows = parse_outline(text)

    with transaction.atomic():
        source.sections.all().delete()
        stack: list[Section] = []
        for position, row in enumerate(rows):
            parent = stack[row["depth"] - 1] if row["depth"] else None
            section = Section.objects.create(
                source=source,
                parent=parent,
                title=row["title"],
                position=position,
            )
            del stack[row["depth"]:]
            stack.append(section)

    return len(rows)


def parse_problems(text: str) -> list[dict]:
    """
    Задачи строками «номер ⇥ условие».

    Табуляция или два пробела подряд отделяют номер от условия — так строка
    приезжает из таблицы и из книги. Номера может не быть вовсе: тогда вся
    строка это условие.
    """
    rows = []
    for number, raw in enumerate(text.splitlines(), start=1):
        # обрезаем только края, но не разделитель: `strip()` съедал табуляцию,
        # и строка «6⇥» становилась условием «6» вместо отказа
        line = raw.strip(" \r")
        if not line.strip():
            continue

        if "\t" in line:
            label, _, body = line.partition("\t")
        elif "  " in line:
            label, _, body = line.partition("  ")
        else:
            label, body = "", line

        body = body.strip()
        if not body:
            api_error(
                Codes.PROBLEM_TEXT_REQUIRED,
                f"Line {number} has a number but no statement.",
                field="problems",
                line=number,
            )
        rows.append({"label": label.strip(), "text": body})

    if not rows:
        api_error(Codes.OUTLINE_EMPTY, "There is nothing to read.", field="problems")
    return rows


def add_problems(source, *, section, text: str, user) -> int:
    """
    Вписать задачи в раздел источника. Заводит условия и связи разом.

    Владение у заведённых условий — то же, что у источника: задачи системной
    книги системные, школьной — школьные. Иначе учитель, вписавший главу в
    общую книгу, оказался бы владельцем половины её содержимого.
    """
    rows = parse_problems(text)

    with transaction.atomic():
        start = source.entries.count()
        for offset, row in enumerate(rows):
            problem = Problem.objects.create(
                school=source.school,
                owner=source.owner,
                created_by=user,
                text=row["text"],
            )
            Entry.objects.create(
                source=source,
                section=section,
                problem=problem,
                label=row["label"],
                position=start + offset,
            )

    return len(rows)


def outline_of(source) -> list[dict]:
    """Оглавление плоским списком с уровнями — рисовать его отступом."""
    sections = list(source.sections.all())
    depth = {}
    out = []
    for section in sections:
        depth[section.pk] = depth.get(section.parent_id, -1) + 1
        out.append(
            {
                "id": section.pk,
                "title": section.title,
                "depth": depth[section.pk],
                "problems": section.entries.count(),
            }
        )
    return out


def tag_tree(kind: str | None = None) -> list[dict]:
    """Словарь плоским списком с уровнями: рисуется отступом, как оглавление."""
    tags = Tag.objects.filter(retired=False)
    if kind:
        tags = tags.filter(kind=kind)

    depth = {}
    out = []
    for tag in tags.order_by("kind", "position", "name"):
        depth[tag.pk] = depth.get(tag.parent_id, -1) + 1
        out.append(
            {
                "id": tag.pk,
                "kind": tag.kind,
                "name": tag.name,
                "parent": tag.parent_id,
                "depth": depth[tag.pk],
            }
        )
    return out


def asked_in(problem, user):
    """Мост в работы: считает его `works.assembling`, который знает про них."""
    from works import assembling

    return assembling.asked_in(problem, user)


def problem_payload(problem, *, user) -> dict:
    """Условие целиком: решения, где встречается, аналоги."""
    from .models import Family

    analogues = []
    if problem.family_id:
        analogues = [
            {"id": other.pk, "text": other.text}
            for other in Problem.objects.visible_to(user)
            .filter(family_id=problem.family_id)
            .exclude(pk=problem.pk)
        ]

    return {
        "id": problem.pk,
        "text": problem.text,
        "answers": list(problem.answers),
        "level": problem.level,
        "may_edit": Problem.objects.writable_by(user).filter(pk=problem.pk).exists(),
        "created_by": (problem.created_by and problem.created_by.get_full_name()) or "",
        "copied_from": problem.copied_from_id,
        "tags": [
            {"id": link.tag_id, "name": link.tag.name, "kind": link.tag.kind}
            for link in problem.links.select_related("tag")
        ],
        "sources": [
            {
                "id": entry.source_id,
                "title": entry.source.title,
                "section": entry.section and entry.section.title,
                "label": entry.label,
                "page": entry.page,
            }
            for entry in problem.entries.select_related("source", "section")
        ],
        "solutions": [
            {
                "id": solution.pk,
                "title": solution.title,
                "text": solution.text,
                "level": solution.level,
                "may_edit": Solution.objects.writable_by(user)
                .filter(pk=solution.pk)
                .exists(),
                "author": (solution.created_by and solution.created_by.get_full_name())
                or "",
                "tags": [
                    {
                        "id": link.tag_id,
                        "name": link.tag.name,
                        "kind": link.tag.kind,
                        "side": link.side,
                    }
                    for link in solution.links.select_related("tag")
                ],
            }
            for solution in Solution.objects.visible_to(user)
            .filter(problem=problem, retired=False)
            .prefetch_related("links__tag")
            .select_related("created_by")
        ],
        "analogues": analogues,
        # Где эту задачу уже спрашивали — среди своих курсов. Ради этого
        # ссылка на банк в работе и стоит: не задать одно и то же дважды.
        "asked_in": asked_in(problem, user),
    }
