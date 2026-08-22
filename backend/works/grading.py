"""
Справочник систем оценивания школы.

Типовые системы заводятся кнопкой, а не появляются сами: угаданный набор из
пяти строк хуже пустого списка — школе с MYP пришлось бы удалять то, чего она
не просила. Тот же приём, что у параллелей: пустое состояние объясняет, что
это, и предлагает набор целиком.

Названия полос — **контент в базе**, поэтому пишутся на языке того, кто нажал:
«5» и «отлично» это разные школы, а не разные локали.
"""

from django.db import transaction

from .models import GradeBand, GradingSystem


def typical(language: str = "en") -> list[dict]:
    """
    Что предлагается школе на старте.

    Границы MYP взяты из опубликованных общих границ программы: сумма четырёх
    уровней 0–32 переводится в отметку 1–7. Они лежат **данными**, а не в коде,
    ровно потому, что IB их пересматривает.
    """
    russian = language == "ru"

    return [
        {
            "name": "5-балльная" if russian else "Five-point",
            "kind": GradingSystem.POINTS,
            "bands": [
                ("5", 85),
                ("4", 70),
                ("3", 50),
                ("2", 0),
            ],
        },
        {
            "name": "MYP 1–7",
            "kind": GradingSystem.LEVELS,
            "bands": [
                ("7", 28),
                ("6", 24),
                ("5", 19),
                ("4", 15),
                ("3", 10),
                ("2", 6),
                ("1", 1),
            ],
        },
        {
            "name": "Зачёт" if russian else "Pass or fail",
            "kind": GradingSystem.PASSFAIL,
            "bands": [
                ("зачёт" if russian else "pass", 50),
                ("незачёт" if russian else "fail", 0),
            ],
        },
    ]


def add_typical(school, language: str = "en") -> int:
    """
    Завести недостающие типовые системы. Нажать дважды не страшно.

    Существующие не трогаются вовсе: школа могла поправить пороги под себя, и
    «обновить до типовых» было бы худшим из возможных прочтений кнопки.
    """
    added = 0
    with transaction.atomic():
        taken = set(school.grading_systems.values_list("name", flat=True))
        for item in typical(language):
            if item["name"] in taken:
                continue

            system = GradingSystem.objects.create(
                school=school, name=item["name"], kind=item["kind"]
            )
            for position, (label, threshold) in enumerate(item["bands"]):
                GradeBand.objects.create(
                    system=system,
                    position=position,
                    label=label,
                    threshold=threshold,
                )
            added += 1

    return added


def set_bands(system, bands) -> None:
    """Полосы системы целиком: порядок — индекс в присланном списке."""
    with transaction.atomic():
        system.bands.all().delete()
        for position, item in enumerate(bands):
            GradeBand.objects.create(
                system=system,
                position=position,
                label=item["label"],
                threshold=item["threshold"],
            )


def payload(system) -> dict:
    return {
        "id": system.pk,
        "name": system.name,
        "kind": system.kind,
        "top_level": system.top_level,
        "is_allowed": system.is_allowed,
        "bands": [
            {"label": band.label, "threshold": band.threshold}
            for band in system.bands.all()
        ],
    }
