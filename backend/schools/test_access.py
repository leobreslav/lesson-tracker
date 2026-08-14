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
from django.utils import timezone
from plans.models import PlanBaseline, PlanNode
from rest_framework.test import APITestCase
from schedule.models import Course, LessonSlot

from .matrix import AccessRulesMixin
from .models import Invitation, School
from .services import enrol as enrol_student
from .testing import (
    assign,
    MONDAY,
    YEAR_START,
    SchoolTestMixin,
    make_attachment,
    make_course,
    make_exception,
    make_master_slot,
    make_node,
    make_slot,
    make_template,
    make_term,
    make_year,
)


class AccessTestCase(AccessRulesMixin, SchoolTestMixin, APITestCase):
    """One school with everything in it, plus the same shape next door."""

    def setUp(self):
        super().setUp()

        self.year = make_year(self.school)
        self.course = make_course(self.school, self.year)
        assign(self.user, self.course)
        self.term = make_term(self.year)
        self.exception = make_exception(self.year)
        self.slot = make_slot(self.user, self.course)
        self.node = make_node(self.user, self.course)
        self.master_slot = make_master_slot(self.course, self.user, number=2)

        self.alien_year = make_year(self.alien_school)
        self.alien_course = make_course(self.alien_school, self.alien_year, "9А")

    def assertCode(self, response, status, code=None):
        self.assertEqual(response.status_code, status, response.content)
        if code is not None:
            self.assertEqual(response.json().get("code"), code, response.content)


