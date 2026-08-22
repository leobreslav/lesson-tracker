"""
Расписание переезжает с учителя на курс.

Уникальность становится `(course, date, lesson_number)` — той же, что у
школьного расписания. Значит перед удалением поля надо убедиться, что двух
слотов на один курс, день и номер в базе нет: они появлялись, только если
курс успел сменить ведущего и оба человека нарисовали себе один и тот же
час. Разрешать это молча нельзя — уцелел бы случайный из двух, и никто бы
не узнал, чей.

Проверка стоит **до** снятия ограничения, а не в обработчике ошибки: сказать
надо, в каком курсе и на какую дату разошлись, а не «нарушено ограничение».
"""

from django.db import migrations, models


def no_two_lessons_in_one_hour(apps, schema_editor):
    LessonSlot = apps.get_model("schedule", "LessonSlot")

    clashes = (
        LessonSlot.objects.values("course_id", "date", "lesson_number")
        .annotate(rows=models.Count("id"))
        .filter(rows__gt=1)
        .order_by("course_id", "date")
    )
    found = list(clashes[:20])
    if not found:
        return

    Course = apps.get_model("schedule", "Course")
    names = dict(Course.objects.values_list("id", "name"))
    listed = ", ".join(
        f"{names.get(row['course_id'], row['course_id'])} "
        f"{row['date']} №{row['lesson_number']} ({row['rows']})"
        for row in found
    )
    raise RuntimeError(
        "У курса не может быть двух уроков на один номер в один день, а в "
        f"базе они есть: {listed}. Такое бывает только если курс сменил "
        "ведущего и оба нарисовали себе этот час — решите вручную, чей урок "
        "остаётся, и удалите лишние."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0009_remove_courseassignment_unique_course_assignment_and_more"),
    ]

    operations = [
        migrations.RunPython(no_two_lessons_in_one_hour, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="lessonslot",
            name="unique_slot_per_teacher_course_day",
        ),
        migrations.RemoveIndex(
            model_name="lessonslot",
            name="slot_teacher_date_idx",
        ),
        migrations.RemoveField(model_name="lessonslot", name="teacher"),
        migrations.AddIndex(
            model_name="lessonslot",
            index=models.Index(fields=["year", "date"], name="slot_year_date_idx"),
        ),
        migrations.AddConstraint(
            model_name="lessonslot",
            constraint=models.UniqueConstraint(
                fields=("course", "date", "lesson_number"),
                name="unique_slot_per_course_day",
            ),
        ),
    ]
