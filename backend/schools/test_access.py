"""
Who may do what, model by model and role by role.

This is the boring file where the holes live. The rules themselves are three
lines in `config/access.py`; what needs proving is that every endpoint is
actually wired to them, and that the two refusals stay distinct:

* another school → **404**, the object is not in the queryset and a stranger
  must not learn it exists;
* own school, no role → **403** with a code, the object is right there and
  the person simply may not change it.
"""

from datetime import date

from calendars.models import DayException, SchoolYear, Term
from django.urls import reverse
from plans.models import PlanNode
from rest_framework.test import APITestCase
from schedule.models import Course, LessonSlot

from .models import Invitation, School
from .testing import SchoolTestMixin, make_user

YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)
MONDAY = date(2026, 9, 7)


class AccessTestCase(SchoolTestMixin, APITestCase):
    """One school with everything in it, plus the same shape next door."""

    def setUp(self):
        super().setUp()

        self.year = SchoolYear.objects.create(
            school=self.school, name="2026/2027",
            start_date=YEAR_START, end_date=YEAR_END,
        )
        self.course = Course.objects.create(
            school=self.school, year=self.year, name="9Б"
        )
        self.term = Term.objects.create(
            year=self.year, name="1 четверть",
            start_date=YEAR_START, end_date=date(2026, 10, 25),
        )
        self.exception = DayException.objects.create(
            year=self.year, start_date=date(2026, 11, 4), end_date=date(2026, 11, 4),
            kind="holiday", title="Праздник",
        )
        self.slot = LessonSlot.objects.create(
            year=self.year, teacher=self.user, course=self.course,
            date=MONDAY, lesson_number=1,
        )
        self.node = PlanNode.objects.create(
            teacher=self.user, course=self.course, position=0, title="Урок"
        )

        self.alien_year = SchoolYear.objects.create(
            school=self.alien_school, name="2026/2027",
            start_date=YEAR_START, end_date=YEAR_END,
        )
        self.alien_course = Course.objects.create(
            school=self.alien_school, year=self.alien_year, name="9А"
        )

    def assertCode(self, response, status, code=None):
        self.assertEqual(response.status_code, status, response.content)
        if code is not None:
            self.assertEqual(response.json().get("code"), code, response.content)


class SchoolObjectReadTests(AccessTestCase):
    """Rule 1: a school object is readable by everybody in that school."""

    URLS = ("schoolyear-list", "term-list", "dayexception-list", "course-list")

    def test_own_teacher_reads_everything(self):
        for name in self.URLS:
            with self.subTest(name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(len(response.json()), 1)

    def test_own_admin_reads_everything(self):
        self.sign_in(self.admin)

        for name in self.URLS:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_another_school_sees_only_its_own(self):
        """Not an error — their own list, with no trace of ours in it."""
        self.sign_in(self.stranger)
        ours = {
            "schoolyear-list": self.year.pk,
            "term-list": self.term.pk,
            "dayexception-list": self.exception.pk,
            "course-list": self.course.pk,
        }

        for name, hidden in ours.items():
            with self.subTest(name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200, response.content)
                self.assertNotIn(hidden, [item["id"] for item in response.json()])

    def test_another_schools_admin_cannot_open_our_object(self):
        self.sign_in(self.alien_admin)

        for name, obj in (
            ("schoolyear-detail", self.year),
            ("term-detail", self.term),
            ("dayexception-detail", self.exception),
            ("course-detail", self.course),
        ):
            with self.subTest(name):
                url = reverse(name, args=[obj.pk])
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.delete(url).status_code, 404)

    def test_user_without_a_school_is_told_why(self):
        self.sign_in(self.outsider)

        for name in self.URLS:
            with self.subTest(name):
                self.assertCode(self.client.get(reverse(name)), 403, "no_school")


