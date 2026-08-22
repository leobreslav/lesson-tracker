"""
Разговор о задаче: кто его видит и кто может писать.

Право тут не «по виду пользователя», а по участию: **свой тред читает ученик,
все треды курса — тот, кто его ведёт** (и администратор школы, который чинит
содержание курсов). Поэтому проверка смотрит на пару «задача и ученик», а не на
роль вообще.
"""

from config.errors import Codes, api_error
from django.db import transaction
from schedule.models import Course

from .models import Message, Thread


def may_read(user, task, student_id: int) -> bool:
    """Свой тред — ученику, все треды курса — ведущему и администратору."""
    if user.kind == "student":
        return user.pk == student_id

    return Course.objects.writable_by(user).filter(pk=task.work.course_id).exists()


def refuse_unless_allowed(user, task, student_id: int) -> None:
    if not may_read(user, task, student_id):
        api_error(
            Codes.ATTACHMENT_FORBIDDEN,
            "That conversation is not yours.",
            field="student",
        )


def open_thread(task, student_id: int) -> Thread:
    """Тред заводится по требованию: пока не спросили, его нет."""
    thread, _ = Thread.objects.get_or_create(task=task, student_id=student_id)
    return thread


def say(task, *, student_id: int, author, text: str, to=None) -> Message:
    """Написать в тред. Пустое сообщение — не сообщение."""
    text = (text or "").strip()
    if not text:
        api_error(Codes.MESSAGE_EMPTY, "There is nothing to send.", field="text")

    with transaction.atomic():
        thread = open_thread(task, student_id)
        message = Message.objects.create(
            thread=thread, author=author, to=to, text=text
        )
        # у треда своя отметка времени: по ней он всплывает в списке, и
        # `auto_now` тут не сработает — правится не он, а его сообщение
        thread.save(update_fields=["updated_at"])

    return message


def payload(thread) -> dict:
    return {
        "id": thread.pk,
        "task": thread.task_id,
        "student": thread.student_id,
        "updated_at": thread.updated_at,
        "messages": [
            {
                "id": message.pk,
                "author": message.author_id,
                "author_name": (message.author and message.author.get_full_name()) or "",
                "to": message.to_id,
                "text": message.text,
                "at": message.created_at,
                "read_at": message.read_at,
            }
            for message in thread.messages.select_related("author")
        ],
    }
