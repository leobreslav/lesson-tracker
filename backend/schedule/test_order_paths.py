"""
Все пути записи против одного правила: очередь остаётся очередью.

Правило держалось точечными проверками в тех местах, которые помнил автор,
и каждый новый путь его не наследовал. Ревизия нашла девять дыр разом:
шесть на календарной оси (здесь) и три в импорте плана (`plans`). Общего у
них ровно одно — они писали мимо проверки, а не вопреки ей.

Поэтому и лечение общее: `SlotViewSet.guard_order` — пост-условие после
записи, внутри транзакции. Тесты здесь стерегут не формулировку отказа, а
то, что **ни один** из путей не проходит.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from schools.testing import (
    SchoolTestMixin,
    assign,
    live_year,
    make_course,
    make_node,
    make_slot,
)

from .models import Slot


class OrderPathsTestCase(SchoolTestMixin, APITestCase):
    """Курс с тремя прошедшими часами, первый и второй записаны."""

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.year = live_year(self.school)
        self.course = make_course(self.school, self.year, "9Б Алгебра")
        assign(self.user, self.course)
        self.rows = [
            make_node(self.user, self.course, f"Урок {number}")
            for number in range(1, 6)
        ]
        self.past = [
            make_slot(self.user, self.course, self.today - timedelta(days=days), 1)
            for days in (21, 14, 7)
        ]
        for slot, row in zip(self.past[:2], self.rows):
            slot.lesson = row
            slot.save(update_fields=["lesson"])

    def code(self, response):
        return response.json().get("code")


class HolesInThePastTests(OrderPathsTestCase):
    def test_a_new_hour_between_records_is_refused(self):
        """Дыра появляется и от создания, а не только от пропуска записи."""
        response = self.client.post(
            reverse("slot-list"),
            {
                "course": self.course.pk,
                "date": str(self.past[0].date),
                "lesson_number": 4,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_order_broken")

    def test_an_hour_before_the_first_record_is_fine(self):
        """До начала учёта очереди нет: там дырам взяться неоткуда."""
        response = self.client.post(
            reverse("slot-list"),
            {
                "course": self.course.pk,
                "date": str(self.today - timedelta(days=28)),
                "lesson_number": 1,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_copying_into_the_closed_past_is_refused(self):
        # свободный номер в источнике: на занятый копирование не полезет, и
        # проверять было бы нечего
        make_slot(self.user, self.course, self.past[2].date, 3)

        response = self.client.post(
            reverse("slot-copy"),
            {
                "course_id": self.course.pk,
                "source_start": str(self.past[2].date),
                "source_end": str(self.past[2].date + timedelta(days=6)),
                "target_start": str(self.past[0].date),
                "target_end": str(self.past[0].date + timedelta(days=6)),
                "mode": "merge",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_order_broken")

    def test_bringing_a_cancelled_hour_back_is_refused(self):
        """Возврат отменённого — та же дыра, только с другой стороны."""
        gap = make_slot(self.user, self.course, self.past[0].date, 5)
        gap.is_cancelled = True
        gap.reason = "карантин"
        gap.save(update_fields=["is_cancelled", "reason"])

        response = self.client.patch(
            reverse("slot-detail", args=[gap.pk]),
            {"is_cancelled": False, "reason": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_order_broken")


class RewritingThePastTests(OrderPathsTestCase):
    def test_moving_a_record_by_patching_the_date_is_refused(self):
        """`move` проверку знал, а правка даты полем шла мимо него."""
        response = self.client.patch(
            reverse("slot-detail", args=[self.past[0].pk]),
            {"date": str(self.today)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_order_broken")

    def test_cancelling_a_recorded_hour_is_refused(self):
        """
        Отмена прятала запись: `Slot.lesson` оставался, а очередь и
        раскладка отменённых не видят — строка плана оказывалась заперта
        навсегда, потому что снять можно только последнюю запись.
        """
        response = self.client.patch(
            reverse("slot-detail", args=[self.past[1].pk]),
            {"is_cancelled": True, "reason": "проба"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_cancel_recorded")
        self.past[1].refresh_from_db()
        self.assertFalse(self.past[1].is_cancelled)

    def test_cancelling_an_unrecorded_hour_still_works(self):
        """«Занятия не было» — обычный способ закрыть час, он остаётся."""
        response = self.client.patch(
            reverse("slot-detail", args=[self.past[2].pk]),
            {"is_cancelled": True, "reason": "карантин"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)


class ClosingDebtsTests(OrderPathsTestCase):
    """
    Разбор долгов писал связь **полем**, мимо всех правил записи.

    Это был второй способ записывать, не знающий ни про очередь, ни про
    подсказанную строку, ни про «только прошедшее». Теперь он идёт через
    тот же сериализатор, что и одиночная запись.
    """

    def close(self, rows):
        return self.client.post(reverse("slot-close"), {"closed": rows}, format="json")

    def test_a_future_hour_cannot_be_closed(self):
        ahead = make_slot(self.user, self.course, self.today + timedelta(days=7), 1)

        response = self.close([{"slot": ahead.pk, "lesson": self.rows[2].pk}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_record_future")

    def test_a_row_the_layout_did_not_suggest_is_refused(self):
        response = self.close([{"slot": self.past[2].pk, "lesson": self.rows[4].pk}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_record_not_suggested")

    def test_the_suggested_row_closes_the_next_hour(self):
        response = self.close([{"slot": self.past[2].pk, "lesson": self.rows[2].pk}])

        self.assertEqual(response.status_code, 200, response.content)
        self.past[2].refresh_from_db()
        self.assertEqual(self.past[2].lesson_id, self.rows[2].pk)

    def test_closing_out_of_order_is_refused(self):
        """Ответили на второй долг, оставив первый, — очередь не примет."""
        later = make_slot(self.user, self.course, self.today, 1)

        response = self.close([{"slot": later.pk, "lesson": self.rows[3].pk}])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.code(response), "slot_record_out_of_order")

    def test_nothing_is_written_when_one_row_is_refused(self):
        """Одна транзакция: половина закрытого списка хуже незакрытого."""
        later = make_slot(self.user, self.course, self.today, 1)

        self.close(
            [
                {"slot": self.past[2].pk, "lesson": self.rows[2].pk},
                {"slot": later.pk, "lesson": self.rows[4].pk},
            ]
        )

        self.past[2].refresh_from_db()
        self.assertIsNone(self.past[2].lesson_id)

    def test_a_cancellation_closes_the_hour_as_before(self):
        response = self.close(
            [{"slot": self.past[2].pk, "cancelled": True, "reason": "карантин"}]
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.past[2].refresh_from_db()
        self.assertTrue(self.past[2].is_cancelled)
