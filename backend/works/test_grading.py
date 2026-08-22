"""
Система оценивания: как из работы получается отметка.

Проверяются три решения, каждое из которых легко откатить назад по недосмотру:
**выбирает учитель** (администратор только ограничивает), **хранятся баллы, а
отметка выводится**, и **работа без системы законна** — баллы есть, отметки нет.
"""

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import SchoolTestMixin, make_course, make_work, make_year

from . import grading, services
from .models import GradeBand, GradingSystem


class BandTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        self.work = make_work(self.user, self.course)
        grading.add_typical(self.school, "ru")
        self.five = self.school.grading_systems.get(name="5-балльная")
        self.myp = self.school.grading_systems.get(name="MYP 1–7")

    def test_points_are_bands_in_percent(self):
        """У баллов порог в процентах: у работ разные максимумы."""
        self.assertEqual(
            services.grade_for(self.five, earned=9, top=10)["label"], "5"
        )
        # 30 из 40 — это 75%, то есть четвёрка: у другой работы другой
        # максимум, а полоса та же
        self.assertEqual(
            services.grade_for(self.five, earned=30, top=40)["label"], "4"
        )
        self.assertEqual(
            services.grade_for(self.five, earned=1, top=10)["label"], "2"
        )

    def test_levels_are_bands_on_the_sum(self):
        """У MYP сумма уровней фиксирована, и порог — сама сумма."""
        self.assertEqual(services.grade_for(self.myp, earned=32, top=32)["label"], "7")
        self.assertEqual(services.grade_for(self.myp, earned=15, top=32)["label"], "4")
        self.assertEqual(services.grade_for(self.myp, earned=3, top=32)["label"], "1")

    def test_no_system_means_no_grade(self):
        """Работа без системы законна: баллы есть, отметки нет."""
        self.assertIsNone(services.grade_for(None, earned=5, top=10))

    def test_nothing_earned_from_nothing(self):
        self.assertIsNone(services.grade_for(self.five, earned=0, top=0))

    def test_the_grade_follows_the_bands(self):
        """
        Отметка выводится, а не хранится.

        Поправили порог — прошлые работы читаются по новому, и это то, чего
        школа обычно и хочет. Хранить букву значило бы соврать при первой же
        правке.
        """
        band = self.five.bands.get(label="5")
        band.threshold = 95
        band.save()

        self.assertEqual(services.grade_for(self.five, earned=9, top=10)["label"], "4")


class TypicalTests(SchoolTestMixin, APITestCase):
    def test_a_new_school_gets_nothing_by_itself(self):
        """Угаданный набор хуже пустого списка: школа удаляла бы ненужное."""
        self.assertEqual(self.school.grading_systems.count(), 0)

    def test_pressing_twice_is_harmless(self):
        grading.add_typical(self.school, "ru")
        added = grading.add_typical(self.school, "ru")

        self.assertEqual(added, 0)
        self.assertEqual(self.school.grading_systems.count(), 3)

    def test_edited_bands_are_not_reset(self):
        """«Обновить до типовых» — худшее прочтение этой кнопки."""
        grading.add_typical(self.school, "ru")
        system = self.school.grading_systems.get(name="5-балльная")
        system.bands.filter(label="5").update(threshold=95)

        grading.add_typical(self.school, "ru")

        self.assertEqual(system.bands.get(label="5").threshold, 95)


class ChoiceTests(SchoolTestMixin, APITestCase):
    """Выбирает учитель, администратор только ограничивает поле выбора."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        grading.add_typical(self.school, "ru")
        self.five = self.school.grading_systems.get(name="5-балльная")

    def test_a_teacher_picks_the_system_on_the_work(self):
        self.client.force_authenticate(self.user)
        work = make_work(self.user, self.course)

        response = self.client.patch(
            reverse("work-detail", args=[work.pk]),
            {"grading_system": self.five.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        work.refresh_from_db()
        self.assertEqual(work.grading_system_id, self.five.pk)

    def test_a_teacher_does_not_edit_the_catalogue(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("grading-system", args=[self.five.pk]),
            {"is_allowed": False},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_the_administrator_restricts_the_choice(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            reverse("grading-system", args=[self.five.pk]),
            {"is_allowed": False, "as_default": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.five.refresh_from_db()
        self.school.refresh_from_db()
        self.assertFalse(self.five.is_allowed)
        self.assertEqual(self.school.default_grading_system_id, self.five.pk)

    def test_another_schools_system_does_not_exist(self):
        self.client.force_authenticate(self.alien_admin)

        response = self.client.patch(
            reverse("grading-system", args=[self.five.pk]),
            {"name": "Чужая"},
            format="json",
        )

        self.assertEqual(response.json()["code"], "other_school")
