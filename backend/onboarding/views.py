from config.access import IsSchoolAdmin, IsSchoolMember
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class StatusView(APIView):
    """
    What is filled in already: the main page builds its steps from this.

    Deliberately open to a user with no school — the answer simply says so,
    and the interface shows the "ask your administrator" screen instead of
    guessing from a 403.
    """

    def get(self, request):
        return Response(services.build_status(request.user))


class DemoView(APIView):
    """
    Demo data: the "this is what a filled-in tracker looks like" set.

    Administrators only, because the year and the courses it creates belong
    to the school. The lessons and the plan inside are the caller's own.

    Deleting removes the caller's lessons and plan, and — for an
    administrator — the school's year and courses with them. A course another
    teacher already works in refuses to go, which is the point of PROTECT.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsSchoolAdmin]

    def post(self, request):
        with transaction.atomic():
            created = services.create_demo(request.user)

        return Response(
            {"created": created, "status": services.build_status(request.user)},
            status=201,
        )

    def delete(self, request):
        with transaction.atomic():
            removed = services.wipe(request.user)

        return Response(
            {"removed": removed, "status": services.build_status(request.user)}
        )
