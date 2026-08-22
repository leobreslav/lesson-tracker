"""
Большой правдоподобный набор данных: школа, в которой уже идёт учебный год.

Базовый `seed_demo` показывает **состояния**: курс с полным планом рядом с
курсом без плана, отменённый урок рядом с дополнительным. Он маленький
намеренно — на нём смотрят вёрстку и на нём же стоят браузерные тесты,
которые знают его даты наизусть.

Этот модуль отвечает на другой вопрос: **как оно выглядит в работе**. Пять
учителей, у каждого три курса примерно по сотне уроков, шесть десятков
учеников, год, в котором сегодняшний день уже глубоко внутри, полсотни
работ с ответами и отметками. Сюда ходят за тем, чего маленький набор не
показывает: как читается план на сто строк, не разъезжается ли сводная
таблица на двадцати учениках, сколько запросов уходит на обзор с пятнадцатью
курсами.

Разделены они по той же причине, по которой разделены `seed_demo` и
`bootstrap`: общий помощник рано или поздно поправили бы ради одного из них.
Здесь это особенно верно — у наборов противоположные требования. Маленькому
нужны **фиксированные** даты, иначе браузерные тесты нельзя написать;
большому нужны **живые**, иначе в нём не бывает прошлого, а без прошлого не
видно ни «занятие проведено», ни долгов, ни темпа.

**Год живой.** Он идёт от 1 июля до 1 июля и всегда содержит сегодня:
запустили в августе — позади полтора месяца занятий, запустили в марте —
восемь. Календарный год берётся тот, в котором учебный год начался, поэтому
данные не протухают от того, что их посеяли в другом месяце.

Случайности здесь нет ни одной: всё раскладывается по остатку от деления.
Второй прогон обязан дать то же самое, иначе «у меня не воспроизводится»
станет обычным ответом.
"""

from datetime import date, timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.utils import timezone
from plans.models import PlanNode
from schedule.models import (
    Course,
    CourseAssignment,
    CourseMethodist,
    CourseStudent,
    GradeLevel,
    Slot,
    Subject,
)
from files.models import KIND_LINK, Attachment
from schools.models import Invitation
from schools import services
from works import statements
from works.models import Criterion, StudentWork, Submission, Task, Work
from schedule import services as schedule_services
from works import services as work_services

User = get_user_model()

LANGUAGE = "ru"

# --- сколько чего -------------------------------------------------------------

#: уроков в плане курса. «Примерно»: два курса намеренно выбиваются, потому
#: что интересны как раз они — план, не помещающийся в год, и план вдвое
#: короче расписания
PLAN_SIZE = 100
#: у каждой темы столько уроков, отсюда и число тем
LESSONS_PER_THEME = 10
#: сколько учеников зачисляется в курс: столько, чтобы сводная таблица была
#: таблицей, а не строкой, и чтобы на ней было видно, как она прокручивается
GROUP_SIZE = 16

# --- люди ---------------------------------------------------------------------

# трое сверх тех двоих, что заводит базовый набор: пять учителей — это уже
# «список», в котором надо кого-то искать, а не пара имён
TEACHERS = (
    ("sidorova@example.com", "Елена", "Сидорова"),
    ("kovalev@example.com", "Артём", "Ковалёв"),
    ("nikitina@example.com", "Ирина", "Никитина"),
)

FIRST_NAMES = (
    ("Артём", "m"), ("Дарья", "f"), ("Кирилл", "m"), ("Полина", "f"),
    ("Никита", "m"), ("Софья", "f"), ("Матвей", "m"), ("Алиса", "f"),
    ("Егор", "m"), ("Варвара", "f"), ("Тимур", "m"), ("Ксения", "f"),
    ("Даниил", "m"), ("Милана", "f"), ("Савва", "m"), ("Вероника", "f"),
    ("Лев", "m"), ("Аглая", "f"), ("Марк", "m"), ("Ульяна", "f"),
)

# фамилия и её латиница для адреса: транслитерировать на лету значило бы
# завести здесь ещё одну таблицу соответствий, а нужна она ровно тут
SURNAMES = (
    ("Абрамов", "abramov"), ("Богданов", "bogdanov"), ("Виноградов", "vinogradov"),
    ("Гущин", "gushchin"), ("Дементьев", "dementyev"), ("Ершов", "ershov"),
    ("Жуков", "zhukov"), ("Зимин", "zimin"), ("Ильин", "ilyin"),
    ("Карпов", "karpov"), ("Лазарев", "lazarev"), ("Мельников", "melnikov"),
    ("Наумов", "naumov"), ("Овчинников", "ovchinnikov"), ("Прохоров", "prokhorov"),
    ("Романов", "romanov"), ("Сафонов", "safonov"), ("Тарасов", "tarasov"),
    ("Ушаков", "ushakov"), ("Фомин", "fomin"), ("Хохлов", "khokhlov"),
    ("Цветков", "tsvetkov"), ("Чернов", "chernov"), ("Шестаков", "shestakov"),
    ("Щукин", "shchukin"), ("Юдин", "yudin"), ("Яковлев", "yakovlev"),
    ("Агапов", "agapov"), ("Беляев", "belyaev"), ("Власов", "vlasov"),
)

