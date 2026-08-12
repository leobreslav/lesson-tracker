"""
`seed_demo` invents data and can delete it, so the guards matter more than
the data itself.

The test runner turns DEBUG off, which is why the refusal is checked without
any setup and everything else runs under `override_settings(DEBUG=True)`.
"""

from io import StringIO

from calendars.models import DayException, SchoolYear, Term
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from plans.models import PlanNode
from schedule.models import Course, LessonSlot

from .models import Invitation, School

User = get_user_model()


def seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


class DebugGuardTests(TestCase):
    def test_it_refuses_to_run_with_debug_off(self):
        """The one thing standing between invented data and the live база."""
        with self.assertRaises(CommandError) as caught:
            seed()

        self.assertIn("DEBUG=True", str(caught.exception))
        self.assertFalse(School.objects.exists())

    @override_settings(DEBUG=True)
    def test_with_debug_on_it_runs(self):
        seed()

        self.assertTrue(School.objects.exists())


@override_settings(DEBUG=True)
class SeedTests(TestCase):
    def test_an_empty_database_gets_a_whole_school(self):
        seed()

        school = School.objects.get()
        self.assertEqual(school.name, "Тестовая школа")

        year = SchoolYear.objects.get(school=school)
        self.assertEqual(year.name, "2026/2027")
        self.assertEqual(Term.objects.filter(year=year).count(), 4)
        self.assertEqual(Course.objects.filter(school=school).count(), 4)
        self.assertEqual(User.objects.filter(school=school).count(), 3)
        self.assertEqual(User.objects.filter(is_school_admin=True).count(), 1)

    def test_the_markup_has_breaks_and_holidays(self):
        seed()

        markup = DayException.objects.all()
        self.assertEqual(markup.filter(kind="vacation").count(), 3)
        self.assertEqual(markup.filter(kind="holiday").count(), 4)

    def test_the_schedule_avoids_non_study_days(self):
        """The seeder asks the calendar rather than guessing."""
        seed()

        year = SchoolYear.objects.get()
        study = {day.date for day in year.build_days() if day.is_study}
        # extra lessons are put next to a regular one on purpose and may
        # legitimately land on a day off — the regular ones may not
        regular = LessonSlot.objects.filter(is_extra=False)

        self.assertTrue(regular.exists())
        self.assertEqual(
            [slot.date for slot in regular if slot.date not in study], []
        )

    def test_the_interface_states_are_all_present(self):
        """
        The point of the whole command: something to look at for each state.

        A course with a full plan, one with a plan that runs out, one with
        neither plan nor timetable, plus cancellations and extra lessons.
        """
        seed()

        courses = {course.name: course for course in Course.objects.all()}

        full = PlanNode.objects.filter(
            course=courses["Grade 6 Algebra"], is_section=False
        ).count()
        partial = PlanNode.objects.filter(
            course=courses["Grade 9 Algebra"], is_section=False
        ).count()

        self.assertGreater(full, 35)
        self.assertLess(partial, full)
        self.assertFalse(
            PlanNode.objects.filter(course=courses["Grade 6 Geometry"]).exists()
        )
        self.assertFalse(
            LessonSlot.objects.filter(course=courses["Grade 9 Geometry"]).exists()
        )
        self.assertTrue(LessonSlot.objects.filter(is_cancelled=True).exists())
        self.assertTrue(LessonSlot.objects.filter(is_extra=True).exists())

    def test_the_plans_are_split_into_blocks(self):
        seed()

        sections = PlanNode.objects.filter(is_section=True)
        self.assertGreater(sections.count(), 3)
        self.assertTrue(
            PlanNode.objects.filter(is_section=False, parent__isnull=False).exists()
        )

    def test_the_summary_says_what_was_made(self):
        output = seed()

        self.assertIn("Тестовая школа", output)
        self.assertIn("2026/2027", output)
        self.assertIn("Grade 6 Algebra", output)


@override_settings(DEBUG=True)
class RepeatTests(TestCase):
    def counts(self):
        return {
            "schools": School.objects.count(),
            "years": SchoolYear.objects.count(),
            "terms": Term.objects.count(),
            "markup": DayException.objects.count(),
            "courses": Course.objects.count(),
            "users": User.objects.count(),
            "slots": LessonSlot.objects.count(),
            "cancelled": LessonSlot.objects.filter(is_cancelled=True).count(),
            "extra": LessonSlot.objects.filter(is_extra=True).count(),
            "plan": PlanNode.objects.count(),
        }

    def test_a_second_run_changes_nothing(self):
        seed()
        after_one = self.counts()

        seed()

        self.assertEqual(self.counts(), after_one)

    def test_three_runs_change_nothing_either(self):
        """
        Marking lessons by hand is the part that used to drift.

        Picking «the twelfth lesson» over a set the command itself grows
        made the second run cancel a different one, so the count crept up.
        """
        seed()
        after_one = self.counts()

        seed()
        seed()

        self.assertEqual(self.counts(), after_one)


@override_settings(DEBUG=True)
class FlushTests(TestCase):
    def test_flush_clears_what_was_there_and_builds_again(self):
        seed()
        stale = Course.objects.create(
            school=School.objects.get(),
            year=SchoolYear.objects.get(),
            name="Лишний курс",
        )

        seed("--flush")

        self.assertFalse(Course.objects.filter(pk=stale.pk).exists())
        self.assertEqual(Course.objects.count(), 4)
        self.assertEqual(School.objects.count(), 1)

    def test_flush_keeps_superusers(self):
        """Wiping the account you administer the box with is never meant."""
        root = User.objects.create_superuser(
            email="root@example.com", password="S3cret-pass-123"
        )

        seed("--flush")

        root.refresh_from_db()
        self.assertTrue(root.is_superuser)
        self.assertIsNone(root.school)


@override_settings(DEBUG=True)
class MinimalTests(TestCase):
    def test_minimal_stops_after_the_courses(self):
        seed("--minimal")

        self.assertEqual(Course.objects.count(), 4)
        self.assertEqual(Term.objects.count(), 4)
        self.assertFalse(LessonSlot.objects.exists())
        self.assertFalse(PlanNode.objects.exists())


@override_settings(DEBUG=True)
class AttachTests(TestCase):
    def test_an_existing_account_joins_as_an_administrator(self):
        me = User.objects.create_user(email="me@example.com")

        output = seed("--email=me@example.com")

        me.refresh_from_db()
        self.assertEqual(me.school, School.objects.get())
        self.assertTrue(me.is_school_admin)
        self.assertIn("me@example.com", output)

    def test_the_address_is_matched_case_insensitively(self):
        me = User.objects.create_user(email="me@example.com")

        seed("--email=Me@Example.com")

        me.refresh_from_db()
        self.assertTrue(me.is_school_admin)

    def test_an_unknown_address_gets_an_invitation_instead(self):
        """They have not signed in yet — the first Google login lands them."""
        output = seed("--email=stranger@example.com")

        invitation = Invitation.objects.get(email="stranger@example.com")
        self.assertTrue(invitation.is_school_admin)
        self.assertEqual(invitation.school, School.objects.get())
        self.assertIn("приглашение", output)

    def test_without_the_flag_nobody_is_attached(self):
        me = User.objects.create_user(email="me@example.com")

        seed()

        me.refresh_from_db()
        self.assertIsNone(me.school)
