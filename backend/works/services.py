"""
Правила работ: кому что видно, когда можно отвечать и во что обходится правка.

Здесь нет ни одного запроса ради запроса: всё, что зовут экраны, сделано
выборками по набору — таблица работ у учителя это тридцать учеников на
десять задач, и запрос на ячейку убил бы её первым же классом.
"""

from collections import defaultdict

from config.errors import Codes, api_error
from django.db.models import Count, Max
from django.utils import timezone

from .models import CLOSED, OPEN, PLANNED, Submission, Task, Work


# --- что ученик может видеть и делать -------------------------------------------


def visible_works(student, *, now=None):
    """
    Работы, которые ученик имеет право видеть.

    Курсы берутся **все его**, включая те, откуда его сняли: работа, которую
    он решал, никуда не делась, и читать её он продолжает. А вот отвечать —
    нет, это отдельный вопрос (`may_answer`).

    Ненаступившее окно прячет работу целиком: «черновика» нет, и вместо него
    работает именно это.
    """
    from schedule.models import Course

    now = now or timezone.now()
    courses = Course.objects.for_student(student, active_only=False)

    return (
        Work.objects.filter(course__in=courses, opens_at__lte=now)
        .select_related("course", "course__subject", "course__grade")
        .order_by("-opens_at", "-id")
    )


def may_answer(work, student, *, now=None) -> None:
    """Молчит или отказывает: окно, зачисление и попытки — три причины."""
    state = work.state(now)
    if state == PLANNED:
        # до открытия работы для ученика не существует вовсе, и сюда он
        # попасть не должен — но API не полагается на то, что интерфейс
        # чего-то не показал
        api_error(Codes.WORK_NOT_OPEN, "This work has not opened yet.")
    if state == CLOSED:
        api_error(
            Codes.WORK_CLOSED,
            "This work is closed: answers are no longer accepted.",
        )

    from schedule.models import Course

    active = Course.objects.for_student(student, active_only=True)
    if not active.filter(pk=work.course_id).exists():
        api_error(
            Codes.NOT_IN_COURSE,
            "You are no longer in this course: what you did stays visible, "
            "but answers are not accepted.",
        )


def attempts_left(work, used: int):
    """Сколько осталось; `None` — без ограничения."""
    if work.attempts is None:
        return None
    return max(0, work.attempts - used)


def answer(task, student, text: str, *, now=None) -> Submission:
    """
    Принять ответ. Попытка расходуется здесь — на **любой** отправке.

    Именно поэтому счётчик считается до записи и по всему журналу: «не
    считать попытку, пока учитель не проверил» означало бы, что право
    ученика на ответ зависит от скорости проверки.

    Текст кладётся как пришёл. Единственное, чего он не переживает, —
    нулевые байты, которых Postgres всё равно не примет.
    """
    work = task.work
    may_answer(work, student, now=now)

    used = Submission.objects.filter(task=task, student=student).count()
    if work.attempts is not None and used >= work.attempts:
        api_error(
            Codes.ATTEMPTS_EXHAUSTED,
            f"No attempts left for this task: {work.attempts} used.",
            attempts=work.attempts,
        )

    return Submission.objects.create(
        task=task, student=student, answer=text.replace("\x00", "")
    )


def my_answers(student, tasks) -> dict:
    """
    Журнал ученика по задачам: `{task_id: [отправки]}`.

    Одним запросом на всю работу — историю показывают целиком, и «покажи
    прошлые попытки» не должно стоить запроса на задачу.
    """
    grouped = defaultdict(list)
    for row in Submission.objects.filter(
        task__in=tasks, student=student
    ).order_by("created_at", "id"):
        grouped[row.task_id].append(row)

    return grouped


def verdict_for(work, submission) -> bool | None:
    """
    Что ученику видно про проверку.

    `show_result` выключен — отметка скрыта до закрытия окна: учитель не
    хочет, чтобы её показали до срока и одноклассники узнали ответ по чужой
    зелёной галочке.
    """
    if submission is None:
        return None
    if work.show_result or work.state() == CLOSED:
        return submission.is_correct
    return None


# --- во что обойдётся правка ----------------------------------------------------


def impact_of(work) -> dict:
    """
    Цена правки открытой работы — числом, а не запретом.

    Тот же разговор, что при импорте плана: запрет здесь дороже ошибки
    (учитель нашёл опечатку в условии посреди урока), а молчание дешевле
    только на вид — «сейчас решают семнадцать человек» меняет решение.
    """
    submissions = Submission.objects.filter(task__work=work)

    return {
        "state": work.state(),
        "answers": submissions.count(),
        "students": submissions.values("student_id").distinct().count(),
        "checked": submissions.filter(is_correct__isnull=False).count(),
    }