#: шестьдесят человек: три параллели по два десятка, как в небольшой школе
STUDENT_COUNT = 60

# --- предметы и курсы ---------------------------------------------------------

# у школы уже есть «Алгебра» и «Геометрия»; остальные заводит этот набор
SUBJECTS = ("Физика", "Химия", "Информатика", "Биология")

GRADE_NAMES = {5: "Grade 5", 7: "Grade 7", 8: "Grade 8", 10: "Grade 10", 11: "Grade 11"}

# Курс: имя, предмет, год обучения, учитель и недельная сетка.
#
# Сетка — пары «день недели, номер урока», понедельник это 0. Внутри одного
# учителя пары **не повторяются**: физически он не ведёт два урока разом, и
# набор, в котором это нарушено, выражал бы состояние, которого приложение
# не допускает. Сторожит это `check_week()` ниже — посеянные данные должны
# быть возможными.
#
# Иванова и Петров получают номера с пятого: первые четыре у них заняты
# курсами базового набора.
COURSES = (
    ("Grade 7 Algebra", "Алгебра", 7, "ivanova@example.com",
     ((0, 5), (2, 5), (4, 5))),
    ("Grade 8 Algebra", "Алгебра", 8, "ivanova@example.com",
     ((1, 6), (3, 6), (4, 6))),
    # восьмой, а не седьмой: седьмой у этих двоих занимает дополнительный
    # урок базового набора, и он ставится раньше, чем сюда доходит очередь
    ("Grade 8 Informatics", "Информатика", 8, "ivanova@example.com",
     ((0, 8), (2, 8))),

    ("Grade 10 Algebra", "Алгебра", 10, "petrov@example.com",
     ((0, 5), (2, 5), (4, 5))),
    ("Grade 11 Algebra", "Алгебра", 11, "petrov@example.com",
     ((1, 6), (3, 6), (4, 6))),
    ("Grade 10 Geometry", "Геометрия", 10, "petrov@example.com",
     ((0, 8), (2, 8))),

    ("Grade 7 Physics", "Физика", 7, "sidorova@example.com",
     ((0, 1), (2, 1), (4, 1))),
    ("Grade 8 Physics", "Физика", 8, "sidorova@example.com",
     ((1, 2), (3, 2), (4, 2))),
    ("Grade 9 Physics", "Физика", 9, "sidorova@example.com",
     ((0, 3), (2, 3))),

    ("Grade 8 Chemistry", "Химия", 8, "kovalev@example.com",
     ((0, 1), (2, 1), (4, 1))),
    ("Grade 10 Chemistry", "Химия", 10, "kovalev@example.com",
     ((1, 2), (3, 2), (4, 2))),
    ("Grade 11 Chemistry", "Химия", 11, "kovalev@example.com",
     ((0, 3), (2, 3))),

    ("Grade 5 Biology", "Биология", 5, "nikitina@example.com",
     ((0, 1), (2, 1), (4, 1))),
    ("Grade 7 Biology", "Биология", 7, "nikitina@example.com",
     ((1, 2), (3, 2), (4, 2))),
    ("Grade 11 Biology", "Биология", 11, "nikitina@example.com",
     ((0, 3), (2, 3))),
)

#: курс, который никому не поручили: расписание у него есть, ведущего нет.
#: Это и есть «нагрузку ещё не раздали» — состояние, которое администратор
#: должен видеть на обзоре, а без такого курса счётчик всегда ноль
UNASSIGNED = ("Grade 9 Chemistry", "Химия", 9, ((1, 4), (3, 4)))

#: курсы, которым план задан не «примерно сотней»: один не помещается в год,
#: другой кончится задолго до мая. Ровный набор прячет ровно эти два экрана
PLAN_SIZES = {"Grade 11 Algebra": 170, "Grade 8 Informatics": 45}

#: кто у кого утверждает план: методист — это тот же учитель, и назначают
#: его на курс, а не на человека
METHODISTS = {
    "Grade 7 Algebra": "petrov@example.com",
    "Grade 8 Algebra": "petrov@example.com",
    "Grade 10 Algebra": "ivanova@example.com",
    "Grade 7 Physics": "kovalev@example.com",
    "Grade 8 Physics": "kovalev@example.com",
    "Grade 8 Chemistry": "sidorova@example.com",
}

#: этот план отправлен и ждёт ответа. Методист у него не один на школу, а
#: тот же, что у соседнего курса: на его главной должно быть видно и
#: «На утверждение», и «Под надзором» — два списка, а не один
PENDING_REVIEW = "Grade 8 Algebra"

