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

from . import assembling, services, statements
from .models import Mark, Submission, Task
from .services import check_answer


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


class TakeIntoCellTests(SchoolTestMixin, APITestCase):
    """
    «Накатить» условие на **эту** ячейку — не то же, что дописать в конец.

    Случай обычный: работу собрали пустыми ячейками (условия на бумаге, искать
    поленились), а потом третью заполнили задачей из каталога.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.work = make_work(self.user, self.course)
        self.cells = [
            Task.objects.create(work=self.work, position=position, maximum=2)
            for position in range(3)
        ]
        self.problem = Problem.objects.create(
            text="Из каталога",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

    def take(self, task, problem):
        self.client.force_authenticate(self.user)
        return self.client.post(
            reverse("task-take", args=[task.pk]),
            {"problem": problem.pk if problem else None},
            format="json",
        )

    def test_an_empty_cell_gets_the_statement_and_keeps_its_place(self):
        answer = self.take(self.cells[2], self.problem)
        self.assertEqual(answer.status_code, 200)

        third = Task.objects.get(pk=self.cells[2].pk)
        self.assertEqual(third.problem_id, self.problem.pk)
        # позиция и цена — свойства ячейки, и подмена условия их не трогает
        self.assertEqual((third.position, third.maximum), (2, 2))
        # соседи как были пустыми, так и остались
        self.assertEqual(
            [Task.objects.get(pk=one.pk).problem_id for one in self.cells[:2]],
            [None, None],
        )

    def test_swapping_the_statement_drops_the_marks_but_not_the_answers(self):
        student = make_user(self.school, "uchenik@example.com", student=True)
        statements.say(self.cells[0], text="Было", user=self.user)
        sent = Submission.objects.create(
            task=self.cells[0], student=student, answer="4"
        )
        check_answer(sent, value=self.cells[0].maximum, by=self.user)

        self.take(self.cells[0], self.problem)
        sent.refresh_from_db()

        # ответ — слова ученика, они на месте; балл — наше суждение об ответе
        # на **тот** вопрос, и после подмены он ни о чём
        self.assertEqual(sent.answer, "4")
        self.assertFalse(Mark.objects.filter(submission=sent).exists())

    def test_a_cell_can_be_emptied_again(self):
        self.take(self.cells[0], self.problem)
        self.take(self.cells[0], None)

        self.assertIsNone(Task.objects.get(pk=self.cells[0].pk).problem_id)

    def test_a_statement_i_cannot_see_is_not_taken(self):
        alien = Problem.objects.create(
            text="Чужая",
            school=self.school,
            owner=self.colleague,
            created_by=self.colleague,
        )
        self.assertEqual(self.take(self.cells[0], alien).status_code, 404)

    def test_the_statement_stays_where_it_was(self):
        # ячейка показывает на условие, а не забирает его себе: в банке оно
        # остаётся тем же самым и там, где лежало
        self.take(self.cells[0], self.problem)
        self.problem.refresh_from_db()

        self.assertEqual(Problem.objects.count(), 1)
        self.assertEqual(self.problem.text, "Из каталога")


class StemInACellTests(SchoolTestMixin, APITestCase):
    """
    Пункт в работе: сюжет показывается вместе с ним, а соседние пункты — нет.

    И шапку можно выключить: свойство **ячейки**, а не условия, потому что
    одна и та же задача идёт в контрольной с данными, а в домашней без — их
    написали на доске.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.work = make_work(self.user, self.course)

        self.stem = Problem.objects.create(
            text="Дан треугольник ABC со сторонами 3, 4, 5.",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        self.first = Problem.objects.create(
            text="Найдите площадь.",
            parent=self.stem,
            position=0,
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        self.second = Problem.objects.create(
            text="Найдите радиус.",
            parent=self.stem,
            position=1,
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

    def cell(self, problem):
        return Task.objects.create(work=self.work, position=0, problem=problem)

    def test_a_stem_becomes_one_cell_per_part(self):
        made = assembling.assemble(
            self.course,
            problems=[self.stem.pk],
            title="Контрольная",
            user=self.user,
        )

        # ячеек две — по числу пунктов, в авторском порядке; сюжета среди них
        # нет: у него нет ни вопроса, ни балла
        self.assertEqual(
            [task.problem_id for task in made.tasks.order_by("position")],
            [self.first.pk, self.second.pk],
        )

    def test_the_stem_comes_with_the_part_but_the_neighbours_do_not(self):
        shown = statements.shown(self.cell(self.first))

        self.assertEqual(shown["text"], "Найдите площадь.")
        self.assertEqual(shown["stem"]["text"], "Дан треугольник ABC со сторонами 3, 4, 5.")
        self.assertTrue(shown["is_part"])
        # соседний пункт в ответе не участвует вовсе
        self.assertNotIn("Найдите радиус.", str(shown))

    def test_a_hidden_stem_is_hidden_from_the_student_together_with_the_hint(self):
        task = self.cell(self.first)
        task.show_stem = False
        task.save(update_fields=["show_stem"])

        student = statements.shown(task, to_student=True)
        self.assertIsNone(student["stem"])
        # и пометка «это пункт» тоже: иначе одним нажатием видно скрытое
        self.assertFalse(student["is_part"])

        # а учителю видно, что он показывает огрызок
        teacher = statements.shown(task)
        self.assertTrue(teacher["is_part"])
        self.assertIsNone(teacher["stem"])

    def test_a_cell_without_a_stem_says_nothing_about_parts(self):
        plain = Problem.objects.create(
            text="Обычная", school=self.school, owner=self.user, created_by=self.user
        )
        shown = statements.shown(self.cell(plain))

        self.assertFalse(shown["is_part"])
        self.assertIsNone(shown["stem"])
