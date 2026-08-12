from collections import Counter
from datetime import date

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from . import services
from .models import DayException, SchoolYear

YEAR_START = date(2026, 9, 1)  # вторник
YEAR_END = date(2027, 5, 31)


class CalendarApiTestCase(SchoolTestMixin, APITestCase):
    """The calendar belongs to the school, so an admin is signed in here."""

    def setUp(self):
        super().setUp()
        # editing the calendar is an administrator's job; the access tests
        # sign in as somebody else on purpose
        self.sign_in(self.admin)
        self.year = SchoolYear.objects.create(
            school=self.school,
            name="2026/2027",
            start_date=YEAR_START,
            end_date=YEAR_END,
        )

    def make_exception(self, start, end, kind, title="", year=None):
        return DayException.objects.create(
            year=year or self.year,
            start_date=start,
            end_date=end,
            kind=kind,
            title=title,
        )

    def post_exception(self, start, end, kind, title="Исключение", year=None):
        return self.client.post(
            reverse("dayexception-list"),
            {
                "year": (year or self.year).pk,
                "start_date": start,
                "end_date": end,
                "kind": kind,
                "title": title,
            },
            format="json",
        )


class SchoolYearApiTests(CalendarApiTestCase):
    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("schoolyear-list")).status_code, 401)

    def test_create_puts_the_year_into_the_requesters_school(self):
        response = self.client.post(
            reverse("schoolyear-list"),
            {"name": "2027/2028", "start_date": "2027-09-01", "end_date": "2028-05-31"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        created = SchoolYear.objects.get(name="2027/2028")
        self.assertEqual(created.school, self.school)
        self.assertEqual(created.weekend_days, [services.SATURDAY, services.SUNDAY])

    def test_list_shows_only_own_years(self):
        SchoolYear.objects.create(
            school=self.alien_school, name="чужой", start_date=YEAR_START, end_date=YEAR_END
        )

        response = self.client.get(reverse("schoolyear-list"))

        self.assertEqual([item["name"] for item in response.json()], ["2026/2027"])

    def test_other_users_year_is_not_found(self):
        alien = SchoolYear.objects.create(
            school=self.alien_school, name="чужой", start_date=YEAR_START, end_date=YEAR_END
        )

        response = self.client.get(reverse("schoolyear-detail", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)

    def test_duplicate_name_in_the_same_school_is_rejected(self):
        response = self.client.post(
            reverse("schoolyear-list"),
            {"name": "2026/2027", "start_date": "2026-09-01", "end_date": "2027-05-31"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_same_name_in_another_school_is_allowed(self):
        self.sign_in(self.alien_admin)

        response = self.client.post(
            reverse("schoolyear-list"),
            {"name": "2026/2027", "start_date": "2026-09-01", "end_date": "2027-05-31"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_end_before_start_is_rejected(self):
        response = self.client.post(
            reverse("schoolyear-list"),
            {"name": "кривой", "start_date": "2027-09-01", "end_date": "2027-08-31"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "year_dates_reversed")

    def test_weekend_days_are_validated(self):
        response = self.client.patch(
            reverse("schoolyear-detail", args=[self.year.pk]),
            {"weekend_days": [7]},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_saturday_can_be_removed_from_weekend(self):
        response = self.client.patch(
            reverse("schoolyear-detail", args=[self.year.pk]),
            {"weekend_days": [services.SUNDAY]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.year.refresh_from_db()
        self.assertEqual(self.year.weekend_days, [services.SUNDAY])

    def test_shrinking_the_year_past_an_exception_is_rejected(self):
        self.make_exception(date(2027, 5, 10), date(2027, 5, 12), services.KIND_VACATION)

        response = self.client.patch(
            reverse("schoolyear-detail", args=[self.year.pk]),
            {"end_date": "2027-05-01"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_detail_includes_exceptions(self):
        self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY, "День единства"
        )

        response = self.client.get(reverse("schoolyear-detail", args=[self.year.pk]))

        self.assertEqual(len(response.json()["exceptions"]), 1)
        self.assertEqual(response.json()["exceptions"][0]["title"], "День единства")

    def test_delete_removes_exceptions_too(self):
        self.make_exception(date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY)

        response = self.client.delete(reverse("schoolyear-detail", args=[self.year.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(DayException.objects.exists())


class DayExceptionApiTests(CalendarApiTestCase):
    def test_create_inside_the_year(self):
        response = self.post_exception("2026-11-04", "2026-11-04", services.KIND_HOLIDAY)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(DayException.objects.count(), 1)

    def test_create_outside_the_year_is_rejected(self):
        response = self.post_exception("2026-08-30", "2026-09-02", services.KIND_VACATION)

        self.assertEqual(response.status_code, 400, response.content)

    def test_end_before_start_is_rejected(self):
        response = self.post_exception("2026-11-05", "2026-11-04", services.KIND_VACATION)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "exception_dates_reversed")

    def test_overlap_of_the_same_kind_is_rejected(self):
        self.make_exception(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Осенние"
        )

        response = self.post_exception("2026-11-02", "2026-11-08", services.KIND_VACATION)

        self.assertEqual(response.status_code, 400, response.content)

    def test_overlap_message_names_the_conflict(self):
        self.make_exception(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Осенние"
        )

        response = self.post_exception(
            "2026-11-02", "2026-11-08", services.KIND_VACATION, title="Осенние"
        )

        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["code"], "exception_overlap")
        self.assertEqual(body["params"]["title"], "Осенние")
        self.assertEqual(body["params"]["start"], "2026-10-26")
        self.assertIn("Осенние", body["detail"])

    def test_same_title_on_other_dates_is_fine(self):
        """Двое «Каникул» в разные даты — норма, имена не уникальны."""
        self.make_exception(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Каникулы"
        )

        response = self.post_exception(
            "2026-12-28", "2027-01-11", services.KIND_VACATION, title="Каникулы"
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(DayException.objects.filter(title="Каникулы").count(), 2)

    def test_failed_creation_leaves_the_calendar_workable(self):
        """После отказа прежняя разметка цела и удаляется как обычно."""
        existing = self.make_exception(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Осенние"
        )

        rejected = self.post_exception(
            "2026-11-02", "2026-11-08", services.KIND_VACATION
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(DayException.objects.count(), 1)

        days = self.client.get(reverse("schoolyear-days", args=[self.year.pk]))
        self.assertEqual(days.status_code, 200)

        removed = self.client.delete(
            reverse("dayexception-detail", args=[existing.pk])
        )
        self.assertEqual(removed.status_code, 204)
        self.assertFalse(DayException.objects.exists())

    def test_overlap_of_a_different_kind_is_allowed(self):
        self.make_exception(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Осенние"
        )

        response = self.post_exception("2026-10-28", "2026-10-28", services.KIND_WORKDAY)

        self.assertEqual(response.status_code, 201, response.content)

    def test_editing_a_period_does_not_conflict_with_itself(self):
        vacation = self.make_exception(
            date(2026, 10, 26), date(2026, 11, 3), services.KIND_VACATION, "Осенние"
        )

        response = self.client.patch(
            reverse("dayexception-detail", args=[vacation.pk]),
            {"end_date": "2026-11-05"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_cannot_attach_an_exception_to_another_users_year(self):
        alien = SchoolYear.objects.create(
            school=self.alien_school, name="чужой", start_date=YEAR_START, end_date=YEAR_END
        )

        response = self.post_exception(
            "2026-11-04", "2026-11-04", services.KIND_HOLIDAY, year=alien
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(DayException.objects.exists())

    def test_list_shows_only_own_exceptions(self):
        alien = SchoolYear.objects.create(
            school=self.alien_school, name="чужой", start_date=YEAR_START, end_date=YEAR_END
        )
        self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY, year=alien
        )
        mine = self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY
        )

        response = self.client.get(reverse("dayexception-list"))

        self.assertEqual([item["id"] for item in response.json()], [mine.pk])

    def test_list_can_be_filtered_by_year(self):
        second = SchoolYear.objects.create(
            school=self.school,
            name="2027/2028",
            start_date=date(2027, 9, 1),
            end_date=date(2028, 5, 31),
        )
        self.make_exception(date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY)
        expected = self.make_exception(
            date(2027, 11, 4), date(2027, 11, 4), services.KIND_HOLIDAY, year=second
        )

        response = self.client.get(reverse("dayexception-list"), {"year": second.pk})

        self.assertEqual([item["id"] for item in response.json()], [expected.pk])

    def test_garbage_year_filter_returns_nothing(self):
        self.make_exception(date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY)

        response = self.client.get(reverse("dayexception-list"), {"year": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_delete(self):
        holiday = self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY
        )

        response = self.client.delete(reverse("dayexception-detail", args=[holiday.pk]))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(DayException.objects.exists())

    def test_cannot_delete_another_users_exception(self):
        alien = SchoolYear.objects.create(
            school=self.alien_school, name="чужой", start_date=YEAR_START, end_date=YEAR_END
        )
        holiday = self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY, year=alien
        )

        response = self.client.delete(reverse("dayexception-detail", args=[holiday.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(DayException.objects.filter(pk=holiday.pk).exists())


class CalendarViewTests(CalendarApiTestCase):
    def test_days_covers_the_whole_year(self):
        response = self.client.get(reverse("schoolyear-days", args=[self.year.pk]))

        days = response.json()["days"]
        self.assertEqual(len(days), (YEAR_END - YEAR_START).days + 1)
        self.assertEqual(days[0]["date"], "2026-09-01")
        self.assertEqual(days[0]["status"], services.STATUS_STUDY)

    def test_days_reflect_exceptions(self):
        self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY, "День единства"
        )

        response = self.client.get(reverse("schoolyear-days", args=[self.year.pk]))

        day = next(d for d in response.json()["days"] if d["date"] == "2026-11-04")
        self.assertEqual(day["status"], services.STATUS_HOLIDAY)
        self.assertEqual(day["title"], "День единства")

    def test_stats_match_the_calendar(self):
        response = self.client.get(reverse("schoolyear-stats", args=[self.year.pk]))

        data = response.json()
        self.assertEqual(len(data["by_weekday"]), 7)
        self.assertEqual(data["total"], sum(row["count"] for row in data["by_weekday"]))
        self.assertEqual(data["total"], len(services.study_days(self.year.build_days())))

    def test_stats_drop_a_day_after_a_holiday_is_added(self):
        before = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()

        self.post_exception("2026-11-04", "2026-11-04", services.KIND_HOLIDAY)

        after = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()
        self.assertEqual(after["total"], before["total"] - 1)

    def test_stats_agree_with_days_on_the_same_data(self):
        """Два эндпоинта считают один и тот же календарь — расходиться нечему."""
        self.make_exception(
            date(2026, 10, 26), date(2026, 11, 8), services.KIND_VACATION, "Осенние"
        )
        self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY, "Праздник"
        )
        self.make_exception(
            date(2026, 11, 7), date(2026, 11, 7), services.KIND_HOLIDAY, "На субботу"
        )
        self.make_exception(
            date(2026, 12, 5), date(2026, 12, 5), services.KIND_WORKDAY, "Отработка"
        )

        days = self.client.get(reverse("schoolyear-days", args=[self.year.pk])).json()["days"]
        stats = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()

        by_status = Counter(day["status"] for day in days)
        self.assertEqual(
            stats["by_status"],
            {status: by_status[status] for status in services.STATUSES},
        )
        self.assertEqual(stats["total"], by_status[services.STATUS_STUDY])
        self.assertEqual(stats["calendar_days"], len(days))

        by_weekday = Counter(
            day["weekday"] for day in days if day["status"] == services.STATUS_STUDY
        )
        for row in stats["by_weekday"]:
            self.assertEqual(row["count"], by_weekday[row["weekday"]], row)

    def test_every_calendar_day_is_counted_exactly_once(self):
        self.make_exception(
            date(2026, 10, 26), date(2026, 11, 8), services.KIND_VACATION, "Осенние"
        )
        self.make_exception(
            date(2026, 11, 4), date(2026, 11, 4), services.KIND_HOLIDAY, "Праздник"
        )

        stats = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()

        self.assertEqual(
            sum(stats["by_status"].values()), (YEAR_END - YEAR_START).days + 1
        )
        self.assertEqual(stats["calendar_days"], sum(stats["by_status"].values()))

    def test_holiday_on_a_weekend_does_not_cost_a_study_day(self):
        before = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()

        # 2026-11-07 — суббота
        self.post_exception("2026-11-07", "2026-11-07", services.KIND_HOLIDAY)

        after = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()
        self.assertEqual(after["total"], before["total"])
        self.assertEqual(after["by_status"][services.STATUS_HOLIDAY], 0)

    def test_days_of_another_users_year_are_not_found(self):
        alien = SchoolYear.objects.create(
            school=self.alien_school, name="чужой", start_date=YEAR_START, end_date=YEAR_END
        )

        response = self.client.get(reverse("schoolyear-days", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)
