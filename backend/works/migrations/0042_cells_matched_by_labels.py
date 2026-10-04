"""
Клетка бланка опознаётся по вписанной подписи — тестовым алгоритмом.

Прежний алгоритм (клетка по месту) не меняется и остаётся главным, поэтому
умолчания такие, что всё прочитанное до этой миграции им и прочитано:
`by_labels=False`, плиток нет.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0041_a_page_may_be_a_mark_sheet"),
    ]

    operations = [
        migrations.AddField(
            model_name="scanpage",
            name="by_labels",
            field=models.BooleanField(
                default=False, verbose_name="cells matched by their labels"
            ),
        ),
        migrations.AddField(
            model_name="scanpage",
            name="tiles",
            field=models.JSONField(
                blank=True, default=list, verbose_name="cells with their labels"
            ),
        ),
    ]
