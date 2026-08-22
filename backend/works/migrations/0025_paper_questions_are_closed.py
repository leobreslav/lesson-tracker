"""
Задачи бумажных работ закрываются для ответов, остальные остаются открытыми.

Это перенос флага работы в ячейку, один к одному: `on_paper=True` значило
«отвечать онлайн нельзя», и после миграции ровно это написано у каждой её
ячейки. Ни одна работа от переезда не меняет поведения — меняется только
место, где ответ хранится, и то, что теперь его можно дать поштучно.

Обратно — тем же соответствием: закрытая ячейка становится бумажной
работой. Точность тут неполная и другой быть не может: работа, у которой
часть вопросов закрыта, а часть открыта, на старой оси не выражается вовсе.
Такую считаем бумажной, если закрыты **все** её вопросы, — иначе смешанную
работу откат объявил бы бумажной целиком и отобрал бы у класса ответы,
которые он давал онлайн.
"""

from django.db import migrations


def close_paper_questions(apps, schema_editor):
    Task = apps.get_model("works", "Task")
    Task.objects.filter(work__on_paper=True).update(open_for_answers=False)


def paper_works_from_closed_questions(apps, schema_editor):
    Work = apps.get_model("works", "Work")
    Task = apps.get_model("works", "Task")

    open_somewhere = set(
        Task.objects.filter(open_for_answers=True).values_list("work_id", flat=True)
    )
    closed_somewhere = set(
        Task.objects.filter(open_for_answers=False).values_list("work_id", flat=True)
    )
    Work.objects.filter(pk__in=closed_somewhere - open_somewhere).update(on_paper=True)


class Migration(migrations.Migration):
    dependencies = [("works", "0024_task_open_for_answers")]

    operations = [
        migrations.RunPython(close_paper_questions, paper_works_from_closed_questions)
    ]
