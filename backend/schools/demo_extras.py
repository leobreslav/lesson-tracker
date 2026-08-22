"""
Досев: по живому случаю в каждую модель, которой иначе не видно.

Базовый набор строит то, ради чего его смотрят глазами, — школу, год, курсы,
план, расписание, работы. Но два десятка моделей после него оставались
**пустыми**: эталоны плана, снимки, журнал занятия, оценки, разговоры,
предложения, траты на чтение сканов. Пустая модель значит, что её экран
никто ни разу не видел с данными, а её запрос ни разу не выполнялся на
непустой выборке, — и первым это обнаруживает не разработчик, а учитель.

Правило тут одно и оно же объясняет, почему модуль отдельный: **каждый случай
заводится тем же путём, каким его заводит приложение**. Не `objects.create`
мимо правил, а сервис: оценка через `works.services.grade`, эталон через
`plans.approval`, снимок через `plans.history`. Посев, пишущий в обход,
выражает состояние, которого в жизни не бывает, — и тесты на нём зелёные, а
интерфейс падает.

Случайности здесь нет: всё раскладывается по остатку от деления, и второй
прогон даёт то же самое.
"""

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone


def build(school, courses, people, students, *, log=print):
    """Досеять всё, чего не хватает. Идемпотентно: повторный посев не двоит."""
    teacher = people["ivanova@example.com"]
    admin = people["director@example.com"]
    course = courses["Grade 6 Algebra"]
    # Эталон и методист заводятся на **другом** курсе, и это не каприз:
    # «Grade 6 Algebra» — курс, на котором стоят браузерные тесты
    # утверждения плана, и посеянный эталон менял бы им начальное состояние.
    # Набору всё равно, на каком курсе показать утверждённый план; тестам —
    # нет.
    supervised = courses["Grade 9 Algebra"]

    made = []
    made.append(_grading(school, courses, teacher))
    made.append(_marks(course, teacher, students))
    made.append(_mixed(course))
    made.append(_talk(course, teacher, students))
    made.append(_attendance(course, teacher, students))
    methodist = people["petrov@example.com"]
    made.append(_methodist_and_baseline(supervised, methodist, admin))
    made.append(_history(course, teacher))
    made.append(_scan_page(course, teacher))
    made.append(_spending(school, teacher, course))
    made.append(_bank_variety(school, teacher, admin, course))
    made.append(_feedback(school, teacher, students))

    log("  досев:     " + ", ".join(one for one in made if one))


def _paper(works):
    """
    Работа, которую писали на бумаге: ячейки есть, ни одна не принимает ответы.

    Флага у работы больше нет, и находить её приходится так же, как это
    делает экран, — по самим ячейкам. Это не обход правила, а его следствие:
    «бумажная» перестала быть свойством работы и стала суммой свойств её
    вопросов.
    """
    return (
        works.filter(tasks__isnull=False)
        .exclude(tasks__open_for_answers=True)
        .distinct()
        .first()
    )


def _grading(school, courses, teacher):
    """Системы оценивания и шкала у бумажной работы."""
    from works import grading, services
    from works.models import Work

    grading.add_typical(school, "ru")
    paper = _paper(Work.objects.filter(course__school=school))
    if paper is None:
        paper = Work.objects.create(
            course=courses["Grade 6 Algebra"],
            created_by=teacher,
            title="Работа на бумаге",
            opens_at=timezone.now() - timedelta(days=2),
            closes_at=timezone.now() + timedelta(days=5),
        )
    if not paper.tasks.exists():
        # ячейки у бумажной работы есть — это `Q1…Q3`, просто без условий и
        # закрытые для ответов: лист лежит у ученика на парте
        services.set_questions(
            paper,
            [
                {"maximum": 5, "open_for_answers": False},
                {"maximum": 5, "open_for_answers": False},
                {"maximum": 10, "open_for_answers": False},
            ],
            by=teacher,
        )
    if paper.grading_system_id is None:
        paper.grading_system = school.grading_systems.filter(kind="points").first()
        paper.save(update_fields=["grading_system"])

    # Вторая работа — по критериям MYP: у оценивания две оси, и на одной
    # только шкале второй не видно вовсе.
    myp, _ = Work.objects.get_or_create(
        course=courses["Grade 9 Algebra"],
        title="Исследование по критериям",
        defaults={
            "created_by": teacher,
            "opens_at": timezone.now() - timedelta(days=3),
            "closes_at": timezone.now() + timedelta(days=10),
            "is_summative": True,
            "grading_system": school.grading_systems.filter(kind="levels").first(),
        },
    )
    if not myp.criteria.exists():
        services.set_scale(
            myp,
            [
                {"name": "Критерий A", "maximum": 8},
                {"name": "Критерий D", "maximum": 8},
            ],
        )
    return "системы оценивания и шкала MYP"