# --- содержание плана ---------------------------------------------------------

THEMES = {
    "Алгебра": (
        "Числовые выражения", "Тождественные преобразования", "Линейные уравнения",
        "Функции и графики", "Системы уравнений", "Степень с целым показателем",
        "Квадратные уравнения", "Неравенства", "Прогрессии", "Вероятность и статистика",
        "Многочлены", "Рациональные дроби",
    ),
    "Геометрия": (
        "Начальные понятия", "Треугольники", "Параллельные прямые",
        "Соотношения в треугольнике", "Четырёхугольники", "Площади",
        "Подобие фигур", "Окружность", "Векторы", "Метод координат",
        "Правильные многоугольники", "Объёмы тел",
    ),
    "Физика": (
        "Механическое движение", "Взаимодействие тел", "Давление",
        "Работа и мощность", "Тепловые явления", "Электрический ток",
        "Магнитное поле", "Световые явления", "Колебания и волны",
        "Строение атома", "Энергия", "Законы сохранения",
    ),
    "Химия": (
        "Первоначальные понятия", "Кислород и водород", "Вода и растворы",
        "Основные классы соединений", "Периодический закон", "Строение вещества",
        "Электролитическая диссоциация", "Неметаллы", "Металлы",
        "Органические вещества", "Скорость реакций", "Химия и жизнь",
    ),
    "Информатика": (
        "Информация и её измерение", "Системы счисления", "Логика",
        "Алгоритмы", "Программирование", "Обработка данных",
        "Компьютерные сети", "Модели и моделирование", "Базы данных",
        "Графика и мультимедиа", "Безопасность", "Проектная работа",
    ),
    "Биология": (
        "Живые организмы", "Клетка", "Царство растений", "Царство грибов",
        "Царство животных", "Организм человека", "Кровообращение", "Дыхание",
        "Обмен веществ", "Нервная система", "Размножение", "Экосистемы",
    ),
}

# роль урока внутри темы: с ней сотня названий читается как план, а не как
# «Урок 1 … Урок 100»
ROLES = (
    "введение", "основные понятия", "разбор примеров", "решение задач",
    "практикум", "самостоятельная работа", "трудные случаи",
    "задачи повышенной сложности", "повторение", "проверочная работа",
)

OBJECTIVES = "Разобрать {theme}: понять, где это применяется, и научиться считать."
BODY = (
    "1. Проверка домашнего задания.\n"
    "2. Новый материал: {title}.\n"
    "3. Разбор двух задач у доски.\n"
    "4. Самостоятельно — задачи на закрепление.\n\n"
    "Ключевая формула: $S = \\frac{{a + b}}{{2}} \\cdot h$"
)
FORMATIVE = "Короткий опрос в конце урока: три вопроса по теме «{theme}»."
HOMEWORK = "Параграф по теме «{theme}», задачи {first}–{last}."

# --- работы -------------------------------------------------------------------

QUESTIONS = (
    ("Вычислите: $2^{10}$", ("1024",)),
    ("Решите уравнение $3x - 12 = 0$", ("4", "x=4", "x = 4")),
    ("Чему равна площадь квадрата со стороной 7?", ("49",)),
    ("Упростите: $(a + b)^2 - 2ab$", ("a^2+b^2", "a²+b²")),
    ("Сколько будет $\\frac{3}{4} + \\frac{1}{4}$?", ("1",)),
    ("Найдите корень уравнения $x^2 = 81$ (положительный)", ("9",)),
)

MYP_CRITERIA = (
    ("Критерий A: знание и понимание", 8),
    ("Критерий B: исследование", 8),
    ("Критерий C: коммуникация", 8),
    ("Критерий D: применение", 8),
)

COMMENTS = (
    "Разобрался с формулой, но потерял знак в третьей задаче.",
    "Аккуратно и по делу. В четвёртой задаче не хватило пояснения.",
    "Ошибка в первом действии утащила за собой весь ответ.",
    "Отличная работа, придраться не к чему.",
    "Вторая часть не сделана — поговорим на консультации.",
)


# --- живой год ----------------------------------------------------------------


def living_year(today=None) -> tuple[int, date, date]:
    """
    Границы года, внутри которого всегда лежит сегодня.

    От 1 июля до 1 июля, а календарный год берётся тот, в котором учебный
    начался: до июля это прошлый. Иначе набор, посеянный весной, оказался бы
    целиком в будущем — и в нём не было бы ни одного проведённого занятия,
    то есть ровно того, ради чего он и нужен.
    """
    today = today or timezone.localdate()
    start_year = today.year if today.month >= 7 else today.year - 1

    return start_year, date(start_year, 7, 1), date(start_year + 1, 7, 1)


