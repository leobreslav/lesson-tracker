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


def plan_as_rows(owner) -> list[plan_services.ImportedRow]:
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

    for branch in plan_services.get_tree(owner):
        rows.append(line(branch.node))
        rows.extend(line(child) for child in branch.children)

    return rows


def template_as_rows(template) -> list[plan_services.ImportedRow]:
    """Template rows in the shape `apply_import` expects."""
    return [
        plan_services.ImportedRow(
            is_section=row.is_header,
            title=row.title,
            note=row.note,
            content=None if row.is_header else _content_of(row),
            attachments=() if row.is_header else file_services.attachments_of(row),
        )
        for row in template.rows.prefetch_related("attachments__stored_file")
    ]


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
def import_into_course(*, template, owner, append: bool) -> dict:
    """
    Copy a template into somebody's plan for a course.

    Straight through `apply_import`, the same call the CSV import makes, so
    numbering and the replace/append behaviour cannot drift between the two
    ways of filling a plan.

    The lesson content is copied; the files are **not**. What the new plan
    gets is its own `Attachment` rows pointing at the template's
    `StoredFile`s — one object in the bucket, however many colleagues take
    the plan. Removing it from one plan leaves every other one intact.
    """
    if not append:
        PlanNode.objects.filter(
            teacher_id=owner.teacher_id, course_id=owner.course_id
        ).delete()

    created = plan_services.apply_import(
        owner, template_as_rows(template), append=append
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
