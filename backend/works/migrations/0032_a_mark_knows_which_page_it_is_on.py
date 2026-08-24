# Страница — часть адреса пометки: у снимка она одна, у PDF их сколько угодно.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('works', '0031_a_second_reader_on_the_same_strip'),
    ]

    operations = [
        migrations.AddField(
            model_name='photonote',
            name='page',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='page, from zero'),
        ),
        migrations.AddField(
            model_name='photostroke',
            name='page',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='page, from zero'),
        ),
    ]
