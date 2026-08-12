"""
A believable school to look at while developing.

Not to be confused with `bootstrap`, which runs on the live database and only
adds what is missing. This one is the opposite kind of tool: it invents data,
it may delete data, and it refuses to run unless DEBUG is on. The two never
share code — a helper used by both would eventually be changed for the sake
of one of them.

What it builds is chosen so the interface can be judged by eye: a course with
a full plan next to one with a gap and one with nothing, a course with no
schedule at all, cancelled and extra lessons among the regular ones. A tidy
uniform dataset hides exactly the states that break layouts.
"""

from datetime import date, timedelta

from allauth.account.models import EmailAddress
from calendars.models import DayException, SchoolYear, Term
from calendars.services import KIND_HOLIDAY, KIND_VACATION
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from onboarding.services import typical_terms, typical_vacations
from plans.models import PlanNode
from schedule.models import LessonSlot, MasterSlot
from schools.models import Invitation, School

User = get_user_model()

SCHOOL_NAME = "Тестовая школа"
START_YEAR = 2026
YEAR_NAME = "2026/2027"
YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)
LANGUAGE = "ru"

# public holidays on top of the three breaks: single days, the kind that
# punch a hole in the middle of a quarter
HOLIDAYS = (
    (date(2026, 11, 4), "День народного единства"),
    (date(2027, 2, 23), "День защитника Отечества"),
    (date(2027, 3, 9), "Перенос с 8 марта"),
    (date(2027, 5, 3), "Праздник весны и труда"),
)

PEOPLE = (
    # (email, first name, last name, administrator)
    ("director@example.com", "Ольга", "Дирекова", True),
    ("ivanova@example.com", "Мария", "Иванова", False),
    ("petrov@example.com", "Пётр", "Петров", False),
)

# (course name, teacher email, weekly slots as (weekday, lesson number))
# weekday numbers are ours: Monday is 0, as in date.weekday()
# the course handed to the developer's own account: it has timetable rows and
# no personal schedule, so importing it visibly does something
IMPORTABLE_COURSE = "Grade 9 Geometry"

COURSES = (
    ("Grade 6 Algebra", "ivanova@example.com", ((0, 1), (2, 1), (4, 2))),
    ("Grade 6 Geometry", "ivanova@example.com", ((1, 2), (3, 1))),
    ("Grade 9 Algebra", "petrov@example.com", ((0, 3), (2, 3), (4, 4))),
    # deliberately without a timetable: the empty states need a subject
    ("Grade 9 Geometry", "petrov@example.com", ()),
)

# a plan of ~40 lessons in blocks — the one that fills a year
FULL_PLAN = (
    (
        "Повторение за 5 класс",
        (
            "Натуральные числа",
            "Обыкновенные дроби",
            "Десятичные дроби",
            "Проценты",
            "Входная контрольная работа",
        ),
    ),
    (
        "Делимость чисел",
        (
            "Делители и кратные",
            "Признаки делимости на 2, 5 и 10",
            "Признаки делимости на 3 и 9",
            "Простые и составные числа",
            "Разложение на простые множители",
            "Наибольший общий делитель",
            "Наименьшее общее кратное",
            "Контрольная работа",
        ),
    ),
    (
        "Действия с дробями",
        (
            "Основное свойство дроби",
            "Сокращение дробей",
            "Приведение к общему знаменателю",
            "Сложение и вычитание",
            "Умножение дробей",
            "Взаимно обратные числа",
            "Деление дробей",
            "Дробные выражения",
            "Контрольная работа",
        ),
    ),
    (
        "Отношения и пропорции",
        (
            "Отношения",
            "Пропорции",
            "Прямая пропорциональность",
            "Обратная пропорциональность",
            "Масштаб",
            "Длина окружности",
            "Площадь круга",
            "Контрольная работа",
        ),
    ),
    (
        "Положительные и отрицательные числа",
        (
            "Координатная прямая",
            "Противоположные числа",
            "Модуль числа",
            "Сравнение чисел",
            "Изменение величин",
        ),
    ),
    (
        "Итоговое повторение",
        (
            "Делимость",
            "Дроби",
            "Пропорции",
            "Итоговая контрольная работа",
            "Разбор итоговой работы",
        ),
    ),
)

