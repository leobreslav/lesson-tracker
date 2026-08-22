from config.access import IsSuperuser
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import Message
from .serializers import MessageSerializer


class WriteAnyoneReadSuperuser(IsSuperuser):
    """
    Писать может каждый вошедший, читать — только суперпользователь.

    Это единственная вьюха проекта с такой формой, и форма у неё такая
    потому, что разговор с разработчиком идёт **через** школы, а не внутри
    одной. Ученик пишет наравне с учителем: поломку он видит ту же, а сказать
    о ней ему было нечем.

    Чужие обращения при этом не видны никому, включая администратора школы:
    жалоба на интерфейс — не школьный документ, и «мой завуч прочитает, что я
    написал» отбивает желание писать вернее любого отказа.
    """

    def has_permission(self, request, view):
        if view.action == "create":
            return True
        return super().has_permission(request, view)


class FeedbackViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Сообщения разработчику: «сломалось» и «хорошо бы».

    Накопитель, а не переписка: ответить отсюда нельзя, и это сознательно.
    Отвечать на обращения означало бы завести вторую почту внутри школьного
    журнала — со своими уведомлениями, непрочитанным и ожиданием ответа,
    которого один человек на всех дать не может. Ответ приходит починкой.
    """

    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, WriteAnyoneReadSuperuser]
    http_method_names = ["get", "post", "head", "options"]
    queryset = Message.objects.select_related("author", "school")

    def get_queryset(self):
        rows = super().get_queryset()

        # `?handled=false` — то, что ещё не унесли в работу; список читают
        # именно так, а не «все за всё время»
        handled = self.request.query_params.get("handled")
        if handled == "false":
            rows = rows.filter(handled_at__isnull=True)
        elif handled == "true":
            rows = rows.filter(handled_at__isnull=False)

        kind = self.request.query_params.get("kind")
        if kind in dict(Message.Kind.choices):
            rows = rows.filter(kind=kind)

        return rows

    def perform_create(self, serializer):
        """
        Автор, школа и страница проставляются здесь, а не приходят телом.

        Иначе «от кого» становится полем формы, то есть тем, что можно
        подставить: сообщение с чужим адресом читалось бы как чужое.
        """
        message = serializer.save(
            author=self.request.user,
            school_id=self.request.user.school_id,
            page=(self.request.data.get("page") or "")[:200],
        )
        services.forward(message)

    @action(detail=True, methods=["post"])
    def handled(self, request, pk=None):
        """
        Отметка «разобрано» — и обратно тем же нажатием.

        Тем же приёмом, что отметка в журнале и вердикт в проверке работ:
        снять ошибочную отметку должно быть нечем иным, кроме как повторным
        нажатием, иначе список копит мусор, который нельзя убрать.
        """
        message = self.get_object()
        message.handled_at = None if message.handled_at else timezone.now()
        message.save(update_fields=["handled_at"])
        return Response(self.get_serializer(message).data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Сколько ждёт разбора — число для значка в баре у суперюзера."""
        return Response(
            {
                "waiting": Message.objects.filter(handled_at__isnull=True).count(),
                "forwarding": bool(request.user.forward_feedback),
            }
        )

