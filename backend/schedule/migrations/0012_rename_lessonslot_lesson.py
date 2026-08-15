"""
`LessonSlot` становится `Lesson`.

Имя «слот» досталось модели, когда она была клеткой в сетке расписания.
С тех пор она стала уроком: у неё дата, номер, отмена с причиной, а дальше
на ней повиснут «что прошли», «кто вёл», посещаемость и работы. Слово
начало бы врать раньше, чем кто-нибудь его перечитал.

Только переименование: ни одного поля здесь не добавляется и не уходит.
`RenameModel` написан руками намеренно — автогенератор увидел бы удаление
одной модели и создание другой, то есть снёс бы 568 уроков боевой базы.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("schedule", "0011_delete_masterslot")]

    operations = [
        migrations.RenameModel(old_name="LessonSlot", new_name="Lesson"),
        migrations.RemoveConstraint(
            model_name="lesson", name="unique_slot_per_course_day"
        ),
        migrations.RemoveIndex(model_name="lesson", name="slot_year_date_idx"),
        migrations.RemoveIndex(model_name="lesson", name="slot_course_date_idx"),
        migrations.AddIndex(
            model_name="lesson",
            index=models.Index(fields=["year", "date"], name="lesson_year_date_idx"),
        ),
        migrations.AddIndex(
            model_name="lesson",
            index=models.Index(
                fields=["course", "date"], name="lesson_course_date_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="lesson",
            constraint=models.UniqueConstraint(
                fields=("course", "date", "lesson_number"),
                name="unique_lesson_per_course_day",
            ),
        ),
    ]
