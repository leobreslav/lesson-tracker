"""
Живой год рядом с базовым — чтобы посмотреть на журнал с прошлым.

Разовая команда для разработки, не часть посева. Базовый набор строит год с
первым сентября, и до его начала в журнале нет ни одной прошедшей даты: столбцы
есть, а клеток нет. `--rich` живой год умеет, но идёт только вместе с `--flush`,
то есть ценой всей базы.

Поэтому здесь третий путь: **ничего не сносить**, а завести рядом второй год —
живой, с занятиями от начала июля, работами на прошедших часах и отмеченной
посещаемостью. Год в школе становится два, и это законное состояние: ограничение
у `SchoolYear` только на имя.

Данные пишутся теми же путями, что и приложение (`school_services.enrol`,
`works_services.grade`), а не мимо них: посев, пишущий в обход правил, выражает
состояние, которого в жизни не бывает.

Связь работы с часом ставится по правилу «оценка появляется на каком-то уроке»:
работа цепляется к тому занятию, на котором за неё выставили оценку. Поле
`Work.slot` подписано иначе («на каком задали»), и это расхождение здесь
намеренное — разговор о подписи идёт отдельно.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from calendars.models import SchoolYear, Term
from schedule.models import (
    Attendance,
    Course,
    CourseAssignment,
    CourseStudent,
    GradeLevel,
    Slot,
    Subject,
)
from schools import rich_demo, services as school_services
from schools.models import School
from works import services as works_services
from works.models import GradingSystem, Work

User = get_user_model()

COURSE_NAME = "Grade 8 Algebra"
SUBJECT = "Алгебра"
LEVEL = 8

# Дважды в неделю: (день недели, номер урока). Понедельник — 0.
# Двух хватает: три давали полсотни столбцов в одной четверти, и журнал
# читался только стрелками.
WEEK = ((0, 2), (3, 3))

# Сколько работ выставлено на каждом прошедшем часе. Ноль — тоже случай:
# в такой день в клетке стоит одна посещаемость, и столбец всё равно нужен.
PATTERN = (1, 0, 2, 1, 3, 0, 1, 2, 1, 0, 3, 1, 2, 1, 0, 1, 2, 1, 3, 0)

# Работы по порядку внутри дня: сначала классная, потом домашняя, потом
# контрольная. Система оценивания у каждой своя — иначе не видно, что журнал
# показывает буквы, а не числа.
KINDS = (
    ("Самостоятельная", False, False, "5-балльная"),
    ("Домашняя", True, False, "Зачёт"),
    ("Контрольная", False, True, "MYP 1–7"),
)

LABELS = {
    "5-балльная": ("5", "4", "3", "2"),
    "Зачёт": ("зачёт", "незачёт"),
    "MYP 1–7": ("7", "6", "5", "4", "3"),
}

COMMENTS = (
    "",
    "Разобрать вторую задачу.",
    "",
    "Аккуратнее с оформлением.",
    "",
)


class Command(BaseCommand):
    help = "Второй, живой учебный год рядом с базовым: журнал с прошлым"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="",
            help="учитель этого курса; по умолчанию первый администратор школы",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "living_year работает только при DEBUG=True: это выдуманные "
                "данные для разработки."
            )

        with transaction.atomic():
            school = School.objects.order_by("pk").first()
            if school is None:
                raise CommandError("В базе нет школы — сначала seed_demo.")

            teacher = self.teacher(school, options["email"])
            year = self.year(school)
            self.terms(year)
            course = self.course(school, year, teacher)
            students = self.enrol(school, course, teacher)
            slots = self.slots(year, course)

            today = timezone.localdate()
            past = [slot for slot in slots if slot.date <= today and not slot.is_cancelled]

            works = self.works(course, teacher, past)
            marks = self.grades(works, students, teacher)
            marked = self.attendance(past, students, teacher)

        self.report(year, course, teacher, students, slots, past, works, marks, marked)

    # --- части ---------------------------------------------------------------

    def teacher(self, school, email):
        if email:
            person = User.objects.filter(email=email).first()
            if person is None:
                raise CommandError(f"Нет такого пользователя: {email}")
            return person

        person = User.objects.filter(school=school, is_school_admin=True).first()
        if person is None:
            raise CommandError("Некому вести курс: назовите --email.")
        return person

    def year(self, school):
        """
        Год, внутри которого лежит сегодня. Имя своё — базовый год не трогаем.

        `living_year` даёт те же границы, что и крупному набору: от первого
        июля до первого июля. Имя базового года такое же по числам, а имя у
        года в школе уникально, — поэтому суффикс, а не совпадение.
        """
        start_year, start, end = rich_demo.living_year()
        name = f"{start_year}/{start_year + 1} · живой"

        year, _ = SchoolYear.objects.get_or_create(
            school=school,
            name=name,
            defaults={"start_date": start, "end_date": end},
        )
        return year

    def terms(self, year):
        """Четыре четверти, покрывающие живой год целиком — от июля до июня."""
        for position, term in enumerate(rich_demo.terms_for(year.start_date.year)):
            Term.objects.get_or_create(
                year=year,
                name=term["name"],
                defaults={
                    "start_date": term["start_date"],
                    "end_date": term["end_date"],
                    "position": position,
                },
            )

    def course(self, school, year, teacher):
        subject, _ = Subject.objects.get_or_create(school=school, name=SUBJECT)
        grade = GradeLevel.objects.filter(school=school, level=LEVEL).first()
        if grade is None:
            grade = GradeLevel.objects.create(
                school=school, level=LEVEL, name=f"Grade {LEVEL}"
            )

        course, _ = Course.objects.get_or_create(
            school=school,
            year=year,
            name=COURSE_NAME,
            defaults={"subject": subject, "grade": grade},
        )
        CourseAssignment.objects.get_or_create(course=course, teacher=teacher)
        return course

    def enrol(self, school, course, teacher):
        """
        Двенадцать учеников школы плюс один снятый: снятый остаётся строкой.

        Берутся уже заведённые — свои у этого года были бы вторым набором имён
        в той же школе, а журнал спрашивают про тех же детей.
        """
        people = list(
            User.objects.filter(school=school, kind=User.Kind.STUDENT).order_by(
                "last_name", "email"
            )[:13]
        )
        if len(people) < 3:
            raise CommandError("В школе почти нет учеников — сначала seed_demo.")

        for student in people:
            school_services.enrol(student, course, by=teacher)

        # последний — снятый с курса: оценки его никуда не делись, и строка в
        # журнале остаётся помеченной
        row = CourseStudent.objects.filter(course=course, student=people[-1]).first()
        if row is not None and row.removed_at is None:
            row.removed_at = timezone.now()
            row.save(update_fields=["removed_at"])

        return people[:-1]

    def slots(self, year, course):
        """
        Часы курса на весь год — по учебным дням, а не по календарю подряд.

        Дни спрашиваются у самого года (`build_days`), тем же расчётом, каким
        их рисует интерфейс: посеянное расписание не должно спорить с показанным.
        """
        if not Slot.objects.filter(course=course).exists():
            study = [day.date for day in year.build_days() if day.is_study]
            Slot.objects.bulk_create(
                Slot(year=year, course=course, date=day, lesson_number=number)
                for day in study
                for weekday, number in WEEK
                if day.weekday() == weekday
            )

        return list(
            Slot.objects.filter(course=course).order_by("date", "lesson_number", "id")
        )

    def works(self, course, teacher, past):
        """
        Работы на прошедших часах: где одна, где две, где три, а где ни одной.

        Час без работы — не пустая клетка, а обычный урок: в нём стоит
        посещаемость, и столбец нужен ровно затем.
        """
        systems = {
            system.name: system
            for system in GradingSystem.objects.filter(school=course.school)
        }
        made = []

        for at, slot in enumerate(past):
            for order in range(PATTERN[at % len(PATTERN)]):
                title, homework, summative, system = KINDS[order]
                name = f"{title} · {slot.date:%d.%m}"
                opens = timezone.make_aware(
                    datetime.combine(slot.date, time(9, 0)),
                    timezone.get_current_timezone(),
                )

                work, created = Work.objects.get_or_create(
                    course=course,
                    slot=slot,
                    title=name,
                    defaults={
                        "created_by": teacher,
                        "opens_at": opens,
                        "closes_at": opens + timedelta(days=7),
                        "is_homework": homework,
                        "is_summative": summative,
                        "grading_system": systems.get(system),
                        "description": "",
                        "attempts": None,
                    },
                )
                if created:
                    made.append((work, system, at))

        return made

    def grades(self, works, students, teacher):
        """
        Оценки — тем же вызовом, каким их ставит учитель (`services.grade`).

        Итог кладётся прямо в `final`: у этих работ нет ни задач, ни критериев,
        и отметка за них — то, что учитель написал рукой. Это и есть случай
        «ответ у доски»: работа без единого вопроса, зато с оценкой.
        """
        count = 0
        for work, system, at in works:
            labels = LABELS[system]
            for number, student in enumerate(students):
                # не у всех и не всегда: сплошная сетка отметок выглядит
                # правильно на любой вёрстке, а расходится она на дырах
                if (number + at) % 7 == 0:
                    continue

                works_services.grade(
                    work,
                    student,
                    final=labels[(number * 3 + at) % len(labels)],
                    comment=COMMENTS[(number + at) % len(COMMENTS)],
                    by=teacher,
                )
                count += 1

        return count

    def attendance(self, past, students, teacher):
        """
        Кто был на занятии: строка заводится только у отмеченных.

        Каждый пятый час не отмечен вовсе — «не отмечено» и «весь класс
        отсутствовал» разные вещи, и в журнале это должно быть видно.
        """
        marked = 0
        for at, slot in enumerate(past):
            if at % 5 == 4:
                continue

            for number, student in enumerate(students):
                turn = (number + at) % 11
                status = (
                    Attendance.Status.ABSENT
                    if turn == 0
                    else Attendance.Status.LATE
                    if turn == 3
                    else Attendance.Status.PRESENT
                )
                _, created = Attendance.objects.get_or_create(
                    slot=slot,
                    student=student,
                    defaults={
                        "status": status,
                        "note": "по заявлению" if turn == 0 else "",
                        "marked_by": teacher,
                    },
                )
                marked += int(created)

        return marked

    def report(self, year, course, teacher, students, slots, past, works, marks, marked):
        say = self.stdout.write
        say("")
        say(f"  год:        {year.name} ({year.start_date} — {year.end_date})")
        say(f"  курс:       {course.name}, ведёт {teacher.email}")
        say(f"  ученики:    {len(students)} в составе, 1 снят")
        say(f"  занятия:    {len(slots)} всего, {len(past)} прошедших")
        say(f"  работы:     {len(works)} на прошедших часах")
        say(f"  оценки:     {marks}")
        say(f"  отмечено:   {marked} строк посещаемости")
        say("")
        say(f"  журнал:     http://localhost:5173/journal (курс «{course.name}»)")
        say("")
