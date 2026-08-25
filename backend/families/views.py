"""
Разделы родителя: его дети и их учителя.

Ученические экраны отдельных вьюх не потребовали — они те же самые, только
смотрят на ребёнка (`families.viewing.subject_of`). Здесь лежит то, чего у
ученика нет вовсе: список его детей.

Переписка отсюда ушла в `talks`: она оказалась не семейной вещью, а общей —
собеседник не меняет природы разговора.
"""

from config.access import IsParent, IsSchoolMember
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conversations
from .viewing import children_of


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
