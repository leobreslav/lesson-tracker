"""
Семейная переписка снесена — после того, как переехала.

Порядок между приложениями Django выбирает сам, и здесь его нельзя оставлять
на его усмотрение: переезд (`talks.0002`) читает эту таблицу, а снос её
удаляет. Совпади порядок неудачно — и перенос упал бы с «App 'families'
doesn't have a 'FamilyThread' model», причём на чистой базе, то есть у всех
сразу. Поэтому зависимость названа, а не угадана: тот же приём, что у
`works.0003`, и та же причина.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('families', '0001_initial'),
        # снос идёт строго после переезда: он читает то, что мы удаляем
        ('talks', '0002_the_family_conversation_moves_in'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='familythread',
            name='child',
        ),
        migrations.RemoveField(
            model_name='familythread',
            name='parent',
        ),
        migrations.RemoveField(
            model_name='familythread',
            name='teacher',
        ),
        migrations.DeleteModel(
            name='FamilyMessage',
        ),
        migrations.DeleteModel(
            name='FamilyThread',
        ),
    ]
