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
    classify,
    split_by_conditions,
    top_candidates,
    troubles,
    vote,
)


def page(index, first="", surname="", marks=None, headerless=False, ours=None):
    cells = [None] * CELLS
    for question, value in (marks or {}).items():
        cells[question] = value
    return Page(
        index=index,
        first=first,
        surname=surname,
        cells=cells,
        headerless=headerless,
        # прочитанная страница по определению наша: метку смотрят там же, где
        # выпрямляют шапку
        ours=(not headerless) if ours is None else ours,
    )


ROSTER = [
    Person(id=1, first="Shahar", last="Jerbi"),
    Person(id=2, first="Fil", last="Burmov"),
    Person(id=3, first="Peter", last="Tibora"),
]


class GroupingTests(SimpleTestCase):
    def test_a_clear_name_takes_its_page(self):
        assigned, doubts, _ = group([page(0, "Shahar", "Jerbi")], ROSTER)

        self.assertEqual(assigned, {0: 1})
        self.assertEqual(doubts, [])

    def test_a_misspelt_name_still_matches(self):
        """Почерк читается с ошибками — на то и нечёткое сравнение."""
        assigned, _, _ = group([page(0, "Shahaar", "Jerbi")], ROSTER)

        self.assertEqual(assigned, {0: 1})

    def test_a_second_page_without_a_name_joins_by_coverage(self):
        """Вторая страница безымянна, но её задачи у хозяина ещё не заняты."""
        pages = [
            page(0, "Fil", "Burmov", {0: 1, 1: 2}),
            page(1, marks={4: 3, 5: 1}),
        ]
        assigned, doubts, _ = group(pages, ROSTER)

        self.assertEqual(assigned, {0: 2, 1: 2})
        self.assertEqual(doubts, [])

    def test_the_order_of_pages_does_not_matter(self):
        """Листы сдают как попало: безымянная страница может идти первой."""
        pages = [
            page(0, marks={4: 3}),
            page(1, "Fil", "Burmov", {0: 1}),
        ]
        assigned, _, _ = group(pages, ROSTER)

        self.assertEqual(assigned, {0: 2, 1: 2})

    def test_an_overlapping_page_is_not_guessed(self):
        """Те же задачи, что уже закрыты, — значит это чужая страница."""
        pages = [
            page(0, "Fil", "Burmov", {0: 1, 1: 2}),
            page(1, marks={0: 3}),
        ]
        assigned, doubts, _ = group(pages, ROSTER)

        self.assertNotIn(1, assigned)
        self.assertEqual([index for index, _ in doubts], [1])

    def test_an_empty_page_goes_to_a_human(self):
        """Ни имени, ни баллов: подходит ко всем, а значит ни к кому."""
        pages = [page(0, "Fil", "Burmov", {0: 1}), page(1)]
        _, doubts, _ = group(pages, ROSTER)

        self.assertEqual([index for index, _ in doubts], [1])

    def test_a_human_decision_is_not_reconsidered(self):
        """Сказал человек — раскладка молчит, даже если имя читается иначе."""
        decided = page(0, "Shahar", "Jerbi")
        decided.student_id = 3
        decided.decided_by_human = True

        assigned, doubts, _ = group([decided], ROSTER)

        self.assertEqual(assigned, {0: 3})
        self.assertEqual(doubts, [])

    def test_the_models_opinion_leads_the_candidates(self):
        """Мнение модели идёт первым — но остаётся предложением, а не решением."""
        one = page(0, "Shalene", "Dorah")
        one.guess = "Shahar Jerbi"

        assigned, doubts, _ = group([one], ROSTER)

        self.assertEqual(assigned, {})
        self.assertEqual(doubts[0][1][0], 1)

    def test_an_opinion_about_a_stranger_is_dropped(self):
        """Назвала того, кого в курсе нет, — мнение не считается вовсе."""
        one = page(0, "Anna", "Kowalski")
        one.guess = "Somebody Else"

        _, doubts, _ = group([one], ROSTER)

        self.assertNotEqual(doubts[0][1][0], None)
        self.assertTrue(all(isinstance(x, int) for x in doubts[0][1]))

    def test_an_unknown_name_is_a_doubt_with_candidates(self):
        """Имени нет в курсе — предлагаем ближайших, но не выбираем сами."""
        _, doubts, _ = group([page(0, "Anna", "Kowalski")], ROSTER)

        self.assertEqual(len(doubts), 1)
        index, candidates = doubts[0]
        self.assertEqual(index, 0)
        self.assertTrue(candidates)


