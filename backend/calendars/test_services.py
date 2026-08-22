"""Тесты расчёта календаря. ORM здесь не нужен — только чистые функции."""

from datetime import date

from django.test import SimpleTestCase

from . import services
from .services import Period

# 2026-09-07 — понедельник, 2026-09-13 — воскресенье
WEEK_START = date(2026, 9, 7)
WEEK_END = date(2026, 9, 13)
# три полные недели, чтобы хватило места на длинные каникулы
THREE_WEEKS_END = date(2026, 9, 27)


def statuses(days):
    return [day.status for day in days]


def status_on(days, day):
    return next(item for item in days if item.date == day).status


class CalendarTestCase(SimpleTestCase):
    def assertCountedOnce(self, days):
        """
        Главный инвариант: у дня ровно один статус.

        Сумма учебных, праздничных, каникулярных и выходных обязана давать
        число календарных дней периода, сколько бы исключений ни наложилось
        друг на друга.
        """
        stats = services.build_stats(days)

        self.assertEqual(sum(stats["by_status"].values()), len(days))
        self.assertEqual(stats["calendar_days"], len(days))
        self.assertEqual(stats["total"], stats["by_status"][services.STATUS_STUDY])
        self.assertEqual(stats["total"], sum(row["count"] for row in stats["by_weekday"]))

        return stats


