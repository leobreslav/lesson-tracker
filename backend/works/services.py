"""
Правила работ: кому что видно, когда можно отвечать и во что обходится правка.

Здесь нет ни одного запроса ради запроса: всё, что зовут экраны, сделано
выборками по набору — таблица работ у учителя это тридцать учеников на
десять задач, и запрос на ячейку убил бы её первым же классом.
"""

from collections import defaultdict

from config.errors import Codes, api_error
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Count, Max, Q
from django.utils import timezone

from bank.models import Problem
from files.models import Attachment

from . import photos, statements, track
from .models import (
    CLOSED,
    GradingSystem,
    OPEN,
    PLANNED,
    Criterion,
    Mark,
    MarkChange,
    PhotoNote,
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


def visible_works_for(people, *, now=None):
    """
    То же правило, но на нескольких человек разом: семья смотрит одним списком.

    Заведено ради вложений работы: родитель видит работы **своих детей**, и
    спрашивается это одной выборкой. Правило при этом не переписывается —
    складываются те же самые `visible_works`, иначе «что видно ученику» имело
    бы два ответа, и разошлись бы они молча.
    """
    queryset = Work.objects.none()
    for person in people:
        queryset = queryset | visible_works(person, now=now)
    return queryset


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

    # открыт ли **этот** вопрос. Спрашивается после окна и зачисления, потому
    # что закрытая ячейка — не запрет ученику, а способ решать: «Q3 сдайте на
    # листе». Раньше на это отвечал флаг работы, и ответ был один на все
    # вопросы разом.
    if not task.open_for_answers:
        api_error(
            Codes.TASK_CLOSED,
            "This question does not take answers online.",
        )

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


def mark_for(work, submission) -> int | None:
    """
    Балл за этот ответ — то, что ученику видно про проверку.

    `show_result` выключен — отметка скрыта до закрытия окна: учитель не
    хочет, чтобы её показали до срока и одноклассники узнали ответ по чужой
    зелёной галочке.
    """
    if submission is None:
        return None
    if work.show_result or work.state() == CLOSED:
        mark = Mark.objects.filter(submission=submission).first()
        return mark.value if mark else None
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
        "checked": Mark.objects.filter(task__work=work, submission__isnull=False).count(),
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
        "checked": Mark.objects.filter(task=task).count(),
        "statement": {
            **statements.cost(task.problem),
            # чужое условие правится только копией: другого исхода нет
            "mine": task.problem is None
            or Problem.objects.writable_by(user).filter(pk=task.problem_id).exists(),
        },
    }


