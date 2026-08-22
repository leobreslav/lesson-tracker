"""
`Lesson` → `Slot`, `covered` → `lesson`, и связь становится `OneToOne`.

Второе переименование этой модели, и второе объясняется первым. `Lesson`
она называлась ровно один этап — пока казалось, что записью о произошедшем
должна быть сама клетка сетки. Оказалось иначе: урок — это строка плана,
получившая дату, а здесь живёт час, в который она попала.

Отсюда и поле: `slot.lesson` читается как «какой урок курса прошёл в этом
часе». `OneToOne`, потому что одна строка плана — ровно одно физическое
занятие; инвариант держит всю раскладку, и здесь он становится
ограничением базы, а не договорённостью.

**Написано руками.** Автогенератор предлагает удалить модель и создать
другую — на боевой базе это 568 занятий в мусор. `RenameModel` и
`RenameField` переименовывают таблицу и колонку, не трогая ни строки.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("plans", "0007_remove_planbaseline_baseline_owner_status_idx_and_more"),
        ("schedule", "0014_alter_lesson_options_lesson_covered_lesson_taught_by"),
    ]

    operations = [
        migrations.RenameModel(old_name="Lesson", new_name="Slot"),
        migrations.RenameField(
            model_name="slot", old_name="covered", new_name="lesson"
        ),
        migrations.AlterModelOptions(
            name="slot",
            options={
                "ordering": ("date", "lesson_number"),
                "verbose_name": "slot",
                "verbose_name_plural": "slots",
            },
        ),
        migrations.AlterField(
            model_name="slot",
            name="lesson",
            field=models.OneToOneField(
                blank=True,
                help_text="Строка плана, которую разобрали в этом часе.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="taught_at",
                to="plans.plannode",
                verbose_name="lesson taught",
            ),
        ),
        migrations.AlterField(
            model_name="slot",
            name="taught_by",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Заполняется только для замены: обычно урок ведёт "
                    "ведущий курса."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="slots_taught",
                to=settings.AUTH_USER_MODEL,
                verbose_name="taught by",
            ),
        ),
        migrations.AlterField(
            model_name="slot",
            name="course",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="slots",
                to="schedule.course",
                verbose_name="course",
            ),
        ),
        migrations.AlterField(
            model_name="slot",
            name="year",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="slots",
                to="calendars.schoolyear",
                verbose_name="school year",
            ),
        ),
        # имена индексов и уникальности задавались явно и остались с прежним
        # словом: в модели `Slot` они читались бы как след прошлой правки
        migrations.RemoveIndex(model_name="slot", name="lesson_year_date_idx"),
        migrations.RemoveIndex(model_name="slot", name="lesson_course_date_idx"),
        migrations.RemoveConstraint(
            model_name="slot", name="unique_lesson_per_course_day"
        ),
        migrations.AddIndex(
            model_name="slot",
            index=models.Index(
                fields=["year", "date"], name="slot_year_date_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="slot",
            index=models.Index(
                fields=["course", "date"], name="slot_course_date_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="slot",
            constraint=models.UniqueConstraint(
                fields=("course", "date", "lesson_number"),
                name="unique_slot_per_course_day",
            ),
        ),
    ]