class BuildDaysTests(CalendarTestCase):
    def test_covers_both_bounds_inclusive(self):
        days = services.build_days(WEEK_START, WEEK_END)

        self.assertEqual(len(days), 7)
        self.assertEqual(days[0].date, WEEK_START)
        self.assertEqual(days[-1].date, WEEK_END)

    def test_single_day_year(self):
        days = services.build_days(WEEK_START, WEEK_START)

        self.assertEqual([day.date for day in days], [WEEK_START])

    def test_weekend_by_default_is_saturday_and_sunday(self):
        days = services.build_days(WEEK_START, WEEK_END)

        self.assertEqual(
            statuses(days),
            [services.STATUS_STUDY] * 5 + [services.STATUS_WEEKEND] * 2,
        )

    def test_saturday_can_be_a_study_day(self):
        """В некоторых школах выходной только воскресенье."""
        days = services.build_days(WEEK_START, WEEK_END, weekend_days=[services.SUNDAY])

        self.assertEqual(
            statuses(days),
            [services.STATUS_STUDY] * 6 + [services.STATUS_WEEKEND],
        )

    def test_holiday_takes_the_day_out_of_study(self):
        holiday = Period(date(2026, 9, 9), date(2026, 9, 9), services.KIND_HOLIDAY, "День города")

        days = services.build_days(WEEK_START, WEEK_END, periods=[holiday])

        wednesday = days[2]
        self.assertEqual(wednesday.status, services.STATUS_HOLIDAY)
        self.assertEqual(wednesday.title, "День города")
        self.assertEqual(statuses(days).count(services.STATUS_STUDY), 4)

    def test_vacation_covers_the_whole_range(self):
        vacation = Period(date(2026, 9, 8), date(2026, 9, 10), services.KIND_VACATION, "Каникулы")

        days = services.build_days(WEEK_START, WEEK_END, periods=[vacation])

        self.assertEqual(
            statuses(days)[:4],
            [services.STATUS_STUDY] + [services.STATUS_VACATION] * 3,
        )

    def test_workday_makes_a_weekend_a_study_day(self):
        """Перенос: суббота 12-го отрабатывается за другой день."""
        transfer = Period(date(2026, 9, 12), date(2026, 9, 12), services.KIND_WORKDAY, "Перенос")

        days = services.build_days(WEEK_START, WEEK_END, periods=[transfer])

        saturday = days[5]
        self.assertEqual(saturday.status, services.STATUS_STUDY)
        self.assertEqual(saturday.title, "Перенос")
        self.assertEqual(days[6].status, services.STATUS_WEEKEND)

    def test_workday_beats_holiday_and_vacation_on_the_same_date(self):
        day = date(2026, 9, 9)
        periods = [
            Period(date(2026, 9, 7), date(2026, 9, 11), services.KIND_VACATION, "Каникулы"),
            Period(day, day, services.KIND_HOLIDAY, "Праздник"),
            Period(day, day, services.KIND_WORKDAY, "Перенос"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(days[2].status, services.STATUS_STUDY)

    def test_holiday_beats_vacation_on_the_same_date(self):
        day = date(2026, 9, 9)
        periods = [
            Period(date(2026, 9, 7), date(2026, 9, 11), services.KIND_VACATION, "Каникулы"),
            Period(day, day, services.KIND_HOLIDAY, "Праздник"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(days[2].status, services.STATUS_HOLIDAY)
        self.assertEqual(days[2].title, "Праздник")

    def test_exception_outside_the_year_is_ignored(self):
        past = Period(date(2026, 8, 1), date(2026, 8, 31), services.KIND_VACATION, "Лето")

        days = services.build_days(WEEK_START, WEEK_END, periods=[past])

        self.assertNotIn(services.STATUS_VACATION, statuses(days))

    def test_exception_is_clipped_by_the_year_bounds(self):
        """Каникулы, начавшиеся до года, красят только дни внутри него."""
        vacation = Period(date(2026, 9, 1), date(2026, 9, 8), services.KIND_VACATION, "Каникулы")

        days = services.build_days(WEEK_START, WEEK_END, periods=[vacation])

        self.assertEqual(days[0].date, WEEK_START)
        self.assertEqual(statuses(days).count(services.STATUS_VACATION), 2)

    def test_exception_id_is_carried_to_the_day(self):
        holiday = Period(date(2026, 9, 9), date(2026, 9, 9), services.KIND_HOLIDAY, "Праздник", id=42)

        days = services.build_days(WEEK_START, WEEK_END, periods=[holiday])

        self.assertEqual(days[2].exception_id, 42)
        self.assertIsNone(days[0].exception_id)


class OverlapTests(CalendarTestCase):
    """Наложения исключений друг на друга и на выходные."""

    def test_holiday_inside_vacation_is_counted_as_holiday_only(self):
        periods = [
            Period(date(2026, 9, 7), date(2026, 9, 11), services.KIND_VACATION, "Каникулы"),
            Period(date(2026, 9, 9), date(2026, 9, 9), services.KIND_HOLIDAY, "Праздник"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(status_on(days, date(2026, 9, 9)), services.STATUS_HOLIDAY)
        stats = self.assertCountedOnce(days)
        self.assertEqual(stats["by_status"][services.STATUS_HOLIDAY], 1)
        self.assertEqual(stats["by_status"][services.STATUS_VACATION], 4)
        self.assertEqual(stats["by_status"][services.STATUS_STUDY], 0)

    def test_holiday_on_a_weekend_stays_a_weekend(self):
        """Праздник в субботу не отнимает урок — считаем его выходным."""
        holiday = Period(date(2026, 9, 12), date(2026, 9, 12), services.KIND_HOLIDAY, "Праздник")

        days = services.build_days(WEEK_START, WEEK_END, periods=[holiday])

        saturday = days[5]
        self.assertEqual(saturday.status, services.STATUS_WEEKEND)
        # пометка пользователя не теряется: название остаётся на дне
        self.assertEqual(saturday.title, "Праздник")
        stats = self.assertCountedOnce(days)
        self.assertEqual(stats["by_status"][services.STATUS_HOLIDAY], 0)
        self.assertEqual(stats["by_status"][services.STATUS_WEEKEND], 2)
        self.assertEqual(stats["total"], 5)

    def test_holiday_overlapping_the_edge_of_vacation(self):
        """Праздник заходит краем в каникулы: спорные дни достаются празднику."""
        periods = [
            Period(date(2026, 9, 9), date(2026, 9, 13), services.KIND_VACATION, "Каникулы"),
            Period(date(2026, 9, 7), date(2026, 9, 9), services.KIND_HOLIDAY, "Праздник"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(
            statuses(days),
            [services.STATUS_HOLIDAY] * 3
            + [services.STATUS_VACATION] * 2
            + [services.STATUS_WEEKEND] * 2,
        )
        self.assertCountedOnce(days)

    def test_vacation_starting_and_ending_on_a_weekend(self):
        """Выходные по краям каникул остаются выходными, потерь на них нет."""
        vacation = Period(date(2026, 9, 12), date(2026, 9, 20), services.KIND_VACATION, "Каникулы")

        days = services.build_days(WEEK_START, THREE_WEEKS_END, periods=[vacation])

        self.assertEqual(status_on(days, date(2026, 9, 12)), services.STATUS_WEEKEND)
        self.assertEqual(status_on(days, date(2026, 9, 14)), services.STATUS_VACATION)
        self.assertEqual(status_on(days, date(2026, 9, 20)), services.STATUS_WEEKEND)
        stats = self.assertCountedOnce(days)
        # девять дней каникул, но уроков теряется только пять
        self.assertEqual(stats["by_status"][services.STATUS_VACATION], 5)

    def test_workday_wins_over_holiday(self):
        day = date(2026, 9, 9)
        periods = [
            Period(day, day, services.KIND_HOLIDAY, "Праздник"),
            Period(day, day, services.KIND_WORKDAY, "Отработка"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(status_on(days, day), services.STATUS_STUDY)
        self.assertEqual(days[2].title, "Отработка")
        self.assertCountedOnce(days)

    def test_workday_wins_over_vacation_even_on_a_weekend(self):
        """Отработка в выходной посреди каникул — самый крайний случай."""
        periods = [
            Period(date(2026, 9, 7), date(2026, 9, 13), services.KIND_VACATION, "Каникулы"),
            Period(date(2026, 9, 12), date(2026, 9, 12), services.KIND_WORKDAY, "Отработка"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(status_on(days, date(2026, 9, 12)), services.STATUS_STUDY)
        stats = self.assertCountedOnce(days)
        self.assertEqual(stats["total"], 1)

    def test_three_kinds_on_one_day(self):
        day = date(2026, 9, 9)
        periods = [
            Period(day, day, services.KIND_VACATION, "Каникулы"),
            Period(day, day, services.KIND_HOLIDAY, "Праздник"),
            Period(day, day, services.KIND_WORKDAY, "Отработка"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(status_on(days, day), services.STATUS_STUDY)
        stats = self.assertCountedOnce(days)
        self.assertEqual(stats["by_status"][services.STATUS_HOLIDAY], 0)
        self.assertEqual(stats["by_status"][services.STATUS_VACATION], 0)

    def test_two_kinds_on_one_day_without_workday(self):
        day = date(2026, 9, 9)
        periods = [
            Period(day, day, services.KIND_VACATION, "Каникулы"),
            Period(day, day, services.KIND_HOLIDAY, "Праздник"),
        ]

        days = services.build_days(WEEK_START, WEEK_END, periods=periods)

        self.assertEqual(status_on(days, day), services.STATUS_HOLIDAY)
        self.assertCountedOnce(days)

    def test_exception_crossing_the_start_of_the_year(self):
        vacation = Period(date(2026, 8, 25), date(2026, 9, 8), services.KIND_VACATION, "Летние")

        days = services.build_days(WEEK_START, WEEK_END, periods=[vacation])

        self.assertEqual(days[0].date, WEEK_START)
        stats = self.assertCountedOnce(days)
        self.assertEqual(stats["by_status"][services.STATUS_VACATION], 2)

    def test_exception_crossing_the_end_of_the_year(self):
        vacation = Period(date(2026, 9, 11), date(2026, 10, 5), services.KIND_VACATION, "Летние")

        days = services.build_days(WEEK_START, WEEK_END, periods=[vacation])

        self.assertEqual(days[-1].date, WEEK_END)
        stats = self.assertCountedOnce(days)
        # из отрезка в календарь попали пятница и два выходных
        self.assertEqual(stats["by_status"][services.STATUS_VACATION], 1)
        self.assertEqual(stats["by_status"][services.STATUS_WEEKEND], 2)

    def test_everything_at_once_still_adds_up(self):
        periods = [
            Period(date(2026, 9, 1), date(2026, 9, 8), services.KIND_VACATION, "Хвост лета"),
            Period(date(2026, 9, 14), date(2026, 9, 20), services.KIND_VACATION, "Осенние"),
            Period(date(2026, 9, 16), date(2026, 9, 16), services.KIND_HOLIDAY, "Праздник"),
            Period(date(2026, 9, 19), date(2026, 9, 19), services.KIND_HOLIDAY, "Ещё праздник"),
            Period(date(2026, 9, 19), date(2026, 9, 19), services.KIND_WORKDAY, "Отработка"),
            Period(date(2026, 9, 26), date(2026, 10, 4), services.KIND_VACATION, "Хвост года"),
        ]

        days = services.build_days(WEEK_START, THREE_WEEKS_END, periods=periods)

        self.assertEqual(len(days), 21)
        self.assertCountedOnce(days)


class StatsTests(CalendarTestCase):
    def test_counts_every_weekday_of_three_full_weeks(self):
        days = services.build_days(WEEK_START, date(2026, 9, 27))

        stats = services.build_stats(days)

        self.assertEqual(stats["total"], 15)
        counts = {row["weekday"]: row["count"] for row in stats["by_weekday"]}
        self.assertEqual(counts[services.MONDAY], 3)
        self.assertEqual(counts[services.FRIDAY], 3)
        self.assertEqual(counts[services.SATURDAY], 0)
        self.assertEqual(counts[services.SUNDAY], 0)

    def test_all_seven_weekdays_are_present_in_the_report(self):
        stats = services.build_stats(services.build_days(WEEK_START, WEEK_END))

        self.assertEqual([row["weekday"] for row in stats["by_weekday"]], list(range(7)))

    def test_holidays_are_subtracted_from_their_weekday(self):
        """Ради этого счётчик и нужен: праздники бьют по одному дню недели."""
        mondays_off = [
            Period(day, day, services.KIND_HOLIDAY, "Праздник")
            for day in (date(2026, 9, 7), date(2026, 9, 14))
        ]

        stats = services.build_stats(
            services.build_days(WEEK_START, date(2026, 9, 27), periods=mondays_off)
        )

        counts = {row["weekday"]: row["count"] for row in stats["by_weekday"]}
        self.assertEqual(counts[services.MONDAY], 1)
        self.assertEqual(counts[services.TUESDAY], 3)
        self.assertEqual(stats["total"], 13)

    def test_transferred_workday_is_counted_on_its_own_weekday(self):
        transfer = Period(date(2026, 9, 12), date(2026, 9, 12), services.KIND_WORKDAY, "Перенос")

        stats = services.build_stats(
            services.build_days(WEEK_START, WEEK_END, periods=[transfer])
        )

        counts = {row["weekday"]: row["count"] for row in stats["by_weekday"]}
        self.assertEqual(counts[services.SATURDAY], 1)
        self.assertEqual(stats["total"], 6)

    def test_total_equals_number_of_study_days(self):
        days = services.build_days(WEEK_START, date(2027, 5, 31))

        self.assertEqual(services.build_stats(days)["total"], len(services.study_days(days)))

    def test_statuses_add_up_to_the_calendar_length_without_exceptions(self):
        days = services.build_days(WEEK_START, date(2027, 5, 31))

        stats = self.assertCountedOnce(days)
        self.assertEqual(stats["calendar_days"], 267)

    def test_holiday_and_vacation_days_are_always_lost_study_days(self):
        """
        Свойство выбранного приоритета: выходной сильнее праздника и каникул,
        поэтому потери уроков — это ровно holiday + vacation.
        """
        periods = [
            Period(date(2026, 9, 12), date(2026, 9, 21), services.KIND_VACATION, "Каникулы"),
            Period(date(2026, 9, 26), date(2026, 9, 26), services.KIND_HOLIDAY, "Праздник"),
            Period(date(2026, 9, 23), date(2026, 9, 23), services.KIND_HOLIDAY, "Ещё праздник"),
        ]
        days = services.build_days(WEEK_START, THREE_WEEKS_END, periods=periods)

        lost = [day for day in days if day.status in (services.STATUS_HOLIDAY, services.STATUS_VACATION)]

        self.assertTrue(lost)
        for day in lost:
            self.assertNotIn(day.weekday, services.DEFAULT_WEEKEND_DAYS)

        clean = services.build_days(WEEK_START, THREE_WEEKS_END)
        stats = services.build_stats(days)
        self.assertEqual(
            services.build_stats(clean)["total"] - stats["total"], len(lost)
        )


class WithinTests(SimpleTestCase):
    def setUp(self):
        self.start, self.end = date(2026, 9, 1), date(2027, 5, 31)

    def test_period_on_the_bounds_is_inside(self):
        period = Period(self.start, self.end, services.KIND_VACATION)

        self.assertTrue(services.is_within(period, self.start, self.end))

    def test_period_starting_before_the_year(self):
        period = Period(date(2026, 8, 31), date(2026, 9, 2), services.KIND_VACATION)

        self.assertFalse(services.is_within(period, self.start, self.end))

    def test_period_ending_after_the_year(self):
        period = Period(date(2027, 5, 30), date(2027, 6, 1), services.KIND_VACATION)

        self.assertFalse(services.is_within(period, self.start, self.end))


class ConflictTests(SimpleTestCase):
    def setUp(self):
        self.vacation = Period(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Осенние", id=1
        )

    def test_overlapping_periods_of_the_same_kind_conflict(self):
        other = Period(date(2026, 11, 3), date(2026, 11, 8), services.KIND_VACATION)

        self.assertEqual(services.find_conflicts(other, [self.vacation]), [self.vacation])

    def test_nested_period_of_the_same_kind_conflicts(self):
        other = Period(date(2026, 10, 28), date(2026, 10, 29), services.KIND_VACATION)

        self.assertTrue(services.find_conflicts(other, [self.vacation]))

    def test_adjacent_periods_do_not_conflict(self):
        other = Period(date(2026, 11, 4), date(2026, 11, 8), services.KIND_VACATION)

        self.assertEqual(services.find_conflicts(other, [self.vacation]), [])

    def test_different_kinds_may_overlap(self):
        """Перенос внутри каникул — нормальная разметка."""
        transfer = Period(date(2026, 10, 28), date(2026, 10, 28), services.KIND_WORKDAY)

        self.assertEqual(services.find_conflicts(transfer, [self.vacation]), [])

    def test_period_does_not_conflict_with_itself(self):
        edited = Period(
            date(2026, 10, 26), date(2026, 11, 5), services.KIND_VACATION, "Осенние", id=1
        )

        self.assertEqual(services.find_conflicts(edited, [self.vacation]), [])

    def test_two_unsaved_periods_still_conflict(self):
        """У новых исключений id пустой у обоих — это не повод считать их одним."""
        first = Period(date(2026, 11, 2), date(2026, 11, 2), services.KIND_HOLIDAY)
        second = Period(date(2026, 11, 2), date(2026, 11, 2), services.KIND_HOLIDAY)

        self.assertEqual(services.find_conflicts(first, [second]), [second])
