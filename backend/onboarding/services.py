"""
The state of a first visit, and the demo data.

The app owns no models: it looks at the calendar, the courses, the schedule
and the plan and folds them into one picture — what is filled in and what is
not yet.

Since the move to schools the picture has two halves. The year and the
courses belong to the school, so a teacher sees the steps their administrator
has already taken; the schedule and the plan are their own.
"""

from __future__ import annotations

from datetime import date

from calendars.models import DayException, SchoolYear, Term
from calendars.services import KIND_VACATION
from django.db.models import Count, Q
from django.utils import timezone
from plans.models import PlanNode
from schedule.models import Course, CourseAssignment, Slot

# учебный год начинается в сентябре: до июня «текущим» считаем прошлый сентябрь
SCHOOL_YEAR_STARTS_IN = 6


def current_start_year(today: date | None = None) -> int:
    today = today or timezone.localdate()
    return today.year if today.month >= SCHOOL_YEAR_STARTS_IN else today.year - 1


VACATION_TITLES = {
    "en": ("Autumn break", "Winter break", "Spring break"),
    "ru": ("Осенние каникулы", "Зимние каникулы", "Весенние каникулы"),
}

TERM_NAMES = {
    "en": ("1st quarter", "2nd quarter", "3rd quarter", "4th quarter"),
    "ru": ("1 четверть", "2 четверть", "3 четверть", "4 четверть"),
}

YEAR_SUFFIX = {"en": "(example)", "ru": "(пример)"}


def typical_vacations(start_year: int, language: str = "en") -> list[dict]:
    """
    Default school breaks — the teacher moves the dates to fit their region.

    Demo content is data, not interface: it is written into the user's
    database once, so it is generated in their language and stays that way
    even if they later switch the interface.
    """
    titles = VACATION_TITLES.get(language, VACATION_TITLES["en"])
    return [
        {
            "title": titles[0],
            "start_date": date(start_year, 10, 26),
            "end_date": date(start_year, 11, 3),
        },
        {
            "title": titles[1],
            "start_date": date(start_year, 12, 28),
            "end_date": date(start_year + 1, 1, 8),
        },
        {
            "title": titles[2],
            "start_date": date(start_year + 1, 3, 23),
            "end_date": date(start_year + 1, 3, 31),
        },
    ]


def typical_terms(start_year: int, language: str = "en") -> list[dict]:
    """Four quarters, one between each pair of breaks."""
    names = TERM_NAMES.get(language, TERM_NAMES["en"])
    return [
        {
            "name": names[0],
            "start_date": date(start_year, 9, 1),
            "end_date": date(start_year, 10, 25),
        },
        {
            "name": names[1],
            "start_date": date(start_year, 11, 4),
            "end_date": date(start_year, 12, 27),
        },
        {
            "name": names[2],
            "start_date": date(start_year + 1, 1, 9),
            "end_date": date(start_year + 1, 3, 22),
        },
        {
            "name": names[3],
            "start_date": date(start_year + 1, 4, 1),
            "end_date": date(start_year + 1, 5, 31),
        },
    ]


# --- state -------------------------------------------------------------------


def current_year(user):
    """The school's freshest year — the one the main page talks about."""
    return (
        SchoolYear.objects.filter(school_id=user.school_id)
        .order_by("-start_date")
        .first()
    )


def course_summary(course, user, today: date) -> dict:
    """
    Один курс так, как он выглядит на главной.

    Слоты берутся по **курсу**, как и в раскладке: ведущий у курса один, но
    он мог смениться среди года, и «сколько дней у этого курса» — вопрос
    курса, а не человека. Считать по себе значило бы показать два разных
    баланса на двух экранах.
    """
    slots = Slot.objects.filter(course=course, is_cancelled=False)
    total = slots.count()
    past = slots.filter(date__lt=today).count()
    lessons = PlanNode.objects.filter(course=course, is_section=False).count()

    return {
        "id": course.pk,
        "name": course.name,
        "slots": total,
        "past": past,
        "remaining": total - past,
        "plan_lessons": lessons,
        # the same meaning as the balance in the layout: slots minus plan
        "balance": total - lessons,
    }


