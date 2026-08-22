"""
Работа привязывается к уроку, а не к строке плана.

Столбец тот же, но смотрит в другую таблицу, поэтому старые значения надо
обнулить: id строки плана в роли id урока — это чужая строка, а не «почти
та же». Терять нечего, привязкой ещё никто не пользовался (интерфейса у неё
не было), но делать это надо явно, а не полагаться на то, что там пусто.
"""

import django.db.models.deletion
from django.db import migrations, models


def forget_the_plan_row(apps, schema_editor):
    apps.get_model("works", "Work").objects.update(lesson_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0014_alter_lesson_options_lesson_covered_lesson_taught_by"),
        ("works", "0002_remove_work_work_owner_idx_remove_work_teacher_and_more"),
    ]

    # Эта правка написана до переименования `Lesson` в `Slot` и ссылается на
    # старое имя. Порядок между приложениями Django выбирает сам, и до сих пор
    # он случайно совпадал с нужным; первая же новая связь между приложениями
    # его переставила, и `to="schedule.lesson"` перестало разрешаться вовсе —
    # с ошибкой, в которой ни слова про имя. Порядок поэтому назван явно.
    run_before = [("schedule", "0015_rename_lesson_slot")]

    operations = [
        migrations.RunPython(forget_the_plan_row, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="work",
            name="lesson",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Урок, на котором работу задали. Не «когда сдавать» — на "
                    "это отвечает окно времени."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="works",
                to="schedule.lesson",
                verbose_name="lesson",
            ),
        ),
    ]
