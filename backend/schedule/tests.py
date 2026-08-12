from datetime import date

from calendars.models import SchoolYear
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin

from .models import Course

YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)


class CourseApiTests(SchoolTestMixin, APITestCase):
    """Courses belong to the school, so the writer here is an administrator."""

    def setUp(self):
        super().setUp()
        self.sign_in(self.admin)
        self.year = self.make_year(self.school, "2026/2027")
        self.alien_year = self.make_year(self.alien_school, "2026/2027")

    def make_year(self, school, name, start=YEAR_START, end=YEAR_END):
        return SchoolYear.objects.create(
            school=school, name=name, start_date=start, end_date=end
        )

    def post_class(self, name, year=None, **extra):
        return self.client.post(
            reverse("course-list"),
            {"name": name, "year": (year or self.year).pk, **extra},
            format="json",
        )

    # --- создание ---

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("course-list")).status_code, 401)

    def test_create_sets_the_school_from_the_request(self):
        response = self.post_class("9Б")

        self.assertEqual(response.status_code, 201, response.content)
        created = Course.objects.get(name="9Б")
        self.assertEqual(created.school, self.school)
        self.assertEqual(created.year, self.year)
        self.assertNotIn("school", response.json())

    def test_school_from_body_is_ignored(self):
        """A foreign school cannot be slipped in through the request body."""
        response = self.post_class("9Б", school=self.alien_school.pk)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Course.objects.get(name="9Б").school, self.school)

    def test_cannot_create_in_another_schools_year(self):
        response = self.post_class("9Б", year=self.alien_year)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("year", response.json())
        self.assertFalse(Course.objects.exists())

    def test_duplicate_name_in_the_same_year_is_rejected(self):
        self.post_class("9Б")

        response = self.post_class("9Б")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["non_field_errors"],
            ["A course with this name already exists in this year."],
        )
        self.assertEqual(Course.objects.count(), 1)

    def test_same_name_in_another_year_is_allowed(self):
        next_year = self.make_year(
            self.school, "2027/2028", date(2027, 9, 1), date(2028, 5, 31)
        )
        self.post_class("9Б")

        response = self.post_class("9Б", year=next_year)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Course.objects.filter(name="9Б").count(), 2)

    def test_same_name_in_another_school_is_allowed(self):
        Course.objects.create(school=self.alien_school, year=self.alien_year, name="9Б")

        response = self.post_class("9Б")

        self.assertEqual(response.status_code, 201, response.content)

    def test_blank_name_is_rejected(self):
        response = self.post_class("   ")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())

    # --- чтение ---

    def test_list_shows_only_the_schools_courses(self):
        mine = Course.objects.create(school=self.school, year=self.year, name="9Б")
        Course.objects.create(school=self.alien_school, year=self.alien_year, name="9А")

        response = self.client.get(reverse("course-list"))

        self.assertEqual([item["id"] for item in response.json()], [mine.pk])

    def test_list_can_be_filtered_by_year(self):
        next_year = self.make_year(
            self.school, "2027/2028", date(2027, 9, 1), date(2028, 5, 31)
        )
        Course.objects.create(school=self.school, year=self.year, name="9Б")
        expected = Course.objects.create(
            school=self.school, year=next_year, name="10Б"
        )

        response = self.client.get(reverse("course-list"), {"year": next_year.pk})

        self.assertEqual([item["id"] for item in response.json()], [expected.pk])

    def test_garbage_year_filter_returns_nothing(self):
        Course.objects.create(school=self.school, year=self.year, name="9Б")

        response = self.client.get(reverse("course-list"), {"year": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_is_ordered_by_name(self):
        for name in ("11А", "5В", "9Б"):
            Course.objects.create(school=self.school, year=self.year, name=name)

        response = self.client.get(reverse("course-list"))

        self.assertEqual([item["name"] for item in response.json()], ["11А", "5В", "9Б"])

    def test_another_schools_course_is_not_found(self):
        alien = Course.objects.create(
            school=self.alien_school, year=self.alien_year, name="9А"
        )

        response = self.client.get(reverse("course-detail", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)

    # --- правка и удаление ---

    def test_rename(self):
        school_class = Course.objects.create(
            school=self.school, year=self.year, name="9Б"
        )

        response = self.client.patch(
            reverse("course-detail", args=[school_class.pk]),
            {"name": "9В"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        school_class.refresh_from_db()
        self.assertEqual(school_class.name, "9В")

    def test_rename_to_an_existing_name_is_rejected(self):
        Course.objects.create(school=self.school, year=self.year, name="9А")
        school_class = Course.objects.create(
            school=self.school, year=self.year, name="9Б"
        )

        response = self.client.patch(
            reverse("course-detail", args=[school_class.pk]),
            {"name": "9А"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_rename_keeps_its_own_name(self):
        """Сохранение без изменения имени не должно ловить само себя."""
        school_class = Course.objects.create(
            school=self.school, year=self.year, name="9Б"
        )

        response = self.client.patch(
            reverse("course-detail", args=[school_class.pk]),
            {"name": "9Б"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_cannot_edit_another_schools_course(self):
        alien = Course.objects.create(
            school=self.alien_school, year=self.alien_year, name="9А"
        )

        response = self.client.patch(
            reverse("course-detail", args=[alien.pk]), {"name": "взлом"}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        alien.refresh_from_db()
        self.assertEqual(alien.name, "9А")

    def test_delete(self):
        school_class = Course.objects.create(
            school=self.school, year=self.year, name="9Б"
        )

        response = self.client.delete(
            reverse("course-detail", args=[school_class.pk])
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Course.objects.exists())

    def test_cannot_delete_another_schools_course(self):
        alien = Course.objects.create(
            school=self.alien_school, year=self.alien_year, name="9А"
        )

        response = self.client.delete(reverse("course-detail", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Course.objects.filter(pk=alien.pk).exists())

    def test_deleting_the_year_removes_its_courses(self):
        Course.objects.create(school=self.school, year=self.year, name="9Б")

        self.client.delete(reverse("schoolyear-detail", args=[self.year.pk]))

        self.assertFalse(Course.objects.exists())


class CourseModelTests(SchoolTestMixin, APITestCase):
    def test_str_is_the_name(self):
        year = SchoolYear.objects.create(
            school=self.school,
            name="2026/2027",
            start_date=YEAR_START,
            end_date=YEAR_END,
        )

        self.assertEqual(
            str(Course.objects.create(school=self.school, year=year, name="9Б")), "9Б"
        )
