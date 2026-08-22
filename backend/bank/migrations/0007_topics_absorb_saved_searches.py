"""
Тема поглощает сохранённый поиск: это была одна вещь в двух моделях.

Структурно они не различались ничем: названное условие с местом в дереве и
владением. Разница была в форме условия (у темы три поля, у поиска дерево) и в
том, что у темы не было владения, а у поиска — родителя. Оба недостатка чинятся
сложением, а не сосуществованием.

Что делает миграция:

* у темы появляется владение (все прежние — системные: других и не было) и
  выражение вместо «суть · запрещено · закрытость»;
* тройка полей переводится в **один лист** — «существует разбор, который
  пользуется тем-то, обходится тем-то и не выходит за пройденное». Именно
  одним листом, а не тремя условиями: требования эти к одному разбору, и
  порознь они находят задачу, у которой это разные разборы;
* сохранённые поиски переезжают темами верхнего уровня со своим владением.
"""

from django.db import migrations, models
import django.db.models.deletion


def predicates_into_expressions(apps, schema_editor):
    Topic = apps.get_model("bank", "Topic")

    for topic in Topic.objects.all():
        wanted = {}
        uses = list(topic.essence.values_list("pk", flat=True))
        avoids = list(topic.forbidden.values_list("pk", flat=True))
        if uses:
            wanted["uses"] = uses
        if avoids:
            wanted["avoids"] = avoids
        if topic.closed:
            wanted["covered"] = True

        topic.expression = {"solution": wanted} if wanted else {}
        topic.save(update_fields=["expression"])


def searches_into_topics(apps, schema_editor):
    Topic = apps.get_model("bank", "Topic")
    SavedSearch = apps.get_model("bank", "SavedSearch")

    for position, saved in enumerate(SavedSearch.objects.all()):
        Topic.objects.create(
            title=saved.name,
            expression=saved.expression,
            position=position,
            school_id=saved.school_id,
            owner_id=saved.owner_id,
            created_by_id=saved.created_by_id,
        )


def nothing_back(apps, schema_editor):
    """Обратно не переливаем: две модели из одной не восстановишь по имени."""


class Migration(migrations.Migration):

    dependencies = [("bank", "0006_owner_leaves_the_school")]

    operations = [
        migrations.AddField(
            model_name="topic",
            name="expression",
            field=models.JSONField(blank=True, default=dict, verbose_name="condition"),
        ),
        migrations.AddField(
            model_name="topic",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="schools.school",
                verbose_name="school; empty means the system catalogue",
            ),
        ),
        migrations.AddField(
            model_name="topic",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="accounts.user",
                verbose_name="owner; empty means the whole school",
            ),
        ),
        migrations.AddField(
            model_name="topic",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="accounts.user",
                verbose_name="who created it",
            ),
        ),
        migrations.AddField(
            model_name="topic",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AlterField(
            model_name="topic",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="children",
                to="bank.topic",
                verbose_name="parent topic",
            ),
        ),
        migrations.RunPython(predicates_into_expressions, nothing_back),
        migrations.RunPython(searches_into_topics, nothing_back),
    ]
