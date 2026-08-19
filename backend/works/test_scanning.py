"""
Разбор пачки сканов: чья страница и что на ней.

Главное здесь то же, что и во всей бумажной подсистеме: **чужая работа не
должна достаться однокласснику**. Поэтому проверяется не «раскладка обычно
работает», а то, как она ведёт себя, когда уверенности нет: одинаковые имена,
пустое поле, порядок страниц вперемешку. Всё сомнительное обязано доехать до
человека, а не разложиться молча.

Группировка и слияние — чистые функции, и тестируются без базы: им всё равно,
откуда взялись прочитанные строки.
"""

from django.test import SimpleTestCase

from .scanning import CELLS, Page, Person, group, merge_marks, troubles


def page(index, first="", surname="", marks=None):
    cells = [None] * CELLS
    for question, value in (marks or {}).items():
        cells[question] = value
    return Page(index=index, first=first, surname=surname, cells=cells)


ROSTER = [
    Person(id=1, first="Shahar", last="Jerbi"),
    Person(id=2, first="Fil", last="Burmov"),
    Person(id=3, first="Peter", last="Tibora"),
]


class GroupingTests(SimpleTestCase):
    def test_a_clear_name_takes_its_page(self):
        assigned, doubts = group([page(0, "Shahar", "Jerbi")], ROSTER)

        self.assertEqual(assigned, {0: 1})
        self.assertEqual(doubts, [])

    def test_a_misspelt_name_still_matches(self):
        """Почерк читается с ошибками — на то и нечёткое сравнение."""
        assigned, _ = group([page(0, "Shahaar", "Jerbi")], ROSTER)

        self.assertEqual(assigned, {0: 1})

    def test_a_second_page_without_a_name_joins_by_coverage(self):
        """Вторая страница безымянна, но её задачи у хозяина ещё не заняты."""
        pages = [
            page(0, "Fil", "Burmov", {0: 1, 1: 2}),
            page(1, marks={4: 3, 5: 1}),
        ]
        assigned, doubts = group(pages, ROSTER)

        self.assertEqual(assigned, {0: 2, 1: 2})
        self.assertEqual(doubts, [])

    def test_the_order_of_pages_does_not_matter(self):
        """Листы сдают как попало: безымянная страница может идти первой."""
        pages = [
            page(0, marks={4: 3}),
            page(1, "Fil", "Burmov", {0: 1}),
        ]
        assigned, _ = group(pages, ROSTER)

        self.assertEqual(assigned, {0: 2, 1: 2})

    def test_an_overlapping_page_is_not_guessed(self):
        """Те же задачи, что уже закрыты, — значит это чужая страница."""
        pages = [
            page(0, "Fil", "Burmov", {0: 1, 1: 2}),
            page(1, marks={0: 3}),
        ]
        assigned, doubts = group(pages, ROSTER)

        self.assertNotIn(1, assigned)
        self.assertEqual([index for index, _ in doubts], [1])

    def test_an_empty_page_goes_to_a_human(self):
        """Ни имени, ни баллов: подходит ко всем, а значит ни к кому."""
        pages = [page(0, "Fil", "Burmov", {0: 1}), page(1)]
        _, doubts = group(pages, ROSTER)

        self.assertEqual([index for index, _ in doubts], [1])

    def test_a_human_decision_is_not_reconsidered(self):
        """Сказал человек — раскладка молчит, даже если имя читается иначе."""
        decided = page(0, "Shahar", "Jerbi")
        decided.student_id = 3
        decided.decided_by_human = True

        assigned, doubts = group([decided], ROSTER)

        self.assertEqual(assigned, {0: 3})
        self.assertEqual(doubts, [])

    def test_the_models_opinion_leads_the_candidates(self):
        """Мнение модели идёт первым — но остаётся предложением, а не решением."""
        one = page(0, "Shalene", "Dorah")
        one.guess = "Shahar Jerbi"

        assigned, doubts = group([one], ROSTER)

        self.assertEqual(assigned, {})
        self.assertEqual(doubts[0][1][0], 1)

    def test_an_opinion_about_a_stranger_is_dropped(self):
        """Назвала того, кого в курсе нет, — мнение не считается вовсе."""
        one = page(0, "Anna", "Kowalski")
        one.guess = "Somebody Else"

        _, doubts = group([one], ROSTER)

        self.assertNotEqual(doubts[0][1][0], None)
        self.assertTrue(all(isinstance(x, int) for x in doubts[0][1]))

    def test_an_unknown_name_is_a_doubt_with_candidates(self):
        """Имени нет в курсе — предлагаем ближайших, но не выбираем сами."""
        _, doubts = group([page(0, "Anna", "Kowalski")], ROSTER)

        self.assertEqual(len(doubts), 1)
        index, candidates = doubts[0]
        self.assertEqual(index, 0)
        self.assertTrue(candidates)


class MergeTests(SimpleTestCase):
    def test_marks_from_several_pages_add_up(self):
        marks, conflicts = merge_marks(
            [page(0, marks={0: 1, 1: 2}), page(1, marks={2: 3})]
        )

        self.assertEqual(marks, {0: 1, 1: 2, 2: 3})
        self.assertEqual(conflicts, [])

    def test_the_same_question_twice_is_a_conflict(self):
        """Молча выбрать одно из двух нельзя — это вопрос к человеку."""
        marks, conflicts = merge_marks(
            [page(0, marks={0: 1}), page(1, marks={0: 3})]
        )

        self.assertEqual(conflicts, ["Q1"])


class TroubleTests(SimpleTestCase):
    def test_a_mark_above_the_maximum_is_trouble(self):
        self.assertIn("mark_too_big", troubles(page(0, "Fil", "Burmov", {0: 7}), 2, 3, 15))

    def test_a_sum_that_does_not_add_up_is_trouble(self):
        one = page(0, "Fil", "Burmov", {0: 1, 1: 2})
        one.cells[15] = 9

        self.assertIn("sum_mismatch", troubles(one, 2, 3, 15))

    def test_an_empty_sum_is_not_trouble(self):
        """Сумму за страницу ставить необязательно: учитель мог полениться."""
        one = page(0, "Fil", "Burmov", {0: 1, 1: 2})

        self.assertNotIn("sum_mismatch", troubles(one, 2, 3, 15))

    def test_a_mark_beyond_the_questions_is_trouble(self):
        """Задач пять, а балл стоит в десятой клетке — читали не то."""
        self.assertIn(
            "beyond_questions", troubles(page(0, "Fil", "Burmov", {9: 1}), 2, 3, 5)
        )

    def test_a_page_signed_with_a_first_name_only_is_flagged(self):
        """Половинное свидетельство: имена повторяются чаще фамилий."""
        self.assertIn(
            "first_name_only", troubles(page(0, "Misha", "", {0: 1}), 2, 3, 15)
        )

    def test_a_page_signed_with_a_surname_only_is_not_flagged(self):
        """Фамилия — свидетельство полноценное, лишний вопрос тут только шум."""
        self.assertNotIn(
            "first_name_only", troubles(page(0, "", "Burmov", {0: 1}), 2, 3, 15)
        )

    def test_a_page_without_an_owner_is_trouble(self):
        self.assertIn("no_owner", troubles(page(0), None, 3, 15))
