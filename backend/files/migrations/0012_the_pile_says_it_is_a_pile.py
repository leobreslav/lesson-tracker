"""
Пачка сканов получает свой признак — и уже приложенные пачки его получают.

До этого пачкой считалось всё, что приложено к работе и скрыто от класса.
Признак «скрыто» отвечает на другой вопрос — кто читает, — и ответы к
контрольной, спрятанные от класса, показывались в таблице результатов пачкой.

Уже лежащие в базе пачки от прочих скрытых файлов по данным не отличить
наверняка, поэтому берётся лучшее из доступного: скрытый от класса PDF,
приложенный к работе файлом, а не в текст. Ошибиться тут можно в одну
сторону — спрятанные ответы в PDF переедут из материалов работы в таблицу
результатов, — и цена её невелика: файл остаётся у учителя, скрытым от
класса, и открывается так же. Обратной ошибки, когда пачка оказалась бы у
класса, быть не может: круг читателей миграция не трогает.
"""

from django.db import migrations, models


def mark_piles(apps, schema_editor):
    Attachment = apps.get_model("files", "Attachment")
    Attachment.objects.filter(
        work__isnull=False,
        staff_only=True,
        inline=False,
        kind="file",
        stored_file__content_type="application/pdf",
    ).update(is_batch=True)


def noop(apps, schema_editor):
    """Откат: поле уходит целиком, восстанавливать нечего."""


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0011_a_picture_in_the_statement"),
    ]

    operations = [
        migrations.AddField(
            model_name="attachment",
            name="is_batch",
            field=models.BooleanField(default=False, verbose_name="the scanned pile"),
        ),
        migrations.RunPython(mark_piles, noop),
    ]
