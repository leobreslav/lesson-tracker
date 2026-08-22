"""
Разговор о задаче.

Главное здесь то же, что и во всей ученической половине: **чужого не видно**.
Ученик читает свой тред и только его; учитель курса — все, потому что отвечать
на вопросы его работа. Чат, которого пока нет, будет читать эти же треды, и
поэтому предмет у треда — пара «задача и ученик», а не «переписка двоих».
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_task,
    make_user,
    make_work,
    make_year,
)

from .models import Message, Thread


class ThreadTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.task = make_task(self.work)

        self.classmate = make_user(self.school, "classmate@example.com", student=True)
        enrol(self.student, self.course, by=self.admin)
        enrol(self.classmate, self.course, by=self.admin)

    def url(self, student=None):
        return (
            f"{reverse('task-thread')}?task={self.task.pk}"
            f"&student={(student or self.student).pk}"
        )

    def say(self, who, text, student=None):
        self.client.force_authenticate(who)
        return self.client.post(self.url(student), {"text": text}, format="json")

    def test_a_student_asks_and_the_teacher_answers_in_one_thread(self):
        self.say(self.student, "Не понял условие")
        self.say(self.user, "Смотри второй абзац")

        self.assertEqual(Thread.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 2)

    def test_the_thread_is_created_on_demand(self):
        """Пока никто не спросил, треда нет — «нет вопросов» это не пустой тред."""
        self.client.force_authenticate(self.student)

        answer = self.client.get(self.url())

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["messages"], [])
        self.assertEqual(Thread.objects.count(), 0)

    def test_a_classmate_does_not_see_it(self):
        self.say(self.student, "Мой вопрос")

        self.client.force_authenticate(self.classmate)
        answer = self.client.get(self.url())

        self.assertEqual(answer.json()["code"], "attachment_forbidden")

    def test_a_classmate_cannot_write_into_it_either(self):
        response = self.say(self.classmate, "Подслушал", student=self.student)

        self.assertEqual(response.json()["code"], "attachment_forbidden")

    def test_the_teacher_of_the_course_sees_every_thread(self):
        self.say(self.student, "Вопрос")

        self.client.force_authenticate(self.user)
        answer = self.client.get(self.url())

        self.assertEqual(len(answer.json()["messages"]), 1)

    def test_a_colleague_from_another_course_does_not(self):
        self.say(self.student, "Вопрос")

        self.client.force_authenticate(self.colleague)
        answer = self.client.get(self.url())

        self.assertEqual(answer.json()["code"], "attachment_forbidden")

    def test_an_empty_message_is_not_a_message(self):
        response = self.say(self.student, "   ")

        self.assertEqual(response.json()["code"], "message_empty")

    def test_the_thread_remembers_who_wrote(self):
        """Автор и адресат, а не «от ученика»: третий участник придёт и не сломает."""
        self.say(self.student, "Вопрос")
        self.say(self.user, "Ответ")

        authors = list(Message.objects.values_list("author_id", flat=True))

        self.assertEqual(authors, [self.student.pk, self.user.pk])