def empty_status() -> dict:
    """The answer for somebody no school has claimed yet."""
    return {
        "school": None,
        "is_school_admin": False,
        "year": {"exists": False, "id": None, "name": None, "start": None, "end": None},
        "calendar": {"terms": 0, "exceptions": 0},
        "classes": {"count": 0, "names": [], "items": []},
        "schedule": {"slots": 0},
        "plan": {"classes_with_plan": 0, "total_classes": 0},
    }


def build_status(user) -> dict:
    """One request: what is done already and what is not."""
    if user.school_id is None:
        return empty_status()

    today = timezone.localdate()
    year = current_year(user)

    courses = (
        # only what this teacher works in: the dashboard is about their year,
        # not the school's whole list
        Course.objects.for_teacher(user).filter(year=year).order_by("name")
        if year is not None
        else Course.objects.none()
    )
    courses = list(courses)

    items = [course_summary(course, user, today) for course in courses]
    with_plan = sum(1 for item in items if item["plan_lessons"] > 0)

    return {
        "school": {"id": user.school_id, "name": user.school.name},
        "is_school_admin": user.is_school_admin,
        "year": {
            "exists": year is not None,
            "id": year.pk if year else None,
            "name": year.name if year else None,
            "start": year.start_date if year else None,
            "end": year.end_date if year else None,
        },
        "calendar": {
            "terms": Term.objects.filter(year=year).count() if year else 0,
            "exceptions": (
                DayException.objects.filter(year=year).count() if year else 0
            ),
        },
        "classes": {
            "count": len(items),
            "names": [item["name"] for item in items],
            "items": items,
        },
        "schedule": {"slots": sum(item["slots"] for item in items)},
        "plan": {"classes_with_plan": with_plan, "total_classes": len(items)},
    }


# --- демо-данные -------------------------------------------------------------

# one weekly template per class: the classes sit on different weekdays, so
# their lesson numbers never collide (a teacher cannot run two lessons at once)
DEMO_CLASSES_EN = (
    {
        "name": "Grade 9B Algebra",
        # (weekday as in date.weekday(), lesson number)
        "week": ((0, 1), (2, 1), (4, 2)),
        # roughly a year's worth of plan: enough to see how the layout
        # spreads topics over dates and where the hours run out
        "plan": (
            (
                "Review of grade 8",
                (
                    "Numerical expressions",
                    "Linear equations",
                    "Systems of equations",
                    "Functions and graphs",
                    "Diagnostic test",
                ),
            ),
            (
                "Quadratic function",
                (
                    "What a quadratic function is",
                    "The parabola",
                    "Shifting the graph",
                    "Maximum and minimum values",
                    "Reading a graph",
                    "Problem solving",
                    "Practice quiz",
                    "Unit test",
                ),
            ),
            (
                "Equations and inequalities",
                (
                    "Quadratic equations",
                    "Vieta's theorem",
                    "Rational equations",
                    "The interval method",
                    "Quadratic inequalities",
                    "Systems of inequalities",
                    "Equations with a parameter",
                    "Unit test",
                ),
            ),
            (
                "Sequences",
                (
                    "What a sequence is",
                    "Arithmetic progressions",
                    "Sum of an arithmetic progression",
                    "Geometric progressions",
                    "Sum of a geometric progression",
                    "Infinite decreasing progressions",
                    "Practice",
                    "Unit test",
                ),
            ),
            (
                "Powers and roots",
                (
                    "Integer exponents",
                    "Arithmetic roots",
                    "Properties of roots",
                    "Simplifying expressions",
                    "Irrational equations",
                    "Practice",
                ),
            ),
            (
                "Elements of statistics",
                (
                    "Mean, mode and median",
                    "Tables and charts",
                    "Probability of an event",
                    "Problem solving",
                ),
            ),
            (
                "Final review",
                (
                    "Functions",
                    "Equations and inequalities",
                    "Progressions",
                    "Final test",
                    "Going through the final test",
                ),
            ),
        ),
    },
    {
        "name": "Grade 9B Geometry",
        "week": ((1, 1), (3, 2)),
        "plan": (),
    },
)

