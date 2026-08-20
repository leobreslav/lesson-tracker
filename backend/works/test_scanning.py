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

from .scanning import (
    CELLS,
    Page,
    Person,
    arrange,
    group,
    merge_marks,
    split_by_conditions,
    troubles,
    vote,
)


def page(index, first="", surname="", marks=None, headerless=False):
    cells = [None] * CELLS
    for question, value in (marks or {}).items():
        cells[question] = value
    return Page(
        index=index,
        first=first,
        surname=surname,
        cells=cells,
        headerless=headerless,
    )


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


class PacketTests(SimpleTestCase):
    """
    Пакет — работа одного ученика: его листы и его условия.

    Условия раздают перед работой, и ряд листов без шапки значит «дальше
    следующий ученик». Свидетельство это надёжнее почерка: оно не зависит ни
    от чтения, ни от того, вписал ли ученик фамилию. Но его может не быть —
    короткая работа обходится без условий, — и обе ситуации обязаны работать.
    """

    def packet(self, *pages):
        return [page for page in pages]

    def test_conditions_cut_the_pile_into_packets(self):
        pages = [
            page(0, headerless=True),
            page(1, headerless=True),
            page(2, "Fil", "Burmov", {0: 1}),
            page(3, headerless=True),
            page(4, headerless=True),
            page(5, "Peter", "Tibora", {0: 3}),
        ]

        packets = arrange(pages, ROSTER)

        self.assertEqual(len(packets), 2)
        self.assertEqual([p.index for p in packets[0].conditions], [0, 1])
        self.assertEqual(packets[0].student_id, 2)
        self.assertEqual(packets[1].student_id, 3)

    def test_one_run_of_conditions_is_a_cover_page_not_a_boundary(self):
        """Один ряд на всю пачку ничего не делит — решаем по именам."""
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, "Peter", "Tibora", {0: 3}),
        ]

        self.assertIsNone(split_by_conditions(pages))

    def test_without_conditions_the_old_way_still_works(self):
        """Короткая работа: условий не раздавали, а пакеты всё равно есть."""
        pages = [
            page(0, "Fil", "Burmov", {0: 1}),
            page(1, marks={4: 3}),
            page(2, "Peter", "Tibora", {0: 3}),
        ]

        packets = arrange(pages, ROSTER)

        owners = {packet.student_id: [p.index for p in packet.pages] for packet in packets}
        self.assertEqual(owners[2], [0, 1])
        self.assertEqual(owners[3], [2])

    def test_a_neighbour_does_not_beat_coverage(self):
        """
        Сосед решает только там, где покрытие оставило выбор.

        У страницы 1 та же задача, что у Фила на странице 0, — значит лист не
        его, как бы близко он ни лежал. Соседство добавляет свидетельство, а не
        отменяет чужое.
        """
        pages = [
            page(0, "Fil", "Burmov", {0: 1}),
            page(1, marks={0: 3}),
            page(2, "Peter", "Tibora", {4: 2}),
        ]

        packets = arrange(pages, ROSTER)

        owner = next(
            packet.student_id
            for packet in packets
            if 1 in [p.index for p in packet.pages]
        )
        self.assertNotEqual(owner, 2)

    def test_a_misread_name_drowns_among_the_others(self):
        """Восемь листов — восемь голосов; одна ошибка чтения ничего не решает."""
        pages = [page(0, headerless=True), page(1, headerless=True)]
        pages += [page(2 + n, "Fil", "Burmov", {n: 1}) for n in range(6)]
        pages[4] = page(4, "Misha", "", {2: 1})  # один лист прочитан неверно
        pages += [page(8, headerless=True), page(9, headerless=True), page(10, "Peter", "Tibora")]

        packets = arrange(pages, ROSTER)

        self.assertEqual(packets[0].student_id, 2)
        self.assertIn(4, [p.index for p in packets[0].pages])

    def test_an_unreadable_packet_asks_once_not_eight_times(self):
        """Спросить «чей это» надо один раз на пакет, а не на каждый лист."""
        pages = [page(0, headerless=True), page(1, headerless=True)]
        pages += [page(2 + n, "Xyz", "Qwerty", {n: 1}) for n in range(4)]
        pages += [page(6, headerless=True), page(7, headerless=True), page(8, "Peter", "Tibora")]

        packets = arrange(pages, ROSTER)

        unresolved = [packet for packet in packets if packet.student_id is None]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(len(unresolved[0].pages), 4)
        self.assertTrue(unresolved[0].candidates)

    def test_a_human_decision_wins_for_the_whole_packet(self):
        decided = page(2, "Xyz", "Qwerty", {0: 1})
        decided.student_id = 3
        decided.decided_by_human = True
        pages = [
            page(0, headerless=True),
            page(1, headerless=True),
            decided,
            page(3, "Xyz", "Qwerty", {1: 2}),
            page(4, headerless=True),
            page(5, headerless=True),
            page(6, "Fil", "Burmov"),
        ]

        packets = arrange(pages, ROSTER)

        self.assertEqual(packets[0].student_id, 3)
        self.assertEqual([p.index for p in packets[0].pages], [2, 3])

    def test_conditions_travel_with_the_work(self):
        """В PDF ученика едут и условия: ответы без вопросов — половина документа."""
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, headerless=True),
            page(3, "Peter", "Tibora", {0: 1}),
        ]

        packets = arrange(pages, ROSTER)

        self.assertEqual([p.index for p in packets[0].all_pages], [0, 1])

    def test_two_packets_of_one_student_become_one(self):
        """Взял второй комплект бумаги — работа всё равно одна."""
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, headerless=True),
            page(3, "Fil", "Burmov", {4: 2}),
        ]

        packets = arrange(pages, ROSTER)

        self.assertEqual(len(packets), 1)
        self.assertEqual([p.index for p in packets[0].all_pages], [0, 1, 2, 3])

    def test_a_silent_packet_is_a_doubt(self):
        """Никто не подписался — решает человек, а не покрытие задач."""
        pages = [
            page(0, headerless=True),
            page(1, marks={0: 1}),
            page(2, headerless=True),
            page(3, "Fil", "Burmov", {0: 1}),
        ]

        packets = arrange(pages, ROSTER)

        self.assertIsNone(packets[0].student_id)
