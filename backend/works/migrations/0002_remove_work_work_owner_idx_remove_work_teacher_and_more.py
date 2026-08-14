"""
Работа переезжает с учителя на курс.

Порядок операций важен: поле `created_by` появляется **до** удаления
`teacher`, чтобы успеть переписать в него автора. Иначе «кто составил»
пропало бы у всех работ разом, и восстановить это было бы неоткуда.

Сверять данные не с чем: уникальных ограничений у работы нет, и две работы
одного курса от разных учителей — законное состояние. После переезда они
просто становятся работами курса, чего мы и добиваемся.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def keep_the_author(apps, schema_editor):
    """Кто составил — история; владения она больше не означает."""
    Work = apps.get_model("works", "Work")
    Work.objects.update(created_by_id=models.F("teacher_id"))


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0007_remove_planbaseline_baseline_owner_status_idx_and_more"),
        ("schedule", "0009_remove_courseassignment_unique_course_assignment_and_more"),
        ("works", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveIndex(model_name="work", name="work_owner_idx"),
        migrations.AddField(
            model_name="work",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="works",
                to=settings.AUTH_USER_MODEL,
                verbose_name="created by",
            ),
        ),
        migrations.RunPython(keep_the_author, migrations.RunPython.noop),
        migrations.RemoveField(model_name="work", name="teacher"),
        migrations.AddIndex(
            model_name="work",
            index=models.Index(fields=["course", "id"], name="work_course_idx"),
        ),
    ]