DEMO_CLASSES_RU = (
    {
        "name": "9Б Алгебра",
        # (день недели по date.weekday(), номер урока)
        "week": ((0, 1), (2, 1), (4, 2)),
        # план примерно на учебный год: на нём видно, как раскладка
        # раскидывает темы по датам и где кончаются часы
        "plan": (
            (
                "Повторение за 8 класс",
                (
                    "Числовые выражения",
                    "Линейные уравнения",
                    "Системы уравнений",
                    "Функции и графики",
                    "Входная контрольная работа",
                ),
            ),
            (
                "Квадратичная функция",
                (
                    "Определение квадратичной функции",
                    "График параболы",
                    "Сдвиги графика",
                    "Наибольшее и наименьшее значение",
                    "Чтение графика",
                    "Решение задач",
                    "Самостоятельная работа",
                    "Контрольная работа",
                ),
            ),
            (
                "Уравнения и неравенства",
                (
                    "Квадратные уравнения",
                    "Теорема Виета",
                    "Дробно-рациональные уравнения",
                    "Метод интервалов",
                    "Квадратные неравенства",
                    "Системы неравенств",
                    "Уравнения с параметром",
                    "Контрольная работа",
                ),
            ),
            (
                "Числовые последовательности",
                (
                    "Понятие последовательности",
                    "Арифметическая прогрессия",
                    "Сумма арифметической прогрессии",
                    "Геометрическая прогрессия",
                    "Сумма геометрической прогрессии",
                    "Бесконечно убывающая прогрессия",
                    "Практикум",
                    "Контрольная работа",
                ),
            ),
            (
                "Степени и корни",
                (
                    "Степень с целым показателем",
                    "Арифметический корень",
                    "Свойства корней",
                    "Преобразование выражений",
                    "Иррациональные уравнения",
                    "Практикум",
                ),
            ),
            (
                "Элементы статистики",
                (
                    "Среднее, мода, медиана",
                    "Таблицы и диаграммы",
                    "Вероятность события",
                    "Решение задач",
                ),
            ),
            (
                "Итоговое повторение",
                (
                    "Функции",
                    "Уравнения и неравенства",
                    "Прогрессии",
                    "Итоговая контрольная работа",
                    "Разбор итоговой работы",
                ),
            ),
        ),
    },
    {
        "name": "9Б Геометрия",
        "week": ((1, 1), (3, 2)),
        "plan": (),
    },
)

DEMO_CLASSES = {"en": DEMO_CLASSES_EN, "ru": DEMO_CLASSES_RU}


def demo_classes(language: str) -> tuple:
    return DEMO_CLASSES.get(language, DEMO_CLASSES_EN)


def create_demo(user) -> dict:
    """
    A full set of data that shows how everything hangs together.

    The year and the courses are the school's, so only an administrator can
    ask for it — the view checks the role. The schedule and the plan inside
    are created for the person who pressed the button.
    """
    start_year = current_start_year()
    language = getattr(user, "language", "en")
    classes = demo_classes(language)

    year = SchoolYear.objects.create(
        school=user.school,
        name=f"{start_year}/{start_year + 1} {YEAR_SUFFIX.get(language, YEAR_SUFFIX['en'])}",
        start_date=date(start_year, 9, 1),
        end_date=date(start_year + 1, 5, 31),
    )

    DayException.objects.bulk_create(
        DayException(year=year, kind=KIND_VACATION, **vacation)
        for vacation in typical_vacations(start_year, language)
    )
    Term.objects.bulk_create(
        Term(year=year, position=index, **term)
        for index, term in enumerate(typical_terms(start_year, language))
    )

    study_days = [day.date for day in year.build_days() if day.is_study]

    created_slots = 0
    for template in classes:
        course = Course.objects.create(
            school=user.school, year=year, name=template["name"]
        )
        # назначение обязательно: курс мой ровно потому, что мне его
        # поручили, — расписание и план принадлежат курсу и никого не
        # опознают
        CourseAssignment.objects.create(course=course, teacher=user)

        slots = [
            Slot(
                year=year,
                course=course,
                date=day,
                lesson_number=number,
            )
            for day in study_days
            for weekday, number in template["week"]
            if day.weekday() == weekday
        ]
        Slot.objects.bulk_create(slots)
        created_slots += len(slots)

        for position, (section_title, lessons) in enumerate(template["plan"]):
            section = PlanNode.objects.create(
                course=course,
                parent=None,
                position=position,
                is_section=True,
                title=section_title,
            )
            PlanNode.objects.bulk_create(
                PlanNode(
                    course=course,
                    parent=section,
                    position=index,
                    is_section=False,
                    title=title,
                )
                for index, title in enumerate(lessons)
            )

    return {
        "year": year.name,
        "classes": len(classes),
        "slots": created_slots,
    }
