"""
Вход по коду из письма: вторая дверь, и чего она не делает.

Проверяется в первую очередь то, чего быть **не должно**: учётки по коду не
заводятся, существование адреса не выдаётся, список допущенных контура
спрашивается, и без почты на боевом контуре дверь честно закрыта.
"""

import re

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from schools.testing import make_school, make_user

from . import codes
from .models import LoginCode


def code_from(message) -> str:
    return re.search(r"\b(\d{6})\b", message.body).group(1)


class LoginCodeTestCase(APITestCase):
    def setUp(self):
        # частота считается в кэше процесса и пережила бы соседний тест
        cache.clear()
        self.school = make_school()
        self.parent = make_user(self.school, "mum@example.com", parent=True)
        self.parent.last_login = None
        self.parent.language = "ru"
        self.parent.save()

    def request(self, email):
        return self.client.post(
            reverse("login_code_request"), {"email": email}, format="json"
        )

    def verify(self, email, code):
        return self.client.post(
            reverse("login_code_verify"), {"email": email, "code": code}, format="json"
        )


class RequestTests(LoginCodeTestCase):
    def test_a_known_address_gets_a_six_digit_code_in_its_language(self):
        answer = self.request("Mum@Example.com")

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(answer.json(), {"sent": True})
        [message] = mail.outbox
        self.assertEqual(message.to, ["mum@example.com"])
        self.assertIn("Код для входа", message.subject)
        self.assertRegex(message.body, r"\b\d{6}\b")
        self.assertEqual(LoginCode.objects.filter(user=self.parent).count(), 1)

    def test_an_unknown_address_gets_the_same_answer_and_no_letter(self):
        answer = self.request("nobody@example.com")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json(), {"sent": True})
        self.assertEqual(mail.outbox, [])

    def test_the_code_is_stored_hashed(self):
        self.request("mum@example.com")

        code = code_from(mail.outbox[0])
        row = LoginCode.objects.get(user=self.parent)
        self.assertNotIn(code, row.code_hash)
        self.assertEqual(row.code_hash, codes.digest(self.parent, code))

    def test_a_new_request_puts_out_the_previous_code(self):
        self.request("mum@example.com")
        first = code_from(mail.outbox[0])
        self.request("mum@example.com")

        answer = self.verify("mum@example.com", first)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "login_code_invalid")

    def test_too_many_requests_stop_sending_but_answer_the_same(self):
        for _ in range(codes.REQUESTS_PER_LIFETIME):
            self.request("mum@example.com")

        answer = self.request("mum@example.com")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(len(mail.outbox), codes.REQUESTS_PER_LIFETIME)

    @override_settings(LOGIN_ALLOWED_EMAILS=["teacher@example.com"])
    def test_an_address_the_contour_does_not_admit_gets_no_letter(self):
        answer = self.request("mum@example.com")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(mail.outbox, [])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", DEBUG=False
    )
    def test_without_mail_outside_development_the_door_is_closed(self):
        answer = self.request("mum@example.com")

        self.assertEqual(answer.status_code, 503)
        self.assertEqual(answer.json()["code"], "email_login_unavailable")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", DEBUG=True
    )
    def test_in_development_the_code_goes_to_the_log(self):
        answer = self.request("mum@example.com")

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(LoginCode.objects.filter(user=self.parent).count(), 1)

    def test_a_letter_that_cannot_be_sent_is_said_so(self):
        with override_settings(EMAIL_BACKEND="accounts.test_codes.BrokenBackend"):
            answer = self.request("mum@example.com")

        self.assertEqual(answer.status_code, 503)
        self.assertEqual(answer.json()["code"], "email_not_sent")


class BrokenBackend:
    """Почтовый бэкенд, у которого всегда упал SMTP."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise ConnectionError("smtp is down")


class VerifyTests(LoginCodeTestCase):
    def sent_code(self, email="mum@example.com"):
        self.request(email)
        return code_from(mail.outbox[-1])

    def test_the_right_code_hands_out_the_token_and_marks_the_arrival(self):
        code = self.sent_code()

        answer = self.verify("MUM@example.com", f" {code} ")

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(answer.json()["key"], Token.objects.get(user=self.parent).key)
        self.parent.refresh_from_db()
        self.assertIsNotNone(self.parent.last_login)
        self.assertIsNotNone(LoginCode.objects.get(user=self.parent).used_at)

    def test_a_code_works_once(self):
        code = self.sent_code()
        self.verify("mum@example.com", code)

        answer = self.verify("mum@example.com", code)

        self.assertEqual(answer.json()["code"], "login_code_invalid")

    def test_a_wrong_code_is_refused_and_counted(self):
        self.sent_code()

        answer = self.verify("mum@example.com", "000000")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "login_code_invalid")
        self.assertEqual(LoginCode.objects.get(user=self.parent).attempts, 1)

    def test_after_the_last_attempt_the_code_is_spent(self):
        code = self.sent_code()
        for _ in range(LoginCode.MAX_ATTEMPTS):
            self.verify("mum@example.com", "000000")

        answer = self.verify("mum@example.com", code)

        self.assertEqual(answer.json()["code"], "login_code_expired")

    def test_an_expired_code_says_to_ask_for_a_new_one(self):
        code = self.sent_code()
        LoginCode.objects.update(expires_at=timezone.now())

        answer = self.verify("mum@example.com", code)

        self.assertEqual(answer.json()["code"], "login_code_expired")

    def test_an_unknown_address_is_the_same_refusal_as_a_wrong_code(self):
        answer = self.verify("nobody@example.com", "123456")

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "login_code_invalid")

    def test_nobody_is_created_by_the_door(self):
        before = codes.User.objects.count()
        self.request("nobody@example.com")
        self.verify("nobody@example.com", "123456")

        self.assertEqual(codes.User.objects.count(), before)

    def test_the_list_of_the_contour_is_asked_at_the_token_too(self):
        code = self.sent_code()

        with override_settings(LOGIN_ALLOWED_EMAILS=["teacher@example.com"]):
            answer = self.verify("mum@example.com", code)

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.json()["code"], "not_allowed_here")
        self.assertFalse(Token.objects.filter(user=self.parent).exists())
