"""
Joining a school through an invitation.

The signature check is mocked away — what these tests care about is which
address the decision is made on, and what happens when it matches nothing.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from schedule.models import Course, CourseAssignment

from . import services
from .models import Invitation, School
from .testing import make_course, make_school, make_user, make_year

User = get_user_model()

GOOGLE_CLAIMS = {
    "iss": "https://accounts.google.com",
    "sub": "1234567890",
    "email": "newcomer@example.com",
    "email_verified": True,
    "given_name": "Мария",
    "family_name": "Иванова",
}


def google_login(claims=None):
    """Sign in through Google with the signature check stubbed out."""
    target = "allauth.socialaccount.providers.google.views._verify_and_decode"
    with patch(target, return_value={**GOOGLE_CLAIMS, **(claims or {})}):
        return Client().post(
            reverse("google_login"),
            {"id_token": "fake"},
            content_type="application/json",
        )


class InvitationAcceptanceTests(TestCase):
    def setUp(self):
        self.school = make_school("Test school")
        self.admin = make_user(self.school, "admin@example.com", admin=True)

    def invite(self, email, **extra):
        return Invitation.objects.create(
            school=self.school, email=email, created_by=self.admin, **extra
        )

    def test_an_invited_newcomer_joins_the_school(self):
        invitation = self.invite("newcomer@example.com")

        response = google_login()

        self.assertEqual(response.status_code, 200, response.content)
        user = User.objects.get(email="newcomer@example.com")
        self.assertEqual(user.school, self.school)
        self.assertFalse(user.is_school_admin)

        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)

    def test_the_invitation_can_grant_the_admin_role(self):
        self.invite("newcomer@example.com", is_school_admin=True)

        google_login()

        self.assertTrue(User.objects.get(email="newcomer@example.com").is_school_admin)

    def test_the_address_is_matched_case_insensitively(self):
        """An administrator types it by hand; Google reports it lowercase."""
        self.invite("NewComer@Example.com")

        google_login()

        self.assertEqual(
            User.objects.get(email="newcomer@example.com").school, self.school
        )

    def test_an_uninvited_person_signs_in_with_no_school(self):
        """A valid state, not an error: the interface asks them to wait."""
        response = google_login()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(User.objects.get(email="newcomer@example.com").school)

    def test_an_unverified_address_never_joins(self):
        """
        The invitation is an authorisation, so only Google's word counts.

        An unverified address is refused at the door anyway, but this is the
        test that keeps it that way: without the check, writing somebody
        else's address into a profile would be enough to walk in.
        """
        self.invite("newcomer@example.com")

        response = google_login({"email_verified": False})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(User.objects.filter(email="newcomer@example.com").exists())
        self.assertIsNone(Invitation.objects.get().accepted_at)

    def test_an_invitation_is_used_once(self):
        self.invite("newcomer@example.com")
        google_login()

        # a second sign-in must not re-stamp or move anybody
        first_accepted = Invitation.objects.get().accepted_at
        google_login()

        self.assertEqual(Invitation.objects.get().accepted_at, first_accepted)
        self.assertEqual(User.objects.filter(email="newcomer@example.com").count(), 1)

    def test_somebody_already_in_a_school_is_not_moved(self):
        """
        A late invitation from elsewhere must not carry a teacher away.

        Their whole schedule hangs off their school; changing it silently on
        a sign-in would leave them staring at somebody else's calendar.
        """
        other_school = make_school("Another school")
        user = make_user(other_school, "newcomer@example.com")
        Invitation.objects.create(school=self.school, email=user.email)

        google_login()

        user.refresh_from_db()
        self.assertEqual(user.school, other_school)

    def test_an_invitation_written_after_a_failed_attempt_still_works(self):
        """The usual order: the person tries first, the admin invites after."""
        google_login()
        self.assertIsNone(User.objects.get(email="newcomer@example.com").school)

        self.invite("newcomer@example.com")
        google_login()

        self.assertEqual(
            User.objects.get(email="newcomer@example.com").school, self.school
        )


class StudentEnrolmentTests(TestCase):
    """
    Ученик приходит по приглашению и попадает в названные курсы.

    Ключевое правило подсистемы: **приглашение расходуется однажды**. Если бы
    оно доносило курсы при каждом входе, снятый с курса возвращался бы туда
    сам, стоило ему войти, — и администратор не смог бы никого отчислить.
    """

    def setUp(self):
        self.school = make_school("Test school")
        self.admin = make_user(self.school, "admin@example.com", admin=True)
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "9Б Алгебра")
        self.geometry = make_course(self.school, self.year, "9Б Геометрия")

    def invite_student(self, email="newcomer@example.com", courses=()):
        """
        Пригласить ученика — то есть завести его и записать на курсы.

        Раньше приглашение было записанным адресом, а зачисление ждало
        первого входа. Теперь учётка появляется сразу, и «записать на курс»
        — обычное действие администратора, а не обещание на будущее.
        """
        invitation = Invitation.objects.create(
            school=self.school, email=email, kind="student", created_by=self.admin
        )
        # ярлык, которым администратор назвал человека при вводе: имя
        # учётки приезжает из Google и должно его вытеснить
        person = services.provision(
            self.school, email, kind="student", name="Как-то Записали"
        )
        for course in courses:
            services.enrol(person, course, by=self.admin)
        return invitation

    def test_a_student_is_enrolled_before_ever_signing_in(self):
        """Учётка и зачисления есть до первого входа, а не появляются на нём."""
        self.invite_student(courses=[self.algebra, self.geometry])

        user = User.objects.get(email="newcomer@example.com")
        self.assertTrue(user.is_student)
        self.assertEqual(user.school, self.school)
        self.assertIsNone(user.last_login, "«ещё не входил» — это пустой last_login")
        self.assertEqual(
            sorted(row.course.name for row in user.enrolments.all()),
            ["9Б Алгебра", "9Б Геометрия"],
        )

    def test_signing_in_claims_that_very_account(self):
        """Вход не заводит вторую учётку, а забирает заготовленную."""
        self.invite_student(courses=[self.algebra])
        before = User.objects.get(email="newcomer@example.com")

        response = google_login()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(User.objects.filter(email="newcomer@example.com").count(), 1)
        after = User.objects.get(pk=before.pk)
        self.assertEqual(after.school, self.school)
        self.assertIsNotNone(after.last_login)
        # имя из Google вытесняет ярлык, которым администратор назвал
        # человека: обычный сигнал дополняет только пустые поля, поэтому
        # решение принимает `accept` — он один знает, что вход первый
        self.assertEqual(after.first_name, "Мария")
        self.assertEqual(after.last_name, "Иванова")

    def test_a_removed_student_does_not_come_back_by_signing_in(self):
        """
        То, ради чего приглашение расходуется однажды.

        Администратор снял ученика с курса; следующий вход не должен
        возвращать его обратно — иначе отчислить никого нельзя.
        """
        self.invite_student(courses=[self.algebra])
        google_login()
        user = User.objects.get(email="newcomer@example.com")
        services.remove_from_course(user.enrolments.get())

        google_login()

        row = user.enrolments.get()
        self.assertIsNotNone(row.removed_at)
        self.assertFalse(row.is_active)

    def test_returning_revives_the_same_row(self):
        """Пара «курс и ученик» одна навсегда: возврат не заводит вторую."""
        self.invite_student(courses=[self.algebra])
        google_login()
        user = User.objects.get(email="newcomer@example.com")
        row = user.enrolments.get()
        services.remove_from_course(row)

        services.enrol(user, self.algebra, by=self.admin)

        self.assertEqual(user.enrolments.count(), 1)
        self.assertIsNone(user.enrolments.get().removed_at)

    def test_a_teacher_invitation_does_not_make_a_student(self):
        Invitation.objects.create(
            school=self.school, email="newcomer@example.com", created_by=self.admin
        )

        google_login()

        self.assertFalse(User.objects.get(email="newcomer@example.com").is_student)

    def test_the_kind_is_set_once_and_never_flips(self):
        """
        Один адрес — один вид учётки.

        Приглашение уже пришедшего человека вторым видом не срабатывает: он
        в школе, а второе приглашение никого не переносит.
        """
        self.invite_student(courses=[self.algebra])
        google_login()
        user = User.objects.get(email="newcomer@example.com")

        Invitation.objects.create(
            school=make_school("Другая школа"),
            email=user.email,
            created_by=self.admin,
        )
        google_login()

        user.refresh_from_db()
        self.assertTrue(user.is_student)
        self.assertEqual(user.school, self.school)

    def test_only_the_active_courses_are_the_ones_to_work_in(self):
        """Два вопроса — два ответа, и оба даёт менеджер курсов."""
        self.invite_student(courses=[self.algebra, self.geometry])
        google_login()
        user = User.objects.get(email="newcomer@example.com")
        services.remove_from_course(user.enrolments.get(course=self.geometry))

        self.assertEqual(
            [course.name for course in Course.objects.for_student(user)],
            ["9Б Алгебра"],
        )
        self.assertEqual(
            sorted(
                course.name
                for course in Course.objects.for_student(user, active_only=False)
            ),
            ["9Б Алгебра", "9Б Геометрия"],
        )


class TeacherLoadTests(TestCase):
    """
    Курс поручают приглашённому — до того, как он впервые вошёл.

    Раньше поручить было нечего: `CourseAssignment` некуда поставить, пока
    нет учётки, и курс приходилось нести в самом приглашении до первого
    входа. Теперь учётка появляется в момент ввода адреса, и назначение —
    обычная строка обычной таблицы.
    """

    def setUp(self):
        self.school = make_school("Test school")
        self.admin = make_user(self.school, "admin@example.com", admin=True)
        self.year = make_year(self.school)
        self.algebra = make_course(self.school, self.year, "9Б Алгебра")
        self.geometry = make_course(self.school, self.year, "9Б Геометрия")

    def invite_teacher(self, email="newcomer@example.com", courses=()):
        Invitation.objects.create(
            school=self.school, email=email, kind="teacher", created_by=self.admin
        )
        person = services.provision(self.school, email, kind="teacher")
        for course in courses:
            CourseAssignment.objects.create(course=course, teacher=person)
        return person

    def test_the_courses_are_led_before_the_first_sign_in(self):
        person = self.invite_teacher(courses=[self.algebra, self.geometry])

        self.assertIsNone(person.last_login)
        self.assertEqual(
            sorted(item.course.name for item in person.course_assignments.all()),
            ["9Б Алгебра", "9Б Геометрия"],
        )

    def test_signing_in_claims_the_account_with_its_load(self):
        person = self.invite_teacher(courses=[self.algebra])

        response = google_login()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(User.objects.filter(email=person.email).count(), 1)
        person.refresh_from_db()
        self.assertIsNotNone(person.last_login)
        self.assertEqual(person.course_assignments.count(), 1)

    def test_a_teacher_invitation_does_not_make_a_student(self):
        self.invite_teacher()

        google_login()

        self.assertFalse(User.objects.get(email="newcomer@example.com").is_student)

    def test_the_invitation_is_stamped_once(self):
        """Билет расходуется однажды: второй вход ничего не переигрывает."""
        self.invite_teacher(courses=[self.algebra])
        google_login()
        invitation = Invitation.objects.get(email="newcomer@example.com")
        stamped = invitation.accepted_at
        self.assertIsNotNone(stamped)

        google_login()

        invitation.refresh_from_db()
        self.assertEqual(invitation.accepted_at, stamped)


class SchoolModelTests(TestCase):
    def test_str_is_the_name(self):
        self.assertEqual(str(School.objects.create(name="Школа №1")), "Школа №1")

    def test_invitation_str_names_both_sides(self):
        school = make_school("Школа №1")
        invitation = Invitation.objects.create(school=school, email="a@b.c")

        self.assertEqual(str(invitation), "a@b.c → Школа №1")

    def test_a_school_with_people_cannot_be_deleted_by_accident(self):
        """PROTECT on User.school: the calendar and courses would be orphaned."""
        from django.db.models import ProtectedError

        school = make_school()
        make_user(school, "somebody@example.com")

        with self.assertRaises(ProtectedError):
            school.delete()


class TestingHelpersTests(TestCase):
    """A guard for the shared fixture helper itself."""

    def test_make_user_without_a_school(self):
        user = make_user(None, "nobody@example.com")

        self.assertIsNone(user.school)
        self.assertFalse(user.is_school_admin)
