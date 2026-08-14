"""Состояние первого входа и демо-данные."""

from datetime import date, timedelta

from calendars.models import DayException, SchoolYear, Term
from django.urls import reverse
from django.utils import timezone
from plans.models import PlanNode
from rest_framework.test import APITestCase
from schedule.models import Course, LessonSlot
from schools.testing import assign, SchoolTestMixin, make_course, make_year

from . import services


class OnboardingTestCase(SchoolTestMixin, APITestCase):
    """The demo belongs to the school, so the person here is an admin."""

    def setUp(self):
        super().setUp()
        self.sign_in(self.admin)
        self.user = self.admin

    def status(self):
        return self.client.get(reverse("onboarding-status")).json()

    def make_year(self, school=None, name="2026/2027"):
        return make_year(school or self.school, name)

    def make_class(self, year, name="9Б"):
        """
        A course of this teacher's.

        Assigned on the way: the dashboard shows what somebody teaches, and
        a course nobody handed them is not on their list.
        """
        course = make_course(year.school, year, name)
        assign(self.user, course)
        return course


class StatusTests(OnboardingTestCase):
    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(
            self.client.get(reverse("onboarding-status")).status_code, 401
        )

    def test_empty_account(self):
        data = self.status()

        self.assertFalse(data["year"]["exists"])
        self.assertIsNone(data["year"]["name"])
        self.assertEqual(data["calendar"], {"terms": 0, "exceptions": 0})
        self.assertEqual(data["classes"]["count"], 0)
        self.assertEqual(data["schedule"]["slots"], 0)
        self.assertEqual(data["plan"], {"classes_with_plan": 0, "total_classes": 0})

    def test_only_year(self):
        self.make_year()

        data = self.status()

        self.assertTrue(data["year"]["exists"])
        self.assertEqual(data["year"]["name"], "2026/2027")
        self.assertEqual(data["year"]["start"], "2026-09-01")
        self.assertEqual(data["classes"]["count"], 0)

    def test_year_with_calendar_markup(self):
        year = self.make_year()
        Term.objects.create(
            year=year, name="1 четверть",
            start_date=date(2026, 9, 1), end_date=date(2026, 10, 25),
        )
        DayException.objects.create(
            year=year, kind="vacation", title="Осенние",
            start_date=date(2026, 10, 26), end_date=date(2026, 11, 3),
        )

        self.assertEqual(self.status()["calendar"], {"terms": 1, "exceptions": 1})

    def test_year_and_classes(self):
        year = self.make_year()
        self.make_class(year, "9Б Алгебра")
        self.make_class(year, "9Б Геометрия")

        data = self.status()

        self.assertEqual(data["classes"]["count"], 2)
        self.assertEqual(
            data["classes"]["names"], ["9Б Алгебра", "9Б Геометрия"]
        )
        self.assertEqual(data["plan"], {"classes_with_plan": 0, "total_classes": 2})

    def test_everything_filled(self):
        year = self.make_year()
        first = self.make_class(year, "9Б Алгебра")
        second = self.make_class(year, "9Б Геометрия")

        today = timezone.localdate()
        LessonSlot.objects.create(
            year=year, teacher=self.user, course=first,
            date=date(2026, 9, 7), lesson_number=1,
        )
        LessonSlot.objects.create(
            year=year, teacher=self.user, course=second,
            date=date(2026, 9, 8), lesson_number=1,
        )
        PlanNode.objects.create(
            teacher=self.user, course=first, position=0, is_section=False, title="Урок"
        )

        data = self.status()

        self.assertEqual(data["schedule"]["slots"], 2)
        self.assertEqual(data["plan"], {"classes_with_plan": 1, "total_classes": 2})
        summary = {item["name"]: item for item in data["classes"]["items"]}
        self.assertEqual(summary["9Б Алгебра"]["slots"], 1)
        self.assertEqual(summary["9Б Алгебра"]["plan_lessons"], 1)
        self.assertEqual(summary["9Б Алгебра"]["balance"], 0)
        self.assertEqual(summary["9Б Геометрия"]["balance"], 1)
        self.assertEqual(
            summary["9Б Алгебра"]["past"] + summary["9Б Алгебра"]["remaining"],
            summary["9Б Алгебра"]["slots"],
        )
        self.assertLessEqual(today.year, 2027)  # даты будущие, past = 0

    def test_cancelled_slots_do_not_count(self):
        year = self.make_year()
        course = self.make_class(year)
        LessonSlot.objects.create(
            year=year, teacher=self.user, course=course, date=date(2026, 9, 7),
            lesson_number=1, is_cancelled=True, reason="Болезнь",
        )

        self.assertEqual(self.status()["schedule"]["slots"], 0)

    def test_latest_year_is_shown(self):
        self.make_year(name="2025/2026")
        SchoolYear.objects.create(
            school=self.school, name="2027/2028",
            start_date=date(2027, 9, 1), end_date=date(2028, 5, 31),
        )

        self.assertEqual(self.status()["year"]["name"], "2027/2028")

    def test_another_users_data_is_invisible(self):
        alien_year = self.make_year(school=self.alien_school, name="чужой")
        alien_class = self.make_class(alien_year, "чужой класс")
        LessonSlot.objects.create(
            year=alien_year, teacher=self.stranger, course=alien_class,
            date=date(2026, 9, 7), lesson_number=1,
        )

        data = self.status()

        self.assertFalse(data["year"]["exists"])
        self.assertEqual(data["classes"]["count"], 0)
        self.assertEqual(data["schedule"]["slots"], 0)