class MatrixTests(AccessTestCase):
    """
    The whole matrix, one call per model.

    A model added later needs five lines here — and if these lines are
    missing, that is the only thing left to notice, which is what
    `test_wiring.py` watches for.
    """

    def test_school_year(self):
        self.assertSchoolObjectRules(
            list_url="schoolyear-list",
            detail_url="schoolyear-detail",
            obj=self.year,
            create={
                "name": "2027/2028",
                "start_date": "2027-09-01",
                "end_date": "2028-05-31",
            },
            patch={"name": "переименован"},
            # три действия читают год по id из пути, каждое своим кодом
            actions=("schoolyear-usage", "schoolyear-days", "schoolyear-stats"),
        )

    def test_course(self):
        self.assertSchoolObjectRules(
            list_url="course-list",
            detail_url="course-detail",
            obj=self.course,
            create={"name": "10А", "year": self.year.pk},
            patch={"name": "9В"},
            # всё, что берёт курс параметром: план, раскладка, эталон,
            # выгрузка, импорт и счётчики расписания. Курс школьный, поэтому
            # спрашивают чужие; свой коллега тут видит **свой** план в общем
            # курсе, и это правильно
            actions=(
                ("plannode-list", "course"),
                ("plannode-layout", "course"),
                ("plannode-layout-slots", "course"),
                ("plannode-layout-summary", "course"),
                ("plannode-baseline", "course"),
                ("plannode-export", "course"),
                ("plannode-export-xlsx", "course"),
                ("lessonslot-list", "course"),
                ("lessonslot-stats", "course"),
                {"name": "plannode-baseline-submit", "param": "course", "method": "post"},
                {"name": "plannode-import", "param": "course", "method": "post"},
                {"name": "plannode-import-xlsx", "param": "course", "method": "post"},
                {"name": "plannode-import-preview", "param": "course", "method": "post"},
                {
                    "name": "plannode-import-preview-xlsx",
                    "param": "course",
                    "method": "post",
                },
                {"name": "lessonslot-bulk", "param": "course", "method": "delete"},
                {"name": "plantemplate-from-plan", "param": "course", "method": "post"},
                {
                    "name": "plan-import-from-template",
                    "param": "course",
                    "method": "post",
                },
            ),
        )

    def test_term(self):
        self.assertSchoolObjectRules(
            list_url="term-list",
            detail_url="term-detail",
            obj=self.term,
            create={
                "year": self.year.pk,
                "name": "2 четверть",
                "start_date": "2026-11-05",
                "end_date": "2026-12-27",
            },
            patch={"name": "2 четверть"},
        )

    def test_calendar_exception(self):
        self.assertSchoolObjectRules(
            list_url="dayexception-list",
            detail_url="dayexception-detail",
            obj=self.exception,
            create={
                "year": self.year.pk,
                "start_date": "2026-12-01",
                "end_date": "2026-12-02",
                "kind": "vacation",
                "title": "Каникулы",
            },
            patch={"title": "Другое название"},
        )

    def test_master_slot(self):
        self.assertSchoolObjectRules(
            list_url="masterslot-list",
            detail_url="masterslot-detail",
            obj=self.master_slot,
            create={
                "year": self.year.pk,
                "course": self.course.pk,
                "teacher": self.user.pk,
                "date": "2026-09-08",
                "lesson_number": 4,
            },
            patch={"lesson_number": 6},
            actions=(
                ("masterslot-list", "course"),
                ("masterslot-summary", "year"),
                {"name": "masterslot-bulk", "param": "course", "method": "delete"},
                {"name": "import-preview", "param": "year", "method": "get"},
            ),
        )

    def test_course_student(self):
        student_row = enrol_student(self.student, self.course, by=self.admin)

        self.assertSchoolObjectRules(
            list_url="coursestudent-list",
            detail_url="coursestudent-detail",
            obj=student_row,
            create={"course": self.course.pk, "student": self.student.pk},
            # состав курса не правят частично: зачислили или сняли
            patch={},
            # массовый ввод берёт курс из query-строки и ходит в базу своим
            # кодом: чужой курс не должен отличаться от несуществующего ни
            # у предпросмотра, ни у самой вставки
            actions=(
                {
                    "name": "coursestudent-preview",
                    "param": "course",
                    "method": "post",
                    "body": {"text": "someone@example.com"},
                },
                {
                    "name": "coursestudent-enrol",
                    "param": "course",
                    "method": "post",
                    "body": {"text": "someone@example.com"},
                },
            ),
        )

    def test_lesson_slot(self):
        self.assertPersonalObjectRules(
            list_url="lessonslot-list",
            detail_url="lessonslot-detail",
            obj=self.slot,
            patch={"is_cancelled": True},
        )

    def test_plan_node(self):
        self.assertPersonalObjectRules(
            list_url="lessonslot-list",
            detail_url="plannode-detail",
            obj=self.node,
            patch={"title": "Правка"},
            # перемещение берёт узел по id из пути: строка плана личная, и
            # чужой узел не должен отличаться от несуществующего даже для
            # коллеги по тому же курсу
            actions=(
                {"name": "plannode-move", "method": "post", "body": {"direction": "up"}},
                {
                    "name": "plannode-move-to",
                    "method": "post",
                    "body": {"parent": None, "position": 0},
                },
                {
                    "name": "plansection-move",
                    "method": "post",
                    "body": {"direction": "up"},
                },
            ),
        )


