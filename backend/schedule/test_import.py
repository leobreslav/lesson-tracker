"""
Importing the school timetable into a teacher's own schedule.

The two properties worth guarding are «only mine» and «only once». The first
is ordinary scoping; the second is the one that is easy to lose by accident,
so two tests poke at both sides of the wall after the copy is made.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework.test import APITestCase
from schools.testing import (
    MONDAY,
    SchoolTestMixin,
    make_course,
    make_master_slot,
    make_slot,
    make_year,
)

from .models import LessonSlot, MasterSlot

TUESDAY = MONDAY + timedelta(days=1)
NEXT_MONDAY = MONDAY + timedelta(days=7)


class ImportTestCase(SchoolTestMixin, APITestCase):
    """A timetable with two courses of mine and one of a colleague's."""

    def setUp(self):
        super().setUp()
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "9Б Алгебра")
        self.geometry = make_course(self.school, self.year, "9Б Геометрия")
        self.theirs = make_course(self.school, self.year, "10А Алгебра")

        make_master_slot(self.algebra, self.user, MONDAY, 1)
        make_master_slot(self.algebra, self.user, NEXT_MONDAY, 1)
        make_master_slot(self.geometry, self.user, TUESDAY, 2)
        make_master_slot(self.theirs, self.colleague, MONDAY, 3)

    def run_import(self, **overrides):
        payload = {
            "year": self.year.pk,
            "start": MONDAY.isoformat(),
            "end": (MONDAY + timedelta(days=30)).isoformat(),
            "mode": "merge",
            **overrides,
        }
        return self.client.post(
            reverse("import-from-school"), payload, format="json"
        )

    def preview(self, **params):
        return self.client.get(
            reverse("import-preview"),
            {"year": self.year.pk, **params},
        )

    def mine(self):
        return LessonSlot.objects.filter(teacher=self.user)


class ScopeTests(ImportTestCase):
    def test_only_my_rows_come_across(self):
        response = self.run_import()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created"], 3)
        self.assertEqual(self.mine().count(), 3)
        self.assertFalse(self.mine().filter(course=self.theirs).exists())

    def test_the_lessons_belong_to_the_importer(self):
        self.run_import()

        self.assertEqual(
            {slot.teacher for slot in LessonSlot.objects.all()}, {self.user}
        )

    def test_a_colleague_imports_their_own_and_only_theirs(self):
        self.sign_in(self.colleague)

        self.run_import()

        self.assertEqual(
            [slot.course for slot in LessonSlot.objects.filter(teacher=self.colleague)],
            [self.theirs],
        )

    def test_a_row_with_nobody_assigned_reaches_nobody(self):
        make_master_slot(self.geometry, None, NEXT_MONDAY, 5)

        self.run_import()

        self.assertFalse(self.mine().filter(lesson_number=5).exists())

    def test_another_school_imports_nothing(self):
        self.sign_in(self.stranger)
        alien_year = make_year(self.alien_school)

        response = self.client.post(
            reverse("import-from-school"),
            {
                "year": alien_year.pk,
                "start": MONDAY.isoformat(),
                "end": (MONDAY + timedelta(days=30)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["created"], 0)
        self.assertFalse(LessonSlot.objects.filter(teacher=self.stranger).exists())

    def test_another_schools_year_cannot_even_be_named(self):
        self.sign_in(self.stranger)

        response = self.run_import()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("year", response.json())

    def test_a_user_without_a_school_is_refused(self):
        self.sign_in(self.outsider)

        response = self.run_import()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "no_school")


class CourseChoiceTests(ImportTestCase):
    def test_no_courses_given_means_all_of_mine(self):
        self.run_import()

        self.assertEqual(
            sorted(slot.course.name for slot in self.mine()),
            ["9Б Алгебра", "9Б Алгебра", "9Б Геометрия"],
        )

    def test_null_courses_means_all_of_mine_too(self):
        """The interface sends an explicit null when nothing is unticked."""
        response = self.run_import(courses=None)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.mine().count(), 3)

    def test_a_subset_brings_only_that_subset(self):
        self.run_import(courses=[self.geometry.pk])

        self.assertEqual([slot.course for slot in self.mine()], [self.geometry])

    def test_a_course_of_another_school_is_refused(self):
        alien = make_course(self.alien_school, name="Чужой")

        response = self.run_import(courses=[alien.pk])

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("courses", response.json())


class ModeTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        # a lesson of mine that the timetable does not know about
        self.handmade = make_slot(self.user, self.algebra, MONDAY, 6)
        # and one exactly where the timetable wants to put a lesson
        self.clash = make_slot(self.user, self.geometry, TUESDAY, 2)

    def test_merge_keeps_what_is_there_and_skips_the_clash(self):
        response = self.run_import(mode="merge")

        data = response.json()
        self.assertEqual(data["created"], 2)
        self.assertEqual(data["skipped"], 1)
        self.assertTrue(self.mine().filter(pk=self.handmade.pk).exists())
        self.assertTrue(self.mine().filter(pk=self.clash.pk).exists())

    def test_merge_reports_a_clash_with_another_course(self):
        LessonSlot.objects.filter(pk=self.clash.pk).delete()
        # the same hour, but a different course of mine
        make_slot(self.user, self.algebra, TUESDAY, 2)

        data = self.run_import(mode="merge").json()

        self.assertEqual(len(data["conflicts"]), 1)
        conflict = data["conflicts"][0]
        self.assertEqual(conflict["class_name"], "9Б Алгебра")
        self.assertEqual(conflict["lesson_number"], 2)

    def test_replace_clears_the_chosen_courses_first(self):
        response = self.run_import(mode="replace")

        data = response.json()
        self.assertEqual(data["created"], 3)
        self.assertFalse(self.mine().filter(pk=self.handmade.pk).exists())
        self.assertFalse(self.mine().filter(pk=self.clash.pk).exists())
        self.assertEqual(self.mine().count(), 3)

    def test_replace_touches_only_the_chosen_courses(self):
        untouched = make_slot(self.user, self.theirs, MONDAY, 7)

        self.run_import(mode="replace", courses=[self.geometry.pk])

        self.assertTrue(self.mine().filter(pk=untouched.pk).exists())
        self.assertTrue(self.mine().filter(pk=self.handmade.pk).exists())

    def test_replace_touches_only_the_chosen_period(self):
        far = make_slot(self.user, self.algebra, MONDAY + timedelta(days=60), 1)

        self.run_import(mode="replace")

        self.assertTrue(self.mine().filter(pk=far.pk).exists())


