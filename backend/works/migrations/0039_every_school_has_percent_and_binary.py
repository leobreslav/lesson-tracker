"""
Бинарная и процентная системы оценивания — у каждой школы, без кнопки.

Виды появились миграцией раньше, а в школах не появились: системы заводит
кнопка «типовые» в справочниках, и учитель, открывший настройки работы,
видел пустой список, не зная, что его сперва надо наполнить в другом
разделе. Новые школы получают обе системы при создании
(`works/signals.py`); эта миграция делает то же для уже существующих.

Сверка идёт по виду: школа, успевшая завести свою процентную или бинарную,
вторую такую же не получает. Язык имён — язык первого администратора школы:
имена это контент в базе, а не интерфейс.

Правила здесь переписаны, а не позваны из `works.grading`: миграция живёт
дольше кода и обязана работать с той схемой, которая была на её шаге.
"""

from django.db import migrations

NAMES = {
    "passfail": {
        "en": ("Passed / not passed", [("passed", 50), ("not passed", 0)]),
        "ru": ("Сдал / не сдал", [("сдал", 50), ("не сдал", 0)]),
    },
    "percent": {
        "en": ("Percent", []),
        "ru": ("Проценты", []),
    },
}


def give(apps, schema_editor):
    School = apps.get_model("schools", "School")
    User = apps.get_model("accounts", "User")
    GradingSystem = apps.get_model("works", "GradingSystem")
    GradeBand = apps.get_model("works", "GradeBand")

    for school in School.objects.all():
        admin = (
            User.objects.filter(school=school, is_school_admin=True)
            .order_by("id")
            .first()
        )
        language = admin.language if admin and admin.language in ("en", "ru") else "en"

        systems = GradingSystem.objects.filter(school=school)
        kinds = set(systems.values_list("kind", flat=True))
        taken = set(systems.values_list("name", flat=True))

        for kind, by_language in NAMES.items():
            name, bands = by_language[language]
            if kind in kinds or name in taken:
                continue

            system = GradingSystem.objects.create(school=school, name=name, kind=kind)
            for position, (label, threshold) in enumerate(bands):
                GradeBand.objects.create(
                    system=system, position=position, label=label, threshold=threshold
                )


def noop(apps, schema_editor):
    """Откат ничего не удаляет: на заведённых системах уже могут стоять работы."""


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0038_the_gradebook_column_and_percent"),
        ("schools", "0012_family_invitation_grants_no_role"),
        ("accounts", "0007_login_code"),
    ]

    operations = [migrations.RunPython(give, noop)]
