"""
`Work.lesson` → `Work.slot`: работу задают на **занятии**, а не на уроке.

Слово поехало вслед за моделью. «Урок» теперь означает строку плана, а час,
в который её провели, называется слотом — и поле указывает именно на час:
«на каком занятии задали». Не «когда сдавать» — на это по-прежнему отвечает
окно времени, и они законно разные.

Написано руками: автогенератор предлагает удалить поле и создать новое, то
есть потерять привязку у всех работ, которые её имеют.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0015_rename_lesson_slot"),
        ("works", "0006_work_description"),
    ]

    operations = [
        migrations.RenameField(
            model_name="work", old_name="lesson", new_name="slot"
        ),
        migrations.AlterField(
            model_name="work",
            name="slot",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Занятие, на котором работу задали. Не «когда сдавать» — "
                    "на это отвечает окно времени."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="works",
                to="schedule.slot",
                verbose_name="set at",
            ),
        ),
    ]
