"""
Turning a plan into a template and back.

Обе стороны — план курса и план на полке — теперь одно и то же дерево, и
копия идёт через ту же плоскую последовательность `ImportedRow`, которой уже
говорят импорт и экспорт CSV. Конверсия в проекте одна, а не три: пишет её
`plans.services.apply_import`, то есть взять шаблон в курс — та же операция,
что импортировать файл, только строки приезжают из базы.

**Предел плоской формы снят, и снят записью.** Раньше строка шаблона не
умела сказать «этот урок вне темы»: у неё был только флаг «заголовок», и урок
верхнего уровня, стоящий после темы, при копировании уходил в эту тему.
Теперь у строки есть `at_top_level`, и она говорит это прямо — тем же полем,
которым это давно говорит CSV, где у каждого урока написана своя тема, а
пустая ячейка значит «вне темы».

Копия остаётся копией: после неё ни одна сторона на другую не ссылается.
Единственное исключение — **файлы**: они не копируются, а разделяются, и
новые ссылки смотрят на тот же объект в бакете.
"""

from django.db import transaction
from files import services as file_services
from plans import services as plan_services
from plans.content import CONTENT_FIELDS
from plans.models import PlanNode
from plans.owning import of_course, of_template


def _content_of(row) -> dict:
    return {field: getattr(row, field) for field in CONTENT_FIELDS}


def plan_as_rows(owner, only=None) -> list[plan_services.ImportedRow]:
    """
    План — плоской последовательностью «заголовок или урок», в порядке показа.

    Одна функция на обе стороны: `owner` — это либо курс, с которого снимают
    шаблон, либо шаблон, который берут в курс. Разными они были, пока разным
    было хранение; теперь единственное, чем они отличаются, — чьё дерево
    спросить.

    Содержание и вложения едут вместе со строками. Вложения отдаются как
    есть — своими `Attachment` автора: тот, кто пишет их дальше, заводит
    **новые ссылки на те же файлы**, а не загружает что-либо заново.

    `only` — идентификаторы строк, которые берут: блок, два блока или один
    урок. Курс собирают из чужих блоков и отдельных уроков, а не только
    целыми планами: «возьму отсюда тему про векторы, а оттуда два урока» —
    обычная просьба, и до сих пор ответом на неё было «возьмите план целиком
    и удалите лишнее».

    Выбор — это **фильтр**, а не новая раскладка: порядок остаётся исходным,
    и решать, что за чем идёт, человеку не приходится.

    Урок, чей заголовок не взяли, приезжает на верхний уровень — иначе он
    попал бы в предыдущий **взятый** блок, то есть «взял урок из темы А»
    молча значило бы «положи его в тему Б».
    """
    chosen = None if only is None else set(only)

    def line(node, *, at_top_level=False):
        return plan_services.ImportedRow(
            is_section=node.is_section,
            title=node.title,
            note=node.note,
            content=None if node.is_section else _content_of(node),
            attachments=() if node.is_section else file_services.attachments_of(node),
            at_top_level=at_top_level,
        )

    rows = []
    for branch in plan_services.get_tree(owner):
        node = branch.node

        if not node.is_section:
            # урок верхнего уровня говорит об этом прямо: без такой записи он
            # прилипал бы к предыдущей теме при первом же копировании
            if chosen is None or node.pk in chosen:
                rows.append(line(node, at_top_level=True))
            continue

        taken = chosen is None or node.pk in chosen
        if taken:
            rows.append(line(node))

        for child in branch.children:
            if chosen is not None and child.pk not in chosen:
                continue
            rows.append(line(child, at_top_level=not taken))

    return rows


@transaction.atomic
def write_rows(template, rows) -> int:
    """
    Переписать план шаблона этими строками. Позиции считает `apply_import`.

    Целиком, а не построчно: у списка нет другого источника порядка, кроме
    того, в каком он приехал, и запись целиком не оставит ни дыры, ни дубля.

    Старые узлы уходят первыми, и вместе с ними их ссылки на файлы, — но сами
    файлы переживают это, потому что новые ссылки заводятся на те же
    `StoredFile` внутри одной транзакции. Уборка сирот идёт после коммита и
    не находит работы.
    """
    rows = list(rows)
    PlanNode.objects.filter(template=template).delete()

    created = plan_services.apply_import(of_template(template), rows, append=False)

    for row, node in created["pairs"]:
        if row.attachments:
            file_services.copy_attachments(row.attachments, plan_row=node)
        # то же правило, что у строки плана курса: картинка живёт ровно
        # столько, сколько в тексте стоит ссылка на неё
        file_services.prune_inline(node)

    # touch updated_at so the list can show when the shelf last moved
    template.save(update_fields=["updated_at"])

    return created["headers"] + created["lessons"]


@transaction.atomic
def import_into_course(*, template, course_id: int, append: bool, rows=None) -> dict:
    """
    Скопировать шаблон в план курса.

    Прямо через `apply_import` — тот же вызов, что делает импорт CSV, — чтобы
    нумерация и поведение replace/append не разъезжались между тремя
    способами заполнить план.

    `rows` — взять не весь шаблон, а перечисленные строки: блок, два блока
    или один урок. Всё остальное при этом не меняется, включая режим:
    `append` дописывает выбранное в конец плана, `replace` строит план из
    него одного.

    Содержание копируется, а файлы — **нет**. Новый план получает свои
    `Attachment` на те же `StoredFile`: один объект в бакете, сколько бы
    коллег план ни взяло, и удаление из одного плана не трогает остальные.
    """
    if not append:
        PlanNode.objects.filter(course_id=course_id).delete()

    created = plan_services.apply_import(
        of_course(course_id), plan_as_rows(of_template(template), rows), append=append
    )

    files = 0
    for row, node in created["pairs"]:
        if row.attachments:
            files += file_services.copy_attachments(row.attachments, plan_row=node)

    return {
        "created_rows": created["headers"] + created["lessons"],
        "created_headers": created["headers"],
        "created_lessons": created["lessons"],
        "created_attachments": files,
    }
