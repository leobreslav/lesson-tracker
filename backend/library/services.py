"""
Turning a plan into a template and back.

Both directions go through the flat «header or lesson» sequence that the CSV
import and export already speak, so there is one conversion in the project
rather than three. `plans.services.apply_import` does the writing in both
cases: taking a template into a course is the same operation as importing a
CSV, with the rows coming from the database instead of a file.
"""

from django.db import transaction
from plans import services as plan_services
from plans.models import PlanNode

from .models import PlanTemplateRow


def plan_as_rows(owner) -> list[plan_services.ImportedRow]:
    """
    A teacher's plan flattened into header/lesson lines, in display order.

    A top-level lesson standing after a header cannot be expressed in this
    shape — it will read as part of that block when the template is used.
    The CSV export has always had the same limit; it is stated on the model.
    """
    rows = []

    for branch in plan_services.get_tree(owner):
        node = branch.node
        rows.append(
            plan_services.ImportedRow(
                is_section=node.is_section, title=node.title, note=node.note
            )
        )
        for child in branch.children:
            rows.append(
                plan_services.ImportedRow(
                    is_section=False, title=child.title, note=child.note
                )
            )

    return rows


def template_as_rows(template) -> list[plan_services.ImportedRow]:
    """Template rows in the shape `apply_import` expects."""
    return [
        plan_services.ImportedRow(
            is_section=row.is_header, title=row.title, note=row.note
        )
        for row in template.rows.all()
    ]


@transaction.atomic
def write_rows(template, rows) -> int:
    """
    Replace the template's lines with these. Positions are the index.

    Rewriting the lot rather than patching row by row: the list is short,
    ordering has no other source of truth, and a whole-list write cannot
    leave a gap or a duplicate position behind.
    """
    template.rows.all().delete()

    PlanTemplateRow.objects.bulk_create(
        PlanTemplateRow(
            template=template,
            position=position,
            is_header=row.is_section,
            title=row.title,
            note=row.note,
        )
        for position, row in enumerate(rows)
    )
    # touch updated_at so the list can show when the shelf last moved
    template.save(update_fields=["updated_at"])

    return template.rows.count()


@transaction.atomic
def import_into_course(*, template, owner, append: bool) -> dict:
    """
    Copy a template into somebody's plan for a course.

    Straight through `apply_import`, the same call the CSV import makes, so
    numbering and the replace/append behaviour cannot drift between the two
    ways of filling a plan.
    """
    if not append:
        PlanNode.objects.filter(
            teacher_id=owner.teacher_id, course_id=owner.course_id
        ).delete()

    created = plan_services.apply_import(
        owner, template_as_rows(template), append=append
    )

    return {
        "created_rows": created["headers"] + created["lessons"],
        "created_headers": created["headers"],
        "created_lessons": created["lessons"],
    }
