"""
Fixtures every app's tests need: a school and the people inside it.

Since everything is scoped by school, almost every test starts the same way —
one school, one teacher, and usually a second person to prove they cannot see
the first one's work. Repeating that in each setUp invited copies that slowly
drifted apart, so it lives here.
"""

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from .models import School

User = get_user_model()


def make_school(name="Test school") -> School:
    return School.objects.create(name=name)


def make_user(school=None, email="teacher@example.com", *, admin=False):
    """A member of the school; `school=None` gives somebody nobody invited."""
    return User.objects.create_user(
        email=email, school=school, is_school_admin=admin
    )


def token_for(user) -> str:
    return Token.objects.get_or_create(user=user)[0].key


def sign_in(client, user):
    """Point an APIClient at this user for the rest of the test."""
    client.credentials(HTTP_AUTHORIZATION=f"Token {token_for(user)}")
    return user


class SchoolTestMixin:
    """
    One school, one teacher signed in, and the cast for the access tests.

    The names say what each person is for:

    * `user` — a teacher of this school, signed in by default;
    * `admin` — an administrator of the same school;
    * `colleague` — another plain teacher here, for "not mine" checks;
    * `stranger` / `alien_admin` — the same two roles in another school;
    * `outsider` — signed in, invited by nobody.
    """

    def setUp(self):
        super().setUp()
        self.school = make_school("Test school")
        self.alien_school = make_school("Another school")

        self.user = make_user(self.school, "teacher@example.com")
        self.admin = make_user(self.school, "admin@example.com", admin=True)
        self.colleague = make_user(self.school, "colleague@example.com")
        self.stranger = make_user(self.alien_school, "stranger@example.com")
        self.alien_admin = make_user(
            self.alien_school, "alien-admin@example.com", admin=True
        )
        self.outsider = make_user(None, "nobody@example.com")

        sign_in(self.client, self.user)

    def sign_in(self, user):
        return sign_in(self.client, user)
