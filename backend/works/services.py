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

from .models import (
    CLOSED,
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
                "comment": mine.comment if mine else "",
                "papers": papers_of(mine),
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
    }


def marks_of(student_work) -> dict:
    """`{id критерия: значение}` — то, что показывает и правит интерфейс."""
    if student_work is None:
        return {}

    return {mark.criterion_id: mark.value for mark in student_work.marks.all()}


def grade(work, student, *, marks=None, comment=None, by=None):
    """
    Поставить оценку и написать слова. Одним вызовом на ученика.

    По одному критерию за раз не пишем намеренно: у MYP их четыре, и
    выставляются они вместе, за один взгляд на работу. Полный набор к тому
    же снимает вопрос «а что с теми, которые не прислали» — они остаются
    как были.

    `marks` — `{критерий: значение}`; `None` в значении снимает отметку.
    Каждое изменение дописывается в журнал (`MarkChange`) — исправленная
    оценка это событие, а не новое значение поля.
    """
    from django.db import transaction

    with transaction.atomic():
        row, _ = StudentWork.objects.get_or_create(work=work, student=student)
        if comment is not None:
            row.comment = comment
            row.save(update_fields=["comment", "updated_at"])

        if not marks:
            return row

        current = {mark.criterion_id: mark for mark in row.marks.all()}
        moved = False
        for criterion in work.criteria.all():
            if criterion.pk not in marks:
                continue

            value = marks[criterion.pk]
            was = current.get(criterion.pk)
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
                    student_work=row, criterion=criterion, value=value
                )

            MarkChange.objects.create(
                student_work=row, criterion=criterion, value=value, changed_by=by
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
            student_id=row.student_id,
            decided_by_human=row.decided_by_human,
        )
        for row in work.scan_pages.all()
    ]


def max_mark_of(work) -> int | None:
    """Наибольший максимум среди задач работы — им проверяются прочитанные клетки."""
    values = [c.maximum for c in work.criteria.all()]
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
    questions = work.criteria.count() or scanning.QUESTIONS

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

    criteria = list(work.criteria.all())
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
            if marks and criteria:
                grade(
                    work,
                    people[packet.student_id],
                    marks={
                        criterion.pk: marks.get(number)
                        for number, criterion in enumerate(criteria)
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
    row.model = data.get("model", "")
    row.save()
    return row


UNSET = object()


def mark_headerless(work, *, index: int):
    """
    Записать, что на странице шапки не нашлось.

    Сервер обязан знать о таких страницах, хотя читать их незачем: без них
    рисунок пачки неполон — а именно по нему видно, где кончается работа
    одного ученика и начинается другого.
    """
    row, _ = ScanPage.objects.get_or_create(work=work, index=index)
    row.headerless = True
    row.save(update_fields=["headerless"])
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
