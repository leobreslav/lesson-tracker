# Второй читатель шапки — отдельная трата: он продаётся по запросам, не по токенам.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vision', '0002_alter_aispend_purpose'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aispend',
            name='purpose',
            field=models.CharField(choices=[('scan_header', 'reading a scanned blank header'), ('scan_reread', 're-reading a header the two readers disagreed about'), ('scan_questions', 'copying the questions off the question paper'), ('scan_second', 'a second reader on the same header')], max_length=32, verbose_name='purpose'),
        ),
    ]
