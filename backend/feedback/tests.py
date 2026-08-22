"""
Пересылка обращений: письмо — уведомление, а не хранилище.

Права проверяются в матрице (`schools/test_access.py`, `FeedbackTests`) —
там, где живут все ответы на вопрос «кому можно». Здесь остальное: кому
уходит письмо, что в нём написано и что бывает, когда почта молчит.
"""

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_school, make_user, sign_in

from .models import Message
from .services import describe, forward, recipients


class RecipientsTests(TestCase):
    def setUp(self):
        self.school = make_school("Test school")

    def test_only_superusers_who_asked_for_it(self):
        """
        Настройка живёт на человеке, а не в конфиге сервера.

        Суперпользователей бывает несколько, и получать письмо на каждое
        обращение хочет не каждый; а обычный пользователь, поставивший себе
        флаг руками через API, письма получать не должен тем более — читать
        чужие обращения ему нечем.
        """
        make_user(self.school, "root@example.com", root=True).__class__.objects.filter(
            email="root@example.com"
        ).update(forward_feedback=True)
        make_user(self.school, "quiet-root@example.com", root=True)
        teacher = make_user(self.school, "teacher@example.com")
        teacher.forward_feedback = True
        teacher.save(update_fields=["forward_feedback"])

        self.assertEqual(recipients(), ["root@example.com"])


class ForwardingTests(TestCase):
    def setUp(self):
        self.school = make_school("Test school")
        self.author = make_user(self.school, "teacher@example.com")
        self.root = make_user(self.school, "root@example.com", root=True)
        self.root.forward_feedback = True
        self.root.save(update_fields=["forward_feedback"])

    def message(self, **fields):
        return Message.objects.create(
            kind=Message.Kind.BUG,
            text="журнал не открывается",
            author=self.author,
            school=self.school,
            page="/lesson/12",
            **fields,
        )

    def test_the_letter_carries_what_the_search_would_otherwise_start_from(self):
        """
        Адрес страницы и автор — в теле письма, а не только в базе.

        Письмо читают с телефона и по нему решают, срочно это или нет.
        «Что-то не работает» без страницы и без имени такого решения не даёт.
        """
        subject, body = describe(self.message())

        self.assertIn("teacher@example.com", subject)
        self.assertIn("/lesson/12", body)
        self.assertIn("журнал не открывается", body)
        self.assertIn("Test school", body)

    def test_it_goes_to_everybody_who_asked(self):
        sent = forward(self.message())

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["root@example.com"])

    def test_no_recipients_is_an_ordinary_state(self):
        """Страница обращений работает и без единого письма."""
        self.root.forward_feedback = False
        self.root.save(update_fields=["forward_feedback"])

        self.assertEqual(forward(self.message()), 0)
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_BACKEND="feedback.tests.BrokenBackend")
    def test_a_broken_mailer_does_not_lose_the_message(self):
        """
        Почта — внешняя система, и её отказ не отменяет принятого обращения.

        Человек нажал «отправить», сообщение записано; ответ «не удалось»
        отправил бы его писать заново то, что уже дошло.
        """
        message = self.message()

        self.assertEqual(forward(message), 0)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())


class BrokenBackend:
    """Почтовый бэкенд, который всегда падает. Нужен тесту выше."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError("почтовый сервер недоступен")


class SendingTests(SchoolTestMixin, APITestCase):
    """Полный путь: нажали «отправить» — письмо ушло, запись осталась."""

    def test_writing_a_message_notifies_the_one_who_asked_for_letters(self):
        root = self.make_root()
        root.forward_feedback = True
        root.save(update_fields=["forward_feedback"])
        sign_in(self.client, self.student)

        response = self.client.post(
            reverse("feedback-list"),
            {"kind": "idea", "text": "хорошо бы тёмную тему", "page": "/student"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("хорошо бы тёмную тему", mail.outbox[0].body)
        # ученик пишет наравне с учителем: поломку он видит ту же
        self.assertEqual(Message.objects.get().author, self.student)
