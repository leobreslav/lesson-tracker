"""
Условие ячейки: одно место, где оно задаётся и правится.

Ячейка работы своего текста не хранит — текст живёт в условии (`bank.Problem`),
и условие это одно и то же, набрано оно в работе на бегу или взято из общего
каталога. Разница только в том, где оно лежит: у одного есть строка в книге, у
другого нет, и лежит оно в самой работе — как в источнике.

Отсюда три состояния ячейки, и все три законны:

    пусто            условия нет вовсе — лист у ученика на парте
    своё             личное условие, лежащее только в этой работе
    из каталога      ссылка на общее условие, которое правит не он

Главное правило здесь — **правка называет цену и умолчание следует за ней**.
Пока по условию никто не отвечал, правка идёт везде: это опечатка, и чинить её
надо во всех местах разом. Как только появились чужие ответы, умолчание
переключается на копию: переписать условие, по которому уже писали, значит
переписать прошлое, и делать это молча нельзя. Чужое и системное условие
правится только копией всегда — прав на него нет.
"""

from bank.models import Problem
from config.errors import Codes, api_error
from django.db import transaction

EVERYWHERE = "everywhere"
COPY = "copy"


def statement_of(task) -> str:
    """Текст ячейки — пустая строка, если условия ещё нет."""
    return task.problem.text if task.problem_id else ""


def answers_of(task) -> list:
    return list(task.problem.answers) if task.problem_id else []


def cost(problem) -> dict:
    """
    Во что обойдётся правка этого условия: где оно спрошено и сколько ответов.

    Числа считаются по **всем** работам, а не только по своим: цена правки не
    становится меньше оттого, что часть работ чужие. А вот показывать, чьи они,
    нельзя — про чужой курс банк не рассказывает.
    """
    from .models import Submission, Task

    if problem is None:
        return {"works": 0, "answers": 0}

    tasks = Task.objects.filter(problem=problem)
    return {
        "works": tasks.values("work_id").distinct().count(),
        "answers": Submission.objects.filter(task__in=tasks).count(),
    }


def say(task, *, text=None, answers=None, user, mode=None):
    """
    Сказать, что за условие стоит в этой ячейке.

    `user` обязателен: у условия всегда есть автор, и вызов без него — не
    состояние, а описка в коде.

    Возвращает условие (может быть новым) или `None`, если сказать было нечего
    и ячейка осталась пустой.
    """
    text = task.problem.text if text is None and task.problem_id else (text or "")
    answers = (
        answers_of(task) if answers is None else [str(one) for one in answers]
    )

    if not text and not answers:
        # Ничего не сказано: пустая ячейка остаётся пустой, а условия с пустым
        # текстом мы не заводим — оно ничем не отличалось бы от «ещё не
        # придумали» и засоряло бы поиск.
        return task.problem

    if task.problem_id is None:
        return _write(task, _make(task, text, answers, user))

    problem = task.problem
    if problem.text == text and list(problem.answers) == answers:
        return problem

    mine = Problem.objects.writable_by(user).filter(pk=problem.pk).exists()
    if not mine:
        # Чужое условие правится только копией, и спрашивать тут нечего:
        # другого исхода нет.
        return _write(task, _fork(task, problem, text, answers, user))

    price = cost(problem)
    chosen = mode or (EVERYWHERE if price["answers"] == 0 else COPY)
    if chosen not in (EVERYWHERE, COPY):
        raise api_error(
            Codes.STATEMENT_MODE_UNKNOWN,
            "Непонятно, править условие везде или сделать копию.",
            field="mode",
        )

    if chosen == COPY:
        return _write(task, _fork(task, problem, text, answers, user))

    problem.text = text
    problem.answers = answers
    problem.save(update_fields=["text", "answers"])
    return problem


def _make(task, text, answers, user):
    """
    Новое условие, лежащее только в этой работе.

    Личное по построению: школа курса, владелец — тот, кто набрал. В книгу оно
    не кладётся, и это и значит «не хранить в библиотеке»: строки в оглавлении
    просто нет.
    """
    return Problem.objects.create(
        school=task.work.course.school,
        owner=user,
        created_by=user,
        text=text,
        answers=answers,
    )


def _fork(task, problem, text, answers, user):
    """Своя копия с пометкой, от чего произошла: прошлое остаётся как было."""
    return Problem.objects.create(
        school=task.work.course.school,
        owner=user,
        created_by=user,
        text=text,
        answers=answers,
        copied_from=problem,
    )


def _write(task, problem):
    with transaction.atomic():
        task.problem = problem
        task.save(update_fields=["problem"])
    return problem


def take(task, problem, *, user):
    """
    Накатить на ячейку готовое условие из банка.

    Случай самый обычный: работу собрали пустыми ячейками — условия были на
    бумаге, искать поленились, — а потом третью ячейку заполнили не руками, а
    взяли задачу из каталога. Ячейка та же, позиция и цена в баллах те же,
    меняется только то, на что она показывает.

    **Вердикты при этом снимаются.** Ответ ученика — его слова, и трогать их
    нельзя; а вердикт — наше суждение о **ответе на этот вопрос**, и после
    подмены вопроса он относится неизвестно к чему. Тот же приём и та же
    причина, что у «перепроверить»: полкласса проверено по не тому эталону.

    `problem=None` очищает ячейку: пустая ячейка — законное состояние, и путь
    к нему должен быть тем же, каким из него выходят.
    """
    from . import services

    if task.problem_id == (problem.pk if problem else None):
        return task.problem

    with transaction.atomic():
        task.problem = problem
        task.save(update_fields=["problem"])
        services.reset_verdicts(task)

    return problem
