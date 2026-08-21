"""
Правила работ: кому что видно, когда можно отвечать и во что обходится правка.

Здесь нет ни одного запроса ради запроса: всё, что зовут экраны, сделано
выборками по набору — таблица работ у учителя это тридцать учеников на
десять задач, и запрос на ячейку убил бы её первым же классом.
"""

from collections import defaultdict

from config.errors import Codes, api_error
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Count, Max
from django.utils import timezone

from bank.models import Problem

from . import statements, track
from .models import (
    CLOSED,
    GradingSystem,
    OPEN,
    PLANNED,
    Criterion,
    Mark,
    MarkChange,
    StudentWork,
    ScanPage,
    Submission,
    Task,
    Work,
)


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

    **Оценки считаются наравне с отправками**, и это не мелочь: у бумажной
    работы отправок нет вовсе, и цена, считавшая только их, сообщала «ничего
    не затронуто» про полностью проверенный класс. А затронуто там самое
    дорогое: дописанная задача поднимает `top` — сумму максимумов, — и доля
    набранного у всех уже оценённых падает молча, без единой перепроверки.
    """
    submissions = Submission.objects.filter(task__work=work)
    graded = work.students.filter(marks__isnull=False).distinct()

    return {
        "state": work.state(),
        "answers": submissions.count(),
        "students": submissions.values("student_id").distinct().count(),
        "checked": submissions.filter(is_correct__isnull=False).count(),
        "graded": graded.count(),
        # знаменатель: из скольки баллов считается работа сейчас
        "top": sum(task.maximum for task in work.tasks.all()),
    }


def task_impact(task, *, user) -> dict:
    """
    Цена правки этой ячейки: сколько ответов и вердиктов она затронет — и
    отдельно, во что обойдётся правка **условия**.

    Второе считается по всем работам, где это условие спрошено, а не только по
    этой: условие одно на всех, и правка доезжает всюду. Из этих чисел
    интерфейс и берёт умолчание — править везде или сделать копию.
    """
    submissions = Submission.objects.filter(task=task)

    return {
        "answers": submissions.count(),
        "students": submissions.values("student_id").distinct().count(),
        "checked": submissions.filter(is_correct__isnull=False).count(),
        "statement": {
            **statements.cost(task.problem),
            # чужое условие правится только копией: другого исхода нет
            "mine": task.problem is None
            or Problem.objects.writable_by(user).filter(pk=task.problem_id).exists(),
        },
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
    # оценки двигают ту же таблицу: поставили отметку — соседний экран
    # должен её увидеть, не дожидаясь перезагрузки
    graded = work.students.aggregate(rows=Count("id"), last=Max("updated_at"))

    return "|".join(
        str(part)
        for part in (
            tasks,
            numbers["total"],
            numbers["last"] and numbers["last"].timestamp(),
            numbers["checked"] and numbers["checked"].timestamp(),
            graded["rows"],
            graded["last"] and graded["last"].timestamp(),
        )
    )


def student_version(work, student) -> str:
    """
    Метка «у ученика что-то изменилось» — тем же приёмом, что у таблицы.

    Смотрит на **его** отправки и на саму работу: отметка учителя приходит
    к нему так же неожиданно, как его ответ — к учителю, и опрашивать без
    дешёвого «не изменилось» здесь нельзя ровно по той же причине.

    `updated_at` работы и число задач в метке потому, что учитель правит
    открытую работу — это разрешено и названо ценой, — и ученик должен
    увидеть новое условие, а не то, которое было при загрузке страницы.
    """
    numbers = Submission.objects.filter(task__work=work, student=student).aggregate(
        total=Count("id"), last=Max("created_at"), checked=Max("checked_at")
    )
    # своя оценка — такое же неожиданное для него событие, как отметка
    graded = work.students.filter(student=student).aggregate(last=Max("updated_at"))

    return "|".join(
        str(part)
        for part in (
            work.tasks.count(),
            work.updated_at.timestamp(),
            numbers["total"],
            numbers["last"] and numbers["last"].timestamp(),
            numbers["checked"] and numbers["checked"].timestamp(),
            graded["last"] and graded["last"].timestamp(),
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
    criteria = list(work.criteria.all())
    graded = {
        row.student_id: row
        for row in work.students.prefetch_related("marks", "attachments")
    }

    # одна выборка на всю таблицу: тридцать учеников на десять задач — это
    # триста ячеек, и запрос на ячейку убил бы экран первым же классом
    journal = defaultdict(list)
    for row in Submission.objects.filter(task__work=work).order_by("created_at", "id"):
        journal[(row.task_id, row.student_id)].append(row)

    # «Эту задачу он уже решал» — одним запросом на всю таблицу: тридцать
    # учеников на десять задач это триста вопросов, и по запросу на клетку
    # экран бы не открылся.
    seen_before = track.solved_before(
        [task.problem_id for task in tasks if task.problem_id],
        [row.student_id for row in rows],
        besides=work,
    )

    students = []
    per_task = {task.pk: {"answered": 0, "correct": 0, "wrong": 0, "unchecked": 0} for task in tasks}

    for enrolment in rows:
        cells = []
        answered = correct = 0

        for task in tasks:
            history = journal[(task.pk, enrolment.student_id)]
            cell = cell_of(task, history)
            # сколько раз он встречал это условие в **других** работах: по
            # нему видно, что задача не новая, — и учителю, и в разговоре
            cell["seen_before"] = seen_before.get(
                (task.problem_id, enrolment.student_id), 0
            )
            cells.append(cell)
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

        mine = graded.get(enrolment.student_id)
        students.append(
            {
                "id": enrolment.student_id,
                "name": full_name(enrolment.student),
                "email": enrolment.student.email,
                "active": enrolment.is_active,
                "answered": answered,
                "correct": correct,
                "cells": cells,
                # оценка и слова учителя: строки может не быть вовсе, и это
                # то же самое, что «ещё не проверен»
                "row": mine.pk if mine else None,
                "marks": marks_of(mine),
                "scores": scores_of(mine),
                "comment": mine.comment if mine else "",
                "papers": papers_of(mine),
            }
        )

    columns = [
        {
            "id": task.pk,
            "position": task.position,
            "question": statements.statement_of(task),
            "answers": statements.answers_of(task),
            "maximum": task.maximum,
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
            "on_paper": work.on_paper,
        },
        "tasks": columns,
        "criteria": [
            {
                "id": item.pk,
                "position": item.position,
                "name": item.name,
                "maximum": item.maximum,
            }
            for item in criteria
        ],
        "students": students,
        "summary": summarise(students, columns),
        "marks_summary": mark_stats(students, tasks),
    }


def grade_for(system, *, earned: int, top: int) -> dict | None:
    """
    Отметка по набранному. Считается, а не хранится.

    Хранить букву значит соврать при первой же правке порогов: две работы с
    одинаковыми баллами получили бы разные отметки, и объяснить это было бы
    некому. Поэтому в базе баллы, а отметка выводится — и меняется вместе с
    порогами, чего школа обычно и хочет.

    Возвращает `None`, когда сказать нечего: системы нет, полос нет или
    набирать было не из чего.
    """
    if system is None or not top:
        return None

    bands = list(system.bands.all())
    if not bands:
        return None

    # у баллов порог в процентах, у уровней — в самой сумме
    value = round(earned / top * 100) if system.kind == GradingSystem.POINTS else earned
    for band in bands:  # отсортированы по убыванию порога
        if value >= band.threshold:
            return {
                "label": band.label,
                "system": system.name,
                "kind": system.kind,
                "value": value,
            }
    return None


def mark_stats(students, questions) -> dict:
    """
    Сводка по оценкам: кто оценён, сколько в среднем и что далось труднее всего.

    Считается **из тех же строк, которыми нарисована таблица**, а не вторым
    проходом по журналу оценок: два расчёта над одними данными расходятся
    молча, и однажды сводка уже обещала одно, а строки показывали другое.

    Трудность задачи — доля набранного от возможного среди тех, кому её вообще
    оценили. Не считаем по классу целиком: у отсутствовавшего оценок нет, и
    приписывать ему ноль значило бы объявить задачу тем труднее, чем больше
    народу болело.

    Пустая шкала даёт пустую сводку: работа может не оцениваться вовсе, и это
    не «ноль», а «нечего показывать».
    """
    if not questions:
        return None

    working = [student for student in students if student["active"]]
    graded = [student for student in students if student["scores"]]
    totals = sorted(sum(student["scores"].values()) for student in graded)
    top = sum(item.maximum for item in questions)

    columns = []
    for item in questions:
        values = [
            student["scores"][item.pk]
            for student in students
            if item.pk in student["scores"]
        ]
        earned = sum(values)
        columns.append(
            {
                "id": item.pk,
                "name": f"Q{item.position + 1}",
                "maximum": item.maximum,
                "question": statements.statement_of(item),
                "graded": len(values),
                "earned": earned,
                # доля набранного от возможного, в процентах
                "facility": round(earned / (item.maximum * len(values)) * 100)
                if values
                else None,
                "full": sum(1 for value in values if value >= item.maximum),
                "partial": sum(1 for value in values if 0 < value < item.maximum),
                "zero": sum(1 for value in values if value == 0),
            }
        )

    answered = [column for column in columns if column["facility"] is not None]
    hardest = min(answered, key=lambda column: column["facility"]) if answered else None
    easiest = max(answered, key=lambda column: column["facility"]) if answered else None

    return {
        "graded": len(graded),
        "students": len(working),
        "max_total": top,
        "mean": round(sum(totals) / len(totals), 1) if totals else None,
        # медиана честнее среднего на маленьком классе: одна двойка среди
        # двадцати пятёрок среднее заметно тянет, а медиану — нет
        "median": totals[len(totals) // 2] if totals else None,
        "best": totals[-1] if totals else None,
        "worst": totals[0] if totals else None,
        "columns": columns,
        "hardest": hardest and hardest["id"],
        "easiest": easiest and easiest["id"],
    }


def scores_of(student_work) -> dict:
    """`{id вопроса: балл}` — вторая ось, «что он решил»."""
    if not student_work:
        return {}
    return {
        mark.task_id: mark.value
        for mark in student_work.marks.all()
        if mark.task_id is not None
    }


def marks_of(student_work) -> dict:
    """`{id критерия: значение}` — то, что показывает и правит интерфейс."""
    if student_work is None:
        return {}

    return {
        mark.criterion_id: mark.value
        for mark in student_work.marks.all()
        if mark.criterion_id is not None
    }


def grade(work, student, *, marks=None, scores=None, comment=None, by=None):
    """
    Поставить оценку и написать слова. Одним вызовом на ученика.

    По одному критерию за раз не пишем намеренно: у MYP их четыре, и
    выставляются они вместе, за один взгляд на работу. Полный набор к тому
    же снимает вопрос «а что с теми, которые не прислали» — они остаются
    как были.

    Осей две, и они разные: `marks` — `{критерий: значение}`, `scores` —
    `{вопрос: балл}`. Критерии отвечают на «как работа оценена» (уровень по
    лучшему соответствию), вопросы — на «что он решил» (балл, который
    складывается в сумму). Работа может иметь обе разом.

    `None` в значении снимает отметку. Каждое изменение дописывается в журнал
    (`MarkChange`) — исправленная оценка это событие, а не новое значение поля.
    """
    from django.db import transaction

    with transaction.atomic():
        row, _ = StudentWork.objects.get_or_create(work=work, student=student)
        if comment is not None:
            row.comment = comment
            row.save(update_fields=["comment", "updated_at"])

        if not marks and not scores:
            return row

        moved = False
        for axis, wanted in (("criterion", marks or {}), ("task", scores or {})):
            rows = work.criteria.all() if axis == "criterion" else work.tasks.all()
            current = {
                getattr(mark, f"{axis}_id"): mark
                for mark in row.marks.all()
                if getattr(mark, f"{axis}_id") is not None
            }

            for item in rows:
                if item.pk not in wanted:
                    continue

                value = wanted[item.pk]
                was = current.get(item.pk)
                if (was.value if was else None) == value:
                    continue

                if value is None:
                    if was:
                        was.delete()
                elif was:
                    was.value = value
                    was.save(update_fields=["value"])
                else:
                    Mark.objects.create(
                        student_work=row, value=value, **{axis: item}
                    )

                MarkChange.objects.create(
                    student_work=row, value=value, changed_by=by, **{axis: item}
                )
                moved = True

        if moved:
            # оценки лежат отдельными строками, и `auto_now` их правку не
            # видит — а опрос смотрит именно на `updated_at`: без этого
            # выставленная отметка не доехала бы до открытого экрана
            row.save(update_fields=["updated_at"])

    return row


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

    «Самой трудной задачи» здесь больше нет: числа по столбцу и так стоят
    в его шапке, а плашка повторяла их отдельно и требовала объяснять, что
    непроверенная задача в кандидаты не идёт. Число, которое надо
    объяснять дважды, дешевле не показывать.
    """
    active = [row for row in students if row["active"]]
    tasks = len(columns)

    started = sum(1 for row in active if row["answered"])
    finished = sum(1 for row in active if tasks and row["answered"] == tasks)

    answers = sum(column["answered"] for column in columns)
    unchecked = sum(column["unchecked"] for column in columns)
    correct = sum(column["correct"] for column in columns)
    checked = sum(column["correct"] + column["wrong"] for column in columns)

    return {
        "students": len(active),
        "started": started,
        "finished": finished,
        "answers": answers,
        "unchecked": unchecked,
        "correct": correct,
        "checked": checked,
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


def scale_payload(work) -> dict:
    """
    Шкала работы наружу: список критериев и подсказка, как её показывать.

    `simple` — «один безымянный критерий», то есть обычная отметка. Правило
    выводится, а не хранится, и интерфейс по нему решает, рисовать одно поле
    или список. Хранить его отдельно значило бы завести второй источник
    правды о том же самом.
    """
    criteria = list(work.criteria.all())

    return {
        "criteria": [
            {
                "id": item.pk,
                "position": item.position,
                "name": item.name,
                "maximum": item.maximum,
            }
            for item in criteria
        ],
        "graded": bool(criteria),
        "simple": len(criteria) == 1 and not criteria[0].name,
    }


def set_questions(work, items, *, by):
    """
    Заменить вопросы работы целиком. Позиция — индекс в присланном списке.

    Тот же приём, что у шкалы и у строк шаблона, и по той же причине:
    построчный CRUD потребовал бы своей перенумерации ради формы, у которой
    вложенности нет. Вопрос, которого в списке не стало, уносит свои баллы и
    отправки каскадом: они были ответами **на него**.
    """
    from django.db import transaction

    with transaction.atomic():
        existing = list(work.tasks.all())

        for position, item in enumerate(items):
            if position < len(existing):
                row = existing[position]
                row.position = position
                row.maximum = item.get("maximum", row.maximum)
                row.save(update_fields=["position", "maximum"])
            else:
                row = Task.objects.create(
                    work=work, position=position, maximum=item.get("maximum", 1)
                )
            statements.say(
                row,
                text=item.get("question"),
                answers=item.get("answers"),
                user=by,
                mode=item.get("mode"),
            )

        for row in existing[len(items):]:
            row.delete()

    return list(work.tasks.all())


def set_scale(work, criteria):
    """
    Заменить шкалу целиком. Позиция — индекс в присланном списке.

    Критерий, которого в списке не стало, уносит свои оценки каскадом: они
    были оценками **по нему**, и без него не значат ничего. Цену этого
    называет `scale_impact` — до нажатия, как и у импорта плана.

    Существующие критерии узнаются по порядку, а не по id: список приходит
    целиком, id в нём нет, и «третья строка осталась третьей» — то же
    правило, что у строк шаблона.
    """
    from django.db import transaction

    with transaction.atomic():
        existing = list(work.criteria.all())

        for position, item in enumerate(criteria):
            if position < len(existing):
                row = existing[position]
                row.position = position
                row.name = item["name"]
                row.maximum = item["maximum"]
                row.save(update_fields=["position", "name", "maximum"])
            else:
                Criterion.objects.create(
                    work=work,
                    position=position,
                    name=item["name"],
                    maximum=item["maximum"],
                )

        for row in existing[len(criteria):]:
            row.delete()

    return work.criteria.all()


def my_grade(work, student) -> dict:
    """
    Оценка глазами ученика: своя, и только когда её можно показывать.

    Правило то же, что у вердикта, и намеренно то же: `show_result`
    выключен — до закрытия окна ничего не видно. Зелёная галочка у соседа и
    есть ответ, разошедшийся по классу; с оценкой это верно тем более.

    Комментарий учителя показывается по тому же правилу: он часто и есть
    объяснение оценки, и врозь они бессмысленны.

    А вот **скан своей работы виден всегда**, независимо от `show_result`.
    Тот флаг про отметку соседа, разошедшуюся по классу; собственная
    исписанная бумага ни к кому больше не относится, и прятать её не от
    кого.
    """
    scale = scale_payload(work)
    row = work.students.filter(student=student).first()
    visible = work.show_result or work.state() == CLOSED

    return {
        "criteria": scale["criteria"],
        "graded": scale["graded"],
        "simple": scale["simple"],
        "marks": marks_of(row) if (row and visible) else {},
        "comment": (row.comment if row and visible else ""),
        "papers": papers_of(row),
    }


def papers_of(student_work) -> list:
    """
    Что приложено к работе ученика: сканы и ссылки.

    Ссылки тоже: обычно это скан, но приложить адрес — законное действие
    (отзыв в общем документе, разбор на видео), и отдавать только файлы
    значило бы, что приложенная ссылка молча не показывается никому.
    """
    if student_work is None:
        return []

    return [
        {
            "id": item.pk,
            "kind": item.kind,
            "title": item.title,
            "url": item.url,
            "size": item.stored_file.size if item.stored_file_id else None,
        }
        for item in student_work.attachments.select_related("stored_file")
    ]


def attach_pages(work, student_id, *, data: bytes, numbers, by=None):
    """
    Нарезать названные страницы и приложить их ученику.

    Одна дверь для обоих путей — ручной разметки и разбора пачки по именам:
    файл каждого ученика проходит обычную загрузку (дедупликация, квота,
    проверка типа), а не свою дорогу в бакет. Своя однажды разойдётся с общей.
    """
    from files import services as file_services
    from files.models import Attachment

    from . import splitting

    row, _ = StudentWork.objects.get_or_create(work=work, student_id=student_id)
    surname = (
        work.course.students.filter(student_id=student_id)
        .values_list("student__last_name", flat=True)
        .first()
        or str(student_id)
    )
    stored, _ = file_services.store_upload(
        upload=SimpleUploadedFile(
            f"{surname}.pdf",
            splitting.cut_pages(data, numbers),
            content_type="application/pdf",
        ),
        school=work.course.school,
        user=by,
    )
    return Attachment.objects.create(
        student_work=row,
        kind="file",
        stored_file=stored,
        title=f"{surname}.pdf",
        position=file_services.next_position(student_work=row),
    )


def split_scan(work, *, data: bytes, pieces, by=None) -> dict:
    """
    Разрезать скан и разложить по ученикам. Одной транзакцией.

    Половина разобранной пачки хуже неразобранной: непонятно, какая
    половина, и второй заход создаст дубли поверх первого. Поэтому либо всё,
    либо ничего.

    Файл каждого ученика проходит обычный путь загрузки: дедупликация,
    квота, проверка типа. Дедупликация тут почти не срабатывает — куски
    разные, — но пусть путь будет один: своя дорога в бакет однажды
    разойдётся с общей.
    """
    from django.db import transaction

    with transaction.atomic():
        for piece in pieces:
            attach_pages(work, piece.student_id, data=data, numbers=piece.pages, by=by)

    return {"created": len(pieces), "students": len({p.student_id for p in pieces})}


def reassign_paper(work, *, attachment, student) -> dict:
    """
    Переложить приложенную работу тому, чья она.

    Файл в бакете не трогается: меняется владелец ссылки. Строка нового
    ученика заводится, если её ещё нет, — то же «по требованию», что и у
    оценки.
    """
    row, _ = StudentWork.objects.get_or_create(work=work, student=student)
    attachment.student_work = row
    attachment.save(update_fields=["student_work"])

    return {"attachment": attachment.pk, "student": student.pk}


# ---------------------------------------------------------------------------
# Разбор пачки сканов
# ---------------------------------------------------------------------------
def scan_roster(work) -> list:
    """Действующий состав курса глазами разбора."""
    from .scanning import Person

    rows = work.course.students.filter(removed_at__isnull=True).select_related("student")
    return [
        Person(id=row.student_id, first=row.student.first_name, last=row.student.last_name)
        for row in rows
    ]


def scan_pages(work) -> list:
    """Строки страниц из базы в объекты разбора."""
    from .scanning import CELLS, Page

    return [
        Page(
            index=row.index,
            first=row.first_name,
            surname=row.surname,
            cells=(list(row.cells) + [None] * CELLS)[:CELLS],
            guess=row.guess,
            headerless=row.headerless,
            ours=row.ours,
            student_id=row.student_id,
            decided_by_human=row.decided_by_human,
        )
        for row in work.scan_pages.all()
    ]


def max_mark_of(work) -> int | None:
    """Наибольший максимум среди вопросов работы — им проверяются прочитанные клетки."""
    values = [task.maximum for task in work.tasks.all()]
    return max(values) if values else None


def scan_state(work) -> dict:
    """
    Всё, что экран должен знать о пачке: страницы, пакеты, сомнения.

    Считается на каждый запрос и нигде не хранится: раскладка зависит от того,
    что прочитано и что человек уже решил, а два источника правды об одном и
    том же разъезжаются молча.

    Единица решения — **пакет**, работа одного ученика: спросить «чей это»
    надо один раз, а не по разу на каждый из восьми листов.
    """
    from . import scanning

    pages = scan_pages(work)
    roster = scan_roster(work)
    packets = scanning.arrange(pages, roster)
    limit = max_mark_of(work)
    questions = work.tasks.count() or scanning.QUESTIONS

    owner_of = {}
    for packet in packets:
        for page in packet.pages:
            owner_of[page.index] = packet.student_id

    rows = []
    for page in pages:
        owner = owner_of.get(page.index)
        rows.append(
            {
                "index": page.index,
                "first_name": page.first,
                "surname": page.surname,
                "cells": page.cells,
                "headerless": page.headerless,
                "student": owner,
                "decided_by_human": page.decided_by_human,
                "candidates": [],
                "trouble": []
                if page.headerless
                else scanning.troubles(page, owner, limit, questions),
            }
        )
    by_index = {row["index"]: row for row in rows}

    out_packets = []
    for number, packet in enumerate(packets):
        marks, conflicts = scanning.merge_marks(packet.pages)
        trouble = sorted(
            {code for page in packet.pages for code in by_index[page.index]["trouble"]}
        )
        # положенное по свободным задачам или по соседу — догадка, и человек
        # о ней узнаёт: на живой пачке такая раскладка ошиблась четырежды из
        # пятнадцати, и ошиблась молча
        if packet.by_fit:
            trouble.append("placed_by_guess")
            for index in packet.by_fit:
                by_index[index]["trouble"].append("placed_by_guess")
        if packet.student_id is None:
            trouble = ["no_owner"] + [c for c in trouble if c != "no_owner"]
            for page in packet.pages:
                if "no_owner" not in by_index[page.index]["trouble"]:
                    by_index[page.index]["trouble"].append("no_owner")
        for page in packet.pages:
            by_index[page.index]["candidates"] = packet.candidates
        out_packets.append(
            {
                "number": number,
                "pages": [page.index for page in packet.pages],
                "conditions": [page.index for page in packet.conditions],
                "student": packet.student_id,
                "candidates": packet.candidates,
                "conflicts": conflicts,
                "marks": {q + 1: value for q, value in marks.items()},
                "total": sum(marks.values()) if marks else 0,
                "trouble": trouble,
            }
        )

    students = []
    mine = {packet.student_id: packet for packet in packets if packet.student_id}
    for person in roster:
        packet = mine.get(person.id)
        marks, conflicts = scanning.merge_marks(packet.pages if packet else [])
        students.append(
            {
                "id": person.id,
                "name": person.full,
                "pages": sorted(page.index for page in (packet.all_pages if packet else [])),
                "marks": {q + 1: value for q, value in marks.items()},
                "total": sum(marks.values()) if marks else 0,
                "conflicts": conflicts,
            }
        )

    from vision import services as vision_services

    return {
        "pages": rows,
        "packets": out_packets,
        "students": students,
        "questions": questions,
        "max_mark": limit,
        "conditions": sum(len(packet.conditions) for packet in packets),
        "doubts": [
            packet["number"] for packet in out_packets if "no_owner" in packet["trouble"]
        ],
        # цена показывается там же, где идёт чтение: узнавать её в другом
        # разделе, уже потратив, — не то же самое, что видеть по ходу
        "budget": vision_services.budget(work.course.school),
    }


def scan_apply(work, *, data: bytes, by=None) -> dict:
    """
    Применить разобранную пачку: страницы ученикам, баллы в оценки.

    Одной транзакцией, и вот почему именно тут это важнее обычного: половина
    применённой пачки — это часть класса с работами и оценками, а часть без, и
    какая именно, снаружи не видно. Строки страниц после успеха удаляются:
    работа сделана, дальше про неё отвечают вложения и оценки.

    **Листы условий уезжают в PDF ученика вместе с его решением.** Иначе он
    открывает свои ответы без вопросов — половину документа, — а ради того,
    чтобы он видел работу целиком, скан ему и отдают.
    """
    from django.db import transaction

    from . import scanning, splitting

    pages = scan_pages(work)
    if not pages:
        api_error(
            Codes.SCAN_NOTHING_READ,
            "Nothing has been read yet: upload the scans first.",
            field="file",
        )

    total = splitting.read_pages(data)
    roster = {person.id: person for person in scan_roster(work)}
    packets = [
        packet
        for packet in scanning.arrange(pages, list(roster.values()))
        if packet.student_id is not None
    ]

    for packet in packets:
        if packet.student_id not in roster:
            api_error(
                Codes.SPLIT_NOT_IN_COURSE,
                "That student does not study in this course.",
                field="plan",
            )
        for page in packet.all_pages:
            if page.index >= total:
                api_error(
                    Codes.SPLIT_OUT_OF_RANGE,
                    f"Page {page.index + 1} is outside the file, which has {total}.",
                    field="file",
                    pages=total,
                )

    if not packets:
        api_error(
            Codes.SPLIT_EMPTY,
            "No page has an owner: say whose pages these are.",
            field="plan",
        )

    questions = list(work.tasks.all())
    from accounts.models import User

    people = User.objects.in_bulk([packet.student_id for packet in packets])
    graded = 0
    with transaction.atomic():
        for packet in packets:
            attach_pages(
                work,
                packet.student_id,
                data=data,
                numbers=[page.index + 1 for page in packet.all_pages],
                by=by,
            )
            marks, _ = scanning.merge_marks(packet.pages)
            if marks and questions:
                grade(
                    work,
                    people[packet.student_id],
                    scores={
                        task.pk: marks.get(number)
                        for number, task in enumerate(questions)
                        if marks.get(number) is not None
                    },
                    by=by,
                )
                graded += 1

        work.scan_pages.all().delete()

    return {"students": len(packets), "graded": graded, "pages": len(pages)}


def save_scan_reading(work, *, index: int, fingerprint: str, data: dict):
    """
    Положить прочитанное. Решение человека при этом не трогается.

    Перечитывание — обычное дело: страницу перезагрузили, модель позвали
    заново. А вот «эту страницу писал Петров» человек сказал руками, и новое
    чтение имени не повод это отменять.
    """
    row, _ = ScanPage.objects.get_or_create(work=work, index=index)
    row.fingerprint = fingerprint
    row.first_name = data.get("first_name", "")
    row.surname = data.get("surname", "")
    row.date_text = data.get("date", "")
    row.guess = data.get("guess", "")
    row.cells = data.get("values") or []
    row.ours = True
    row.model = data.get("model", "")
    row.save()
    return row


UNSET = object()


def mark_headerless(work, *, index: int, ours: bool = False):
    """
    Записать, что на странице шапки не нашлось, и наш ли это лист.

    Сервер обязан знать о таких страницах, хотя читать их незачем: без них
    рисунок пачки неполон — по нему видно, где кончается работа одного ученика
    и начинается другого. А метка в углу отвечает, лист это условий или наш,
    смазанный: первое — норма, второе — потерянная работа.
    """
    row, _ = ScanPage.objects.get_or_create(work=work, index=index)
    row.headerless = True
    row.ours = ours
    row.save(update_fields=["headerless", "ours"])
    return row


def edit_scan_page(work, *, index: int, student=UNSET, cells=None):
    """
    Правка страницы человеком: чья она и что в клетках.

    Владельца и клетки правят порознь, поэтому «не прислали» и «прислали
    пусто» — разные вещи: первое значит «не трогай», второе — «сними
    владельца». Отобрать страницу у не того ученика надо уметь, и отдельного
    действия под это заводить незачем; различает их сентинел, потому что
    `None` тут занят настоящим значением.
    """
    from .scanning import CELLS

    row, _ = ScanPage.objects.get_or_create(work=work, index=index)
    fields = []
    if student is not UNSET:
        row.student_id = student
        row.decided_by_human = True
        fields += ["student", "decided_by_human"]
    if cells is not None:
        row.cells = (list(cells) + [None] * CELLS)[:CELLS]
        fields.append("cells")
    if fields:
        row.save(update_fields=fields)
    return row


def apply_questions(work, found: list, *, by) -> dict:
    """
    Записать прочитанные условия в шкалу работы.

    Номер задачи с листа ложится на вопрос работы по порядку — `Q1` на первый,
    и так далее. Вопрос и есть то место, где условию положено лежать: критерий
    отвечает на другой вопрос — «как работа оценена», — и в MYP это A, B, C, D
    со своими уровнями, а не задачи.

    Расхождение не подгоняется, а называется. Задач на листе оказалось больше,
    чем в шкале, — значит человек ошибся, объявляя шкалу, либо мы прочитали
    лишнее; и то и другое решает он, а не мы. Молча дописать критерии значит
    задним числом переписать то, по чему уже, может быть, выставлены оценки.

    Максимальный балл с листа («2 marks») тоже только сообщается: менять его у
    критерия, за который уже стоят оценки, — переписывать чужую проверку.
    """
    questions = list(work.tasks.all())
    by_number = {item["number"]: item for item in found}

    written = 0
    for position, task in enumerate(questions, start=1):
        item = by_number.get(position)
        if not item:
            continue
        statements.say(task, text=item["text"], user=by)
        written += 1

    mismatched = [
        {"number": item["number"], "marks": item["marks"]}
        for item in found
        if item["marks"] is not None
        and item["number"] <= len(questions)
        and questions[item["number"] - 1].maximum != item["marks"]
    ]

    return {
        "found": len(found),
        "written": written,
        "criteria": len(questions),
        # номера, для которых критерия не нашлось: шкала короче листа
        "extra": sorted(number for number in by_number if number > len(questions)),
        # лист говорит про максимум не то, что стоит в шкале
        "marks_differ": mismatched,
    }
