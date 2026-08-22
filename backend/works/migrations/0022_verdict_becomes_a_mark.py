"""
Вердикт переезжает с отправки в оценку за вопрос.

`Submission.is_correct` отвечал на «что он решил» булевым значением, а
`Mark(task=…)` — баллом. Это были два ответа на один вопрос, и разъезжались
они молча: бумажная работа писала баллы, онлайновая — галочки, и таблица
выбирала между ними по флагу `on_paper`.

Ось одна, и состояний у неё ровно четыре: не присылал, прислал и ноль,
прислал и часть максимума, прислал и максимум. Балл выражает все четыре, а
галочка — только крайние; частичный балл онлайн поставить было негде вовсе.

Перенос: `True` → максимум вопроса, `False` → ноль, `None` → строки нет,
потому что «не проверено» это отсутствие оценки, а не её значение.

Берётся **последняя проверенная** отправка по каждой паре «ученик и вопрос».
Если после неё пришла новая, непроверенная, балл остаётся за той, за
которую поставлен, — ссылка `Mark.submission` это и хранит, а ячейка
показывает, что пришло новое и надо посмотреть.

Уже стоящие баллы не трогаются: у бумажной работы они и есть вердикт, и
перезаписывать их галочкой было бы враньём.
"""

from django.db import migrations


def verdicts_to_marks(apps, schema_editor):
    Submission = apps.get_model("works", "Submission")
    StudentWork = apps.get_model("works", "StudentWork")
    Mark = apps.get_model("works", "Mark")

    # последняя проверенная отправка по каждой паре «вопрос и ученик»
    latest = {}
    checked = (
        Submission.objects.filter(is_correct__isnull=False)
        .select_related("task", "task__work")
        .order_by("created_at", "id")
    )
    for row in checked:
        latest[(row.task_id, row.student_id)] = row

    rows = {}
    for submission in latest.values():
        work_id = submission.task.work_id
        key = (work_id, submission.student_id)
        if key not in rows:
            rows[key], _ = StudentWork.objects.get_or_create(
                work_id=work_id, student_id=submission.student_id
            )

        student_work = rows[key]
        # балл за этот вопрос уже есть — значит его поставил человек за
        # бумагу или прошлым разбором пачки; галочка его не отменяет
        if Mark.objects.filter(
            student_work=student_work, task_id=submission.task_id
        ).exists():
            continue

        Mark.objects.create(
            student_work=student_work,
            task_id=submission.task_id,
            value=submission.task.maximum if submission.is_correct else 0,
            submission=submission,
        )


def marks_to_verdicts(apps, schema_editor):
    """
    Обратно: балл — верно, если он равен максимуму.

    Частичный балл при этом становится «неверно», и вернуть его нечем — на
    старой оси такого состояния не было вовсе. Обратная миграция здесь
    существует, чтобы откат не падал, а не чтобы ничего не потерять.
    """
    Mark = apps.get_model("works", "Mark")
    Submission = apps.get_model("works", "Submission")

    for mark in Mark.objects.filter(submission__isnull=False).select_related(
        "task", "submission"
    ):
        Submission.objects.filter(pk=mark.submission_id).update(
            is_correct=mark.value >= mark.task.maximum
        )


class Migration(migrations.Migration):
    dependencies = [("works", "0021_mark_submission")]

    operations = [migrations.RunPython(verdicts_to_marks, marks_to_verdicts)]
