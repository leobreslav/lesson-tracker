"""
Сравнение планов, переживших копирование.

Сравнение в проекте **точное**: строки узнаются по устойчивому номеру, а не
по названию, как в текстовых diff'ах, — потому переименование видно
переименованием, а не парой «удалили и добавили». Копирование этот порядок
рвёт: взятый с полки план это новые строки с новыми номерами.

Здесь проверяется, что запись «откуда я родом» (`PlanNode.origin_id`) чинит
ровно это — и что там, где родства нет, сравнение честно говорит «нет», а не
выдумывает похожесть по названиям.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    make_course,
    make_grade,
    make_node,
    make_subject,
    make_template,
    make_year,
)

from . import services
from .models import PlanNode
from .owning import of_course, of_template

SAMPLE = (
    (True, "Тригонометрия"),
    (False, "Синус суммы"),
    (False, "Косинус суммы"),
)


class OriginTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.subject = make_subject(self.school, "Алгебра")
        self.grade = make_grade(self.school, 9)
        self.course = make_course(self.school, self.year, "9Б")
        self.course.subject = self.subject
        self.course.grade = self.grade
        self.course.save(update_fields=["subject", "grade"])
        assign(self.user, self.course)

        self.template = make_template(
            self.school, self.user, subject=self.subject, grade=9, rows=SAMPLE
        )

    def take_into(self, course=None):
        """Взять шаблон в план курса — тем же путём, каким это делает экран."""
        return self.client.post(
            reverse("plan-import-from-template"),
            {"course": (course or self.course).pk, "template": self.template.pk},
            format="json",
        )

    def compare(self, before, after):
        return services.aligned_snapshots(before, after)


class ACopyRemembersWhereItCameFromTests(OriginTestCase):
    def test_taking_a_template_records_the_origin_of_every_row(self):
        self.assertEqual(self.take_into().status_code, 200)

        origins = services.origins_of(of_course(self.course))
        shelf = set(
            PlanNode.objects.filter(template=self.template).values_list("pk", flat=True)
        )

        self.assertEqual(len(origins), len(shelf))
        self.assertEqual(set(origins.values()), shelf)

    def test_a_copy_is_still_a_copy(self):
        """
        Память о происхождении — не связь, и правки по ней не бегут.

        Это главное свойство полки, и потерять его легче всего именно тут:
        поле называется как ссылка и лежит рядом со ссылками. Взяли план,
        переименовали строку у себя — на полке обязано остаться прежнее.
        """
        self.take_into()
        mine = PlanNode.objects.get(course=self.course, title="Синус суммы")

        self.client.patch(
            reverse("plannode-detail", args=[mine.pk]), {"title": "Синус"}, format="json"
        )

        self.assertTrue(
            PlanNode.objects.filter(template=self.template, title="Синус суммы").exists()
        )


class ComparingPlansThatSurvivedACopyTests(OriginTestCase):
    def test_a_fresh_copy_differs_from_its_source_in_nothing(self):
        self.take_into()

        before, after, matched = self.compare(
            of_template(self.template), of_course(self.course)
        )

        self.assertTrue(matched)
        self.assertEqual(
            [row.node_id for row in before], [row.node_id for row in after]
        )

    def test_a_renamed_row_reads_as_renamed_and_not_as_two(self):
        """
        Ради этого всё и заведено.

        Без записи о происхождении номера у копии свои, общей части у
        последовательностей нет вовсе, и сравнение честно показало бы
        «удалено три, добавлено три» — на плане, где изменили одно слово.
        """
        from . import diff

        self.take_into()
        mine = PlanNode.objects.get(course=self.course, title="Синус суммы")
        mine.title = "Синус суммы углов"
        mine.save(update_fields=["title"])

        before, after, matched = self.compare(
            of_template(self.template), of_course(self.course)
        )
        changes = diff.plan_diff(before, after)
        states = {change.title: change.state for change in changes}

        self.assertTrue(matched)
        self.assertEqual(states["Синус суммы углов"], "changed")
        self.assertEqual(states["Косинус суммы"], "same")

    def test_the_yearly_round_trip_matches(self):
        """
        Годовой цикл: взял шаблон, вёл год, обновляешь полку.

        Курс в сентябре — уже другая запись с другими строками, и связи с
        шаблоном у него нет по замыслу. Сходится это по **обратной** памяти:
        строки курса помнят, из какого шаблона они выросли.
        """
        september = make_course(self.school, self.year, "9В")
        september.subject = self.subject
        september.grade = self.grade
        september.save(update_fields=["subject", "grade"])
        assign(self.user, september)

        self.take_into(september)

        before, after, matched = self.compare(
            of_template(self.template), of_course(september)
        )

        self.assertTrue(matched)
        self.assertEqual(
            [row.node_id for row in before], [row.node_id for row in after]
        )

    def test_two_unrelated_plans_say_so_rather_than_pretend(self):
        """
        Родства нет — сравнение молчит, а не выдумывает.

        Приблизительное сопоставление по названиям тут было бы хуже
        молчания: оно соврало бы про переименования ровно так, как врёт
        текстовый diff, — и человек принял бы решение по неправде.
        """
        make_node(self.user, self.course, "Тригонометрия", position=0, section=True)

        before, after, matched = self.compare(
            of_template(self.template), of_course(self.course)
        )

        self.assertFalse(matched)


class TheDiffIsAskedBeforeOverwritingTests(OriginTestCase):
    def test_the_course_asks_what_the_template_would_replace(self):
        self.take_into()

        answer = self.client.get(
            reverse("plannode-diff-from-template"),
            {"course": self.course.pk, "template": self.template.pk},
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(answer.json()["matched"])
        self.assertEqual(answer.json()["replacing"], len(SAMPLE))
        self.assertEqual(answer.json()["arriving"], len(SAMPLE))

    def test_the_shelf_asks_what_the_course_would_replace(self):
        self.take_into()

        answer = self.client.get(
            reverse("plantemplate-diff-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertTrue(answer.json()["matched"])

    def test_a_colleague_cannot_ask_about_somebody_else_s_shelf(self):
        self.sign_in(self.colleague)

        answer = self.client.get(
            reverse("plantemplate-diff-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
        )

        self.assertIn(answer.status_code, (400, 403, 404), answer.content)


class UndoKeepsTheOriginTests(OriginTestCase):
    """
    Отмена не стирает родство с полкой.

    `origin_id` появился позже, чем список полей снимка, и в этот список не
    попал. Значит снимок его не хранил, а восстановление не выставляло: урок
    возвращался, а «откуда он родом» — нет, и `diff-from-template` после
    отмены отвечал «эти планы не родня» — то есть числами вместо построчного
    сравнения, ровно в том месте, ради которого память о происхождении и
    заведена.

    Класс ошибки тут важнее самого поля: дописали новое, не учли, как
    работает отмена. Между появлением `origin_id` и этой находкой прошло
    меньше десяти дней.
    """

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)
        self.take_into()

    def undo(self):
        return self.client.post(
            f"{reverse('plannode-undo')}?course={self.course.pk}", {}, format="json"
        )

    def test_a_deleted_row_comes_back_knowing_where_it_came_from(self):
        mine = PlanNode.objects.get(course=self.course, title="Синус суммы")
        origin = mine.origin_id
        self.assertIsNotNone(origin, "строка с полки обязана помнить источник")

        self.client.delete(reverse("plannode-detail", args=[mine.pk]))
        answer = self.undo()

        self.assertEqual(answer.status_code, 200, answer.content)
        back = PlanNode.objects.get(pk=mine.pk)
        self.assertEqual(back.origin_id, origin)

    def test_the_comparison_still_matches_after_an_undo(self):
        """
        Проверяется не поле, а то, ради чего оно есть.

        Родство держит построчное сравнение с полкой; равенство `origin_id`
        само по себе ничего не обещает, если сравнение его не читает.
        """
        from . import diff

        mine = PlanNode.objects.get(course=self.course, title="Синус суммы")
        self.client.delete(reverse("plannode-detail", args=[mine.pk]))
        self.undo()

        before, after, matched = self.compare(
            of_template(self.template), of_course(self.course)
        )

        self.assertTrue(matched, "родство с полкой обязано пережить отмену")
        states = {
            change.title: change.state for change in diff.plan_diff(before, after)
        }
        self.assertEqual(
            states["Синус суммы"],
            "same",
            "вернувшаяся строка — та же самая, а не новая рядом с удалённой",
        )
