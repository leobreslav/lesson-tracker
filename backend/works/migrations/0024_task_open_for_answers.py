"""
У ячейки появляется признак «принимает ответы онлайн».

Отвечал на это флаг работы (`on_paper`), и ответ был один на всю работу:
либо весь класс решает онлайн, либо весь класс пишет на бумаге. Смешанный
случай — «Q1 и Q2 решайте онлайн, Q3 сдайте на листе» — был недостижим не
потому, что его запретили, а потому, что выразить его было нечем.

Открыто по умолчанию: так ведёт себя обычная работа, и так же вела себя
любая работа до этой миграции. Задачи бумажных работ закрывает следующая.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("works", "0023_remove_submission_is_correct")]

    operations = [
        migrations.AddField(
            model_name="task",
            name="open_for_answers",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Ученик может прислать ответ на этот вопрос. Закрыт — "
                    "значит решают на бумаге: ячейка есть, поля ответа нет."
                ),
                verbose_name="accepts answers online",
            ),
        ),
    ]