def reset_verdicts(task) -> int:
    """
    Снять баллы со всех ответов на задачу — «перепроверить задачу».

    Нужно ровно тогда, когда в системе оказался неверный эталон и половина
    класса проверена неправильно. Ответы при этом не трогаются: они и есть
    то, что надо перечитать.

    Снимаются только баллы **за ответы**: балл без ссылки поставлен за
    бумагу, эталон к нему отношения не имеет.
    """
    marks = Mark.objects.filter(task=task, submission__isnull=False)
    Submission.objects.filter(pk__in=marks.values("submission_id")).update(
        checked_at=None, checked_by=None
    )
    count, _ = marks.delete()
    return count


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

    tasks = Task.objects.filter(work__in=works).values_list(
        "id", "work_id", "open_for_answers"
    )
    task_to_work = {task_id: work_id for task_id, work_id, _ in tasks}

    counts = {
        work.pk: {
            "tasks": 0,
            "open": 0,
            "answers": 0,
            "unchecked": 0,
            "students": set(),
            "mine": set(),
        }
        for work in works
    }
    for _, work_id, open_for_answers in tasks:
        counts[work_id]["tasks"] += 1
        counts[work_id]["open"] += 1 if open_for_answers else 0

    submissions = Submission.objects.filter(task_id__in=task_to_work)
    if student is not None:
        submissions = submissions.filter(student=student)

    judged = set(
        Mark.objects.filter(submission__isnull=False).values_list(
            "submission_id", flat=True
        )
    )

    for submission_id, task_id, student_id in submissions.values_list(
        "id", "task_id", "student_id"
    ):
        row = counts[task_to_work[task_id]]
        row["answers"] += 1
        row["students"].add(student_id)
        row["mine"].add(task_id)
        if submission_id not in judged:
            row["unchecked"] += 1

    return {
        work_id: {
            "tasks": row["tasks"],
            # сколько вопросов принимают ответы: «есть ли тут что делать»
            # считается по ним, а не по числу задач вообще
            "open_tasks": row["open"],
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
    # присланная фотография — такое же событие для учителя, как ответ: класс
    # снимает тетради на уроке, и снимки обязаны появляться в таблице сами
    shots = Attachment.objects.filter(student_work__work=work).aggregate(
        total=Count("id"), last=Max("id")
    )

    return "|".join(
        str(part)
        for part in (
            tasks,
            numbers["total"],
            numbers["last"] and numbers["last"].timestamp(),
            numbers["checked"] and numbers["checked"].timestamp(),
            graded["rows"],
            graded["last"] and graded["last"].timestamp(),
            shots["total"],
            shots["last"],
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

    Открытых вопросов в метке ровно по той же причине: учитель открывает
    ячейку тогда, когда классу пора отвечать, — и поле ответа должно
    появиться само. Без этого числа опрос не замечал бы открытия вовсе:
    задач столько же, работу никто не сохранял.
    """
    cells = work.tasks.aggregate(
        total=Count("id"), open=Count("id", filter=Q(open_for_answers=True))
    )
    numbers = Submission.objects.filter(task__work=work, student=student).aggregate(
        total=Count("id"), last=Max("created_at"), checked=Max("checked_at")
    )
    # своя оценка — такое же неожиданное для него событие, как отметка
    graded = work.students.filter(student=student).aggregate(last=Max("updated_at"))
    # снимки его работы и заметки учителя на них. Снимки потому, что убрать
    # их может и учитель; заметки — потому, что они и есть проверка, и
    # прикреплённая к клетке фраза обязана доехать без F5.
    #
    # Мазков в метке нет намеренно: обводка меняется десятками штрихов
    # подряд, и метка дёргала бы страницу ученика всё время, пока учитель
    # рисует. Их читает сам просмотрщик — при открытии, разом с картинкой.
    shots = Attachment.objects.filter(
        student_work__work=work, student_work__student=student
    ).aggregate(total=Count("id"), last=Max("id"))
    pinned = PhotoNote.objects.filter(
        attachment__student_work__work=work,
        attachment__student_work__student=student,
    ).aggregate(total=Count("id"), last=Max("updated_at"))
    # приложенное к самому заданию: условия pdf'ом кладут ровно тогда, когда
    # классу пора их открыть, и ждать от ученика F5 тут значит не дать ему
    # условий вовсе. `updated_at` работы этого не ловит — вложение живёт
    # своей строкой и работу не трогает
    handout = Attachment.objects.filter(work=work).aggregate(
        total=Count("id"), last=Max("id")
    )

    return "|".join(
        str(part)
        for part in (
            cells["total"],
            cells["open"],
            work.updated_at.timestamp(),
            numbers["total"],
            numbers["last"] and numbers["last"].timestamp(),
            numbers["checked"] and numbers["checked"].timestamp(),
            graded["last"] and graded["last"].timestamp(),
            shots["total"],
            shots["last"],
            pinned["total"],
            pinned["last"] and pinned["last"].timestamp(),
            handout["total"],
            handout["last"],
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
        # `attachments` тут больше не нужен: снимки собирает `photos.sheets`
        # одним запросом на всю таблицу, а prefetch всё равно не помогал —
        # фильтр по месту внутри работы заставлял Django спрашивать заново
        for row in work.students.prefetch_related("marks")
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

    # снимки всей таблицы одним запросом: и те, что лежат на работе целиком
    # (столбец «работа ученика»), и те, что по задачам (точка в клетке). Из
    # одних данных, а не двумя проходами: в клетке это единственный знак,
    # по которому видно, что ученик сдал тетрадью, а не полем ответа
    shots = photos.sheets(work)

    students = []
    per_task = {task.pk: {"answered": 0, "correct": 0, "wrong": 0, "unchecked": 0} for task in tasks}

    for enrolment in rows:
        cells = []
        answered = correct = 0

        verdicts = verdicts_of(graded.get(enrolment.student_id))

        for task in tasks:
            history = journal[(task.pk, enrolment.student_id)]
            cell = cell_of(task, history, verdicts.get(task.pk))
            # сколько раз он встречал это условие в **других** работах: по
            # нему видно, что задача не новая, — и учителю, и в разговоре
            cell["seen_before"] = seen_before.get(
                (task.problem_id, enrolment.student_id), 0
            )
            cell["photos"] = len(
                shots.get(enrolment.student_id, {}).get("tasks", {}).get(task.pk, [])
            )
            cells.append(cell)
            if not history:
                continue

            answered += 1
            per_task[task.pk]["answered"] += 1

            # «решил» — это полный балл. Частичный не был доступен вовсе, пока
            # вердикт был галочкой, и складывать его с полным нельзя: колонка
            # отвечает на «кто справился», а не «кто что-то написал»
            value = cell["mark"]
            if value is None:
                per_task[task.pk]["unchecked"] += 1
            elif value >= task.maximum:
                correct += 1
                per_task[task.pk]["correct"] += 1
            else:
                per_task[task.pk]["wrong"] += 1

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
                # итог за работу: выведенный системой или поставленный
                # руками. Считается здесь, а не в браузере, по той же
                # причине, по которой там не считается состояние работы:
                # пороги живут в базе, и второй расчёт разошёлся бы с первым
                "grade": final_grade(work, mine),
                "papers": shots.get(enrolment.student_id, photos.empty_sheet())[
                    "work"
                ],
            }
        )

    columns = [
        {
            "id": task.pk,
            "position": task.position,
            # как вопрос назван: «1а», «324 из Галицкого» или номер по порядку
            "name": task.name,
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


def grade_source(work, row) -> tuple[int, int]:
    """
    Из чего система считает отметку: уровни по критериям или баллы за вопросы.

    Ось выбирает **вид системы**, а не наличие данных: у уровневой (MYP)
    отметка получается из суммы уровней, у балльной — из процента набранного
    за вопросы. Работа может нести обе оси разом, и спрашивать «где что-то
    есть» значило бы считать отметку то так, то этак у двух соседних учеников
    одной работы.
    """
    system = work.grading_system
    if system is None:
        return 0, 0

    if system.kind == GradingSystem.LEVELS:
        values, rows = marks_of(row), work.criteria.all()
    else:
        values, rows = scores_of(row), work.tasks.all()

    return sum(values.values()), sum(item.maximum for item in rows)


def final_grade(work, row) -> dict | None:
    """
    Итог за работу: что вывела система — и что сказал учитель.

    **Мнение учителя сильнее, и это правило, а не поблажка.** Пороги системы
    — хороший умолчательный ответ, но только умолчательный: работа бывает
    решена и списана, бывает на границе, где видно, что человек понял, и
    отвечает за отметку перед родителем учитель, а не таблица. Поэтому
    поставленное руками показывается вместо выведенного везде, где итог
    вообще показывается.

    Выведенное при этом **не прячется**: оно приезжает рядом (`derived`), и
    учитель видит, от чего отступил. Спрятать его значило бы превратить
    осознанное решение в незаметное расхождение.

    `None` — сказать нечего: системы нет и руками ничего не поставлено.
    """
    earned, top = grade_source(work, row)
    derived = grade_for(work.grading_system, earned=earned, top=top)
    mine = ((row.grade if row else "") or "").strip()

    if not mine and derived is None:
        return None

    return {
        "label": mine or derived["label"],
        # то, что вывела бы система: не подсказка, а вторая половина ответа
        "derived": derived["label"] if derived else None,
        "by_teacher": bool(mine),
        "system": work.grading_system.name if work.grading_system_id else None,
        "earned": earned,
        "top": top,
    }


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
                "name": item.name,
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


def grade(
    work,
    student,
    *,
    marks=None,
    scores=None,
    comment=None,
    by=None,
    answers=None,
    final=None,
):
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

    `answers` — `{вопрос: отправка}`, за какой именно ответ поставлен балл.
    Приходит только с проверки онлайн-ответа; у бумаги отправки нет вовсе.
    Не передали — прежняя ссылка **сохраняется**: учитель, поправивший балл
    рукой, судит тот же ответ, что и раньше, а не отвязывает его от оценки.
    """
    from django.db import transaction

    with transaction.atomic():
        row, _ = StudentWork.objects.get_or_create(work=work, student=student)
        if comment is not None:
            row.comment = comment
            row.save(update_fields=["comment", "updated_at"])

        # Итог руками. Пустая строка **снимает** его и возвращает работу
        # системе — то же движение, что и пустое поле у балла: снять и
        # поставить ноль это разные вещи, а «0» бывает отметкой.
        if final is not None:
            row.grade = final.strip()[:40]
            row.save(update_fields=["grade", "updated_at"])

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
                answer = (answers or {}).get(item.pk) if axis == "task" else None
                # тот же балл, но за **другой** ответ — это новая проверка, а
                # не пустая правка: учитель посмотрел присланное заново и
                # оценил так же. Пропустить её значило бы оставить ячейку с
                # пометкой «надо посмотреть» после того, как посмотрели
                same = (was.value if was else None) == value and (
                    answer is None or (was is not None and was.submission_id == answer.pk)
                )
                if same:
                    continue

                if value is None:
                    if was:
                        was.delete()
                elif was:
                    was.value = value
                    fields = ["value"]
                    if answer is not None:
                        was.submission = answer
                        fields.append("submission")
                    was.save(update_fields=fields)
                else:
                    Mark.objects.create(
                        student_work=row,
                        value=value,
                        submission=answer,
                        **{axis: item},
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


def check_answer(submission, *, value, by):
    """
    Балл за **конкретный ответ**. Ставится и снимается одним вызовом.

    Оценка живёт не на отправке, а на паре «ученик и вопрос» (`Mark`), и
    ссылкой помнит, за какой ответ поставлена. Из этого следует главное:
    ученик прислал новое — балл не перевешивается на него молча и не
    исчезает. Он остаётся тем, чем был, а ячейка показывает, что пришёл
    новый ответ и на него надо посмотреть. Решает человек.

    `None` — снять: учитель передумал или увидел, что смотрел не ту
    отправку. Попытку это не расходует, ответ ученика не трогает.

    Время и имя проверявшего остаются на самой отправке: они отвечают на
    другой вопрос — «когда и кто на неё смотрел», — и после снятия балла
    остаются правдой.
    """
    task = submission.task
    if value is not None and not 0 <= value <= task.maximum:
        api_error(
            Codes.MARK_OUT_OF_RANGE,
            f"The mark is above the maximum of {task.maximum}.",
            field="mark",
            maximum=task.maximum,
        )

    row = grade(
        task.work,
        submission.student,
        scores={task.pk: value},
        by=by,
        answers={task.pk: submission},
    )

    submission.checked_at = timezone.now() if value is not None else None
    submission.checked_by = by if value is not None else None
    submission.save(update_fields=["checked_at", "checked_by"])
    return row


def verdicts_of(student_work) -> dict:
    """`{id вопроса: (балл, за какой ответ)}` — то, из чего собирается клетка."""
    if student_work is None:
        return {}

    return {
        mark.task_id: (mark.value, mark.submission_id)
        for mark in student_work.marks.all()
        if mark.task_id is not None
    }


def cell_of(task, history, verdict=None) -> dict:
    """
    Одна клетка: последний ответ, балл за него и надо ли смотреть заново.

    `stale` — «пришёл новый ответ после того, как балл поставлен». Это весь
    ответ на гонку «учитель проверял, пока ученик отправлял», и решение тут
    другое, чем было: раньше ячейка гасла в «не проверено», теряя из виду
    поставленный балл. Теперь балл виден, а рядом с ним знак — надо
    посмотреть. Гасить оценку за то, что ученик прислал ещё раз, значит
    стирать работу учителя чужими руками.
    """
    value, judged = verdict if verdict else (None, None)

    if not history:
        # балл без единой отправки — это бумага: писали на листе, а не здесь
        return {
            "task": task.pk,
            "submission": None,
            "attempts": 0,
            "mark": value,
            "maximum": task.maximum,
            "stale": False,
        }

    last = history[-1]

    return {
        "task": task.pk,
        "submission": last.pk,
        "attempts": len(history),
        "answer": last.answer,
        "mark": value,
        "maximum": task.maximum,
        "at": last.created_at,
        "stale": value is not None and judged is not None and judged != last.pk,
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
                row.label = item.get("label", row.label)
                row.maximum = item.get("maximum", row.maximum)
                row.open_for_answers = item.get(
                    "open_for_answers", row.open_for_answers
                )
                row.save(
                    update_fields=[
                        "position", "label", "maximum", "open_for_answers"
                    ]
                )
            else:
                row = Task.objects.create(
                    work=work,
                    position=position,
                    label=item.get("label", ""),
                    maximum=item.get("maximum", 1),
                    open_for_answers=item.get("open_for_answers", True),
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


def my_grade(work, student, *, viewer=None) -> dict:
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
        # итог — по тому же правилу, что и баллы: `show_result` выключен —
        # до закрытия окна не видно ничего. Показывается ровно один ответ,
        # тот, что действует; «система вывела 4, а учитель поставил 5» —
        # разговор учителя с собой, а не с классом
        "grade": final_grade(work, row) if visible else None,
        "comment": (row.comment if row and visible else ""),
        "papers": photos.of_student(work, student, viewer=viewer)["work"],
    }


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
            second=row.second or {},
        )
        for row in work.scan_pages.all()
    ]


def max_mark_of(work) -> int | None:
    """Наибольший максимум среди вопросов работы — им проверяются прочитанные клетки."""
    values = [task.maximum for task in work.tasks.all()]
    return max(values) if values else None


def standing_marks(work) -> dict:
    """`{(ученик, позиция вопроса): балл}` — то, что уже стоит в базе."""
    positions = {task.pk: task.position for task in work.tasks.all()}

    return {
        (mark.student_work.student_id, positions[mark.task_id]): mark.value
        for mark in Mark.objects.filter(
            student_work__work=work, task__isnull=False
        ).select_related("student_work")
        if mark.task_id in positions
    }


def differing_marks(standing, student_id, read, names=None) -> list:
    """
    Что скан перепишет, и на что именно.

    Спрашивают об этом человека, а не решают за него, и по той же причине, по
    какой спрашивают о конфликте внутри пачки: одна задача с двумя разными
    баллами — не задача выбора, а факт, о котором надо знать. Здесь второй
    балл к тому же чужого происхождения: он мог быть поставлен за онлайн-ответ
    или прошлым разбором той же пачки.

    Совпадение молчит: повторный разбор той же пачки — обычное дело, и
    пятнадцать строк «было 3, пришло 3» превратили бы список в шум.
    """
    if student_id is None:
        return []

    out = []
    for position, value in sorted(read.items()):
        was = standing.get((student_id, position))
        if was is not None and was != value:
            out.append(
                {"question": question_name(names, position), "was": was, "now": value}
            )
    return out


def question_names(work) -> list[str]:
    """
    Как зовутся вопросы работы, по порядку клеток бланка.

    Клетка и вопрос связаны позицией, а не именем: третья клетка листа — это
    третий вопрос, как бы учитель его ни назвал. Поэтому имена едут отдельным
    списком рядом с баллами, а не ключами в них: ключ должен оставаться местом,
    иначе переименование вопроса потеряло бы уже прочитанные баллы.
    """
    return [task.name for task in work.tasks.all()]


def question_name(names, position: int) -> str:
    """Имя клетки: своё, если работа его знает, иначе номер по порядку."""
    if names and 0 <= position < len(names):
        return names[position]
    return str(position + 1)


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
    names = question_names(work)
    questions = len(names) or scanning.QUESTIONS

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
                # Тройка лучших — по самой странице. От пакета кандидаты
                # приходили пустыми всякий раз, когда пакет решился или был
                # собран постранично, и экран показывал вместо них первых по
                # списку класса — то есть заведомо не тех.
                "candidates": scanning.top_candidates(page, roster),
                # Второе чтение едет на экран целиком: человек решает спор,
                # глядя на обе версии и на бумагу, а не на наш вывод о том,
                # кто из читателей прав. Мы этого и не знаем.
                "second": page.second,
                "trouble": []
                if page.headerless
                else scanning.troubles(page, owner, limit, questions),
            }
        )
    by_index = {row["index"]: row for row in rows}

    # что уже стоит в базе по этим ученикам: балл мог быть поставлен онлайн
    # или прошлым разбором пачки, и молча переписать его нельзя
    standing = standing_marks(work)

    out_packets = []
    for number, packet in enumerate(packets):
        marks, conflicts = scanning.merge_marks(packet.pages)
        conflicts = [question_name(names, q) for q in conflicts]
        overwrites = differing_marks(standing, packet.student_id, marks, names)
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
        # лист, забранный из чужого пакета по своей подписи: переложили не
        # молча, а вслух — человек видит, что решение принято за него
        if packet.signed_apart:
            trouble.append("signed_apart")
            for index in packet.signed_apart:
                by_index[index]["trouble"].append("signed_apart")
        if packet.student_id is None:
            trouble = ["no_owner"] + [c for c in trouble if c != "no_owner"]
            for page in packet.pages:
                if "no_owner" not in by_index[page.index]["trouble"]:
                    by_index[page.index]["trouble"].append("no_owner")
        # Кандидаты пакета не затирают страничные: у пакета их может не быть
        # вовсе, а у страницы они есть всегда, когда на ней прочитано имя.
        for page in packet.pages:
            if not by_index[page.index]["candidates"]:
                by_index[page.index]["candidates"] = packet.candidates
        out_packets.append(
            {
                "number": number,
                "pages": [page.index for page in packet.pages],
                "conditions": [page.index for page in packet.conditions],
                "student": packet.student_id,
                "candidates": packet.candidates,
                "conflicts": conflicts,
                "overwrites": overwrites,
                "marks": {q + 1: value for q, value in marks.items()},
                "total": sum(marks.values()) if marks else 0,
                "trouble": trouble + (["mark_differs"] if overwrites else []),
            }
        )

    # Странице, на которой имени нет, предлагается хозяин предыдущей.
    #
    # Своего свидетельства у такой страницы нет вовсе, и кандидатов ей взять
    # неоткуда — список выходил пустым, а выбирать приходилось из всего класса.
    # Между тем пачка лежит стопкой: лист без подписи почти всегда продолжение
    # предыдущего, и это ровно та догадка, по которой раскладка кладёт такие
    # листы сама. Предлагаем, а не назначаем: подсказка стоит первой кнопкой,
    # решает человек.
    last_owner = None
    for row in rows:
        unnamed = not (row["first_name"].strip() or row["surname"].strip())
        if unnamed:
            # У безымянной страницы кандидаты пакета — набор случайных фамилий
            # с нулевым сходством: сравнивать было не с чем. Показывать их
            # значит предлагать людей наугад, да ещё и заслонять ими
            # единственную осмысленную подсказку.
            row["candidates"] = [last_owner] if last_owner is not None else []
        elif not row["candidates"] and last_owner is not None:
            row["candidates"] = [last_owner]
        if row["student"] is not None:
            last_owner = row["student"]

    students = []
    mine = {packet.student_id: packet for packet in packets if packet.student_id}
    for person in roster:
        packet = mine.get(person.id)
        marks, conflicts = scanning.merge_marks(packet.pages if packet else [])
        conflicts = [question_name(names, q) for q in conflicts]
        students.append(
            {
                "id": person.id,
                "name": person.full,
                "pages": sorted(page.index for page in (packet.all_pages if packet else [])),
                "marks": {q + 1: value for q, value in marks.items()},
                "total": sum(marks.values()) if marks else 0,
                "conflicts": conflicts,
                # Листы одного ученика лежат в стопке подряд — так их и
                # сдают. Разрыв почти всегда значит, что чужая страница
                # приписана ему по догадке: покрытие задач совпало, а работа
                # чужая. Само по себе это не отказ — пачку могли и
                # перемешать, — но сказать об этом надо: молча такое не
                # находится вовсе.
                "scattered": _scattered(packet.pages if packet else []),
                # Балл, который скан перепишет, называется до записи — и
                # называется он теперь у ученика, а не у пакета: разбор идёт
                # постранично, а «было 3, придёт 1» — это про итог человека,
                # а не про то, как листы сгруппировались по дороге.
                "overwrites": differing_marks(standing, person.id, marks, names),
            }
        )

    from vision import services as vision_services

    return {
        "pages": rows,
        "packets": out_packets,
        "students": students,
        "questions": questions,
        # подписи столбцов таблицы разбора: «1а», «324 из Галицкого» или номер
        # по порядку. Пустой список у работы, где вопросы ещё не заведены, —
        # тогда клетки зовутся своими номерами
        "question_names": names,
        "max_mark": limit,
        "conditions": sum(len(packet.conditions) for packet in packets),
        "doubts": [
            packet["number"] for packet in out_packets if "no_owner" in packet["trouble"]
        ],
        # цена показывается там же, где идёт чтение: узнавать её в другом
        # разделе, уже потратив, — не то же самое, что видеть по ходу
        "budget": vision_services.budget(work.course.school),
        # ...а «во что обошлась вот эта пачка» — вопрос отдельный от школьного
        # потолка, и ответ на него нужен там же, у пачки
        "spend": scan_spend(work),
    }


def _scattered(pages) -> bool:
    """Лежат ли листы ученика в стопке подряд."""
    if len(pages) < 2:
        return False
    places = sorted(page.index for page in pages)
    return places[-1] - places[0] + 1 != len(places)


def scan_spend(work) -> dict:
    """
    Во что обошлась эта пачка: сумма, число вызовов и разбивка по поводам.

    **Считается от начала пачки, а не за всё время работы.** Одну и ту же
    работу разбирают повторно — пересняли пачку, доложили забытые листы, — и
    сумма за всю историю отвечала бы на вопрос, которого никто не задавал.
    Началом считается самая ранняя из живущих строк `ScanPage`: они заводятся
    при первом чтении и уносятся применением, то есть живут ровно столько,
    сколько живёт пачка.

    Строки журнала не удаляются вместе с ними — журнал трат вечен, и `total`
    рядом отвечает «сколько эта работа стоила всего».
    """
    from django.db.models import Count, Sum

    from vision.models import AiSpend

    rows = AiSpend.objects.filter(work=work)
    total = rows.aggregate(sum=Sum("cost_micros"))["sum"] or 0

    started = (
        ScanPage.objects.filter(work=work)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    batch = rows.filter(created_at__gte=started) if started else rows.none()

    by_purpose = {
        row["purpose"]: {"micros": row["micros"] or 0, "calls": row["calls"]}
        for row in batch.values("purpose").annotate(
            micros=Sum("cost_micros"), calls=Count("id")
        )
    }

    return {
        "micros": sum(one["micros"] for one in by_purpose.values()),
        "calls": sum(one["calls"] for one in by_purpose.values()),
        "by_purpose": by_purpose,
        "total_micros": total,
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
    # Что увидел второй читатель. Кладём и тогда, когда он не ответил: «его не
    # было» — тоже сведение, и без него страница без второго мнения
    # неотличима от страницы, где второй читатель промолчал по ошибке.
    row.second = data.get("second") or {}
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
        # Человек вписал балл — значит перед ним сетка баллов, то есть лист
        # решения, что бы ни решил поиск шапки. Без этого проставленные руками
        # баллы пропадали молча: страница, сочтённая листом условий, в
        # раскладку не попадает вовсе, и её клетки никуда не едут.
        if row.headerless and any(value is not None for value in row.cells):
            row.headerless = False
            fields.append("headerless")
    # Спор двух читателей человеком и исчерпывается: он затем и показывается,
    # чтобы на страницу посмотрели глазами. Оставить пометку после правки
    # значило бы звать смотреть на то, что уже посмотрели, — а пометка,
    # которую нельзя снять, перестаёт что-либо значить уже к третьей странице.
    if fields and row.second.get("differs"):
        row.second = dict(row.second, differs=[])
        fields.append("second")
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
