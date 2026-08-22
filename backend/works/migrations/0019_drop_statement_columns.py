"""
Старые колонки условия сносятся.

Отдельной миграцией, а не следом за переливкой: Postgres не даёт менять
таблицу в той же транзакции, где только что правились её строки, — «pending
trigger events». Разделение тут вынужденное и потому названо.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("works", "0018_cell_holds_a_statement")]

    operations = [
        migrations.RemoveField(model_name="task", name="question"),
        migrations.RemoveField(model_name="task", name="answers"),
        migrations.RemoveField(model_name="criterion", name="question"),
    ]
