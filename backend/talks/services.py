"""
Разговоры глазами экрана: список собеседников и лента одного разговора.

**Лента собирается по собеседнику, а не по поводу.** Человек помнит, с кем он
говорил, а не в какой из трёх таблиц это лежало: вопрос ученика о задаче и
ответ ему же «зайди после урока» — один разговор, и разложить их по двум
экранам значит заставить искать сказанное в двух местах.

Поэтому лента складывается из двух источников: разговоров (`Talk`) и тредов о
задаче (`works.Thread`). Заметки на снимке тетради в неё **не** входят, и это
решение, а не забывчивость: заметка приколота к точке на картинке, и «здесь
потерян минус» без «здесь» — не сообщение, а загадка. Читают их там, где видно
место, — в просмотрщике.
"""

from collections import defaultdict

from config.errors import Codes, api_error
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .access import my_talks, refuse_unless_allowed
from .models import Talk


def talk_with(user, other, child=None) -> Talk:
    """
    Разговор с этим человеком — заводится по требованию, как строка журнала.

    Пара нормализована по номеру: «Иванова с Петровым» и «Петров с Ивановой» —
    один разговор, и порядок в паре не должен заводить второй.
    """
    refuse_unless_allowed(user, other)

    lower, upper = sorted((user, other), key=lambda person: person.pk)
    talk, _ = Talk.objects.get_or_create(
        school_id=user.school_id, lower=lower, upper=upper, child=child
    )
    return talk


def say(user, other, *, text: str, child=None):
    """Написать. Пустое сообщение — не сообщение."""
    from works.models import Message

    text = (text or "").strip()
    if not text:
        api_error(Codes.MESSAGE_EMPTY, "There is nothing to send.", field="text")

    with transaction.atomic():
        talk = talk_with(user, other, child=child)
        message = Message.objects.create(
            talk=talk, author=user, to=other, text=text
        )
        # у разговора своя отметка времени: по ней он всплывает в списке, а
        # `auto_now` тут не сработает — правится не он, а его сообщение
        talk.updated_at = timezone.now()
        talk.save(update_fields=["updated_at"])

    return message


def _threads_between(user, other):
    """
    Треды о задачах, которые видят **эти двое**.

    Только пара «ученик и ведущий его курса»: у родителя права на разговор о
    задаче нет и сегодня (`works.threads.may_read`), и заводить его здесь
    задним числом значило бы открыть чужую переписку боком.
    """
    from schedule.models import Course
    from works.models import Thread

    family, staff = (user, other) if user.is_family else (other, user)
    if not (family.is_student and staff.is_teacher):
        return Thread.objects.none()

    return Thread.objects.filter(
        student=family, task__work__course__in=Course.objects.for_teacher(staff)
    )


def _messages_between(user, other):
    """Всё, что эти двое сказали друг другу, каким бы поводом оно ни было."""
    from works.models import Message

    pair = my_talks(user).filter(Q(lower=other) | Q(upper=other))

    return (
        Message.objects.filter(
            Q(talk__in=pair) | Q(thread__in=_threads_between(user, other))
        )
        .select_related("author", "talk", "thread", "thread__task")
        .order_by("created_at", "id")
    )


def conversation(user, other, *, mark_read=True) -> dict:
    """
    Лента разговора с этим человеком.

    Открытое считается прочитанным — и считается **здесь**, а не отдельной
    кнопкой: непрочитанное нужно затем, чтобы найти, где тебя ждут, а не
    затем, чтобы им управлять.
    """
    refuse_unless_allowed(user, other)

    rows = list(_messages_between(user, other))
    if mark_read:
        unread = [row.pk for row in rows if row.author_id != user.pk and not row.read_at]
        if unread:
            from works.models import Message

            Message.objects.filter(pk__in=unread).update(read_at=timezone.now())

    return {
        "person": _person(other),
        "messages": [_message(row, user) for row in rows],
    }


