from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from schedule.models import LessonSlot, SchoolClass

from . import services
from .models import PlanNode
from .serializers import (
    MoveSerializer,
    MoveToSerializer,
    PlanNodeCreateSerializer,
    PlanNodeUpdateSerializer,
    check_structure,
    flat_payload,
    layout_payload,
    tree_payload,
)


def read_date(value):
    """Дата из параметра запроса. Мусор — это None, а не 500."""
    try:
        return parse_date(value or "")
    except ValueError:
        # parse_date падает на «2026-13-45»: формат похож, даты не существует
        return None


def own_nodes(user):
    return PlanNode.objects.filter(school_class__owner=user).select_related(
        "school_class", "parent"
    )


def perform_move(node, data) -> Response:
    form = MoveSerializer(data=data)
    form.is_valid(raise_exception=True)

    with transaction.atomic():
        moved = services.move(node, form.validated_data["direction"])

    # False — узел упёрся в край дерева, это не ошибка
    return Response({"moved": moved})


class PlanNodeViewSet(viewsets.ModelViewSet):
    """
    Учебный план класса.

    Список отдаёт дерево целиком, а не плоский набор узлов: без порядка и
    вложенности он бесполезен.
    """

    def get_queryset(self):
        return own_nodes(self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return PlanNodeCreateSerializer
        return PlanNodeUpdateSerializer

    def requested_class(self):
        raw = self.request.query_params.get("class")
        if not raw or not raw.isdigit():
            raise ValidationError({"class": "Нужен параметр class с id класса."})

        return get_object_or_404(
            SchoolClass.objects.filter(owner=self.request.user), pk=raw
        )

    def list(self, request, *args, **kwargs):
        return Response(tree_payload(self.requested_class()))

    @action(detail=False, methods=["get"])
    def flat(self, request):
        """Только уроки, по порядку — последовательность для расписания."""
        return Response(flat_payload(self.requested_class()))

    def layout_entries(self, school_class):
        """Сопоставление плана и расписания. Запросы здесь, расчёт — в services."""
        slots = LessonSlot.objects.filter(
            school_class=school_class, is_cancelled=False
        ).order_by("date", "lesson_number")

        return services.build_layout(
            services.flatten_lessons(school_class), list(slots)
        )

    @action(detail=False, methods=["get"])
    def layout(self, request):
        """
        Раскладка целиком или за период.

        Период режет уже посчитанную раскладку: сопоставление всегда идёт по
        всему плану и всему расписанию, иначе номера поехали бы.
        """
        entries = self.layout_entries(self.requested_class())

        start, end = (read_date(request.query_params.get(name)) for name in ("from", "to"))
        if start or end:
            entries = [
                entry
                for entry in entries
                if entry.slot is not None
                and (start is None or entry.slot.date >= start)
                and (end is None or entry.slot.date <= end)
            ]

        return Response(layout_payload(entries))

    @action(detail=False, methods=["get"], url_path="layout/summary", url_name="layout-summary")
    def layout_summary(self, request):
        school_class = self.requested_class()
        cancelled = LessonSlot.objects.filter(
            school_class=school_class, is_cancelled=True
        ).count()

        return Response(
            services.layout_summary(
                self.layout_entries(school_class),
                today=timezone.localdate(),
                cancelled_count=cancelled,
            )
        )

    def destroy(self, request, *args, **kwargs):
        node = self.get_object()
        # по умолчанию бережём содержимое: уроки всплывают на верхний уровень
        keep_children = request.query_params.get("keep_children", "true").lower() not in (
            "false",
            "0",
        )

        with transaction.atomic():
            if node.is_section and keep_children:
                services.dissolve_section(node)
            else:
                school_class, parent_id = node.school_class, node.parent_id
                node.delete()
                services.reindex(school_class, parent_id)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """Шаг вверх или вниз: с заходом в папки и выходом из них."""
        return perform_move(self.get_object(), request.data)

    @action(detail=True, methods=["post"])
    def move_to(self, request, pk=None):
        """Явный перенос, когда пошаговое движение неудобно."""
        node = self.get_object()

        form = MoveToSerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        parent = form.validated_data["parent"]

        if parent is not None and parent.school_class_id != node.school_class_id:
            raise ValidationError({"parent": "Папка принадлежит другому классу."})
        check_structure(node, parent)

        with transaction.atomic():
            services.place(node, parent, form.validated_data["position"])

        return Response({"moved": True})


class SectionMoveView(APIView):
    """Перемещение папки целиком относительно соседей верхнего уровня."""

    def post(self, request, pk):
        section = get_object_or_404(own_nodes(request.user).filter(is_section=True), pk=pk)
        return perform_move(section, request.data)
