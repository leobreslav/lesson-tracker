"""
The plan library: who sees what, and what a copy is.

Two properties carry the section. Visibility — a draft is private, a
published entry is the school's — and independence: taking a template gives
you a plan of your own, and nothing afterwards links the two.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from plans.models import PlanNode
from plans.owning import of_course
from rest_framework.test import APITestCase
from schools.testing import (
    assign,
    make_grade,
    SchoolTestMixin,
    make_course,
    make_node,
    make_subject,
    make_template,
    make_year,
)

from .models import PlanTemplate

# a small plan: two blocks with lessons inside, plus a lesson before them
SAMPLE = (
    (False, "Вводный урок"),
    (True, "Тригонометрия"),
    (False, "Синус суммы"),
    (False, "Косинус суммы"),
    (True, "Векторы"),
    (False, "Понятие вектора"),
)

# то же самое, но в виде дерева: у урока названа тема, в которой он лежит
SAMPLE_TREE = (
    (False, "Вводный урок", None),
    (True, "Тригонометрия", None),
    (False, "Синус суммы", "Тригонометрия"),
    (False, "Косинус суммы", "Тригонометрия"),
    (True, "Векторы", None),
    (False, "Понятие вектора", "Векторы"),
)


class LibraryTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.subject = make_subject(self.school, "Алгебра")
        self.geometry = make_subject(self.school, "Геометрия")
        self.course = make_course(self.school, self.year, "9Б")
        self.course.subject = self.subject
        self.course.grade = make_grade(self.school, 9)
        self.course.save(update_fields=["subject", "grade"])
        # шаблон снимается с плана СВОЕГО курса, поэтому назначение нужно
        # так же, как и в интерфейсе
        assign(self.user, self.course)

    def build_plan(self, teacher=None, course=None):
        """The tree the sample template mirrors: a lesson, then two blocks."""
        teacher = teacher or self.user
        course = course or self.course

        make_node(teacher, course, "Вводный урок", position=0)
        trig = make_node(teacher, course, "Тригонометрия", position=1, section=True)
        make_node(teacher, course, "Синус суммы", parent=trig, position=0)
        make_node(teacher, course, "Косинус суммы", parent=trig, position=1)
        vectors = make_node(teacher, course, "Векторы", position=2, section=True)
        make_node(teacher, course, "Понятие вектора", parent=vectors, position=0)

    def structure(self, teacher=None, course=None):
        """
        The plan as «header / lesson» pairs, in display order.

        The header a lesson sits under is part of the pair: while the rows
        were flat, a lesson inside a block and a lesson at the top level
        looked identical here, and a copy that lost its nesting compared
        equal to one that kept it.
        """
        from plans import services

        rows = []
        for branch in services.get_tree(of_course(course or self.course)):
            rows.append((branch.node.is_section, branch.node.title, None))
            rows.extend(
                (False, child.title, branch.node.title) for child in branch.children
            )
        return rows

    def rows_of(self, template):
        """План шаблона плоским списком — тем же, каким его отдаёт ответ."""
        from library.serializers import template_rows_payload

        return [
            (row["is_header"], row["title"])
            for row in template_rows_payload(template)
        ]


class VisibilityTests(LibraryTestCase):
    def test_a_draft_is_invisible_to_colleagues(self):
        draft = make_template(self.school, self.user, published=False, title="Черновик")

        self.sign_in(self.colleague)
        listing = self.client.get(reverse("plantemplate-list")).json()

        self.assertEqual(listing, [])
        self.assertEqual(
            self.client.get(reverse("plantemplate-detail", args=[draft.pk])).status_code,
            404,
        )

    def test_a_draft_is_visible_to_its_author(self):
        draft = make_template(self.school, self.user, published=False)

        listing = self.client.get(reverse("plantemplate-list")).json()

        self.assertEqual([item["id"] for item in listing], [draft.pk])
        self.assertTrue(listing[0]["mine"])
        self.assertFalse(listing[0]["is_published"])

    def test_a_published_entry_is_visible_to_the_whole_school(self):
        template = make_template(self.school, self.user, title="Общий")

        self.sign_in(self.colleague)
        listing = self.client.get(reverse("plantemplate-list")).json()

        self.assertEqual([item["id"] for item in listing], [template.pk])
        self.assertFalse(listing[0]["mine"])
        self.assertFalse(listing[0]["can_edit"])

    def test_another_schools_library_is_invisible(self):
        alien = make_template(
            self.alien_school, self.stranger, title="Чужой", published=True
        )

        listing = self.client.get(reverse("plantemplate-list")).json()

        self.assertEqual(listing, [])
        self.assertEqual(
            self.client.get(reverse("plantemplate-detail", args=[alien.pk])).status_code,
            404,
        )

    def test_a_user_without_a_school_sees_nothing(self):
        make_template(self.school, self.user)
        self.sign_in(self.outsider)

        response = self.client.get(reverse("plantemplate-list"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "no_school")

    def test_mine_filters_out_the_rest(self):
        make_template(self.school, self.colleague, title="Чужой опубликованный")
        mine = make_template(self.school, self.user, title="Мой")

        listing = self.client.get(reverse("plantemplate-list"), {"mine": "true"}).json()

        self.assertEqual([item["id"] for item in listing], [mine.pk])

    def test_filters_by_subject_and_grade(self):
        make_template(self.school, self.user, subject=self.subject, grade=9, title="А9")
        geometry = make_template(
            self.school, self.user, subject=self.geometry, grade=7, title="Г7"
        )

        by_subject = self.client.get(
            reverse("plantemplate-list"), {"subject": self.geometry.pk}
        ).json()
        by_grade = self.client.get(reverse("plantemplate-list"), {"grade": 7}).json()

        self.assertEqual([item["id"] for item in by_subject], [geometry.pk])
        self.assertEqual([item["id"] for item in by_grade], [geometry.pk])

    def test_a_garbage_filter_returns_nothing_rather_than_crashing(self):
        make_template(self.school, self.user)

        self.assertEqual(
            self.client.get(reverse("plantemplate-list"), {"grade": "девять"}).json(), []
        )


class TemplateReadTests(LibraryTestCase):
    def test_the_number_of_queries_does_not_grow_with_the_rows(self):
        """
        Просмотр шаблона — обычное действие: кнопка «Посмотреть» на полке.

        Строки сериализуются вместе с вложениями, и каждая ходила за ними
        сама: полсотни уроков — полсотни запросов. Проверяется не конкретное
        число (оно поедет от соседней правки), а то, что оно не зависит от
        длины шаблона.
        """
        small = make_template(self.school, self.user, rows=SAMPLE)
        big = make_template(
            self.school,
            self.user,
            title="Длинный",
            rows=tuple((False, f"Урок {i}") for i in range(60)),
        )

        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("plantemplate-detail", args=[small.pk]))
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(reverse("plantemplate-detail", args=[big.pk]))

        self.assertEqual(len(response.json()["rows"]), 60)
        self.assertEqual(
            len(many),
            len(few),
            f"запросы растут со строками: {len(few)} против {len(many)}",
        )


class AuthorshipTests(LibraryTestCase):
    def test_a_colleague_cannot_edit_my_template(self):
        template = make_template(self.school, self.user)
        self.sign_in(self.colleague)

        response = self.client.patch(
            reverse("plantemplate-detail", args=[template.pk]),
            {"title": "Переписал"},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["code"], "not_template_author")

    def test_an_administrator_cannot_edit_it_either(self):
        """The role runs the school; authorship is not part of the school."""
        template = make_template(self.school, self.user)
        self.sign_in(self.admin)

        response = self.client.patch(
            reverse("plantemplate-detail", args=[template.pk]),
            {"title": "Переписал"},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.content)
        template.refresh_from_db()
        self.assertEqual(template.title, "Шаблон")

    def test_the_author_edits_and_publishes(self):
        template = make_template(self.school, self.user, published=False)

        response = self.client.patch(
            reverse("plantemplate-detail", args=[template.pk]),
            {"title": "Алимов, углублённый", "is_published": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        template.refresh_from_db()
        self.assertEqual(template.title, "Алимов, углублённый")
        self.assertTrue(template.is_published)

    def test_the_author_deletes_their_own(self):
        template = make_template(self.school, self.user)

        response = self.client.delete(reverse("plantemplate-detail", args=[template.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(PlanTemplate.objects.exists())

    def test_an_administrator_may_clear_out_somebody_elses(self):
        """The library is the school's, so somebody has to be able to tidy."""
        template = make_template(self.school, self.user)
        self.sign_in(self.admin)

        response = self.client.delete(reverse("plantemplate-detail", args=[template.pk]))

        self.assertEqual(response.status_code, 204, response.content)

    def test_a_plain_colleague_may_not_delete(self):
        template = make_template(self.school, self.user)
        self.sign_in(self.colleague)

        response = self.client.delete(reverse("plantemplate-detail", args=[template.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(PlanTemplate.objects.filter(pk=template.pk).exists())

    def test_anybody_in_the_school_may_add_one(self):
        response = self.client.post(
            reverse("plantemplate-list"),
            {"subject": self.subject.pk, "grade": 9, "title": "Мой первый"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        template = PlanTemplate.objects.get()
        self.assertEqual(template.author, self.user)
        self.assertFalse(template.is_published, "новый шаблон — черновик")


class FromPlanTests(LibraryTestCase):
    def test_it_copies_the_structure_exactly(self):
        self.build_plan()

        response = self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Из плана"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        template = PlanTemplate.objects.get()
        self.assertEqual(self.rows_of(template), list(SAMPLE))

    def test_the_subject_and_grade_come_from_the_course(self):
        self.build_plan()

        self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Из плана"},
            format="json",
        )

        template = PlanTemplate.objects.get()
        self.assertEqual(template.subject, self.subject)
        self.assertEqual(template.grade, 9)

    def test_the_thirteenth_year_of_study_is_publishable(self):
        """
        Верхней границы у года обучения нет — ни у параллели, ни у шаблона.

        Одиннадцать лет это местная система; в британской и IB-школе их
        тринадцать. Ограничение уже дважды всплывало в разных местах, и
        второй раз — прямо в форме публикации, где `max={11}` не давал
        снять шаблон с двенадцатого и тринадцатого года.
        """
        self.build_plan()
        self.course.grade = make_grade(self.school, level=13, name="Year 13")
        self.course.save(update_fields=["grade"])

        response = self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Из плана"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(PlanTemplate.objects.get().grade, 13)

    def test_the_course_wins_over_what_the_form_sent(self):
        """
        Шаблон — снимок **этого** курса, и предмет с годом берутся у него.

        Присланное значение остаётся запасным: у курсов, заведённых до
        справочников, спросить больше некого. Но пока побеждало оно, «Алгебра
        9» могла уехать на полку «Геометрией 7» и разойтись с курсом молча.
        """
        self.build_plan()

        self.client.post(
            reverse("plantemplate-from-plan"),
            {
                "course": self.course.pk,
                "title": "Из плана",
                "subject": self.geometry.pk,
                "grade": 7,
            },
            format="json",
        )

        template = PlanTemplate.objects.get()
        self.assertEqual(template.subject, self.subject)
        self.assertEqual(template.grade, 9)

    def test_a_course_without_a_grade_still_takes_it_from_the_form(self):
        self.build_plan()
        self.course.grade = None
        self.course.save(update_fields=["grade"])

        response = self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Из плана", "grade": 7},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(PlanTemplate.objects.get().grade, 7)

    def test_a_course_without_a_subject_asks_for_one(self):
        self.build_plan()
        self.course.subject = None
        self.course.save(update_fields=["subject"])

        response = self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Из плана"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "subject_required")

    def test_it_starts_as_a_draft(self):
        self.build_plan()

        self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Из плана"},
            format="json",
        )

        self.assertFalse(PlanTemplate.objects.get().is_published)

    def test_an_empty_plan_has_nothing_to_publish(self):
        response = self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": "Пустой"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "plan_empty")
        self.assertFalse(PlanTemplate.objects.exists())

    def test_a_plan_of_a_course_i_do_not_teach_is_not_taken(self):
        """Снять шаблон можно со своего курса — чужой в поле не пройдёт."""
        theirs = make_course(self.school, self.year, "9Ж")
        self.build_plan(teacher=self.colleague, course=theirs)

        response = self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": theirs.pk, "title": "Чужой план"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("course", response.json())


class UpdateFromPlanTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.build_plan()
        self.template = make_template(
            self.school, self.user, subject=self.subject, rows=SAMPLE
        )

    def test_the_author_refreshes_the_shelf_copy(self):
        make_node(self.user, self.course, "Новый урок", position=3)

        response = self.client.post(
            reverse("plantemplate-update-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn((False, "Новый урок"), self.rows_of(self.template))

    def test_the_year_of_study_follows_the_course(self):
        """
        Предмет и год берутся у курса заново, а не замерзают при публикации.

        Администратор поправил год обучения параллели — шаблон, обновлённый
        после этого, обязан переехать вместе с курсом: иначе он остаётся на
        полке под старым годом, и по фильтру его не найти.
        """
        self.course.grade = make_grade(self.school, level=10, name="10 класс")
        self.course.save(update_fields=["grade"])

        self.client.post(
            reverse("plantemplate-update-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
            format="json",
        )

        self.template.refresh_from_db()
        self.assertEqual(self.template.grade, 10)

    def test_a_course_without_a_grade_leaves_the_template_alone(self):
        """Спрашивать нечего — остаётся то, что назвали при публикации."""
        self.course.grade = None
        self.course.subject = None
        self.course.save(update_fields=["grade", "subject"])

        self.client.post(
            reverse("plantemplate-update-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
            format="json",
        )

        self.template.refresh_from_db()
        self.assertEqual(self.template.grade, 9)
        self.assertEqual(self.template.subject, self.subject)

    def test_a_colleague_cannot_refresh_it(self):
        self.sign_in(self.colleague)

        response = self.client.post(
            reverse("plantemplate-update-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_it_does_not_reach_anybody_who_already_took_a_copy(self):
        """
        The point of the whole design: a copy stops being connected.

        A colleague imports, the author then changes the template, and the
        colleague's plan is exactly as they left it.
        """
        self.template.is_published = True
        self.template.save(update_fields=["is_published"])

        theirs = make_course(self.school, self.year, "9Е")
        assign(self.colleague, theirs)

        self.sign_in(self.colleague)
        self.client.post(
            reverse("plan-import-from-template"),
            {"course": theirs.pk, "template": self.template.pk},
            format="json",
        )
        before = self.structure(course=theirs)

        self.sign_in(self.user)
        make_node(self.user, self.course, "Добавленный позже", position=9)
        self.client.post(
            reverse("plantemplate-update-from-plan", args=[self.template.pk]),
            {"course": self.course.pk},
            format="json",
        )

        self.assertEqual(self.structure(course=theirs), before)


class ImportTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.template = make_template(
            self.school, self.colleague, subject=self.subject, rows=SAMPLE
        )

    def use(self, **overrides):
        payload = {
            "course": self.course.pk,
            "template": self.template.pk,
            "mode": "replace",
            **overrides,
        }
        return self.client.post(
            reverse("plan-import-from-template"), payload, format="json"
        )

    def test_it_recreates_the_structure_in_my_plan(self):
        response = self.use()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created_lessons"], 4)
        self.assertEqual(response.json()["created_headers"], 2)
        self.assertEqual(self.structure(), list(SAMPLE_TREE))

    def test_replace_clears_what_was_there(self):
        make_node(self.user, self.course, "Старый урок", position=0)

        self.use(mode="replace")

        self.assertNotIn((False, "Старый урок"), self.structure())
        self.assertEqual(len(self.structure()), len(SAMPLE))

    def test_append_keeps_what_was_there(self):
        make_node(self.user, self.course, "Старый урок", position=0)

        self.use(mode="append")

        structure = self.structure()
        self.assertEqual(structure[0], (False, "Старый урок", None))
        self.assertEqual(len(structure), len(SAMPLE) + 1)

    def test_it_writes_into_the_named_course_and_no_other(self):
        untouched = make_course(self.school, self.year, "9З")
        assign(self.colleague, untouched)

        self.use()

        self.assertTrue(PlanNode.objects.filter(course=self.course).exists())
        self.assertFalse(PlanNode.objects.filter(course=untouched).exists())

    def test_three_courses_get_three_independent_plans(self):
        second = make_course(self.school, self.year, "9В")
        third = make_course(self.school, self.year, "9Г")
        assign(self.user, second)
        assign(self.user, third)

        for course in (self.course, second, third):
            self.use(course=course.pk)

        # editing one leaves the other two alone
        node = PlanNode.objects.filter(course=second, title="Синус суммы").get()
        self.client.patch(
            reverse("plannode-detail", args=[node.pk]),
            {"title": "Переименован"},
            format="json",
        )

        self.assertEqual(self.structure(course=self.course), list(SAMPLE_TREE))
        self.assertEqual(self.structure(course=third), list(SAMPLE_TREE))
        self.assertIn(
            (False, "Переименован", "Тригонометрия"), self.structure(course=second)
        )

    def test_a_draft_of_somebody_else_cannot_be_used(self):
        self.template.is_published = False
        self.template.save(update_fields=["is_published"])

        response = self.use()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("template", response.json())

    def test_a_template_of_another_school_cannot_be_used(self):
        alien = make_template(self.alien_school, self.stranger, title="Чужой")

        response = self.use(template=alien.pk)

        self.assertEqual(response.status_code, 400, response.content)
        # именно у курса: строки самого шаблона — тоже узлы плана, и «ни одной
        # строки в базе» с некоторых пор означало бы «шаблона тоже нет»
        self.assertFalse(PlanNode.objects.filter(course=self.course).exists())

    def test_a_course_of_another_school_cannot_receive_it(self):
        alien_course = make_course(self.alien_school, name="Чужой курс")

        response = self.use(course=alien_course.pk)

        self.assertEqual(response.status_code, 400, response.content)

    def test_the_import_is_all_or_nothing(self):
        from unittest.mock import patch

        make_node(self.user, self.course, "Старый урок", position=0)

        # services imports the model inside the function, so the model
        # itself is what has to be broken
        with patch(
            "plans.models.PlanNode.objects.create",
            side_effect=RuntimeError("база отвалилась"),
        ):
            with self.assertRaises(RuntimeError):
                self.use(mode="replace")

        # replace deletes before it writes: the transaction is what keeps
        # the old plan from vanishing when the write fails
        self.assertEqual(self.structure(), [(False, "Старый урок", None)])


class TakingPartOfATemplateTests(LibraryTestCase):
    """
    Курс собирают конструктором: блок отсюда, урок оттуда.

    До этого полка умела одно — отдать план целиком, — и «мне нужна только
    тема про векторы» решалось так: взять сотню чужих уроков и удалить
    девяносто. Работа на полчаса, после которой отменять нечего.
    """

    def setUp(self):
        super().setUp()
        self.template = make_template(
            self.school, self.colleague, subject=self.subject, rows=SAMPLE
        )
        self.rows = {row.title: row.pk for row in self.template.nodes.all()}

    def take(self, titles, **overrides):
        payload = {
            "course": self.course.pk,
            "template": self.template.pk,
            "mode": "append",
            "rows": [self.rows[title] for title in titles],
            **overrides,
        }
        return self.client.post(
            reverse("plan-import-from-template"), payload, format="json"
        )

    def test_a_block_arrives_whole_and_nothing_else_does(self):
        response = self.take(["Тригонометрия", "Синус суммы", "Косинус суммы"])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.structure(),
            [
                (True, "Тригонометрия", None),
                (False, "Синус суммы", "Тригонометрия"),
                (False, "Косинус суммы", "Тригонометрия"),
            ],
        )

    def test_one_lesson_is_a_legal_thing_to_take(self):
        self.take(["Синус суммы"])

        self.assertEqual(self.structure(), [(False, "Синус суммы", None)])

    def test_a_lesson_whose_header_stayed_behind_lands_on_the_top_level(self):
        """
        Иначе оно молча уехало бы в чужую тему.

        `apply_import` кладёт урок в последний виденный заголовок, и без
        отдельного признака «этот урок вне темы» взятый из «Векторов» урок
        оказался бы внутри взятой «Тригонометрии» — то есть план получил бы
        связь, которой никто не просил и которую никто не заметит.
        """
        self.take(["Тригонометрия", "Синус суммы", "Понятие вектора"])

        self.assertEqual(
            self.structure(),
            [
                (True, "Тригонометрия", None),
                (False, "Синус суммы", "Тригонометрия"),
                (False, "Понятие вектора", None),
            ],
        )

    def test_the_order_stays_the_templates_own(self):
        """Выбор — фильтр, а не новая раскладка: порядок решать не человеку."""
        self.take(["Понятие вектора", "Вводный урок"])

        self.assertEqual(
            [title for _, title, _ in self.structure()],
            ["Вводный урок", "Понятие вектора"],
        )

    def test_it_is_added_to_the_plan_that_is_already_there(self):
        make_node(self.user, self.course, "Старый урок", position=0)

        self.take(["Векторы", "Понятие вектора"])

        self.assertEqual(
            [title for _, title, _ in self.structure()],
            ["Старый урок", "Векторы", "Понятие вектора"],
        )

    def test_replace_still_replaces_when_only_a_block_is_taken(self):
        make_node(self.user, self.course, "Старый урок", position=0)

        self.take(["Векторы", "Понятие вектора"], mode="replace")

        self.assertEqual(
            [title for _, title, _ in self.structure()],
            ["Векторы", "Понятие вектора"],
        )

    def test_a_row_of_another_template_is_refused_by_name(self):
        """
        Молчать тут нельзя: «взял пять уроков, приехало три» не объяснится.

        Строка чужого шаблона так же не должна приниматься, как чужой
        шаблон, — и отказ обязан называться, а не терять лишнее по дороге.
        """
        # снимком: живой шаблон у автора один на предмет и параллель, а
        other = make_template(
            self.school, self.colleague, subject=self.subject, rows=SAMPLE
        )
        alien = other.nodes.first().pk

        response = self.client.post(
            reverse("plan-import-from-template"),
            {
                "course": self.course.pk,
                "template": self.template.pk,
                "mode": "append",
                "rows": [self.rows["Вводный урок"], alien],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "template_row_unknown")
        self.assertFalse(PlanNode.objects.filter(course=self.course).exists())

    def test_an_empty_choice_is_not_a_way_to_wipe_the_plan(self):
        make_node(self.user, self.course, "Старый урок", position=0)

        response = self.client.post(
            reverse("plan-import-from-template"),
            {
                "course": self.course.pk,
                "template": self.template.pk,
                "mode": "replace",
                "rows": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertTrue(
            PlanNode.objects.filter(course=self.course, title="Старый урок").exists()
        )

    def test_the_undo_button_says_a_block_rather_than_a_plan(self):
        """
        «Отменить загрузку плана» обещало бы не то: план на месте, а
        отменяются пять дописанных уроков.
        """
        from plans.history import PlanSnapshot

        self.take(["Векторы", "Понятие вектора"])

        snapshot = PlanSnapshot.objects.filter(course=self.course).latest("made_at")
        self.assertEqual(snapshot.action, "template_part")
        self.assertEqual(snapshot.detail, self.template.title)

    def test_taking_the_whole_template_is_still_one_field_short(self):
        """Нет поля — прежнее поведение, до последней строки."""
        response = self.client.post(
            reverse("plan-import-from-template"),
            {
                "course": self.course.pk,
                "template": self.template.pk,
                "mode": "replace",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.structure(), list(SAMPLE_TREE))


class RowEditingTests(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.template = make_template(
            self.school, self.user, subject=self.subject, rows=SAMPLE
        )

    def test_the_author_replaces_the_lines(self):
        response = self.client.put(
            reverse("plantemplate-rows", args=[self.template.pk]),
            [
                {"is_header": True, "title": "Новый блок"},
                {"is_header": False, "title": "Первый урок", "note": "заметка"},
            ],
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.rows_of(self.template),
            [(True, "Новый блок"), (False, "Первый урок")],
        )
        # позиции считает `apply_import`, и урок ложится **внутрь** блока:
        # плоский список на входе, дерево в хранении
        block = PlanNode.objects.get(template=self.template, is_section=True)
        lesson = PlanNode.objects.get(template=self.template, is_section=False)
        self.assertEqual((block.parent_id, block.position), (None, 0))
        self.assertEqual((lesson.parent_id, lesson.position), (block.pk, 0))

    def test_a_colleague_cannot_replace_them(self):
        self.sign_in(self.colleague)

        response = self.client.put(
            reverse("plantemplate-rows", args=[self.template.pk]),
            [{"is_header": False, "title": "Взлом"}],
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.rows_of(self.template), list(SAMPLE))



class NamedNotGuessedTests(LibraryTestCase):
    """
    Что перезаписывают на полке, **называют**, а не угадывают по предмету.

    Угадывание тут было: кнопка «Обновить шаблон» искала «мой шаблон с тем
    же предметом и той же параллелью» и брала первый — то есть первый по
    алфавиту, потому что полка приезжает отсортированной по названию. Чинили
    это пометкой «веду», и пометка честно отвечала на вопрос «какой из
    них» — но заодно запрещала второй такой же: ограничение
    `one_live_template_per_subject_and_grade` не пускало на полку две мои
    записи по алгебре за девятый.

    Запрет платил за вопрос, которого больше нет. Полка — витрина, а не
    единственная версия плана: «сохранил в сентябре, сохранил в мае» —
    обычный год работы, и обе записи законны. Шаблон для перезаписи
    приезжает номером в адресе, и выбирает его человек.
    """

    def setUp(self):
        super().setUp()
        self.build_plan()

    def save(self, title="Из плана", **extra):
        return self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": self.course.pk, "title": title, **extra},
            format="json",
        )

    def refresh(self, template):
        return self.client.post(
            reverse("plantemplate-update-from-plan", args=[template.pk]),
            {"course": self.course.pk},
            format="json",
        )

    # --- полка принимает столько записей, сколько сохранили ---

    def test_the_same_plan_may_be_saved_twice(self):
        """
        Два моих плана по одному предмету и параллели — законное состояние.

        Раньше второй отвечал `template_already_live`, и объяснить это было
        нечем: человек просил положить рядом ещё одну запись, а ему говорили
        про пометку, о которой он не спрашивал.
        """
        first = self.save(title="Сентябрьский")
        second = self.save(title="Майский")

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(
            sorted(PlanTemplate.objects.values_list("title", flat=True)),
            ["Майский", "Сентябрьский"],
        )

    def test_as_many_as_you_like(self):
        """Ограничения нет вовсе, а не «одно живое плюс сколько угодно копий»."""
        self.save(title="Первый")
        self.save(title="Второй")
        self.save(title="Третий")

        self.assertEqual(PlanTemplate.objects.count(), 3)

    # --- перезапись бьёт туда, куда указали ---

    def test_a_refresh_hits_the_template_it_was_asked_about(self):
        """
        Не «мой шаблон по этому предмету», а вот этот — по номеру в адресе.
        Проверяется на паре, где угадывание как раз и промахивалось: две мои
        записи по одному предмету, обновляем **вторую**.
        """
        self.save(title="Аисты")
        self.save(title="Ящерицы")
        untouched = PlanTemplate.objects.get(title="Аисты")
        target = PlanTemplate.objects.get(title="Ящерицы")
        before = self.rows_of(untouched)
        make_node(self.user, self.course, "Новый урок", position=3)

        response = self.refresh(target)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn((False, "Новый урок"), self.rows_of(target))
        self.assertEqual(self.rows_of(untouched), before)

    def test_only_the_author_refreshes(self):
        """Полка школьная, но запись авторская: чужую не переписывают."""
        alien = make_template(self.school, self.colleague, subject=self.geometry)
        before = self.rows_of(alien)

        response = self.refresh(alien)

        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(self.rows_of(alien), before)

    # --- переезд предмета вслед за курсом ---

    def test_a_refresh_carries_the_subject_and_grade_of_the_course(self):
        """
        Предмет и год берутся у курса заново — иначе они замерзали бы в
        момент публикации, и найти шаблон по фильтру стало бы нельзя.

        Раньше этот переезд умел столкнуть шаблон с другим моим живым, и
        столкновение приходилось ловить отказом. Сталкиваться больше не с
        чем: соседняя запись по тому же предмету законна.
        """
        eighth = make_course(self.school, self.year, "8Б")
        eighth.subject = self.subject
        eighth.grade = make_grade(self.school, 8)
        eighth.save(update_fields=["subject", "grade"])
        assign(self.user, eighth)
        make_node(self.user, eighth, "Урок", position=0)

        self.save(title="Алгебра 9")
        self.client.post(
            reverse("plantemplate-from-plan"),
            {"course": eighth.pk, "title": "Алгебра 8"},
            format="json",
        )
        eighth_template = PlanTemplate.objects.get(title="Алгебра 8")

        # администратор поправил параллель курса: теперь он девятый
        eighth.grade = self.course.grade
        eighth.save(update_fields=["grade"])

        response = self.client.post(
            reverse("plantemplate-update-from-plan", args=[eighth_template.pk]),
            {"course": eighth.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        eighth_template.refresh_from_db()
        self.assertEqual(eighth_template.grade, self.course.grade.level)
        self.assertEqual(PlanTemplate.objects.count(), 2)
