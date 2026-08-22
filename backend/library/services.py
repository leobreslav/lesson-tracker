"""
Turning a plan into a template and back.

Both directions go through the flat «header or lesson» sequence that the CSV
import and export already speak, so there is one conversion in the project
rather than three. `plans.services.apply_import` does the writing in both
cases: taking a template into a course is the same operation as importing a
CSV, with the rows coming from the database instead of a file.
"""

from django.db import transaction
from files import services as file_services
from plans import services as plan_services
from plans.content import CONTENT_FIELDS
from plans.models import PlanNode

from .models import PlanTemplateRow


def _content_of(row) -> dict:
    return {field: getattr(row, field) for field in CONTENT_FIELDS}


def plan_as_rows(course_id: int) -> list[plan_services.ImportedRow]:
    """
    A teacher's plan flattened into header/lesson lines, in display order.

    A top-level lesson standing after a header cannot be expressed in this
    shape — it will read as part of that block when the template is used.
    The CSV export has always had the same limit; it is stated on the model.

    Content and attachments ride along. The attachments are the teacher's own
    `Attachment` rows, handed over as they are: `write_rows` points the
    template's copies at the same files rather than uploading anything.
    """
    rows = []

    def line(node):
        return plan_services.ImportedRow(
            is_section=node.is_section,
            title=node.title,
            note=node.note,
            content=None if node.is_section else _content_of(node),
            attachments=() if node.is_section else file_services.attachments_of(node),
        )

    for branch in plan_services.get_tree(course_id):
        rows.append(line(branch.node))
        rows.extend(line(child) for child in branch.children)

    return rows


def _as_imported(row, *, at_top_level: bool) -> plan_services.ImportedRow:
    return plan_services.ImportedRow(
        is_section=row.is_header,
        title=row.title,
        note=row.note,
        content=None if row.is_header else _content_of(row),
        attachments=() if row.is_header else file_services.attachments_of(row),
        at_top_level=at_top_level,
    )


def template_as_rows(template, only=None) -> list[plan_services.ImportedRow]:
    """
    Template rows in the shape `apply_import` expects.

    `only` — идентификаторы строк, которые берут. Курс собирают из чужих
    блоков и отдельных уроков, а не только целыми планами: «возьму отсюда
    тему про векторы, а оттуда два урока» — обычная просьба, и до сих пор
    ответом на неё было «возьмите план целиком и удалите лишнее».

    Выбор — это **фильтр**, а не новая раскладка: порядок остаётся
    шаблонным, и решать, что за чем идёт, человеку не приходится.

    Урок, чей заголовок не взяли, приезжает на верхний уровень. Иначе он
    попал бы в предыдущий **взятый** блок — `apply_import` кладёт урок в
    последний виденный заголовок, — то есть «взял урок из темы А» молча
    значило бы «положи его в тему Б».
    """
    rows = template.rows.prefetch_related("attachments__stored_file")

    if only is None:
        return [_as_imported(row, at_top_level=False) for row in rows]

    chosen = set(only)
    taken = []
    header = None

    for row in rows:
        if row.is_header:
            header = row
            if row.pk in chosen:
                taken.append(_as_imported(row, at_top_level=False))
            continue

        if row.pk in chosen:
            orphan = header is None or header.pk not in chosen
            taken.append(_as_imported(row, at_top_level=orphan))

    return taken


@transaction.atomic
def write_rows(template, rows) -> int:
    """
    Replace the template's lines with these. Positions are the index.

    Rewriting the lot rather than patching row by row: the list is short,
    ordering has no other source of truth, and a whole-list write cannot
    leave a gap or a duplicate position behind.

    The old rows go first, and with them their attachments — but the files
    behind those attachments survive, because the new rows are pointed at the
    same `StoredFile` inside this transaction. The orphan sweep runs on
    commit and finds nothing to do.
    """
    rows = list(rows)
    template.rows.all().delete()

    created = PlanTemplateRow.objects.bulk_create(
        PlanTemplateRow(
            template=template,
            position=position,
            is_header=row.is_section,
            title=row.title,
            note=row.note,
            **(row.content or {}),
        )
        for position, row in enumerate(rows)
    )

    for source, target in zip(rows, created):
        if source.attachments:
            file_services.copy_attachments(source.attachments, template_row=target)

    # touch updated_at so the list can show when the shelf last moved
    template.save(update_fields=["updated_at"])

    return len(created)


@transaction.atomic
def import_into_course(*, template, course_id: int, append: bool, rows=None) -> dict:
    """
    Copy a template into the plan of a course.

    Straight through `apply_import`, the same call the CSV import makes, so
    numbering and the replace/append behaviour cannot drift between the two
    ways of filling a plan.

    `rows` — взять не весь шаблон, а перечисленные строки: блок, два
    блока или один урок. Всё остальное при этом не меняется, включая режим:
    `append` дописывает выбранное в конец плана, `replace` строит план из
    него одного.

    The lesson content is copied; the files are **not**. What the new plan
    gets is its own `Attachment` rows pointing at the template's
    `StoredFile`s — one object in the bucket, however many colleagues take
    the plan. Removing it from one plan leaves every other one intact.
    """
    if not append:
        PlanNode.objects.filter(course_id=course_id).delete()

    created = plan_services.apply_import(
        course_id, template_as_rows(template, rows), append=append
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
