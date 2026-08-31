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

    def test_a_colleague_reads_the_tree_of_a_published_template(self):
        """
        «Читают все» — теперь про эту ручку, а не только про список полки.

        Абзац выше утверждал это давно, а ручка отвечала 404 всякому, кроме
        автора: выложенная запись была видна списком в окне библиотеки, но
        не открывалась. Наружу это выходило пустым экраном по присланной
        ссылке — то есть полка витрина, на которую нельзя посмотреть.

        Шире доступ от этого не стал ни на строку: читаемое — то же
        `visible_templates`, по которому полка и показывается, а чужой
        черновик остаётся отсутствующим (тест выше).
        """
        self.add("Тригонометрия", is_section=True)
        sign_in(self.client, self.colleague)

        answer = self.tree()

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(
            [row["title"] for row in answer.json()["nodes"]], ["Тригонометрия"]
        )

    def test_a_colleague_does_not_get_the_undo_journal(self):
        """
        Читать — да, отменять — нет, и журнал отмены идёт со второй стороной.

        Он отвечает на «что я могу вернуть», а вернуть читатель не может
        ничего: список снимков предложил бы ему кнопки, которых у него нет,
        и заодно показал бы все прошлые состояния чужой записи. Поэтому
        `plan_history` спрашивает владельца как пишущий, хотя сам не пишет.
        """
        self.add("Тригонометрия", is_section=True)
        sign_in(self.client, self.colleague)

        answer = self.client.get(
            reverse("plannode-plan-history"), {"template": self.template.pk}
        )

        self.assertEqual(answer.status_code, 404, answer.content)


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


class TheShelfExchangesFilesLikeACourseTests(TemplatePlanTestCase):
    """
    Обмен файлами на полке — тот же, что у курса, и это не удобство.

    План на полке пишут ровно так же, как план курса, и «набрать сорок
    уроков» одинаково не хочется в обоих. Ручки при этом были курсовые: на
    полке меню файлов не рисовали вовсе, потому что оно ответило бы отказом.
    Отказ шёл не от правила, а от того, что владельца никто не обобщил.

    Граница между сторонами при этом не стёрлась, а стала точнее: своё —
    и читают, и пишут; чужое — только читают. Выгрузка чужого этого не
    нарушает, а **заканчивает**: показать и не дать взять — не защита, а
    неудобство, потому что возьмут всё равно, только руками.
    """

    def export(self, kind="export", template=None):
        return self.client.get(
            reverse(f"plannode-{kind}"), {"template": (template or self.template).pk}
        )

    def test_an_author_takes_their_shelf_plan_as_a_file(self):
        self.add("Тригонометрия", is_section=True)

        for kind in ("export", "export-xlsx"):
            with self.subTest(kind=kind):
                answer = self.export(kind)
                self.assertEqual(answer.status_code, 200, answer.content)
                self.assertTrue(answer.content)

    def test_a_colleague_takes_a_published_shelf_plan_as_a_file(self):
        """
        Ровно то, ради чего чужую запись вообще открыли: её берут себе.

        Своей кнопки «взять в курс» у чужой заготовки нет — она живёт в окне
        «Из библиотеки», — а файл работает отовсюду и ложится обратно
        импортом, потому что формат один на всех.
        """
        self.add("Тригонометрия", is_section=True)
        sign_in(self.client, self.colleague)

        answer = self.export()

        self.assertEqual(answer.status_code, 200, answer.content)

    def test_a_colleague_does_not_export_someone_elses_draft(self):
        """Чужой черновик отсутствует и для выгрузки — тем же 404."""
        draft = make_template(self.school, self.user, published=False,
                              title="Черновик")
        sign_in(self.client, self.colleague)

        self.assertEqual(self.export(template=draft).status_code, 404)

    def test_an_author_imports_a_file_into_their_shelf_plan(self):
        """
        Импорт на полке — тот же, что у курса, включая режимы.

        Проверок про проведённые занятия и очередь записей он тут не зовёт,
        и это не пропуск: строка на полке не проведена никогда, а записей у
        неё нет, потому что нет занятий.
        """
        self.add("Старое", is_section=True)

        # владелец — в строке запроса, как и у курса: тело тут занято файлом
        answer = self.client.post(
            f"{reverse('plannode-import-rows')}?template={self.template.pk}",
            {
                "mode": "replace",
                "rows": [
                    ["", "Тригонометрия", "Синус суммы"],
                    ["", "Тригонометрия", "Косинус суммы"],
                ],
            },
            format="json",
        )

        self.assertEqual(answer.status_code, 200, answer.content)
        self.assertEqual(
            [row["title"] for row in self.tree().json()["nodes"]],
            ["Тригонометрия"],
        )

    def test_a_colleague_does_not_import_into_a_published_template(self):
        """Читают все, пишет автор — и у файла это то же правило."""
        sign_in(self.client, self.colleague)

        answer = self.client.post(
            f"{reverse('plannode-import-rows')}?template={self.template.pk}",
            {"mode": "append", "rows": [["", "Тема", "Чужая строка"]]},
            format="json",
        )

        self.assertIn(answer.status_code, (400, 404), answer.content)
        self.assertFalse(PlanNode.objects.filter(title="Чужая строка").exists())
