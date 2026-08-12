"""
`bootstrap` runs on the live database at every container start.

That is the whole reason these tests exist: the command has to be safe to
call again and again, on a database that already has people in it, with the
environment half-configured. A crash here means the backend container will
not start.
"""

from io import StringIO
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

User = get_user_model()

ENV = {
    "BOOTSTRAP_SUPERUSER_EMAIL": "root@example.com",
    "BOOTSTRAP_SUPERUSER_PASSWORD": "S3cret-pass-123",
}


def run(**env):
    """
    Run the command with a controlled environment, return its output.

    Anything not passed is blanked rather than inherited: a variable left
    over from the real environment would make the "not configured" tests
    pass for the wrong reason.
    """
    out = StringIO()
    environment = dict.fromkeys(ENV, "") | env

    with patch.dict("os.environ", environment, clear=False):
        call_command("bootstrap", stdout=out)
    return out.getvalue()


def run_without_env():
    out = StringIO()
    with patch.dict("os.environ", {}, clear=True):
        call_command("bootstrap", stdout=out)
    return out.getvalue()


class SuperuserTests(TestCase):
    def test_creates_the_first_superuser(self):
        output = run(**ENV)

        user = User.objects.get(email="root@example.com")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("S3cret-pass-123"))
        self.assertIn("создан суперпользователь", output)

    def test_the_new_superuser_can_sign_into_admin(self):
        """A password that cannot be used is the same as no superuser."""
        run(**ENV)

        self.assertTrue(
            self.client.login(username="root@example.com", password="S3cret-pass-123")
        )

    def test_an_existing_superuser_is_left_alone(self):
        existing = User.objects.create_superuser(
            email="already@example.com", password="Original-pass-1"
        )

        output = run(**ENV)

        existing.refresh_from_db()
        self.assertTrue(existing.check_password("Original-pass-1"))
        self.assertFalse(User.objects.filter(email="root@example.com").exists())
        self.assertIn("уже есть", output)

    def test_a_plain_account_with_that_address_is_promoted(self):
        """
        The usual order in practice: the person signs in through Google
        first, and only then gets named as the superuser.
        """
        user = User.objects.create_user(email="root@example.com")

        run(**ENV)

        user.refresh_from_db()
        self.assertTrue(user.is_superuser)
        self.assertEqual(User.objects.filter(email="root@example.com").count(), 1)

    def test_without_the_variables_it_warns_and_carries_on(self):
        """A container that refuses to start is worse than a missing account."""
        output = run_without_env()

        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        self.assertIn("не заданы", output)

    def test_a_half_configured_environment_is_also_a_skip(self):
        output = run(BOOTSTRAP_SUPERUSER_EMAIL="root@example.com")

        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        self.assertIn("не заданы", output)


class VerifiedEmailTests(TestCase):
    def test_the_superuser_gets_a_verified_address(self):
        """
        Otherwise allauth wipes their password on the first Google sign-in.

        We have walked into this once already, which is why it is a step of
        its own rather than a side effect somebody could remove.
        """
        run(**ENV)

        user = User.objects.get(email="root@example.com")
        self.assertTrue(
            EmailAddress.objects.filter(user=user, email=user.email, verified=True)
            .exists()
        )

    def test_an_account_that_lost_its_address_gets_it_back(self):
        user = User.objects.create_superuser(
            email="already@example.com", password="Original-pass-1"
        )
        EmailAddress.objects.filter(user=user).delete()

        output = run_without_env()

        self.assertTrue(EmailAddress.objects.filter(user=user, verified=True).exists())
        self.assertIn("подтверждён адрес", output)


class IdempotencyTests(TestCase):
    def snapshot(self):
        """Everything bootstrap could possibly have touched."""
        return {
            "users": sorted(
                User.objects.values_list("email", "is_superuser", "is_staff", "password")
            ),
            "emails": sorted(
                EmailAddress.objects.values_list("email", "verified", "primary")
            ),
        }

    def test_ten_runs_leave_what_one_run_left(self):
        run(**ENV)
        after_one = self.snapshot()

        for _ in range(9):
            run(**ENV)

        self.assertEqual(self.snapshot(), after_one)

    def test_the_second_run_reports_no_changes(self):
        run(**ENV)

        output = run(**ENV)

        self.assertIn("уже есть", output)
        self.assertIn("подтверждённые адреса на месте", output)
        self.assertNotIn("создан суперпользователь", output)

    def test_it_survives_an_empty_database(self):
        output = run_without_env()

        self.assertEqual(User.objects.count(), 0)
        self.assertIn("bootstrap:", output)
