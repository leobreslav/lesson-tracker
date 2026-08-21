"""
Условия задач, прочитанные с листа.

Условие ложится в вопрос работы — там ему и место: критерий отвечает на другой
вопрос, «как работа оценена». Проверяется тут одно решение и его последствия: **расхождение не
подгоняется, а называется**. Задач на листе больше, чем в шкале, или максимум
на бумаге не тот, что выставлен, — это вопрос к человеку, а не повод молча
переписать то, по чему уже могут стоять оценки.
"""

from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_course, make_work, make_year

from . import services


class QuestionTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course, on_paper=True)
        services.set_questions(
            self.work, [{"maximum": 3} for _ in (1, 2, 3)], by=self.user
        )

    def questions(self, *items):
        return [
            {"number": number, "text": text, "marks": marks}
            for number, text, marks in items
        ]

    def test_the_statements_land_on_the_questions_by_number(self):
        got = services.apply_questions(
            self.work,
            by=self.user,
            found=self.questions(
                (1, "$2+2$", 3), (2, "$3\\times3$", 3), (3, "Сколько?", 3)
            ),
        )

        self.assertEqual(got["written"], 3)
        texts = list(self.work.tasks.values_list("problem__text", flat=True))
        self.assertEqual(texts, ["$2+2$", "$3\\times3$", "Сколько?"])

    def test_questions_beyond_the_scale_are_named_not_added(self):
        """
        Лист длиннее шкалы — это вопрос к человеку.

        Дописать критерии молча значит задним числом переписать то, по чему уже
        могут стоять оценки.
        """
        got = services.apply_questions(
            self.work, by=self.user, found=self.questions((1, "раз", 3), (4, "четыре", 3))
        )

        self.assertEqual(got["extra"], [4])
        self.assertEqual(self.work.tasks.count(), 3)

    def test_a_different_top_mark_is_reported_not_applied(self):
        got = services.apply_questions(self.work, by=self.user, found=self.questions((2, "два", 5)))

        self.assertEqual(got["marks_differ"], [{"number": 2, "marks": 5}])
        self.assertEqual(self.work.tasks.all()[1].maximum, 3)

    def test_reading_again_overwrites_the_old_text(self):
        """Кнопку жмут второй раз именно затем, чтобы переписать прочитанное."""
        services.apply_questions(self.work, by=self.user, found=self.questions((1, "старое", None)))
        services.apply_questions(self.work, by=self.user, found=self.questions((1, "новое", None)))

        self.assertEqual(self.work.tasks.first().problem.text, "новое")

    def test_a_sheet_without_questions_changes_nothing(self):
        services.apply_questions(self.work, by=self.user, found=self.questions((1, "раз", None)))

        got = services.apply_questions(self.work, by=self.user, found=[])

        self.assertEqual(got["written"], 0)
        self.assertEqual(self.work.tasks.first().problem.text, "раз")