# a plan that runs out halfway: the layout has to show the shortfall
PARTIAL_PLAN = (
    (
        "Начальные геометрические сведения",
        ("Точки и прямые", "Отрезок и луч", "Углы", "Смежные углы", "Вертикальные углы"),
    ),
    ("Треугольники", ("Первый признак равенства", "Второй признак", "Третий признак")),
)

# a handful of lessons marked by hand, so the schedule is not uniform
CANCELLED = (("Grade 6 Algebra", 12, "Болезнь"), ("Grade 6 Algebra", 30, "Карантин"),
             ("Grade 9 Algebra", 18, "Актированный день"))
EXTRA = (("Grade 6 Geometry", "Консультация"), ("Grade 9 Algebra", "Замена коллеги"))


class Command(BaseCommand):
    help = "Заполнить базу правдоподобными данными для разработки"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="снести все данные перед созданием",
        )
        parser.add_argument(
            "--email",
            default="",
            help="привязать существующего пользователя к школе администратором",
        )
        parser.add_argument(
            "--minimal",
            action="store_true",
            help="только школа, год и курсы — без расписания и планов",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo работает только при DEBUG=True. Это выдуманные "
                "данные: на боевой базе им не место. Для живой базы есть "
                "bootstrap."
            )

        with transaction.atomic():
            if options["flush"]:
                self.flush()

            school = self.school()
            people = self.people(school)
            year = self.year(school)
            self.markup(year)
            courses = self.courses(school, year)

            self.timetable(year, courses, people)

            if not options["minimal"]:
                self.schedule(year, courses, people)
                self.plans(courses, people)

            attached = self.attach(school, options["email"])

        self.summary(school, people, courses, options, attached)

    # --- building blocks ------------------------------------------------------

    def flush(self):
        """
        Everything, in dependency order.

        Slots and plan rows hold their course under PROTECT, so they go
        first; users hold their school the same way and are cleared before
        the schools themselves. Superusers survive: wiping the account you
        administer the box with is never what you meant.
        """
        PlanNode.objects.all().delete()
        LessonSlot.objects.all().delete()
        MasterSlot.objects.all().delete()
        SchoolYear.objects.all().delete()  # carries courses, terms, markup
        Invitation.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        User.objects.filter(is_superuser=True).update(school=None, is_school_admin=False)
        School.objects.all().delete()
        self.stdout.write(self.style.WARNING("  очищено: всё, кроме суперпользователей"))

    def school(self):
        school, _ = School.objects.get_or_create(name=SCHOOL_NAME)
        return school

    def people(self, school):
        """The staff. Existing accounts keep their names and passwords."""
        people = {}

        for email, first, last, admin in PEOPLE:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "school": school,
                    "is_school_admin": admin,
                    "language": LANGUAGE,
                },
            )
            if not created and user.school_id != school.pk:
                user.school = school
                user.is_school_admin = admin
                user.save(update_fields=["school", "is_school_admin"])

            EmailAddress.objects.get_or_create(
                user=user,
                email=user.email,
                defaults={"verified": True, "primary": True},
            )
            people[email] = user

        return people

    def year(self, school):
        year, _ = SchoolYear.objects.get_or_create(
            school=school,
            name=YEAR_NAME,
            defaults={"start_date": YEAR_START, "end_date": YEAR_END},
        )
        return year

    def markup(self, year):
        """Breaks, public holidays and the four quarters between them."""
        for vacation in typical_vacations(START_YEAR, LANGUAGE):
            DayException.objects.get_or_create(
                year=year,
                start_date=vacation["start_date"],
                end_date=vacation["end_date"],
                kind=KIND_VACATION,
                defaults={"title": vacation["title"]},
            )

        for day, title in HOLIDAYS:
            DayException.objects.get_or_create(
                year=year,
                start_date=day,
                end_date=day,
                kind=KIND_HOLIDAY,
                defaults={"title": title},
            )

        for position, term in enumerate(typical_terms(START_YEAR, LANGUAGE)):
            Term.objects.get_or_create(
                year=year,
                name=term["name"],
                defaults={
                    "start_date": term["start_date"],
                    "end_date": term["end_date"],
                    "position": position,
                },
            )

    def courses(self, school, year):
        from schedule.models import Course

        courses = {}
        for name, _, _ in COURSES:
            course, _ = Course.objects.get_or_create(
                school=school, year=year, name=name
            )
            courses[name] = course
        return courses

    def timetable(self, year, courses, people):
        """
        The school-wide timetable, so the teacher's import has a source.

        Deliberately not a copy of the personal schedule below. One course —
        the one nobody teaches personally — is laid out with **no teacher**:
        that is both the «load not shared out yet» state an administrator
        sees, and the course handed to the developer's own account so that
        pressing «import» visibly does something.
        """
        study_days = [day.date for day in year.build_days() if day.is_study]
        rows = []

        for name, email, week in COURSES:
            course = courses[name]
            # the importable course waits for a real account to claim it
            teacher = None if name == IMPORTABLE_COURSE else people[email]
            if MasterSlot.objects.filter(course=course).exists():
                continue

            # the course with no personal schedule still gets a timetable:
            # that is the one worth importing
            template = week or ((1, 3), (3, 3))

            rows.extend(
                MasterSlot(
                    school=course.school,
                    year=year,
                    course=course,
                    teacher=teacher,
                    date=day,
                    lesson_number=number,
                )
                for day in study_days
                for weekday, number in template
                if day.weekday() == weekday
            )

        MasterSlot.objects.bulk_create(rows)

    def schedule(self, year, courses, people):
        """
        A year of lessons: two or three a week per course.

        Non-study days are skipped by asking the calendar rather than by
        guessing — the same `build_days` the application uses, so the seeded
        schedule cannot disagree with what the interface draws.
        """
        study_days = [day.date for day in year.build_days() if day.is_study]

        for name, email, week in COURSES:
            if not week:
                continue

            course = courses[name]
            teacher = people[email]
            if LessonSlot.objects.filter(teacher=teacher, course=course).exists():
                continue

            LessonSlot.objects.bulk_create(
                LessonSlot(
                    year=year,
                    teacher=teacher,
                    course=course,
                    date=day,
                    lesson_number=number,
                )
                for day in study_days
                for weekday, number in week
                if day.weekday() == weekday
            )
        self.mark_by_hand(courses, people)

    def mark_by_hand(self, courses, people):
        """Cancellations and extra lessons — the states a uniform seed lacks."""
        teachers = {name: email for name, email, _ in COURSES}

        for name, index, reason in CANCELLED:
            slot = self.nth_slot(courses[name], index)
            if slot is not None and not slot.is_cancelled:
                slot.is_cancelled = True
                slot.reason = reason
                slot.save(update_fields=["is_cancelled", "reason"])

        for name, reason in EXTRA:
            course = courses[name]
            teacher = people[teachers[name]]
            if LessonSlot.objects.filter(
                teacher=teacher, course=course, is_extra=True
            ).exists():
                continue

            anchor = self.nth_slot(course, 5)
            if anchor is None:
                continue
            LessonSlot.objects.create(
                year=anchor.year,
                teacher=teacher,
                course=course,
                # a number the weekly template never uses, on the next day
                date=anchor.date + timedelta(days=1),
                lesson_number=7,
                is_extra=True,
                reason=reason,
            )

    def nth_slot(self, course, index):
        """
        The n-th regular lesson of a course.

        Extra lessons are left out of the count on purpose: they are added by
        this very command, and letting them shift the ordering would make the
        second run mark a different lesson than the first.
        """
        slots = LessonSlot.objects.filter(course=course, is_extra=False).order_by(
            "date", "lesson_number"
        )
        return slots[index] if slots.count() > index else None

    def plans(self, courses, people):
        """
        Three states side by side: a full plan, a short one, and nothing.

        Grade 9 Geometry keeps neither plan nor schedule — that is the course
        the empty states are checked against.
        """
        self.write_plan(courses["Grade 6 Algebra"], people["ivanova@example.com"], FULL_PLAN)
        self.write_plan(courses["Grade 9 Algebra"], people["petrov@example.com"], PARTIAL_PLAN)

    def write_plan(self, course, teacher, blocks):
        if PlanNode.objects.filter(teacher=teacher, course=course).exists():
            return

        for position, (title, lessons) in enumerate(blocks):
            section = PlanNode.objects.create(
                teacher=teacher,
                course=course,
                parent=None,
                position=position,
                is_section=True,
                title=title,
            )
            PlanNode.objects.bulk_create(
                PlanNode(
                    teacher=teacher,
                    course=course,
                    parent=section,
                    position=index,
                    is_section=False,
                    title=lesson,
                )
                for index, lesson in enumerate(lessons)
            )

    def attach(self, school, email):
        """
        Put the developer's own account into the school as an administrator.

        Without it the seeded school can only be looked at through the
        fictional accounts, which cannot sign in through Google.
        """
        email = (email or "").strip().lower()
        if not email:
            return None

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            # they have not signed in yet: leave an invitation instead, so
            # the first Google sign-in lands them in the school
            Invitation.objects.get_or_create(
                school=school, email=email, defaults={"is_school_admin": True}
            )
            return (
                f"{email} (приглашение — войдите через Google; чтобы получить "
                f"уроки в расписании школы, повторите seed_demo после входа)"
            )

        user.school = school
        user.is_school_admin = True
        user.save(update_fields=["school", "is_school_admin"])
        claimed = self.give_timetable(user)
        note = f", в расписании школы за вами {claimed} уроков" if claimed else ""
        return f"{email} (администратор школы{note})"

    def give_timetable(self, user) -> int:
        """
        Hand the importable course to this account, so import has an effect.

        Its rows are seeded with no teacher precisely so that a real person
        can claim them. Nothing of theirs can clash: the course has no
        personal schedule anywhere in the seed.
        """
        rows = MasterSlot.objects.filter(course__name=IMPORTABLE_COURSE)
        if rows.filter(teacher=user).exists():
            return rows.filter(teacher=user).count()

        return rows.filter(teacher__isnull=True).update(teacher=user)

    # --- what happened --------------------------------------------------------

    def summary(self, school, people, courses, options, attached):
        lessons = PlanNode.objects.filter(is_section=False).count()
        self.stdout.write(self.style.SUCCESS("\nseed_demo:"))
        self.stdout.write(f"  школа:     {school.name}")
        self.stdout.write(f"  год:       {YEAR_NAME} ({YEAR_START} — {YEAR_END})")
        self.stdout.write(
            f"  разметка:  {Term.objects.filter(year__school=school).count()} термов, "
            f"{DayException.objects.filter(year__school=school).count()} исключений"
        )
        self.stdout.write(f"  курсы:     {', '.join(courses)}")
        self.stdout.write(f"  учителя:   {', '.join(people)}")

        if options["minimal"]:
            self.stdout.write("  расписание и планы: пропущены (--minimal)")
        else:
            self.stdout.write(
                f"  уроки:     {LessonSlot.objects.count()} "
                f"({LessonSlot.objects.filter(is_cancelled=True).count()} отменено, "
                f"{LessonSlot.objects.filter(is_extra=True).count()} дополнительных)"
            )
            self.stdout.write(f"  план:      {lessons} уроков в планах")

        self.stdout.write(
            f"  расписание школы: {MasterSlot.objects.count()} уроков "
            f"({MasterSlot.objects.filter(teacher__isnull=True).count()} без учителя)"
        )

        if attached:
            self.stdout.write(self.style.SUCCESS(f"\n  войти как: {attached}"))
        else:
            self.stdout.write(
                "\n  войти под выдуманными учётками нельзя — вход только через "
                "Google. Свяжите свой аккаунт: --email=<ваш адрес>"
            )
