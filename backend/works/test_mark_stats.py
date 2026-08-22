"""
Сводка по оценкам: кто оценён, сколько в среднем, что далось труднее всего.

Проверяется здесь не арифметика ради арифметики, а три решения, каждое из
которых легко откатить назад по недосмотру: трудность считается среди
**оценённых**, медиана стоит рядом со средним, а работа без шкалы даёт пустую
сводку, а не нули.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_user,
    make_work,
    make_year,
)

from . import services


class MarkStatsTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        services.set_questions(
            self.work,
            [{"question": f"Задача {n}", "maximum": 3} for n in (1, 2, 3)],
            by=self.user,
        )
        self.questions = list(self.work.tasks.all())

        self.second = make_user(self.school, "second@example.com", student=True)
        enrol(self.student, self.course, by=self.admin)
        enrol(self.second, self.course, by=self.admin)
        self.client.force_authenticate(self.user)

    def grade(self, student, values):
        services.grade(
            self.work,
            student,
            scores={self.questions[n].pk: value for n, value in enumerate(values)},
            by=self.user,
        )

    def stats(self):
        return services.build_table(self.work)["marks_summary"]

    def test_the_hardest_question_is_the_one_they_scored_least_on(self):
        self.grade(self.student, [3, 1, 0])
        self.grade(self.second, [3, 2, 0])

        got = self.stats()

        self.assertEqual(got["hardest"], self.questions[2].pk)
        self.assertEqual(got["easiest"], self.questions[0].pk)

    def test_difficulty_counts_the_graded_only(self):
        """
        Отсутствовавшему оценок нет, и ноль ему не приписывается.

        Иначе задача объявлялась бы тем труднее, чем больше народу болело.
        """
        self.grade(self.student, [3, 3, 3])

        column = self.stats()["columns"][0]

        self.assertEqual(column["graded"], 1)
        self.assertEqual(column["facility"], 100)

    def test_the_middle_is_shown_next_to_the_mean(self):
        """Одна двойка среди отличников тянет среднее, а медиану — нет."""
        self.grade(self.student, [3, 3, 3])
        self.grade(self.second, [0, 0, 0])

        got = self.stats()

        self.assertEqual(got["mean"], 4.5)
        self.assertEqual(got["best"], 9)
        self.assertEqual(got["worst"], 0)

    def test_full_partial_and_zero_are_counted_apart(self):
        self.grade(self.student, [3, 2, 0])
        self.grade(self.second, [3, 0, 0])

        columns = self.stats()["columns"]

        self.assertEqual((columns[0]["full"], columns[0]["partial"], columns[0]["zero"]), (2, 0, 0))
        self.assertEqual((columns[1]["full"], columns[1]["partial"], columns[1]["zero"]), (0, 1, 1))

    def test_a_work_without_questions_says_nothing(self):
        """Работа может не иметь вопросов вовсе, и это не «ноль»."""
        plain = make_work(self.user, self.course, title="Без вопросов")

        self.assertIsNone(services.build_table(plain)["marks_summary"])

    def test_the_table_carries_it(self):
        self.grade(self.student, [3, 3, 3])

        answer = self.client.get(reverse("work-table", args=[self.work.pk]))

        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["marks_summary"]["graded"], 1)
