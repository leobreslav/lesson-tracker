"""
Joining a school through an invitation.

The signature check is mocked away — what these tests care about is which
address the decision is made on, and what happens when it matches nothing.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Invitation, School
from .testing import make_school, make_user

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