def _marks(course, teacher, students):
    """
    Оценки, строка «работа и ученик» и журнал правок.

    Через `services.grade`, а не строкой в базе: правка оценки — событие, и
    заводит его только этот путь.
    """
    from works import services
    from works.models import Work

    paper = _paper(Work.objects.filter(course=course))
    if paper is None or not paper.tasks.exists():
        return ""

    cells = list(paper.tasks.order_by("position"))
    active = [row.student for row in course.students.filter(removed_at=None)][:3]
    for number, student in enumerate(active):
        services.grade(
            paper,
            student,
            scores={
                cell.pk: (number + index) % (cell.maximum + 1)
                for index, cell in enumerate(cells)
            },
            comment="Разобрать вторую задачу" if number == 0 else "",
            by=teacher,
        )

    # правка оценки: у первого ученика балл меняется — так в журнале правок
    # появляется событие, а не только значение
    if active:
        services.grade(
            paper, active[0], scores={cells[0].pk: cells[0].maximum}, by=teacher
        )
    return "оценки и журнал правок"


def _mixed(course):
    """
    Работа, где часть вопросов решают онлайн, а последний — на листе.

    Ради неё флаг работы и снимали: «Q1 и Q2 решайте онлайн, Q3 сдайте на
    бумаге» — обычная контрольная, и выразить её было нечем. Пока такой
    работы нет в посеве, экран смешанного случая никто ни разу не видел
    глазами — а он выглядит иначе, чем оба крайних.
    """
    from works.models import Task, Work

    already = Task.objects.filter(
        work__course=course, open_for_answers=False, problem__isnull=False
    ).exists()
    if already:
        return ""

    work = (
        Work.objects.filter(course=course, tasks__open_for_answers=True)
        .annotate(cells=Count("tasks"))
        .filter(cells__gte=2)
        .distinct()
        .first()
    )
    if work is None:
        return ""

    last = work.tasks.order_by("position").last()
    last.open_for_answers = False
    last.save(update_fields=["open_for_answers"])
    return "смешанная работа"


def _talk(course, teacher, students):
    """Разговор о задаче: ученик спросил, учитель ответил."""
    from works import threads
    from works.models import Work

    # работа **с задачами**: домашняя «на каникулы» их не имеет, и первая
    # попавшаяся онлайновая оказалась именно ею
    work = (
        Work.objects.filter(course=course, tasks__open_for_answers=True)
        .distinct()
        .first()
    )
    task = work.tasks.first() if work else None
    if task is None:
        return ""

    student = course.students.filter(removed_at=None).first()
    if student is None:
        return ""

    thread = threads.open_thread(task, student.student_id)
    if not thread.messages.exists():
        threads.say(
            task,
            student_id=student.student_id,
            author=student.student,
            text="А тут точно нужно раскрывать скобки?",
        )
        threads.say(
            task,
            student_id=student.student_id,
            author=teacher,
            text="Да, иначе не сократится. Посмотрите пример на уроке.",
        )
    return "разговор о задаче"


def _attendance(course, teacher, students):
    """
    Журнал занятия: три состояния, а не сплошное «был».
    """
    from schedule.models import Attendance, Slot

    slots = Slot.objects.filter(course=course, is_cancelled=False)
    slot = slots.order_by("date").first()
    if slot is None or Attendance.objects.filter(slot=slot).exists():
        return ""

    состояния = ["present", "absent", "late"]
    for number, enrolment in enumerate(course.students.filter(removed_at=None)[:6]):
        Attendance.objects.create(
            slot=slot,
            student=enrolment.student,
            status=состояния[number % len(состояния)],
            note="по заявлению" if number % 3 == 1 else "",
            marked_by=teacher,
        )
    return "журнал занятия"


def _methodist_and_baseline(course, teacher, admin):
    """
    Методист, отправленный план и утверждённый эталон.

    Эталон снимается **в момент утверждения**, поэтому и заводится он
    единственным законным путём — через `approval`.
    """
    from plans import approval
    from schedule.models import CourseMethodist

    CourseMethodist.objects.get_or_create(course=course, user=admin)
    if course.plan_baselines.exists():
        return ""

    baseline = approval.submit(course, admin, teacher)
    approval.approve(baseline, admin)
    return "методист и эталон"


