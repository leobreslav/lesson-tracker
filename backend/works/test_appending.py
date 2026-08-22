"""
Дописать задачу в работу, где уже есть проверенное.

Два разных вопроса, и оба стоит проверять машиной, а не рассуждением:

* нельзя ли **по ошибке** положить задачу в работу как в книгу — то есть
  спутать два места, где условие лежит;
* что делает дописанная задача с уже выставленными оценками.
"""

from bank.models import Problem, Source
from django.urls import reverse
from rest_framework.test import APITestCase
from schedule.models import CourseStudent
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_user,
    make_work,
)

from . import grading, services
from .models import GradingSystem, Task


class WorkIsNotABookTests(SchoolTestMixin, APITestCase):
    """
    Работа и книга — два места, где условие лежит, но кладут в них **разными
    дверями**, и перепутать их нельзя: «взять к себе» принимает только книгу.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.work = make_work(self.user, self.course)
        self.problem = Problem.objects.create(
            text="Условие", school=self.school, owner=self.user, created_by=self.user
        )

    def test_a_work_id_is_not_accepted_as_a_book(self):
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-copy"),
            {"problems": [self.problem.pk], "into": self.work.pk},
            format="json",
        )

        # id работы в поле книги — это ненайденная книга, а не «положим в
        # работу»: у копирования нет пути, которым можно тронуть работу
        self.assertEqual(answer.status_code, 404)
        self.assertEqual(self.work.tasks.count(), 0)

    def test_a_book_id_is_not_accepted_as_a_work(self):
        book = Source.objects.create(
            title="Книга", school=self.school, owner=self.user, created_by=self.user
        )
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("work-add-from-bank", args=[book.pk]),
            {"problems": [self.problem.pk]},
            format="json",
        )
        self.assertEqual(answer.status_code, 404)


class AppendingCostTests(SchoolTestMixin, APITestCase):
    """
    Дописанная задача **меняет знаменатель**: набранное считается из суммы
    максимумов, и у всех уже оценённых доля от возможного падает молча.

    Запрещать это нельзя — «забыл вписать пятое задание, класс ещё пишет»
    случай обычный, — но цена должна быть названа. Проверяется здесь именно
    она: что `impact` видит оценки, а не только отправки.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.student = make_user(self.school, "uchenik@example.com", student=True)
        CourseStudent.objects.create(course=self.course, student=self.student)

        self.work = make_work(self.user, self.course)
        grading.add_typical(self.school, "ru")
        self.work.grading_system = GradingSystem.objects.filter(
            school=self.school, kind=GradingSystem.POINTS
        ).first()
        self.work.save(update_fields=["grading_system"])

        services.set_questions(
            self.work, [{"maximum": 5}, {"maximum": 5}], by=self.user
        )
        self.cells = list(self.work.tasks.order_by("position"))
        services.grade(
            self.work,
            self.student,
            scores={self.cells[0].pk: 5, self.cells[1].pk: 4},
            by=self.user,
        )

    def mark(self):
        stats = services.build_table(self.work)["marks_summary"]
        return stats["max_total"], stats["mean"]

    def test_appending_moves_the_denominator_under_the_graded(self):
        was_top, was_mean = self.mark()
        self.assertEqual(was_top, 10)

        Task.objects.create(work=self.work, position=2, maximum=5)
        now_top, now_mean = self.mark()

        # девять из десяти превратились в девять из пятнадцати, и никто
        # ничего не перепроверял
        self.assertEqual(now_top, 15)
        self.assertLess(now_mean / now_top, was_mean / was_top)

    def test_the_cost_counts_the_graded_and_not_only_the_answers(self):
        cost = services.impact_of(self.work)

        # у бумажной работы отправок нет вовсе: цена, считающая только их,
        # сказала бы «ничего не затронуто» про полностью проверенный класс
        self.assertEqual(cost["answers"], 0)
        self.assertEqual(cost["graded"], 1)
        self.assertEqual(cost["top"], 10)