def terms_for(start_year: int) -> list[dict]:
    """
    Четыре четверти, покрывающие год целиком — от июля до июня.

    `onboarding.typical_terms` начинает год первым сентября, и для живого
    года это значит, что июль и август не входят ни в один терм. Занятия в
    них есть, а терма у них нет — состояние законное, но здесь оно было бы
    случайным следствием чужого умолчания, а не решением.
    """
    return [
        {"name": "1 четверть", "start_date": date(start_year, 7, 1),
         "end_date": date(start_year, 10, 25)},
        {"name": "2 четверть", "start_date": date(start_year, 11, 4),
         "end_date": date(start_year, 12, 27)},
        {"name": "3 четверть", "start_date": date(start_year + 1, 1, 9),
         "end_date": date(start_year + 1, 3, 22)},
        {"name": "4 четверть", "start_date": date(start_year + 1, 4, 1),
         "end_date": date(start_year + 1, 6, 30)},
    ]


def check_week() -> None:
    """
    Один учитель — одна пара «день и номер». Проверяется до записи.

    Приложение такого не допускает (`Slot.find_conflict`), а `bulk_create`
    мимо валидации проходит. Набор, в котором учитель ведёт два урока разом,
    выражал бы состояние, недостижимое через интерфейс, — и первый же экран,
    который на это посмотрит, покажет неправду.
    """
    taken = {}
    for name, _, _, email, week in COURSES:
        for pair in week:
            if pair in taken.setdefault(email, {}):
                raise ValueError(
                    f"{email}: {pair} занят курсом «{taken[email][pair]}», "
                    f"а его просит «{name}»"
                )
            taken[email][pair] = name


# --- сборка -------------------------------------------------------------------


def build(school, year, people, subjects, grades, *, log) -> dict:
    """
    Достроить школу до рабочего размера. Идемпотентно, как и базовый набор.

    `people`, `subjects` и `grades` приходят от `seed_demo`: базовый набор
    уже завёл двоих учителей, два предмета и две параллели, и заводить их
    второй раз незачем. Всё остальное строится здесь.
    """
    check_week()

    subjects = {**subjects, **make_subjects(school)}
    grades = {**grades, **make_grades(school)}
    people = {**people, **make_teachers(school)}
    students = make_students(school)

    courses = make_courses(school, year, subjects, grades, people)
    enrol(courses, students)
    plans = make_plans(courses, people)
    slots = make_slots(year, courses)
    record(courses, plans)
    works = make_works(courses, people, students)
    make_reviews(courses, people, plans)
    invite(school, courses, people)
    check_conflicts()

    log(
        f"  крупный набор: курсов {len(courses)}, "
        f"строк плана {sum(len(rows) for rows in plans.values())}, "
        f"занятий {slots}, учеников {len(students)}, работ {works}"
    )

    return {"courses": courses, "students": students}


def check_conflicts() -> None:
    """
    После сборки: ни один учитель не стоит в двух местах одновременно.

    `check_week()` смотрит на таблицу курсов, но этого мало — внеплановые
    занятия ставятся поверх неё, и базовый набор успевает поставить свои
    до того, как сюда дойдёт очередь. Проверка стоит в конце и по базе,
    потому что именно база и есть то, на что потом посмотрят экраны.

    Падает, а не предупреждает: набор, выражающий невозможное состояние,
    хуже отсутствия набора — по нему будут судить о правильности экранов.
    """
    from django.db.models import Count

    clashes = (
        Slot.objects.filter(
            is_cancelled=False, course__assignments__teacher__isnull=False
        )
        .values("course__assignments__teacher", "date", "lesson_number")
        .annotate(times=Count("id"))
        .filter(times__gt=1)
        .order_by("date", "lesson_number")
    )
    first = clashes.first()
    if first is not None:
        raise ValueError(
            "посеяно невозможное расписание: учитель "
            f"{first['course__assignments__teacher']} стоит "
            f"{first['times']} раза в {first['date']}, урок "
            f"{first['lesson_number']}"
        )


def make_subjects(school) -> dict:
    return {
        name: Subject.objects.get_or_create(school=school, name=name)[0]
        for name in SUBJECTS
    }


def make_grades(school) -> dict:
    made = {}
    for level, name in GRADE_NAMES.items():
        made[level] = GradeLevel.objects.get_or_create(
            school=school, level=level, defaults={"name": name}
        )[0]
    return made


def person(school, email, first, last, *, student=False):
    """Учётка с подтверждённым адресом: без него вход через Google не найдёт её."""
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            "first_name": first,
            "last_name": last,
            "school": school,
            "language": LANGUAGE,
            "kind": User.Kind.STUDENT if student else User.Kind.TEACHER,
            # уже входили: «ещё не входил» в этом наборе принадлежит троим
            # приглашённым, и на остальных пометка стоять не должна
            "last_login": timezone.now(),
        },
    )
    EmailAddress.objects.get_or_create(
        user=user, email=user.email, defaults={"verified": True, "primary": True}
    )
    return user


