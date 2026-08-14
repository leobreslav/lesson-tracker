from datetime import date

from calendars.models import SchoolYear
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import assign, SchoolTestMixin, make_course, make_node

from . import services
from .models import PlanNode


class PlanTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.course = self.make_course(self.school, "9Б")
        assign(self.user, self.course)
        self.alien_class = self.make_course(self.alien_school, "9А")

    def owner(self, teacher=None, course=None):
        """The (teacher, course) pair every plan query needs."""
        return services.PlanOwner(
            teacher_id=(teacher or self.user).pk, course_id=(course or self.course).pk
        )

    def make_course(self, school, name):
        return make_course(school, name=name)

    def add(self, title, parent=None, position=0, is_section=False, course=None,
            teacher=None):
        return make_node(
            teacher or self.user,
            course or self.course,
            title,
            parent=parent,
            position=position,
            section=is_section,
        )

    def build_sample(self):
        """Пример из задания: папка, папка, урок, урок, папка."""
        trig = self.add("Тригонометрия", position=0, is_section=True)
        self.add("Синус суммы", parent=trig, position=0)
        self.add("Косинус суммы", parent=trig, position=1)

        vectors = self.add("Векторы", position=1, is_section=True)
        self.add("Понятие вектора", parent=vectors, position=0)
        self.add("Сложение векторов", parent=vectors, position=1)

        self.add("Повторение", position=2)
        self.add("Контрольная работа", position=3)

        stereo = self.add("Стереометрия", position=4, is_section=True)
        self.add("Аксиомы", parent=stereo, position=0)

        return trig, vectors, stereo

    # --- вспомогательные срезы состояния ---

    def node(self, title):
        return PlanNode.objects.get(course=self.course, title=title)

    def numbers(self):
        return {
            item.node.title: item.number
            for item in services.flatten_lessons(self.owner())
        }

    def structure(self):
        """Дерево как список строк — читаемые ожидания в тестах."""
        rows = []
        for branch in services.get_tree(self.owner()):
            rows.append(branch.node.title)
            rows.extend(f"  {child.title}" for child in branch.children)
        return rows

    def titles_with_notes(self):
        """
        Срез плана вместе с заметками — для сверки после кругового CSV.

        Тема урока — часть среза, и это важно: пока строки шли плоским
        списком, урок внутри темы и урок на верхнем уровне давали одинаковый
        кортеж, и круговой тест не заметил, как импорт перестал вкладывать
        уроки в темы вовсе.
        """
        rows = []
        for branch in services.get_tree(self.owner()):
            rows.append((None, branch.node.title, branch.node.note, branch.node.is_section))
            rows.extend(
                (branch.node.title, child.title, child.note, child.is_section)
                for child in branch.children
            )
        return rows

    def positions(self, parent=None):
        return [node.position for node in services.level(self.owner(), parent)]

    # --- запросы ---

    def tree(self, course=None):
        return self.client.get(
            reverse("plannode-list"),
            {"course": (course or self.course).pk},
        )

    def move(self, node, direction):
        return self.client.post(
            reverse("plannode-move", args=[node.pk]),
            {"direction": direction},
            format="json",
        )


