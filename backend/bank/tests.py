"""
Банк задач: владение, словарь и заведение книги.

Главное здесь — **три уровня владения**: системное видят все и правит
суперпользователь, школьное — школа и её администраторы, личное — автор (и
администратор, он школьный суперпользователь). Ошибка тут не «показали
лишнее», а чужая библиотека, которую посторонний правит.
"""

from django.core.exceptions import ValidationError
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_course, make_node

from . import services, topics
from .models import (
    METHOD,
    OBJECT,
    Entry,
    Problem,
    Introduction,
    Section,
    Solution,
    SolutionTag,
    Source,
    Tag,
    Topic,
)


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


class SearchTests(SchoolTestMixin, APITestCase):
    """
    Поиск по граням. Проверяется не «нашлось что-то», а два правила, на
    которых он стоит: грани складываются **и**, а грани решения спрашиваются
    у **одного** решения.
    """

    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.circle = Tag.objects.create(name="окружность", kind=OBJECT)
        self.vieta = Tag.objects.create(name="теорема Виета", kind="theorem")
        self.derivative = Tag.objects.create(name="производная", kind=METHOD)

        self.square = self.problem("Решите $x^2-5x+6=0$")
        self.circle_task = self.problem("Окружность вписана в треугольник")
        self.tag_problem(self.circle_task, self.circle)

    def problem(self, text):
        return Problem.objects.create(
            text=text, school=self.school, owner=self.user, created_by=self.user
        )

    def tag_problem(self, problem, tag):
        problem.links.create(tag=tag)

    def solution(self, problem, title, uses=(), avoids=()):
        made = Solution.objects.create(
            problem=problem,
            title=title,
            text="…",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        for tag in uses:
            made.links.create(tag=tag, side=SolutionTag.USES)
        for tag in avoids:
            made.links.create(tag=tag, side=SolutionTag.AVOIDS)
        return made

    def find(self, **params):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("bank-search"), params)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_words_narrow_the_set_together(self):
        found = self.find(text="окружность треугольник")
        self.assertEqual([row["id"] for row in found["problems"]], [self.circle_task.pk])

        # оба слова обязательны: иначе поиск из двух слов шире, чем из одного
        self.assertEqual(self.find(text="окружность парабола")["total"], 0)

    def test_the_facets_of_a_solution_are_asked_of_one_solution(self):
        # у задачи два разных разбора: один через Виета, другой без производной
        self.solution(self.square, "через Виета", uses=[self.vieta])
        self.solution(self.square, "без производной", avoids=[self.derivative])

        self.assertEqual(self.find(uses=self.vieta.pk)["total"], 1)
        self.assertEqual(self.find(avoids=self.derivative.pk)["total"], 1)

        # а вместе — ни одного: такого разбора у задачи нет
        found = self.find(uses=self.vieta.pk, avoids=self.derivative.pk)
        self.assertEqual(found["total"], 0)

        self.solution(self.square, "оба", uses=[self.vieta], avoids=[self.derivative])
        self.assertEqual(
            self.find(uses=self.vieta.pk, avoids=self.derivative.pk)["total"], 1
        )

    def test_the_facets_say_how_much_is_left(self):
        found = self.find()
        rows = {row["tag"]: row["count"] for row in found["facets"]}
        self.assertEqual(rows[self.circle.pk], 1)

        # выбранная грань из списка уходит: «сужает на всё» — не подсказка
        found = self.find(tag=self.circle.pk)
        self.assertNotIn(self.circle.pk, [row["tag"] for row in found["facets"]])

    def test_a_retired_problem_leaves_the_search_but_not_the_works(self):
        self.circle_task.retired = True
        self.circle_task.save(update_fields=["retired"])
        self.assertEqual(self.find(text="окружность")["total"], 0)

    def test_another_school_is_not_searched(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.get(reverse("bank-search"), {"text": "окружность"})
        self.assertEqual(response.data["total"], 0)


class PayloadTests(SchoolTestMixin, APITestCase):
    """
    Ответ про задачу собирается с тегами и решениями, и это стоит проверять
    отдельно: связь через промежуточную модель зовётся по имени, а имя однажды
    поменяли — питон при этом молчит до первого запроса.
    """

    def test_a_problem_comes_with_its_tags_and_solutions(self):
        tag = Tag.objects.create(name="многочлен", kind=OBJECT)
        method = Tag.objects.create(name="замена переменной", kind=METHOD)
        problem = Problem.objects.create(
            text="$x^4-5x^2+4=0$",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        problem.links.create(tag=tag)
        solution = Solution.objects.create(
            problem=problem,
            title="через замену",
            text="…",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        solution.links.create(tag=method, side=SolutionTag.USES)

        self.client.force_authenticate(self.user)
        response = self.client.get(reverse("bank-problem", args=[problem.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([one["name"] for one in response.data["tags"]], ["многочлен"])
        self.assertEqual(
            [one["name"] for one in response.data["solutions"][0]["tags"]],
            ["замена переменной"],
        )


class ExpressionTests(SchoolTestMixin, APITestCase):
    """
    Выражение из граней. Проверяется главное: «или» действительно шире «и», а
    отрицание отрицает **задачу**, а не связь.
    """

    def setUp(self):
        super().setUp()
        self.algebra = Tag.objects.create(name="алгебра", kind="subject")
        self.geometry = Tag.objects.create(name="геометрия", kind="subject")
        self.circle = Tag.objects.create(name="окружность", kind=OBJECT)
        self.derivative = Tag.objects.create(name="производная", kind=METHOD)

        self.equation = self.problem("Решите уравнение", [self.algebra])
        self.circle_task = self.problem("Окружность", [self.geometry, self.circle])

    def problem(self, text, tags):
        made = Problem.objects.create(
            text=text, school=self.school, owner=self.user, created_by=self.user
        )
        for tag in tags:
            made.links.create(tag=tag)
        return made

    def search(self, node):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            reverse("bank-search"), {"expression": node}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"] for row in response.data["problems"]}

    def test_any_is_wider_than_all(self):
        both = [{"tag": self.algebra.pk}, {"tag": self.geometry.pk}]
        self.assertEqual(self.search({"all": both}), set())
        self.assertEqual(
            self.search({"any": both}), {self.equation.pk, self.circle_task.pk}
        )

    def test_not_means_the_problem_has_no_such_tag(self):
        # у задачи два тега; «не окружность» не должно ловить её вторым тегом
        found = self.search({"not": {"tag": self.circle.pk}})
        self.assertEqual(found, {self.equation.pk})

    def test_a_side_asks_the_solutions(self):
        solution = Solution.objects.create(
            problem=self.equation,
            title="в лоб",
            text="…",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        solution.links.create(tag=self.derivative, side=SolutionTag.AVOIDS)

        self.assertEqual(
            self.search({"tag": self.derivative.pk, "side": "avoids"}),
            {self.equation.pk},
        )
        self.assertEqual(
            self.search({"tag": self.derivative.pk, "side": "uses"}), set()
        )

    def test_a_node_we_do_not_understand_is_refused_with_its_address(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            reverse("bank-search"),
            {"expression": {"all": [{"tag": self.algebra.pk}, {"колдовство": 1}]}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "bank_expression_bad")
        self.assertIn("2", response.data["detail"])


class CopyingTests(SchoolTestMixin, APITestCase):
    """
    Взять чужое к себе. Проверяются обе стороны разницы между ссылкой и своей
    копией: ссылка не заводит второй задачи, а копия достаётся правящему.
    """

    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.common = Source.objects.create(title="Мордкович", created_by=self.root)
        self.chapter = Section.objects.create(
            source=self.common, title="Квадратные уравнения"
        )
        self.problem = Problem.objects.create(text="$x^2=4$", created_by=self.root)
        Entry.objects.create(
            source=self.common, section=self.chapter, problem=self.problem, label="12"
        )
        self.mine = Source.objects.create(
            title="Мои листочки",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

    def copy(self, **body):
        self.client.force_authenticate(self.user)
        return self.client.post(reverse("bank-copy"), body, format="json")

    def test_a_link_keeps_one_problem_and_carries_its_number(self):
        answer = self.copy(problem=self.problem.pk, into=self.mine.pk)
        self.assertEqual(answer.status_code, 201)
        self.assertEqual(answer.data["problem"], self.problem.pk)
        self.assertEqual(Problem.objects.count(), 1)
        self.assertEqual(self.mine.entries.get().label, "12")

    def test_a_fork_belongs_to_the_book_it_landed_in(self):
        answer = self.copy(problem=self.problem.pk, into=self.mine.pk, mode="fork")
        made = Problem.objects.get(pk=answer.data["problem"])

        # копия системной задачи в личной книге обязана быть личной, иначе
        # правит её по-прежнему один суперпользователь — то есть копировали зря
        self.assertEqual(made.level, "personal")
        self.assertEqual(made.copied_from_id, self.problem.pk)
        self.assertEqual(made.text, self.problem.text)

    def test_a_whole_chapter_comes_with_its_problems(self):
        Entry.objects.create(
            source=self.common,
            section=self.chapter,
            problem=Problem.objects.create(text="$x^2=9$", created_by=self.root),
            label="13",
        )
        answer = self.copy(section=self.chapter.pk, into=self.mine.pk)
        self.assertEqual(answer.status_code, 201)
        self.assertEqual(self.mine.sections.count(), 1)
        self.assertEqual(
            [entry.label for entry in self.mine.entries.order_by("position")],
            ["12", "13"],
        )

    def test_copying_into_a_book_that_is_not_mine_is_refused(self):
        alien = Source.objects.create(
            title="Чужое",
            school=self.school,
            owner=self.colleague,
            created_by=self.colleague,
        )
        self.assertEqual(
            self.copy(problem=self.problem.pk, into=alien.pk).status_code, 404
        )


class AnalogueTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.problems = [
            Problem.objects.create(
                text=f"$x^2={number}$",
                school=self.school,
                owner=self.user,
                created_by=self.user,
            )
            for number in (4, 9, 16)
        ]

    def declare(self, one, other):
        self.client.force_authenticate(self.user)
        return self.client.post(
            reverse("bank-analogues"),
            {"problem": one.pk, "other": other.pk},
            format="json",
        )

    def test_families_merge_rather_than_nest(self):
        first, second, third = self.problems
        self.declare(first, second)
        self.declare(third, second)

        families = {
            Problem.objects.get(pk=one.pk).family_id for one in self.problems
        }
        self.assertEqual(len(families), 1)
        self.assertNotIn(None, families)

    def test_leaving_a_pair_dissolves_the_family(self):
        first, second, _ = self.problems
        self.declare(first, second)

        self.client.delete(
            reverse("bank-analogues"), {"problem": first.pk}, format="json"
        )
        # оставшийся один — это не семья: «без аналогов» и «аналог был, да сплыл»
        # для читающего одно и то же
        self.assertIsNone(Problem.objects.get(pk=second.pk).family_id)

    def test_a_problem_is_not_its_own_analogue(self):
        answer = self.declare(self.problems[0], self.problems[0])
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "bank_same_problem")


class ChronologyTests(SchoolTestMixin, APITestCase):
    """
    План как хронология понятий. Проверяется главное: понятие вводится
    **однажды**, а «пройдено» считается по порядку плана, а не по датам.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        self.first = make_node(self.user, self.course, "Квадратный трёхчлен", position=0)
        self.second = make_node(self.user, self.course, "Теорема Виета", position=1)
        self.third = make_node(self.user, self.course, "Производная", position=2)

        self.vieta = Tag.objects.create(name="теорема Виета", kind="theorem")
        self.derivative = Tag.objects.create(name="производная", kind=METHOD)

    def introduce(self, node, tag):
        self.client.force_authenticate(self.user)
        return self.client.post(
            reverse("bank-chronology", args=[self.course.pk]),
            {"node": node.pk, "tag": tag.pk},
            format="json",
        )

    def test_a_notion_is_introduced_once_and_moves_rather_than_doubles(self):
        self.introduce(self.second, self.vieta)
        self.introduce(self.third, self.vieta)

        rows = Introduction.objects.filter(course=self.course, tag=self.vieta)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().node_id, self.third.pk)

    def test_covered_is_counted_by_the_order_of_the_plan(self):
        self.introduce(self.second, self.vieta)
        self.introduce(self.third, self.derivative)

        self.assertEqual(topics.introduced(self.course, upto=self.first), set())
        self.assertEqual(
            topics.introduced(self.course, upto=self.second), {self.vieta.pk}
        )
        self.assertEqual(
            topics.introduced(self.course, upto=self.third),
            {self.vieta.pk, self.derivative.pk},
        )

    def test_the_chronology_comes_in_the_order_of_the_plan(self):
        self.introduce(self.third, self.derivative)
        self.client.force_authenticate(self.user)
        answer = self.client.get(reverse("bank-chronology", args=[self.course.pk]))

        self.assertEqual(
            [row["title"] for row in answer.data["lessons"]],
            ["Квадратный трёхчлен", "Теорема Виета", "Производная"],
        )
        self.assertEqual(answer.data["lessons"][2]["tags"][0]["name"], "производная")

    def test_a_colleague_does_not_mark_up_someone_elses_course(self):
        self.client.force_authenticate(self.colleague)
        answer = self.client.post(
            reverse("bank-chronology", args=[self.course.pk]),
            {"node": self.first.pk, "tag": self.vieta.pk},
            format="json",
        )
        self.assertEqual(answer.status_code, 404)


class TopicTests(SchoolTestMixin, APITestCase):
    """
    Тема — папка, заданная условием, и она же сохранённый поиск.

    Главное здесь два правила: **вложение сужает** (условие ребёнка включает
    родительское) и **закрытость** — «разбор не выходит за пройденное»,
    которое считается по хронологии курса.
    """

    def setUp(self):
        super().setUp()
        self.course = make_course(self.school)
        self.lesson = make_node(self.user, self.course, "Теорема Виета")

        self.algebra = Tag.objects.create(name="алгебра", kind="subject")
        self.vieta = Tag.objects.create(name="теорема Виета", kind="theorem")
        self.derivative = Tag.objects.create(name="производная", kind=METHOD)

        self.problem = self.make_problem("$x^2-5x+6=0$")
        self.plain = self.solution(self.problem, [self.algebra, self.vieta])
        self.fancy = self.solution(self.problem, [self.algebra, self.derivative])

        self.other = self.make_problem("Окружность")
        self.solution(self.other, [self.derivative])

    def make_problem(self, text):
        return Problem.objects.create(
            text=text, school=self.school, owner=self.user, created_by=self.user
        )

    def solution(self, problem, tags):
        made = Solution.objects.create(
            problem=problem,
            title="разбор",
            text="…",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        for tag in tags:
            made.links.create(tag=tag, side=SolutionTag.USES)
        return made

    def make_topic(self, title, expression, parent=None, **fields):
        return Topic.objects.create(
            title=title,
            expression=expression,
            parent=parent,
            created_by=self.root if hasattr(self, "root") else None,
            **fields,
        )

    def found(self, topic, **params):
        self.client.force_authenticate(self.user)
        answer = self.client.get(reverse("bank-topic", args=[topic.pk]), params)
        self.assertEqual(answer.status_code, 200, answer.data)
        return {row["id"] for row in answer.data["problems"]}

    def test_a_topic_finds_what_its_condition_says(self):
        topic = self.make_topic("Алгебра", {"solution": {"uses": [self.algebra.pk]}})
        self.assertEqual(self.found(topic), {self.problem.pk})

    def test_nesting_narrows_it(self):
        parent = self.make_topic("Алгебра", {"solution": {"uses": [self.algebra.pk]}})
        # у ребёнка своё условие — одно, без повторения родительского
        child = self.make_topic(
            "Через Виета", {"solution": {"uses": [self.vieta.pk]}}, parent=parent
        )

        self.assertEqual(self.found(child), {self.problem.pk})

        # а вот ребёнок, чьё условие не пересекается с родителем, пуст:
        # вниз по дереву всегда уже
        deeper = self.make_topic(
            "Про окружность", {"text": "Окружность"}, parent=child
        )
        self.assertEqual(self.found(deeper), set())

    def test_a_topic_without_a_condition_equals_its_parent(self):
        parent = self.make_topic("Алгебра", {"solution": {"uses": [self.algebra.pk]}})
        section = self.make_topic("Просто раздел", {}, parent=parent)
        self.assertEqual(self.found(section), {self.problem.pk})

    def test_closed_asks_the_chronology_of_the_course(self):
        topic = self.make_topic(
            "Что мы умеем",
            {"solution": {"uses": [self.algebra.pk], "covered": True}},
        )

        # ничего не пройдено — ни один разбор не годится
        self.assertEqual(self.found(topic, course=self.course.pk), set())

        topics.introduce(self.course, self.lesson, self.vieta)
        topics.introduce(self.course, self.lesson, self.algebra)
        self.assertEqual(self.found(topic, course=self.course.pk), {self.problem.pk})

    def test_the_screen_is_told_that_a_course_is_needed(self):
        topic = self.make_topic("Умеем", {"solution": {"covered": True}})
        self.client.force_authenticate(self.user)
        answer = self.client.get(reverse("bank-topic", args=[topic.pk]))
        self.assertTrue(answer.data["needs_course"])

    def test_the_requirements_are_asked_of_one_solution(self):
        # «через Виета и без производной» — про один разбор: у этой задачи
        # это два разных, и такому условию она не отвечает
        topic = self.make_topic(
            "Оба сразу",
            {"solution": {"uses": [self.vieta.pk, self.derivative.pk]}},
        )
        self.assertEqual(self.found(topic), set())

    def test_a_saved_search_is_a_topic_of_my_own(self):
        self.client.force_authenticate(self.user)
        made = self.client.post(
            reverse("bank-topics"),
            {"title": "Мой запрос", "expression": {"tag": self.algebra.pk}},
            format="json",
        )
        self.assertEqual(made.status_code, 201)
        self.assertEqual(made.data["level"], "personal")

        listed = self.client.get(reverse("bank-topics"))
        self.assertEqual(
            [row["title"] for row in listed.data["topics"]], ["Мой запрос"]
        )

    def test_a_broken_condition_is_refused_at_saving_time(self):
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-topics"),
            {"title": "Кривой", "expression": {"колдовство": 1}},
            format="json",
        )
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "bank_expression_bad")

    def test_a_teacher_cannot_start_a_common_topic(self):
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-topics"),
            {"title": "Общая", "expression": {}, "level": "system"},
            format="json",
        )
        self.assertEqual(answer.status_code, 400)

    def test_a_colleague_does_not_see_my_topic(self):
        self.client.force_authenticate(self.user)
        self.client.post(
            reverse("bank-topics"), {"title": "Моя", "expression": {}}, format="json"
        )

        self.client.force_authenticate(self.colleague)
        listed = self.client.get(reverse("bank-topics"))
        self.assertEqual(listed.data["topics"], [])

    def test_deleting_a_parent_imprints_its_condition_into_the_children(self):
        parent = self.make_topic("Алгебра", {"solution": {"uses": [self.algebra.pk]}})
        child = self.make_topic(
            "Через Виета", {"solution": {"uses": [self.vieta.pk]}}, parent=parent
        )

        topics.remove(parent)
        child.refresh_from_db()

        # ветка не стала шире, чем была: условие родителя впечатано
        self.assertEqual(
            child.expression,
            {
                "all": [
                    {"solution": {"uses": [self.algebra.pk]}},
                    {"solution": {"uses": [self.vieta.pk]}},
                ]
            },
        )
        self.assertIsNone(child.parent_id)


class TagLinkTests(SchoolTestMixin, APITestCase):
    """
    Разметка тегами. Снятие проверяется отдельно от навешивания: права у них
    одни, а написаны они порознь — и однажды одно из двух осталось без них.
    """

    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.object_tag = Tag.objects.create(name="многочлен", kind=OBJECT)
        self.method = Tag.objects.create(name="производная", kind=METHOD)
        self.common = Problem.objects.create(text="$x^2=4$", created_by=self.root)
        self.common.links.create(tag=self.object_tag)

    def link(self, method, body):
        self.client.force_authenticate(self.user)
        return getattr(self.client, method)(
            reverse("bank-tag-links"), body, format="json"
        )

    def test_a_system_problem_cannot_be_undressed_by_a_teacher(self):
        answer = self.link(
            "delete", {"problem": self.common.pk, "tag": self.object_tag.pk}
        )
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "bank_read_only")
        self.assertEqual(self.common.links.count(), 1)

    def test_a_method_does_not_go_on_a_statement(self):
        mine = Problem.objects.create(
            text="…", school=self.school, owner=self.user, created_by=self.user
        )
        answer = self.link("post", {"problem": mine.pk, "tag": self.method.pk})
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "tag_kind_mismatch")


class ListQueryTests(SchoolTestMixin, APITestCase):
    """
    Списки задачника не должны дорожать от того, что на полке много книг.

    Право на правку у каждой строки своё, и спрошенное построчно оно даёт
    запрос на строку — ровно у того, ради кого полку и завели.
    """

    def test_the_shelf_costs_the_same_for_one_book_and_for_ten(self):
        self.client.force_authenticate(self.user)
        self.book("Одна")

        with CaptureQueriesContext(connection) as one:
            self.client.get(reverse("bank-sources"))

        for number in range(9):
            self.book(f"Книга {number}")

        with CaptureQueriesContext(connection) as ten:
            answer = self.client.get(reverse("bank-sources"))

        self.assertEqual(len(answer.data["sources"]), 10)
        self.assertEqual(len(ten.captured_queries), len(one.captured_queries))

    def book(self, title):
        return Source.objects.create(
            title=title, school=self.school, owner=self.user, created_by=self.user
        )


class BookListingTests(SchoolTestMixin, APITestCase):
    """
    С чего открывается книга. Ошибка тут выглядит как пустая книга при
    четырёх задачах в ней — и читается как поломка, а не как фильтр.
    """

    def setUp(self):
        super().setUp()
        self.book = Source.objects.create(
            title="Листочки", school=self.school, owner=self.user, created_by=self.user
        )
        self.chapter = Section.objects.create(source=self.book, title="Глава")
        self.inside = self.entry("1", self.chapter)
        self.outside = self.entry("2", None)

    def entry(self, label, section):
        problem = Problem.objects.create(
            text=f"Задача {label}",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        return Entry.objects.create(
            source=self.book, section=section, problem=problem, label=label
        )

    def open(self, **params):
        self.client.force_authenticate(self.user)
        answer = self.client.get(reverse("bank-source", args=[self.book.pk]), params)
        self.assertEqual(answer.status_code, 200)
        return [row["label"] for row in answer.data["entries"]]

    def test_a_book_opens_whole(self):
        self.assertEqual(sorted(self.open()), ["1", "2"])

    def test_a_chapter_narrows_it(self):
        self.assertEqual(self.open(section=self.chapter.pk), ["1"])

    def test_outside_the_chapters_is_a_choice_of_its_own(self):
        self.assertEqual(self.open(section="none"), ["2"])


class ForkTests(SchoolTestMixin, APITestCase):
    """
    Копия несёт разметку. Без этого подборка, набранная копированием, немая:
    она не ищется по граням — то есть самым частым способом.
    """

    def test_a_copy_carries_the_tags_and_the_answers(self):
        root = self.make_root()
        tag = Tag.objects.create(name="многочлен", kind=OBJECT)
        common = Problem.objects.create(
            text="$x^2=4$", answers=["2", "-2"], created_by=root
        )
        common.links.create(tag=tag)
        mine = Source.objects.create(
            title="Моя книга",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-copy"),
            {"problem": common.pk, "into": mine.pk, "mode": "fork"},
            format="json",
        )
        copy = Problem.objects.get(pk=answer.data["problem"])

        self.assertEqual([link.tag_id for link in copy.links.all()], [tag.pk])
        self.assertEqual(copy.answers, ["2", "-2"])
        self.assertEqual(copy.copied_from_id, common.pk)

        # у оригинала разметка не тронута: копия — вторая строка, а не переезд
        self.assertEqual(common.links.count(), 1)


class ShelvedTests(SchoolTestMixin, APITestCase):
    """
    «В книге» против «только в работе».

    После того как ячейка работы стала условием, личный поиск наполовину
    состоит из набранного на бегу. Это правильно — «я это уже спрашивал»
    обязано их находить, — но отличать одно от другого надо: грань и делает
    это, а строка результата называет место.
    """

    def setUp(self):
        super().setUp()
        self.book = Source.objects.create(
            title="Мои листочки",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        self.shelved = self.problem("В книге")
        Entry.objects.create(source=self.book, problem=self.shelved, label="1")
        self.scratch = self.problem("Только в работе")

    def problem(self, text):
        return Problem.objects.create(
            text=text, school=self.school, owner=self.user, created_by=self.user
        )

    def find(self, **params):
        self.client.force_authenticate(self.user)
        return self.client.get(reverse("bank-search"), params).data

    def test_by_default_everything_of_mine_is_found(self):
        self.assertEqual(self.find()["total"], 2)

    def test_the_facet_tells_them_apart(self):
        self.assertEqual(
            [row["id"] for row in self.find(shelved="yes")["problems"]],
            [self.shelved.pk],
        )
        self.assertEqual(
            [row["id"] for row in self.find(shelved="no")["problems"]],
            [self.scratch.pk],
        )

    def test_the_row_says_where_it_lies(self):
        rows = {row["id"]: row["where"] for row in self.find()["problems"]}
        self.assertEqual(rows[self.shelved.pk], {"kind": "book", "title": "Мои листочки"})
        self.assertIsNone(rows[self.scratch.pk])


class CopyManyTests(SchoolTestMixin, APITestCase):
    """
    Берут пачкой: главу, вариант, десяток отобранного. По одной — тот же путь
    с одним элементом, и второго кода для этого не заводится.
    """

    def setUp(self):
        super().setUp()
        self.root = self.make_root()
        self.common = [
            Problem.objects.create(text=f"Общая {number}", created_by=self.root)
            for number in (1, 2, 3)
        ]
        self.mine = Source.objects.create(
            title="Моя книга",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

    def test_a_handful_lands_in_the_order_it_was_picked(self):
        wanted = [one.pk for one in reversed(self.common)]
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-copy"),
            {"problems": wanted, "into": self.mine.pk},
            format="json",
        )

        self.assertEqual(answer.status_code, 201)
        self.assertEqual(answer.data["taken"], 3)
        self.assertEqual(
            [entry.problem_id for entry in self.mine.entries.order_by("position")],
            wanted,
        )

    def test_an_empty_pick_is_refused(self):
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-copy"), {"problems": [], "into": self.mine.pk}, format="json"
        )
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "bank_nothing_to_copy")


class PartsTests(SchoolTestMixin, APITestCase):
    """
    Пункты задачи: два дерева и то, как их различает вставка.

    Главное здесь — что **буква принадлежит книге, а не задаче**: один и тот
    же пункт бывает «3а» у Мордковича и «5б» у Галицкого, и обе метки
    правдивы. И что сюжет — не задача: у него нет ни вопроса, ни ответа.
    """

    def setUp(self):
        super().setUp()
        self.book = Source.objects.create(
            title="Мордкович",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )

    def fill(self, text, source=None):
        return services.add_problems(
            source or self.book, section=None, text=text, user=self.user
        )

    def test_a_stem_with_parts_makes_one_number_and_two_letters(self):
        made = self.fill(
            "3\tДан треугольник ABC со сторонами 3, 4, 5.\n"
            "  а)\tНайдите площадь.\n"
            "  б)\tНайдите радиус вписанной окружности."
        )

        # задач две: сюжет в счёт не идёт, он не задача
        self.assertEqual(made, 2)

        number = self.book.entries.get(parent__isnull=True)
        self.assertEqual(number.label, "3")
        self.assertEqual(number.problem.text, "Дан треугольник ABC со сторонами 3, 4, 5.")

        letters = list(number.children.order_by("position"))
        self.assertEqual([one.label for one in letters], ["а)", "б)"])
        # дерево задачи: пункты — дети сюжета, и порядок у них авторский
        self.assertEqual(
            [one.problem.parent_id for one in letters], [number.problem_id] * 2
        )
        self.assertEqual([one.problem.position for one in letters], [0, 1])

    def test_a_bare_number_leaves_its_parts_independent(self):
        # «15. а) x²=4 б) x²=9» — четыре уравнения под одним номером, но
        # ничем, кроме номера, не связанные
        made = self.fill("15\n  а)\t$x^2=4$\n  б)\t$x^2=9$")

        self.assertEqual(made, 2)
        number = self.book.entries.get(parent__isnull=True)
        self.assertIsNone(number.problem)
        self.assertEqual(
            [one.problem.parent_id for one in number.children.all()], [None, None]
        )

    def test_letters_written_into_the_number_stay_separate_problems(self):
        made = self.fill("16а\tРешите неравенство\n16б\tПостройте график")

        self.assertEqual(made, 2)
        self.assertEqual(self.book.entries.filter(parent__isnull=True).count(), 2)
        self.assertFalse(Problem.objects.filter(parent__isnull=False).exists())

    def test_an_indent_without_a_number_above_is_refused(self):
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-source", args=[self.book.pk]),
            {"problems": "  а)\tОдин пункт без номера"},
            format="json",
        )
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "part_without_number")

    def test_the_same_part_gets_its_own_label_in_another_book(self):
        self.fill("3\tДан треугольник ABC.\n  а)\tНайдите площадь.")
        part = Problem.objects.get(text="Найдите площадь.")

        other = Source.objects.create(
            title="Галицкий",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        number = Entry.objects.create(source=other, label="5")
        Entry.objects.create(source=other, parent=number, problem=part, label="5б")

        # одно условие, два адреса, и обе метки живут на строках книг
        self.assertEqual(
            sorted(entry.label for entry in part.entries.all()), ["5б", "а)"]
        )
        # а дерево задачи от этого не двоится: сюжет у пункта один
        self.assertEqual(part.parent.text, "Дан треугольник ABC.")

    def test_a_phrase_over_parts_needs_a_tab_rather_than_a_guess(self):
        # «15» с пунктами — номер, а «Решите уравнение:» — условие сюжета.
        # Различить их можно только разделителем, и вместо угадывания отказ.
        self.client.force_authenticate(self.user)
        answer = self.client.post(
            reverse("bank-source", args=[self.book.pk]),
            {"problems": "Решите уравнение:\n  а)\t$x^2=4$"},
            format="json",
        )
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "number_needs_a_tab")

    def test_a_part_of_a_part_is_refused(self):
        self.fill("3\tСюжет.\n  а)\tПункт.")
        part = Problem.objects.get(text="Пункт.")
        deeper = Problem(
            text="Подпункт", school=self.school, owner=self.user, parent=part
        )

        with self.assertRaises(ValidationError):
            deeper.full_clean()


class FamilyInTheListTests(SchoolTestMixin, APITestCase):
    """
    Семья аналогов стоит в выдаче **одной строкой**.

    Аналогов у задачи бывают сотни: та же задача с другими числами, разосланная
    по вариантам. Показывать каждую — значит замылить выдачу одним и тем же
    условием, а искать в ней станет невозможно. Строка поэтому одна, и она же
    дверь: с её страницы видны все аналоги.
    """

    def setUp(self):
        super().setUp()
        self.tag = Tag.objects.create(name="уравнение", kind="task")
        self.family = [self.problem(f"$x^2 = {number}$") for number in (4, 9, 16)]
        self.alone = self.problem("Окружность вписана в треугольник")

        self.client.force_authenticate(self.user)
        for other in self.family[1:]:
            self.client.post(
                reverse("bank-analogues"),
                {"problem": self.family[0].pk, "other": other.pk},
                format="json",
            )

    def problem(self, text):
        made = Problem.objects.create(
            text=text, school=self.school, owner=self.user, created_by=self.user
        )
        made.links.create(tag=self.tag)
        return made

    def find(self, **params):
        self.client.force_authenticate(self.user)
        return self.client.get(reverse("bank-search"), params).data

    def test_a_family_takes_one_row_and_says_how_many_more(self):
        found = self.find()

        # четыре задачи, но семей две: три уравнения — одно и то же условие
        self.assertEqual(found["total"], 2)
        rows = {row["id"]: row for row in found["problems"]}
        self.assertEqual(len(rows), 2)

        shown = next(row for row in found["problems"] if row["family"])
        self.assertEqual(shown["analogues"], 2)
        self.assertEqual(rows[self.alone.pk]["analogues"], 0)

    def test_the_facets_count_families_too(self):
        # грань, обещавшая четыре и оставившая две строки, врала бы
        rows = {row["tag"]: row["count"] for row in self.find()["facets"]}
        self.assertEqual(rows[self.tag.pk], 2)

    def test_leaving_the_family_brings_the_problem_back_as_its_own_row(self):
        self.client.delete(
            reverse("bank-analogues"), {"problem": self.family[1].pk}, format="json"
        )
        found = self.find()

        # вышел из семьи — стал отдельной строкой: строк три, а не две
        self.assertEqual(found["total"], 3)


class SubjectTests(SchoolTestMixin, APITestCase):
    """
    Предмет — самый глобальный фильтр, и он же обычный тег.

    Своего поля у задачи под него нет намеренно: второе хранилище предмета
    разошлось бы с разметкой на первой же правке. А вот у книги поле есть — и
    её предмет достаётся вписанным в неё задачам, иначе фильтр не работал бы
    ровно там, где задач больше всего.
    """

    def setUp(self):
        super().setUp()
        self.algebra = Tag.objects.create(name="алгебра", kind="subject")
        self.geometry = Tag.objects.create(name="геометрия", kind="subject")

        self.book = Source.objects.create(
            title="Алгебра, сборник",
            subject=self.algebra,
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        services.add_problems(
            self.book, section=None, text="1\tРешите уравнение", user=self.user
        )

    def test_a_problem_typed_into_a_book_takes_its_subject(self):
        problem = self.book.entries.get().problem
        self.assertEqual(
            [link.tag_id for link in problem.links.all()], [self.algebra.pk]
        )

    def test_the_search_narrows_by_subject(self):
        other = Source.objects.create(
            title="Геометрия",
            subject=self.geometry,
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        services.add_problems(other, section=None, text="1\tНайдите угол", user=self.user)

        self.client.force_authenticate(self.user)
        found = self.client.get(
            reverse("bank-search"), {"subject": self.algebra.pk}
        ).data
        self.assertEqual([row["text"] for row in found["problems"]], ["Решите уравнение"])

    def test_a_part_is_found_by_the_subject_of_its_stem(self):
        # у пункта своей разметки может не быть вовсе, а предмет у него тот же
        services.add_problems(
            self.book,
            section=None,
            text="7\tДан треугольник\n  а)\tНайдите площадь",
            user=self.user,
        )
        part = Problem.objects.get(text="Найдите площадь")
        part.links.all().delete()

        self.client.force_authenticate(self.user)
        found = self.client.get(
            reverse("bank-search"), {"subject": self.algebra.pk, "text": "площадь"}
        ).data
        self.assertEqual([row["id"] for row in found["problems"]], [part.pk])

    def test_the_shelf_narrows_by_subject_too(self):
        Source.objects.create(
            title="Геометрия",
            subject=self.geometry,
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        self.client.force_authenticate(self.user)
        shelf = self.client.get(reverse("bank-sources"), {"subject": self.algebra.pk})
        self.assertEqual(
            [row["title"] for row in shelf.data["sources"]], ["Алгебра, сборник"]
        )


class ImportTests(SchoolTestMixin, APITestCase):
    """
    Массовый импорт таблицей: колонка «Пункт» различает то же, что отступ.

    Формат один на три входа (вставка таблицы, CSV, книга Excel), и пишет их
    один код — иначе три пути завели бы три немного разных книги.
    """

    def setUp(self):
        super().setUp()
        self.book = Source.objects.create(
            title="Импортированная",
            school=self.school,
            owner=self.user,
            created_by=self.user,
        )
        self.client.force_authenticate(self.user)

    def send(self, rows, **extra):
        return self.client.post(
            reverse("bank-import", args=[self.book.pk]),
            {"rows": rows, **extra},
            format="json",
        )

    HEADER = ["Раздел", "Номер", "Пункт", "Условие", "Ответ"]

    def test_a_table_lands_as_sections_numbers_and_parts(self):
        answer = self.send(
            [
                self.HEADER,
                ["Квадратные уравнения", "14", "", "Дан треугольник ABC.", ""],
                ["Квадратные уравнения", "14", "а)", "Найдите площадь", "6"],
                ["Квадратные уравнения", "14", "б)", "Найдите радиус", "1"],
                ["Квадратные уравнения", "15", "а)", "$x^2=4$", "±2"],
            ]
        )

        self.assertEqual(answer.status_code, 201)
        # задач три: сюжет в счёт не идёт
        self.assertEqual(answer.data["added"], 3)

        # раздел завёлся сам: заводить оглавление отдельным заходом —
        # издевательство над тем, кто принёс таблицу
        self.assertEqual([one.title for one in self.book.sections.all()],
                         ["Квадратные уравнения"])

        numbers = list(self.book.entries.filter(parent__isnull=True).order_by("position"))
        self.assertEqual([one.label for one in numbers], ["14", "15"])
        # у четырнадцатого сюжет, у пятнадцатого — чистый номер
        self.assertEqual(numbers[0].problem.text, "Дан треугольник ABC.")
        self.assertIsNone(numbers[1].problem)

        part = numbers[0].children.first()
        self.assertEqual(part.problem.answers, ["6"])
        self.assertEqual(part.problem.parent_id, numbers[0].problem_id)

    def test_a_part_without_a_number_is_refused_with_its_line(self):
        answer = self.send([self.HEADER, ["", "", "а)", "Пункт без номера", ""]])

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "part_without_number")
        self.assertEqual(answer.data["params"]["line"], 2)

    def test_a_wrong_header_is_refused_rather_than_guessed(self):
        answer = self.send([["Задача", "Ответ"], ["…", "…"]])

        self.assertEqual(answer.status_code, 400)
        self.assertEqual(answer.data["code"], "csv_header_invalid")

    def test_the_preview_writes_nothing_and_refuses_nothing(self):
        answer = self.send(
            [self.HEADER, ["", "", "а)", "Пункт без номера", ""]], preview=True
        )

        # ошибка приезжает списком в теле: иначе единственным её следом была бы
        # ошибка в консоли браузера
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.data["errors"])
        self.assertFalse(self.book.entries.exists())

    def test_the_preview_counts_what_will_appear(self):
        answer = self.send(
            [
                self.HEADER,
                ["Глава", "14", "", "Сюжет", ""],
                ["Глава", "14", "а)", "Пункт", ""],
                ["Глава", "20", "", "Обычная задача", ""],
            ],
            preview=True,
        )

        self.assertEqual(answer.data["numbers"], 2)
        self.assertEqual(answer.data["problems"], 2)
        self.assertEqual(answer.data["stems"], 1)
        self.assertEqual(answer.data["sections"], 1)

    def test_a_book_that_is_not_mine_takes_nothing(self):
        alien = Source.objects.create(
            title="Чужая",
            school=self.school,
            owner=self.colleague,
            created_by=self.colleague,
        )
        answer = self.client.post(
            reverse("bank-import", args=[alien.pk]),
            {"rows": [self.HEADER, ["", "1", "", "Задача", ""]]},
            format="json",
        )
        self.assertEqual(answer.status_code, 404)


class AdminSeesWhatHeMayFixTests(SchoolTestMixin, APITestCase):
    """
    Администратор школы видит то, что вправе править.

    Право у него было с самого начала, а видимости не было — и ветка была
    недостижима: объект не находился раньше, чем спрашивалось право. Наружу
    это вылезло на предложениях: он разбирал сообщение об опечатке в задаче,
    которую не мог открыть.
    """

    def test_a_personal_problem_of_a_colleague_is_visible_to_the_admin(self):
        mine = Problem.objects.create(
            text="Личная", school=self.school, owner=self.user, created_by=self.user
        )

        self.assertIn(mine, Problem.objects.visible_to(self.admin))
        # и править её он тоже вправе: одно без другого не работало
        self.assertIn(mine, Problem.objects.writable_by(self.admin))

    def test_a_colleague_still_does_not_see_it(self):
        mine = Problem.objects.create(
            text="Личная", school=self.school, owner=self.user, created_by=self.user
        )

        # право даёт роль, а не членство: рядовой учитель как не видел, так и
        # не видит
        self.assertNotIn(mine, Problem.objects.visible_to(self.colleague))

    def test_another_school_is_still_invisible_to_its_admin(self):
        mine = Problem.objects.create(
            text="Наша", school=self.school, owner=self.user, created_by=self.user
        )

        self.assertNotIn(mine, Problem.objects.visible_to(self.alien_admin))
