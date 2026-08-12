"""Четверти и семестры: валидация, календарь и статистика."""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from . import services
from .models import DayException, Term
from .tests import CalendarApiTestCase


class FakeTerm:
    def __init__(self, pk, start, end, name=""):
        self.pk = pk
        self.start_date = start
        self.end_date = end
        self.name = name


class FindTermTests(SimpleTestCase):
    def setUp(self):
        self.first = FakeTerm(1, date(2026, 9, 1), date(2026, 10, 25), "1 четверть")
        self.second = FakeTerm(2, date(2026, 11, 5), date(2026, 12, 27), "2 четверть")
        self.terms = [self.first, self.second]

    def test_date_inside_a_term(self):
        self.assertIs(services.find_term(date(2026, 9, 15), self.terms), self.first)

    def test_bounds_are_inclusive(self):
        self.assertIs(services.find_term(date(2026, 9, 1), self.terms), self.first)
        self.assertIs(services.find_term(date(2026, 10, 25), self.terms), self.first)

    def test_date_between_terms_has_none(self):
        """Каникулы между четвертями ни в один терм не входят."""
        self.assertIsNone(services.find_term(date(2026, 10, 30), self.terms))

    def test_date_outside_all_terms(self):
        self.assertIsNone(services.find_term(date(2027, 3, 1), self.terms))

    def test_no_terms_at_all(self):
        self.assertIsNone(services.find_term(date(2026, 9, 15), []))

    def test_overlap_helper(self):
        self.assertTrue(
            services.spans_overlap(
                date(2026, 9, 1), date(2026, 9, 10), date(2026, 9, 10), date(2026, 9, 20)
            )
        )
        self.assertFalse(
            services.spans_overlap(
                date(2026, 9, 1), date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 20)
            )
        )


class DaysWithTermsTests(SimpleTestCase):
    def test_days_carry_the_term(self):
        term = FakeTerm(7, date(2026, 9, 7), date(2026, 9, 9), "1 четверть")

        days = services.build_days(
            date(2026, 9, 7), date(2026, 9, 11), terms=[term]
        )

        self.assertEqual([day.term_id for day in days], [7, 7, 7, None, None])
        self.assertEqual(days[0].term_name, "1 четверть")
        self.assertEqual(days[-1].term_name, "")

    def test_stats_split_study_days_by_term(self):
        term = FakeTerm(7, date(2026, 9, 7), date(2026, 9, 13), "1 четверть")

        stats = services.build_stats(
            services.build_days(date(2026, 9, 7), date(2026, 9, 20), terms=[term])
        )

        first, outside = stats["by_term"]
        self.assertEqual((first["id"], first["study"], first["calendar_days"]), (7, 5, 7))
        self.assertEqual((outside["id"], outside["study"]), (None, 5))
        self.assertEqual(
            sum(row["study"] for row in stats["by_term"]), stats["total"]
        )

    def test_vacation_inside_a_term_does_not_break_counting(self):
        term = FakeTerm(7, date(2026, 9, 7), date(2026, 9, 18), "1 четверть")
        vacation = services.Period(
            date(2026, 9, 9), date(2026, 9, 11), services.KIND_VACATION, "Каникулы"
        )

        stats = services.build_stats(
            services.build_days(
                date(2026, 9, 7), date(2026, 9, 18), periods=[vacation], terms=[term]
            )
        )

        row = stats["by_term"][0]
        self.assertEqual(row["calendar_days"], 12)
        self.assertEqual(row["study"], 7)  # десять будних минус три дня каникул
        self.assertEqual(row["study"], stats["total"])