class TreeApiTests(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.build_sample()

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.tree().status_code, 401)

    def test_class_parameter_is_required(self):
        response = self.client.get(reverse("plannode-list"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "class_required")

    def test_tree_is_nested_and_numbered(self):
        data = self.tree().json()

        titles = [item["title"] for item in data["nodes"]]
        self.assertEqual(
            titles,
            ["Тригонометрия", "Векторы", "Повторение", "Контрольная работа", "Стереометрия"],
        )

        trig = data["nodes"][0]
        self.assertTrue(trig["is_section"])
        self.assertIsNone(trig["number"])
        self.assertEqual(
            [(child["title"], child["number"]) for child in trig["children"]],
            [("Синус суммы", 1), ("Косинус суммы", 2)],
        )
        self.assertEqual(data["nodes"][2]["number"], 5)
        self.assertEqual(data["nodes"][4]["children"][0]["number"], 7)

    def test_counts(self):
        self.assertEqual(
            self.tree().json()["counts"],
            {"lessons": 7, "sections": 3},
        )

    def test_lessons_come_out_in_order_with_their_sections(self):
        """
        Последовательность уроков — та самая, что ложится на слоты.

        Раньше её проверяли через `/api/plan/flat/`; эндпоинт убран как
        никем не вызываемый, а сама последовательность нужна по-прежнему —
        на ней держится вся раскладка, поэтому проверяем функцию.
        """
        lessons = services.flatten_lessons(self.owner())

        self.assertEqual([item.number for item in lessons], list(range(1, 8)))
        self.assertEqual(lessons[0].section.title, "Тригонометрия")
        self.assertIsNone(lessons[4].section)

    def test_another_users_class_is_not_found(self):
        response = self.tree(self.alien_class)

        self.assertEqual(response.status_code, 404)


class CreateTests(PlanTestCase):
    def post(self, **fields):
        payload = {"course": self.course.pk, "title": "Новый", **fields}
        return self.client.post(reverse("plannode-list"), payload, format="json")

    def test_lesson_goes_to_the_end_of_the_level(self):
        self.build_sample()

        response = self.post(title="Ещё урок")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            self.structure()[-3:], ["Стереометрия", "  Аксиомы", "Ещё урок"]
        )
        self.assertEqual(self.node("Ещё урок").position, 5)
        self.assertEqual(self.numbers()["Ещё урок"], 8)

    def test_lesson_inside_a_section(self):
        trig, _, _ = self.build_sample()

        response = self.post(title="Тангенс", parent=trig.pk)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.node("Тангенс").position, 2)
        self.assertEqual(self.numbers()["Тангенс"], 3)

    def test_insert_after_a_given_node(self):
        self.build_sample()
        first = self.node("Повторение")

        response = self.post(title="Вставка", after=first.pk)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            self.structure(),
            [
                "Тригонометрия",
                "  Синус суммы",
                "  Косинус суммы",
                "Векторы",
                "  Понятие вектора",
                "  Сложение векторов",
                "Повторение",
                "Вставка",
                "Контрольная работа",
                "Стереометрия",
                "  Аксиомы",
            ],
        )
        self.assertEqual(self.positions(), [0, 1, 2, 3, 4, 5])

    def test_after_from_another_level_is_rejected(self):
        trig, _, _ = self.build_sample()
        inside = self.node("Синус суммы")

        response = self.post(title="Вставка", after=inside.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "anchor_other_level")

    def test_section_inside_section_is_forbidden(self):
        trig, _, _ = self.build_sample()

        response = self.post(title="Вложенная", is_section=True, parent=trig.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "section_inside_section")

    def test_lesson_inside_lesson_is_forbidden(self):
        self.build_sample()

        response = self.post(title="Вложенный", parent=self.node("Повторение").pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "parent_not_section")

    def test_cannot_create_in_another_users_class(self):
        response = self.client.post(
            reverse("plannode-list"),
            {"class": self.alien_class.pk, "title": "Чужой"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(PlanNode.objects.filter(title="Чужой").exists())

    def test_model_clean_forbids_nested_section(self):
        trig, _, _ = self.build_sample()
        node = PlanNode(
            teacher=self.user,
            course=self.course,
            parent=trig,
            position=9,
            is_section=True,
            title="Вложенная",
        )

        with self.assertRaises(ValidationError) as caught:
            node.full_clean()

        self.assertIn("parent", caught.exception.message_dict)

    def test_model_clean_forbids_duplicate_position(self):
        self.build_sample()
        node = PlanNode(
            teacher=self.user, course=self.course, parent=None, position=0, title="Дубль"
        )

        with self.assertRaises(ValidationError) as caught:
            node.full_clean()

        self.assertIn("position", caught.exception.message_dict)


class UpdateAndDeleteTests(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.trig, self.vectors, self.stereo = self.build_sample()

    def test_patch_edits_content(self):
        node = self.node("Повторение")

        response = self.client.patch(
            reverse("plannode-detail", args=[node.pk]),
            {"title": "Повторение курса", "note": "две пары"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        node.refresh_from_db()
        self.assertEqual(node.title, "Повторение курса")
        self.assertEqual(node.note, "две пары")

    def test_patch_cannot_reparent(self):
        node = self.node("Повторение")

        self.client.patch(
            reverse("plannode-detail", args=[node.pk]),
            {"parent": self.trig.pk, "position": 0, "is_section": True},
            format="json",
        )

        node.refresh_from_db()
        self.assertIsNone(node.parent_id)
        self.assertFalse(node.is_section)

    def test_delete_lesson_closes_the_gap(self):
        response = self.client.delete(
            reverse("plannode-detail", args=[self.node("Повторение").pk])
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.positions(), [0, 1, 2, 3])
        self.assertEqual(self.numbers()["Контрольная работа"], 5)

    def test_delete_section_keeping_children(self):
        response = self.client.delete(
            f"{reverse('plannode-detail', args=[self.vectors.pk])}?keep_children=true"
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.structure(),
            [
                "Тригонометрия",
                "  Синус суммы",
                "  Косинус суммы",
                "Понятие вектора",
                "Сложение векторов",
                "Повторение",
                "Контрольная работа",
                "Стереометрия",
                "  Аксиомы",
            ],
        )
        self.assertEqual(self.positions(), [0, 1, 2, 3, 4, 5])
        # нумерация не поехала: уроки остались на своих местах
        self.assertEqual(self.numbers()["Аксиомы"], 7)

    def test_delete_section_with_children(self):
        response = self.client.delete(
            f"{reverse('plannode-detail', args=[self.vectors.pk])}?keep_children=false"
        )

        self.assertEqual(response.status_code, 204)
        self.assertNotIn("Понятие вектора", self.numbers())
        self.assertEqual(self.positions(), [0, 1, 2, 3])
        self.assertEqual(self.numbers()["Повторение"], 3)

    def test_delete_keeps_children_by_default(self):
        self.client.delete(reverse("plannode-detail", args=[self.vectors.pk]))

        self.assertIn("Понятие вектора", self.numbers())

    def test_cannot_delete_another_users_node(self):
        alien = self.add("Чужой", course=self.alien_class, teacher=self.stranger)

        response = self.client.delete(reverse("plannode-detail", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(PlanNode.objects.filter(pk=alien.pk).exists())


class MoveTests(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.trig, self.vectors, self.stereo = self.build_sample()

    def test_swap_inside_a_section(self):
        self.move(self.node("Синус суммы"), services.DOWN)

        self.assertEqual(
            self.structure()[:3],
            ["Тригонометрия", "  Косинус суммы", "  Синус суммы"],
        )

    def test_top_level_lesson_enters_the_section_below_as_first(self):
        self.move(self.node("Повторение"), services.DOWN)

        # ниже «Повторения» лежит «Контрольная работа», а не папка
        self.assertEqual(
            self.structure()[6:8], ["Контрольная работа", "Повторение"]
        )

        self.move(self.node("Повторение"), services.DOWN)

        self.assertEqual(
            self.structure()[7:], ["Стереометрия", "  Повторение", "  Аксиомы"]
        )

    def test_top_level_lesson_enters_the_section_above_as_last(self):
        self.move(self.node("Повторение"), services.UP)

        self.assertEqual(
            self.structure()[3:7],
            ["Векторы", "  Понятие вектора", "  Сложение векторов", "  Повторение"],
        )

    def test_lesson_leaves_the_section_downwards(self):
        self.move(self.node("Сложение векторов"), services.DOWN)

        self.assertEqual(
            self.structure()[3:6],
            ["Векторы", "  Понятие вектора", "Сложение векторов"],
        )
        self.assertEqual(self.numbers()["Сложение векторов"], 4)

    def test_lesson_leaves_the_section_upwards(self):
        self.move(self.node("Понятие вектора"), services.UP)

        self.assertEqual(
            self.structure()[3:6],
            ["Понятие вектора", "Векторы", "  Сложение векторов"],
        )
        self.assertEqual(self.numbers()["Понятие вектора"], 3)

    def test_first_node_cannot_go_up(self):
        response = self.move(self.node("Тригонометрия"), services.UP)

        self.assertFalse(response.json()["moved"])
        self.assertEqual(self.structure()[0], "Тригонометрия")

    def test_last_node_cannot_go_down(self):
        response = self.move(self.node("Стереометрия"), services.DOWN)

        self.assertFalse(response.json()["moved"])
        self.assertEqual(self.structure()[-2], "Стереометрия")

    def test_first_lesson_of_the_first_section_goes_out_and_stops(self):
        node = self.node("Синус суммы")

        self.assertTrue(self.move(node, services.UP).json()["moved"])
        self.assertEqual(self.structure()[0], "Синус суммы")

        node.refresh_from_db()
        self.assertFalse(self.move(node, services.UP).json()["moved"])

    def test_last_lesson_of_the_last_section_goes_out_and_stops(self):
        node = self.node("Аксиомы")

        self.assertTrue(self.move(node, services.DOWN).json()["moved"])
        self.assertEqual(self.structure()[-1], "Аксиомы")

        node.refresh_from_db()
        self.assertFalse(self.move(node, services.DOWN).json()["moved"])

    def test_section_moves_with_its_children(self):
        self.move(self.vectors, services.UP)

        self.assertEqual(
            self.structure(),
            [
                "Векторы",
                "  Понятие вектора",
                "  Сложение векторов",
                "Тригонометрия",
                "  Синус суммы",
                "  Косинус суммы",
                "Повторение",
                "Контрольная работа",
                "Стереометрия",
                "  Аксиомы",
            ],
        )
        self.assertEqual(self.numbers()["Понятие вектора"], 1)

    def test_section_endpoint_moves_the_block(self):
        response = self.client.post(
            reverse("plansection-move", args=[self.vectors.pk]),
            {"direction": services.DOWN},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.structure()[3], "Повторение")
        self.assertEqual(self.structure()[4], "Векторы")

    def test_section_endpoint_rejects_a_lesson(self):
        response = self.client.post(
            reverse("plansection-move", args=[self.node("Повторение").pk]),
            {"direction": services.DOWN},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_bad_direction_is_rejected(self):
        response = self.client.post(
            reverse("plannode-move", args=[self.node("Повторение").pk]),
            {"direction": "sideways"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_cannot_move_another_users_node(self):
        alien = self.add("Чужой", course=self.alien_class, teacher=self.stranger)

        response = self.move(alien, services.DOWN)

        self.assertEqual(response.status_code, 404)

    def test_walking_up_visits_every_position(self):
        """
        Кнопкой «вверх» урок должен пройти весь план до первого места,
        нигде не перепрыгивая через соседа и не теряясь.
        """
        node = self.node("Повторение")
        seen = [self.numbers()["Повторение"]]

        for _ in range(50):
            if not self.move(node, services.UP).json()["moved"]:
                break
            node.refresh_from_db()
            seen.append(self.numbers()["Повторение"])

        self.assertEqual(seen[0], 5)
        self.assertEqual(seen[-1], 1)
        # шаг меняет номер не больше чем на единицу и только в одну сторону
        for before, after in zip(seen, seen[1:]):
            self.assertIn(before - after, (0, 1))
        self.assertEqual(len(self.numbers()), 7)

    def test_walking_down_reaches_the_last_place(self):
        node = self.node("Синус суммы")
        seen = [self.numbers()["Синус суммы"]]

        for _ in range(50):
            if not self.move(node, services.DOWN).json()["moved"]:
                break
            node.refresh_from_db()
            seen.append(self.numbers()["Синус суммы"])

        self.assertEqual(seen[0], 1)
        self.assertEqual(seen[-1], 7)
        for before, after in zip(seen, seen[1:]):
            self.assertIn(after - before, (0, 1))
        self.assertEqual(len(self.numbers()), 7)


class MoveToTests(PlanTestCase):
    def setUp(self):
        super().setUp()
        self.trig, self.vectors, self.stereo = self.build_sample()

    def move_to(self, node, parent, position):
        return self.client.post(
            reverse("plannode-move-to", args=[node.pk]),
            {"parent": parent.pk if parent else None, "position": position},
            format="json",
        )

    def test_move_lesson_into_a_section(self):
        response = self.move_to(self.node("Повторение"), self.stereo, 0)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.structure()[-3:], ["Стереометрия", "  Повторение", "  Аксиомы"])
        self.assertEqual(self.positions(), [0, 1, 2, 3])

    def test_move_lesson_to_the_top_level(self):
        response = self.move_to(self.node("Косинус суммы"), None, 0)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.structure()[:3], ["Косинус суммы", "Тригонометрия", "  Синус суммы"])
        self.assertEqual(self.numbers()["Косинус суммы"], 1)

    def test_position_beyond_the_level_is_clamped(self):
        response = self.move_to(self.node("Повторение"), None, 99)

        self.assertEqual(response.status_code, 200, response.content)
        # позиция за краем уровня — узел встаёт последним
        self.assertEqual(self.structure()[-1], "Повторение")
        self.assertEqual(self.numbers()["Повторение"], 7)

    def test_section_cannot_be_nested(self):
        response = self.move_to(self.vectors, self.trig, 0)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "section_inside_section")

    def test_lesson_cannot_be_nested_into_a_lesson(self):
        response = self.move_to(self.node("Повторение"), self.node("Аксиомы"), 0)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "parent_not_section")

    def test_every_position_inside_a_section_is_accepted(self):
        lesson = self.node("Повторение")

        for position, expected in ((0, 0), (1, 1), (2, 2), (9, 2)):
            with self.subTest(position=position):
                response = self.move_to(lesson, self.trig, position)

                self.assertEqual(response.status_code, 200, response.content)
                lesson.refresh_from_db()
                self.assertEqual(lesson.position, expected)
                self.assertEqual(self.positions(self.trig), [0, 1, 2])

    def test_every_position_on_the_top_level_is_accepted(self):
        lesson = self.node("Синус суммы")

        # после первого переноса урок и сам стоит на верхнем уровне,
        # так что мест становится шесть
        for position in range(7):
            with self.subTest(position=position):
                response = self.move_to(lesson, None, position)

                self.assertEqual(response.status_code, 200, response.content)
                lesson.refresh_from_db()
                self.assertEqual(lesson.position, min(position, 5))
                self.assertEqual(self.positions(), [0, 1, 2, 3, 4, 5])

    def test_section_can_be_reordered_by_move_to(self):
        response = self.move_to(self.stereo, None, 0)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.structure()[:2], ["Стереометрия", "  Аксиомы"])
        self.assertEqual(self.positions(), [0, 1, 2, 3, 4])

    def test_positions_stay_dense_on_both_levels(self):
        self.move_to(self.node("Косинус суммы"), self.vectors, 1)

        self.assertEqual(self.positions(), [0, 1, 2, 3, 4])
        self.assertEqual(self.positions(self.trig), [0])
        self.assertEqual(self.positions(self.vectors), [0, 1, 2])
        self.assertEqual(
            [item.number for item in services.flatten_lessons(self.owner())],
            [1, 2, 3, 4, 5, 6, 7],
        )

    def test_last_lesson_can_leave_the_section_which_stays_empty(self):
        response = self.move_to(self.node("Аксиомы"), None, 0)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.structure()[0], "Аксиомы")
        # папка осталась на месте, просто пустая — сама она не удаляется
        self.assertEqual(self.structure()[-1], "Стереометрия")
        self.assertEqual(self.positions(self.stereo), [])
        self.assertTrue(PlanNode.objects.filter(pk=self.stereo.pk).exists())

    def test_moving_between_sections(self):
        response = self.move_to(self.node("Синус суммы"), self.vectors, 1)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.structure()[:5],
            [
                "Тригонометрия",
                "  Косинус суммы",
                "Векторы",
                "  Понятие вектора",
                "  Синус суммы",
            ],
        )
        self.assertEqual(self.numbers()["Синус суммы"], 3)

    def test_cannot_move_another_users_node(self):
        alien = self.add("Чужой", course=self.alien_class, teacher=self.stranger)

        response = self.move_to(alien, None, 0)

        self.assertEqual(response.status_code, 404)

    def test_parent_from_another_class_is_rejected(self):
        alien_section = self.add(
            "Чужая папка", is_section=True, course=self.alien_class, teacher=self.stranger
        )

        response = self.move_to(self.node("Повторение"), alien_section, 0)

        self.assertEqual(response.status_code, 400, response.content)


class ReindexTests(PlanTestCase):
    def test_reindex_closes_gaps(self):
        for position in (0, 5, 9):
            self.add(f"Урок {position}", position=position)

        services.reindex(self.owner(), None)

        self.assertEqual(self.positions(), [0, 1, 2])
        self.assertEqual(
            [node.title for node in services.level(self.owner())],
            ["Урок 0", "Урок 5", "Урок 9"],
        )

    def test_reindex_touches_only_its_level(self):
        section = self.add("Папка", position=0, is_section=True)
        self.add("Внутри", parent=section, position=7)
        self.add("Снаружи", position=4)

        services.reindex(self.owner(), section)

        self.assertEqual(self.positions(section), [0])
        self.assertEqual(self.node("Снаружи").position, 4)