class CandidateTests(SimpleTestCase):
    """
    Кого экран предлагает по одной странице.

    Список кандидатов раньше жил только у пакета, а у пакета его нет всякий
    раз, когда пакет решился или собран постранично. Экран получал пустоту и
    показывал вместо неё первых по списку класса — то есть заведомо не тех,
    чьё имя на листе. Человек при этом видел «Read as: Миронова» и три кнопки
    с посторонними фамилиями, и правильного ответа среди них не было вовсе.
    """

    def test_a_page_offers_the_person_whose_name_is_on_it(self):
        best = top_candidates(page(0, "Shahar", "Jerbi"), ROSTER)

        self.assertEqual(best[0], 1)

    def test_a_misspelt_name_still_leads(self):
        """Ради этого кандидатов и показывают: точное совпадение решилось бы само."""
        best = top_candidates(page(0, "Shahar", "Jerbe"), ROSTER)

        self.assertEqual(best[0], 1)

    def test_three_are_offered_not_the_whole_class(self):
        self.assertEqual(len(top_candidates(page(0, "Sh", "J"), ROSTER)), 3)

    def test_an_unsigned_page_offers_nobody(self):
        """
        Пустая шапка не свидетельство. Предложить по ней тройку значит
        предложить случайных людей — а выбирать всё равно из полного списка.
        """
        self.assertEqual(top_candidates(page(0), ROSTER), [])

    def test_the_models_opinion_goes_to_the_top(self):
        """
        Мнение модели — свидетельство этого же листа, и в голосовании пакета
        оно учитывается так же. Расходиться эти места не должны.
        """
        one = page(0, "Shalene", "Dorah")
        one.guess = "Peter Tibora"

        self.assertEqual(top_candidates(one, ROSTER)[0], 3)

    def test_an_opinion_about_a_stranger_does_not_lead(self):
        """Модель могла назвать кого угодно; названное сверяется с составом."""
        one = page(0, "Shahar", "Jerbi")
        one.guess = "Someone Else"

        self.assertEqual(top_candidates(one, ROSTER)[0], 1)


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

        # номер клетки, а не готовая подпись: как вопрос зовётся, знает работа,
        # а сюда приезжают только страницы
        self.assertEqual(conflicts, [0])


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
        """Один ряд на всю пачку ничего не делит — это общие условия."""
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, "Peter", "Tibora", {0: 3}),
        ]

        self.assertIsNone(split_by_conditions(pages, classify(pages)))

    def test_a_trailing_run_does_not_cut_the_pile(self):
        """
        Ряд без шапки в самом конце пачки — это не граница: за ним нет работы.

        Стоило это целой разобранной пачки. Два последних листа не опознались
        как наш бланк (пустые обороты), попали в «условия» и дали второй ряд —
        а два ряда включают разрезку. Тридцать четыре листа стали двумя
        пакетами, и голосование, у которого один пакет — один ученик, отдало
        чужие листы одному человеку, а половину пачки не решило вовсе.
        """
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, "Peter", "Tibora", {1: 3}),
            page(3, headerless=True),
            page(4, headerless=True),
        ]

        self.assertIsNone(split_by_conditions(pages, classify(pages)))

    def test_a_trailing_run_after_a_real_boundary_still_leaves_it(self):
        """Хвост ничего не отменяет: настоящая граница как была, так и есть."""
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, headerless=True),
            page(3, "Peter", "Tibora", {0: 3}),
            page(4, headerless=True),
        ]

        packets = split_by_conditions(pages, classify(pages))

        self.assertIsNotNone(packets)
        # хвост заводит свой пакет из одних условий, и это не важно; важно, что
        # настоящая граница по-прежнему развела двух учеников по разным пакетам
        with_pages = [packet for packet in packets if packet.pages]
        self.assertEqual([[p.index for p in one.pages] for one in with_pages], [[1], [3]])

    def test_a_signed_page_leaves_a_foreign_packet(self):
        """
        Подпись сильнее группировки.

        Пакет — догадка о том, как листы лежат вместе; подпись — свидетельство
        о том, чей лист. На живой пачке пакет, собранный по ошибочной границе,
        отдал Варваре Мироновой страницу, подписанную «Кирилл Орлов»: её имя
        стояло на первом листе того же пакета, и голосование решило за всех.
        """
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, "Peter", "Tibora", {1: 3}),
            page(3, headerless=True),
            page(4, "Shahar", "Jerbi", {0: 2}),
            page(5, "Shahar", "Jerbi", {1: 2}),
        ]

        packets = arrange(pages, ROSTER)
        owner = {
            page.index: packet.student_id
            for packet in packets
            for page in packet.pages
        }

        self.assertEqual(owner[1], 2)
        self.assertEqual(owner[2], 3)

    def test_a_page_taken_out_says_so(self):
        """Переложили не молча: человек видит, что решение принято за него."""
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, "Peter", "Tibora", {1: 3}),
            page(3, headerless=True),
            page(4, "Shahar", "Jerbi", {0: 2}),
        ]

        packets = arrange(pages, ROSTER)
        moved = [index for packet in packets for index in packet.signed_apart]

        self.assertIn(2, moved)

    def test_an_unsigned_page_stays_where_the_packet_put_it(self):
        """
        Молчащий лист забирать не за что: у него нет своего свидетельства, и
        границы пакета — лучшее, что о нём известно.
        """
        pages = [
            page(0, headerless=True),
            page(1, "Fil", "Burmov", {0: 1}),
            page(2, marks={1: 3}),
            page(3, headerless=True),
            page(4, "Peter", "Tibora", {0: 2}),
        ]

        packets = arrange(pages, ROSTER)
        owner = {
            page.index: packet.student_id
            for packet in packets
            for page in packet.pages
        }

        self.assertEqual(owner[2], owner[1])

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


