"""
Пересылка обращений тому, кто их разбирает.

Письмо — не хранилище, а **уведомление**: сообщение уже лежит в базе и
никуда не денется, а письмо только говорит «пришло новое». Отсюда всё
остальное устройство: отправка не в транзакции, отказ почты не роняет
обращение, и повторов нет.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def recipients():
    """
    Кому пересылать: суперпользователи, которые сами об этом попросили.

    Настройка живёт на человеке (`User.forward_feedback`), а не в конфиге
    сервера: суперпользователей может быть несколько, и «кому идут письма»
    решает каждый за себя. Пустой список — обычное состояние, а не поломка:
    страница обращений работает и без единого письма.
    """
    from accounts.models import User

    return list(
        User.objects.filter(is_superuser=True, forward_feedback=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def describe(message) -> tuple[str, str]:
    """Тема и тело письма. Отдельной функцией — её и проверяют тесты."""
    who = message.author.email if message.author_id else "аноним"
    school = message.school.name if message.school_id else "без школы"
    subject = f"[lesson-tracker] {message.get_kind_display()} от {who}"
    body = "\n".join(
        [
            f"Вид: {message.get_kind_display()}",
            f"От: {who} ({school})",
            f"Страница: {message.page or 'не названа'}",
            "",
            message.text,
        ]
    )
    return subject, body


def forward(message) -> int:
    """
    Разослать уведомление. Возвращает число **ушедших** писем.

    Не число адресатов: с `fail_silently` они расходятся молча, и разошлись
    бы ровно там, где это важно знать.

    `fail_silently` здесь обязателен и объяснён: почта — внешняя система,
    и её недоступность не должна отменять уже принятое обращение. Человек
    нажал «отправить», сообщение записано; ответ «не удалось» отправил бы
    его писать заново то, что уже дошло.
    """
    people = recipients()
    if not people:
        return 0

    subject, body = describe(message)
    try:
        sent = send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None) or None,
            people,
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 — почта не должна ронять запись
        logger.exception("feedback: не удалось переслать обращение %s", message.pk)
        return 0

    # `fail_silently` гасит отказ — и вместе с ним всякий след того, что
    # письмо не ушло. Отказ проглочен, лог чист, обращение лежит на своей
    # странице: снаружи это неотличимо от доставленного письма, и «почему мне
    # ничего не приходит» становится вопросом без единой зацепки. Поэтому
    # смотрим, что вернул сам `send_mail`, а не считаем адресатов: он и есть
    # ответ «сколько ушло».
    if not sent:
        logger.warning(
            "feedback: обращение %s не переслано — почта промолчала, адресатов %d",
            message.pk,
            len(people),
        )
        return 0

    return sent
