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

    Обратной кнопки нет намеренно. Раньше здесь был `DELETE`, сносивший
    **все** данные вызывающего, а у администратора — ещё и год со всеми
    курсами школы. Одно нажатие на главной, и год работы коллег держался
    только на `PROTECT`; ради разового «убрать пример» это слишком дорого.
    Демо разбирается теми же экранами, что и настоящие данные, а на снос
    года есть отдельный экран, который считает цену заранее.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsSchoolAdmin]

    def post(self, request):
        with transaction.atomic():
            created = services.create_demo(request.user)

        return Response(
            {"created": created, "status": services.build_status(request.user)},
            status=201,
        )
