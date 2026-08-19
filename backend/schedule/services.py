"""
Раскладка расписания по датам. Чистые функции, без ORM.

Учебные дни здесь не вычисляются: их считает calendars.services, а сюда
приходит уже готовое множество дат.

Здесь же — умолчание для имени параллели: это тоже чистая функция, и она
нужна и вьюхе, и фикстурам.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Collection, Iterable, Mapping, Sequence

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


def sweepable(lessons):
    """
    Уроки, которые массовая операция вправе снести: пустые клетки сетки.

    Урок перестаёт быть клеткой, как только на нём появилась запись —
    отменили с причиной, поставили внеплановый, отметили что прошли, назвали
    замену или задали работу. Это уже история, а историю оптом не чистят:
    «перекопировать неделю на год» иначе стёрло бы её всю разом, и
    восстановить было бы неоткуда.

    Фильтр, а не проверка в цикле: и `bulk`, и `replace` работают наборами.

    Что считается записью, перечислено **не здесь**, а в самой модели
    (`Slot.empty_conditions`), и оттуда же это спрашивает `has_record`.
    Пока список стоял в двух местах, он держался на том, что их правят
    вместе, — а следующая таблица на занятии просто не попала бы ни в один
    из них и была бы снесена первой же массовой чисткой.
    """
    return lessons.filter(
        is_extra=False,
        is_cancelled=False,
        **lessons.model.empty_conditions(),
    )


def free_number(*, teacher_id, year, day, start: int = 1):
    """
    Первый номер, на котором учитель в этот день ещё свободен.

    Нужен там, где занятие ставят **не по недельной сетке** — отработка,
    консультация, замена: у сетки номер задан заранее и проверен, а
    внеплановому его надо выбрать. Выбранный наугад однажды совпадёт с
    чужим уроком того же учителя, и получится расписание, в котором он
    ведёт два урока разом, — то, что приложение через интерфейс не
    допускает.

    `None`, если свободного номера в дне нет вовсе.
    """
    from .models import MAX_LESSON_NUMBER, Slot

    for number in range(start, MAX_LESSON_NUMBER + 1):
        busy = Slot.find_conflict(
            teacher_id=teacher_id, year=year, date=day, lesson_number=number
        )
        if busy is None:
            return number

    return None


def mark_attendance(slot, marks, *, by) -> None:
    """
    Записать журнал занятия. Одной транзакцией и без лишних строк.

    `status: null` не хранится значением, а **удаляет строку**: «не
    отмечено» — это отсутствие записи, и хранить его иначе значило бы
    заводить строку на каждого ученика каждого занятия года. Разница между
    «не отмечено» и «отсутствовал» при этом остаётся видимой, а она нужна:
    пустой журнал и журнал, где не было всего класса, — разные вещи.
    """
    from django.db import transaction

    from .models import Attendance

    with transaction.atomic():
        for row in marks:
            if row["status"] is None:
                Attendance.objects.filter(
                    slot=slot, student_id=row["student"]
                ).delete()
                continue

            Attendance.objects.update_or_create(
                slot=slot,
                student_id=row["student"],
                defaults={
                    "status": row["status"],
                    "note": row.get("note", ""),
                    "marked_by": by,
                },
            )


def occupied_message(day: date, lesson_number: int, class_name: str) -> str:
    """A teacher cannot run two classes at once — say which one is in the way."""
    return f"{day.isoformat()}, lesson {lesson_number} is taken by {class_name}"


def cycle_days(start_date: date, end_date: date, step: int = 1) -> int:
    """
    Длина цикла источника в днях, округлённая вверх до целых недель.

    Кратность семи — то, что заставляет понедельники попадать на
    понедельники: сдвиг на целое число недель дня недели не меняет.
    Двухнедельный источник даёт цикл в 14 дней, то есть чередование недель
    повторяется, а не схлопывается.

    `step` — «через сколько раз повторять»: 1 значит каждую неделю, 2 —
    через неделю. Растягивается именно цикл, а не источник: в пропущенную
    неделю целевые даты смотрят в пустой хвост цикла и не находят там
    ничего. Отдельной ветки «а тут не копируем» поэтому нет вовсе.
    """
    span = (end_date - start_date).days + 1
    weeks = -(-span // 7)  # деление с округлением вверх
    return weeks * 7 * step


def repeat_dates(
    start: date, until: date, step: int, study_dates: Collection[date]
) -> tuple[list[date], int]:
    """
    Один час, повторённый через `step` недель: даты для сетки.

    Сдвиг всегда кратен семи, поэтому день недели не меняется — то же
    правило, на котором держится копирование периода. «Через неделю» — это
    тот же шаг, только вдвое длиннее.

    **Первая дата берётся как есть, остальные — только учебные.** Разница
    не в аккуратности: по первой клетке человек щёлкнул сам, и урок в
    неучебный день бывает законным (отработка, суббота); а повторы он
    задал правилом, и правило не знает, что 3 января каникулы. Пропущенные
    возвращаются числом — молчаливая потеря дат хуже названной.
    """
    dates, skipped = [], 0
    day = start
    while day <= until:
        if day == start or day in study_dates:
            dates.append(day)
        else:
            skipped += 1
        day += timedelta(days=7 * step)

    return dates, skipped


def source_date_for(target: date, source_start: date, cycle: int) -> date:
    """Какой день источника отвечает за целевую дату."""
    # остаток в Python неотрицателен, поэтому цель раньше источника тоже works
    return source_start + timedelta(days=(target - source_start).days % cycle)


def covered_dates(
    *,
    source_start: date,
    source_end: date,
    target_start: date,
    target_end: date,
    step: int = 1,
) -> list[date]:
    """
    Целевые даты, которые копирование действительно накрывает.

    Нужно это `replace`: заменять надо там, куда кладут, а не во всём
    периоде. При шаге «через неделю» пропущенные недели копирование не
    трогает вовсе — и стирать в них тоже нечего, иначе выходило самое
    неприятное: уроки исчезли, а взамен ничего не появилось.

    То же правило чинит и старую странность с неполной неделей: источник
    «пн–пт», растянутый на месяц, выметал в цели и субботы с воскресеньями,
    хотя ничего в них не клал.
    """
    cycle = cycle_days(source_start, source_end, step)
    span = (source_end - source_start).days

    return [
        target
        for target in iter_dates(target_start, target_end)
        if (target - source_start).days % cycle <= span
    ]


def plan_copy(
    *,
    source_start: date,
    source_end: date,
    target_start: date,
    target_end: date,
    source_numbers: Mapping[date, Sequence[int]],
    study_dates: Iterable[date],
    step: int = 1,
) -> tuple[list[tuple[date, int]], int]:
    """
    Что нужно создать в целевом периоде.

    `source_numbers` — номера уроков по датам источника, уже отфильтрованные
    по «обычности». Возвращает план (пары дата+номер) и число уроков,
    пропущенных из-за неучебных дней цели.

    `step=2` — «через неделю»: цикл вдвое длиннее источника, и половина
    целевых дат попадает в его пустую половину.
    """
    cycle = cycle_days(source_start, source_end, step)
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


def suggested_topics(course) -> dict:
    """
    Что раскладка говорит про каждый урок курса: `{урок: строка плана}`.

    Считается по **всему** году: сопоставление позиционное, и обрезать его
    датами значило бы сдвинуть номера. Своего расчёта тут нет — та же
    `build_layout`, что и везде.
    """
    from plans import services as plan_services

    from .models import Slot

    lessons = plan_services.flatten_lessons(course.pk)
    slots = list(
        Slot.objects.filter(course=course, is_cancelled=False).order_by(
            "date", "lesson_number"
        )
    )

    return {
        entry.slot.pk: entry.lesson.node
        for entry in plan_services.build_layout(lessons, slots)
        if entry.slot is not None and entry.lesson is not None
    }

