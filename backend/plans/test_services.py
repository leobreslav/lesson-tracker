"""Нумерация и правила дерева. Базы здесь нет — только чистые функции."""

from dataclasses import dataclass

from django.test import SimpleTestCase

from . import services
from .owning import PlanOwner

#: Владелец по умолчанию у всего, что заводит `FakeNode`.
COURSE = PlanOwner("course", 1)


@dataclass
class FakeNode:
    """Минимум полей, которых хватает ядру services."""

    pk: int
    position: int
    is_section: bool = False
    parent_id: int | None = None
    title: str = ""
    course_id: int | None = 1
    template_id: int | None = None


def section(pk, position, title=""):
    return FakeNode(pk=pk, position=position, is_section=True, title=title)


def lesson(pk, position, parent_id=None, title=""):
    return FakeNode(pk=pk, position=position, parent_id=parent_id, title=title)


# папка, папка, урок, урок, папка — как в примере из задания
MIXED = [
    section(1, 0, "Тригонометрия"),
    lesson(11, 0, parent_id=1, title="Синус суммы"),
    lesson(12, 1, parent_id=1, title="Косинус суммы"),
    section(2, 1, "Векторы"),
    lesson(21, 0, parent_id=2, title="Понятие вектора"),
    lesson(22, 1, parent_id=2, title="Сложение векторов"),
    lesson(3, 2, title="Повторение"),
    lesson(4, 3, title="Контрольная работа"),
    section(5, 4, "Стереометрия"),
    lesson(51, 0, parent_id=5, title="Аксиомы"),
]


class BuildTreeTests(SimpleTestCase):
    def test_top_level_keeps_positions(self):
        tree = services.build_tree(MIXED)

        self.assertEqual(
            [branch.node.title for branch in tree],
            ["Тригонометрия", "Векторы", "Повторение", "Контрольная работа", "Стереометрия"],
        )

    def test_children_are_nested_and_ordered(self):
        tree = services.build_tree(MIXED)

        self.assertEqual(
            [child.title for child in tree[0].children],
            ["Синус суммы", "Косинус суммы"],
        )
        self.assertEqual(tree[2].children, ())

    def test_order_does_not_depend_on_input_order(self):
        tree = services.build_tree(list(reversed(MIXED)))

        self.assertEqual(
            [branch.node.pk for branch in tree], [1, 2, 3, 4, 5]
        )
        self.assertEqual([child.pk for child in tree[1].children], [21, 22])


class NumberingTests(SimpleTestCase):
    def numbers(self, nodes=MIXED):
        return [
            (item.number, item.node.title)
            for item in services.number_lessons(services.build_tree(nodes))
        ]

    def test_depth_first_order(self):
        self.assertEqual(
            self.numbers(),
            [
                (1, "Синус суммы"),
                (2, "Косинус суммы"),
                (3, "Понятие вектора"),
                (4, "Сложение векторов"),
                (5, "Повторение"),
                (6, "Контрольная работа"),
                (7, "Аксиомы"),
            ],
        )

    def test_sections_do_not_take_numbers(self):
        titles = [title for _, title in self.numbers()]

        self.assertNotIn("Тригонометрия", titles)
        self.assertNotIn("Стереометрия", titles)

    def test_numbering_is_continuous(self):
        numbers = [number for number, _ in self.numbers()]

        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_empty_section_does_not_break_the_run(self):
        nodes = [section(1, 0, "Пустая"), lesson(2, 1, title="Первый")]

        self.assertEqual(self.numbers(nodes), [(1, "Первый")])

    def test_lesson_carries_its_section(self):
        lessons = services.number_lessons(services.build_tree(MIXED))

        self.assertEqual(lessons[0].section.title, "Тригонометрия")
        self.assertIsNone(lessons[4].section)

    def test_no_lessons_at_all(self):
        self.assertEqual(self.numbers([section(1, 0, "Пустая")]), [])


class CountsTests(SimpleTestCase):
    def test_counts_lessons_and_sections(self):
        nodes = MIXED + [lesson(6, 5, title="Ещё урок")]

        self.assertEqual(
            services.counts(services.build_tree(nodes)),
            {"lessons": 8, "sections": 3},
        )


class StructureTests(SimpleTestCase):
    def test_root_level_is_always_fine(self):
        self.assertEqual(
            services.structure_problems(owner=COURSE, parent=None, is_section=True),
            {},
        )

    def test_section_inside_section_is_forbidden(self):
        problems = services.structure_problems(
            owner=COURSE, parent=section(1, 0), is_section=True
        )

        self.assertIn("parent", problems)

    def test_lesson_cannot_be_nested_into_a_lesson(self):
        problems = services.structure_problems(
            owner=COURSE, parent=lesson(1, 0), is_section=False
        )

        self.assertIn("parent", problems)

    def test_parent_from_another_class_is_forbidden(self):
        alien = section(1, 0)
        alien.course_id = 2

        problems = services.structure_problems(
            owner=COURSE, parent=alien, is_section=False
        )

        self.assertIn("parent", problems)

    def test_a_section_from_the_shelf_is_not_a_parent_for_a_course(self):
        """
        Владельцы сравниваются целиком, а не по номеру.

        У курса №1 и у шаблона №1 номер один и тот же, и сравнение по числу
        разрешило бы взять в родители тему с чужой полки — то есть склеить
        два дерева в одно, о чём не узнал бы никто: на экране курса такая
        строка просто не показалась бы.
        """
        from_the_shelf = section(1, 0)
        from_the_shelf.course_id = None
        from_the_shelf.template_id = 1

        problems = services.structure_problems(
            owner=COURSE, parent=from_the_shelf, is_section=False
        )

        self.assertIn("parent", problems)

    def test_lesson_inside_a_section_is_allowed(self):
        self.assertEqual(
            services.structure_problems(
                owner=COURSE, parent=section(1, 0), is_section=False
            ),
            {},
        )