def _history(course, teacher):
    """
    Снимок плана: он снимается перед каждой правкой, и достаточно её сделать.

    Правим содержание строки, у которой есть вложения, — тогда в снимок
    попадает и ссылка на файл, то есть заполняется `PlanSnapshotFile`.
    """
    from plans import history
    from plans.models import PlanNode

    if course.snapshots.exists():
        return ""

    row = (
        PlanNode.objects.filter(course=course, is_section=False)
        .filter(attachments__isnull=False)
        .distinct()
        .first()
        or PlanNode.objects.filter(course=course, is_section=False).first()
    )
    if row is None:
        return ""

    history.take(course, teacher, "edit", row.title)
    row.title = f"{row.title}"
    row.save(update_fields=["title"])
    return "снимок плана"


def _scan_page(course, teacher):
    """
    Прочитанная страница пачки — без файла: разбор кладёт её ещё до нарезки.
    """
    from works.models import ScanPage, Work

    paper = _paper(Work.objects.filter(course=course))
    if paper is None or ScanPage.objects.filter(work=paper).exists():
        return ""

    students = [row.student for row in course.students.filter(removed_at=None)][:2]
    for number, student in enumerate(students):
        ScanPage.objects.create(
            work=paper,
            index=number,
            fingerprint=f"demo-{number}",
            first_name=student.first_name,
            surname=student.last_name,
            cells=[number, None, 3] + [None] * 13,
            ours=True,
            student=student,
            decided_by_human=number == 1,
        )
    return "страницы пачки"


def _spending(school, teacher, course):
    """
    Трата на чтение скана: журнал есть, а вызова модели не было и не нужно.
    """
    from vision.models import AiSpend

    if AiSpend.objects.filter(school=school).exists():
        return ""

    from works.models import Work

    work = _paper(Work.objects.filter(course=course))
    for number in range(3):
        AiSpend.objects.create(
            school=school,
            user=teacher,
            work=work,
            purpose="header" if number else "questions",
            model="claude-haiku-4-5-20251001",
            input_tokens=1500 + number * 100,
            output_tokens=120 + number * 10,
            cost_micros=2300 + number * 400,
        )
    return "траты на чтение"


def _feedback(school, teacher, students):
    """
    Обращения к разработчику: неразобранное и разобранное.

    Раздел этот видит один человек на всю установку, и увидеть его с данными
    иначе негде: пишут в него из интерфейса, а посев его не заводил. Пустая
    страница обращений выглядит одинаково и когда всё разобрано, и когда
    запрос молча отдаёт не то.

    Два состояния, а не одно, ровно поэтому: список по умолчанию показывает
    ждущее, и вкладка «разобранные» без единой строки не отвечает на вопрос,
    работает ли она.

    Пишут оба вида пользователей — учитель и ученик, — потому что это и есть
    главное решение раздела: ученик видит те же поломки, а сказать о них ему
    было нечем.
    """
    from feedback.models import Message

    if Message.objects.exists():
        return ""

    Message.objects.create(
        kind=Message.Kind.BUG,
        text="В расписании неделя листается стрелками, а с клавиатуры нет.",
        author=teacher,
        school=school,
        page="/schedule",
    )
    Message.objects.create(
        kind=Message.Kind.IDEA,
        text="Хорошо бы видеть дедлайн работы прямо в списке курсов.",
        author=students[0],
        school=school,
        page="/",
    )
    # разобранное помечается так же, как это делает вьюха: отметкой времени
    Message.objects.create(
        kind=Message.Kind.IDEA,
        text="Пусть журнал занятия открывается по клику на самом уроке.",
        author=teacher,
        school=school,
        page="/lesson/1",
        handled_at=timezone.now() - timedelta(days=3),
    )
    return "обращения к разработчику"