def make_teachers(school) -> dict:
    return {
        email: person(school, email, first, last)
        for email, first, last in TEACHERS
    }


def make_students(school) -> list:
    """
    Шестьдесят учеников. Имена собираются из двух списков по остатку.

    Женская фамилия получает «а» — мелочь, но список, в котором Дарья
    Абрамов, читается как сгенерированный, а на такой набор перестают
    смотреть всерьёз.
    """
    made = []
    for index in range(STUDENT_COUNT):
        first, sex = FIRST_NAMES[index % len(FIRST_NAMES)]
        surname, latin = SURNAMES[index % len(SURNAMES)]
        last = f"{surname}а" if sex == "f" else surname
        email = f"{latin}{index + 1}@example.com"
        made.append(person(school, email, first, last, student=True))

    return made


def make_courses(school, year, subjects, grades, people) -> dict:
    courses = {}
    for name, subject, level, email, _ in COURSES:
        course, _ = Course.objects.get_or_create(
            school=school,
            year=year,
            name=name,
            defaults={"subject": subjects[subject], "grade": grades[level]},
        )
        CourseAssignment.objects.get_or_create(course=course, teacher=people[email])

        reviewer = METHODISTS.get(name)
        if reviewer:
            CourseMethodist.objects.get_or_create(
                course=course,
                user=people[reviewer],
                defaults={"assigned_by": people[email]},
            )
        courses[name] = course

    name, subject, level, _ = UNASSIGNED
    courses[name] = Course.objects.get_or_create(
        school=school,
        year=year,
        name=name,
        defaults={"subject": subjects[subject], "grade": grades[level]},
    )[0]

    return courses


