"""
Работа, собранная из банка.

Ради этого банк и строился: учитель набирает задачи поиском или из книги и
объявляет их работой в таком-то курсе, на таком-то занятии.

Главное решение здесь — **в работу кладётся снимок условия, а не живая
ссылка**, и оно стоит объяснения, потому что соблазн ровно обратный.

Живая ссылка выглядит экономнее и чинит опечатки разом: поправил условие в
банке — поправилось везде. Но работа это **запись о том, что ученики решали**,
и у неё есть ответы, отметки и разбор. Поменяли в банке числа — и мартовская
контрольная задним числом стала другой: ответы к ней перестают сходиться, а
сказать об этом некому. Правка условия в банке — обычное дело (условие
уточняют, числа меняют, задачу переписывают под другой класс), и цена этой
экономии оказалась бы в подделанном прошлом.

Поэтому у задачи работы своё условие, а ссылка на банк отвечает на **другой**
вопрос: откуда взято. Из неё получаются две вещи, которых иначе не было бы
вовсе: «где эта задача уже спрашивалась» на странице условия и честная
пометка «в банке условие изменилось» — расхождение **называется**, а не
подгоняется молча в ту или другую сторону.
"""

from bank.models import Problem
from config.errors import Codes, api_error
from django.db import transaction
from django.utils import timezone

from . import services
from .models import Task, Work

# Окно по умолчанию — неделя. Число тут не истина, а годная заготовка: окно
# правят в настройках, и правят почти всегда. Ноль-длины окно было бы хуже:
# работа, которой для ученика не существует ни секунды, читается как «сборка
# не сработала».
DEFAULT_DAYS = 7


def assemble(course, *, problems, title, user, slot=None, is_homework=False, when=None):
    """
    Объявить набор задач работой курса.

    Одной транзакцией: половина собранной работы — это работа, в которой часть
    задач молча отсутствует, и какая именно, снаружи не видно.
    """
    chosen = _ordered(problems, user)
    if not chosen:
        raise api_error(
            Codes.WORK_NOTHING_TO_ASSEMBLE,
            "Не выбрано ни одной задачи: собирать нечего.",
            field="problems",
        )

    now = when or timezone.now()
    opens = _opens_at(slot, now)
    with transaction.atomic():
        work = Work.objects.create(
            course=course,
            created_by=user,
            title=title.strip() or _title_of(slot, now),
            opens_at=opens,
            closes_at=opens + timezone.timedelta(days=DEFAULT_DAYS),
            is_homework=is_homework,
            slot=slot,
        )
        for position, problem in enumerate(chosen):
            take(problem, work=work, position=position)

    return work


def add(work, *, problems, user):
    """Дописать задачи из банка в конец готовой работы."""
    chosen = _ordered(problems, user)
    start = services.next_position(work)

    with transaction.atomic():
        made = [
            take(problem, work=work, position=start + offset)
            for offset, problem in enumerate(chosen)
        ]
    return made


def take(problem, *, work, position) -> Task:
    """
    Одна задача банка — в работу: снимок условия плюс ссылка на происхождение.

    Ответ переезжает эталоном, если он есть: у банка он один и короткий, а у
    задачи работы их список — «x+3» и «3+x» одинаково верны, и первый из них
    как раз приезжает отсюда.
    """
    return Task.objects.create(
        work=work,
        position=position,
        question=problem.text,
        answers=[problem.answer] if problem.answer else [],
        problem=problem,
    )


def _ordered(problems, user):
    """
    Задачи в том порядке, в каком их назвали.

    Порядок — это решение учителя (он ставил задачи по возрастанию
    сложности), и терять его на выборке из базы нельзя. Чужая задача просто не
    находится: видимость спрашивается тем же `visible_to`, что и везде.
    """
    ids = [int(one) for one in problems]
    found = {
        problem.pk: problem
        for problem in Problem.objects.visible_to(user).filter(pk__in=ids)
    }
    return [found[one] for one in ids if one in found]


def _opens_at(slot, now):
    """
    Когда работа появится у ученика.

    Названо занятие — с начала того дня, и это важнее, чем кажется:
    черновиков у работы нет, видимость задаёт окно, и «открыть сейчас»
    означало бы, что контрольная, собранная за неделю до урока, всю неделю
    висит у класса на виду. Собирают её заранее как раз затем, чтобы этого не
    было.

    Занятия нет — работу задают сейчас, и открыта она сейчас.
    """
    if slot is None:
        return now

    from datetime import datetime, time

    return timezone.make_aware(datetime.combine(slot.date, time.min))


def _title_of(slot, now):
    """Имя по умолчанию — дата: работа без названия в списке неотличима от соседей."""
    day = slot.date if slot else now.date()
    return f"Работа {day:%d.%m}"


def stale(work) -> dict:
    """
    Где условие в банке ушло вперёд снимка.

    Отвечает `{task_id: текст из банка}`. Показывается это пометкой, а не
    правится само: обновить условие задачи, по которой уже писали, — решение
    учителя, а не следствие чужой правки.
    """
    return {
        task.pk: task.problem.text
        for task in work.tasks.select_related("problem")
        if task.problem_id and task.problem.text != task.question
    }


def refresh(task) -> Task:
    """Взять условие из банка заново — по прямой просьбе."""
    if not task.problem_id:
        raise api_error(
            Codes.TASK_NOT_FROM_BANK,
            "Эта задача не из банка: обновлять её неоткуда.",
            field="id",
        )
    task.question = task.problem.text
    task.save(update_fields=["question"])
    return task


def asked_in(problem, user) -> list[dict]:
    """
    Где эту задачу уже спрашивали — среди **своих** курсов.

    Чужие работы не показываются, и это не осторожность ради осторожности:
    «в 9Б её решали в марте» — сведение о чужом курсе, а банк общий. Своих
    достаточно для того, ради чего список и нужен: не задать одно и то же
    дважды.
    """
    from schedule.models import Course

    mine = Course.objects.for_teacher(user)
    return [
        {
            "work": task.work_id,
            "title": task.work.title,
            "course": task.work.course.name,
            # День, а не отметка времени: вопрос тут «когда задавали», и
            # отвечает на него занятие, если работа к нему привязана, — оно
            # правдивее окна, которое учитель мог открыть накануне вечером.
            "date": task.work.slot.date if task.work.slot_id else task.work.opens_at.date(),
        }
        for task in (
            Task.objects.filter(problem=problem, work__course__in=mine)
            .select_related("work", "work__course", "work__slot")
            .order_by("-work__opens_at")
        )
    ]
