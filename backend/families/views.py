"""
Разделы родителя: его дети и их учителя.

Ученические экраны отдельных вьюх не потребовали — они те же самые, только
смотрят на ребёнка (`families.viewing.subject_of`). Здесь лежит то, чего у
ученика нет вовсе: список его детей.

Переписка отсюда ушла в `talks`: она оказалась не семейной вещью, а общей —
собеседник не меняет природы разговора.
"""

from config.access import IsParent, IsSchoolMember, SchoolScopedViewSet
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conversations
from .models import Guardianship
from .serializers import GuardianshipSerializer
from .viewing import children_of


class GuardianshipViewSet(SchoolScopedViewSet):
    """
    Родство глазами школы: администратор связывает и снимает, все читают.

    Стоит под `/api/school/`, а не под `/api/family/`: спрашивает тут не
    родитель про своих детей, а школа про свои пары. Школа у пары — школа
    ребёнка; родитель в той же, это проверяет `link`.

    Снятие **удаляет** строку, в отличие от зачисления: «бывшее родство» —
    не состояние, о котором кто-то спросит (см. модель).
    """

    serializer_class = GuardianshipSerializer
    queryset = Guardianship.objects.select_related("parent", "child")
    school_path = "child__school"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        child = self.request.query_params.get("child")
        if child:
            queryset = queryset.filter(child_id=child) if child.isdigit() else queryset.none()
        return queryset


class ChildrenView(APIView):
    """
    Дети этого родителя. С них начинается его интерфейс.

    Отдаётся и тогда, когда ребёнок один: экран решает по числу, показывать
    ли выбор, и «сколько их» — не то, о чём он должен догадываться.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsParent]

    def get(self, request):
        return Response(
            {
                "children": [
                    {
                        "id": child.pk,
                        "name": " ".join(
                            filter(None, (child.first_name, child.last_name))
                        )
                        or child.email,
                        "email": child.email,
                    }
                    for child in children_of(request.user)
                ]
            }
        )


class ChildTeachersView(APIView):
    """Кому родитель может написать про этого ребёнка."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsParent]

    def get(self, request):
        from .viewing import subject_of

        child = subject_of(request)
        return Response(
            {
                "child": child.pk,
                "teachers": [
                    {
                        "id": teacher.pk,
                        "name": " ".join(
                            filter(None, (teacher.first_name, teacher.last_name))
                        )
                        or teacher.email,
                    }
                    for teacher in conversations.teachers_for(child)
                ],
            }
        )
