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
from bank.models import (
    Entry,
    Problem,
    Proposal,
    Section,
    Solution,
    SolutionTag,
    Source as BankSource,
    Tag as BankTag,
    Topic,
)
from calendars.models import DayException, SchoolYear, Term
from calendars.services import KIND_HOLIDAY, KIND_VACATION
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from files import services as file_services
from files import storage as file_storage
from files.models import KIND_FILE, KIND_LINK, Attachment, StoredFile
from onboarding.services import typical_terms, typical_vacations
from plans.models import PlanNode
from library import services as library_services
from library.models import PlanTemplate, PlanTemplateRow
from schedule.models import (
    Course,
    CourseAssignment,
    CourseStudent,
    GradeLevel,
    Slot,
    Subject,
)
from schedule import services as schedule_services
from schools import demo_extras, rich_demo, services as school_services
from schools.models import Invitation, School
from works import statements
from works.models import Submission, Task, Work

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

# Ученики: имя, фамилия и адрес. Шестеро на курс — столько же, сколько в
# небольшой группе, и достаточно, чтобы сводная таблица работ выглядела как
# таблица, а не как строка.
STUDENTS = (
    ("stepanov@example.com", "Артём", "Степанов"),
    ("volkova@example.com", "Дарья", "Волкова"),
    ("orlov@example.com", "Кирилл", "Орлов"),
    ("zaytseva@example.com", "Полина", "Зайцева"),
    ("belov@example.com", "Никита", "Белов"),
    ("gusev@example.com", "Матвей", "Гусев"),
    ("titova@example.com", "Софья", "Титова"),
    ("noskov@example.com", "Егор", "Носков"),
    ("lebedeva@example.com", "Алиса", "Лебедева"),
    ("kuznetsov@example.com", "Тимур", "Кузнецов"),
    ("mironova@example.com", "Варвара", "Миронова"),
    ("shilov@example.com", "Даниил", "Шилов"),
    ("panova@example.com", "Ксения", "Панова"),
    # снят с курса: видит сделанное, работать не может. Состояние редкое, но
    # именно на нём разъезжаются экраны, поэтому оно есть в демо
    ("morozova@example.com", "Ева", "Морозова"),
)

# в каком курсе учится группа
STUDENT_COURSE = "Grade 6 Algebra"
REMOVED_STUDENT = "morozova@example.com"

# приглашён, но ещё не входил: администратор видит его в списке ожидающих
INVITED_STUDENT = "sokolov@example.com"

# (course name, teacher email, weekly slots as (weekday, lesson number))
# weekday numbers are ours: Monday is 0, as in date.weekday()
# (course name, subject, grade, teacher email, weekly slots)
COURSES = (
    ("Grade 6 Algebra", "Алгебра", 6, "ivanova@example.com", ((0, 1), (2, 1), (4, 2))),
    ("Grade 6 Geometry", "Геометрия", 6, "ivanova@example.com", ((1, 2), (3, 1))),
    ("Grade 9 Algebra", "Алгебра", 9, "petrov@example.com", ((0, 3), (2, 3), (4, 4))),
    # deliberately without a personal timetable: empty states need a course
    ("Grade 9 Geometry", "Геометрия", 9, "petrov@example.com", ()),
)

SUBJECTS = ("Алгебра", "Геометрия")

# Two of the eleven default year groups are renamed: «Grade 9» becomes an MYP
# label whose number says 4 while its year of study is 9. Sorting has to keep
# it in the right place, and a demo where every name matches its number would
# never show that it does.
DEMO_GRADE_NAMES = {6: "Grade 6", 9: "MYP 4"}

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

