"""
Работа, собранная из банка.

Главное, что тут проверяется, — **снимок**: правка условия в банке не
переписывает контрольную, которую уже написали, а становится видимым
расхождением. Второе по важности — порядок: учитель ставит задачи по
возрастанию сложности, и выборка из базы не вправе его перетасовать.
"""

from bank.models import Problem
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_slot,
    make_work,
)

from . import assembling, statements
from .models import Task, Work


class AssemblingTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.problems = [
            Problem.objects.create(
                text=f"Задача {number}",
                answers=[str(number)],
                school=self.school,
                owner=self.user,
                created_by=self.user,
            )
            for number in (1, 2, 3)
        ]

    def collect(self, order=None, **extra):
        self.client.force_authenticate(self.user)
        body = {
            "course": self.course.pk,
            "title": "Проверочная",
            # `or` тут нельзя: пустой список — это осмысленный случай, а не
            # «не назвали», и он как раз проверяется отдельным тестом
            "problems": [one.pk for one in self.problems] if order is None else order,
            **extra,
        }
        return self.client.post(reverse("work-from-bank"), body, format="json")

    def test_a_work_is_assembled_in_the_order_the_teacher_named(self):
        # порядок обратный алфавитному и обратный порядку в базе: если его
        # где-нибудь потеряют, тест это увидит
        wanted = [one.pk for one in reversed(self.problems)]
        answer = self.collect(order=wanted)
        self.assertEqual(answer.status_code, 201)

        work = Work.objects.get(pk=answer.data["id"])
        self.assertEqual(
            [task.problem_id for task in work.tasks.order_by("position")], wanted
        )
        self.assertEqual(
            [statements.statement_of(task) for task in work.tasks.order_by("position")],
            ["Задача 3", "Задача 2", "Задача 1"],
        )

    def test_the_cell_holds_a_reference_and_nothing_of_its_own(self):
        work = Work.objects.get(pk=self.collect().data["id"])
        first = work.tasks.order_by("position").first()

        self.assertEqual(first.problem_id, self.problems[0].pk)
        self.assertEqual(statements.answers_of(first), ["1"])

        # правка условия доезжает до работы: второго текста у работы нет
        self.problems[0].text = "Уточнённое условие"
        self.problems[0].save(update_fields=["text"])
        first.refresh_from_db()
        self.assertEqual(statements.statement_of(first), "Уточнённое условие")

    def test_a_work_can_be_set_at_a_lesson(self):
        slot = make_slot(self.user, self.course)
        work = Work.objects.get(pk=self.collect(slot=slot.pk).data["id"])
        self.assertEqual(work.slot_id, slot.pk)

    def test_a_lesson_of_another_course_is_refused(self):
        other = make_course(self.school, year=self.course.year, name="Другой")
        assign(self.user, other)
        alien = make_slot(self.user, other)
        self.assertEqual(self.collect(slot=alien.pk).status_code, 404)

    def test_an_empty_set_is_refused_rather_than_making_an_empty_work(self):
        answer = self.collect(order=[])
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "work_nothing_to_assemble")
        self.assertFalse(Work.objects.filter(course=self.course).exists())

    def test_a_problem_that_is_not_visible_simply_is_not_taken(self):
        alien = Problem.objects.create(
            text="Чужая", school=self.school, owner=self.colleague, created_by=self.colleague
        )
        work = Work.objects.get(
            pk=self.collect(order=[self.problems[0].pk, alien.pk]).data["id"]
        )
        self.assertEqual(work.tasks.count(), 1)

    def test_a_course_that_is_not_mine_gets_nothing(self):
        other = make_course(self.school, year=self.course.year, name="Чужой курс")
        assign(self.colleague, other)

        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("work-from-bank"),
            {
                "course": other.pk,
                "title": "Ага",
                "problems": [self.problems[0].pk],
            },
            format="json",
        )
        self.assertEqual(answer.status_code, 404)

    def test_problems_are_added_to_the_end_of_an_existing_work(self):
        work = make_work(self.user, self.course)
        statements.say(
            Task.objects.create(work=work, position=0),
            text="Своя, руками",
            user=self.user,
        )

        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("work-add-from-bank", args=[work.pk]),
            {"problems": [self.problems[1].pk]},
            format="json",
        )
        self.assertEqual(answer.status_code, 201)
        self.assertEqual(
            [statements.statement_of(task) for task in work.tasks.order_by("position")],
            ["Своя, руками", "Задача 2"],
        )

    def test_a_statement_typed_by_hand_is_a_problem_of_my_own(self):
        work = make_work(self.user, self.course)
        mine = Task.objects.create(work=work, position=0)
        statements.say(mine, text="Своя, руками", user=self.user)
        mine.refresh_from_db()

        self.assertEqual(mine.problem.level, "personal")
        self.assertEqual(mine.problem.owner_id, self.user.pk)
        # в библиотеке её нет: строки в оглавлении не завелось
        self.assertFalse(mine.problem.entries.exists())

    def test_where_a_problem_was_already_asked_counts_only_my_courses(self):
        self.collect()

        asked = assembling.asked_in(self.problems[0], self.user)
        self.assertEqual([row["course"] for row in asked], [self.course.name])

        # у коллеги эта же задача не спрашивалась нигде: список про свои курсы
        self.assertEqual(assembling.asked_in(self.problems[0], self.colleague), [])


class WindowTests(SchoolTestMixin, APITestCase):
    """
    Когда собранная работа появится у ученика.

    Черновиков у работы нет — видимость задаёт окно, — поэтому умолчание тут
    не косметика: «открыть сейчас» означало бы, что контрольная, собранная за
    неделю до урока, всю неделю висит у класса на виду.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        assign(self.user, self.course)
        self.problem = Problem.objects.create(
            text="Задача", school=self.school, owner=self.user, created_by=self.user
        )

    def test_a_work_set_at_a_future_lesson_opens_on_that_day(self):
        from datetime import timedelta

        from django.utils import timezone as tz

        # день внутри года курса: фикстура сеет 2026/2027, и час вне границ
        # не завёлся бы вовсе
        ahead = self.course.year.start_date + timedelta(days=7)
        slot = make_slot(self.user, self.course, day=ahead)

        work = assembling.assemble(
            self.course,
            problems=[self.problem.pk],
            title="Контрольная",
            slot=slot,
            user=self.user,
        )
        self.assertEqual(tz.localtime(work.opens_at).date(), ahead)
        # год посеян в будущем, значит и работа открыта не сейчас
        self.assertGreater(work.opens_at, tz.now())

    def test_without_a_lesson_it_opens_now(self):
        from django.utils import timezone as tz

        before = tz.now()
        work = assembling.assemble(
            self.course, problems=[self.problem.pk], title="Сейчас", user=self.user
        )
        self.assertGreaterEqual(work.opens_at, before)
