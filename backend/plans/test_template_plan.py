"""
План на полке правится тем же экраном, что и боевой.

Ради этого у строки плана и завёлся второй владелец. Здесь проверяется не
модель — её стережёт ограничение базы и `config/test_invariants.py`, — а то,
ради чего всё затевалось: обычная ручка плана принимает `?template=` и ведёт
себя ровно так же, как с курсом, включая отмену.

Что у шаблона **не** должно появиться, проверяется тут же и по той же
причине: календаря у полки нет, и «проведён ли урок» там не вопрос.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_template, sign_in

from .models import PlanNode


class TemplatePlanTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # пустой намеренно: дерево набирается через ту же ручку, что и у
        # курса, — иначе тест проверял бы фикстуру, а не ручку
        self.template = make_template(self.school, self.user, rows=())

    def tree(self, template=None):
        return self.client.get(
            reverse("plannode-list"), {"template": (template or self.template).pk}
        )

    def add(self, title, *, is_section=False, parent=None, template=None):
        return self.client.post(
            reverse("plannode-list"),
            {
                "template": (template or self.template).pk,
                "title": title,
                "is_section": is_section,
                **({"parent": parent} if parent else {}),
            },
            format="json",
        )


class TheShelfIsEditedByTheSamePlanEndpointTests(TemplatePlanTestCase):
    def test_an_author_builds_a_tree_in_their_template(self):
        section = self.add("Тригонометрия", is_section=True)
        self.assertEqual(section.status_code, 201, section.content)

        lesson = self.add("Синус суммы", parent=section.json()["id"])
        self.assertEqual(lesson.status_code, 201, lesson.content)

        data = self.tree().json()
        self.assertEqual([row["title"] for row in data["nodes"]], ["Тригонометрия"])
        self.assertEqual(
            [row["title"] for row in data["nodes"][0]["children"]], ["Синус суммы"]
        )
        self.assertEqual(data["counts"], {"lessons": 1, "sections": 1})

    def test_the_numbering_is_the_same_numbering(self):
        """
        Сквозной номер у полки считается тем же обходом, что у курса.

        Своего расчёта тут нет и быть не должно: номер урока — свойство
        дерева, а не календаря, и второй ответ на него разошёлся бы с первым
        ровно в тот день, когда шаблон возьмут в курс.
        """
        self.add("Повторение")
        section = self.add("Векторы", is_section=True)
        self.add("Понятие вектора", parent=section.json()["id"])

        data = self.tree().json()
        numbers = [data["nodes"][0]["number"], data["nodes"][1]["children"][0]["number"]]

        self.assertEqual(numbers, [1, 2])

    def test_a_row_on_the_shelf_is_never_taught(self):
        """
        У полки нет календаря, и «проведено» там не вопрос.

        Проверяется не пустота ради пустоты: на этом признаке держится
        ручка перетаскивания и половина запретов очереди записей. Ответь
        сервер здесь `null` вместо `false` — таблица спрятала бы ручки у
        всех строк шаблона, и выглядело бы это поломкой.
        """
        self.add("Синус суммы")

        row = self.tree().json()["nodes"][0]

        self.assertIs(row["taught"], False)


class OnlyTheAuthorEditsWhatIsOnTheShelfTests(TemplatePlanTestCase):
    def test_a_colleague_does_not_find_the_tree_of_a_draft(self):
        """
        Чужой черновик отсутствует, а не «запрещён».

        То же правило, что у самой полки: про черновик коллеги знать
        незачем вовсе, и 404 тут честнее 403 — иначе отказ сам сообщает, что
        такой шаблон есть.
        """
        draft = make_template(self.school, self.user, published=False,
                              title="Черновик")
        sign_in(self.client, self.colleague)

        self.assertEqual(self.tree(draft).status_code, 404)

    def test_a_colleague_may_not_write_into_a_published_template(self):
        """
        Опубликованный шаблон читают все, а правит автор.

        Это и есть разница между полкой и курсом: курс школы чинит
        администратор, а чужой план на полке — ничей, кроме автора. Коллега
        видит шаблон в библиотеке, но его дерево ему не ручка.
        """
        sign_in(self.client, self.colleague)

        response = self.add("Чужая строка")

        self.assertIn(response.status_code, (400, 404), response.content)
        self.assertFalse(PlanNode.objects.filter(title="Чужая строка").exists())


class UndoWorksOnTheShelfTests(TemplatePlanTestCase):
    def test_a_row_deleted_by_mistake_comes_back(self):
        """
        Ошиблись с удалением — нажали отмену, и строка вернулась.

        Ради этого журнал и получил владельца. Строка при этом воскресает
        **со своим номером**: за ней стоят вложения и ссылки, и новая строка
        с новым номером — это не она.
        """
        created = self.add("Синус суммы").json()["id"]

        self.assertEqual(
            self.client.delete(reverse("plannode-detail", args=[created])).status_code,
            204,
        )
        self.assertFalse(PlanNode.objects.filter(pk=created).exists())

        undo = self.client.post(
            f"{reverse('plannode-undo')}?template={self.template.pk}",
            {},
            format="json",
        )

        self.assertEqual(undo.status_code, 200, undo.content)
        self.assertTrue(PlanNode.objects.filter(pk=created).exists())

    def test_the_journal_of_the_shelf_is_not_the_journal_of_a_course(self):
        """
        Снимки считаются по владельцу, и это не педантизм.

        Граница у журнала одна на двадцать шагов. Считай он их вместе, правка
        шаблона вытесняла бы отмену в курсе — то есть кнопка «отменить» в
        курсе молча переставала бы работать после работы на полке.
        """
        self.add("Синус суммы")

        history = self.client.get(
            reverse("plannode-plan-history"), {"template": self.template.pk}
        )

        self.assertEqual(history.status_code, 200, history.content)
        self.assertTrue(history.json()["steps"])
        self.assertTrue(
            all(step["action"] == "create" for step in history.json()["steps"])
        )
