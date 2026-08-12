"""
A way into the application for browser tests, and nothing else.

Signing in through Google cannot be driven from a headless browser, so the
e2e stack needs a door of its own. It is a door that must not exist anywhere
near production, so it is closed three times over:

* `E2E_TEST_LOGIN` is false unless the environment says otherwise, and the
  URLs are not even added to the routing table when it is off — a request to
  them gets an ordinary 404, with no hint that such a path was ever a thing;
* the views check the flag again at call time, so importing them by hand
  cannot help either;
* the reset endpoint runs `seed_demo`, which refuses to work with DEBUG off.

The production `.env.prod` never sets the flag, and `.env.prod.example` says
so out loud.
"""

from django.conf import settings
from django.core.management import call_command
from django.http import Http404
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User


def enabled() -> bool:
    return bool(getattr(settings, "E2E_TEST_LOGIN", False))


class E2EView(APIView):
    """Open to anyone — but only when the flag is on, and it never is."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        if not enabled():
            # 404 rather than 403: a closed door should look like no door
            raise Http404
        return super().initial(request, *args, **kwargs)


class TestLoginView(E2EView):
    """
    A token for an existing account, by email.

    Deliberately does not create anybody: the tests run against `seed_demo`
    data, and an endpoint that could invent users would be a second way to
    get into a school.
    """

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        user = User.objects.filter(email__iexact=email).first()

        if user is None:
            return Response({"detail": f"no such user: {email}"}, status=404)

        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "key": token.key,
                "email": user.email,
                "school": user.school_id,
                "is_school_admin": user.is_school_admin,
            }
        )


class TestResetView(E2EView):
    """
    Put the database back to the seeded state.

    Each test starts from here, so one test cannot leave the next one a
    surprise. `seed_demo --flush` is the same command a developer runs by
    hand, which keeps the fixtures the tests see and the fixtures a person
    sees identical.
    """

    def post(self, request):
        call_command("seed_demo", flush=True, verbosity=0)
        return Response({"reset": True})