class DemoTests(OnboardingTestCase):
    def create(self):
        return self.client.post(reverse("onboarding-demo"))

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.post(reverse("onboarding-demo")).status_code, 401)

    def test_demo_creates_a_full_set(self):
        response = self.create()

        self.assertEqual(response.status_code, 201, response.content)
        status = response.json()["status"]

        self.assertTrue(status["year"]["exists"])
        self.assertEqual(status["calendar"]["terms"], 4)
        self.assertEqual(status["calendar"]["exceptions"], 3)
        self.assertEqual(status["classes"]["count"], 2)
        self.assertGreater(status["schedule"]["slots"], 100)
        self.assertEqual(status["plan"]["classes_with_plan"], 1)

    def test_demo_skips_vacations_and_weekends(self):
        self.create()
        year = SchoolYear.objects.get(school=self.school)

        # уроков в каникулы и выходные быть не должно
        vacation = DayException.objects.filter(year=year).first()
        self.assertFalse(
            LessonSlot.objects.filter(
                teacher=self.user,
                date__range=(vacation.start_date, vacation.end_date),
            ).exists()
        )
        weekend_slots = [
            slot
            for slot in LessonSlot.objects.filter(teacher=self.user)
            if slot.date.weekday() >= 5
        ]
        self.assertEqual(weekend_slots, [])

    def test_demo_classes_do_not_collide_on_lesson_numbers(self):
        """У учителя не бывает двух уроков в одно окно — пример это уважает."""
        self.create()

        pairs = list(
            LessonSlot.objects.filter(teacher=self.user)
            .values_list("date", "lesson_number")
        )

        self.assertEqual(len(pairs), len(set(pairs)))

    def test_demo_plan_is_a_two_level_tree(self):
        self.create()

        sections = PlanNode.objects.filter(teacher=self.user, is_section=True)
        lessons = PlanNode.objects.filter(teacher=self.user, is_section=False)

        self.assertEqual(sections.count(), 7)
        self.assertEqual(lessons.count(), 44)
        self.assertTrue(all(lesson.parent_id is not None for lesson in lessons))

    def test_demo_follows_the_user_language(self):
        """Демо-данные — контент в базе, поэтому заводятся на языке учителя."""
        self.user.language = "ru"
        self.user.save(update_fields=["language"])

        self.client.post(reverse("onboarding-demo"))

        year = SchoolYear.objects.get(school=self.school)
        self.assertIn("(пример)", year.name)
        self.assertEqual(
            list(year.terms.values_list("name", flat=True))[:1], ["1 четверть"]
        )
        self.assertEqual(
            sorted(Course.objects.filter(school=self.school).values_list("name", flat=True)),
            ["9Б Алгебра", "9Б Геометрия"],
        )

    def test_demo_is_in_english_by_default(self):
        self.client.post(reverse("onboarding-demo"))

        year = SchoolYear.objects.get(school=self.school)
        self.assertIn("(example)", year.name)
        self.assertEqual(
            sorted(Course.objects.filter(school=self.school).values_list("name", flat=True)),
            ["Grade 9B Algebra", "Grade 9B Geometry"],
        )


class DefaultsTests(APITestCase):
    def test_school_year_is_picked_by_the_current_date(self):
        """С июня предлагаем наступающий год: летом готовятся к сентябрю."""
        self.assertEqual(services.current_start_year(date(2026, 5, 31)), 2025)
        self.assertEqual(services.current_start_year(date(2026, 6, 1)), 2026)
        self.assertEqual(services.current_start_year(date(2026, 8, 31)), 2026)
        self.assertEqual(services.current_start_year(date(2027, 1, 15)), 2026)

    def test_typical_terms_do_not_overlap_and_fit_the_year(self):
        terms = services.typical_terms(2026)

        self.assertEqual(len(terms), 4)
        for previous, following in zip(terms, terms[1:]):
            self.assertLess(previous["end_date"], following["start_date"])
        self.assertGreaterEqual(terms[0]["start_date"], date(2026, 9, 1))
        self.assertLessEqual(terms[-1]["end_date"], date(2027, 5, 31))

    def test_typical_vacations_land_between_terms(self):
        terms = services.typical_terms(2026)
        vacations = services.typical_vacations(2026)

        self.assertEqual(len(vacations), 3)
        for vacation in vacations:
            inside_term = any(
                term["start_date"] <= vacation["start_date"] <= term["end_date"]
                for term in terms
            )
            self.assertFalse(inside_term, vacation["title"])

    def test_vacations_are_ordered_and_valid(self):
        for vacation in services.typical_vacations(2026):
            self.assertLessEqual(vacation["start_date"], vacation["end_date"])