def task_impact(task) -> dict:
    """То же самое про одну задачу: сколько вердиктов затронет правка."""
    submissions = Submission.objects.filter(task=task)

    return {
        "answers": submissions.count(),
        "students": submissions.values("student_id").distinct().count(),
        "checked": submissions.filter(is_correct__isnull=False).count(),
    }


def reset_verdicts(task) -> int:
    """
    Снять отметки со всех отправок задачи — «перепроверить задачу».

    Нужно ровно тогда, когда в системе оказался неверный эталон и половина
    класса проверена неправильно. Ответы при этом не трогаются: они и есть
    то, что надо перечитать.
    """
    return Submission.objects.filter(task=task, is_correct__isnull=False).update(
        is_correct=None, checked_at=None, checked_by=None
    )


# --- порядок задач ---------------------------------------------------------------


def next_position(work) -> int:
    """Новая задача встаёт в конец: другого места у неё нет."""
    last = work.tasks.order_by("-position").first()
    return 0 if last is None else last.position + 1


def reindex(work) -> None:
    """Плотные позиции 0, 1, 2… — как в плане, и по той же причине."""
    for index, task in enumerate(work.tasks.order_by("position", "id")):
        if task.position != index:
            Task.objects.filter(pk=task.pk).update(position=index)


def move(task, direction: str) -> bool:
    """Шаг вверх или вниз среди соседей. `False` — край, а не ошибка."""
    reindex(task.work)
    task.refresh_from_db()

    step = -1 if direction == "up" else 1
    neighbour = task.work.tasks.filter(position=task.position + step).first()
    if neighbour is None:
        return False

    here, there = task.position, neighbour.position
    Task.objects.filter(pk=task.pk).update(position=there)
    Task.objects.filter(pk=neighbour.pk).update(position=here)
    return True


# --- сводка для списка работ ------------------------------------------------------


def totals_for(works, *, student=None) -> dict:
    """
    Числа, без которых список работ — просто список названий.

    У учителя это «задач 6 · ответили 17 из 24 · не проверено 9», у ученика
    «задач 6 · ответил на 4». Считается одним проходом на весь список: работ
    у курса за год десятки.
    """
    works = list(works)
    if not works:
        return {}

    tasks = Task.objects.filter(work__in=works).values_list("id", "work_id")
    task_to_work = dict(tasks)

    counts = {
        work.pk: {"tasks": 0, "answers": 0, "unchecked": 0, "students": set(), "mine": set()}
        for work in works
    }
    for _, work_id in tasks:
        counts[work_id]["tasks"] += 1

    submissions = Submission.objects.filter(task_id__in=task_to_work)
    if student is not None:
        submissions = submissions.filter(student=student)

    for task_id, student_id, checked in submissions.values_list(
        "task_id", "student_id", "is_correct"
    ):
        row = counts[task_to_work[task_id]]
        row["answers"] += 1
        row["students"].add(student_id)
        row["mine"].add(task_id)
        if checked is None:
            row["unchecked"] += 1

    return {
        work_id: {
            "tasks": row["tasks"],
            "answers": row["answers"],
            "unchecked": row["unchecked"],
            "students": len(row["students"]),
            "answered_tasks": len(row["mine"]),
        }
        for work_id, row in counts.items()
    }


def enrolled_count(course) -> int:
    """Сколько человек сейчас учится — знаменатель в «ответили 17 из 24»."""
    return course.students.filter(removed_at__isnull=True).count()


# --- сводная таблица ---------------------------------------------------------------


def table_version(work) -> str:
    """
    Метка «в таблице что-то изменилось» — одним запросом.

    Опрос идёт раз в несколько секунд у каждого открытого экрана, а воркеров
    у прода два: ответ «ничего не изменилось» обязан быть дешёвым, иначе
    первый же тяжёлый сосед начнёт копить очередь. Считаются три вещи, и
    вместе они меняются при любом событии таблицы: появилась отправка,
    поставили или сняли отметку, удалили задачу.

    Не хэш содержимого: хэш пришлось бы собирать по всем строкам, то есть
    делать ровно ту работу, которой опрос и должен избегать.
    """
    numbers = Submission.objects.filter(task__work=work).aggregate(
        total=Count("id"), last=Max("created_at"), checked=Max("checked_at")
    )
    tasks = work.tasks.count()

    return "|".join(
        str(part)
        for part in (
            tasks,
            numbers["total"],
            numbers["last"] and numbers["last"].timestamp(),
            numbers["checked"] and numbers["checked"].timestamp(),
        )
    )


