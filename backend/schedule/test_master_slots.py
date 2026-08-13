"""
The school timetable itself: who may edit it and what it refuses to hold.

The access matrix is checked once, generically, in `schools/test_access.py`.
What is here is the behaviour specific to this table — the clash between two
courses of one teacher, and the row nobody has been assigned to yet.
"""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    assign,
    MONDAY,
    SchoolTestMixin,
    make_course,
    make_master_slot,
    make_year,
)

from .models import MasterSlot

TUESDAY = date(2026, 9, 8)


class MasterSlotTestCase(SchoolTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "9Б Алгебра")
        self.geometry = make_course(self.school, self.year, "9Б Геометрия")
        # в школьном расписании можно назвать только назначенного учителя
        for course in (self.algebra, self.geometry):
            assign(self.user, course)
            assign(self.colleague, course)
        self.sign_in(self.admin)

    def post(self, **fields):
        payload = {
            "year": self.year.pk,
            "course": self.algebra.pk,
            "teacher": self.user.pk,
            "date": MONDAY.isoformat(),
            "lesson_number": 1,
            **fields,
        }
        return self.client.post(reverse("masterslot-list"), payload, format="json")


class CreationTests(MasterSlotTestCase):
    def test_an_admin_lays_out_a_lesson(self):
        response = self.post()

        self.assertEqual(response.status_code, 201, response.content)
        slot = MasterSlot.objects.get()
        self.assertEqual(slot.school, self.school)
        self.assertEqual(slot.teacher, self.user)

    def test_a_row_may_have_no_teacher_yet(self):
        """The grid is usually built before the load is shared out."""
        response = self.post(teacher=None)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(MasterSlot.objects.get().teacher)

    def test_one_teacher_cannot_stand_in_two_places(self):
        make_master_slot(self.algebra, self.user, MONDAY, 1)

        response = self.post(course=self.geometry.pk, lesson_number=1)

        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body["code"], "slot_number_taken")
        self.assertEqual(body["params"]["class_name"], "9Б Алгебра")
        self.assertEqual(MasterSlot.objects.count(), 1)

    def test_rows_without_a_teacher_never_clash(self):
        """Nobody is standing there yet, so there is nothing to clash with."""
        make_master_slot(self.algebra, None, MONDAY, 1)

        response = self.post(course=self.geometry.pk, teacher=None, lesson_number=1)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MasterSlot.objects.count(), 2)

    def test_two_teachers_may_share_an_hour(self):
        make_master_slot(self.algebra, self.user, MONDAY, 1)

        response = self.post(
            course=self.geometry.pk, teacher=self.colleague.pk, lesson_number=1
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_a_course_cannot_be_booked_twice_that_hour(self):
        make_master_slot(self.algebra, self.user, MONDAY, 1)

        response = self.post(teacher=self.colleague.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("non_field_errors", response.json())

    def test_a_course_of_another_school_is_refused(self):
        alien = make_course(self.alien_school, name="Чужой")

        response = self.post(course=alien.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("course", response.json())

    def test_a_teacher_of_another_school_is_refused(self):
        response = self.post(teacher=self.stranger.pk)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("teacher", response.json())

    def test_a_date_outside_the_year_is_refused(self):
        response = self.post(date="2025-09-01")

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["code"], "slot_outside_year")

    def test_the_model_catches_the_clash_too(self):
        """The admin site goes through full_clean, not the serializer."""
        make_master_slot(self.algebra, self.user, MONDAY, 1)
        duplicate = MasterSlot(
            school=self.school,
            year=self.year,
            course=self.geometry,
            teacher=self.user,
            date=MONDAY,
            lesson_number=1,
        )

        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()

        self.assertIn("lesson_number", caught.exception.message_dict)


class FilterTests(MasterSlotTestCase):
    def setUp(self):
        super().setUp()
        make_master_slot(self.algebra, self.user, MONDAY, 1)
        make_master_slot(self.geometry, self.colleague, MONDAY, 2)
        make_master_slot(self.algebra, self.user, TUESDAY, 1)

    def listing(self, **params):
        return self.client.get(reverse("masterslot-list"), params).json()

    def test_by_teacher(self):
        rows = self.listing(teacher=self.colleague.pk)

        self.assertEqual([row["course_name"] for row in rows], ["9Б Геометрия"])

    def test_by_course(self):
        self.assertEqual(len(self.listing(course=self.algebra.pk)), 2)

    def test_by_period(self):
        rows = self.listing(start=TUESDAY.isoformat(), end=TUESDAY.isoformat())

        self.assertEqual(len(rows), 1)

    def test_garbage_filters_return_nothing_rather_than_crash(self):
        self.assertEqual(self.listing(teacher="абв"), [])
        self.assertEqual(self.listing(start="вчера"), [])

    def test_the_row_carries_readable_names(self):
        row = self.listing(teacher=self.colleague.pk)[0]

        self.assertEqual(row["course_name"], "9Б Геометрия")
        self.assertEqual(row["teacher_name"], "colleague@example.com")


class SummaryTests(MasterSlotTestCase):
    def test_it_counts_what_is_laid_out_and_what_has_nobody(self):
        make_master_slot(self.algebra, self.user, MONDAY, 1)
        make_master_slot(self.geometry, None, MONDAY, 2)

        data = self.client.get(reverse("masterslot-summary")).json()

        self.assertEqual(data["total"], 2)
        self.assertEqual(data["unassigned"], 1)
        self.assertEqual(data["teachers"], 1)


class BulkTests(MasterSlotTestCase):
    def setUp(self):
        super().setUp()
        make_master_slot(self.algebra, self.user, MONDAY, 1)
        make_master_slot(self.geometry, self.colleague, TUESDAY, 2)

    def clear(self, **params):
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return self.client.delete(f"{reverse('masterslot-bulk')}?{query}")

    def test_a_period_is_cleared(self):
        response = self.clear(start=MONDAY.isoformat(), end=TUESDAY.isoformat())

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["deleted"], 2)
        self.assertFalse(MasterSlot.objects.exists())

    def test_one_course_at_a_time(self):
        self.clear(
            start=MONDAY.isoformat(),
            end=TUESDAY.isoformat(),
            course=self.algebra.pk,
        )

        self.assertEqual(
            [slot.course for slot in MasterSlot.objects.all()], [self.geometry]
        )

    def test_the_period_is_required(self):
        response = self.clear(start=MONDAY.isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "period_required")

    def test_a_teacher_cannot_clear_the_timetable(self):
        self.sign_in(self.user)

        response = self.clear(start=MONDAY.isoformat(), end=TUESDAY.isoformat())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(MasterSlot.objects.count(), 2)


class CopyTests(MasterSlotTestCase):
    def setUp(self):
        super().setUp()
        make_master_slot(self.algebra, self.user, MONDAY, 1)
        make_master_slot(self.geometry, self.colleague, TUESDAY, 2)

    def copy(self, **overrides):
        payload = {
            "source_start": MONDAY.isoformat(),
            "source_end": (MONDAY + timedelta(days=6)).isoformat(),
            "target_start": (MONDAY + timedelta(days=7)).isoformat(),
            "target_end": (MONDAY + timedelta(days=13)).isoformat(),
            "mode": "merge",
            **overrides,
        }
        return self.client.post(reverse("masterslot-copy"), payload, format="json")

    def test_a_week_is_repeated_for_every_course(self):
        response = self.copy()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created"], 2)
        self.assertEqual(MasterSlot.objects.count(), 4)

    def test_the_weekday_is_kept(self):
        self.copy()

        moved = MasterSlot.objects.filter(course=self.algebra).order_by("date").last()
        self.assertEqual(moved.date.weekday(), MONDAY.weekday())
        self.assertEqual(moved.teacher, self.user)

    def test_a_teacher_cannot_copy_the_timetable(self):
        self.sign_in(self.user)

        self.assertEqual(self.copy().status_code, 403)
