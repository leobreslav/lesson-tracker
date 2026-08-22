"""
Два дерева: у задачи — про смысл, у книги — про адрес.

У задачи появляется сюжет: «Дан треугольник ABC» и вопросы к нему. Это
свойство самого условия, одинаковое во всех книгах, — поэтому ни номеров, ни
букв тут нет.

У книги появляется вложенность строк: номер и его пункты. Метки и порядок
принадлежат книге, и потому один и тот же пункт бывает «3а» у Мордковича и
«5б» у Галицкого. Ровно поэтому букву нельзя держать на задаче — она вместила
бы только одну.

Строка книги при этом может ни на что не показывать: «15. а) x²=4 б) x²=9» —
номер, у которого есть только пункты, а над буквами не напечатано ничего.

Существующие книги от этого не меняются: у всех строк родителя нет, у всех
задач сюжета нет, и каждая из них остаётся листом — то есть задачей.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bank', '0009_topic_created_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='bank.entry', verbose_name='the numbered row this one is a part of'),
        ),
        migrations.AddField(
            model_name='problem',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='parts', to='bank.problem', verbose_name='the stem this is a question to'),
        ),
        migrations.AddField(
            model_name='problem',
            name='position',
            field=models.PositiveIntegerField(default=0, verbose_name='position among the parts'),
        ),
        migrations.AlterField(
            model_name='entry',
            name='problem',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='bank.problem', verbose_name='what stands here; empty means a bare number'),
        ),
    ]
