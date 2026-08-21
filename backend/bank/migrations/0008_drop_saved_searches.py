"""
Прежние поля темы и модель сохранённого поиска сносятся.

Отдельной миграцией, а не следом за переливкой: Postgres не даёт менять
таблицу в той же транзакции, где только что правились её строки.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("bank", "0007_topics_absorb_saved_searches")]

    operations = [
        migrations.RemoveField(model_name="topic", name="essence"),
        migrations.RemoveField(model_name="topic", name="forbidden"),
        migrations.RemoveField(model_name="topic", name="closed"),
        migrations.RemoveField(model_name="savedsearch", name="school"),
        migrations.RemoveField(model_name="savedsearch", name="owner"),
        migrations.RemoveField(model_name="savedsearch", name="created_by"),
        migrations.DeleteModel(name="SavedSearch"),
        migrations.AlterModelOptions(
            name="topic",
            options={
                "ordering": ("position", "title", "id"),
                "verbose_name": "topic",
                "verbose_name_plural": "topics",
            },
        ),
    ]
