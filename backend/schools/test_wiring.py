"""
Every API view is scoped, or is listed here as deliberately not.

The per-model matrix in `test_access.py` proves the rules hold for the models
somebody remembered to write tests for. It cannot prove anything about the
endpoint added next month whose test nobody wrote — and that is the failure
this project is actually exposed to: a new viewset that forgets its base
class answers happily to everyone, and no existing test turns red.

So this walks the URL configuration instead of the models. Every view under
/api/ has to either go through `config.access` or appear in EXEMPT with a
reason. Adding an endpoint therefore forces a decision, in a diff, in front
of a reviewer.
"""

from config.access import (
    IsSchoolAdmin,
    IsSchoolAdminForWrite,
    IsSchoolMember,
    IsSuperuser,
    SchoolScopedViewSet,
    TeacherScopedViewSet,
)
from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver

# Views that are open on purpose, and why. Anything here answers before the
# user is known to belong anywhere, so it must not touch school data.
EXEMPT = {
    "GoogleLoginView": "signing in: there is no user yet",
    "LogoutView": "signing out: only deletes the caller's own token",
    "MeView": "the caller's own profile, taken from the token, never from a URL",
    "APIRootView": (
        "DRF's router index: lists the endpoint URLs of a router and no data. "
        "Authenticated like everything else, and every URL it names is itself "
        "scoped — checked by this very test"
    ),
    "StatusView": (
        "onboarding status: deliberately answers a user with no school, "
        "so the interface can show them the right screen instead of a 403"
    ),
}

# The permission classes that count as "this view knows about schools".
SCOPING = (IsSchoolMember, IsSchoolAdmin, IsSchoolAdminForWrite, IsSuperuser)


def api_views(prefix="api/"):
    """Every view reachable under /api/, as (route, view class)."""

    def walk(patterns, route=""):
        for entry in patterns:
            here = route + str(entry.pattern)
            if isinstance(entry, URLResolver):
                yield from walk(entry.url_patterns, here)
            elif isinstance(entry, URLPattern):
                view = getattr(entry.callback, "cls", None)
                if view is not None:
                    yield here, view

    seen = {}
    for route, view in walk(get_resolver().url_patterns):
        if route.startswith(prefix):
            seen.setdefault(view.__name__, (route, view))
    return seen


class ApiWiringTests(SimpleTestCase):
    def test_the_walk_finds_the_endpoints(self):
        """A guard for the guard: a broken walk would pass everything."""
        found = api_views()

        self.assertGreater(len(found), 10, found)
        for expected in ("CourseViewSet", "LessonSlotViewSet", "PlanNodeViewSet"):
            self.assertIn(expected, found)

    def test_every_view_is_scoped_or_listed_as_exempt(self):
        unscoped = []

        for name, (route, view) in sorted(api_views().items()):
            if name in EXEMPT:
                continue
            if issubclass(view, (SchoolScopedViewSet, TeacherScopedViewSet)):
                continue
            if any(
                issubclass(permission, SCOPING)
                for permission in getattr(view, "permission_classes", [])
            ):
                continue
            unscoped.append(f"{name} ({route})")

        self.assertEqual(
            unscoped,
            [],
            "эти вьюхи не проходят через config.access и не перечислены в "
            "EXEMPT — добавьте базовый класс или запишите причину",
        )

    def test_exempt_views_still_exist(self):
        """A stale exemption is a hole that outlives the view it excused."""
        found = api_views()

        self.assertEqual(
            sorted(name for name in EXEMPT if name not in found),
            [],
            "в EXEMPT остались вьюхи, которых больше нет",
        )

    def test_school_scoped_viewsets_declare_a_path_to_the_school(self):
        """
        `school_path` is what the filter walks; a wrong one silently widens it.

        The default "school" is right for models holding the key themselves
        and wrong for anything hanging off a year, so it is checked against
        the model rather than trusted.
        """
        for name, (_, view) in sorted(api_views().items()):
            if not issubclass(view, SchoolScopedViewSet):
                continue

            with self.subTest(name):
                model = view.queryset.model
                complaint = f"{name}.school_path = {view.school_path!r}"

                for step in view.school_path.split("__"):
                    try:
                        field = model._meta.get_field(step)
                    except FieldDoesNotExist:
                        self.fail(f"{complaint}: у {model.__name__} нет поля {step!r}")
                    model = field.related_model
                    self.assertIsNotNone(model, f"{complaint}: {step!r} — не связь")

                self.assertEqual(
                    model.__name__, "School", f"{complaint} ведёт не в School"
                )

    def test_teacher_scoped_viewsets_point_at_a_user(self):
        for name, (_, view) in sorted(api_views().items()):
            if not issubclass(view, TeacherScopedViewSet):
                continue

            with self.subTest(name):
                field = view.queryset.model._meta.get_field(view.teacher_path)
                self.assertEqual(field.related_model.__name__, "User")
