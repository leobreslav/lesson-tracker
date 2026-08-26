"""
Виды работ: типовой набор и то, как он показывается.

Справочник школы, устроенный как системы оценивания: правит администратор,
читают все. Здесь только два действия, которых не хватало вьюхе, — «показать»
и «добавить недостающие типовые».
"""

from django.db import transaction

from .models import WorkKind

# Типовые виды: имя, метка в шапке журнала, цвет и идёт ли в итог по
# умолчанию. Метки в один-два знака и разные между собой — в шапке их
# читают глазами, не наводя.
TYPICAL = {
    "ru": (
        ("Контрольная", "К", "blue", True),
        ("Проверочная", "П", "violet", False),
        ("Самостоятельная", "С", "slate", False),
        ("Проект", "Пр", "green", True),
        ("Лабораторная", "Л", "amber", False),
        ("Устный ответ", "У", "slate", False),
    ),
    "en": (
        ("Test", "T", "blue", True),
        ("Quiz", "Q", "violet", False),
        ("Classwork", "C", "slate", False),
        ("Project", "P", "green", True),
        ("Lab", "L", "amber", False),
        ("Oral answer", "O", "slate", False),
    ),
}


def typical(language: str = "en"):
    """Типовой набор на языке учителя: это контент школы, а не интерфейс."""
    return TYPICAL.get(language, TYPICAL["en"])


def payload(kind) -> dict:
    """Вид так, как его видит клиент — и справочник, и шапка журнала."""
    return {
        "id": kind.pk,
        "name": kind.name,
        "label": kind.label,
        "color": kind.color,
        "counts_to_term": kind.counts_to_term,
        "is_allowed": kind.is_allowed,
        "position": kind.position,
    }


def add_typical(school, language: str = "en") -> int:
    """
    Завести недостающие типовые виды. Нажать дважды не страшно.

    Существующие не трогаются вовсе — ни метка, ни цвет: школа могла
    переименовать «Проверочную» в «Летучку» и перекрасить, и «обновить до
    типовых» было бы худшим из возможных прочтений кнопки.
    """
    added = 0
    with transaction.atomic():
        taken = set(school.work_kinds.values_list("name", flat=True))
        start = school.work_kinds.count()

        for position, (name, label, color, counts) in enumerate(typical(language)):
            if name in taken:
                continue

            WorkKind.objects.create(
                school=school,
                name=name,
                label=label,
                color=color,
                counts_to_term=counts,
                position=start + position,
            )
            added += 1

    return added
