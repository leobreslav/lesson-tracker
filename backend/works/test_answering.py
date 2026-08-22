"""
Ответы онлайн открываются **поштучно**, ячейкой, а не флагом работы.

Флаг работы (`on_paper`) отвечал на этот вопрос одним ответом на все ячейки
разом, и обычная контрольная — «Q1 и Q2 решайте онлайн, Q3 сдайте на листе»
— была недостижима не потому, что её запретили, а потому, что выразить её
было нечем.

Проверяется здесь три вещи, и каждая ломается по-своему:

* **отказ на закрытой ячейке приходит с сервера**, а не только прячется
  экраном. Интерфейс, который чего-то не показал, — не правило;
* **«здесь есть что делать» считается по ячейкам**: работа, все вопросы
  которой пишут на бумаге, открыта и видна, а отвечать в ней негде;
* **метка опроса меняется, когда вопрос открыли.** Без этого поле ответа не
  появилось бы само — а появляется оно ровно тогда, когда учитель на уроке
  сказал «пишем», и обновлять страницу руками в этот момент никто не станет.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.services import enrol
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_task,
    make_work,
    make_year,
)

from . import services
from .models import Submission


class AnsweringTestCase(SchoolTestMixin, APITestCase):
    """Работа из двух вопросов: первый решают онлайн, второй — на листе."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.online = make_task(self.work, position=0)
        self.paper = make_task(self.work, question="Постройте график", position=1)
        self.paper.open_for_answers = False
        self.paper.save(update_fields=["open_for_answers"])

        enrol(self.student, self.course, by=self.admin)
        self.sign_in(self.student)

    def answer(self, task, text="4"):
        return self.client.post(
            reverse("student-answer", args=[task.pk]), {"answer": text}, format="json"
        )

    def my_work(self):
        return self.client.get(reverse("student-work", args=[self.work.pk])).json()


class ClosedCellTakesNoAnswersTests(AnsweringTestCase):
    def test_an_open_cell_takes_the_answer(self):
        self.assertEqual(self.answer(self.online).status_code, 201)

    def test_a_closed_cell_refuses_with_its_own_code(self):
        """
        Отказ именно про ячейку, а не про работу.

        Кодом `work_closed` тут ответить нельзя: работа открыта, и ученик,
        прочитав такое, пошёл бы к учителю с вопросом про окно времени.
        """
        refused = self.answer(self.paper)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "task_closed")
        self.assertFalse(Submission.objects.filter(task=self.paper).exists())

    def test_a_closed_cell_spends_no_attempt(self):
        """
        Отказ не считается попыткой: она расходуется на **отправке**, а
        отправки не было. Иначе закрытая ячейка съедала бы право ученика на
        ответ, которого ему и не давали.
        """
        self.work.attempts = 1
        self.work.save(update_fields=["attempts"])

        self.answer(self.paper)
        self.paper.open_for_answers = True
        self.paper.save(update_fields=["open_for_answers"])

        self.assertEqual(self.answer(self.paper).status_code, 201)

    def test_opening_the_cell_lets_the_answer_through(self):
        self.assertEqual(self.answer(self.paper).status_code, 400)

        self.paper.open_for_answers = True
        self.paper.save(update_fields=["open_for_answers"])

        self.assertEqual(self.answer(self.paper).status_code, 201)


class TheScreenSaysWhichCellsAreOpenTests(AnsweringTestCase):
    def test_each_cell_carries_its_own_answer(self):
        cells = {row["id"]: row["open_for_answers"] for row in self.my_work()["tasks"]}

        self.assertTrue(cells[self.online.pk])
        self.assertFalse(cells[self.paper.pk])

    def test_a_mixed_work_can_still_be_answered(self):
        self.assertTrue(self.my_work()["can_answer"])

    def test_a_work_written_entirely_on_paper_can_not(self):
        """
        «Есть ли тут что делать» считается по ячейкам, а не по работе.

        Работа при этом остаётся открытой и видимой: скан и оценка приезжают
        сюда же, и прятать её было бы враньём.
        """
        self.online.open_for_answers = False
        self.online.save(update_fields=["open_for_answers"])

        body = self.my_work()

        self.assertEqual(body["state"], "open")
        self.assertFalse(body["can_answer"])
        # зачисление тут ни при чём, и экран должен уметь сказать это словами
        self.assertTrue(body["enrolled"])

    def test_the_list_agrees_with_the_work_itself(self):
        """
        Список и сама работа отвечают на один вопрос одинаково.

        Разойдясь, они дали бы худший вид неправды: в списке «решать», внутри
        решать негде.
        """
        self.online.open_for_answers = False
        self.online.save(update_fields=["open_for_answers"])

        listed = self.client.get(reverse("student-works")).json()["works"][0]

        self.assertFalse(listed["can_answer"])
        self.assertEqual(listed["can_answer"], self.my_work()["can_answer"])


class OpeningACellReachesTheStudentTests(AnsweringTestCase):
    def test_the_poll_notices_that_a_cell_was_opened(self):
        """
        Учитель открыл вопрос — поле ответа появляется само.

        Метку иначе не сдвинуть ничем: задач столько же, работу никто не
        сохранял, отправок не прибавилось. Опрос отвечал бы «не изменилось»
        до тех пор, пока ученик не нажмёт F5, — то есть ровно на уроке.
        """
        before = services.student_version(self.work, self.student)

        self.paper.open_for_answers = True
        self.paper.save(update_fields=["open_for_answers"])

        self.assertNotEqual(
            before, services.student_version(self.work, self.student)
        )


class TheTeacherOpensAndClosesTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        self.task = make_task(self.work)

    def test_a_new_cell_takes_answers(self):
        """
        Умолчание — открыто, и это не мелочь.

        Работа, у которой вопросы созданы, но ни один не открыт, выглядит для
        класса пустой, а обнаруживается это на уроке. Закрывает вопрос
        учитель, и делает он это осознанно.
        """
        self.assertTrue(self.task.open_for_answers)

    def test_the_teacher_closes_a_cell_and_reopens_it(self):
        url = reverse("task-detail", args=[self.task.pk])

        closed = self.client.patch(url, {"open_for_answers": False}, format="json")
        self.task.refresh_from_db()
        self.assertEqual(closed.status_code, 200)
        self.assertFalse(self.task.open_for_answers)

        self.client.patch(url, {"open_for_answers": True}, format="json")
        self.task.refresh_from_db()
        self.assertTrue(self.task.open_for_answers)

    def test_closing_a_cell_keeps_its_statement(self):
        """
        Закрытая ячейка — не пустая: условие видно, ответить нельзя.

        Это и есть разница между показом и правом, из-за которой поле не
        сложилось с `show_stem`.
        """
        self.client.patch(
            reverse("task-detail", args=[self.task.pk]),
            {"open_for_answers": False},
            format="json",
        )
        self.task.refresh_from_db()

        self.assertTrue(self.task.problem_id)
