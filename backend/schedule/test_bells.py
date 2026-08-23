"""
Расписание звонков: справочник школы, правится целиком.

Проверяется здесь то же, что у всякого справочника школы, плюс одно своё:
номер урока — ключ, и повтор в нём не «последний побеждает», а отказ.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_user, sign_in

from .models import BellTime


class BellsTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.user.is_school_admin = True
        self.user.save(update_fields=["is_school_admin"])
        self.url = reverse("school-bells")

    def rows(self, *pairs):
        return {
            "bells": [
                {"number": number, "starts_at": starts, "ends_at": ends}
                for number, starts, ends in pairs
            ]
        }

    def test_an_admin_sets_the_bells(self):
        sign_in(self.client, self.user)

        answer = self.client.put(
            self.url, self.rows((1, "08:30", "09:15"), (2, "09:25", "10:10")), format="json"
        )

        self.assertEqual(answer.status_code, status.HTTP_200_OK)
        self.assertEqual(
            answer.json()["bells"],
            [
                {"number": 1, "starts_at": "08:30", "ends_at": "09:15"},
                {"number": 2, "starts_at": "09:25", "ends_at": "10:10"},
            ],
        )

    def test_the_whole_thing_is_replaced(self):
        """Список приходит целиком: «строки, которой не стало» тут не бывает."""
        sign_in(self.client, self.user)
        self.client.put(self.url, self.rows((1, "08:30", "09:15"), (2, "09:25", "10:10")), format="json")

        self.client.put(self.url, self.rows((1, "09:00", "09:45")), format="json")

        self.assertEqual(BellTime.objects.count(), 1)
        self.assertEqual(str(BellTime.objects.get().starts_at), "09:00:00")

    def test_an_empty_list_means_no_bells(self):
        """До звонков школа жила, и пустой справочник — рабочее состояние."""
        sign_in(self.client, self.user)
        self.client.put(self.url, self.rows((1, "08:30", "09:15")), format="json")

        answer = self.client.put(self.url, {"bells": []}, format="json")

        self.assertEqual(answer.status_code, status.HTTP_200_OK)
        self.assertEqual(BellTime.objects.count(), 0)

    def test_the_same_number_twice_is_refused(self):
        sign_in(self.client, self.user)

        answer = self.client.put(
            self.url, self.rows((1, "08:30", "09:15"), (1, "09:25", "10:10")), format="json"
        )

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "bell_number_twice")

    def test_a_lesson_ending_before_it_starts_is_refused(self):
        sign_in(self.client, self.user)

        answer = self.client.put(self.url, self.rows((1, "09:15", "08:30")), format="json")

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "bell_ends_before_it_starts")

    def test_a_teacher_reads_them_but_does_not_change_them(self):
        teacher = make_user(self.school, email="plain@example.com")
        sign_in(self.client, teacher)

        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)
        refused = self.client.put(self.url, {"bells": []}, format="json")
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_student_does_not_get_here(self):
        pupil = make_user(self.school, email="kid@example.com", student=True)
        sign_in(self.client, pupil)

        answer = self.client.get(self.url)

        self.assertEqual(answer.status_code, status.HTTP_403_FORBIDDEN)
