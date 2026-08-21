"""
Работа, собранная из банка.

Ради этого банк и строился: учитель набирает задачи поиском или из книги и
объявляет их работой в таком-то курсе, на таком-то занятии.

Ячейка держит **ссылку** на условие, а не его копию: задача, набранная в
работе руками, и задача из общего каталога — одно и то же, и второго текста у
работы нет. Правка условия поэтому доезжает всюду, где его спросили, — а там,
где это дорого (по нему уже отвечали), правка не идёт молча: цена называется, и
умолчание переключается на копию. Живёт это правило в `statements.py`, одним
местом на все пути.
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
    """Одна задача банка — в работу: ячейка со ссылкой, и больше ничего."""
    return Task.objects.create(work=work, position=position, problem=problem)


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
