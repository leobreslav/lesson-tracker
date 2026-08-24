# Второе чтение той же полоски: что увидел Mathpix и в чём не сошёлся с моделью.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('works', '0030_work_description_is_the_assignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='scanpage',
            name='second',
            field=models.JSONField(blank=True, default=dict, verbose_name='what the second reader saw'),
        ),
    ]
