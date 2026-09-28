"""
Что школа получает с рождения.

Одно: бинарную и процентную системы оценивания (`grading.add_universal`).
Остальной справочник по-прежнему заводится кнопкой «типовые» — там есть что
угадывать, и угаданное хуже пустого.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from . import grading


@receiver(post_save, sender="schools.School")
def give_the_school_its_universal_systems(sender, instance, created, raw, **kwargs):
    # `raw` — загрузка фикстуры: там строки приезжают готовыми, и дописывать
    # к ним свои значило бы спорить с тем, что в фикстуре записано
    if not created or raw:
        return

    # Язык школы в момент создания неизвестен: администратора у неё ещё нет.
    # Английский — язык интерфейса по умолчанию; имена правятся в справочнике
    grading.add_universal(instance, "en")
