from config.access import IsSchoolAdmin, IsSchoolMember, IsTeacher
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

    Отсюда и права: `IsTeacher` **без** `IsSchoolMember`. Школы у учителя
    может ещё не быть, и объяснить это должен ответ, а не отказ; вид же
    известен всегда, и ученику здесь считать нечего — у него другая главная.
    """

    permission_classes = [IsAuthenticated, IsTeacher]

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

    permission_classes = [IsAuthenticated, IsSchoolMember, IsTeacher, IsSchoolAdmin]

    def post(self, request):
        with transaction.atomic():
            created = services.create_demo(request.user)

        return Response(
            {"created": created, "status": services.build_status(request.user)},
            status=201,
        )
