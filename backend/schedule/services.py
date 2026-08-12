"""
Раскладка расписания по датам. Чистые функции, без ORM.

Учебные дни здесь не вычисляются: их считает calendars.services, а сюда
приходит уже готовое множество дат.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping, Sequence

from calendars.services import iter_dates

MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def format_day(day: date) -> str:
    """«14 октября» — для сообщений пользователю."""
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"


def occupied_message(day: date, lesson_number: int, class_name: str) -> str:
    """Текст про занятый номер урока: учитель не ведёт два класса разом."""
    return f"{format_day(day)} {lesson_number}-й урок занят: {class_name}"


def cycle_days(start_date: date, end_date: date) -> int:
    """
    Длина цикла источника в днях, округлённая вверх до целых недель.

    Кратность семи — то, что заставляет понедельники попадать на
    понедельники: сдвиг на целое число недель дня недели не меняет.
    Двухнедельный источник даёт цикл в 14 дней, то есть чередование недель
    повторяется, а не схлопывается.
    """
    span = (end_date - start_date).days + 1
    weeks = -(-span // 7)  # деление с округлением вверх
    return weeks * 7


def source_date_for(target: date, source_start: date, cycle: int) -> date:
    """Какой день источника отвечает за целевую дату."""
    # остаток в Python неотрицателен, поэтому цель раньше источника тоже works
    return source_start + timedelta(days=(target - source_start).days % cycle)


def plan_copy(
    *,
    source_start: date,
    source_end: date,
    target_start: date,
    target_end: date,
    source_numbers: Mapping[date, Sequence[int]],
    study_dates: Iterable[date],
) -> tuple[list[tuple[date, int]], int]:
    """
    Что нужно создать в целевом периоде.

    `source_numbers` — номера уроков по датам источника, уже отфильтрованные
    по «обычности». Возвращает план (пары дата+номер) и число уроков,
    пропущенных из-за неучебных дней цели.
    """
    cycle = cycle_days(source_start, source_end)
    study = set(study_dates)
    plan: list[tuple[date, int]] = []
    skipped = 0

    for target in iter_dates(target_start, target_end):
        numbers = source_numbers.get(source_date_for(target, source_start, cycle), ())
        if not numbers:
            continue

        if target not in study:
            skipped += len(numbers)
            continue

        plan.extend((target, number) for number in numbers)

    return plan, skipped