def build_table(work) -> dict:
    """
    Ученики по строкам, задачи по столбцам. Всё одним проходом.

    В ячейке — **последняя** отправка: она и есть текущий ответ. Прошлые
    никуда не делись, их показывает история ячейки, а в клетке таблицы
    нужен один ответ, иначе таблицу не прочитать.

    Снятые с курса остаются строками и помечены: их ответы никуда не
    делись, и смешивать их с работающими нельзя — это разные ответы на
    вопрос «кто не справился».
    """
    from schedule.models import CourseStudent

    rows = list(
        CourseStudent.objects.filter(course_id=work.course_id)
        .select_related("student")
        .order_by("student__first_name", "student__last_name", "student__email")
    )
    tasks = list(work.tasks.all())

    # одна выборка на всю таблицу: тридцать учеников на десять задач — это
    # триста ячеек, и запрос на ячейку убил бы экран первым же классом
    journal = defaultdict(list)
    for row in Submission.objects.filter(task__work=work).order_by("created_at", "id"):
        journal[(row.task_id, row.student_id)].append(row)

    students = []
    per_task = {task.pk: {"answered": 0, "correct": 0, "wrong": 0, "unchecked": 0} for task in tasks}

    for enrolment in rows:
        cells = []
        answered = correct = 0

        for task in tasks:
            history = journal[(task.pk, enrolment.student_id)]
            cells.append(cell_of(task, history))
            if not history:
                continue

            answered += 1
            last = history[-1]
            per_task[task.pk]["answered"] += 1
            if last.is_correct is True:
                correct += 1
                per_task[task.pk]["correct"] += 1
            elif last.is_correct is False:
                per_task[task.pk]["wrong"] += 1
            else:
                per_task[task.pk]["unchecked"] += 1

        students.append(
            {
                "id": enrolment.student_id,
                "name": full_name(enrolment.student),
                "email": enrolment.student.email,
                "active": enrolment.is_active,
                "answered": answered,
                "correct": correct,
                "cells": cells,
            }
        )

    columns = [
        {
            "id": task.pk,
            "position": task.position,
            "question": task.question,
            "answers": task.answers,
            **per_task[task.pk],
        }
        for task in tasks
    ]

    return {
        "version": table_version(work),
        "changed": True,
        "work": {
            "id": work.pk,
            "title": work.title,
            "state": work.state(),
            "course_name": work.course.name,
        },
        "tasks": columns,
        "students": students,
        "summary": summarise(students, columns),
    }


def summarise(students, columns) -> dict:
    """
    Статистика работы — из тех же строк, которыми нарисована таблица.

    Не второй проход по журналу: сводка и таблица обязаны говорить одно и
    то же, а два расчёта над одними данными расходятся молча — так уже
    было у раскладки плана, где сводка обещала одно, а строки показывали
    другое. Здесь считается по готовым ячейкам, и разойтись им негде.

    Кого считать. **Начали и закончили** — только про действующих: снятый
    с курса ничего не «не закончил», он ушёл. А вот **ответы и проверку**
    считаем все: работа учителя не становится меньше оттого, что автор
    ответа больше не в курсе.

    «Самая трудная» — та, где меньше всего доля верных среди
    **проверенных**. Непроверенная задача в кандидаты не попадает вовсе:
    иначе самой трудной всегда оказывалась бы та, до которой не дошли
    руки.
    """
    active = [row for row in students if row["active"]]
    tasks = len(columns)

    started = sum(1 for row in active if row["answered"])
    finished = sum(1 for row in active if tasks and row["answered"] == tasks)

    answers = sum(column["answered"] for column in columns)
    unchecked = sum(column["unchecked"] for column in columns)
    correct = sum(column["correct"] for column in columns)
    checked = sum(column["correct"] + column["wrong"] for column in columns)

    judged = [
        column for column in columns if column["correct"] + column["wrong"] > 0
    ]
    hardest = min(
        judged,
        key=lambda column: column["correct"] / (column["correct"] + column["wrong"]),
        default=None,
    )

    return {
        "students": len(active),
        "started": started,
        "finished": finished,
        "answers": answers,
        "unchecked": unchecked,
        "correct": correct,
        "checked": checked,
        "hardest": hardest
        and {
            "id": hardest["id"],
            "position": hardest["position"],
            "correct": hardest["correct"],
            "checked": hardest["correct"] + hardest["wrong"],
        },
    }


def cell_of(task, history) -> dict:
    """
    Одна клетка: последняя отправка и то, что о ней надо знать сразу.

    `redone` — «переделал после проверки»: последняя отправка не проверена,
    а раньше отметка уже стояла. Это и есть весь ответ на гонку «учитель
    проверял, пока ученик отправлял»: отметка осталась на прошлой строке,
    и видно, что смотрели не то.
    """
    if not history:
        return {"task": task.pk, "submission": None, "attempts": 0}

    last = history[-1]
    checked_before = any(row.is_correct is not None for row in history[:-1])

    return {
        "task": task.pk,
        "submission": last.pk,
        "attempts": len(history),
        "answer": last.answer,
        "verdict": last.is_correct,
        "at": last.created_at,
        "redone": last.is_correct is None and checked_before,
    }


def full_name(person) -> str:
    return " ".join(filter(None, (person.first_name, person.last_name))) or person.email
