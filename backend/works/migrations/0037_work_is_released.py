"""
Выдача работы классу отдельным полем — и уже заведённые работы выданы.

Умолчание у поля `False`, и для новых работ это верно: их заводят пустыми и
дописывают. А для тех, что уже лежат в базе, `False` означало бы, что они
разом пропали у учеников — включая идущие прямо сейчас и уже отвеченные.

Поэтому миграция не только добавляет поле, но и проставляет существующим
строкам `True`. Обратный ход тоже назван: снимая поле, ничего восстанавливать
не надо, но `RunPython` без обратной стороны запрещает откат всей миграции, а
запрещать его тут не за что.
"""

from django.db import migrations, models


def release_existing(apps, schema_editor):
    """Всё, что заведено до этой миграции, уже видно ученикам."""
    Work = apps.get_model("works", "Work")
    Work.objects.update(is_released=True)


def noop(apps, schema_editor):
    """Откат: поле уходит целиком, восстанавливать нечего."""


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0036_the_school_says_what_kinds_of_work_it_has"),
    ]

    operations = [
        migrations.AddField(
            model_name="work",
            name="is_released",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Выдана ли работа классу. Пока нет — ученику её не "
                    "существует независимо от окна времени: заводят работу "
                    "пустой и дописывают задачи, а окно к этому моменту уже "
                    "проставлено по умолчанию."
                ),
                verbose_name="released to students",
            ),
        ),
        migrations.RunPython(release_existing, noop),
    ]
