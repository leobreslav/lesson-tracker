"""
Условие ячейки: одно устройство на все три случая.

Проверяется главное правило: **умолчание при правке следует за ценой**. Пока по
условию никто не отвечал, правка идёт везде — это опечатка. Как только
появились чужие ответы, правка молча не переписывает прошлое, а делает копию.
"""

from bank.models import Problem, Source, Entry
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_user,
    make_work,
)

from . import services, statements
from .models import Task


class StatementTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.work = make_work(self.user, self.course)
        self.task = Task.objects.create(work=self.work, position=0)

    def say(self, **fields):
        return statements.say(self.task, user=self.user, **fields)

    def answer_from_a_student(self):
        student = make_user(self.school, "uchenik@example.com", student=True)
        from .models import Submission

        Submission.objects.create(task=self.task, student=student, answer="4")

    # --- три состояния ячейки ---------------------------------------------

    def test_an_empty_cell_keeps_no_statement(self):
        self.say(text="", answers=[])
        self.task.refresh_from_db()

        # пустая ячейка — законное состояние, а условия с пустым текстом мы не
        # заводим: они засорили бы банк немыми строками
        self.assertIsNone(self.task.problem)
        self.assertFalse(Problem.objects.exists())

    def test_typing_a_statement_makes_a_problem_of_my_own(self):
        problem = self.say(text="Сколько будет 2+2?", answers=["4"])
        self.task.refresh_from_db()

        self.assertEqual(self.task.problem_id, problem.pk)
        self.assertEqual(problem.level, "personal")
        self.assertEqual(problem.answers, ["4"])
        # «не хранить в библиотеке» — это отсутствие строки в книге, и всё
        self.assertFalse(problem.entries.exists())

    def test_the_same_statement_can_be_shelved_later(self):
        problem = self.say(text="Сколько будет 2+2?")
        book = Source.objects.create(
            title="Мои листочки",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        Entry.objects.create(source=book, problem=problem, label="1")

        self.task.refresh_from_db()
        # задача та же самая: положить в книгу — это действие, а не другой вид
        self.assertEqual(self.task.problem_id, problem.pk)

    # --- правка: умолчание следует за ценой -------------------------------

    def test_without_answers_the_edit_goes_everywhere(self):
        problem = self.say(text="Было")
        second = make_work(self.user, self.course, title="Вторая")
        Task.objects.create(work=second, position=0, problem=problem)

        self.say(text="Стало")
        problem.refresh_from_db()

        self.assertEqual(problem.text, "Стало")
        self.assertEqual(Problem.objects.count(), 1)
        # у обеих работ условие одно и то же, второго текста нет ни у кого
        self.assertEqual(
            {task.problem_id for task in Task.objects.all()}, {problem.pk}
        )

    def test_with_answers_the_edit_makes_a_copy_by_default(self):
        problem = self.say(text="Было")
        self.answer_from_a_student()

        made = self.say(text="Стало")
        problem.refresh_from_db()
        self.task.refresh_from_db()

        self.assertEqual(problem.text, "Было")  # прошлое не переписано
        self.assertEqual(made.text, "Стало")
        self.assertEqual(made.copied_from_id, problem.pk)
        self.assertEqual(self.task.problem_id, made.pk)

    def test_everywhere_is_still_possible_when_asked_for(self):
        problem = self.say(text="Было")
        self.answer_from_a_student()

        self.say(text="Опечатка исправлена", mode=statements.EVERYWHERE)
        problem.refresh_from_db()

        self.assertEqual(problem.text, "Опечатка исправлена")
        self.assertEqual(Problem.objects.count(), 1)

    def test_someone_elses_statement_is_always_copied(self):
        common = Problem.objects.create(text="Общая", created_by=self.make_root())
        self.task.problem = common
        self.task.save(update_fields=["problem"])

        made = self.say(text="По-своему")
        common.refresh_from_db()

        self.assertEqual(common.text, "Общая")
        self.assertEqual(made.level, "personal")
        self.assertEqual(made.copied_from_id, common.pk)

    def test_the_cost_is_countable_before_the_edit(self):
        problem = self.say(text="Было")
        self.answer_from_a_student()
        second = make_work(self.user, self.course, title="Вторая")
        Task.objects.create(work=second, position=0, problem=problem)

        self.assertEqual(statements.cost(problem), {"works": 2, "answers": 1})

    # --- через API --------------------------------------------------------

    def test_the_wire_still_speaks_of_a_question(self):
        self.client.force_authenticate(self.user)
        made = self.client.post(
            reverse("task-list"),
            {"work": self.work.pk, "question": "Условие", "answers": ["ответ"]},
            format="json",
        )
        self.assertEqual(made.status_code, 201)
        self.assertEqual(made.data["question"], "Условие")
        self.assertEqual(made.data["answers"], ["ответ"])

        task = Task.objects.get(pk=made.data["id"])
        self.assertEqual(task.problem.text, "Условие")

    def test_a_statement_that_was_asked_cannot_be_deleted_by_accident(self):
        problem = self.say(text="Спрошенная")

        with self.assertRaises(Exception):
            problem.delete()

        # снять — можно: из поиска уходит, из работы нет
        problem.retired = True
        problem.save(update_fields=["retired"])
        self.task.refresh_from_db()
        self.assertEqual(statements.statement_of(self.task), "Спрошенная")
