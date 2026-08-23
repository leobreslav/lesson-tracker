"""
Разделы родителя: его дети, собеседники и разговоры.

Ученические экраны отдельных вьюх не потребовали — они те же самые, только
смотрят на ребёнка (`families.viewing.subject_of`). Здесь лежит то, чего у
ученика нет вовсе: список детей и переписка с учителем.
"""

from config.access import IsParent, IsParentOrTeacher, IsSchoolMember
from config.errors import Codes, api_error
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conversations
from .models import FamilyThread
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


class FamilyThreadsView(APIView):
    """
    Разговоры: список у обеих сторон, заведение — у родителя.

    Одна вьюха на учителя и родителя намеренно: вопрос «мои разговоры» у них
    один и тот же, а отвечает на него участие, а не вид. Разъехавшись на две,
    они разошлись бы в первой же правке — так уже было с выборками курсов.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember, IsParentOrTeacher]

    def get(self, request):
        return Response(
            {
                "threads": [
                    conversations.payload(thread, unread_for=request.user)
                    for thread in conversations.threads_of(request.user)
                ]
            }
        )

    def post(self, request):
        """Начать разговор — право родителя: он выбирает, к кому обратиться."""
        if not request.user.is_parent:
            api_error(
                Codes.PARENTS_ONLY,
                "Only a parent starts a conversation.",
            )

        from accounts.models import User

        child = get_object_or_404(User, pk=request.data.get("child"))
        teacher = get_object_or_404(User, pk=request.data.get("teacher"))
        thread = conversations.open_thread(
            parent=request.user, teacher=teacher, child=child
        )
        if request.data.get("text"):
            conversations.say(
                thread, author=request.user, text=request.data["text"]
            )
        thread.refresh_from_db()
        return Response(conversations.payload(thread, unread_for=request.user))


class FamilyThreadView(APIView):
    """Один разговор: прочитать и ответить. Право — по участию."""

    permission_classes = [IsAuthenticated, IsSchoolMember, IsParentOrTeacher]

    def get(self, request, pk):
        thread = get_object_or_404(
            FamilyThread.objects.select_related("parent", "teacher", "child"), pk=pk
        )
        conversations.refuse_unless_allowed(request.user, thread)
        return Response(conversations.payload(thread, unread_for=request.user))

    def post(self, request, pk):
        thread = get_object_or_404(
            FamilyThread.objects.select_related("parent", "teacher", "child"), pk=pk
        )
        conversations.refuse_unless_allowed(request.user, thread)
        conversations.say(
            thread, author=request.user, text=request.data.get("text", "")
        )
        thread.refresh_from_db()
        return Response(conversations.payload(thread, unread_for=request.user))


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
