"""
Страница бывает листом баллов.

Для работ длиннее пятнадцати задач учитель ставит баллы не в шапке бланка, а
на отдельном листе (`blank/mark_sheet.tex`), и раскладке надо знать, какой
лист перед ней: от этого зависит, откуда в пачке берутся баллы.

Умолчание — бланк ответов: всё, что прочитано до этой миграции, им и было.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0040_a_page_may_leave_the_pile"),
    ]

    operations = [
        migrations.AddField(
            model_name="scanpage",
            name="sheet",
            field=models.CharField(
                choices=[("answer", "answer sheet"), ("marks", "mark sheet")],
                default="answer",
                max_length=8,
                verbose_name="which sheet",
            ),
        ),
    ]
