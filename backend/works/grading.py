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
            "name": "Сдал / не сдал" if russian else "Passed / not passed",
            "kind": GradingSystem.PASSFAIL,
            "bands": [
                ("сдал" if russian else "passed", 50),
                ("не сдал" if russian else "not passed", 0),
            ],
        },
        # Полос нет: отметкой служит сам процент набранного от максимума
        {
            "name": "Проценты" if russian else "Percent",
            "kind": GradingSystem.PERCENT,
            "bands": [],
        },
    ]


# Виды, которые есть у каждой школы сразу, без кнопки «типовые».
#
# Правило «новая школа не получает ничего» писалось про системы, в которых
# есть что угадывать: пятибалльная или семибалльная, какие пороги, MYP или
# нет. В этих двух угадывать нечего — процент от максимума один на весь мир,
# а «сдал / не сдал» — две полосы с порогом в половину. Пустой же список
# стоил того, что учитель, открыв настройки работы, не видел ни одной системы
# и не знал, что их надо сперва завести в другом разделе.
UNIVERSAL = (GradingSystem.PASSFAIL, GradingSystem.PERCENT)


def _create(school, item) -> None:
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


def add_universal(school, language: str = "en") -> int:
    """
    Завести школе бинарную и процентную системы, если таких видов у неё нет.

    Сверка идёт **по виду**, а не по имени: школа могла переименовать
    «Percent» в «Проценты», и вторая процентная система рядом с первой была
    бы выбором из двух одинаковых.

    Зовётся при создании школы (`works/signals.py`) и миграцией для уже
    существующих — то есть один раз на школу. Удалённая администратором
    система поэтому сама не возвращается: его рычаг сильнее нашего умолчания.
    """
    added = 0
    with transaction.atomic():
        kinds = set(school.grading_systems.values_list("kind", flat=True))
        names = set(school.grading_systems.values_list("name", flat=True))
        for item in typical(language):
            if item["kind"] not in UNIVERSAL or item["kind"] in kinds:
                continue
            if item["name"] in names:
                continue
            _create(school, item)
            added += 1

    return added


def add_typical(school, language: str = "en") -> int:
    """
    Завести недостающие типовые системы. Нажать дважды не страшно.

    Существующие не трогаются вовсе: школа могла поправить пороги под себя, и
    «обновить до типовых» было бы худшим из возможных прочтений кнопки.

    Универсальные виды сверяются по виду, остальные по имени: бинарная и
    процентная у школы уже есть с рождения, и названы они могли быть на
    другом языке — кнопка не должна заводить «Проценты» рядом с «Percent».
    """
    added = 0
    with transaction.atomic():
        taken = set(school.grading_systems.values_list("name", flat=True))
        kinds = set(school.grading_systems.values_list("kind", flat=True))
        for item in typical(language):
            if item["name"] in taken:
                continue
            if item["kind"] in UNIVERSAL and item["kind"] in kinds:
                continue

            _create(school, item)
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