def enrol(courses, students) -> None:
    """
    Состав курсов. Группы пересекаются: ученик учится у нескольких учителей.

    Непересекающиеся группы — самая незаметная неправда в демо-данных: на
    них никогда не видно, что у ученика несколько курсов, а именно так
    выглядит его главная.
    """
    for index, (name, course) in enumerate(courses.items()):
        # окно сдвигается на треть группы, поэтому соседние курсы делят
        # учеников, а дальние — нет
        start = (index * GROUP_SIZE // 3) % len(students)
        group = [students[(start + step) % len(students)] for step in range(GROUP_SIZE)]

        for student in group:
            CourseStudent.objects.get_or_create(course=course, student=student)

        # один снятый на каждый третий курс: строка остаётся, работать он
        # больше не может, а сделанное видит
        if index % 3 == 0:
            leaving = CourseStudent.objects.filter(
                course=course, student=group[-1]
            ).first()
            if leaving and leaving.removed_at is None:
                leaving.removed_at = timezone.now()
                leaving.save(update_fields=["removed_at"])


def plan_rows(subject: str, level: int, size: int) -> list[tuple[str, str]]:
    """
    План курса как плоский список «тема, урок» — сотня строк из двух банков.

    Темы сдвигаются по году обучения: два курса одного предмета иначе
    получили бы дословно одинаковый план, и на них не было бы видно, что
    планы вообще разные.
    """
    themes = THEMES[subject]
    shift = level % len(themes)

    rows = []
    for index in range(size):
        theme = themes[(index // LESSONS_PER_THEME + shift) % len(themes)]
        role = ROLES[index % len(ROLES)]
        rows.append((theme, f"{theme}: {role}"))

    return rows


def make_plans(courses, people) -> dict:
    """Дерево из тем и уроков, у каждого четвёртого — содержание."""
    made = {}

    for name, subject, level, email, _ in COURSES:
        course = courses[name]
        if PlanNode.objects.filter(course=course).exists():
            made[name] = list(
                PlanNode.objects.filter(course=course, is_section=False)
            )
            continue

        rows = plan_rows(subject, level, PLAN_SIZES.get(name, PLAN_SIZE))

        sections = {}
        lessons = []
        for theme, title in rows:
            if theme not in sections:
                sections[theme] = PlanNode.objects.create(
                    course=course,
                    title=theme,
                    is_section=True,
                    position=len(sections),
                )
            parent = sections[theme]
            index = len(lessons)
            written = index % 4 == 0
            lessons.append(
                PlanNode(
                    course=course,
                    parent=parent,
                    title=title,
                    position=index % LESSONS_PER_THEME,
                    objectives=OBJECTIVES.format(theme=theme) if written else "",
                    body=BODY.format(title=title) if written else "",
                    formative=FORMATIVE.format(theme=theme) if written else "",
                    homework=(
                        HOMEWORK.format(theme=theme, first=index + 1, last=index + 6)
                        if written
                        else ""
                    ),
                )
            )

        PlanNode.objects.bulk_create(lessons)
        made[name] = list(
            PlanNode.objects.filter(course=course, is_section=False).order_by(
                "parent__position", "position", "id"
            )
        )

    return made


def make_slots(year, courses) -> int:
    """
    Год занятий по недельной сетке, плюс отмены и дополнительные.

    Учебные дни спрашиваются у календаря, а не угадываются: тот же
    `build_days`, которым рисует интерфейс, — иначе посеянное расписание
    расходилось бы с тем, что видно на экране.
    """
    study_days = [day.date for day in year.build_days() if day.is_study]
    today = timezone.localdate()
    total = 0

    unassigned = UNASSIGNED[0]
    schedules = [*COURSES, (unassigned, None, None, None, UNASSIGNED[3])]
    make_ups = []

    for order, (name, _, _, _, week) in enumerate(schedules):
        course = courses[name]
        if Slot.objects.filter(course=course).exists():
            total += Slot.objects.filter(course=course).count()
            continue

        rows = [
            Slot(year=year, course=course, date=day, lesson_number=number)
            for day in study_days
            for weekday, number in week
            if day.weekday() == weekday
        ]
        Slot.objects.bulk_create(rows)
        total += len(rows)

        # срывы и компенсации: год без них выглядит идеально ровным, а
        # именно по ним администрация и читает календарную ось
        past = list(
            Slot.objects.filter(course=course, date__lt=today).order_by("date")
        )
        for shift, reason in ((3, "Болезнь учителя"), (11, "Карантин"), (19, "Актовый день")):
            if len(past) > shift + order:
                slot = past[shift + order]
                slot.is_cancelled = True
                slot.reason = reason
                slot.save(update_fields=["is_cancelled", "reason"])

        if past:
            make_ups.append((order, course, past[0].date))

    total += place_make_ups(year, study_days, make_ups)
    return total


def place_make_ups(year, study_days, make_ups) -> int:
    """
    Отработки взамен сорванных дней — **после** того, как разложена вся
    сетка.

    Порядок здесь не косметика: номер спрашивается у `free_number`, а тот
    смотрит в базу. Пока отработка ставилась в том же проходе, что и сетка,
    она видела расписание только тех курсов, до которых цикл уже дошёл, — и
    занимала час, который следующий курс того же учителя занимал сеткой.
    Набор падал на собственной проверке `check_conflicts`, и правильно.

    День — учебный, а не «ближайшая суббота», как было сперва: субботу
    получали **все девятнадцать курсов сразу**, и набор показывал шестнадцать
    занятий в один неучебный день. Одному курсу суббота оставлена намеренно:
    отработка в выходной — настоящее состояние с настоящим предупреждением,
    и увидеть его надо, просто не в шестнадцати экземплярах.
    """
    study = set(study_days)
    added = 0

    for order, course, first in make_ups:
        make_up = first + timedelta(days=(5 - first.weekday()) % 7)
        if order % 19:
            while make_up not in study and make_up <= year.end_date:
                make_up += timedelta(days=1)

        lead = CourseAssignment.objects.filter(course=course).first()
        number = schedule_services.free_number(
            teacher_id=lead.teacher_id if lead else None,
            year=year,
            day=make_up,
            start=8,
        )
        if number is None:
            continue

        Slot.objects.get_or_create(
            year=year,
            course=course,
            date=make_up,
            lesson_number=number,
            defaults={"is_extra": True, "reason": "Отработка"},
        )
        added += 1

    return added


def record(courses, plans) -> None:
    """
    Проставить связь «занятие проведено» на прошедших часах.

    Без неё в наборе нет ни подтверждённых тем, ни долгов, ни разложения
    резерва — то есть половины того, ради чего он и нужен. Связи ставятся
    по порядку: i-й прошедший час получает i-й урок плана, ровно так, как их
    поставил бы учитель, нажимавший кнопку каждый день.

    Три состояния, и все три настоящие: курс, где закрыто всё; курс, где
    последние занятия ещё не закрыты (долги); и курс, где кнопку не нажимали
    ни разу — такой ничего не должен, и это тоже надо уметь показать.
    """
    today = timezone.localdate()

    for order, (name, _, _, _, _) in enumerate(COURSES):
        # каждый третий курс живёт без связей вовсе
        if order % 3 == 2:
            continue

        course = courses[name]
        past = list(
            Slot.objects.filter(
                course=course, date__lt=today, is_cancelled=False
            ).order_by("date", "lesson_number")
        )
        # у каждого второго курса хвост остаётся незакрытым: это и есть долг
        gap = 3 if order % 2 else 0
        # но не короче того, что уже записано: между посевами дни проходят, и
        # часы, записанные в прошлый раз, могли уехать за эту границу. Дырку
        # перед ними строгая очередь потом не простит
        recorded = [i for i, slot in enumerate(past) if slot.lesson_id]
        closing = past[: max(len(past) - gap, (recorded[-1] + 1) if recorded else 0)]

        # Записи **дописываются**, а не ставятся один раз: набор
        # идемпотентен и его сеют повторно, а между посевами проходят дни —
        # вчерашнее будущее становится прошлым. Прежний ранний выход «у
        # курса уже есть записи» оставлял такие часы незакрытыми посреди
        # закрытого хвоста, а порядок записи теперь строгий, и дырка в нём
        # держит всё, что после неё.
        free = [row for row in plans[name] if row.pk not in {
            slot.lesson_id for slot in closing if slot.lesson_id
        }]
        touched = []
        for slot in closing:
            if slot.lesson_id:
                continue
            if not free:
                break
            slot.lesson = free.pop(0)
            touched.append(slot)

        Slot.objects.bulk_update(touched, ["lesson"])


def invite(school, courses, people) -> None:
    """
    Несколько человек, которые ещё ни разу не входили.

    Учётки у них настоящие и с первой минуты — приглашение заводит их
    сразу, — а отличает их только пустой `last_login`. Один записан на два
    курса: на одном не видно, что человек бывает не в одном месте.

    Состояние это нужно в наборе именно потому, что на ровном списке
    вошедших экраны выглядят одинаково правильно.
    """
    admin = next(
        (person for person in people.values() if person.is_school_admin), None
    )
    waiting = (
        ("novikova@example.com", "Алина Новикова", ("Grade 7 Physics",)),
        ("gromov@example.com", "Игорь Громов", ("Grade 8 Chemistry", "Grade 8 Physics")),
        ("panteleev@example.com", "Роман Пантелеев", ("Grade 5 Biology",)),
    )

    for email, name, names in waiting:
        Invitation.objects.get_or_create(
            school=school,
            email=email,
            defaults={"kind": "student", "name": name, "created_by": admin},
        )
        if User.objects.filter(email=email).exists():
            continue

        person = services.provision(school, email, kind="student", name=name)
        for item in names:
            services.enrol(person, courses[item], by=admin)


def make_reviews(courses, people, plans) -> None:
    """
    Утверждённые эталоны, правки поверх них и один висящий запрос.

    Без эталона половина обзора — приглашение «отправить на утверждение», и
    ни расхождения, ни разложения резерва на нём не увидеть. А эталон,
    совпадающий с планом строка в строку, показывает нули — тоже не то,
    ради чего сюда смотрят. Поэтому после утверждения план правится: пара
    дописанных уроков и один выброшенный, как оно и бывает к ноябрю.

    Один курс остаётся с **неотвеченным** запросом: у методиста должно быть
    что подписать, иначе его половина главной пуста.
    """
    from plans import approval

    for name, reviewer_email in METHODISTS.items():
        course = courses[name]
        if course.plan_baselines.exists():
            continue

        teacher = CourseAssignment.objects.get(course=course).teacher
        reviewer = people[reviewer_email]
        baseline = approval.submit(course, reviewer, teacher)

        if name == PENDING_REVIEW:
            continue

        approval.approve(baseline, reviewer)

        # план разошёлся с принятым: две строки дописаны, одна выброшена —
        # именно это и читает плашка «расхождение с эталоном»
        lessons = plans[name]
        tail = lessons[-1].parent
        PlanNode.objects.bulk_create(
            PlanNode(
                course=course,
                parent=tail,
                title=f"{tail.title}: доработка после каникул {step + 1}",
                position=LESSONS_PER_THEME + step,
            )
            for step in range(2)
        )
        PlanNode.objects.filter(pk=lessons[len(lessons) // 2].pk).delete()


def make_works(courses, people, students) -> int:
    """
    Пять работ на курс: две закрытые, открытая, будущая и бумажная.

    Состояния перечислены, а не насыпаны случайно: работа видна ученику
    ровно тогда, когда открыто её окно, и на ровном наборе из одних
    открытых не видно ни «запланирована», ни «закрыта».
    """
    now = timezone.now()
    made = 0

    for order, (name, _, _, email, _) in enumerate(COURSES):
        course = courses[name]
        if Work.objects.filter(course=course).exists():
            continue

        teacher = people[email]
        group = [
            row.student
            for row in CourseStudent.objects.filter(course=course).select_related(
                "student"
            )
        ]

        windows = (
            ("Проверочная: начало года", -60, -59, True, True),
            ("Контрольная за четверть", -20, -19, True, True),
            ("Практика: разбор задач", -1, 5, True, False),
            ("Домашняя работа на неделю", 4, 11, False, False),
        )
        for title, opens, closes, answered, checked in windows:
            work = Work.objects.create(
                course=course,
                created_by=teacher,
                title=f"{title}",
                opens_at=now + timedelta(days=opens),
                closes_at=now + timedelta(days=closes),
                attempts=2,
            )
            made += 1
            # Условие живёт в банке, и заводится оно тем же путём, что и в
            # приложении: `bulk_create` тут не годится — ячейке нужна ссылка,
            # а ссылке нужен объект.
            tasks = [
                ask(work, teacher, position, question, answers)
                for position, (question, answers) in enumerate(QUESTIONS[:5])
            ]
            if answered:
                answer(list(work.tasks.order_by("position")), group, teacher, now,
                       checked=checked, salt=order)

        made += paper_work(course, teacher, group, now, salt=order)

    return made


def answer(tasks, students, teacher, now, *, checked, salt) -> None:
    """
    Ответы в работе — по списку состояний клетки, а не наугад.

    Сводная таблица тем и живёт, что в ней видно **разное**: пустая клетка,
    ответ без отметки, верный, неверный и переделанный после проверки.
    Ровный набор из одних галочек выглядит правильно на любой вёрстке, а
    разъезжается она как раз на смеси.
    """
    if not tasks or not students:
        return

    pattern = ("correct", "wrong", "unchecked", "skip", "correct", "redone", "correct")
    rows = []
    redone = []
    judged = []

    for index, student in enumerate(students):
        for position, task in enumerate(tasks):
            state = pattern[(index + position + salt) % len(pattern)]
            if state == "skip":
                continue
            if not checked and state in ("correct", "wrong"):
                state = "unchecked"

            right = (statements.answers_of(task) or ["мой ответ"])[0]
            rows.append(
                Submission(
                    task=task,
                    student=student,
                    answer=right if state in ("correct", "redone") else "не знаю",
                    checked_at=None if state == "unchecked" else now - timedelta(days=1),
                    checked_by=None if state == "unchecked" else teacher,
                )
            )
            if state != "unchecked":
                judged.append((len(rows) - 1, task, student, state))
            if state == "redone":
                redone.append((task, student, right))

    made = Submission.objects.bulk_create(rows)

    # Баллы ставятся после вставки и по одному: оценка живёт не на отправке,
    # а на паре «ученик и вопрос», и ставит её тот же путь, что у учителя.
    # Пакетно тут не выйдет — у каждой оценки своя строка «работа ученика».
    from works.services import check_answer

    for index, task, student, state in judged:
        check_answer(
            made[index], value=task.maximum if state == "correct" else 0, by=teacher
        )

    # переделанный ответ — вторая строка журнала: балл остался за прошлой, а
    # клетка показывает, что пришло новое и надо посмотреть
    Submission.objects.bulk_create(
        Submission(task=task, student=student, answer=right)
        for task, student, right in redone
    )


def ask(work, teacher, position, question, answers):
    """Ячейка вместе с условием: своего текста у ячейки нет."""
    task = Task.objects.create(work=work, position=position)
    statements.say(task, text=question, answers=list(answers), user=teacher)
    return task


def paper_work(course, teacher, group, now, *, salt) -> int:
    """
    Контрольная на бумаге: задач и отправок нет, зато есть оценки.

    Шкала настоящая — четыре критерия MYP: обычная отметка одним числом не
    показала бы, как читается рубрика, а именно она в этих школах и стоит.
    """
    work = Work.objects.create(
        course=course,
        created_by=teacher,
        title="Контрольная на бумаге",
        opens_at=now - timedelta(days=35),
        closes_at=now - timedelta(days=34),
        on_paper=True,
    )
    criteria = Criterion.objects.bulk_create(
        Criterion(work=work, position=position, name=name, maximum=maximum)
        for position, (name, maximum) in enumerate(MYP_CRITERIA)
    )
    criteria = list(work.criteria.order_by("position"))

    for index, student in enumerate(group):
        # двое в группе работу не писали: пустая строка в таблице — тоже
        # состояние, и без неё не видно, считает ли сводка отсутствующих
        if (index + salt) % 8 == 3:
            continue

        row, _ = StudentWork.objects.get_or_create(work=work, student=student)

        # скан работы. Ссылкой, а не файлом: файлов пришлось бы залить две
        # сотни, а у стенда браузерных тестов ключей R2 нет вовсе — экран же
        # проверяет, что у ученика есть **своя** бумага и не видно чужой,
        # и для этого вид вложения безразличен
        if (index + salt) % 4 == 1:
            Attachment.objects.get_or_create(
                student_work=row,
                kind=KIND_LINK,
                defaults={
                    "url": f"https://scans.example.com/{work.pk}/{student.pk}.pdf",
                    "title": f"{student.last_name}.pdf",
                },
            )

        work_services.grade(
            work,
            student,
            marks={
                criterion.pk: (index + position + salt) % criterion.maximum + 1
                for position, criterion in enumerate(criteria)
            },
            comment=COMMENTS[(index + salt) % len(COMMENTS)],
            by=teacher,
        )

    return 1