class IndependenceTests(ImportTestCase):
    """
    The copy is a copy. Nothing links it back, and that is the design.

    Both directions are checked, because the temptation to «just sync it»
    would break exactly one of them first.
    """

    def test_editing_my_lesson_leaves_the_timetable_alone(self):
        self.run_import()
        slot = self.mine().get(course=self.algebra, date=MONDAY)

        self.client.patch(
            reverse("lessonslot-detail", args=[slot.pk]),
            {"is_cancelled": True, "reason": "Болезнь"},
            format="json",
        )

        row = MasterSlot.objects.get(course=self.algebra, date=MONDAY)
        self.assertEqual(row.lesson_number, 1)
        self.assertEqual(MasterSlot.objects.count(), 4)

    def test_editing_the_timetable_leaves_my_lessons_alone(self):
        self.run_import()
        row = MasterSlot.objects.get(course=self.algebra, date=MONDAY)

        self.sign_in(self.admin)
        self.client.patch(
            reverse("masterslot-detail", args=[row.pk]),
            {"lesson_number": 8},
            format="json",
        )

        self.assertTrue(
            self.mine().filter(course=self.algebra, date=MONDAY, lesson_number=1).exists()
        )

    def test_deleting_the_timetable_row_leaves_my_lesson_alone(self):
        self.run_import()
        row = MasterSlot.objects.get(course=self.algebra, date=MONDAY)

        self.sign_in(self.admin)
        self.client.delete(reverse("masterslot-detail", args=[row.pk]))

        self.assertTrue(self.mine().filter(course=self.algebra, date=MONDAY).exists())

    def test_importing_twice_adds_nothing_the_second_time(self):
        self.run_import()

        second = self.run_import().json()

        self.assertEqual(second["created"], 0)
        self.assertEqual(self.mine().count(), 3)


class TransactionTests(ImportTestCase):
    def test_a_failure_rolls_the_whole_import_back(self):
        """
        One bad row must not leave half a week behind.

        The failure is forced at the last write, which is the only moment
        where a partial result could survive a missing transaction.
        """
        from unittest.mock import patch

        with patch(
            "schedule.importing.LessonSlot.objects.bulk_create",
            side_effect=RuntimeError("база отвалилась"),
        ):
            with self.assertRaises(RuntimeError):
                self.run_import(mode="replace")

        # replace deletes before it writes: without the transaction the
        # deletion would have stuck and the teacher would lose lessons
        self.assertEqual(MasterSlot.objects.count(), 4)
        self.assertEqual(self.mine().count(), 0)

    def test_replace_does_not_lose_lessons_when_the_write_fails(self):
        from unittest.mock import patch

        handmade = make_slot(self.user, self.algebra, MONDAY, 6)

        with patch(
            "schedule.importing.LessonSlot.objects.bulk_create",
            side_effect=RuntimeError("база отвалилась"),
        ):
            with self.assertRaises(RuntimeError):
                self.run_import(mode="replace")

        self.assertTrue(self.mine().filter(pk=handmade.pk).exists())


class PreviewTests(ImportTestCase):
    def test_it_says_what_would_come(self):
        data = self.preview(
            start=MONDAY.isoformat(), end=(MONDAY + timedelta(days=30)).isoformat()
        ).json()

        self.assertEqual(data["available"], 3)
        self.assertEqual(data["created"], 3)
        self.assertEqual(
            sorted(item["name"] for item in data["courses"]),
            ["9Б Алгебра", "9Б Геометрия"],
        )

    def test_it_writes_nothing(self):
        self.preview()

        self.assertFalse(LessonSlot.objects.exists())

    def test_it_names_the_conflicts(self):
        make_slot(self.user, self.algebra, TUESDAY, 2)

        data = self.preview().json()

        self.assertEqual(len(data["conflicts"]), 1)
        self.assertEqual(data["conflicts"][0]["class_name"], "9Б Алгебра")

    def test_without_a_period_it_covers_the_whole_year(self):
        data = self.preview().json()

        self.assertEqual(data["start"], self.year.start_date.isoformat())
        self.assertEqual(data["end"], self.year.end_date.isoformat())

    def test_the_year_is_required(self):
        response = self.client.get(reverse("import-preview"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "year_required")

    def test_another_schools_year_is_not_previewable(self):
        self.sign_in(self.stranger)

        response = self.preview()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "year_required")

    def test_a_colleague_sees_their_own_preview(self):
        self.sign_in(self.colleague)

        data = self.preview().json()

        self.assertEqual([item["name"] for item in data["courses"]], ["10А Алгебра"])
