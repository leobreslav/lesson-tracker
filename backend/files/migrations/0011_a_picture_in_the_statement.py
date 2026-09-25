# A picture pasted into the statement of a question: the seventh owner.
#
# The statement lives in `bank.Problem` and nowhere else, so that is where its
# picture hangs — not off the work that asked it (the same statement is asked
# in other works and lies in the book), and not off the cell (a cell has no
# text of its own).

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

# The owners as this migration knows them. Spelled out here rather than
# imported from the model: a migration describes the table as it was, and
# the model's list will keep growing.
OWNERS = (
    "plan_row",
    "student_work",
    "work",
    "bookmark_owner",
    "school_shelf",
    "problem",
)


def owned_by(field):
    return Q(**{f"{name}__isnull": name != field for name in OWNERS})


class Migration(migrations.Migration):

    dependencies = [
        ("bank", "0012_proposals"),
        ("files", "0010_attachment_drops_the_template_row_owner"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="attachment",
            name="attachment_has_exactly_one_owner",
        ),
        migrations.AddField(
            model_name="attachment",
            name="problem",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="attachments",
                to="bank.problem",
                verbose_name="statement of a question",
            ),
        ),
        migrations.AddIndex(
            model_name="attachment",
            index=models.Index(
                fields=["problem", "position"], name="attachment_problem_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="attachment",
            constraint=models.CheckConstraint(
                condition=(
                    owned_by("plan_row")
                    | owned_by("student_work")
                    | owned_by("work")
                    | owned_by("bookmark_owner")
                    | owned_by("school_shelf")
                    | owned_by("problem")
                ),
                name="attachment_has_exactly_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="attachment",
            constraint=models.CheckConstraint(
                condition=Q(problem__isnull=True) | Q(inline=True),
                name="attachment_of_a_statement_stands_in_its_text",
            ),
        ),
    ]
