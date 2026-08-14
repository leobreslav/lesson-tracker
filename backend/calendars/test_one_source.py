"""
Учебный день — один и тот же на всех страницах.

Расчёт всегда жил в одном месте (`SchoolYear.build_days`), а вот **ответ**
разошёлся: календарь отдавал статус, сводное расписание — ещё и `is_study`
рядом с ним. Школьное расписание читало `is_study` из календарного ответа,
получало `undefined` и красило неучебными все дни года, включая будни.

Поэтому тесты здесь сравнивают не вычисление, а именно ответы эндпоинтов
между собой: одна дата, три страницы, один вердикт.
"""

from datetime import date

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    assign,
    make_course,
    make_year,
)

from .models import DayException

# понедельник внутри года и суббота той же недели
WEEKDAY = MONDAY
WEEKEND = date(2026, 9, 12)


class OneSourceTests(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.sign_in(self.admin)
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.admin, self.course)

    # --- как о дне спрашивает каждая из страниц ---

    def from_calendar(self, day):
        """Страница «Учебный год» и школьное расписание: /days/ этого года."""
        answer = self.client.get(reverse("schoolyear-days", args=[self.year.pk])).json()
        return next(item for item in answer["days"] if item["date"] == day.isoformat())

    def from_agenda(self, day):
        """«Моё расписание»: сводный вид по всем классам."""
        answer = self.client.get(
            reverse("lessonslot-agenda"),
            {"start": day.isoformat(), "end": day.isoformat()},
        ).json()
        return answer["days"][day.isoformat()]

    def assertSameVerdict(self, day, *, study):
        calendar, agenda = self.from_calendar(day), self.from_agenda(day)

        self.assertEqual(calendar["is_study"], study, f"календарь про {day}")
        self.assertEqual(agenda["is_study"], study, f"расписание про {day}")
        self.assertEqual(calendar["status"], agenda["status"])
        self.assertEqual(calendar["title"], agenda["title"])

    # --- сами проверки ---

    def test_an_ordinary_weekday_is_a_study_day_everywhere(self):
        self.assertSameVerdict(WEEKDAY, study=True)

    def test_a_weekend_is_not_a_study_day_anywhere(self):
        self.assertSameVerdict(WEEKEND, study=False)

    def test_a_holiday_is_not_a_study_day_anywhere(self):
        DayException.objects.create(
            year=self.year, start_date=WEEKDAY, end_date=WEEKDAY,
            kind="holiday", title="Праздник",
        )

        self.assertSameVerdict(WEEKDAY, study=False)

    def test_a_year_without_terms_still_has_study_days(self):
        """
        Термы — разметка поверх года, а не условие учебного дня.

        Год без единого терма — обычное состояние сразу после создания, и
        расписание в нём должно работать.
        """
        self.assertEqual(self.year.terms.count(), 0)

        day = self.from_calendar(WEEKDAY)

        self.assertTrue(day["is_study"])
        self.assertIsNone(day["term_id"])

    def test_every_field_of_the_day_is_answered_the_same(self):
        """Не только is_study: расходиться могло любое поле ответа."""
        calendar = self.from_calendar(WEEKDAY)
        agenda = self.from_agenda(WEEKDAY)

        shared = set(calendar) & set(agenda)
        self.assertIn("is_study", shared)
        for field in shared:
            self.assertEqual(calendar[field], agenda[field], field)

    def test_a_date_outside_every_year_is_answered_too(self):
        """Расписание листается и за границы года — там не должно падать."""
        far = date(2030, 9, 2)

        day = self.from_agenda(far)

        self.assertFalse(day["is_study"])
        self.assertEqual(day["status"], "outside")


class TimetableAcceptsWeekdaysTests(SchoolTestMixin, APITestCase):
    """Урок в обычный будний день заводится — и в школьном, и в личном."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)

    def test_the_admin_lays_out_a_lesson_on_a_weekday(self):
        """Расписание школы — те же слоты, только чужого курса."""
        self.sign_in(self.admin)

        response = self.client.post(
            reverse("lessonslot-list"),
            {
                "course": self.course.pk,
                "date": WEEKDAY.isoformat(),
                "lesson_number": 1,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_a_personal_lesson_on_a_weekday_carries_no_warning(self):
        response = self.client.post(
            reverse("lessonslot-list"),
            {
                "course": self.course.pk,
                "date": WEEKDAY.isoformat(),
                "lesson_number": 1,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        # предупреждение «не учебный день» появляется только в каникулы
        self.assertIsNone(response.json()["warning"])