def _bank_variety(school, teacher, admin, course):
    """
    Задачник во всех формах: три уровня владения, сюжет с пунктами, чистый
    номер, аналоги, копия, снятая задача, свой поиск и предложения.

    Формы тут не для красоты: на ровном наборе экраны выглядят одинаково
    правильно, а расходятся они как раз на них.
    """
    from bank import proposals, services
    from bank.models import (
        Entry,
        Problem,
        Proposal,
        Solution,
        SolutionTag,
        Source,
        Tag,
        Topic,
    )

    if Source.objects.filter(school__isnull=True).exists():
        return ""

    algebra = Tag.objects.get(name="алгебра")
    vieta = Tag.objects.get(name="теорема Виета")
    swap = Tag.objects.get(name="замена переменной")

    # системная книга: её видят все школы, правит суперпользователь
    common = Source.objects.create(
        title="Сборник задач, общий", author="Мордкович", subject=algebra
    )
    services.add_problems(
        common,
        section=None,
        text=(
            "3\tДан треугольник ABC со сторонами 3, 4, 5.\n"
            "  а)\tНайдите его площадь.\n"
            "  б)\tНайдите радиус вписанной окружности.\n"
            "15\n"
            "  а)\t$x^2 = 4$\n"
            "  б)\t$x^2 = 9$\n"
            "22\tДокажите, что сумма углов треугольника равна $180°$."
        ),
        user=admin,
    )

    # школьная книга: видит вся школа, правят администраторы
    ours = Source.objects.create(
        title="Наш сборник на четверть",
        school=school,
        subject=algebra,
        created_by=admin,
    )
    services.add_problems(
        ours,
        section=None,
        text="1\tНайдите значение функции в точке.\n2\tПостройте вектор суммы.",
        user=admin,
    )

    # семья аналогов: та же задача с другими числами
    first = Problem.objects.filter(text__startswith="$x^2 = 4$").first()
    second = Problem.objects.filter(text__startswith="$x^2 = 9$").first()
    if first and second:
        from bank import copying

        copying.join_family(first, second, user=admin)

    # своя копия чужой задачи — с пометкой, откуда она
    доказать = Problem.objects.filter(text__startswith="Докажите, что сумма").first()
    if доказать:
        мой = Source.objects.filter(owner=teacher).first()
        if мой:
            copying.copy_problem(доказать, into=мой, mode="fork", user=teacher)

    # снятая задача: из поиска ушла, из работ — нет
    Problem.objects.create(
        text="Устаревшая задача про логарифмы",
        school=school,
        owner=teacher,
        created_by=teacher,
        retired=True,
    )

    # Разбор с тегами **обеих сторон**: «через Виета» и «без замены
    # переменной». Отрицание — единственная форма связи, которой иначе в базе
    # нет вовсе, а поиск «без производной» стоит на ней; поэтому знак
    # доставляется отдельно и на тот разбор, который уже есть. Пока досев
    # пропускал готовый разбор целиком, `avoids` не появлялся никогда.
    начало = "Решите уравнение $x^2"
    квадратное = Problem.objects.filter(text__startswith=начало).first()
    if квадратное:
        разбор = квадратное.solutions.filter(title="По теореме Виета").first()
        if разбор is None:
            разбор = Solution.objects.create(
                problem=квадратное,
                title="По теореме Виета",
                text="Сумма корней 5, произведение 6.",
                school=school,
                owner=teacher,
                created_by=teacher,
            )
            разбор.links.create(tag=vieta, side=SolutionTag.USES)
        разбор.links.get_or_create(tag=swap, side=SolutionTag.AVOIDS)

    # сохранённый поиск: это тема верхнего уровня, своя
    Topic.objects.get_or_create(
        title="Мои на пробник",
        school=school,
        owner=teacher,
        defaults={
            "expression": {"solution": {"uses": [vieta.pk]}},
            "created_by": teacher,
        },
    )

    # предложения в трёх состояниях, одно с разговором
    ждёт = proposals.make(
        teacher,
        kind=Proposal.TYPO,
        problem=Problem.objects.filter(text__startswith="Найдите значение").first(),
        text="кажется, пропущено «в точке x = 2»",
        suggested="Найдите значение функции в точке $x = 2$.",
    )
    proposals.say(ждёт, admin, "А в каком именно задании? Уточните.")

    принято = proposals.make(
        teacher,
        kind=Proposal.TAG,
        problem=Problem.objects.filter(text__startswith="Постройте вектор").first(),
        tag=algebra,
        text="сюда просится предмет",
    )
    proposals.accept(принято, admin, answer="Верно, повесил.")

    отклонено = proposals.make(
        teacher,
        kind=Proposal.OTHER,
        problem=Problem.objects.filter(text__startswith="Постройте вектор").first(),
        text="может, убрать эту задачу?",
    )
    proposals.decline(отклонено, admin, answer="Нет, она нужна на зачёте.")

    return "задачник во всех формах"
