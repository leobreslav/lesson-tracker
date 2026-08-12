"""Тесты раскладки копирования. ORM не нужен — только чистые функции."""

from datetime import date, timedelta

from django.test import SimpleTestCase

from . import services

# 2026-09-07 — понедельник
MONDAY = date(2026, 9, 7)


class CycleTests(SimpleTestCase):
    def test_week_source_gives_week_cycle(self):
        self.assertEqual(services.cycle_days(MONDAY, MONDAY + timedelta(days=6)), 7)

    def test_two_week_source_gives_two_week_cycle(self):
        self.assertEqual(services.cycle_days(MONDAY, MONDAY + timedelta(days=13)), 14)

    def test_single_day_source_still_repeats_weekly(self):
        self.assertEqual(services.cycle_days(MONDAY, MONDAY), 7)

    def test_incomplete_week_is_rounded_up(self):
        self.assertEqual(services.cycle_days(MONDAY, MONDAY + timedelta(days=7)), 14)

    def test_source_date_keeps_the_weekday(self):
        """Главное свойство цикла: понедельник цели смотрит в понедельник источника."""
        for shift in range(0, 400):
            target = MONDAY + timedelta(days=shift)
            source = services.source_date_for(target, MONDAY, 14)
            self.assertEqual(source.weekday(), target.weekday(), target)

    def test_target_before_the_source_maps_backwards(self):
        target = MONDAY - timedelta(days=7)

        self.assertEqual(services.source_date_for(target, MONDAY, 14), MONDAY + timedelta(days=7))


class PlanCopyTests(SimpleTestCase):
    def plan(self, source_numbers, target_start, target_end, study_dates, weeks=1):
        return services.plan_copy(
            source_start=MONDAY,
            source_end=MONDAY + timedelta(days=weeks * 7 - 1),
            target_start=target_start,
            target_end=target_end,
            source_numbers=source_numbers,
            study_dates=study_dates,
        )

    def test_week_is_repeated_on_matching_weekdays(self):
        source = {MONDAY: [1, 2], MONDAY + timedelta(days=2): [3]}
        target_start = MONDAY + timedelta(days=7)
        target_end = MONDAY + timedelta(days=20)
        study = set(services.iter_dates(target_start, target_end))

        plan, skipped = self.plan(source, target_start, target_end, study)

        self.assertEqual(skipped, 0)
        self.assertEqual(
            plan,
            [
                (target_start, 1),
                (target_start, 2),
                (target_start + timedelta(days=2), 3),
                (target_start + timedelta(days=7), 1),
                (target_start + timedelta(days=7), 2),
                (target_start + timedelta(days=9), 3),
            ],
        )

    def test_non_study_days_are_skipped_and_counted(self):
        source = {MONDAY: [1, 2]}
        target_start = MONDAY + timedelta(days=7)
        target_end = MONDAY + timedelta(days=20)
        # первый понедельник цели — неучебный
        study = set(services.iter_dates(target_start, target_end)) - {target_start}

        plan, skipped = self.plan(source, target_start, target_end, study)

        self.assertEqual(skipped, 2)
        self.assertEqual(plan, [(target_start + timedelta(days=7), 1), (target_start + timedelta(days=7), 2)])

    def test_two_week_source_alternates(self):
        """Двухнедельный цикл не должен схлопываться в одну неделю."""
        source = {MONDAY: [1], MONDAY + timedelta(days=7): [2]}
        target_start = MONDAY + timedelta(days=14)
        target_end = MONDAY + timedelta(days=41)  # четыре недели
        study = set(services.iter_dates(target_start, target_end))

        plan, _ = self.plan(source, target_start, target_end, study, weeks=2)

        self.assertEqual(
            plan,
            [
                (MONDAY + timedelta(days=14), 1),
                (MONDAY + timedelta(days=21), 2),
                (MONDAY + timedelta(days=28), 1),
                (MONDAY + timedelta(days=35), 2),
            ],
        )

    def test_days_outside_the_source_range_add_nothing(self):
        """Источник в полторы недели: хвост цикла пустой, а не повторяет начало."""
        source = {MONDAY: [1]}
        target_start = MONDAY + timedelta(days=14)
        target_end = MONDAY + timedelta(days=27)
        study = set(services.iter_dates(target_start, target_end))

        plan, skipped = self.plan(source, target_start, target_end, study, weeks=2)

        self.assertEqual(plan, [(MONDAY + timedelta(days=14), 1)])
        self.assertEqual(skipped, 0)

    def test_empty_source_produces_nothing(self):
        target_start = MONDAY + timedelta(days=7)
        target_end = MONDAY + timedelta(days=13)

        plan, skipped = self.plan({}, target_start, target_end, set())

        self.assertEqual((plan, skipped), ([], 0))
