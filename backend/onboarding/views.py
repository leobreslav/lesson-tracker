from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class StatusView(APIView):
    """Что уже заполнено: главная строит по этому ответу список шагов."""

    def get(self, request):
        return Response(services.build_status(request.user))


class DemoView(APIView):
    """
    Демо-данные: комплект «как это выглядит заполненным».

    Удаление сносит вообще все данные пользователя, а не только созданные
    примером: помечать демо-объекты флагом ради этого не стоит — на первом
    входе других данных всё равно нет, а подтверждение спрашивает интерфейс.
    """

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
