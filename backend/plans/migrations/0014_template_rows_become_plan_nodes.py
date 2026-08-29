"""
Плоские строки шаблона переезжают в узлы плана.

Форм хранения у одного и того же — программы курса — было две: дерево у
курса и плоский список у полки. Вторая существовала ради того, чтобы не
копировать самый хитрый код проекта (`place`/`reindex`/`move`), и ценой
этого был предел, записанный на самой модели: урок верхнего уровня **после**
заголовка неотличим от урока внутри него.

Здесь дерево становится общим, и предел исчезает вместе со второй формой.
Разложить плоское в дерево можно ровно одним способом — тем же, каким это
делает импорт CSV: урок ложится в последний виденный заголовок, а до первого
заголовка остаётся наверху. Другого прочтения у этих данных нет и не было.

Вложения переезжают вместе со строками, и **в том же действии**: у ссылки
владелец ровно один, и состояние «названы оба» база не пустит. Порядок
поэтому обратный привычному — сначала узлы, потом переброс ссылок, и только
после этого (отдельными миграциями своих приложений) исчезают старая таблица
и старое поле.

Обратного хода нет намеренно. Он был бы не «вернуть как было», а «сложить
дерево обратно в плоский список», то есть снова потерять уровень у уроков,
стоящих после темы, — уже у тех, кого набрали деревом. Терять чужую работу
молча миграция не вправе.
"""

from django.db import migrations


def rows_into_nodes(apps, schema_editor):
    PlanTemplateRow = apps.get_model("library", "PlanTemplateRow")
    PlanNode = apps.get_model("plans", "PlanNode")
    Attachment = apps.get_model("files", "Attachment")

    content_fields = ("objectives", "body", "formative", "homework")
    moved = {}

    for template_id in (
        PlanTemplateRow.objects.values_list("template_id", flat=True)
        .distinct()
        .order_by("template_id")
    ):
        section = None
        top_position = 0
        inner_position = 0

        for row in PlanTemplateRow.objects.filter(template_id=template_id).order_by(
            "position", "id"
        ):
            if row.is_header:
                section = PlanNode.objects.create(
                    template_id=template_id,
                    parent=None,
                    position=top_position,
                    is_section=True,
                    title=row.title,
                    note=row.note,
                )
                top_position += 1
                inner_position = 0
                moved[row.pk] = section.pk
                continue

            node = PlanNode.objects.create(
                template_id=template_id,
                parent=section,
                position=inner_position if section else top_position,
                is_section=False,
                title=row.title,
                note=row.note,
                **{field: getattr(row, field) for field in content_fields},
            )
            if section:
                inner_position += 1
            else:
                top_position += 1
            moved[row.pk] = node.pk

    # Оба поля одним запросом: «владелец ровно один» — ограничение базы, и
    # промежуточное состояние с двумя владельцами она просто не примет.
    for attachment in Attachment.objects.filter(template_row__isnull=False):
        node_id = moved.get(attachment.template_row_id)
        if node_id is None:
            # строка заголовка: содержания и материалов у темы не бывает, но
            # ссылка, заведённая мимо интерфейса, всё же могла бы висеть
            continue
        Attachment.objects.filter(pk=attachment.pk).update(
            plan_row_id=node_id, template_row=None
        )


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0013_snapshot_owner"),
        ("library", "0004_plantemplate_is_live_and_more"),
        ("files", "0009_the_school_shelf"),
    ]

    operations = [
        migrations.RunPython(rows_into_nodes, migrations.RunPython.noop),
    ]