class TermApiTests(CalendarApiTestCase):
    def post_term(self, name, start, end, year=None, **extra):
        return self.client.post(
            reverse("term-list"),
            {
                "year": (year or self.year).pk,
                "name": name,
                "start_date": start,
                "end_date": end,
                **extra,
            },
            format="json",
        )

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("term-list")).status_code, 401)

    def test_create(self):
        response = self.post_term("1 четверть", "2026-09-01", "2026-10-25")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Term.objects.get().name, "1 четверть")

    def test_terms_may_leave_gaps(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")

        response = self.post_term("2 четверть", "2026-11-05", "2026-12-27")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Term.objects.count(), 2)

    def test_overlapping_terms_are_rejected(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")

        response = self.post_term("2 четверть", "2026-10-20", "2026-12-27")

        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["code"], "term_overlap")
        self.assertEqual(body["params"]["name"], "1 четверть")
        self.assertEqual(Term.objects.count(), 1)

    def test_touching_terms_are_rejected(self):
        """Один и тот же день в двух четвертях — тоже пересечение."""
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")

        response = self.post_term("2 четверть", "2026-10-25", "2026-12-27")

        self.assertEqual(response.status_code, 400, response.content)

    def test_term_outside_the_year_is_rejected(self):
        response = self.post_term("Лишняя", "2026-08-01", "2026-09-10")

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "term_outside_year")

    def test_end_before_start_is_rejected(self):
        response = self.post_term("Кривая", "2026-10-25", "2026-09-01")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "term_dates_reversed")

    def test_editing_a_term_does_not_conflict_with_itself(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")
        term = Term.objects.get()

        response = self.client.patch(
            reverse("term-detail", args=[term.pk]),
            {"end_date": "2026-11-01"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_model_clean_catches_overlap(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")
        duplicate = Term(
            year=self.year,
            name="2 четверть",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 11, 1),
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_list_is_filtered_by_year(self):
        second = self.year.__class__.objects.create(
            school=self.school,
            name="2027/2028",
            start_date=date(2027, 9, 1),
            end_date=date(2028, 5, 31),
        )
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")
        self.post_term("Первый семестр", "2027-09-01", "2027-12-31", year=second)

        response = self.client.get(reverse("term-list"), {"year": second.pk})

        self.assertEqual([item["name"] for item in response.json()], ["Первый семестр"])

    def test_cannot_create_in_another_users_year(self):
        alien = self.year.__class__.objects.create(
            school=self.alien_school,
            name="чужой",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
        )

        response = self.post_term("Чужая", "2026-09-01", "2026-10-25", year=alien)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(Term.objects.exists())

    def test_another_users_term_is_invisible(self):
        alien_year = self.year.__class__.objects.create(
            school=self.alien_school,
            name="чужой",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 31),
        )
        alien = Term.objects.create(
            year=alien_year,
            name="Чужая",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 10, 25),
        )

        self.assertEqual(self.client.get(reverse("term-list")).json(), [])
        self.assertEqual(
            self.client.get(reverse("term-detail", args=[alien.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.delete(reverse("term-detail", args=[alien.pk])).status_code, 404
        )

    def test_deleting_the_year_removes_its_terms(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")

        self.client.delete(reverse("schoolyear-detail", args=[self.year.pk]))

        self.assertFalse(Term.objects.exists())

    def test_days_endpoint_reports_the_term(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")
        term = Term.objects.get()

        days = self.client.get(reverse("schoolyear-days", args=[self.year.pk])).json()["days"]

        inside = next(day for day in days if day["date"] == "2026-09-15")
        outside = next(day for day in days if day["date"] == "2026-11-15")
        self.assertEqual((inside["term_id"], inside["term_name"]), (term.pk, "1 четверть"))
        self.assertEqual((outside["term_id"], outside["term_name"]), (None, ""))

    def test_stats_endpoint_splits_by_term(self):
        self.post_term("1 четверть", "2026-09-01", "2026-10-25")
        DayException.objects.create(
            year=self.year,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 9),
            kind=services.KIND_VACATION,
            title="Осенние",
        )

        data = self.client.get(reverse("schoolyear-stats", args=[self.year.pk])).json()

        by_term = {row["name"] or "вне термов": row["study"] for row in data["by_term"]}
        self.assertEqual(sum(by_term.values()), data["total"])
        self.assertEqual(len(data["by_term"]), 2)
