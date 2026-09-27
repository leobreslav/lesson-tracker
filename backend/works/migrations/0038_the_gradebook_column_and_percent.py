"""
Место работы в журнале — её собственное решение; оценивание в процентах.

`in_journal` по умолчанию `True`, и для уже заведённых работ это то же
самое, что было: до появления поля в журнал попадала каждая. Проставлять
строкам ничего не надо — умолчание поля и есть прежнее поведение.

У системы оценивания прибавился вид `percent`. Значения прежних видов не
менялись, так что данных миграция не трогает.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0037_work_is_released"),
    ]

    operations = [
        migrations.AddField(
            model_name="work",
            name="in_journal",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Столбец работы в журнале курса. Место ему даёт занятие, к "
                    "которому работа привязана; без занятия он встаёт в конец."
                ),
                verbose_name="stands in the gradebook",
            ),
        ),
        migrations.AlterField(
            model_name="gradingsystem",
            name="kind",
            field=models.CharField(
                choices=[
                    ("points", "sum of question marks, bands in percent"),
                    ("levels", "levels per criterion, bands on the sum"),
                    ("passfail", "passed or not passed, the line in percent"),
                    ("percent", "percent of the maximum, no bands"),
                ],
                default="points",
                max_length=16,
                verbose_name="kind",
            ),
        ),
    ]