# Slot content on three lessons out of forty — enough to see the panel with
# something in it and the paperclip on some rows but not all.
#
# Markdown with maths in $…$ and $$…$$, which is the point: the panel has to
# render it and the export has to hand it over to LaTeX unharmed.
LESSON_CONTENT = {
    "Признаки делимости на 3 и 9": {
        "objectives": (
            "**A. Знание и понимание** — применять признаки делимости.\n\n"
            "**B. Исследование закономерностей** — сформулировать признак "
            "самостоятельно, проверив гипотезу на примерах.\n"
        ),
        "body": (
            "## Признак делимости на 3\n\n"
            "Число делится на 3 тогда и только тогда, когда на 3 делится "
            "сумма его цифр.\n\n"
            "Для $N = \\overline{a_k a_{k-1} \\ldots a_0}$ верно\n\n"
            "$$N = \\sum_{i=0}^{k} a_i \\cdot 10^i "
            "\\equiv \\sum_{i=0}^{k} a_i \\pmod 3,$$\n\n"
            "поскольку $10 \\equiv 1 \\pmod 3$, а значит и "
            "$10^i \\equiv 1 \\pmod 3$ при любом $i$.\n\n"
            "### Разбор у доски\n\n"
            "1. $4\\,725$: сумма цифр $18$, делится на 9 — значит и на 3.\n"
            "2. $1\\,003$: сумма цифр $4$ — не делится ни на 3, ни на 9.\n"
        ),
        "formative": (
            "Пять чисел на карточке. Для каждого ответить, делится ли оно "
            "на 3 и на 9, и **назвать сумму цифр** как обоснование:\n\n"
            "$2\\,331$, $50\\,004$, $7\\,777$, $123\\,456$, $999\\,000$\n"
        ),
        "homework": "№ 84–89, а также № 93 (со звёздочкой) — доказать признак для 9.\n",
    },
    "Сложение и вычитание": {
        "objectives": "**A. Знание и понимание** — складывать дроби с разными знаменателями.\n",
        "body": (
            "Общий знаменатель — это НОК знаменателей:\n\n"
            "$$\\frac{a}{b} + \\frac{c}{d} = \\frac{a \\cdot \\frac{m}{b} + "
            "c \\cdot \\frac{m}{d}}{m}, \\qquad m = \\mathrm{НОК}(b, d).$$\n\n"
            "Например, $\\frac{5}{12} + \\frac{7}{18} = \\frac{15 + 14}{36} "
            "= \\frac{29}{36}$.\n"
        ),
        "formative": "Три примера на доске, два в тетради. Проверка в парах.\n",
        "homework": "№ 265–270.\n",
    },
    "Длина окружности": {
        "objectives": "**D. Применение математики в реальном контексте.**\n",
        "body": (
            "$$C = 2\\pi R = \\pi D$$\n\n"
            "Измеряем нитью крышку банки и колесо самоката, считаем "
            "отношение $C / D$ и сравниваем с $\\pi \\approx 3{,}1416$.\n"
        ),
        "formative": "",
        "homework": "Измерить дома три круглых предмета, заполнить таблицу.\n",
    },
}

# Files and links on those same lessons. The bytes are made up here rather
# than shipped in the repository: a seeder that needs binary fixtures is a
# seeder nobody can read.
DEMO_FILES = (
    (
        "Признаки делимости на 3 и 9",
        "Карточка — делимость.txt",
        "text/plain",
        "2331  50004  7777  123456  999000\n"
        "Для каждого числа: сумма цифр, делится ли на 3, делится ли на 9.\n",
    ),
    (
        "Сложение и вычитание",
        "Тренажёр — дроби.txt",
        "text/plain",
        "5/12 + 7/18 =\n3/8 + 5/6 =\n7/15 - 2/9 =\n",
    ),
)

DEMO_LINKS = (
    ("Длина окружности", "GeoGebra: окружность и её длина", "https://www.geogebra.org/"),
)

# a handful of lessons marked by hand, so the schedule is not uniform
CANCELLED = (("Grade 6 Algebra", 12, "Болезнь"), ("Grade 6 Algebra", 30, "Карантин"),
             ("Grade 9 Algebra", 18, "Актированный день"))
EXTRA = (("Grade 6 Geometry", "Консультация"), ("Grade 9 Algebra", "Замена коллеги"))

# задачи демонстрационных работ: у одной эталонов два — «x+3» и «3+x» верны
# одинаково, и именно это список допустимых ответов и выражает
OPEN_TASKS = (
    ("Раскройте скобки: $(a+b)^2$", ("a^2+2ab+b^2", "a^2 + 2ab + b^2")),
    ("Упростите: $x + 3 + 0$", ("x+3", "3+x")),
    ("Чему равен $\\sin(90°)$?", ("1",)),
)

PAST_TASKS = (
    ("Вычислите $\\sin(30°) + \\cos(60°)$", ("1",)),
    ("Решите уравнение $2x = 10$", ("5", "x=5")),
    ("Назовите формулу синуса суммы", ("sin(a+b)=sin a cos b + cos a sin b",)),
    ("Чему равен $\\cos(0)$?", ("1",)),
    ("Упростите $\\sin^2 x + \\cos^2 x$", ("1",)),
    ("Решите $\\tg x = 0$ на $[0; \\pi]$", ("0", "x=0", "0, pi")),
)


# Словарь: по паре тегов каждого вида, чтобы в поиске были видны все грани —
# в том числе те, что живут на решении и умеют отрицание.
DEMO_TAGS = [
    ("алгебра", "subject"),
    ("геометрия", "subject"),
    ("многочлен", "object"),
    ("окружность", "object"),
    ("доказательство", "task"),
    ("уравнение", "task"),
    ("теорема Виета", "theorem"),
    ("замена переменной", "method"),
]

DEMO_SOLUTIONS = [
    ("1", "По теореме Виета", ["алгебра", "теорема Виета"]),
    ("2", "Заменой $t=x^2$", ["алгебра", "замена переменной"]),
]

# Открытая тема спрашивает «есть ли в разборе вот это», закрытая — ещё и «нет
# ли в нём ничего сверх пройденного». Порознь разницу не увидеть.
DEMO_TOPICS = [
    ("Квадратные уравнения", ["алгебра"], False),
    ("Что мы уже умеем", ["алгебра"], True),
]

