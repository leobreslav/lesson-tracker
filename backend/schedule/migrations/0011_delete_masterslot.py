"""
Школьное расписание переезжает в расписание курсов и исчезает как таблица.

`MasterSlot` был тем же самым — курс, дата, номер, — и после того как
`LessonSlot` переехал на курс, у него не осталось ни одного своего поля:
школа выводится из курса, учитель из назначения, ключ совпадал буква в
букву. На dev-базе 268 из 334 строк лежали в обеих таблицах одновременно.

Правило переноса одно, и оно нужно из-за импорта: учитель забирал строки
себе копией и дальше правил её как хотел. Поэтому **у курса, где уроки уже
есть, побеждают уроки**, а школьные строки переезжают только туда, где
своих нет вовсе. Иначе перенесённый учителем урок получил бы рядом
воскресший оригинал, и отличить их было бы нечем.

Обратно не разъезжается: `reverse` не пишем, потому что после удаления
таблицы восстанавливать нечего — какая строка была школьной, а какая нет,
в базе больше не записано.
"""

from django.db import migrations


def carry_the_timetable_over(apps, schema_editor):
    MasterSlot = apps.get_model("schedule", "MasterSlot")
    LessonSlot = apps.get_model("schedule", "LessonSlot")

    taken = set(LessonSlot.objects.values_list("course_id", flat=True))
    rows = MasterSlot.objects.exclude(course_id__in=taken)

    LessonSlot.objects.bulk_create(
        LessonSlot(
            year_id=row.year_id,
            course_id=row.course_id,
            date=row.date,
            lesson_number=row.lesson_number,
        )
        for row in rows.iterator()
    )


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0010_remove_lessonslot_unique_slot_per_teacher_course_day_and_more"),
    ]

    operations = [
        migrations.RunPython(carry_the_timetable_over, migrations.RunPython.noop),
        migrations.DeleteModel(name="MasterSlot"),
    ]