class GuessTests(SimpleTestCase):
    """
    Догадка законна, но она не выдаётся за прочитанное.

    Измерено на живой пачке: раскладка по свободным задачам и соседству
    ошиблась четыре раза из пятнадцати — и ошиблась молча. Запрещать её нельзя
    (иначе всякий неподписанный лист шёл бы к человеку), а молчать о ней —
    можно только один раз, до первой чужой контрольной у одноклассника.
    """

    def test_a_page_placed_without_its_own_name_is_marked(self):
        pages = [
            page(0, "Fil", "Burmov", {0: 1}),
            page(1, marks={4: 3}),
        ]

        _, _, by_fit = group(pages, ROSTER)

        self.assertEqual(by_fit, {1})

    def test_a_page_placed_by_its_own_name_is_not_marked(self):
        pages = [page(0, "Fil", "Burmov", {0: 1}), page(1, "Peter", "Tibora", {0: 3})]

        _, _, by_fit = group(pages, ROSTER)

        self.assertEqual(by_fit, set())

    def test_the_packet_remembers_which_pages_were_guessed(self):
        pages = [
            page(0, "Fil", "Burmov", {0: 1}),
            page(1, marks={4: 3}),
        ]

        packets = arrange(pages, ROSTER)

        self.assertEqual(packets[0].by_fit, [1])


class KindTests(SimpleTestCase):
    """
    Что это за страница: решение, условия или наш лист, который не прочитался.

    Отвечает на это метка в углу поля записи — единственный твёрдый факт в
    этой части: лист условий печатают из своих материалов, и метки на нём нет.
    Но её может не оказаться и на наших листах — печатали со старого бланка,
    принтер съел угол, — и тогда доверять ей нельзя вовсе.
    """

    def test_a_sheet_without_our_mark_is_conditions(self):
        pages = [
            page(0, headerless=True, ours=False),
            page(1, "Fil", "Burmov", {0: 1}),
        ]

        self.assertEqual(classify(pages)[0], "conditions")

    def test_our_sheet_that_did_not_read_is_not_conditions(self):
        """Смазанное фото нашего листа — потерянная работа, а не условие."""
        pages = [
            page(0, headerless=True, ours=True),
            page(1, "Fil", "Burmov", {0: 1}),
        ]

        self.assertEqual(classify(pages)[0], "unreadable")

    def test_without_the_mark_anywhere_the_signal_is_ignored(self):
        """
        Ни на одном листе метки нет — печатали со старого бланка.

        Доверять ей тут значит объявить условиями всю пачку, поэтому работает
        прежнее правило: прочиталась шапка или нет.
        """
        pages = [
            page(0, headerless=True, ours=False),
            page(1, "Fil", "Burmov", {0: 1}, ours=False),
        ]

        self.assertEqual(classify(pages)[1], "read")
        self.assertEqual(classify(pages)[0], "conditions")


class CommonConditionsTests(SimpleTestCase):
    """Условия отсканированы один раз, в начале пачки: они общие для всех."""

    def test_they_go_into_every_students_file(self):
        pages = [
            page(0, headerless=True, ours=False),
            page(1, headerless=True, ours=False),
            page(2, "Fil", "Burmov", {0: 1}),
            page(3, "Peter", "Tibora", {0: 3}),
        ]

        packets = arrange(pages, ROSTER)

        self.assertEqual(len(packets), 2)
        for packet in packets:
            self.assertEqual([p.index for p in packet.conditions], [0, 1])

    def test_they_do_not_cut_the_pile(self):
        """Один ряд — не граница: иначе пачка из пятнадцати работ станет двумя."""
        pages = [page(0, headerless=True, ours=False)]
        pages += [page(1 + n, f"Name{n}", "", {0: 1}) for n in range(3)]

        packets = arrange(pages, ROSTER)

        self.assertGreater(len(packets), 2)
