"""
Условие переезжает из ячейки в банк.

До этой правки текст задачи жил в трёх местах: `Task.question`,
`Criterion.question` и `bank.Problem.text`. Теперь он в одном, а ячейка держит
ссылку — и задача, набранная в работе на бегу, ничем не отличается от задачи из
общего каталога, кроме того, что не лежит ни в одной книге.

Что делает миграция с накопленным:

* у каждой ячейки с текстом или эталонами заводится **личное** условие: школа
  берётся у курса, владелец — у автора работы. В книгу оно не кладётся, то есть
  в библиотеке не появляется, а в поиске найдётся только у автора;
* ячейка без текста и без эталонов условия не получает: пустая ячейка — это
  законное состояние (`Q1…Qn` бумажной работы, где лист лежит у ученика на
  парте), и заводить под неё условие с пустым текстом значило бы засорить банк
  сотней немых строк;
* условие критерия выбрасывается: писал его когда-то разбор листа условий, а
  пишет он давно в ячейки, так что поле осталось пустым следом.

Обратный ход возвращает текст в ячейку — на случай отката; лишние условия при
этом остаются в банке, и это честнее, чем удалять то, что человек мог за это
время положить в книгу.
"""

from django.db import migrations, models
import django.db.models.deletion


def statements_into_the_bank(apps, schema_editor):
    Task = apps.get_model("works", "Task")
    Problem = apps.get_model("bank", "Problem")

    rows = Task.objects.select_related("work", "work__course").filter(problem__isnull=True)
    for task in rows.iterator():
        text = (task.question or "").strip()
        answers = [one for one in (task.answers or []) if one.strip()]
        if not text and not answers:
            continue

        task.problem = Problem.objects.create(
            school_id=task.work.course.school_id,
            owner_id=task.work.created_by_id,
            created_by_id=task.work.created_by_id,
            text=task.question or "",
            answers=answers,
        )
        task.save(update_fields=["problem"])


def statements_back_into_the_cell(apps, schema_editor):
    Task = apps.get_model("works", "Task")
    for task in Task.objects.select_related("problem").exclude(problem__isnull=True):
        task.question = task.problem.text
        task.answers = list(task.problem.answers)
        task.save(update_fields=["question", "answers"])


class Migration(migrations.Migration):

    dependencies = [
        ("bank", "0005_problem_answers"),
        ("works", "0017_task_problem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="problem",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="asked_in",
                to="bank.problem",
                verbose_name="statement",
            ),
        ),
        migrations.RunPython(statements_into_the_bank, statements_back_into_the_cell),
    ]