class SchoolObjectWriteTests(AccessTestCase):
    """Rule 2: writing a school object needs the administrator role."""

    def payloads(self):
        return (
            (
                "schoolyear-list",
                "schoolyear-detail",
                self.year,
                {"name": "2027/2028", "start_date": "2027-09-01",
                 "end_date": "2028-05-31"},
                {"name": "переименован"},
            ),
            (
                "course-list",
                "course-detail",
                self.course,
                {"name": "10А", "year": self.year.pk},
                {"name": "9В"},
            ),
            (
                "term-list",
                "term-detail",
                self.term,
                {"year": self.year.pk, "name": "2 четверть",
                 "start_date": "2026-11-05", "end_date": "2026-12-27"},
                {"name": "2 четверть"},
            ),
            (
                "dayexception-list",
                "dayexception-detail",
                self.exception,
                {"year": self.year.pk, "start_date": "2026-12-01",
                 "end_date": "2026-12-02", "kind": "vacation", "title": "Каникулы"},
                {"title": "Другое название"},
            ),
        )

    def test_teacher_of_the_same_school_may_not_write(self):
        for create_url, detail_url, obj, create, patch in self.payloads():
            with self.subTest(create_url):
                self.assertCode(
                    self.client.post(reverse(create_url), create, format="json"),
                    403,
                    "school_admin_required",
                )
                self.assertCode(
                    self.client.patch(
                        reverse(detail_url, args=[obj.pk]), patch, format="json"
                    ),
                    403,
                    "school_admin_required",
                )
                self.assertCode(
                    self.client.delete(reverse(detail_url, args=[obj.pk])),
                    403,
                    "school_admin_required",
                )

    def test_admin_of_the_same_school_may_write(self):
        self.sign_in(self.admin)

        for create_url, detail_url, obj, create, patch in self.payloads():
            with self.subTest(create_url):
                self.assertEqual(
                    self.client.post(reverse(create_url), create, format="json").status_code,
                    201,
                )
                self.assertEqual(
                    self.client.patch(
                        reverse(detail_url, args=[obj.pk]), patch, format="json"
                    ).status_code,
                    200,
                )

    def test_admin_of_another_school_gets_a_404_not_a_403(self):
        """The role is real, the object is not theirs — it must not exist."""
        self.sign_in(self.alien_admin)

        for _, detail_url, obj, _, patch in self.payloads():
            with self.subTest(detail_url):
                self.assertEqual(
                    self.client.patch(
                        reverse(detail_url, args=[obj.pk]), patch, format="json"
                    ).status_code,
                    404,
                )

    def test_user_without_a_school_may_not_write(self):
        self.sign_in(self.outsider)

        for create_url, _, _, create, _ in self.payloads():
            with self.subTest(create_url):
                self.assertCode(
                    self.client.post(reverse(create_url), create, format="json"),
                    403,
                    "no_school",
                )

    def test_a_year_of_another_school_cannot_be_named_in_the_body(self):
        """The body is a second door: the field queryset closes it too."""
        self.sign_in(self.admin)

        response = self.client.post(
            reverse("course-list"),
            {"name": "Чужой", "year": self.alien_year.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("year", response.json())


class PersonalObjectTests(AccessTestCase):
    """Rule 3: lessons and plan rows belong to one teacher, role or no role."""

    def test_own_lessons_and_plan_are_visible(self):
        self.assertEqual(
            [item["id"] for item in self.client.get(reverse("lessonslot-list")).json()],
            [self.slot.pk],
        )
        tree = self.client.get(reverse("plannode-list"), {"course": self.course.pk})
        self.assertEqual(len(tree.json()["nodes"]), 1)

    def test_a_colleague_sees_nothing_of_mine_in_the_same_course(self):
        """The course is shared; what happens inside it is not."""
        self.sign_in(self.colleague)

        self.assertEqual(self.client.get(reverse("lessonslot-list")).json(), [])
        tree = self.client.get(reverse("plannode-list"), {"course": self.course.pk})
        self.assertEqual(tree.json()["nodes"], [])

    def test_a_colleague_cannot_open_or_change_my_lesson(self):
        self.sign_in(self.colleague)
        url = reverse("lessonslot-detail", args=[self.slot.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.patch(url, {"is_cancelled": True}, format="json").status_code,
            404,
        )
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(LessonSlot.objects.filter(pk=self.slot.pk).exists())

    def test_an_administrator_has_no_power_over_my_lessons(self):
        """The role governs the school's shared objects, not people's work."""
        self.sign_in(self.admin)
        url = reverse("lessonslot-detail", args=[self.slot.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(LessonSlot.objects.filter(pk=self.slot.pk).exists())

    def test_an_administrator_has_no_power_over_my_plan(self):
        self.sign_in(self.admin)
        url = reverse("plannode-detail", args=[self.node.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.patch(url, {"title": "Правка"}, format="json").status_code, 404
        )
        self.assertTrue(PlanNode.objects.filter(pk=self.node.pk).exists())

    def test_another_school_cannot_reach_my_lesson(self):
        self.sign_in(self.stranger)

        self.assertEqual(
            self.client.get(reverse("lessonslot-detail", args=[self.slot.pk])).status_code,
            404,
        )

    def test_lessons_cannot_be_put_into_another_schools_course(self):
        response = self.client.post(
            reverse("lessonslot-list"),
            {"course": self.alien_course.pk, "date": MONDAY, "lesson_number": 3},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("course", response.json())

    def test_a_plan_cannot_be_written_into_another_schools_course(self):
        response = self.client.post(
            reverse("plannode-list"),
            {"course": self.alien_course.pk, "title": "Чужой"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_a_plan_of_another_schools_course_is_not_found(self):
        response = self.client.get(
            reverse("plannode-list"), {"course": self.alien_course.pk}
        )

        self.assertEqual(response.status_code, 404)

    def test_user_without_a_school_reaches_nothing(self):
        self.sign_in(self.outsider)

        self.assertCode(self.client.get(reverse("lessonslot-list")), 403, "no_school")
        self.assertCode(
            self.client.get(reverse("plannode-list"), {"course": self.course.pk}),
            403,
            "no_school",
        )

    def test_two_teachers_keep_separate_schedules_in_one_course(self):
        """The same number on the same day, two people — both are fine."""
        self.sign_in(self.colleague)

        response = self.client.post(
            reverse("lessonslot-list"),
            {"course": self.course.pk, "date": MONDAY, "lesson_number": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            LessonSlot.objects.filter(course=self.course, date=MONDAY).count(), 2
        )


class CourseDeletionTests(AccessTestCase):
    """A course somebody teaches is held by PROTECT, and says by whom."""

    def test_a_course_with_a_colleagues_lessons_cannot_be_deleted(self):
        self.sign_in(self.admin)

        response = self.client.delete(reverse("course-detail", args=[self.course.pk]))

        self.assertCode(response, 400, "course_in_use")
        self.assertEqual(response.json()["params"]["slots"], 1)
        self.assertEqual(response.json()["params"]["plan_rows"], 1)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())

    def test_an_empty_course_goes_away(self):
        self.sign_in(self.admin)
        spare = Course.objects.create(
            school=self.school, year=self.year, name="Пустой"
        )

        response = self.client.delete(reverse("course-detail", args=[spare.pk]))

        self.assertEqual(response.status_code, 204, response.content)


class MembersAndInvitationsTests(AccessTestCase):
    """The people of the school: who sees the list and who edits it."""

    def test_every_member_sees_the_people(self):
        response = self.client.get(reverse("member-list"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            sorted(item["email"] for item in response.json()),
            ["admin@example.com", "colleague@example.com", "teacher@example.com"],
        )

    def test_the_list_stops_at_the_school_border(self):
        self.sign_in(self.stranger)

        emails = [item["email"] for item in self.client.get(reverse("member-list")).json()]

        self.assertEqual(sorted(emails), ["alien-admin@example.com", "stranger@example.com"])

    def test_a_teacher_cannot_hand_out_the_role(self):
        response = self.client.patch(
            reverse("member-detail", args=[self.colleague.pk]),
            {"is_school_admin": True},
            format="json",
        )

        self.assertCode(response, 403, "school_admin_required")
        self.colleague.refresh_from_db()
        self.assertFalse(self.colleague.is_school_admin)

    def test_an_admin_hands_out_the_role(self):
        self.sign_in(self.admin)

        response = self.client.patch(
            reverse("member-detail", args=[self.colleague.pk]),
            {"is_school_admin": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.colleague.refresh_from_db()
        self.assertTrue(self.colleague.is_school_admin)

    def test_the_last_administrator_cannot_step_down(self):
        """A school with no admin could never be repaired from the interface."""
        self.sign_in(self.admin)

        response = self.client.patch(
            reverse("member-detail", args=[self.admin.pk]),
            {"is_school_admin": False},
            format="json",
        )

        self.assertCode(response, 400, "last_admin")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_school_admin)

    def test_a_second_administrator_may_step_down(self):
        self.sign_in(self.admin)
        self.colleague.is_school_admin = True
        self.colleague.save(update_fields=["is_school_admin"])

        response = self.client.patch(
            reverse("member-detail", args=[self.colleague.pk]),
            {"is_school_admin": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_another_schools_admin_cannot_touch_our_people(self):
        self.sign_in(self.alien_admin)

        response = self.client.patch(
            reverse("member-detail", args=[self.user.pk]),
            {"is_school_admin": True},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_school_admin)

    def test_invitations_are_invisible_to_a_plain_teacher(self):
        self.assertCode(
            self.client.get(reverse("invitation-list")), 403, "school_admin_required"
        )
        self.assertCode(
            self.client.post(
                reverse("invitation-list"), {"email": "new@example.com"}, format="json"
            ),
            403,
            "school_admin_required",
        )

    def test_an_admin_invites(self):
        self.sign_in(self.admin)

        response = self.client.post(
            reverse("invitation-list"),
            {"email": "New.Teacher@example.com", "is_school_admin": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        invitation = Invitation.objects.get()
        # stored lowercase: Google reports the address that way
        self.assertEqual(invitation.email, "new.teacher@example.com")
        self.assertEqual(invitation.school, self.school)
        self.assertEqual(invitation.created_by, self.admin)

    def test_the_same_address_is_not_invited_twice(self):
        self.sign_in(self.admin)
        self.client.post(
            reverse("invitation-list"), {"email": "new@example.com"}, format="json"
        )

        response = self.client.post(
            reverse("invitation-list"), {"email": "new@example.com"}, format="json"
        )

        self.assertCode(response, 400, "invitation_exists")

    def test_somebody_already_in_a_school_is_not_invited(self):
        self.sign_in(self.admin)

        response = self.client.post(
            reverse("invitation-list"),
            {"email": self.stranger.email},
            format="json",
        )

        self.assertCode(response, 400, "already_member")

    def test_invitations_of_another_school_are_not_listed(self):
        Invitation.objects.create(
            school=self.alien_school, email="somebody@example.com"
        )
        self.sign_in(self.admin)

        self.assertEqual(self.client.get(reverse("invitation-list")).json(), [])

    def test_an_admin_renames_their_school(self):
        self.sign_in(self.admin)

        response = self.client.patch(
            reverse("my-school"), {"name": "Гимназия №2"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Гимназия №2")

    def test_a_teacher_cannot_rename_the_school(self):
        response = self.client.patch(
            reverse("my-school"), {"name": "Моя школа"}, format="json"
        )

        self.assertCode(response, 403, "school_admin_required")
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Test school")

    def test_a_blank_name_is_refused(self):
        """DRF trims and refuses it as a plain field error — no code needed."""
        self.sign_in(self.admin)

        response = self.client.patch(
            reverse("my-school"), {"name": "   "}, format="json"
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("name", response.json())

    def test_my_school_is_reported(self):
        response = self.client.get(reverse("my-school"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "Test school")

    def test_a_user_without_a_school_gets_the_code(self):
        self.sign_in(self.outsider)

        self.assertCode(self.client.get(reverse("my-school")), 403, "no_school")


class SuperuserSchoolTests(AccessTestCase):
    """
    The list of all schools: the one place `is_superuser` counts in the app.

    Everywhere else a superuser is a plain member of their own school, and
    these tests are what keeps that true.
    """

    def setUp(self):
        super().setUp()
        self.root = make_user(self.school, "root@example.com")
        self.root.is_superuser = True
        self.root.is_staff = True
        self.root.save(update_fields=["is_superuser", "is_staff"])

    def test_a_superuser_sees_every_school(self):
        self.sign_in(self.root)

        response = self.client.get(reverse("school-list"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            sorted(item["name"] for item in response.json()),
            ["Another school", "Test school"],
        )

    def test_the_list_carries_who_runs_each_school(self):
        self.sign_in(self.root)

        rows = {item["name"]: item for item in self.client.get(reverse("school-list")).json()}

        self.assertEqual(rows["Test school"]["admins"], ["admin@example.com"])
        self.assertEqual(rows["Test school"]["members"], 4)

    def test_a_school_admin_is_not_a_superuser(self):
        """The role runs a school; it does not create them."""
        self.sign_in(self.admin)

        self.assertCode(
            self.client.get(reverse("school-list")), 403, "superuser_required"
        )
        self.assertCode(
            self.client.post(reverse("school-list"), {"name": "Своя"}, format="json"),
            403,
            "superuser_required",
        )

    def test_a_teacher_is_not_a_superuser(self):
        self.assertCode(
            self.client.get(reverse("school-list")), 403, "superuser_required"
        )

    def test_a_superuser_creates_a_school(self):
        self.sign_in(self.root)

        response = self.client.post(
            reverse("school-list"), {"name": "Гимназия №3"}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(School.objects.filter(name="Гимназия №3").exists())

    def test_a_superuser_renames_any_school(self):
        self.sign_in(self.root)

        response = self.client.patch(
            reverse("school-detail", args=[self.alien_school.pk]),
            {"name": "Переименована"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.alien_school.refresh_from_db()
        self.assertEqual(self.alien_school.name, "Переименована")

    def test_a_school_with_members_is_not_deleted(self):
        self.sign_in(self.root)

        response = self.client.delete(
            reverse("school-detail", args=[self.alien_school.pk])
        )

        self.assertCode(response, 400, "school_in_use")
        self.assertEqual(response.json()["params"]["members"], 2)
        self.assertTrue(School.objects.filter(pk=self.alien_school.pk).exists())

    def test_an_empty_school_is_deleted(self):
        self.sign_in(self.root)
        spare = School.objects.create(name="Пустая")

        response = self.client.delete(reverse("school-detail", args=[spare.pk]))

        self.assertEqual(response.status_code, 204, response.content)

    def test_a_superuser_invites_the_first_administrator(self):
        self.sign_in(self.root)
        spare = School.objects.create(name="Новая")

        response = self.client.post(
            reverse("school-invite", args=[spare.pk]),
            {"email": "Head@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        invitation = Invitation.objects.get(school=spare)
        self.assertEqual(invitation.email, "head@example.com")
        self.assertTrue(invitation.is_school_admin)
        self.assertEqual(invitation.created_by, self.root)

    def test_inviting_somebody_who_already_has_a_school_is_refused(self):
        self.sign_in(self.root)
        spare = School.objects.create(name="Новая")

        response = self.client.post(
            reverse("school-invite", args=[spare.pk]),
            {"email": self.user.email},
            format="json",
        )

        self.assertCode(response, 400, "already_member")

    def test_a_superuser_has_no_extra_power_over_lessons(self):
        """Creating schools is not the same as owning what happens in them."""
        self.sign_in(self.root)

        url = reverse("lessonslot-detail", args=[self.slot.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_a_superuser_without_the_school_role_still_cannot_write_courses(self):
        self.sign_in(self.root)

        response = self.client.post(
            reverse("course-list"),
            {"name": "Курс суперюзера", "year": self.year.pk},
            format="json",
        )

        self.assertCode(response, 403, "school_admin_required")
