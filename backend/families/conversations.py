"""
Кто с кем может говорить и кто это читает.

Право тут **по участию**, а не по виду пользователя, — тот же приём, что у
разговора о задаче (`works/threads.py`). Родитель читает свои треды, учитель —
те, где собеседник он. Администратор школы сюда не входит намеренно: право
чинить курсы не то же самое, что право читать чужую переписку о ребёнке.
"""

from config.errors import Codes, api_error
from django.db import transaction
from schedule.models import CourseAssignment, CourseStudent

from .models import FamilyMessage, FamilyThread, Guardianship


def teachers_for(child):
    """
    С кем родителю есть о чём говорить: ведущие курсов, где ребёнок учится.

    Берутся **действующие** зачисления: список «кому написать» — это про
    сегодня, а прошлогодний учитель в нём был бы предложением, за которым
    ничего не стоит. Прежние разговоры при этом никуда не деваются и
    читаются — они уже состоялись.
    """
    courses = CourseStudent.objects.filter(
        student=child, removed_at__isnull=True
    ).values_list("course_id", flat=True)

    # Курс в таблице назначений встречается один раз (`one_teacher_per_course`),
    # но `related_name` у неё множественный, и полагаться на «ровно один» тут
    # незачем: берём всех, кто там стоит, и схлопываем повторы — один учитель
    # ведёт у ребёнка и алгебру, и геометрию.
    seen, out = set(), []
    for row in (
        CourseAssignment.objects.filter(course_id__in=courses)
        .select_related("teacher")
        .order_by("teacher__last_name", "teacher__email")
    ):
        if row.teacher_id in seen:
            continue
        seen.add(row.teacher_id)
        out.append(row.teacher)
    return out


def may_read(user, thread) -> bool:
    """Свой тред — участнику. Третьего читателя у разговора нет."""
    return user.pk in (thread.parent_id, thread.teacher_id)


def refuse_unless_allowed(user, thread) -> None:
    if not may_read(user, thread):
        api_error(
            Codes.ATTACHMENT_FORBIDDEN,
            "That conversation is not yours.",
            field="thread",
        )


def open_thread(*, parent, teacher, child) -> FamilyThread:
    """
    Тред заводится по требованию: пока не заговорили, его нет.

    Проверяется здесь ровно то, чего не выразить ограничением: что это
    действительно ребёнок этого родителя и что учитель действительно ведёт
    курс, где ребёнок учится. Без второй проверки родитель писал бы любому
    сотруднику школы, а список собеседников превратился бы в справочник.
    """
    if not Guardianship.objects.filter(parent=parent, child=child).exists():
        api_error(Codes.NOT_YOUR_CHILD, "No such child of yours.", field="child")

    if teacher.pk not in {one.pk for one in teachers_for(child)}:
        api_error(
            Codes.NOT_A_TEACHER_OF_THIS_CHILD,
            "This teacher does not teach your child.",
            field="teacher",
        )

    thread, _ = FamilyThread.objects.get_or_create(
        parent=parent, teacher=teacher, child=child
    )
    return thread


def say(thread, *, author, text: str) -> FamilyMessage:
    """Написать в тред. Пустое сообщение — не сообщение."""
    text = (text or "").strip()
    if not text:
        api_error(Codes.MESSAGE_EMPTY, "There is nothing to send.", field="text")

    with transaction.atomic():
        message = FamilyMessage.objects.create(
            thread=thread, author=author, text=text
        )
        # у треда своя отметка времени: по ней он всплывает в списке, и
        # `auto_now` тут не сработает — правится не он, а его сообщение
        FamilyThread.objects.filter(pk=thread.pk).update(
            updated_at=message.created_at
        )

    return message


def threads_of(user):
    """Разговоры этого человека — с любой стороны, свежие сверху."""
    side = (
        {"parent": user} if user.is_parent else {"teacher": user}
    )
    return FamilyThread.objects.filter(**side).select_related(
        "parent", "teacher", "child"
    )


def payload(thread, *, unread_for=None) -> dict:
    messages = list(thread.messages.select_related("author"))
    return {
        "id": thread.pk,
        "parent": _person(thread.parent),
        "teacher": _person(thread.teacher),
        "child": _person(thread.child),
        "updated_at": thread.updated_at,
        "messages": [
            {
                "id": row.pk,
                "author": _person(row.author),
                "mine": unread_for is not None and row.author_id == unread_for.pk,
                "text": row.text,
                "created_at": row.created_at,
            }
            for row in messages
        ],
    }


def _person(user) -> dict:
    full = " ".join(filter(None, (user.first_name, user.last_name))) or user.email
    return {"id": user.pk, "name": full, "kind": user.kind}
