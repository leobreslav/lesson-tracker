from datetime import date

from calendars.models import SchoolYear
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import SchoolClass

User = get_user_model()

YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)


class SchoolClassApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="teacher@example.com")
        self.other = User.objects.create_user(email="other@example.com")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}"
        )
        self.year = self.make_year(self.user, "2026/2027")
        self.alien_year = self.make_year(self.other, "2026/2027")

    def make_year(self, owner, name, start=YEAR_START, end=YEAR_END):
        return SchoolYear.objects.create(
            owner=owner, name=name, start_date=start, end_date=end
        )

    def post_class(self, name, year=None, **extra):
        return self.client.post(
            reverse("schoolclass-list"),
            {"name": name, "year": (year or self.year).pk, **extra},
            format="json",
        )

    # --- создание ---

    def test_requires_authentication(self):
        self.client.credentials()

        self.assertEqual(self.client.get(reverse("schoolclass-list")).status_code, 401)

    def test_create_sets_owner_from_request(self):
        response = self.post_class("9Б")

        self.assertEqual(response.status_code, 201, response.content)
        created = SchoolClass.objects.get(name="9Б")
        self.assertEqual(created.owner, self.user)
        self.assertEqual(created.year, self.year)
        self.assertNotIn("owner", response.json())

    def test_owner_from_body_is_ignored(self):
        """Подставить чужого владельца через тело запроса нельзя."""
        response = self.post_class("9Б", owner=self.other.pk)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(SchoolClass.objects.get(name="9Б").owner, self.user)

    def test_cannot_create_in_another_users_year(self):
        response = self.post_class("9Б", year=self.alien_year)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("year", response.json())
        self.assertFalse(SchoolClass.objects.exists())

    def test_duplicate_name_in_the_same_year_is_rejected(self):
        self.post_class("9Б")

        response = self.post_class("9Б")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["non_field_errors"],
            ["A class with this name already exists in this year."],
        )
        self.assertEqual(SchoolClass.objects.count(), 1)

    def test_same_name_in_another_year_is_allowed(self):
        next_year = self.make_year(
            self.user, "2027/2028", date(2027, 9, 1), date(2028, 5, 31)
        )
        self.post_class("9Б")

        response = self.post_class("9Б", year=next_year)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(SchoolClass.objects.filter(name="9Б").count(), 2)

    def test_same_name_for_another_owner_is_allowed(self):
        SchoolClass.objects.create(owner=self.other, year=self.alien_year, name="9Б")

        response = self.post_class("9Б")

        self.assertEqual(response.status_code, 201, response.content)

    def test_blank_name_is_rejected(self):
        response = self.post_class("   ")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())

    # --- чтение ---

    def test_list_shows_only_own_classes(self):
        mine = SchoolClass.objects.create(owner=self.user, year=self.year, name="9Б")
        SchoolClass.objects.create(owner=self.other, year=self.alien_year, name="9А")

        response = self.client.get(reverse("schoolclass-list"))

        self.assertEqual([item["id"] for item in response.json()], [mine.pk])

    def test_list_can_be_filtered_by_year(self):
        next_year = self.make_year(
            self.user, "2027/2028", date(2027, 9, 1), date(2028, 5, 31)
        )
        SchoolClass.objects.create(owner=self.user, year=self.year, name="9Б")
        expected = SchoolClass.objects.create(
            owner=self.user, year=next_year, name="10Б"
        )

        response = self.client.get(reverse("schoolclass-list"), {"year": next_year.pk})

        self.assertEqual([item["id"] for item in response.json()], [expected.pk])

    def test_garbage_year_filter_returns_nothing(self):
        SchoolClass.objects.create(owner=self.user, year=self.year, name="9Б")

        response = self.client.get(reverse("schoolclass-list"), {"year": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_list_is_ordered_by_name(self):
        for name in ("11А", "5В", "9Б"):
            SchoolClass.objects.create(owner=self.user, year=self.year, name=name)

        response = self.client.get(reverse("schoolclass-list"))

        self.assertEqual([item["name"] for item in response.json()], ["11А", "5В", "9Б"])

    def test_another_users_class_is_not_found(self):
        alien = SchoolClass.objects.create(
            owner=self.other, year=self.alien_year, name="9А"
        )

        response = self.client.get(reverse("schoolclass-detail", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)

    # --- правка и удаление ---

    def test_rename(self):
        school_class = SchoolClass.objects.create(
            owner=self.user, year=self.year, name="9Б"
        )

        response = self.client.patch(
            reverse("schoolclass-detail", args=[school_class.pk]),
            {"name": "9В"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        school_class.refresh_from_db()
        self.assertEqual(school_class.name, "9В")

    def test_rename_to_an_existing_name_is_rejected(self):
        SchoolClass.objects.create(owner=self.user, year=self.year, name="9А")
        school_class = SchoolClass.objects.create(
            owner=self.user, year=self.year, name="9Б"
        )

        response = self.client.patch(
            reverse("schoolclass-detail", args=[school_class.pk]),
            {"name": "9А"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_rename_keeps_its_own_name(self):
        """Сохранение без изменения имени не должно ловить само себя."""
        school_class = SchoolClass.objects.create(
            owner=self.user, year=self.year, name="9Б"
        )

        response = self.client.patch(
            reverse("schoolclass-detail", args=[school_class.pk]),
            {"name": "9Б"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_cannot_edit_another_users_class(self):
        alien = SchoolClass.objects.create(
            owner=self.other, year=self.alien_year, name="9А"
        )

        response = self.client.patch(
            reverse("schoolclass-detail", args=[alien.pk]), {"name": "взлом"}, format="json"
        )

        self.assertEqual(response.status_code, 404)
        alien.refresh_from_db()
        self.assertEqual(alien.name, "9А")

    def test_delete(self):
        school_class = SchoolClass.objects.create(
            owner=self.user, year=self.year, name="9Б"
        )

        response = self.client.delete(
            reverse("schoolclass-detail", args=[school_class.pk])
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(SchoolClass.objects.exists())

    def test_cannot_delete_another_users_class(self):
        alien = SchoolClass.objects.create(
            owner=self.other, year=self.alien_year, name="9А"
        )

        response = self.client.delete(reverse("schoolclass-detail", args=[alien.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SchoolClass.objects.filter(pk=alien.pk).exists())

    def test_deleting_the_year_removes_its_classes(self):
        SchoolClass.objects.create(owner=self.user, year=self.year, name="9Б")

        self.client.delete(reverse("schoolyear-detail", args=[self.year.pk]))

        self.assertFalse(SchoolClass.objects.exists())


class SchoolClassModelTests(APITestCase):
    def test_str_is_the_name(self):
        user = User.objects.create_user(email="teacher@example.com")
        year = SchoolYear.objects.create(
            owner=user, name="2026/2027", start_date=YEAR_START, end_date=YEAR_END
        )

        self.assertEqual(
            str(SchoolClass.objects.create(owner=user, year=year, name="9Б")), "9Б"
        )
