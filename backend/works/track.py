"""
След ученика: что он решал, где и чем это кончилось.

**Перекрёсток попытки.** Попытка (`Submission`) стоит на пересечении ученика и
**ячейки**, а не задачи: ячейка — это работа плюс условие, и через неё
достаются обе стороны.

    ученик ──┐
             ├── попытка ── ячейка ──┬── работа  ── курс ── учитель
    условие ─┘                       └── условие

Учитель в этом перекрёстке не участвует вовсе — он появляется только как
`checked_by` у отметки: кто проверил. Это намеренно: работа принадлежит курсу,
а не человеку, и смена ведущего не должна переписывать чужие ответы.

Отсюда и берётся всё в этом модуле: **след** — это попытки ученика, собранные
по условиям, а не по работам. За годы учёбы он и складывается в «что этот
человек решал», причём условие остаётся тем же объектом, сколько бы раз его ни
спрашивали — ровно ради этого ячейка и держит ссылку, а не копию текста.
"""

from collections import defaultdict

from django.db.models import Max

from .models import Mark, Submission


def solved_before(problems, students, *, besides=None) -> dict:
    """
    Кто из этих учеников уже решал эти условия — раньше и не в этой работе.

    Отвечает `{(problem_id, student_id): сколько раз}`. Одним запросом на всё,
    потому что спрашивают это про таблицу целиком: тридцать учеников на десять
    задач — триста вопросов, и по запросу на клетку экран бы не открылся.
    """
    found = Submission.objects.filter(
        task__problem__in=problems, student__in=students
    ).exclude(task__work=besides)

    counted = defaultdict(int)
    for row in found.values("task__problem_id", "student_id"):
        counted[(row["task__problem_id"], row["student_id"])] += 1
    return counted


def seen_by(student, problem, *, besides=None) -> list[dict]:
    """
    Где этот ученик уже встречал это условие — с самого начала и до сих пор.

    Порядок обратный: спрашивают «когда в последний раз», а не «когда впервые».
    """
    found = (
        Submission.objects.filter(task__problem=problem, student=student)
        .exclude(task__work=besides)
        .select_related("task", "task__work", "task__work__course")
        .order_by("-created_at")
    )

    # «справился ли» — это полный балл за тот ответ. Отдельным запросом на всю
    # выборку: по запросу на попытку экран открывался бы столько раз, сколько
    # раз ученик встречал условие
    judged = dict(
        Mark.objects.filter(submission__in=found).values_list("submission_id", "value")
    )

    seen = {}
    for row in found:
        work = row.task.work
        seen.setdefault(
            work.pk,
            {
                "work": work.pk,
                "title": work.title,
                "course": work.course.name,
                "when": row.created_at,
                "closed": work.state() == "closed",
                "attempts": 0,
                # вердикт последней попытки в той работе: он и есть ответ на
                # «справился ли». Полный балл — справился, неполный и ноль —
                # нет, балла нет вовсе — не проверяли
                "was_right": (
                    None
                    if row.pk not in judged
                    else judged[row.pk] >= row.task.maximum
                ),
            },
        )
        seen[work.pk]["attempts"] += 1

    return list(seen.values())


def track(student, *, courses=None) -> list[dict]:
    """
    Полный след: каждое условие, которое ученик решал, и чем это кончилось.

    Собирается по **условиям**, а не по работам: вопрос тут «что он решал», и
    задача, спрошенная трижды в трёх работах, — одна строка с тремя встречами.

    `courses` сужает до тех курсов, которые вправе видеть спрашивающий: учителю
    показываются только его, а ученику — свои целиком. Ограничение приходит
    снаружи, потому что права — не дело этого модуля.
    """
    attempts = Submission.objects.filter(student=student).select_related(
        "task", "task__problem", "task__work", "task__work__course"
    )
    if courses is not None:
        attempts = attempts.filter(task__work__course__in=courses)

    marks = {
        row["task_id"]: row["value"]
        for row in Mark.objects.filter(
            student_work__student=student, task__isnull=False
        ).values("task_id", "value")
    }

    judgements = dict(
        Mark.objects.filter(submission__student=student).values_list(
            "submission_id", "value"
        )
    )

    rows = {}
    for attempt in attempts.order_by("created_at"):
        problem = attempt.task.problem
        if problem is None:
            # ячейка без условия: решали то, что было на бумаге, и сказать про
            # это в следе нечего
            continue

        row = rows.setdefault(
            problem.pk,
            {
                "problem": problem.pk,
                "text": problem.text,
                "stem": problem.parent.text if problem.parent_id else "",
                "times": 0,
                "first": attempt.created_at,
                "last": attempt.created_at,
                "works": [],
                "right": 0,
                "wrong": 0,
                "score": None,
            },
        )
        row["times"] += 1
        row["last"] = attempt.created_at
        # балл за **эту** попытку: полный — справился, неполный и ноль — нет.
        # Балла нет вовсе — попытку не проверяли, и в счёт она не идёт
        judged = judgements.get(attempt.pk)
        if judged is not None:
            if judged >= attempt.task.maximum:
                row["right"] += 1
            else:
                row["wrong"] += 1
        if attempt.task.work_id not in [one["id"] for one in row["works"]]:
            row["works"].append(
                {
                    "id": attempt.task.work_id,
                    "title": attempt.task.work.title,
                    "course": attempt.task.work.course.name,
                }
            )
        if attempt.task_id in marks:
            row["score"] = marks[attempt.task_id]

    return sorted(rows.values(), key=lambda row: row["last"], reverse=True)


def summary(rows) -> dict:
    """
    Числа следа: сколько условий, сколько попыток, сколько взято с первого раза.

    Считается **из тех же строк**, которыми нарисован след, а не вторым
    проходом по журналу: два расчёта над одними данными расходятся молча.
    """
    if not rows:
        return {"problems": 0, "attempts": 0, "right": 0, "repeated": 0}

    return {
        "problems": len(rows),
        "attempts": sum(row["times"] for row in rows),
        "right": sum(1 for row in rows if row["right"]),
        # условия, которые спрашивали больше одного раза: по ним и видно, что
        # человек прошёл дважды
        "repeated": sum(1 for row in rows if len(row["works"]) > 1),
    }