DEMO_PROBLEMS = [
    ("1", r"Решите уравнение $x^2 - 5x + 6 = 0$.", ["алгебра", "многочлен", "уравнение"]),
    ("2", r"Решите уравнение $x^4 - 5x^2 + 4 = 0$.", ["алгебра", "уравнение"]),
    (
        "3",
        r"Докажите, что $x^2 + y^2 \geqslant 2xy$ при любых $x$ и $y$.",
        ["алгебра", "доказательство"],
    ),
    (
        "4",
        "Окружность вписана в прямоугольный треугольник. Найдите её радиус.",
        ["геометрия", "окружность"],
    ),
]


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
        parser.add_argument(
            "--rich",
            action="store_true",
            help=(
                "школа в рабочем размере: живой год, пять учителей, планы по "
                "сотне уроков, шесть десятков учеников, работы с ответами"
            ),
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

            rich = options["rich"]
            school = self.school()
            people = self.people(school)
            year = self.year(school, rich=rich)
            self.markup(year, rich=rich)
            subjects = self.subjects(school)
            grades = self.grades(school)
            courses = self.courses(school, year, subjects, grades, people)
            students = self.students(school, courses)

            if not options["minimal"]:
                self.works(courses, people, students)
                self.schedule(year, courses, people)
                self.plans(courses, people)
                self.library(school, subjects, people, courses)
                self.bank(school, people, courses)
                demo_extras.build(
                    school, courses, people, students, log=self.stdout.write
                )

            if rich and not options["minimal"]:
                rich_demo.build(
                    school, year, people, subjects, grades, log=self.stdout.write
                )

            attached = self.attach(school, options["email"])

        self.summary(school, people, courses, options, attached)

    def students(self, school, courses):
        """
        Группа учеников в одном курсе плюс два особых случая.

        Первый — снятый с курса: строка остаётся, `removed_at` стоит, и он
        по-прежнему видит сделанное. Второй — приглашённый, который ещё ни
        разу не входил: у администратора он в списке ожидающих, учётки нет.

        Оба нужны здесь, а не в тестах: на ровном списке из шести человек
        экраны выглядят одинаково правильно, а расходятся они как раз на
        этих двух.
        """
        course = courses[STUDENT_COURSE]
        enrolled = []

        for email, first, last in STUDENTS:
            student, _ = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "school": school,
                    "kind": User.Kind.STUDENT,
                    "language": LANGUAGE,
                    # эти уже входили: «ещё не входил» — отдельное
                    # состояние набора, и оно принадлежит одному человеку
                    "last_login": timezone.now(),
                },
            )
            EmailAddress.objects.get_or_create(
                user=student,
                email=student.email,
                defaults={"verified": True, "primary": True},
            )
            row = school_services.enrol(student, course)
            if email == REMOVED_STUDENT:
                school_services.remove_from_course(row)
            enrolled.append(student)

        # Приглашённый, который ещё ни разу не входил, — третье состояние
        # ученика. Учётка у него теперь настоящая и с первой минуты: её
        # видно в списках, она записана на курс, и отличает её только
        # пустой `last_login`.
        invitation, _ = Invitation.objects.get_or_create(
            school=school,
            email=INVITED_STUDENT,
            defaults={"kind": User.Kind.STUDENT},
        )
        if not User.objects.filter(email=INVITED_STUDENT).exists():
            newcomer = school_services.provision(
                school, INVITED_STUDENT, kind=User.Kind.STUDENT, name="Новичок"
            )
            school_services.enrol(newcomer, course)

        return enrolled

    def works(self, courses, people, students):
        """
        Работы — те же три состояния, что у всего остального в этом seed'е.

        Открытая, закрытая и запланированная: на ровном наборе экраны
        выглядят одинаково правильно, а расходятся они как раз здесь —
        запланированной ученик не видит вовсе, в закрытой не может отвечать,
        а в открытой у него кончаются попытки.

        В закрытой лежат ответы: без них сводная таблица учителя — пустая
        сетка, на которой ничего не проверишь глазами.
        """
        course = courses[STUDENT_COURSE]
        teacher = people[COURSES[0][3]]
        now = timezone.now()

        open_work, created = Work.objects.get_or_create(
            course=course,
            created_by=teacher,
            title="Проверочная: формулы сложения",
            defaults={
                "opens_at": now - timedelta(hours=2),
                "closes_at": now + timedelta(days=3),
                "attempts": 2,
            },
        )
        if created:
            for position, (question, answers) in enumerate(OPEN_TASKS):
                self.ask(open_work, teacher, position, question, answers)

        past, created = Work.objects.get_or_create(
            course=course,
            created_by=teacher,
            title="Контрольная: тригонометрия",
            defaults={
                "opens_at": now - timedelta(days=9),
                "closes_at": now - timedelta(days=8),
                "attempts": 1,
            },
        )
        if created:
            for position, (question, answers) in enumerate(PAST_TASKS):
                self.ask(past, teacher, position, question, answers)

        # ответы досеваются на каждом прогоне, а не только при создании
        # работы: ученик, появившийся позже, иначе остался бы с пустой
        # строкой навсегда, а таблица — с дырой, которой в жизни не бывает
        self.answers(list(past.tasks.all()), students, teacher, now, checked=True)
        self.answers(
            list(open_work.tasks.all()), students, teacher, now, checked=False
        )

        Work.objects.get_or_create(
            course=course,
            created_by=teacher,
            title="Домашняя работа на каникулы",
            defaults={
                # окно в будущем и есть «черновик»: ученику её пока нет
                "opens_at": now + timedelta(days=5),
                "closes_at": now + timedelta(days=12),
                "show_result": False,
            },
        )

    def ask(self, work, teacher, position, question, answers):
        """
        Ячейка работы вместе с условием.

        Условие заводится тем же путём, что и в приложении: своего текста у
        ячейки нет ни одного поля, и посев, пишущий его мимо, выражал бы
        состояние, которого не бывает. Задачи эти личные и ни в одной книге не
        лежат — ровно как у учителя, набравшего их на бегу.
        """
        task = Task.objects.create(work=work, position=position)
        statements.say(task, text=question, answers=list(answers), user=teacher)
        return task

    def answers(self, tasks, students, teacher, now, *, checked):
        """
        Ответы в работе. Не случайные — по списку состояний клетки.

        Сводная таблица тем и живёт, что в ней видно **разное**: пустая
        клетка, ответ без отметки, верный, неверный и переделанный после
        проверки. Ровный набор из одних галочек выглядит правильно на любой
        вёрстке, а разъезжается она как раз на смеси, поэтому состояния
        перечислены здесь списком и раскладываются по сетке по остатку.

        `checked=False` — открытая работа: отметок в ней почти нет, её ещё
        решают, и она нужна, чтобы посмотреть на «17 ответов на проверку».

        Идемпотентность: пара «задача и ученик», у которой уже есть хоть
        одна отправка, пропускается целиком. Иначе второй прогон дописывал
        бы всем по второй попытке.
        """
        if not tasks:
            return

        # состояния клетки по кругу; пропуск — тоже состояние, и его в
        # списке два, чтобы таблица не выглядела заполненной сплошь
        pattern = ("correct", "wrong", "unchecked", "skip", "correct", "redone", "skip")

        for index, student in enumerate(students):
            # первый в списке открытую работу ещё не открывал: пустой экран
            # решения — тоже состояние, и посмотреть на него надо уметь
            if index == 0 and not checked:
                continue

            for position, task in enumerate(tasks):
                if Submission.objects.filter(task=task, student=student).exists():
                    continue

                state = pattern[(index + position) % len(pattern)]
                # первый отвечает на всё: иначе плашка «прошли работу
                # целиком» всегда ноль, и по ней не понять, считает ли она
                if index == 0 and state == "skip":
                    state = "correct"
                if state == "skip":
                    continue
                if not checked and state in ("correct", "wrong"):
                    # открытую ещё не проверяли: пусть ждёт очереди
                    state = "unchecked"

                right = statements.answers_of(task)[:1] or ["мой ответ"]
                right = right[0]
                wrong = "не знаю"
                minutes = index * 3 + position

                first = Submission.objects.create(
                    task=task,
                    student=student,
                    answer=right if state in ("correct", "redone") else wrong,
                    is_correct=None if state == "unchecked" else state == "correct",
                    checked_at=None if state == "unchecked" else now - timedelta(days=6),
                    checked_by=None if state == "unchecked" else teacher,
                )
                Submission.objects.filter(pk=first.pk).update(
                    created_at=now - timedelta(days=7, minutes=-minutes)
                )

                if state == "redone":
                    # проверенный ответ переделали: отметка осталась на
                    # прошлой строке, клетка вернулась в «не проверено»
                    Submission.objects.filter(pk=first.pk).update(is_correct=False)
                    Submission.objects.create(
                        task=task, student=student, answer=right
                    )

    # --- building blocks ------------------------------------------------------

    def flush(self):
        """
        Everything, in dependency order.

        Slots and plan rows hold their course under PROTECT, so they go
        first; users hold their school the same way and are cleared before
        the schools themselves. Superusers survive: wiping the account you
        administer the box with is never what you meant.
        """
        # работы держат курс через PROTECT, как уроки и план, поэтому идут
        # первыми — вместе с задачами и ответами, которые висят на них
        # Задачник сносится первым и **целиком**, включая системный уровень:
        # у системных задач, книг и тем школы нет вовсе, и каскад от школы до
        # них не доходит — после `--flush` они оставались бы в базе, а посев
        # видел бы их и не заводил заново. Порядок внутри свой: предложения
        # держат задачи, ячейки работ держат условия через `PROTECT`.
        Work.objects.all().delete()
        Proposal.objects.all().delete()
        # у темы родитель под `PROTECT` (ветка не должна молча расширяться),
        # поэтому при сносе всего сперва развязываем дерево
        Topic.objects.all().update(parent=None)
        Topic.objects.all().delete()
        BankSource.objects.all().delete()
        Problem.objects.all().delete()
        BankTag.objects.all().delete()
        PlanTemplate.objects.all().delete()
        PlanNode.objects.all().delete()
        # the two deletes above took every attachment with them, so nothing
        # points at a file any more. The signal that empties the bucket runs
        # on commit and would find the rows already gone by then (schools
        # cascade into them), so the objects are removed here instead
        self.flush_files()
        Slot.objects.all().delete()
        Course.objects.all().update(subject=None)
        Subject.objects.all().delete()
        SchoolYear.objects.all().delete()  # carries courses, terms, markup
        Invitation.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        User.objects.filter(is_superuser=True).update(school=None, is_school_admin=False)
        School.objects.all().delete()
        self.stdout.write(self.style.WARNING("  очищено: всё, кроме суперпользователей"))

    def flush_files(self):
        """
        Empty the dev bucket of what this seed put there.

        Снимки плана сносятся **до** файлов, и это не мелочь: снимок держит
        объект в хранилище через `PROTECT` — ровно затем, чтобы отменённое
        удаление строки могло вернуть её вложения. При сносе всего этот
        замок срабатывает первым, и `--flush` падает с `ProtectedError`,
        успев удалить половину. Поймано досевом, который начал заводить
        снимки: до него в базе разработки их просто не бывало.
        """
        from plans.models import PlanSnapshot

        PlanSnapshot.objects.all().delete()

        gone = 0
        for stored in StoredFile.objects.all():
            try:
                file_storage.delete(stored.key)
            except file_storage.StorageUnavailable as error:
                self.stdout.write(self.style.WARNING(f"  {stored.key}: {error}"))
                continue
            gone += 1

        StoredFile.objects.all().delete()
        if gone:
            self.stdout.write(self.style.WARNING(f"  очищено файлов: {gone}"))

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
                    # сотрудники уже входили: без этого в списках у всех
                    # стояла бы пометка «ещё не входил»
                    "last_login": timezone.now(),
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

    def year(self, school, *, rich=False):
        """
        Учебный год. Обычно фиксированный, у крупного набора — живой.

        Даты базового набора зашиты нарочно: на них стоят браузерные тесты,
        и «первый понедельник» в них написан числом. Крупному набору,
        наоборот, нужен год, внутри которого лежит сегодня, — иначе в нём
        нет ни одного проведённого занятия, а без прошлого не видно ни
        связи «занятие проведено», ни долгов, ни разложения резерва.
        """
        if rich:
            start_year, start, end = rich_demo.living_year()
            name = f"{start_year}/{start_year + 1}"
        else:
            start, end, name = YEAR_START, YEAR_END, YEAR_NAME

        year, created = SchoolYear.objects.get_or_create(
            school=school,
            name=name,
            defaults={"start_date": start, "end_date": end},
        )
        if not created and (year.start_date, year.end_date) != (start, end):
            year.start_date, year.end_date = start, end
            year.save(update_fields=["start_date", "end_date"])

        return year

    def markup(self, year, *, rich=False):
        """Breaks, public holidays and the four quarters between them."""
        start_year = year.start_date.year
        for vacation in typical_vacations(start_year, LANGUAGE):
            DayException.objects.get_or_create(
                year=year,
                start_date=vacation["start_date"],
                end_date=vacation["end_date"],
                kind=KIND_VACATION,
                defaults={"title": vacation["title"]},
            )

        for day, title in HOLIDAYS:
            if not year.start_date <= day <= year.end_date:
                continue
            DayException.objects.get_or_create(
                year=year,
                start_date=day,
                end_date=day,
                kind=KIND_HOLIDAY,
                defaults={"title": title},
            )

        # у живого года четверти свои: `typical_terms` начинает первым
        # сентября, и июль с августом не попали бы ни в один терм — занятия
        # в них есть, а терма нет, и это было бы случайностью, а не решением
        terms = (
            rich_demo.terms_for(start_year)
            if rich
            else typical_terms(start_year, LANGUAGE)
        )
        for position, term in enumerate(terms):
            Term.objects.get_or_create(
                year=year,
                name=term["name"],
                defaults={
                    "start_date": term["start_date"],
                    "end_date": term["end_date"],
                    "position": position,
                },
            )

    def subjects(self, school):
        return {
            name: Subject.objects.get_or_create(school=school, name=name)[0]
            for name in SUBJECTS
        }

    def grades(self, school):
        """
        Year groups. Заводятся здесь же: новая школа не получает ни одной,
        а две из них переименованы, чтобы было видно — имя и год обучения
        разные вещи, ради чего справочник и заведён.
        """
        levels = {
            level.level: level
            for level in GradeLevel.objects.filter(school=school)
        }
        for level, name in DEMO_GRADE_NAMES.items():
            grade = levels.get(level) or GradeLevel.objects.create(
                school=school, level=level, name=name
            )
            if grade.name != name:
                grade.name = name
                grade.save(update_fields=["name"])
            levels[level] = grade
        return levels

    def courses(self, school, year, subjects, grades, people):
        courses = {}
        for name, subject, grade, email, _ in COURSES:
            course, _ = Course.objects.get_or_create(
                school=school,
                year=year,
                name=name,
                defaults={"subject": subjects[subject], "grade": grades[grade]},
            )
            # a course made before subjects existed gets them now
            if course.subject_id is None:
                course.subject = subjects[subject]
                course.grade = grades[grade]
                course.save(update_fields=["subject", "grade"])

            # who teaches it — the link the timetable and every personal list
            # now hang off
            CourseAssignment.objects.get_or_create(
                course=course, teacher=people[email]
            )
            courses[name] = course
        return courses

    def schedule(self, year, courses, people):
        """
        A year of lessons: two or three a week per course.

        Non-study days are skipped by asking the calendar rather than by
        guessing — the same `build_days` the application uses, so the seeded
        schedule cannot disagree with what the interface draws.
        """
        study_days = [day.date for day in year.build_days() if day.is_study]

        for name, _, _, email, week in COURSES:
            if not week:
                continue

            course = courses[name]
            if Slot.objects.filter(course=course).exists():
                continue

            Slot.objects.bulk_create(
                Slot(
                    year=year,
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
        for name, index, reason in CANCELLED:
            slot = self.nth_slot(courses[name], index)
            if slot is not None and not slot.is_cancelled:
                slot.is_cancelled = True
                slot.reason = reason
                slot.save(update_fields=["is_cancelled", "reason"])

        for name, reason in EXTRA:
            course = courses[name]
            if Slot.objects.filter(course=course, is_extra=True).exists():
                continue

            anchor = self.nth_slot(course, 5)
            if anchor is None:
                continue

            day = anchor.date + timedelta(days=1)
            lead = CourseAssignment.objects.filter(course=course).first()
            # номер спрашиваем, а не назначаем: «тот, который сетка не
            # занимает» было правдой, пока курсов было четыре, — с крупным
            # набором учитель оказывался в двух местах разом
            number = schedule_services.free_number(
                teacher_id=lead.teacher_id if lead else None,
                year=anchor.year,
                day=day,
                start=7,
            )
            if number is None:
                continue

            Slot.objects.create(
                year=anchor.year,
                course=course,
                date=day,
                lesson_number=number,
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
        slots = Slot.objects.filter(course=course, is_extra=False).order_by(
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

    def library(self, school, subjects, people, courses):
        """
        A shelf with something on it: two published plans and one draft.

        The draft belongs to a fictional teacher on purpose — that is the
        entry the developer must *not* see until they log in as its author,
        which is the visibility rule worth eyeballing.

        The first entry is **snapshotted from a real course plan** instead of
        being written out here, and that is the point of it: only that path
        carries the lesson content and the attachments across. Taking it into
        another course then leads to the same object in R2 rather than to a
        copy — the shareability worth checking by hand.
        """
        source = courses["Grade 6 Algebra"], people["ivanova@example.com"]

        shelf = (
            ("Алгебра 6, по учебнику", subjects["Алгебра"], 6,
             people["ivanova@example.com"], True, source),
            ("Геометрия 9, базовая", subjects["Геометрия"], 9,
             people["petrov@example.com"], True, PARTIAL_PLAN),
            ("Алгебра 9, черновик", subjects["Алгебра"], 9,
             people["petrov@example.com"], False, PARTIAL_PLAN),
        )

        for title, subject, grade, author, published, blocks in shelf:
            if PlanTemplate.objects.filter(school=school, title=title).exists():
                continue

            template = PlanTemplate.objects.create(
                school=school,
                subject=subject,
                grade=grade,
                title=title,
                description="Демонстрационный шаблон из seed_demo.",
                author=author,
                is_published=published,
            )

            if blocks is source:
                course, teacher = blocks
                library_services.write_rows(
                    template,
                    library_services.plan_as_rows(course.pk),
                )
                continue

            rows, position = [], 0
            for header, lessons in blocks:
                rows.append(
                    PlanTemplateRow(
                        template=template, position=position, is_header=True, title=header
                    )
                )
                position += 1
                for lesson in lessons:
                    rows.append(
                        PlanTemplateRow(
                            template=template, position=position, title=lesson
                        )
                    )
                    position += 1

            PlanTemplateRow.objects.bulk_create(rows)

    def bank(self, school, people, courses=None):
        """
        Задачник: словарь тегов и книга с задачами.

        Словарь тут не украшение — без него поиск по граням показывает пустую
        колонку, и непонятно, сломан он или просто нечем сужать. Теги
        системные (их и в жизни заводит суперпользователь), поэтому при
        повторном посеве они не дублируются, а находятся по имени и виду.
        """
        tags = {}
        for name, kind in DEMO_TAGS:
            tags[name] = BankTag.objects.get_or_create(name=name, kind=kind)[0]

        teacher = people["ivanova@example.com"]
        source, _ = BankSource.objects.get_or_create(
            title="Листочки по алгебре",
            school=school,
            owner=teacher,
            # предмет у книги — чтобы самый глобальный фильтр было чем
            # проверить, и чтобы её задачи получили его сразу
            defaults={"created_by": teacher, "subject": tags["алгебра"]},
        )
        if source.entries.exists():
            return

        section = Section.objects.create(source=source, title="Квадратные уравнения")
        for position, (label, text, on_it) in enumerate(DEMO_PROBLEMS):
            problem = Problem.objects.create(
                text=text, school=school, owner=teacher, created_by=teacher
            )
            for name in on_it:
                problem.links.create(tag=tags[name])
            Entry.objects.create(
                source=source,
                section=section,
                problem=problem,
                label=label,
                position=position,
            )
        self.solutions(school, teacher, tags, source)
        self.topics(tags)
        if courses:
            self.chronology(courses, tags)
        self.stdout.write("  задачник:  4 задачи, 2 разбора, словарь из 8 тегов")

    def solutions(self, school, teacher, tags, source):
        """
        Разборы: без них тематический каталог пуст, а он именно про них.
        Тема — условие на средства **решения**, и задача попадает в неё через
        свой разбор, а не через собственные теги.
        """
        for label, title, uses in DEMO_SOLUTIONS:
            entry = source.entries.filter(label=label).first()
            if entry is None or entry.problem.solutions.exists():
                continue
            solution = Solution.objects.create(
                problem=entry.problem,
                title=title,
                text="…",
                school=school,
                owner=teacher,
                created_by=teacher,
            )
            for name in uses:
                solution.links.create(tag=tags[name], side=SolutionTag.USES)

    def topics(self, tags):
        """
        Две темы, и вторая вложена в первую: **вложение сужает**, и увидеть
        это можно только парой. Заодно вторая — про пройденное, то есть та,
        что спрашивает курс и урок.
        """
        parent = None
        for title, essence, closed in DEMO_TOPICS:
            wanted = {"uses": [tags[name].pk for name in essence]}
            if closed:
                wanted["covered"] = True
            topic, _ = Topic.objects.get_or_create(
                title=title,
                defaults={"expression": {"solution": wanted}, "parent": parent},
            )
            parent = parent or topic

    def chronology(self, courses, tags):
        """
        Одно понятие отмечено введённым: закрытая тема без хронологии отвечает
        «ничего» — правда, но бесполезная, и на демо она выглядит поломкой.
        """
        from bank import topics as bank_topics

        course = courses["Grade 6 Algebra"]
        lesson = PlanNode.objects.filter(course=course, is_section=False).first()
        if lesson:
            bank_topics.introduce(course, lesson, tags["теорема Виета"])

    def write_plan(self, course, teacher, blocks):
        if PlanNode.objects.filter(course=course).exists():
            return

        for position, (title, lessons) in enumerate(blocks):
            section = PlanNode.objects.create(
                course=course,
                parent=None,
                position=position,
                is_section=True,
                title=title,
            )
            PlanNode.objects.bulk_create(
                PlanNode(
                    course=course,
                    parent=section,
                    position=index,
                    is_section=False,
                    title=lesson,
                    **LESSON_CONTENT.get(lesson, {}),
                )
                for index, lesson in enumerate(lessons)
            )

        self.attachments(course, teacher)

    # --- files -------------------------------------------------------------------

    def storage_ready(self) -> bool:
        """
        Whether uploading is even worth trying.

        The browser-test stack and a fresh clone have no R2 keys, and a
        seeder that dies because of that is a seeder that stops being run.
        Content and links still land; only the uploads are skipped, loudly.

        Спрашивается **хранилище**, а не настройки, и разница не
        косметическая. Тут стояла своя копия того же условия
        (`R2_BUCKET_NAME and R2_ENDPOINT_URL`), и в тестах она врала: раннер
        подменяет бэкенд на память, писать туда можно и нужно, а копия
        по-прежнему смотрела в пустые настройки и пропускала файлы. Сторож
        пустоты падал у всех, у кого нет ключей R2, — то есть у всех, кроме
        машины, где эти строки писали. `files.storage.configured()` знает
        оба случая, и знать их должен он один.
        """
        return file_storage.configured()

    def attachments(self, course, teacher):
        """Files and links on the lessons that have content."""
        lessons = {
            node.title: node
            for node in PlanNode.objects.filter(course=course, is_section=False)
        }

        for title, name, kind, text in DEMO_FILES:
            node = lessons.get(title)
            if node is None or node.attachments.filter(kind=KIND_FILE).exists():
                continue
            if not self.storage_ready():
                continue

            upload = SimpleUploadedFile(name, text.encode("utf-8"), content_type=kind)
            try:
                stored, _ = file_services.store_upload(
                    upload=upload, school=course.school, user=teacher
                )
            except (file_storage.StorageUnavailable, file_services.UploadRefused) as error:
                self.stdout.write(self.style.WARNING(f"  файл {name}: {error}"))
                continue

            Attachment.objects.create(
                plan_row=node, kind=KIND_FILE, stored_file=stored, title=name
            )

        for title, label, address in DEMO_LINKS:
            node = lessons.get(title)
            if node is None or node.attachments.filter(kind=KIND_LINK).exists():
                continue
            Attachment.objects.create(
                plan_row=node, kind=KIND_LINK, url=address, title=label
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
        return f"{email} (администратор школы)"

    # --- what happened --------------------------------------------------------

    def summary(self, school, people, courses, options, attached):
        lessons = PlanNode.objects.filter(is_section=False).count()
        # числа читаются из базы, а не из констант: с `--rich` половина
        # данных приходит из другого модуля, и сводка, собранная по здешним
        # спискам, врала бы ровно про то, ради чего этот флаг и нажали
        year = SchoolYear.objects.filter(school=school).order_by("-start_date").first()
        teachers = User.objects.filter(school=school, kind=User.Kind.TEACHER)
        learners = User.objects.filter(school=school, kind=User.Kind.STUDENT)
        all_courses = Course.objects.filter(school=school).order_by("name")

        self.stdout.write(self.style.SUCCESS("\nseed_demo:"))
        self.stdout.write(f"  школа:     {school.name}")
        if year:
            self.stdout.write(
                f"  год:       {year.name} ({year.start_date} — {year.end_date})"
            )
        self.stdout.write(
            f"  разметка:  {Term.objects.filter(year__school=school).count()} термов, "
            f"{DayException.objects.filter(year__school=school).count()} исключений"
        )
        self.stdout.write(
            f"  курсы:     {all_courses.count()} — "
            f"{', '.join(all_courses.values_list('name', flat=True)[:4])}…"
        )
        self.stdout.write(
            f"  учителя:   {teachers.count()} — "
            f"{', '.join(teachers.order_by('email').values_list('email', flat=True))}"
        )
        self.stdout.write(
            f"  ученики:   {learners.count()} человек, "
            f"{CourseStudent.objects.filter(removed_at__isnull=True).count()} зачислений, "
            f"{CourseStudent.objects.filter(removed_at__isnull=False).count()} снято, "
            f"{Invitation.objects.filter(kind='student', accepted_at__isnull=True).count()}"
            " ждёт первого входа"
        )
        self.stdout.write(
            f"  записано:  {Slot.objects.filter(lesson__isnull=False).count()} занятий "
            f"из {Slot.objects.filter(date__lt=timezone.localdate(), is_cancelled=False).count()}"
            " прошедших"
        )

        if options["minimal"]:
            self.stdout.write("  расписание и планы: пропущены (--minimal)")
        else:
            self.stdout.write(
                f"  уроки:     {Slot.objects.count()} "
                f"({Slot.objects.filter(is_cancelled=True).count()} отменено, "
                f"{Slot.objects.filter(is_extra=True).count()} дополнительных)"
            )
            self.stdout.write(f"  план:      {lessons} уроков в планах")
            self.stdout.write(
                f"  содержание: {PlanNode.objects.exclude(body='').count()} уроков, "
                f"{Attachment.objects.count()} вложений "
                f"({StoredFile.objects.count()} файлов в хранилище)"
            )
            if not self.storage_ready():
                self.stdout.write(
                    self.style.WARNING(
                        "  R2 не настроен (R2_BUCKET_NAME/R2_ENDPOINT_URL пусты) — "
                        "файлы пропущены, ссылки на месте"
                    )
                )

        if not options["minimal"]:
            self.stdout.write(
                f"  работы:    {Work.objects.count()} "
                f"({Task.objects.count()} задач, {Submission.objects.count()} ответов, "
                f"{Submission.objects.filter(is_correct__isnull=True).count()} не проверено)"
            )
        self.stdout.write(
            f"  библиотека: {PlanTemplate.objects.count()} шаблонов "
            f"({PlanTemplate.objects.filter(is_published=False).count()} черновик)"
        )
        if attached:
            self.stdout.write(self.style.SUCCESS(f"\n  войти как: {attached}"))
        else:
            self.stdout.write(
                "\n  войти под выдуманными учётками нельзя — вход только через "
                "Google. Свяжите свой аккаунт: --email=<ваш адрес>"
            )
