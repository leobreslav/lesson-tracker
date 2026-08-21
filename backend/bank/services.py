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
    Задачи строками «номер ⇥ условие», пункты — отступом.

    Разбор понимает два случая, и различает их **отступ**, а не догадка:

        14\tДан треугольник ABC со сторонами 3, 4, 5.
          а)\tНайдите площадь.
          б)\tНайдите радиус вписанной окружности.

        15
          а)\t$x^2 = 4$
          б)\t$x^2 = 9$

        16а\tРешите неравенство …
        16б\tПостройте график …

    Первый номер — **сюжет**: у строки-номера есть текст, значит пункты без
    него бессмысленны, и в дереве задачи они его дети. Второй — просто номер:
    текста нет, и четыре уравнения под ним самостоятельны, а буквы им даёт
    книга. Третий — две отдельные задачи, у каждой свой номер целиком.

    Различить это машиной нельзя, и она не пытается: решает вписывающий. Зато
    **вместо угадывания — отказ**: строка с отступом, над которой нет номера,
    отклоняется с указанием своей строки, как и прыжок глубины в оглавлении.

    Отдаёт плоский список строк, у каждой `label`, `text` и `parts` —
    список таких же строк на один уровень глубже.
    """
    rows = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue

        # обрезаем только края, но не разделитель: `strip()` съедал табуляцию,
        # и строка «6⇥» становилась условием «6» вместо отказа
        # Отступ — только пробелы: табуляция здесь уже занята разделителем
        # номера и условия, и путать их нельзя.
        indented = raw[:1] == " "
        line = raw.strip(" \r")

        label, body, split = _split_row(line)
        row = {"label": label, "text": body, "parts": [], "line": number, "split": split}

        if not indented:
            rows.append(row)
            continue

        if not rows:
            api_error(
                Codes.PART_WITHOUT_NUMBER,
                f"Line {number} is indented but there is no number above it.",
                field="problems",
                line=number,
            )
        rows[-1]["parts"].append(row)

    if not rows:
        api_error(Codes.OUTLINE_EMPTY, "There is nothing to read.", field="problems")

    for row in rows:
        if row["parts"] and not row["split"]:
            # Строка с пунктами и без разделителя: «15» — это номер, а
            # «Решите уравнение:» — условие сюжета, и различить их можно
            # только разделителем. Одно слово читаем номером, а фразу
            # отклоняем: вместо угадывания — отказ.
            if row["text"].split() == [row["text"]]:
                row["label"], row["text"] = row["text"], ""
            else:
                api_error(
                    Codes.NUMBER_NEEDS_A_TAB,
                    f"Line {row['line']} has parts: separate its number from the "
                    "statement with a tab.",
                    field="problems",
                    line=row["line"],
                )

        # У номера с пунктами текста может не быть вовсе — это чистый адрес. А
        # вот у строки без пунктов условие обязательно: номер, за которым
        # ничего не стоит, это опечатка, а не задача.
        if not row["text"] and not row["parts"]:
            api_error(
                Codes.PROBLEM_TEXT_REQUIRED,
                f"Line {row['line']} has a number but no statement.",
                field="problems",
                line=row["line"],
            )
        for part in row["parts"]:
            if not part["text"]:
                api_error(
                    Codes.PROBLEM_TEXT_REQUIRED,
                    f"Line {part['line']} has a letter but no statement.",
                    field="problems",
                    line=part["line"],
                )

    return rows


def _split_row(line: str) -> tuple[str, str, bool]:
    """
    Номер и условие. Табуляция или два пробела подряд — так строка приезжает
    из таблицы и из книги; номера может не быть вовсе.

    Третьим отдаёт, был ли разделитель: без него строка неоднозначна, и
    решает это уже вызывающий — по тому, есть ли у неё пункты.
    """
    if "\t" in line:
        label, _, body = line.partition("\t")
    elif "  " in line:
        label, _, body = line.partition("  ")
    else:
        return "", line.strip(), False

    return label.strip(), body.strip(), True


def add_problems(source, *, section, text: str, user) -> int:
    """
    Вписать задачи в раздел источника. Заводит оба дерева разом.

    Владение у заведённых условий — то же, что у источника: задачи системной
    книги системные, школьной — школьные. Иначе учитель, вписавший главу в
    общую книгу, оказался бы владельцем половины её содержимого.

    Что получается из трёх случаев разбора:

    | вписано | дерево задачи | дерево книги |
    |---------|---------------|--------------|
    | номер с текстом и пунктами | сюжет и его дети | строка-номер и строки-пункты |
    | номер без текста, с пунктами | ничего: пункты самостоятельны | то же |
    | номер с текстом, без пунктов | одна задача | одна строка |

    Возвращает число заведённых **задач** — то есть листьев, а не строк:
    спрашивают «сколько задач вписалось», и сюжет в этом счёте не участвует.
    """
    rows = parse_problems(text)
    return write_numbers(source, rows, user=user, section=section)


def write_numbers(source, numbers, *, user, section=None) -> int:
    """
    Записать разобранные номера в книгу — общий писатель на все три входа.

    Вставка отступом, таблица и книга Excel разбираются по-разному, но кладутся
    **одним кодом**: иначе три пути завели бы три немного разных книги, и
    расхождение всплыло бы через полгода на чужих данных.

    Раздел берётся из строки, если он там назван: таблица приходит с колонкой
    «Раздел», и заводить оглавление отдельным заходом было бы издевательством.
    """
    made = 0
    with transaction.atomic():
        start = source.entries.filter(parent__isnull=True).count()
        chapters = {}

        for offset, row in enumerate(numbers):
            place = section
            title = (row.get("section") or "").strip()
            if title:
                if title not in chapters:
                    chapters[title], _ = Section.objects.get_or_create(
                        source=source, title=title, parent=None
                    )
                place = chapters[title]

            stem = None
            if row["text"]:
                stem = _problem(
                    source, user, row["text"], answers=row.get("answers") or []
                )
                if not row["parts"]:
                    made += 1

            number = Entry.objects.create(
                source=source,
                section=place,
                problem=stem,
                label=row["label"],
                position=start + offset,
            )

            for spot, part in enumerate(row["parts"]):
                problem = _problem(
                    source,
                    user,
                    part["text"],
                    parent=stem,
                    position=spot,
                    answers=part.get("answers") or [],
                )
                Entry.objects.create(
                    source=source,
                    section=place,
                    problem=problem,
                    parent=number,
                    label=part["label"],
                    position=spot,
                )
                made += 1

    return made


def _problem(source, user, text, *, parent=None, position=0, answers=()):
    """
    Условие книги. Предмет книги достаётся ему сразу.

    Предмет — самый частый фильтр, и вешать его руками на каждую из четырёхсот
    вписанных задач никто не станет. А книга своим предметом уже названа, и
    другого у её задач не бывает: сборник по алгебре не содержит задач по
    географии.
    """
    made = Problem.objects.create(
        school=source.school,
        owner=source.owner,
        created_by=user,
        text=text,
        parent=parent,
        position=position,
        answers=list(answers),
    )
    if source.subject_id:
        made.links.create(tag_id=source.subject_id)
    return made


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

    parts = [
        {"id": part.pk, "text": part.text, "position": part.position}
        for part in problem.parts.order_by("position", "id")
    ]

    return {
        "id": problem.pk,
        # Сюжет, если это пункт: показывать пункт без него нельзя ни учителю,
        # ни ученику — он бессмыслен. И сами пункты, если это сюжет: «показать
        # целиком» отвечает из этого же ответа, без второго запроса.
        "stem": (
            {"id": problem.parent_id, "text": problem.parent.text}
            if problem.parent_id
            else None
        ),
        "parts": parts,
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
