"""
Fixtures every app's tests need: a school, the people in it, and their work.

Since everything is scoped by school, almost every test starts the same way —
one school, one teacher, and usually a second person to prove they cannot see
the first one's work. Repeating that in each setUp invited copies that slowly
drifted apart, so it lives here.

The builders below keep the invariants the API enforces. A slot takes its year
from its course rather than accepting one, because a slot whose year differs
from its course's year is refused by the serializer (`slot_year_mismatch`) —
a fixture that can express it would be testing a state the product cannot
reach.
"""

from datetime import date

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from .models import School

User = get_user_model()

# the school year every test uses unless it needs its own dates
YEAR_START = date(2026, 9, 1)
YEAR_END = date(2027, 5, 31)
# the first full Monday inside it: the usual starting point for a week
MONDAY = date(2026, 9, 7)


# --- people ------------------------------------------------------------------


def make_school(name="Test school") -> School:
    return School.objects.create(name=name)


def make_user(school=None, email="teacher@example.com", *, admin=False, root=False):
    """
    A member of the school; `school=None` gives somebody nobody invited.

    `root` is a Django superuser — the only role that means anything outside
    a school, and only in the section that creates them.
    """
    return User.objects.create_user(
        email=email,
        school=school,
        is_school_admin=admin,
        is_superuser=root,
        is_staff=root,
    )


def token_for(user) -> str:
    return Token.objects.get_or_create(user=user)[0].key


def sign_in(client, user):
    """Point an APIClient at this user for the rest of the test."""
    client.credentials(HTTP_AUTHORIZATION=f"Token {token_for(user)}")
    return user


# --- what the school owns ----------------------------------------------------


def make_year(school, name="2026/2027", start=YEAR_START, end=YEAR_END):
    from calendars.models import SchoolYear

    return SchoolYear.objects.create(
        school=school, name=name, start_date=start, end_date=end
    )


def make_course(school, year=None, name="9Б"):
    """A course of the school. Without a year, one is made to hold it."""
    from schedule.models import Course

    return Course.objects.create(
        school=school, year=year or make_year(school), name=name
    )


def make_term(year, name="1 четверть", start=None, end=None):
    from calendars.models import Term

    return Term.objects.create(
        year=year,
        name=name,
        start_date=start or year.start_date,
        end_date=end or date(2026, 10, 25),
    )


def make_exception(year, day=date(2026, 11, 4), kind="holiday", title="Праздник"):
    from calendars.models import DayException

    return DayException.objects.create(
        year=year, start_date=day, end_date=day, kind=kind, title=title
    )


# --- what a teacher owns inside it -------------------------------------------


def make_slot(teacher, course, day=MONDAY, number=1, **flags):
    """One lesson. The year follows the course — never passed separately."""
    from schedule.models import LessonSlot

    return LessonSlot.objects.create(
        year=course.year,
        teacher=teacher,
        course=course,
        date=day,
        lesson_number=number,
        **flags,
    )


def make_node(teacher, course, title="Урок", *, parent=None, position=0, section=False):
    from plans.models import PlanNode

    return PlanNode.objects.create(
        teacher=teacher,
        course=course,
        parent=parent,
        position=position,
        is_section=section,
        title=title,
    )


class SchoolTestMixin:
    """
    One school, one teacher signed in, and the cast for the access tests.

    The names say what each person is for:

    * `user` — a teacher of this school, signed in by default;
    * `admin` — an administrator of the same school;
    * `colleague` — another plain teacher here, for "not mine" checks;
    * `stranger` / `alien_admin` — the same two roles in another school;
    * `outsider` — signed in, invited by nobody;
    * `root` — a Django superuser, built on demand by `make_root()`.
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

    def make_root(self, email="root@example.com", school=None):
        """A superuser. Not in the default cast — most tests do not need one."""
        return make_user(school if school is not None else self.school, email, root=True)