def ribbon(user) -> dict:
    """
    С кем этот человек говорил и кому может написать.

    Два списка, а не один: разговор, которого ещё не было, и разговор с
    непрочитанным — разные вещи, и мешать их в одном списке значит прятать
    второе за первым. Экран показывает начатые сверху, а остальных — в
    выборе собеседника.
    """
    from works.models import Message

    from .access import partners

    talks = list(my_talks(user).select_related("lower", "upper", "child"))
    people = {}
    last = {}
    unread = defaultdict(int)

    def note(person, message):
        """Собеседник в списке один, сколько бы поводов у разговора ни было."""
        people.setdefault(person.pk, person)
        if person.pk not in last or message.created_at > last[person.pk].created_at:
            last[person.pk] = message
        if message.author_id != user.pk and not message.read_at:
            unread[person.pk] += 1

    for talk in talks:
        # собеседник попадает в список и до первого слова: разговор заведён
        people.setdefault(talk.other_side(user).pk, talk.other_side(user))

    for message in Message.objects.filter(talk__in=talks).select_related(
        "talk", "talk__lower", "talk__upper", "author"
    ):
        note(message.talk.other_side(user), message)

    # треды о задачах — те же собеседники, и второй строки в списке они не
    # заводят: разговор с человеком один
    for thread in _readable_threads(user).select_related(
        "student", "task__work__course"
    ):
        person = _counterpart_of_thread(user, thread)
        if person is None:
            continue
        for message in thread.messages.select_related("author"):
            note(person, message)

    started = [
        _person(person)
        | {
            "last": _message(last[person.pk], user) if person.pk in last else None,
            "unread": unread.get(person.pk, 0),
        }
        for person in people.values()
    ]
    started.sort(key=lambda row: (row["last"] or {}).get("at") or "", reverse=True)

    return {
        "started": started,
        # кому можно написать первым — целиком, включая тех, с кем уже говорят:
        # выбор собеседника отвечает на «кому можно», а не «с кем ещё не начали»
        "partners": [_person(person) for person in partners(user)],
    }


def _readable_threads(user):
    """Треды о задачах, которые этот человек вправе читать."""
    from schedule.models import Course
    from works.models import Thread

    if user.is_student:
        return Thread.objects.filter(student=user)
    if user.is_teacher:
        return Thread.objects.filter(
            task__work__course__in=Course.objects.for_teacher(user)
        )
    return Thread.objects.none()


def _counterpart_of_thread(user, thread):
    """
    Кто по ту сторону треда о задаче.

    У ученика это ведущий курса, у учителя — сам ученик. Роль, а не
    сохранённая пара: курс меняет ведущего, и прежний разговор не должен
    оставаться у человека, который его больше не ведёт.
    """
    from schedule.models import CourseAssignment

    if user.is_teacher:
        return thread.student

    row = CourseAssignment.objects.filter(
        course_id=thread.task.work.course_id
    ).select_related("teacher").first()
    return row.teacher if row else None


def _person(person) -> dict:
    return {
        "id": person.pk,
        "name": person.get_full_name() or person.email,
        "kind": person.kind,
    }


def _message(message, me=None) -> dict:
    return {
        "id": message.pk,
        "author": message.author_id,
        "author_name": (message.author and message.author.get_full_name()) or "",
        # «моё ли это» считает сервер, а не экран: у экрана свой номер под
        # рукой не всегда, а ответ тут один и тот же для всех, кто смотрит
        "mine": bool(me is not None and message.author_id == me.pk),
        "text": message.text,
        "at": message.created_at,
        "read_at": message.read_at,
        # Повод, если он есть: по нему экран рисует ссылку к работе. Пусто —
        # разговор без повода, и вести из него некуда.
        "task": message.thread.task_id if message.thread_id else None,
        "work": message.thread.task.work_id if message.thread_id else None,
    }
