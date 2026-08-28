"""
Школьный день: сколько в нём уроков и когда они идут. Правится целиком.

Проверяется здесь то же, что у всякого справочника школы, плюс два своих:
номер урока — ключ, и повтор в нём не «последний побеждает», а отказ; а
длина дня — предложение, а не запрет задним числом.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    make_course,
    make_slot,
    make_user,
    sign_in,
)

from .models import BellTime, Slot


class BellsTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.user.is_school_admin = True
        self.user.save(update_fields=["is_school_admin"])
        self.url = reverse("school-bells")

    def rows(self, *pairs, lessons_per_day=10):
        return {
            "lessons_per_day": lessons_per_day,
            "bells": [
                {"number": number, "starts_at": starts, "ends_at": ends}
                for number, starts, ends in pairs
            ],
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

        answer = self.client.put(self.url, {"lessons_per_day": 10, "bells": []}, format="json")

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
        refused = self.client.put(self.url, {"lessons_per_day": 10, "bells": []}, format="json")
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)

    def test_the_length_of_the_day_travels_with_the_bells(self):
        """
        «Убрать седьмой урок» и «стереть время седьмого» — одно движение.

        Порознь они оставляли бы школу со звонком на урок, которого в дне
        нет, — состояние, которого никто не просил.
        """
        sign_in(self.client, self.user)

        answer = self.client.put(
            self.url,
            self.rows((1, "08:30", "09:15"), lessons_per_day=6),
            format="json",
        )

        self.assertEqual(answer.status_code, status.HTTP_200_OK)
        self.assertEqual(answer.json()["lessons_per_day"], 6)
        self.school.refresh_from_db()
        self.assertEqual(self.school.lessons_per_day, 6)

    def test_a_bell_for_a_lesson_the_day_does_not_hold_is_refused(self):
        """Звонок на седьмой урок в шестиурочном дне звонит в пустоту."""
        sign_in(self.client, self.user)

        answer = self.client.put(
            self.url,
            self.rows((7, "13:30", "14:15"), lessons_per_day=6),
            format="json",
        )

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "bell_beyond_day")

    def test_a_day_outside_the_range_is_refused(self):
        """
        Ноль уроков — не школьный день, а одиннадцатого номера не бывает в базе.

        Отказ с кодом, а не отказ поля DRF: длину человек правит кнопками, и
        упереться в границу для него обычное дело, а не ошибка ввода.
        """
        sign_in(self.client, self.user)

        for length in (0, 11):
            with self.subTest(lessons_per_day=length):
                answer = self.client.put(
                    self.url, self.rows(lessons_per_day=length), format="json"
                )
                self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(answer.json()["code"], "lessons_per_day_range")

    def test_shortening_the_day_keeps_the_hours_already_scheduled(self):
        """
        Сокращение — предложение на будущее, а не отмена прошлого.

        Отказ на этом месте запер бы школу с восьмиурочным прошлым: перейти
        на шесть уроков она не смогла бы никогда. Поэтому час остаётся, а
        число `busiest` говорит об этом заранее — рядом с кнопкой.
        """
        sign_in(self.client, self.user)
        course = make_course(self.school)
        make_slot(self.user, course, number=8)

        answer = self.client.put(
            self.url, self.rows(lessons_per_day=6), format="json"
        )

        self.assertEqual(answer.status_code, status.HTTP_200_OK)
        self.assertEqual(answer.json()["busiest"], 8)
        self.assertEqual(Slot.objects.filter(lesson_number=8).count(), 1)

    def test_a_new_hour_beyond_the_day_is_refused(self):
        """
        Сокращённый день держит границу там, где час **ставят**.

        Иначе «убрали седьмой урок» не значило бы ничего: сетка перестала бы
        его рисовать, а по API он заводился бы по-прежнему.
        """
        sign_in(self.client, self.user)
        self.school.lessons_per_day = 6
        self.school.save(update_fields=["lessons_per_day"])
        course = make_course(self.school)
        make_slot(self.user, course, number=1)

        answer = self.client.post(
            reverse("slot-list"),
            {
                "course": course.pk,
                "year": course.year_id,
                "date": str(course.year.start_date),
                "lesson_number": 7,
            },
            format="json",
        )

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "slot_number_beyond_day")

    def test_a_whole_row_beyond_the_day_is_refused_too(self):
        """
        Ряд заводит часы мимо `SlotSerializer` — и границу спрашивает сам.

        Без этого «убрали седьмой урок» не значило бы ничего: одиночный час
        на нём получал бы отказ, а тридцать четыре разом заводились бы молча.
        """
        sign_in(self.client, self.user)
        self.school.lessons_per_day = 6
        self.school.save(update_fields=["lessons_per_day"])
        course = make_course(self.school)
        make_slot(self.user, course, number=1)

        answer = self.client.post(
            reverse("slot-repeat"),
            {
                "course": course.pk,
                "date": str(course.year.start_date),
                "lesson_number": 7,
                "until": str(course.year.end_date),
            },
            format="json",
        )

        self.assertEqual(answer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(answer.json()["code"], "slot_number_beyond_day")

    def test_an_hour_left_beyond_the_day_is_still_editable(self):
        """
        День сокращают задним числом, и стоящий за границей час не заперт.

        Спрашивается граница только про **новый** номер: иначе отменить
        сорвавшийся восьмой урок или поставить ему кабинет было бы нечем.
        """
        sign_in(self.client, self.user)
        course = make_course(self.school)
        slot = make_slot(self.user, course, number=8)
        self.school.lessons_per_day = 6
        self.school.save(update_fields=["lessons_per_day"])

        answer = self.client.patch(
            reverse("slot-detail", args=[slot.pk]),
            {"is_cancelled": True, "reason": "заболел учитель"},
            format="json",
        )

        self.assertEqual(answer.status_code, status.HTTP_200_OK)

    def test_a_student_does_not_get_here(self):
        pupil = make_user(self.school, email="kid@example.com", student=True)
        sign_in(self.client, pupil)

        answer = self.client.get(self.url)

        self.assertEqual(answer.status_code, status.HTTP_403_FORBIDDEN)
