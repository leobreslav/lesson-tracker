"""
У условия становится **список** верных ответов вместо одной строки.

Форм у верного ответа несколько («x+3» и «3+x»), и список этот уже был — но
лежал он не у условия, а у задачи работы. Теперь он там, где ему место: что
считать верным ответом, от работы не зависит.

Порядок операций тут не косметика: сначала завести новое поле, потом перелить,
и только потом снести старое. Сгенерированная миграция делала наоборот и
уносила ответы вместе с колонкой.
"""

import django.contrib.postgres.fields
from django.db import migrations, models


def keep_the_answer(apps, schema_editor):
    Problem = apps.get_model("bank", "Problem")
    for problem in Problem.objects.exclude(answer=""):
        problem.answers = [problem.answer]
        problem.save(update_fields=["answers"])


def back_to_one(apps, schema_editor):
    """Обратно берётся первый: больше одной строки старое поле не вмещает."""
    Problem = apps.get_model("bank", "Problem")
    for problem in Problem.objects.exclude(answers=[]):
        problem.answer = problem.answers[0][:200]
        problem.save(update_fields=["answer"])


class Migration(migrations.Migration):

    dependencies = [
        ("bank", "0004_topic_introduction"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="answers",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(),
                blank=True,
                default=list,
                help_text="Хранятся ровно как введены: обработка — при сравнении.",
                size=None,
                verbose_name="accepted answers",
            ),
        ),
        migrations.RunPython(keep_the_answer, back_to_one),
        migrations.RemoveField(model_name="problem", name="answer"),
    ]
