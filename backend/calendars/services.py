"""
Расчёт учебного календаря.

Модуль намеренно ничего не знает про ORM и Django: на вход идут даты и
простые структуры :class:`Period`, на выходе — :class:`Day`. Ту же логику
дальше будет использовать расчёт слотов расписания, поэтому она вынесена
отдельно от моделей и сериализаторов.

Дни недели нумеруются как в :meth:`datetime.date.weekday`: понедельник — 0,
воскресенье — 6.

Приоритет разметки
------------------

У каждой даты ровно один статус, сколько бы исключений на неё ни наложилось.
Порядок разбора — от сильного к слабому:

1. ``workday`` → ``study``. Перенос ставят именно поверх нерабочего дня
   (отработка субботы, рабочий день внутри каникул), поэтому он сильнее всех
   остальных пометок. Не нужен — удаляется, а не перебивается другим видом.
2. ``weekend``. Выходной по расписанию недели учебным днём и так не был, так
   что праздник или каникулы на нём ничего не отнимают. Название исключения
   при этом сохраняется — пометка пользователя не теряется.
3. ``holiday``. Праздник — точечная разметка, он вырезает конкретный день из
   каникул, а не наоборот.
4. ``vacation``.
5. ``study`` — всё остальное внутри границ года.

Из этого порядка следует удобное свойство: день со статусом ``holiday`` или
``vacation`` — всегда день, который иначе был бы учебным. Значит потери
уроков считаются простым сложением этих двух счётчиков, без повторной
проверки на выходные.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Iterable, Iterator, Sequence

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)

WEEKDAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
WEEKDAY_CHOICES = tuple(enumerate(WEEKDAY_NAMES))

# в большинстве школ учатся пять дней, но кое-где суббота рабочая
DEFAULT_WEEKEND_DAYS = (SATURDAY, SUNDAY)

# виды исключений
KIND_HOLIDAY = "holiday"
KIND_VACATION = "vacation"
KIND_WORKDAY = "workday"

# статусы дня в развёрнутом календаре
STATUS_STUDY = "study"
STATUS_HOLIDAY = "holiday"
STATUS_VACATION = "vacation"
STATUS_WEEKEND = "weekend"

STATUSES = (STATUS_STUDY, STATUS_HOLIDAY, STATUS_VACATION, STATUS_WEEKEND)

# date outside every school year: not a status of the calendar, but the
# schedule spans weeks the year does not cover and has to say something
STATUS_OUTSIDE = "outside"

# fallback wording for API payloads; the UI localises by status code
STATUS_LABELS = {
    STATUS_STUDY: "study day",
    STATUS_HOLIDAY: "public holiday",
    STATUS_VACATION: "school break",
    STATUS_WEEKEND: "weekend",
}


@dataclass(frozen=True)
class Period:
    """Отрезок дат с видом исключения. Для одиночного дня границы совпадают."""

    start_date: date
    end_date: date
    kind: str
    title: str = ""
    id: int | None = None

    def contains(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date

    def overlaps(self, other: "Period") -> bool:
        return self.start_date <= other.end_date and other.start_date <= self.end_date


@dataclass(frozen=True)
class Day:
    """День развёрнутого календаря."""

    date: date
    status: str
    title: str = ""
    exception_id: int | None = None
    # терм, в который попал день; вне термов — None, это нормально
    term_id: int | None = None
    term_name: str = ""

    @property
    def weekday(self) -> int:
        return self.date.weekday()

    @property
    def is_study(self) -> bool:
        return self.status == STATUS_STUDY


def outside_day(day: date) -> Day:
    """A date no school year covers. Never a study day."""
    return Day(date=day, status=STATUS_OUTSIDE)


def day_payload(day: Day) -> dict:
    """
    One calendar day as **every** endpoint sends it.

    The computation was always shared (`SchoolYear.build_days`), but the
    serialisation was not: `/calendar/years/<id>/days/` sent the status and
    the agenda sent `is_study` next to it. The school timetable read
    `is_study` from the first one, got `undefined`, and marked every day of
    the year as not a study day. Two payloads for one thing is one payload
    too many.
    """
    return {
        "date": day.date,
        "weekday": day.weekday,
        "status": day.status,
        "is_study": day.is_study,
        "title": day.title,
        "exception": day.exception_id,
        "term_id": day.term_id,
        "term_name": day.term_name,
    }


MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def format_day(day: date) -> str:
    """«14 октября» — для сообщений пользователю."""
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"


def format_span(start_date: date, end_date: date) -> str:
    """«14 октября» либо «26 октября — 3 ноября»."""
    if start_date == end_date:
        return format_day(start_date)
    return f"{format_day(start_date)} — {format_day(end_date)}"


def spans_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    """Пересекаются ли два отрезка дат (границы включительно)."""
    return start_a <= end_b and start_b <= end_a


def find_term(day: date, terms: Iterable):
    """
    Терм, накрывающий дату, или None.

    Термы не обязаны покрывать год целиком: каникулы между четвертями
    в терм не входят, и это не ошибка.
    """
    return next(
        (term for term in terms if term.start_date <= day <= term.end_date), None
    )


def iter_dates(start_date: date, end_date: date) -> Iterator[date]:
    """Все даты отрезка, включая границы."""
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def resolve_day(
    day: date,
    weekend_days: Iterable[int],
    periods: Iterable[Period],
) -> Day:
    """
    Единственный статус дня с учётом всех накрывающих его исключений.

    Порядок разбора описан в шапке модуля: перенос → выходной → праздник →
    каникулы → учебный день.
    """
    covering = [period for period in periods if period.contains(day)]

    def first(kind: str) -> Period | None:
        return next((period for period in covering if period.kind == kind), None)

    workday = first(KIND_WORKDAY)
    if workday is not None:
        return Day(day, STATUS_STUDY, workday.title, workday.id)

    holiday = first(KIND_HOLIDAY)
    vacation = first(KIND_VACATION)

    if day.weekday() in set(weekend_days):
        # выходной сильнее праздника и каникул, но пометку не теряем:
        # название видно в подсказке, а исключение — в списке
        note = holiday or vacation
        if note is not None:
            return Day(day, STATUS_WEEKEND, note.title, note.id)
        return Day(day, STATUS_WEEKEND)

    if holiday is not None:
        return Day(day, STATUS_HOLIDAY, holiday.title, holiday.id)

    if vacation is not None:
        return Day(day, STATUS_VACATION, vacation.title, vacation.id)

    return Day(day, STATUS_STUDY)


def build_days(
    start_date: date,
    end_date: date,
    weekend_days: Iterable[int] = DEFAULT_WEEKEND_DAYS,
    periods: Iterable[Period] = (),
    terms: Iterable = (),
) -> list[Day]:
    """Развёрнутый календарь учебного года: по одной записи на каждую дату."""
    weekend = set(weekend_days)
    # исключения за границами года на календарь не влияют
    inside = [p for p in periods if p.end_date >= start_date and p.start_date <= end_date]
    terms = list(terms)

    days = []
    for day in iter_dates(start_date, end_date):
        resolved = resolve_day(day, weekend, inside)
        term = find_term(day, terms)
        days.append(
            replace(
                resolved,
                term_id=term.pk if term is not None else None,
                term_name=term.name if term is not None else "",
            )
            if term is not None
            else resolved
        )

    return days


def study_days(days: Iterable[Day]) -> list[Day]:
    return [day for day in days if day.is_study]


def count_by_weekday(days: Iterable[Day]) -> dict[int, int]:
    """Сколько учебных дней приходится на каждый день недели (0–6)."""
    counts = dict.fromkeys(range(7), 0)
    for day in study_days(days):
        counts[day.weekday] += 1
    return counts


def count_by_status(days: Iterable[Day]) -> dict[str, int]:
    """
    Сколько дней в каждом статусе.

    У дня ровно один статус, поэтому сумма счётчиков равна числу
    календарных дней в периоде — на этом инварианте держатся все отчёты.
    """
    counts = dict.fromkeys(STATUSES, 0)
    for day in days:
        counts[day.status] += 1
    return counts


def count_by_term(days: Iterable[Day]) -> list[dict]:
    """
    Учебные дни по термам, в порядке появления в календаре.

    Дни вне термов идут отдельной записью с `id: None` — их наличие
    нормально: между четвертями каникулы.
    """
    buckets: dict[int | None, dict] = {}

    for day in days:
        bucket = buckets.setdefault(
            day.term_id,
            {"id": day.term_id, "name": day.term_name, "study": 0, "calendar_days": 0},
        )
        bucket["calendar_days"] += 1
        if day.is_study:
            bucket["study"] += 1

    return list(buckets.values())


def build_stats(days: Sequence[Day]) -> dict:
    """Итоги: учебные дни всего, по дням недели, статусам и термам."""
    by_weekday = count_by_weekday(days)
    by_status = count_by_status(days)

    return {
        "calendar_days": len(days),
        "total": by_status[STATUS_STUDY],
        "by_status": by_status,
        "by_weekday": [
            {"weekday": weekday, "name": WEEKDAY_NAMES[weekday], "count": count}
            for weekday, count in sorted(by_weekday.items())
        ],
        "by_term": count_by_term(days),
    }


def is_within(period: Period, start_date: date, end_date: date) -> bool:
    """Целиком ли исключение попадает в границы года."""
    return start_date <= period.start_date and period.end_date <= end_date


def find_conflicts(period: Period, others: Iterable[Period]) -> list[Period]:
    """
    Исключения того же вида, пересекающиеся с `period`.

    Разные виды пересекаться могут — например, перенос рабочего дня внутри
    каникул, — а два одинаковых означают, что пользователь дважды разметил
    один и тот же день.
    """
    def is_same(other: Period) -> bool:
        # сравнение по id имеет смысл, только когда оба сохранены: у двух
        # новых исключений id одинаково пустой, но это разные отрезки
        return period.id is not None and other.id == period.id

    return [
        other
        for other in others
        if other.kind == period.kind and not is_same(other) and other.overlaps(period)
    ]