class ForeignKeyDoorTests(AccessTestCase):
    """
    The body of a request is a second door into the same room.

    The viewset filters what you can reach by URL; these check that naming
    somebody else's object in a foreign key does not get you there either.
    """

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

    def test_an_administrator_has_no_power_over_my_lessons(self):
        """The role governs the school's shared objects, not people's work."""
        self.sign_in(self.admin)
        url = reverse("lessonslot-detail", args=[self.slot.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(LessonSlot.objects.filter(pk=self.slot.pk).exists())

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

    def test_two_teachers_keep_separate_schedules_in_one_course(self):
        """The same number on the same day, two people — both are fine."""
        # one course, two teachers on it: that is what an assignment allows
        assign(self.colleague, self.course)
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

    def test_the_list_is_teachers_unless_students_are_asked_for(self):
        """
        Два списка одним адресом: без параметра — сотрудники.

        Ученик тоже в школе, и если бы он попадал в список участников,
        администратор выдал бы ему роль или поставил вести урок.
        """
        enrol_student(self.student, self.course, by=self.admin)

        staff = self.client.get(reverse("member-list")).json()
        students = self.client.get(reverse("member-list"), {"kind": "student"}).json()

        self.assertNotIn(self.student.email, [item["email"] for item in staff])
        self.assertEqual([item["email"] for item in students], [self.student.email])
        self.assertEqual(
            [course["name"] for course in students[0]["courses"]], [self.course.name]
        )

    def test_a_student_cannot_be_made_an_administrator(self):
        self.sign_in(self.admin)

        self.assertCode(
            self.client.patch(
                reverse("member-detail", args=[self.student.pk]),
                {"is_school_admin": True},
                format="json",
            ),
            400,
            "not_a_student",
        )

    def test_detaching_a_student_is_refused_first_and_then_confirmed(self):
        """
        Ошиблись адресом при вставке — исправить это надо чем-то.

        Отвязка устроена как у учителя: сперва отказ со счётчиком, потом
        `force`. Зачисления снимаются вместе со школой, но строки остаются:
        они и есть след того, что человек здесь учился.
        """
        row = enrol_student(self.student, self.course, by=self.admin)
        self.sign_in(self.admin)
        url = reverse("member-detail", args=[self.student.pk])

        refused = self.client.delete(url)
        self.assertCode(refused, 400, "member_in_use")
        self.assertEqual(refused.json()["params"]["courses"], 1)

        self.assertEqual(self.client.delete(f"{url}?force=true").status_code, 204)

        self.student.refresh_from_db()
        row.refresh_from_db()
        self.assertIsNone(self.student.school)
        self.assertIsNotNone(row.removed_at)

    def test_a_detached_student_does_not_see_the_old_school(self):
        enrol_student(self.student, self.course, by=self.admin)
        self.student.school = None
        self.student.save(update_fields=["school"])
        self.sign_in(self.student)

        self.assertCode(
            self.client.get(reverse("student-courses")), 403, "no_school"
        )

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
        self.root = self.make_root()

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
        # считаются все привязанные к школе, ученики в том числе: это число
        # отвечает на вопрос «кто мешает удалить школу», а мешают все
        self.assertEqual(rows["Test school"]["members"], 5)

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


class StudentTests(AccessTestCase):
    """
    Второй вид пользователя: в школе состоит, учителем не является.

    Матрица проверяет каждую модель по отдельности; здесь то, что мимо неё:
    что именно ученику всё-таки можно и что вид не переписывается сам.
    """

    def test_the_profile_stays_open(self):
        """`/api/me/` нужна ученику ровно так же: имя, язык, выход."""
        self.sign_in(self.student)

        response = self.client.get(reverse("me"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["email"], self.student.email)

    def test_the_language_is_still_theirs_to_change(self):
        self.sign_in(self.student)

        response = self.client.patch(reverse("me"), {"language": "ru"}, format="json")

        self.assertEqual(response.status_code, 200, response.content)
        self.student.refresh_from_db()
        self.assertEqual(self.student.language, "ru")

    def test_the_kind_is_not_editable_from_the_profile(self):
        """Вид назначается приглашением, а не заявляется о себе в профиле."""
        self.sign_in(self.student)

        self.client.patch(reverse("me"), {"kind": "teacher"}, format="json")

        self.student.refresh_from_db()
        self.assertTrue(self.student.is_student)

    def test_the_first_steps_are_not_theirs(self):
        """У ученика другая главная, и считать шаги первого входа ему нечего."""
        self.sign_in(self.student)

        self.assertCode(self.client.get(reverse("onboarding-status")), 403, "teachers_only")

    def test_a_teacher_without_a_school_still_gets_the_steps(self):
        """
        Права `IsTeacher` и `IsSchoolMember` разведены нарочно: школы может
        ещё не быть, и это состояние объясняет ответ, а не отказ.
        """
        self.sign_in(self.outsider)

        response = self.client.get(reverse("onboarding-status"))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["school"])

    def test_a_student_is_not_a_school_member_in_the_lists(self):
        """
        «Люди школы» перестало значить «учителя», и все такие места сужены.

        Иначе ученик попал бы и в список участников, и в выбор «кто ведёт
        урок» школьного расписания.
        """
        self.sign_in(self.admin)

        members = self.client.get(reverse("member-list")).json()
        self.assertNotIn(
            self.student.pk, [item["id"] for item in members]
        )

        overview = self.client.get(reverse("school-overview")).json()
        self.assertEqual(overview["teachers"], len(members))

    def test_a_student_cannot_be_named_as_the_teacher_of_a_lesson(self):
        self.sign_in(self.admin)

        response = self.client.post(
            reverse("masterslot-list"),
            {
                "year": self.year.pk,
                "course": self.course.pk,
                "teacher": self.student.pk,
                "date": str(MONDAY),
                "lesson_number": 5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)


class ActionDoorTests(AccessTestCase):
    """
    Действия вьюсетов, у которых нет своей строки в матрице.

    Матрица заводится на модель, а часть `@action` висит на объектах, чьи
    правила описаны отдельно: вложение отвечает «не ваше» внутри школы,
    запрос на утверждение виден только методисту курса, шаблон — только
    своей школе. Правило неотличимости у всех одно, и проверяется оно тем же
    помощником.

    Сторож поверх роутеров (`test_wiring.py`) сюда не дотягивается: он
    смотрит на класс вьюхи, а действие внутри ходит в модели своим кодом.
    """

    def test_attachment_download(self):
        """
        Скачивание — единственное место, где ссылку подписывают.

        Внутри школы вложение честно отвечает «не ваше» (это отступление
        описано в разделе про доступ), поэтому спрашивают только чужие: для
        них урока коллеги не существует.
        """
        attachment = make_attachment(self.node)

        self.assertActionRules(
            actions=("attachment-download",),
            obj=attachment,
            people=(self.stranger, self.alien_admin),
        )

    def test_plan_review(self):
        """Утвердить и вернуть может только методист курса — остальным 404."""
        baseline = PlanBaseline.objects.create(
            teacher=self.user,
            course=self.course,
            status=PlanBaseline.Status.PENDING,
            submitted_at=timezone.now(),
        )

        self.assertActionRules(
            actions=(
                {"name": "planreview-approve", "method": "post"},
                {
                    "name": "planreview-return",
                    "method": "post",
                    "body": {"comment": "нет"},
                },
            ),
            obj=baseline,
            # ни коллега, ни администратор школы методистом не назначены:
            # роль висит на паре «курс и человек», а не на должности
            people=(self.colleague, self.admin, self.stranger, self.alien_admin),
        )

    def test_plan_template(self):
        """Шаблон школьный: чужая школа не должна отличать его от пустого id."""
        template = make_template(self.school, self.user)

        self.assertActionRules(
            actions=(
                {"name": "plantemplate-update-from-plan", "method": "post"},
                {"name": "plantemplate-rows", "method": "put", "body": {"rows": []}},
            ),
            obj=template,
            people=(self.stranger, self.alien_admin),
        )

    def test_school_invite(self):
        """Приглашение первого администратора — только суперпользователю."""
        self.assertActionRules(
            actions=(
                {
                    "name": "school-invite",
                    "method": "post",
                    "body": {"email": "new@example.com"},
                },
            ),
            obj=self.school,
            people=(self.user, self.admin, self.stranger, self.alien_admin),
        )

    def test_copying_takes_the_course_from_the_body(self):
        """
        У копирования id курса едет в теле, а не в пути.

        Проверять это тем же правилом стоит именно потому, что тело мимо
        queryset'а вьюхи проходит: ограничивает его сериализатор, и забыть
        там ограничение так же легко, как и во вьюхе.
        """
        period = {
            "source_start": "2026-09-07",
            "source_end": "2026-09-13",
            "target_start": "2026-09-14",
            "target_end": "2026-09-20",
        }

        for name, field in (("lessonslot-copy", "course_id"), ("masterslot-copy", "course")):
            for person in (self.stranger, self.alien_admin):
                with self.subTest(f"{name} для {person.email}"):
                    self.sign_in(person)
                    ours = self.client.post(
                        reverse(name), {**period, field: self.course.pk}, format="json"
                    )
                    unknown = self.client.post(
                        reverse(name), {**period, field: 10**9}, format="json"
                    )

                    self.assertEqual(
                        (ours.status_code, self.without_id(ours, self.course.pk)),
                        (unknown.status_code, self.without_id(unknown, 10**9)),
                        f"{name} выдаёт существование курса: {ours.content}",
                    )
