"""
Банк задач: владение, словарь и заведение книги.

Главное здесь — **три уровня владения**: системное видят все и правит
суперпользователь, школьное — школа и её администраторы, личное — автор (и
администратор, он школьный суперпользователь). Ошибка тут не «показали
лишнее», а чужая библиотека, которую посторонний правит.
"""

from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from . import services
from .models import METHOD, OBJECT, Entry, Problem, Solution, SolutionTag, Source, Tag


class OwningTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.system = Source.objects.create(title="Мордкович", created_by=self.root)
        self.school_book = Source.objects.create(
            title="Сборник школы", school=self.school, created_by=self.admin
        )
        self.mine = Source.objects.create(
            title="Мои листочки",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

    def test_the_three_levels_are_told_apart_by_the_fields(self):
        self.assertEqual(self.system.level, "system")
        self.assertEqual(self.school_book.level, "school")
        self.assertEqual(self.mine.level, "personal")

    def test_a_teacher_sees_system_school_and_own(self):
        seen = Source.objects.visible_to(self.user)

        self.assertEqual(seen.count(), 3)

    def test_a_colleague_does_not_see_my_personal_shelf(self):
        seen = Source.objects.visible_to(self.colleague)

        self.assertNotIn(self.mine, seen)
        self.assertIn(self.school_book, seen)

    def test_another_school_sees_only_the_system_one(self):
        seen = Source.objects.visible_to(self.alien_admin)

        self.assertEqual(list(seen), [self.system])

    def test_a_teacher_writes_only_to_their_own(self):
        writable = Source.objects.writable_by(self.user)

        self.assertEqual(list(writable), [self.mine])

    def test_the_administrator_writes_to_everything_in_the_school(self):
        """Администратор — школьный суперпользователь, включая личное учителя."""
        writable = Source.objects.writable_by(self.admin)

        self.assertIn(self.mine, writable)
        self.assertIn(self.school_book, writable)
        self.assertNotIn(self.system, writable)

    def test_only_a_superuser_writes_to_the_system_catalogue(self):
        self.assertIn(self.system, Source.objects.writable_by(self.root))


class TagTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.method = Tag.objects.create(kind=METHOD, name="разложение на множители")

    def test_only_a_superuser_adds_tags(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(
            reverse("bank-tags"), {"kind": METHOD, "name": "своё"}, format="json"
        )

        self.assertEqual(response.json()["code"], "superuser_only_tags")

    def test_a_parent_must_be_of_the_same_kind(self):
        """Метод внутри объекта — бессмыслица, и выразить её нельзя."""
        child = Tag(kind=OBJECT, name="логарифм", parent=self.method)

        with self.assertRaises(ValidationError):
            child.full_clean()

    def test_a_tag_of_the_wrong_kind_does_not_go_on_a_solution(self):
        thing = Tag.objects.create(kind=OBJECT, name="пирамида")
        problem = Problem.objects.create(text="…", created_by=self.root)
        solution = Solution.objects.create(problem=problem, text="…", created_by=self.root)

        link = SolutionTag(solution=solution, tag=thing)

        with self.assertRaises(ValidationError):
            link.full_clean()

    def test_only_a_method_or_a_theorem_can_be_avoided(self):
        """«Не использует дискриминант» осмысленно, «не про пирамиду» — нет."""
        thing = Tag.objects.create(kind=OBJECT, name="пирамида")
        problem = Problem.objects.create(text="…", created_by=self.root)
        solution = Solution.objects.create(problem=problem, text="…", created_by=self.root)

        link = SolutionTag(solution=solution, tag=thing, side=SolutionTag.AVOIDS)

        with self.assertRaises(ValidationError):
            link.full_clean()


class OutlineTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.source = Source.objects.create(
            title="Книга", school=self.school, owner=self.user, created_by=self.user
        )

    def test_indent_makes_the_depth(self):
        rows = services.parse_outline("Глава 1\n  §1\n    1.1\n  §2\nГлава 2")

        self.assertEqual([row["depth"] for row in rows], [0, 1, 2, 1, 0])

    def test_a_jump_of_two_levels_is_refused(self):
        """Угадывать, что имелось в виду, мы не беремся."""
        with self.assertRaises(Exception) as caught:
            services.parse_outline("Глава\n    сразу вглубь")

        self.assertEqual(caught.exception.detail["code"], "outline_jump")

    def test_the_outline_is_replaced_whole(self):
        services.set_outline(self.source, "Глава 1\n  §1")
        services.set_outline(self.source, "Другая\n  §2\n  §3")

        self.assertEqual(
            list(self.source.sections.values_list("title", flat=True)),
            ["Другая", "§2", "§3"],
        )

    def test_problems_come_in_by_the_line(self):
        added = services.add_problems(
            self.source,
            section=None,
            text="6\t2+2\n7\t3+3\nбез номера",
            user=self.user,
        )

        self.assertEqual(added, 3)
        self.assertEqual(
            list(self.source.entries.values_list("label", flat=True)), ["6", "7", ""]
        )

    def test_added_problems_belong_to_the_book_not_the_typist(self):
        """
        Учитель вписал главу в школьную книгу — задачи школьные, а не его.

        Иначе он оказался бы владельцем половины общего содержимого.
        """
        book = Source.objects.create(
            title="Общая", school=self.school, created_by=self.admin
        )

        services.add_problems(book, section=None, text="1\t2+2", user=self.user)

        problem = Problem.objects.get(entries__source=book)
        self.assertEqual(problem.level, "school")
        self.assertEqual(problem.created_by, self.user)

    def test_a_numbered_line_without_a_statement_is_refused(self):
        with self.assertRaises(Exception) as caught:
            services.parse_problems("6\t")

        self.assertEqual(caught.exception.detail["code"], "problem_text_required")


class SourceApiTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.source = Source.objects.create(
            title="Книга", school=self.school, owner=self.user, created_by=self.user
        )
        self.client.force_authenticate(self.user)

    def test_the_number_is_an_address(self):
        services.add_problems(
            self.source, section=None, text="6\t2+2\n14а\t3+3", user=self.user
        )

        answer = self.client.get(
            reverse("bank-source", args=[self.source.pk]), {"label": "14а"}
        )

        self.assertEqual(len(answer.json()["entries"]), 1)
        self.assertEqual(answer.json()["entries"][0]["label"], "14а")

    def test_a_colleague_cannot_write_into_my_book(self):
        self.client.force_authenticate(self.colleague)

        answer = self.client.post(
            reverse("bank-source", args=[self.source.pk]),
            {"outline": "Глава"},
            format="json",
        )

        self.assertEqual(answer.status_code, 404)

    def test_a_student_has_no_bank_at_all(self):
        self.client.force_authenticate(self.student)

        answer = self.client.get(reverse("bank-sources"))

        self.assertEqual(answer.json()["code"], "teachers_only")


class SolutionTests(SchoolTestMixin, APITestCase):
    def test_a_personal_solution_to_a_system_problem(self):
        """Главный способ, которым учитель вкладывается в общую библиотеку."""
        root = self.make_root()
        problem = Problem.objects.create(text="2x²+5x−3=0", created_by=root)
        self.client.force_authenticate(self.user)

        answer = self.client.post(
            reverse("bank-solutions"),
            {"problem": problem.pk, "title": "Разложением", "text": "…"},
            format="json",
        )

        self.assertEqual(answer.status_code, 201)
        solution = Solution.objects.get(pk=answer.json()["id"])
        self.assertEqual(solution.level, "personal")
        self.assertEqual(solution.problem, problem)
