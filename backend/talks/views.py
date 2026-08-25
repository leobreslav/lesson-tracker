"""
Две двери на один мессенджер: список собеседников и один разговор.

**Одна дверь на все виды пользователей**, и это то же решение, что у
просмотрщика снимков: учитель, ученик и родитель спрашивают здесь одно и то
же — «с кем я говорил и что мне сказали». Вопрос тут «ваш ли это разговор», а
не «кто вы по виду», и отвечает на него `talks.access`: собеседники считаются
от спрашивающего, а чужой разговор не читается никем, включая администратора
школы.
"""

from accounts.models import User
from config.access import IsSchoolMember
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class TalksView(APIView):
    """С кем говорили и кому можно написать."""

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get(self, request):
        return Response(services.ribbon(request.user))


class TalkView(APIView):
    """
    Один разговор — адресуется **человеком**, а не номером разговора.

    Так его и держат в голове: «переписка с Ивановой», а не «тред 47». К тому
    же разговоров с одним человеком бывает два (о разных детях), а лента у них
    одна: собеседник один, и делить её было бы враньём о том, как это
    выглядит.
    """

    permission_classes = [IsAuthenticated, IsSchoolMember]

    def get(self, request, person):
        other = self._person(request, person)
        return Response(services.conversation(request.user, other))

    def post(self, request, person):
        other = self._person(request, person)
        child = request.data.get("child")
        services.say(
            request.user,
            other,
            text=request.data.get("text", ""),
            child=(
                get_object_or_404(
                    User.objects.filter(school_id=request.user.school_id), pk=child
                )
                if child
                else None
            ),
        )
        return Response(services.conversation(request.user, other))

    def _person(self, request, person):
        """
        Собеседник — из своей школы, иначе 404.

        Чужая школа не «нельзя», а «нет такого»: знать, что человек
        существует, постороннему незачем. А «есть ли вам о чём говорить»
        спрашивается дальше, в `access`, и отвечает уже отказом с причиной.
        """
        return get_object_or_404(
            User.objects.filter(school_id=request.user.school_id), pk=person
        )
