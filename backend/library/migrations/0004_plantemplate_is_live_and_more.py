"""
Пометка «этот шаблон я веду» и ограничение, что он один.

Поле приезжает со значением `True` у всех: сегодня любой шаблон может
оказаться тем, который обновляют, и молча объявить чьи-то шаблоны снимками
нельзя. Но ограничение требует, чтобы живой был один, — поэтому между
добавлением поля и ограничением стоит правка данных, и порядок операций тут
не косметика: без неё ограничение упадёт на первом же человеке, у которого
по одному предмету лежат черновик и опубликованный.

Кого оставить живым, решаем **тем же правилом, каким это решалось до сих
пор**, — первым в порядке сортировки полки, то есть по названию. Правило
дурное (алфавит ничего не значит), но оно и работало, и менять поведение
молча хуже, чем сохранить его и дать человеку перевесить пометку руками.
Ровно этого выбора у него до сих пор и не было.
"""

from django.conf import settings
from django.db import migrations, models


def keep_one_live_per_group(apps, schema_editor):
    PlanTemplate = apps.get_model("library", "PlanTemplate")

    # тот же порядок, в котором полка приезжает клиенту, — по нему клиент и
    # брал «первый мой шаблон с тем же предметом и параллелью»
    templates = PlanTemplate.objects.order_by("subject__name", "grade", "title", "pk")

    seen = set()
    demoted = []
    for template in templates:
        # автора нет — вести шаблон некому, ограничение его не касается
        if template.author_id is None:
            continue

        key = (
            template.school_id,
            template.author_id,
            template.subject_id,
            template.grade,
        )
        if key in seen:
            template.is_live = False
            demoted.append(template)
        else:
            seen.add(key)

    PlanTemplate.objects.bulk_update(demoted, ["is_live"])


def all_live_again(apps, schema_editor):
    """Назад — снова все живые: до этой миграции разницы между ними не было."""
    apps.get_model("library", "PlanTemplate").objects.update(is_live=True)


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0003_alter_plantemplate_grade'),
        ('schedule', '0019_homegroup_homegroupstudent_and_more'),
        ('schools', '0010_alter_invitation_kind'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='plantemplate',
            name='is_live',
            field=models.BooleanField(default=True, verbose_name='kept up to date by its author'),
        ),
        # между полем и ограничением: иначе ограничение не встанет на живой базе
        migrations.RunPython(keep_one_live_per_group, all_live_again),
        migrations.AddConstraint(
            model_name='plantemplate',
            constraint=models.UniqueConstraint(condition=models.Q(('is_live', True)), fields=('school', 'author', 'subject', 'grade'), name='one_live_template_per_subject_and_grade'),
        ),
    ]
