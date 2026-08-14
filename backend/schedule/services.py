"""
Раскладка расписания по датам. Чистые функции, без ORM.

Учебные дни здесь не вычисляются: их считает calendars.services, а сюда
приходит уже готовое множество дат.

Здесь же — умолчание для имени параллели: это тоже чистая функция, и она
нужна и вьюхе, и фикстурам.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping, Sequence

# форматирование дат общее для приложений и живёт в календаре
from calendars.services import format_day, iter_dates


# Имя параллели по умолчанию. Это **контент в базе**, а не интерфейс:
# записывается один раз и при смене языка не переписывается — то же правило,
# что у типовых каникул и четвертей в `onboarding.services`. Школа, нажавшая
# «Добавить 1–11» в русском интерфейсе, получала «Grade 1», хотя рядом те же
# кнопки заводят «1 четверть».
GRADE_NAMES = {"en": "Grade {level}", "ru": "{level} класс"}


def grade_name(level: int, language: str = "en") -> str:
    return GRADE_NAMES.get(language, GRADE_NAMES["en"]).format(level=level)


def place_copies(*, plan, skipped, occupied, busy, make) -> dict:
    """
    Turn a copy plan into objects, refusing the places already taken.

    The plan itself comes from `plan_copy`, which knows nothing about the
    database. This is the other half: it walks the plan once and decides what
    each slot meets.

    Two kinds of obstacle, told apart on purpose:

    * `occupied` — the same course already has that number that day. Nothing
      to report: repeating a copy should be quiet, not alarming.
    * `busy` — a **different** course holds the number, mapped to its name.
      Physically impossible for one teacher, so it is skipped *and* named,
      because the person needs to know what got in the way.

    `make(date, number)` builds the unsaved object; the caller keeps its own
    model. Both the personal schedule and the school-wide one go through
    here, so the accounting cannot drift between them.
    """
    created, conflicts = [], []
    taken = set(occupied)

    for day, number in plan:
        if (day, number) in taken:
            skipped += 1
            continue

        name = busy.get((day, number))
        if name is not None:
            skipped += 1
            conflicts.append(
                {
                    "date": day,
                    "lesson_number": number,
                    "class_name": name,
                    "message": occupied_message(day, number, name),
                }
            )
            continue

        taken.add((day, number))
        created.append(make(day, number))

    return {"created": created, "skipped": skipped, "conflicts": conflicts}


def occupied_message(day: date, lesson_number: int, class_name: str) -> str:
    """A teacher cannot run two classes at once — say which one is in the way."""
    return f"{day.isoformat()}, lesson {lesson_number} is taken by {class_name}"


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
