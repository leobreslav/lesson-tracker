"""
Страницу можно убрать из пачки.

Пустой оборот, титульный лист сканера, чужой листок в стопке — до сих пор у
такой страницы было два исхода, и оба неверные: остаться «ничьей» и держать
шаг разбора запертым либо считаться листом условий и резать пачку на работы.

Умолчание `False`: всё, что прочитано до этой миграции, в пачке остаётся.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0039_every_school_has_percent_and_binary"),
    ]

    operations = [
        migrations.AddField(
            model_name="scanpage",
            name="dropped",
            field=models.BooleanField(
                default=False, verbose_name="taken out of the pile"
            ),
        ),
    ]
