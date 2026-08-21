"""
`created_at` у темы становится обязательным.

Заводили его в прошлой миграции с `null=True`: у существовавших тем времени
создания не было вовсе, и придумывать его нечем. Теперь, когда у всех строк
время проставлено, поле приводится к общему виду `Owned`.
"""

from django.db import migrations, models
from django.utils import timezone


def stamp_the_old_ones(apps, schema_editor):
    Topic = apps.get_model("bank", "Topic")
    Topic.objects.filter(created_at__isnull=True).update(created_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [("bank", "0008_drop_saved_searches")]

    operations = [
        migrations.RunPython(stamp_the_old_ones, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="topic",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
