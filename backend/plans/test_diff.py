"""
Построчное сравнение плана с эталоном.

Числа отвечали на «сильно ли разошлось», а спрашивают «что именно вы
поменяли». Сопоставление здесь точное — по `node_id`, — поэтому
переименование видно переименованием, а не «удалили и добавили».

Главная ловушка проверяется отдельно: вставка в начало не должна красить
весь план. Позиции для этого не сравниваются вовсе — общая часть считается
через LCS, как в текстовых diff'ах, только по числам.
"""

from django.test import SimpleTestCase

from .diff import common, plan_diff, summary
from .services import SnapshotRow


def row(node_id, title, *, section=False, content=""):
    return SnapshotRow(section, title, node_id, content)


def shape(changes):
    return [(change.node_id, change.state) for change in changes]


class CommonPartTests(SimpleTestCase):
    def test_the_common_part_survives_an_insertion(self):
        self.assertEqual(common([1, 2, 3], [9, 1, 2, 3]), [1, 2, 3])

    def test_a_moved_row_falls_out_of_the_common_part(self):
        self.assertEqual(common([1, 2, 3], [3, 1, 2]), [1, 2])


class PlanDiffTests(SimpleTestCase):
    def test_an_untouched_plan_shows_nothing(self):
        rows = [row(1, "Синус"), row(2, "Косинус")]

        self.assertEqual(shape(plan_diff(rows, rows)), [(1, "same"), (2, "same")])

    def test_an_added_row_is_added(self):
        before = [row(1, "Синус")]
        after = [row(1, "Синус"), row(2, "Тангенс")]

        self.assertEqual(shape(plan_diff(before, after)), [(1, "same"), (2, "added")])

    def test_a_deleted_row_stays_as_a_ghost_in_its_old_place(self):
        before = [row(1, "Синус"), row(2, "Косинус"), row(3, "Тангенс")]
        after = [row(1, "Синус"), row(3, "Тангенс")]

        self.assertEqual(
            shape(plan_diff(before, after)),
            [(1, "same"), (2, "removed"), (3, "same")],
        )

    def test_a_rename_is_a_rename_and_not_a_pair_of_edits(self):
        before = [row(1, "Синус")]
        after = [row(1, "Синус суммы")]

        [change] = plan_diff(before, after)

        self.assertEqual(change.state, "changed")
        self.assertEqual(change.was_title, "Синус")

    def test_changed_content_is_named_without_storing_the_content(self):
        before = [row(1, "Синус", content="aaa")]
        after = [row(1, "Синус", content="bbb")]

        [change] = plan_diff(before, after)

        self.assertEqual(change.state, "changed")
        self.assertTrue(change.content_changed)
        self.assertEqual(change.was_title, "")

    def test_an_old_snapshot_without_a_fingerprint_says_nothing_about_content(self):
        """Снимки, снятые до отпечатка, не должны врать про содержание."""
        before = [row(1, "Синус", content="")]
        after = [row(1, "Синус", content="bbb")]

        [change] = plan_diff(before, after)

        self.assertEqual(change.state, "same")
        self.assertFalse(change.content_changed)

    def test_inserting_at_the_top_does_not_paint_the_whole_plan(self):
        """Та самая ловушка: сравнение позиций в лоб покрасило бы всё."""
        before = [row(number, f"Урок {number}") for number in range(1, 21)]
        after = [row(99, "Новый")] + before

        changes = plan_diff(before, after)

        self.assertEqual(summary(changes), {
            "added": 1, "removed": 0, "moved": 0, "changed": 0, "same": 20,
        })

    def test_a_row_carried_across_the_plan_is_the_moved_one(self):
        before = [row(1, "А"), row(2, "Б"), row(3, "В")]
        after = [row(3, "В"), row(1, "А"), row(2, "Б")]

        self.assertEqual(
            shape(plan_diff(before, after)),
            [(3, "moved"), (1, "same"), (2, "same")],
        )

    def test_a_deleted_and_recreated_row_counts_as_both(self):
        """Честно: это две правки, а не одна — так же считает и сводка."""
        before = [row(1, "Синус")]
        after = [row(2, "Синус")]

        self.assertEqual(shape(plan_diff(before, after)), [(2, "added"), (1, "removed")])

    def test_a_split_theme_moves_nobody(self):
        """
        Разрез темы не двигает уроки в ленте — только добавляет заголовок.

        Ради этого сравнение и идёт по последовательности, а не по
        родителям: перегруппировка не должна выглядеть как перетряска.
        """
        before = [
            row(10, "Глава I", section=True),
            row(1, "Урок 1"),
            row(2, "Урок 2"),
            row(3, "Урок 3"),
        ]
        after = [
            row(10, "Глава I", section=True),
            row(1, "Урок 1"),
            row(11, "Глава II", section=True),
            row(2, "Урок 2"),
            row(3, "Урок 3"),
        ]

        self.assertEqual(
            shape(plan_diff(before, after)),
            [(10, "same"), (1, "same"), (11, "added"), (2, "same"), (3, "same")],
        )
